# Afet Bölgelerinde Haberleşme Altyapısından Bağımsız Olarak Çalışabilen Uçta Yapay Zekâ Destekli İHA Sürüsü

**[Sistem Gereksinimleri](#sistem-gereksinimleri) · [Kurulum öncesinde yapılması gerekenler](#kurulum-öncesinde-yapılması-gerekenler) · [Kurulum](#kurulum) · [Kurulum sonrası yapılması gerekenler](#kurulum-sonrası-yapılması-gerekenler) · [Tamamlanma Yüzdesi](#tamamlanma-yüzdesi) · [Klasörler](#klasörler)**

---

## Sistem Gereksinimleri

| Gerekli | Ne olmalı? |
|---|---|
| İşlemci | En az 12 mantıksal işlemci (thread) |
| Bellek (RAM) | En az 28 GB (32 GB önerilir) |
| Disk | En az 100 GB boş alan |
| Ekran kartı | NVIDIA, en az 12 GB bellek önerilir (RTX 5070 ile denendi) |
| İşletim sistemi | **Kubuntu 24.04.5 LTS**, kurulum dili **İngilizce** |
| Diğer | İnternet bağlantısı (Kubuntu kurulumundan sonra) ve yönetici (sudo) şifresi |

Kurulum betiği başlamadan önce bunları kendisi de kontrol eder. Eksik bir şey varsa **hiçbir şey kurmadan durur** ve neyin eksik olduğunu yazar.

**Denenen sistem:** AMD Ryzen 9 7950X, NVIDIA RTX 5070, sürücü 595.99.02. Başka makineler henüz denenmedi. Ayrıca Ubuntu paketlerinin (ROS 2, Gazebo vb.) sürümleri sabitlenmiş değildir; başka bir tarihte yapılan kurulumda sürümler farklı çıkabilir.

---

## Kurulum öncesinde yapılması gerekenler

Adımlar bu sırayla, eksiksiz yapılır. Komutlar **Konsole**'da çalıştırılır (başlat menüsünde "Konsole" yaz).

<details>
<summary><b>Adım 1 — Kubuntu'yu kur</b></summary>

1. **Kubuntu 24.04.5 LTS** sürümünü [kubuntu.org/getkubuntu](https://kubuntu.org/getkubuntu/) adresinden indir ve bir USB belleğe yaz. Başka sürümler çalışmaz.
2. Kurulum sırasında dil olarak **English** seç. Türkçe seçme, betikler İngilizce sistem bekler. (Klavye düzenini istersen Türkçe yapabilirsin, bu dili etkilemez.)
3. Kurulum türü olarak **Normal installation** seç (web tarayıcısı, ofis programları vb. dahil olan tam kurulum). **Minimal installation** seçme.
4. > **Önemli:** Kurulum boyunca bilgisayar **internete bağlı olmasın** (ağ kablosunu çıkar, Wi-Fi'ye bağlanma). Biz kurulumu internetsiz yaptık, test ettiğimiz yol budur. İnternete kurulum bittikten sonra bağlanacaksın.
5. Kurulum bitince bilgisayarı yeniden başlat, **Konsole**'u aç, internete bağlan ve şu iki komutla kontrol et:

```bash
lsb_release -d
echo $LANG
```

Ekranda `Ubuntu 24.04.5 LTS` ve `en_US.UTF-8` görmelisin.

</details>

<details>
<summary><b>Adım 2 — Sistemi güncelle</b></summary>

İnternete bağlıyken şunu çalıştır (birkaç dakika sürebilir):

```bash
sudo apt update && sudo apt full-upgrade -y
```

Şifre sorarsa yönetici şifreni yaz. Yazarken ekranda hiçbir şey görünmez, bu normaldir.

</details>

<details>
<summary><b>Adım 3 — NVIDIA sürücüsünü kur</b></summary>

Kurulum betiklerimiz ekran kartı sürücüsüne **dokunmaz**, yalnızca doğru kurulu mu diye bakar. Sürücüyü sen kuracaksın:

```bash
sudo apt install -y build-essential dkms linux-headers-$(uname -r)
sudo apt install -y nvidia-driver-595-open
sudo reboot
```

Bilgisayar yeniden açılınca kontrol et:

```bash
nvidia-smi
```

Tablonun en üstünde sürücü sürümünü ve `CUDA Version: 13.2` (veya daha büyük) görmelisin. Biz `595.99.02` sürümüyle denedik. Olmuyorsa aşağıdaki [Sorun mu var?](#sorun-mu-var) bölümüne bak.

</details>

<details>
<summary><b>Adım 4 — Git'i kur</b></summary>

Projeyi indirmek için gerekli:

```bash
sudo apt install -y git
```

</details>

---

## Kurulum

Hepsi **Konsole**'da yapılır. Komutları kutudan kopyalayıp yapıştır, Enter'a bas.

**1. Projeyi indir**

```bash
cd ~
git clone https://github.com/omerfarukguner/blm498-diploma-calismasi.git
cd blm498-diploma-calismasi
```

**2. Kurulumu başlat**

```bash
./setup/install_all.sh
```

- Önce bilgisayarını kontrol eder. Sorun yoksa **sudo şifreni bir kez** sorar.
- Sonra ROS 2, Gazebo, PX4 ve yapay zekâ araçlarını indirip kurar. İnternet hızına göre **15 ile 60 dakika** sürer. Konsole'u kapatma, bilgisayarı uyutma.
- Ekranda satır başlarında şu işaretleri göreceksin:

| İşaret | Anlamı |
|---|---|
| `(+)` | Başarılı |
| `(-)` | Hata |
| `(!)` | Uyarı |
| `(i)` | Bilgi |

- Yarıda durdurmak istersen `Ctrl + C` bas. Sonra aynı komutu tekrar çalıştırırsan kaldığı yerden devam eder.
- Kurulum bitince son satırlarda başarıyla bittiğini görmelisin. Kurulumun kısa bir raporu `.generated/kurulum_raporu.md` dosyasına yazılır.

---

## Kurulum sonrası yapılması gerekenler

Proje paketlerinin derlenmesi (`colcon build`) kurulumun parçasıdır (`./setup/50_proje_derleme.sh`; `install_all.sh` sırasında 50. adım). `araclar/kosu.sh baslat` her koşudan önce projeyi yeniden derler, koşu güncel kodla çalışır.

**1. Her yeni terminalde.** ROS 2 ve projenin Python ortamı kendiliğinden açılmaz. Her yeni Konsole'da, proje klasöründeyken şunu çalıştır:

```bash
source setup/env.sh
```

**2. Bilgisayarı yeniden başlatırsan.** Ağı yavaşlatan ve proje adreslerini açan ayar silinir. Tekrar aç:

```bash
./setup/60_ag_emulasyon_tc.sh
```

Aşağıdaki kontroller bu ayarın açık olmasını bekler.

**3. (İsteğe bağlı, önerilir) Gizlilik.** Yapay zekâ kitaplığı (Ultralytics) varsayılan olarak anonim kullanım bilgisi göndermek için ayarlıdır. Kapatmak için:

```bash
.venv/bin/yolo settings sync=False
```

**4. Her şey çalışıyor mu, kontrol et.** Aşağıdaki kontrolleri sırayla çalıştır. Her birinde **hiç `(-)` satırı olmamalı** ve son satır `(+)` ile bitmelidir. Testler çalışırken bilgisayarı başka işler için kullanma: Gazebo ve ekran kartı yoğun kullanılır, ölçümler bozulabilir. Bir kontrol bitmeden diğerini başlatma.

| Sıra | Komut | Ne kontrol eder? | Süre |
|---|---|---|---|
| 1 | `./setup/verify_all.sh` | Kurulan her şey yerinde mi | yaklaşık 1 dk |
| 2 | `./setup/runtime_smoke.sh` | Gazebo, ROS 2, PX4 ve yapay zekâ birlikte çalışıyor mu | birkaç dk |
| 3 | `./setup/dds_profil_dogrula.sh` | ROS 2 haberleşmesi yalnız proje ağını kullanıyor mu | birkaç dk |
| 4 | `./setup/arac_kimlik_testi.sh` | 1 ve 3 İHA bağlantısı, kimlik doğrulama, zaman ekseni | yaklaşık 2 dk |
| 5 | `./setup/kamera_olcum_testi.sh` | Kamera görüntü zamanları ve görüş açısı | 15 dk'dan uzun |
| 6 | `./setup/yuk_olcum_testi.sh gpu` | 3 İHA + 3 kamera + yapay zekâ birlikte, ekran kartı yeterli mi | yaklaşık 10-15 dk |
| 7 | `./setup/egitim_bellek_denemesi.sh` | Model eğitimi ekran kartı belleğine sığıyor mu | birkaç dk |

Bir test arkasında süreç bırakırsa sonraki test `(-)` verebilir. Gerekirse `ros2 daemon stop` çalıştırıp tekrar dene.

### Geliştirici testleri

Yukarıdaki doğrulama listesinden ayrıdır: yazılım bileşenlerini (araç süreci, kamera, çıkarım işçisi, rota…) sınar. Kurulum sonrası, yazılımı değiştirdiğinde çalıştır; hepsi başsız Gazebo + PX4 SITL açar ve kendi artığını toplar. Aynı anda yalnız bir tanesi çalışsın (ortak portlar). Ortak ön koşullar: kurulum tamam (`./setup/verify_all.sh` hepsi `(+)`), sürü ağı uygulanmış (`./setup/60_ag_emulasyon_tc.sh`), `colcon build` ile derlenmiş `install/` (`px4_adapter_testi`, `arac_sureci_testi`, `kamera_alici_testi` ve `cikarim_isci_testi` içindeki `birim`/`statik` adımları bunu kendisi derler; `alan_pilot_testi` derlemeyi yapmaz, `install/` hazır olmalıdır), `ros2 daemon` kapalı. Alt küme için test adı verilir (örn. `./setup/arac_sureci_testi.sh birim`); `--dry-run` ne yapacağını yazar, süreç başlatmaz.

| Komut | Ne sınar? | Yaklaşık süre | Ön koşul |
|---|---|---|---|
| `./setup/sozlesme_testi.sh` | Sözleşme dosyası doğrulayıcısı: geçerli örnekler geçer, bozuk örnekler beklenen nedenle reddedilir (simülasyon yok) | < 1 dk | yok |
| `./setup/kosu_testi.sh` | `araclar/kosu.sh`: koşu başlat/durdur/temizle, koşu üst verisi, çöküş ve zorla kapatma | yaklaşık 3-4 dk | PX4 derlenmiş; damga bileşeni için `cmake` |
| `./setup/px4_adapter_testi.sh` | `px4_adapter` (kimlik koruması, görev yükleme, hazırlık, görev), bölge/rota üretimi ve tek komut yolu | yaklaşık 8 dk | proje derlemesi (`./setup/50_proje_derleme.sh`; kurulumun parçasıdır) |
| `./setup/arac_sureci_testi.sh` | Araç süreci ve görev durum makinesi (tek ve üç araç + deneme koordinatörü), durum geçişleri | yaklaşık 10 dk | proje derlemesi (`./setup/50_proje_derleme.sh`); `.venv` |
| `./setup/kamera_alici_testi.sh` | Kamera, damga bileşeni ve kamera alıcısı: kayıpsız akış, kayıp ve geç kare senaryoları (`kayip`) | `birim kayip` alt kümesi yaklaşık 5 dk; tam koşu daha uzun | `cmake` (damga bileşeni derlemesi); `colcon build` |
| `./setup/cikarim_isci_testi.sh` | Çıkarım işçisi ve kare sonucu: GPU/CPU arka uçları, hata ve işçi ölümü senaryoları, üç araç | yaklaşık 15 dk | model ağırlık dosyaları (`yolo26l.pt`, `yolo26s.pt`, `yolo26s.onnx`; `.generated/models/`); GPU sürücüsü |
| `./setup/uc_mod_testi.sh` | Uçta mod: araçlar kare sonuçlarını reliable DDS ile yer istasyonuna gönderir; her numara için tam bir sonuç, dört durum, COMPLETE'in son sonuçtan sonra gelmesi, gecikmiş/eksik sonuç senaryoları (alt kümeler: `birim`, `tek`, `hata`, `uc`, `gecikme`) | yaklaşık 25 dk (tamamı) | `colcon build` (üç paket: `swarm_msgs`, `swarm_vehicle`, `swarm_gcs`); model ağırlıkları |
| `./setup/yer_istasyonu_testi.sh` | Yer istasyonu görev koordinatörü (`/gcs/mission_coordinator`): `Mission` ataması ve yerel rota karşılaştırması, bariyer/t0, COMPLETE/t1, izleme, komut yolu iskeleti, `kosu.sh` ile tek komutla üç araçlı koşu (alt kümeler: `birim`, `uc`, `komut`, `mission`, `bayat`) | yaklaşık 25 dk (tamamı) | `colcon build` (üç paket); model ağırlıkları |
| `./setup/dds_doygunluk_testi.sh` | Doygun hatta DDS canlılığı **ölçümü** (risk U21): merkezi modun ağ yükünü taklit eden sentetik TCP yükü (3 × 2 Hz × 921 600 B) ile aynı anda gerçek üç araçlı uçta mod koşusu; S0 taban, S1 sürekli doygunluk, S2 başlangıçta doygunluk (alt kümeler: `birim`, `s0`, `s1`, `s2`, `dryrun`). Ağ profiline dokunmaz, tc yalnız okunur; ölçüm "sorun var" derse bu test hatası değildir | yaklaşık 45-60 dk (s0 s1 s2) | `colcon build`; model ağırlıkları; sürü ağı (`60_ag_emulasyon_tc.sh`) uygulanmış |
| `./setup/alan_pilot_testi.sh` | Alan ve rota mini pilotu: üç araç tam rotayı uçar; süre, yönelim, kapsama, bölge taşması ölçülür; aday alan tablosu yazdırılır | yaklaşık 5 dk | `colcon build`; model ağırlıkları; `numpy` (venv) |

Notlar: süreler bu geliştirme makinesindendir (RTX 5070, 7950X); ölçüm testleri (`alan_pilot_testi`, `yuk_olcum_testi`) görsel istemci açıkken çalıştırılmamalıdır.

**Tek komutla uçta modda üç araçlı koşu.** Kurulum (proje derlemesi dahil; gerekirse `./setup/50_proje_derleme.sh`) sonrası (sürü ağı uygulanmış, `ros2 daemon` kapalı):

```bash
./araclar/kosu.sh baslat --arac 3 --yer-istasyonu var   # Gazebo + 3 PX4 + yer istasyonu görev koordinatörü + 3 araç süreci
./araclar/kosu.sh bekle                                 # yer istasyonu bitene dek bekler; çıkış kodu 0 = koşu tamam
./araclar/kosu.sh durdur
```

`--yer-istasyonu` verilmezse yalnız Gazebo ve PX4 başlar (kendi bağdaştırıcısını bağlayan testler için); `--yer-istasyonu yok` araç süreçlerini başlatır, koordinatörü başlatmaz. Koşu klasörü: `.generated/kosular/<kimlik>/` (görev kaydı `kayit/yer_istasyonu_gorev.jsonl`, izleme `kayit/yer_istasyonu_durum.jsonl`).

**Gazebo görüntüsünü izlemek (isteğe bağlı).** Koşular başsızdır (görsel arayüz yok). Bir koşu sürerken görmek için ayrı bir terminalde, koşunun Gazebo bölümüyle bağlan: `GZ_PARTITION=<koşu bölümü> GZ_IP=127.0.0.1 gz sim -g` (bölüm adı `./setup/alan_pilot_testi.sh` çıktısının başında ve koşu klasöründeki `kosu.json` içindedir: `gz_partition`); kamera görüntüsü için açılan pencerede "Image Display" eklentisini ekleyip aracın kamera konusunu seç. **Önizleme açıkken yapılan koşu ölçüm sayılmaz** (ekran kartı ve işlemci yükü ekler); ölçüm koşusundan önce pencereyi kapat.

### Sorun mu var?

<details>
<summary><b>Kurulum hiç başlamadı, ekranda <code>(-)</code> satırları var</b></summary>

Betik başlamadan önce bilgisayarını kontrol eder, `(-)` satırı hangi şeyin eksik olduğunu yazar (RAM, disk, dil, ekran kartı sürücüsü gibi). Onu düzelt ve komutu tekrar çalıştır. Bu aşamada bilgisayarına hiçbir şey kurulmaz.

</details>

<details>
<summary><b>Kurulum bir adımda durdu</b></summary>

Aynı komutu tekrar çalıştır: `./setup/install_all.sh`. Betikler tekrar çalıştırılabilir, bitmiş adımları atlar. Yine olmuyorsa, en yeni günlük dosyasını ekibe gönder:

```bash
ls -t .generated/logs | head -3
```

Çıkan dosyalar `.generated/logs/` klasöründedir.

</details>

<details>
<summary><b><code>nvidia-smi</code> çalışmıyor ya da CUDA sürümü düşük</b></summary>

- Paket bulunamazsa: Konsole'da `sudo apt update` çalıştırıp tekrar dene. Hâlâ bulamazsa sistem ayarlarındaki **Driver Manager** (sürücü yöneticisi) ile NVIDIA'nın **open** sürümlü sürücüsünü seç.
- Sürücü kurulu görünüp `nvidia-smi` hata veriyorsa, çok yaygın bir neden **Secure Boot**'tur. Bilgisayarın BIOS ayarlarından Secure Boot'u kapatıp tekrar dene.
- `nvidia-smi` çalışıyor ama CUDA 13.2'den düşük görünüyorsa sürücü eski demektir, daha yeni bir NVIDIA open sürücüsü kur.

</details>

<details>
<summary><b>Yeniden başlattım, kontroller ağ ile ilgili hata veriyor</b></summary>

Normal. Ağ ayarı yeniden başlatmada silinir. Şunu çalıştır: `./setup/60_ag_emulasyon_tc.sh`

</details>

---

## Tamamlanma Yüzdesi

<!-- ILERLEME:BASLA -->
**Projenin tamamlanma oranı: %25,9**  (28 / 74 madde bitti)

`█████░░░░░░░░░░░░░░░` %25,9

| Paket | Tarih | Ağırlık | Biten madde | Paketin ilerlemesi |
|---|---|---|---|---|
| K. Kurulum ve doğrulama testleri | 1 Şubat 2027 - 14 Şubat 2027 | %10 | 14 / 14 | %100,0 |
| A. Veri ve model | 15 Şubat 2027 - 21 Mart 2027 | %20 | 0 / 13 | %0,0 |
| B. Sürü yazılımı | 15 Şubat 2027 - 21 Mart 2027 | %25 | 14 / 21 | %63,6 |
| C. Kabul testleri ve pilot koşular | 22 Mart 2027 - 18 Nisan 2027 | %20 | 0 / 14 | %0,0 |
| D. Ana deneyler | 19 Nisan 2027 - 9 Mayıs 2027 | %15 | 0 / 5 | %0,0 |
| E. Analiz ve raporlama | 10 Mayıs 2027 - 28 Mayıs 2027 | %10 | 0 / 7 | %0,0 |

Aşağıdaki başlıklara tıklayınca maddeleri görürsün. Biten maddeler işaretli kutu (☑), kalın `[TAMAMLANDI]` etiketi ve italik açıklamayla; bitmeyenler boş kutuyla (☐) gösterilir.

<details>
<summary><b>K. Kurulum ve doğrulama testleri</b> · 1 Şubat 2027 - 14 Şubat 2027 · 14 / 14 madde · %100,0</summary>

- [x] **K1 [TAMAMLANDI]** - *Ubuntu 24.04, ROS 2 Jazzy, Gazebo Harmonic 8.15, PX4 v1.16.0, MAVSDK-Python 3.17.4 + mavsdk_server kurulumu; Gazebo grafik arayüzsüz, yalnız sunucu modunda çalışır (FR-31)*
- [x] **K2a [TAMAMLANDI]** - *Ortam kilidi: sürümler (`versions.env`), Python kilidi (pip `-c`, PyTorch/Ultralytics dahil), PX4 commit kaydı, SHA-256 özet listesi, kurulum raporu (FR-31)*
- [x] **K2b [TAMAMLANDI]** - *Ortam kilidi: apt paketlerinin ve NVIDIA sürücüsü/CUDA bileşenlerinin tam sürüm listesi kaydı (FR-31)*
- [x] **K3 [TAMAMLANDI]** - *NVIDIA sürücüsü, CUDA ve PyTorch CUDA derlemesi uyum testi (RTX 5070, sm_120) (GŞÖA 6.2)*
- [x] **K4 [TAMAMLANDI]** - *Ultralytics (8.4.210) ve MAVSDK-Python (3.17.4) sürümlerinin birlikte çalışma testinde sabitlenmesi (FR-31)*
- [x] **K5 [TAMAMLANDI]** - *gz-transport Python bağlamalarının çalıştığının doğrulanması (gerçek mesaj alışverişi) (GŞÖA 5.3)*
- [x] **K6 [TAMAMLANDI]** - *Fast DDS XML profili (yalnız UDPv4; SHM, data-sharing, intraprocess kapalı; sabit tek yayın keşif) ve ROS 2 tarafından uygulandığının doğrulanması (FR-21)*
- [x] **K7 [TAMAMLANDI]** - *Tek araç ve üç araç bağlantı/kimlik testleri: MAV_SYS_ID 1–3, UDP 14540–14542, gRPC 50051–50053, ad alanı /uav_1–/uav_3, beklenen sistem kimliği doğrulanmadan komut yok (FR-2, FR-8)*
- [x] **K8 [TAMAMLANDI]** - *Tek araç: simülasyon zamanı ile PX4 zaman damgalarının aynı eksende olduğunun doğrulanması (FR-17)*
- [x] **K9 [TAMAMLANDI]** - *Tek araç: Gazebo kamera damgalarının 0,5 s'nin tam katı ve karelerin sırayla teslim edildiğinin doğrulanması; doğrulanmazsa iki mod için yedek yola geçiş kararı (FR-10, FR-11)*
- [x] **K10 [TAMAMLANDI]** - *Kameranın yatay görüş açısının 30 m'den hedef piksel boyutu ölçülerek belirlenmesi ve 3. hafta başında kilitlenmesi (GŞÖA 5.2)*
- [x] **K11 [TAMAMLANDI]** - *Üç araç + üç kamera + üç GPU işçisi + Gazebo birlikte: işçi başına kare/s, gerçek zaman faktörü, GPU belleği ölçümü (nms=False) (FR-15, FR-24)*
- [x] **K12 [TAMAMLANDI]** - *GPU/CPU kararı: araç başına 2 kare/s sağlanıyor mu; sağlanmıyorsa YOLO26s + ONNX Runtime CPU hız ölçümü, NMS'siz çıktı kontrolü, B planı kararı (FR-15)*
- [x] **K13 [TAMAMLANDI]** - *Eğitim denemesi: batch=16 GPU belleğine sığıyor mu (sığmazsa bellek ölçütüyle en büyük değer), eğitim içi doğrulama nms=False kullanıyor mu (GŞÖA 6.2)*

</details>

<details>
<summary><b>A. Veri ve model</b> · 15 Şubat 2027 - 21 Mart 2027 · 0 / 13 madde · %0,0</summary>

- [ ] A1 - Gazebo sahne üreticisi: iki sınıf (görünür insan, görünür enkaz yığını); ışık, konum, yönelim tohumla; kısmi örtülme yok; hedefler birbirini örtmez (FR-16, FR-26)
- [ ] A2 - 60 eğitim + 10 doğrulama + 30 test sahnesi; yerleşim, tohum ve görünüm varyantı bölümler arasında ayrık; test hedef merkezleri ≥ 10 m; test sahnesinde 15 insan + 15 enkaz (FR-26)
- [ ] A3 - Etiket üretimi: Gazebo sınır kutusu kamerası (olmazsa hedef sınır kutularının izdüşümü); yöntem pilotta kilitlenir (GŞÖA 6.1)
- [ ] A4 - 7.200 eğitim + 1.200 doğrulama görüntüsü ve etiketleri, yerden 30 m, test koşularıyla aynı kamera ayarları (GŞÖA 6.2)
- [ ] A5 - Etiketlerin %10'u sahne ve sınıf bazında tabakalı görsel kontrol; sistematik hata ilgili bölümün tümünde düzeltilir (GŞÖA 6.1)
- [ ] A6 - (isteğe bağlı) Hazır veri seti: akademik lisanslı, havadan çekilmiş; künye, lisans, SHA-256; sınıf eşleme tablosu ve örneklem kontrolü; yalnız eğitim bölümüne (GŞÖA 6.1)
- [ ] A7 - Eğitim süresinin pilotta ölçülmesi, 14 haftalık takvime uygunluk değerlendirmesi (GŞÖA 6.2)
- [ ] A8 - (isteğe bağlı, ana deneylerden sonra, model kilidini değiştirmez) A veri planı modeli (hazır veri + Gazebo) eğitimi: 50 epoch, batch=16, 640, nms=False (eğitim çağrısında `nms=False` açıkça verilir; verilmezse eğitim içi doğrulama NMS'li başlıkla çalışır, K13 bulgusu), save_period=1 (FR-15, FR-16)
- [ ] A9 - B veri planı modeli (yalnız Gazebo) aynı ayarlarla eğitimi; eğitim çağrısında `nms=False` açıkça verilir (K13 bulgusu: verilmezse eğitim içi doğrulama NMS'li) (FR-15, FR-16)
- [ ] A10 - Epoch seçimi: Gazebo doğrulama sahnelerinde iki sınıf ortalama AP50'yi en çoklayan epoch (eşitlikte erken) (GŞÖA 6)
- [ ] A11 - Veri planı (kullanıcı kararı): B planı (yalnız Gazebo) birinci öncelik ve sabittir; A planı isteğe bağlı ek deney olarak yalnız zaman kalırsa, ana deneylerden sonra denenir ve sonucu (beklenen/düşük çıkması dahil, önceden varsayılmadan) raporlanır; ana deneylerde kullanılan model kilidini ve seçimi değiştirmez (GŞÖA 6)
- [ ] A12 - Çıkarım ayarlarının sabitlenmesi: güven 0,25; nms=False; max_det 300; FP32; batch=1 (FR-15)
- [ ] A13 - Model ve veri dosyalarının nihai SHA-256 özetleri (6. hafta sonu) (FR-31)

</details>

<details>
<summary><b>B. Sürü yazılımı</b> · 15 Şubat 2027 - 21 Mart 2027 · 14 / 21 madde · %63,6</summary>

- [x] **B1 [TAMAMLANDI]** - *`swarm_msgs`: durum, görev, tarama başlatma/bitiş, COMPLETE, kare sonucu, "kare alınamadı", komut (araç kimliği, sıra numarası, onay durumu) mesaj tanımları (FR-2, FR-3, FR-4, FR-12)*
- [x] **B2 [TAMAMLANDI]** - *Alanın üç çakışmayan tarama bölgesine ayrılması, şerit planı (w = 2·30·tan(görüş açısı/2), komşu izler ≥ 2 m örtüşür), rota dosyaları (FR-1)*
- [x] **B3 [TAMAMLANDI]** - *`px4_adapter`: araç başına ayrı MAVSDK System ve mavsdk_server; sistem kimliği doğrulaması; rotanın yerden 30 m görev (mission) olarak yüklenmesi; PX4'e komut yazan tek modül (FR-7, FR-8)*
- [x] **B4 [TAMAMLANDI]** - *Araç süreci (`swarm_vehicle`): tek ROS 2 düğümü /uav_N, durum/görev modülü, 2 Hz durum, diğer iki aracın durumunu alma ve kaydetme, durum makinesi (HAZIR → BARİYER_BEKLE → TARAMA → WAIT → TAMAMLANDI) (FR-2, FR-4)*
- [x] **B5 [TAMAMLANDI]** - *Yer istasyonu (`swarm_gcs`): `/gcs/mission_coordinator` (hazır bildirimleri, başlangıç bariyeri, t0; COMPLETE koşulları, t1), izleme ve komut arayüzü (FR-3, FR-5)*
- [x] **B6 [TAMAMLANDI]** - *Araç gövdesine sabit, aşağı bakan kamera (640 × 480 RGB8, sıkıştırmasız, 2 kare/s) ve kalibrasyon dosyası (FR-9)*
- [x] **B7 [TAMAMLANDI]** - *Gazebo sunucusunda damga bileşeni: araç kimliği, simülasyon zamanı, kare numarası (n = 2·t_sim), üretim anının monotonik zamanı (FR-10, FR-23)*
- [x] **B8 [TAMAMLANDI]** - *Kamera alıcısı: gz-transport doğrudan abone (ros_gz_bridge yok), kare numaralandırma, "kare alınamadı" ve "geç geldi" kuralları; damgalar doğrulanmazsa yedek yol (FR-10, FR-11)*
- [x] **B9 [TAMAMLANDI]** - *Çıkarım işçisi (alt süreç, IP kullanmayan yerel kanal): YOLO26L, GPU, FP32, batch=1, nms=False, güven 0,25; B planında YOLO26s + ONNX Runtime CPU (FR-13, FR-15, FR-16)*
- [x] **B10 [TAMAMLANDI]** - *Kare sonuç iletisi: tespit yoksa açık "tespit yok", işlem hatası ve "kare alınamadı" "tespit yok" olarak kodlanmaz (FR-12)*
- [x] **B11 [TAMAMLANDI]** - *Uçta mod: kare sonuçları, "kare alınamadı" kayıtları reliable DDS QoS ile; durum ve görev mesajları DDS ile (FR-13)*
- [ ] B12 - Merkezi mod: araç başına TCP kanalı, sıkıştırmasız görüntü, geri basınçta kare atılmaz; her iletide araç kimliği, kare numarası, simülasyon zamanı, kamera kalibrasyon kimliği ve kare üretim anına eşlenmiş canlı PX4 konum/yönelim tahmini; yer istasyonunda üç çıkarım işçisi (FR-14)
- [ ] B13 - Disk destekli uygulama kuyrukları; kare başına aşama zaman damgaları (üretim, kuyruğa giriş, aktarım, çıkarım başı/sonu, kullanılabilirlik) (GŞÖA 6.8)
- [ ] B14 - Kare–poz enterpolasyonu (konum doğrusal, yönelim küresel) ve konum hesaplayıcı (NED→ENU, kutu merkezinden ışın–zemin kesişimi, aralık sınırı 100 ms); telemetri yüksek hızda alınıp kaynak zamanına göre saklanır, merkezde gecikmiş kare 2 Hz durum mesajıyla konumlandırılmaz (FR-17, FR-18)
- [ ] B15 - Hedef birleştirme: üretim zamanına göre işleme, aynı sınıf ve ilk konuma ≤ 2,5 m ise aday, en yüksek güvenli tespitin konumu (FR-19)
- [x] **B16 [TAMAMLANDI]** - *Ağ emülasyonu betiği: loopback 10.10.0.0/24, tek ortak htb sınırlayıcı 25 Mbit/s, bayt sınırlı FIFO, geri alma ve doğrulama (FR-20)*
- [x] **B17 [TAMAMLANDI]** - *Sınırlayıcı kuyruk sınırının el kitabındaki öngörülen değere (4 MiB) getirilmesi ve yeniden doğrulanması (eskiden yapılandırmada 256 KiB idi) (FR-20)*
- [ ] B18 - Değerlendirme yazılımı: sınıf ve ≤ 5 m şartıyla Macar algoritmasıyla bire bir atama; TP, FP, FN, R, precision (FR-28)
- [ ] B19 - Bütünleşik işlev testi, iki modda: bölge paylaşımı, ortak başlangıç, ilerleme bildirimi, ortak tamamlanma; her görev karesi için sonuç veya "kare alınamadı" (FR-1, FR-2, FR-3, FR-4, FR-5)
- [x] **B20 [TAMAMLANDI]** - *Deney yapılandırma dosyasının ağ ve port bölümü (adresler, kuyruk, portlar, kimlikler) (GŞÖA 5.1)*
- [ ] B21 - Deney yapılandırma dosyasının genişletilmesi: sahne, rota, model, koşu, çıkarım ayarları (GŞÖA 5.1)

</details>

<details>
<summary><b>C. Kabul testleri ve pilot koşular</b> · 22 Mart 2027 - 18 Nisan 2027 · 0 / 14 madde · %0,0</summary>

- [ ] C1 - Ağ sınırı kabul testi 1: ölçülen DDS ve görüntü kanalı soketleri yalnız 10.10.0.x adreslerini kullanır (FR-25)
- [ ] C2 - Kabul testi 2: yerel trafik üretilirken D sayacı artmaz; yer istasyonu bileşenleri ve çıkarım alt süreçlerinde DDS yok (FR-25)
- [ ] C3 - Kabul testi 3: bilinen boyutlu gönderim sınırlayıcıdan geçer, bir kez sayılır, burst ≥ en büyük paket (FR-25)
- [ ] C4 - Kabul testi 4: sayaçlar ile kare ve mesaj sıra kayıtları karşılaştırılır, açıklanmamış boşluk yok (FR-25, FR-22)
- [ ] C5 - Kabul testi 5: eşleşmeden sonra %100 paket düşürme, her iki modda; uygulama teslimi durur, Gazebo–PX4/MAVLink sürer, kaldırılınca devam eder (FR-25)
- [ ] C6 - Uç/merkez ve kaynak eşitliği doğrulaması: aynı sahne, rota, tohum, kamera, ağırlık özeti, GPU, FP32, batch, nms=False, güven; bellek ve GPU kayıtları (GŞÖA 5.3)
- [ ] C7 - İşçi CPU eşlemesi: işçi başına aynı fiziksel çekirdeğe ait iki mantıksal CPU, çakışmasız, diğer süreçler dışarıda; iki modda aynı eşleme (GŞÖA 5.2)
- [ ] C8 - D ölçümü: t0 ve t1 anlarında sınırlayıcı gönderilmiş bayt sayaçları; COMPLETE baytları ayrı (FR-22)
- [ ] C9 - L ölçümü ve ek çıktılar (precision, FP/görev, konum hatası, tamamlanamayan oranı, hazırlık süresi, RTF, kare sayısı, GPU kullanımı/belleği) (FR-23, FR-24)
- [ ] C10 - Ayar pilotları: ortak FIFO kuyruk sınırının kesin değeri (FR-20)
- [ ] C11 - Nihai yapılandırmayla pilotlar: 3 doğrulama sahnesi × 2 mod = 6 koşu; rota uzunluğu, hız, tarama süresi, RTF; her hedef ≥ 1 karenin görüş alanında (FR-27)
- [ ] C12 - Tp, Sp, Dp ve H = 60·⌈2·max(Tp, Sp + 8Dp/C)/60⌉ hesabı (FR-27)
- [ ] C13 - Kalan protokol değerleri (telemetri aralık sınırı vb.); ortam kilidi ve protokol kilidi (etiketli commit + SHA-256 listesi) (FR-31)
- [ ] C14 - Koşu otomasyonu: 30 sahne × 2 mod, çift içi sıra kaydedilen rastgele tohumla, eşzamanlı çalıştırma yok, eğitim de ana koşularla eşzamanlı yapılmaz, başlatma dosyaları tek yapılandırmadan (FR-26)

</details>

<details>
<summary><b>D. Ana deneyler</b> · 19 Nisan 2027 - 9 Mayıs 2027 · 0 / 5 madde · %0,0</summary>

- [ ] D1 - Ana koşular: sahne 1–10 (her biri iki modda) (FR-26, FR-27)
- [ ] D2 - Ana koşular: sahne 11–20 (FR-26, FR-27)
- [ ] D3 - Ana koşular: sahne 21–30 (FR-26, FR-27)
- [ ] D4 - Teknik geçersizlik halinde ilgili çiftin iki mod için yeniden çalıştırılması; tamamlanamayan koşuların kaydı (dışlama yok) (FR-27)
- [ ] D5 - Koşu verilerinin bütünlüğü: dosya özetleri, sayaç–kayıt tutarlılığı (FR-31)

</details>

<details>
<summary><b>E. Analiz ve raporlama</b> · 10 Mayıs 2027 - 28 Mayıs 2027 · 0 / 7 madde · %0,0</summary>

- [ ] E1 - Hedef eşleştirme ve R, precision, FP; iki mod için mutlak ve sınıf bazlı (FR-24, FR-28)
- [ ] E2 - D, B, T için sahne başına yüzde iyileşme; L için medyan ve 95. yüzdelik farkları (FR-29)
- [ ] E3 - %95 percentile bootstrap, 10.000 yeniden örnekleme, eşleştirme bozulmadan (FR-29)
- [ ] E4 - Ölçüt ölçüt karar kuralı; R için üç sonuçlu kural; tek ortak başarı kararı yok; "fark gösterilemedi" eşdeğerlik değil (FR-30)
- [ ] E5 - Tamamlanamayan koşular: sansürlü süre gösterimi, kısmi trafik, tamamlanan çiftlerle koşullu analiz (FR-27)
- [ ] E6 - RTF, kare sayısı, rota sapması, konum hatası ve birleştirme hatalarının incelenmesi (GŞÖA 6.8)
- [ ] E7 - Sonuçların raporlanması (simülasyon sınırları ve varsayımlar açıkça belirtilerek) (FR-30)

</details>
<!-- ILERLEME:BITIS -->

---

## Klasörler

| Klasör | İçinde ne var? |
|---|---|
| `setup/` | Kurulum, kontrol ve ölçüm betikleri (`install_all.sh`, `verify_all.sh`, testler) |
| `config/` | Deney ayarları (adresler, portlar, ağ hızı, kamera, çıkarım ve eğitim değerleri) ve ROS 2 haberleşme profili |
| `planlama/` | Hedef ağacı (yüzdelerin kaynağı), mimari şemalar, kararlar, riskler, iş bölümü |
| `araclar/` | Yardımcı programlar (ilerleme hesabı, araç kimlik testi, kamera ve yük ölçümü, eğitim denemesi) |
| `third_party/` | Kurulumla inen PX4 kaynak kodu (depoya girmez) |
| `.venv/` | Kurulumla oluşan Python ortamı (depoya girmez) |
| `.generated/` | Kurulum raporu, günlükler, indirilen modeller ve ölçüm kayıtları (depoya girmez) |
