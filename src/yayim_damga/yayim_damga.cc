// YayimDamga — Gazebo sunucu sürecinde çalışan keşif amaçlı damga bileşeni (kare yayımlanma anı, FR-23).
// Her kamera karesi için bir satır yazar: yöntem, araç/kamera kimliği, header.stamp (ns), CLOCK_MONOTONIC (ns), kare numarası.
// Yöntemler (SDF <yontem> ile seçilir, virgülle ayrılmış birden çok olabilir):
//   abone : sunucu süreci içinde, aynı görüntü konusuna gz-transport ile süreç içi abone (header.stamp mesajdan okunur)
//   bilgi : aynı algılayıcının camera_info konusuna süreç içi abone (algılayıcı görüntüyle birlikte yayımlar; header.stamp mesajdan)
//   kare  : gz-rendering kamerasının "yeni görüntü karesi" olayı (header.stamp, o anki simülasyon zamanından türetilir)
// Kayıt: bellekte ön ayrılmış arabellek; ayrı bir yazıcı iş parçacığı 1 sn'de bir dosyaya boşaltır, kapanışta son boşaltma yapılır.
// Kayıt biçimi geçicidir (keşif).
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <fstream>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <gz/common/Console.hh>
#include <gz/msgs/camera_info.pb.h>
#include <gz/msgs/image.pb.h>
#include <gz/plugin/Register.hh>
#include <gz/rendering/Camera.hh>
#include <gz/rendering/RenderEngine.hh>
#include <gz/rendering/RenderingIface.hh>
#include <gz/rendering/Scene.hh>
#include <gz/sim/Entity.hh>
#include <gz/sim/EntityComponentManager.hh>
#include <gz/sim/Sensor.hh>
#include <gz/sim/System.hh>
#include <gz/sim/Util.hh>
#include <gz/sim/components/Camera.hh>
#include <gz/sim/components/Name.hh>
#include <gz/transport/Node.hh>

#include "saat.hh"

