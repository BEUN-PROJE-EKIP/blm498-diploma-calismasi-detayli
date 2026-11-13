// YayimDamga — Gazebo sunucu sürecinde çalışan damga bileşeni (kalıcı hâl; B7, FR-23).
// Her araç kamerası karesi için bir `kare_olay` kaydı yazar (planlama/sozlesmeler.md §8.3): kaynak "gazebo_damga", olay "uretim", araç kimliği,
// simülasyon damgası (görüntü iletisinin header.stamp'i, ns), kare numarası n (damga ızgaraya tam oturuyorsa n = hz·t_sim, aksi halde "izgara_disi";
// yuvarlama yok) ve üretim anının CLOCK_MONOTONIC zamanı (ns).
// Üretim anı = sunucu süreci içinde, aynı görüntü konusuna süreç içi gz-transport aboneliğinin geri çağrısında okunan zaman (kararlar: kare yayımlanma anı).
// Araç kimliği: görüntü konusunun ait olduğu EN ÜST model adı `<model_onek><örnek>` biçimindeyse, `arac_kimlikleri` listesinin <örnek>. değeri
// (PX4: <model>_<örnek>, UAV_SYS_IDS sırası); eşleşmeyen kamera kaydedilmez, sayaçla günlüğe uyarı yazılır.
// SDF parametreleri: <cikti_yolu> (tam dosya yolu), <hz> (CAM_RATE_HZ), <model_onek>, <arac_kimlikleri> (boşlukla ayrılmış).
// Kayıt: bellekte arabellek; ayrı yazıcı iş parçacığı 1 sn'de bir dosyaya boşaltır, kapanışta (SIGTERM) son boşaltma yapılır. SIGKILL'de son ≤ 1 sn kaybolabilir.
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <fstream>
#include <memory>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <gz/common/Console.hh>
#include <gz/msgs/image.pb.h>
#include <gz/plugin/Register.hh>
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
  int arac;          // araç kimliği (UAV_SYS_IDS değeri)
  int64_t damga_ns;  // header.stamp (ns)
  int64_t mono_ns;   // CLOCK_MONOTONIC (ns)
};

class Yayim : public gz::sim::System, public gz::sim::ISystemConfigure, public gz::sim::ISystemPreUpdate
{
public:
  ~Yayim() override { Kapat(); }

  void Configure(const gz::sim::Entity &, const std::shared_ptr<const sdf::Element> &_sdf,
                 gz::sim::EntityComponentManager &, gz::sim::EventManager &) override
  {
    yol_ = _sdf->Get<std::string>("cikti_yolu", "gazebo_damga.jsonl").first;
    hz_ = _sdf->Get<double>("hz", 2.0).first;
    onek_ = _sdf->Get<std::string>("model_onek", "").first;
    std::istringstream is(_sdf->Get<std::string>("arac_kimlikleri", "").first);
    int k;
    while (is >> k) kimlikler_.push_back(k);
    arabellek_.reserve(1 << 16);
    dosya_.open(yol_, std::ios::out | std::ios::trunc);
    if (!dosya_) gzerr << "[YayimDamga] kayıt dosyası açılamadı: " << yol_ << std::endl;
    yazici_ = std::thread([this] { Yaz(); });
    gzmsg << "[YayimDamga] cikti=" << yol_ << " hz=" << hz_ << " model_onek=" << onek_ << " arac_sayisi=" << kimlikler_.size() << std::endl;
  }

  void PreUpdate(const gz::sim::UpdateInfo &, gz::sim::EntityComponentManager &_ecm) override
  {
    // Kamera algılayıcılarını ECM'den bul (araçlar çalışma sırasında eklenir); konu algılayıcı hazır olunca belli olur.
    _ecm.Each<gz::sim::components::Camera, gz::sim::components::Name>(
      [&](const gz::sim::Entity &e, const gz::sim::components::Camera *, const gz::sim::components::Name *) -> bool
      {
        if (bilinen_.count(e)) return true;
        gz::sim::Sensor s(e);
        auto konu = s.Topic(_ecm);
        if (!konu) return true;
        bilinen_.insert(e);
        auto ust = gz::sim::topLevelModel(e, _ecm);
        auto ad = _ecm.Component<gz::sim::components::Name>(ust);
        const std::string model = ad ? ad->Data() : std::string();
        int arac = -1;
        if (!onek_.empty() && model.rfind(onek_, 0) == 0)
        {
          const std::string sayi = model.substr(onek_.size());
          if (!sayi.empty() && sayi.find_first_not_of("0123456789") == std::string::npos)
          {
            const size_t i = static_cast<size_t>(std::stoul(sayi));
            if (i < kimlikler_.size()) arac = kimlikler_[i];
          }
        }
        if (arac < 0)
        {
          ++eslesmeyen_;
          gzwarn << "[YayimDamga] kamera araç kimliğine eşlenemedi, KAYDEDİLMEYECEK: model=" << model << " konu=" << *konu
                 << " (eşleşmeyen kamera sayısı=" << eslesmeyen_ << ")" << std::endl;
          return true;
        }
        auto cb = [this, arac](const gz::msgs::Image &m)
        {
          const int64_t w = MonotonikNs();   // üretim anı: süreç içi abonenin geri çağrısı
          const int64_t ns = static_cast<int64_t>(m.header().stamp().sec()) * 1000000000LL + m.header().stamp().nsec();
          Ekle({arac, ns, w});
        };
        if (!node_.Subscribe<gz::msgs::Image>(*konu, cb)) gzerr << "[YayimDamga] abonelik kurulamadı: " << *konu << std::endl;
        else gzmsg << "[YayimDamga] kamera bulundu: model=" << model << " arac_kimligi=" << arac << " konu=" << *konu << std::endl;
        return true;
      });
  }

private:
  void Ekle(const Kayit &r)
  {
    std::lock_guard<std::mutex> g(kilit_);
    arabellek_.push_back(r);
  }

  void Yaz()
  {
    std::vector<Kayit> yerel;
    yerel.reserve(1 << 12);
    while (true)
    {
      {
        std::unique_lock<std::mutex> g(kilit_);
        cv_.wait_for(g, std::chrono::seconds(1), [this] { return dur_; });
        yerel.swap(arabellek_);
      }
      for (const auto &r : yerel)
      {
        // Izgara: n = hz·t, damga ızgaraya tam oturuyorsa; yuvarlama yok.
        std::string n = "\"izgara_disi\"";
        if (hz_ > 0 && hz_ == static_cast<double>(static_cast<int64_t>(hz_)))
        {
          const int64_t h = static_cast<int64_t>(hz_);
          if ((r.damga_ns * h) % 1000000000LL == 0) n = std::to_string(r.damga_ns * h / 1000000000LL);
        }
        dosya_ << "{\"surum\": 1, \"tur\": \"kare_olay\", \"kaynak\": \"gazebo_damga\", \"arac_kimligi\": " << r.arac << ", \"n\": " << n
               << ", \"sim_damga_ns\": " << r.damga_ns << ", \"olay\": \"uretim\", \"mono_ns\": " << r.mono_ns << "}\n";
        ++yazilan_;
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
    gzmsg << "[YayimDamga] kapanış: yazılan kayıt=" << yazilan_ << " eşleşmeyen kamera=" << eslesmeyen_ << std::endl;
  }

  gz::transport::Node node_;
  std::vector<int> kimlikler_;
  std::set<gz::sim::Entity> bilinen_;
  std::vector<Kayit> arabellek_;
  std::mutex kilit_;
  std::condition_variable cv_;
  std::thread yazici_;
  std::ofstream dosya_;
  std::string yol_, onek_;
  double hz_ = 2.0;
  bool dur_ = false;
  size_t eslesmeyen_ = 0;
  size_t yazilan_ = 0;
};
}  // namespace yayim

GZ_ADD_PLUGIN(yayim::Yayim, gz::sim::System, yayim::Yayim::ISystemConfigure, yayim::Yayim::ISystemPreUpdate)
GZ_ADD_PLUGIN_ALIAS(yayim::Yayim, "yayim::YayimDamga")