namespace yayim
{
struct Kayit
{
  const char *yontem;      // sabit dizge göstergesi
  int kamera;              // kameralar_ dizin numarası
  int64_t damga_ns;        // header.stamp (ns)
  int64_t mono_ns;
  int64_t sim_ns;          // kare yöntemi için PreUpdate'te okunan sim zamanı; abone için damga ile aynı
};

class Yayim : public gz::sim::System,
              public gz::sim::ISystemConfigure,
              public gz::sim::ISystemPreUpdate
{
public:
  ~Yayim() override { Kapat(); }

  void Configure(const gz::sim::Entity &, const std::shared_ptr<const sdf::Element> &_sdf,
                 gz::sim::EntityComponentManager &, gz::sim::EventManager &) override
  {
    std::string yontem = _sdf->Get<std::string>("yontem", "abone,kare").first;
    dizin_ = _sdf->Get<std::string>("cikti_dizini", ".").first;
    hz_ = _sdf->Get<double>("hz", 2.0).first;
    motor_ = _sdf->Get<std::string>("render_engine", "ogre2").first;
    abone_ = yontem.find("abone") != std::string::npos;
    bilgi_ = yontem.find("bilgi") != std::string::npos;
    kare_ = yontem.find("kare") != std::string::npos;
    arabellek_.reserve(1 << 20);
    dosya_.open(dizin_ + "/yayim_damga.csv", std::ios::out | std::ios::trunc);
    dosya_ << "yontem,kimlik,konu,damga_ns,mono_ns,sim_ns,n\n";
    dosya_.flush();
    yazici_ = std::thread([this] { Yaz(); });
    gzmsg << "[YayimDamga] yontem=" << yontem << " cikti=" << dizin_ << " hz=" << hz_ << std::endl;
  }

  void PreUpdate(const gz::sim::UpdateInfo &_info, gz::sim::EntityComponentManager &_ecm) override
  {
    sim_ns_.store(std::chrono::duration_cast<std::chrono::nanoseconds>(_info.simTime).count());
    if (bagli_ >= toplam_ && toplam_ > 0 && !yeniden_) return;
    // Kamera algılayıcılarını ECM'den bul; kimlik = en üst düzey model adı, konu = algılayıcı konusu.
    _ecm.Each<gz::sim::components::Camera, gz::sim::components::Name>(
      [&](const gz::sim::Entity &e, const gz::sim::components::Camera *, const gz::sim::components::Name *) -> bool
      {
        if (bilinen_.count(e)) return true;
        gz::sim::Sensor s(e);
        auto konu = s.Topic(_ecm);
        if (!konu) return true;
        Kamera k;
        k.konu = *konu;
        k.kapsamli = gz::sim::removeParentScope(gz::sim::scopedName(e, _ecm, "::", false), "::");
        auto ust = gz::sim::topLevelModel(e, _ecm);
        auto ad = _ecm.Component<gz::sim::components::Name>(ust);
        k.kimlik = ad ? ad->Data() : k.kapsamli;
        kameralar_.push_back(k);
        bilinen_.insert(e);
        toplam_ = kameralar_.size();
        if (abone_) AboneOl(static_cast<int>(kameralar_.size()) - 1);
        if (bilgi_) BilgiAboneOl(static_cast<int>(kameralar_.size()) - 1);
        gzmsg << "[YayimDamga] kamera bulundu: kimlik=" << k.kimlik << " konu=" << k.konu << " kapsamli_ad=" << k.kapsamli << std::endl;
        return true;
      });
    if (kare_) KareBagla();
  }

private:
  struct Kamera
  {
    std::string konu, kimlik, kapsamli;
    bool kare_bagli = false;
    gz::common::ConnectionPtr baglanti;
  };

  void AboneOl(int idx)
  {
    const std::string konu = kameralar_[idx].konu;
    auto cb = [this, idx](const gz::msgs::Image &m)
    {
      const int64_t w = MonotonikNs();
      const int64_t ns = static_cast<int64_t>(m.header().stamp().sec()) * 1000000000LL + m.header().stamp().nsec();
      Ekle({"abone", idx, ns, w, ns});
    };
    if (!node_.Subscribe<gz::msgs::Image>(konu, cb)) gzerr << "[YayimDamga] abonelik kurulamadı: " << konu << std::endl;
  }

  void BilgiAboneOl(int idx)
  {
    // Bilgi konusu: görüntü konusunun son parçası atılıp /camera_info eklenir (algılayıcının varsayılanı).
    std::string konu = kameralar_[idx].konu;
    const auto p = konu.rfind('/');
    konu = (p == std::string::npos ? konu : konu.substr(0, p)) + "/camera_info";
    auto cb = [this, idx](const gz::msgs::CameraInfo &m)
    {
      const int64_t w = MonotonikNs();
      const int64_t ns = static_cast<int64_t>(m.header().stamp().sec()) * 1000000000LL + m.header().stamp().nsec();
      Ekle({"bilgi", idx, ns, w, ns});
    };
    if (!node_.Subscribe<gz::msgs::CameraInfo>(konu, cb)) gzerr << "[YayimDamga] abonelik kurulamadı: " << konu << std::endl;
    else gzmsg << "[YayimDamga] bilgi konusuna abone: " << konu << std::endl;
  }

  void KareBagla()
  {
    // sceneFromFirstRenderEngine() bu süreçte motoru bulamadığı için (kayıt defteri boş görünüyor) motor adıyla aranır;
    // motor yüklü değilse yenisi YÜKLENMEZ (yalnızca Sensors sistemi yükler).
    if (!gz::rendering::isEngineLoaded(motor_)) {
      if (++motor_bekleme_ % 250 == 1) {
        std::string l;
        for (const auto &a : gz::rendering::loadedEngines()) l += a + " ";
        gzmsg << "[YayimDamga] motor '" << motor_ << "' yüklü değil; yüklü motorlar: [" << l << "]" << std::endl;
      }
      return;
    }
    auto *motor = gz::rendering::engine(motor_);
    if (!motor || motor->SceneCount() == 0) return;
    auto scene = motor->SceneByIndex(0);
    if (!scene) return;
    size_t bagli = 0;
    for (size_t i = 0; i < kameralar_.size(); ++i)
    {
      auto &k = kameralar_[i];
      if (k.kare_bagli) { ++bagli; continue; }
      auto dugum = scene->NodeByName(k.kapsamli);
      auto kam = std::dynamic_pointer_cast<gz::rendering::Camera>(dugum);
      if (!kam) continue;
      const int idx = static_cast<int>(i);
      k.baglanti = kam->ConnectNewImageFrame(
        [this, idx](const void *, unsigned int, unsigned int, unsigned int, const std::string &)
        {
          const int64_t w = MonotonikNs();
          const int64_t sim = sim_ns_.load();
          if (kare_sayac_.fetch_add(1) == 0) gzmsg << "[YayimDamga] ilk kare olayı alındı" << std::endl;
          Ekle({"kare", idx, sim, w, sim});
        });
      k.kare_bagli = true;
      ++bagli;
      gzmsg << "[YayimDamga] kare olayına bağlandı: " << k.kapsamli << std::endl;
    }
    bagli_ = bagli;
    if (bagli_ < kameralar_.size() && !uyari_) {
      uyari_ = true;
      gzwarn << "[YayimDamga] kare olayı: bazı kameralar sahnede bulunamadı (kapsamlı ad eşleşmedi)" << std::endl;
    }
  }

  void Ekle(const Kayit &r)
  {
    std::lock_guard<std::mutex> g(kilit_);
    arabellek_.push_back(r);
  }

  void Yaz()
  {
    std::vector<Kayit> yerel;
    yerel.reserve(1 << 16);
    while (true)
    {
      {
        std::unique_lock<std::mutex> g(kilit_);
        cv_.wait_for(g, std::chrono::seconds(1), [this] { return dur_; });
        yerel.swap(arabellek_);
      }
      for (const auto &r : yerel)
      {
        // Izgara: n = t·hz, damga ızgaraya tam oturuyorsa; yuvarlama yok.
        std::string n = "izgara_disi";
        const double hz = hz_;
        if (hz > 0 && hz == static_cast<double>(static_cast<int64_t>(hz)))
        {
          const int64_t h = static_cast<int64_t>(hz);
          if ((r.damga_ns * h) % 1000000000LL == 0) n = std::to_string(r.damga_ns * h / 1000000000LL);
        }
        const auto &k = kameralar_[r.kamera];
        dosya_ << r.yontem << ',' << k.kimlik << ',' << k.konu << ',' << r.damga_ns << ',' << r.mono_ns << ',' << r.sim_ns << ',' << n << '\n';
      }
      dosya_.flush();
      yerel.clear();
      std::lock_guard<std::mutex> g(kilit_);
      if (dur_ && arabellek_.empty()) break;
    }
  }

  void Kapat()
  {
    {
      std::lock_guard<std::mutex> g(kilit_);
      if (dur_) return;
      dur_ = true;
    }
    cv_.notify_all();
    if (yazici_.joinable()) yazici_.join();
  }

  gz::transport::Node node_;
  std::vector<Kamera> kameralar_;
  std::set<gz::sim::Entity> bilinen_;
  std::vector<Kayit> arabellek_;
  std::mutex kilit_;
  std::condition_variable cv_;
  std::thread yazici_;
  std::ofstream dosya_;
  std::string dizin_, motor_;
  int motor_bekleme_ = 0;
  double hz_ = 2.0;
  bool abone_ = false, bilgi_ = false, kare_ = false, uyari_ = false, yeniden_ = false, dur_ = false;
  size_t bagli_ = 0, toplam_ = 0;
  std::atomic<int64_t> sim_ns_{0};
  std::atomic<int64_t> kare_sayac_{0};
};
}  // namespace yayim

GZ_ADD_PLUGIN(yayim::Yayim, gz::sim::System, yayim::Yayim::ISystemConfigure, yayim::Yayim::ISystemPreUpdate)
GZ_ADD_PLUGIN_ALIAS(yayim::Yayim, "yayim::YayimDamga")
