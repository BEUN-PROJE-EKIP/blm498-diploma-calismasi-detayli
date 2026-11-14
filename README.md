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
**Genel tamamlanma: %25,9** (28 / 80 madde; kod ve makine işi dahil)

`█████░░░░░░░░░░░░░░░` %25,9

**Geliştirme oranı: %40,4** (28 / 55 geliştirme maddesi; yalnız kod ve altyapı işi)

`████████░░░░░░░░░░░░` %40,4

Kilometre taşları (✔ bitti, ◐ sürüyor, ☐ başlamadı). Maddeler iş sırasıyla dizilidir: sıradaki iş, bitmemiş en üstteki maddedir. Biten kilometre taşları kapalıdır, başlığına tıklayınca açılır.

<details>
<summary>✔ <b>K - Kurulum ve doğrulama</b> [%100,0]</summary>

- ✔ K1 - Temel yazılım kurulumu
- ✔ K2a - Ortam kilidi ve özet listesi
- ✔ K2b - apt ve NVIDIA sürüm kaydı
- ✔ K3 - GPU ve CUDA uyum testi
- ✔ K4 - Ultralytics ve MAVSDK sürüm kilidi
- ✔ K5 - gz-transport Python doğrulaması
- ✔ K6 - Fast DDS profili
- ✔ K7 - Bağlantı ve kimlik testleri
- ✔ K8 - Simülasyon ve PX4 zaman ekseni
- ✔ K9 - Kamera damga ve sıra ölçümü
- ✔ K10 - Kamera görüş açısı kilidi
- ✔ K11 - Üç araç yük ölçümü
- ✔ K12 - GPU/CPU kararı
- ✔ K13 - Eğitim batch denemesi
- ✔ B16 - Ağ emülasyonu betiği
- ✔ B17 - Kuyruk sınırı 4 MiB
- ✔ B20 - Yapılandırma ağ bölümü

</details>

<details>
<summary>✔ <b>M0 - Sözleşmeler</b> [%100,0]</summary>

- ✔ B1 - swarm_msgs mesaj paketi

</details>

<details>
<summary>✔ <b>M1 - Tek araç iskeleti</b> [%100,0]</summary>

- ✔ B3 - PX4 bağdaştırıcısı
- ✔ B4 - Araç süreci ve durum makinesi
- ✔ B6 - Araç kamerası
- ✔ B7 - Gazebo damga bileşeni
- ✔ B8 - Kamera alıcısı
- ✔ B9 - Çıkarım işçisi
- ✔ B10 - Kare sonuç iletisi
- ✔ B2 - Bölgeler ve şerit rotaları

</details>

<details>
<summary>✔ <b>M2 - Üç araç</b> [%100,0]</summary>

- ✔ B11 - Uçta mod iletişimi
- ✔ B5 - Yer istasyonu koordinatörü

</details>

<details open>
<summary>☐ <b>M3 - Merkezi mod ve izleme</b> [Ömer Faruk GÜNER, %0,0]</summary>

Bekler: yok, başlayabilir

- ☐ B12 - Merkezi mod
- ☐ B13 - Disk kuyrukları ve aşama damgaları
- ☐ B14 - Poz enterpolasyonu ve konum hesabı
- ☐ B15 - Hedef birleştirme

</details>

<details open>
<summary>☐ <b>M4 - Veri hattı</b> [Mikail DEĞER, %0,0]</summary>

Bekler: yok, başlayabilir

- ☐ A1 - Sahne üreticisi
- ☐ A2 - Eğitim, doğrulama, test sahneleri
- ☐ A3 - Etiket üretim yöntemi
- ☐ A4a - Görüntü ve etiket üretim kodu
- ☐ A4b - Eğitim ve doğrulama görüntüleri üretimi
- ☐ A5 - Etiket görsel kontrolü
- ☐ A12 - Çıkarım ayarları kilidi

</details>

<details open>
<summary>☐ <b>M5 - Model</b> [Mikail DEĞER, %0,0]</summary>

Bekler: M4

- ☐ A7 - Eğitim süresi pilotu
- ☐ A9 - B planı modeli eğitimi
- ☐ A10 - Epoch seçimi
- ☐ A13 - Model ve veri özetleri
- ☐ A6 - Hazır veri seti (isteğe bağlı)
- ☐ A8 - A planı modeli eğitimi (isteğe bağlı)
- ☐ A11 - Veri planı kaydı (isteğe bağlı)

</details>

<details open>
<summary>☐ <b>M6a - Değerlendirme ve analiz yazılımı</b> [Miraç BOZACIOĞLU, %0,0]</summary>

Bekler: yok, başlayabilir

- ☐ B18 - Değerlendirme yazılımı
- ☐ E1a - Eşleştirme analiz betiği
- ☐ E2a - İyileşme analiz betiği
- ☐ E3a - Bootstrap betiği
- ☐ E4a - Karar kuralı betiği
- ☐ E5a - Sansürlü koşu betiği

</details>

<details open>
<summary>☐ <b>M6b - Bütünleşik koşu ve kabul testleri</b> [Ömer Faruk GÜNER, %0,0]</summary>

Bekler: M3, M5, M6a

- ☐ B19 - Bütünleşik işlev testi
- ☐ C1 - Kabul testi 1: ağ adresleri
- ☐ C2 - Kabul testi 2: yerel trafik
- ☐ C3 - Kabul testi 3: sınırlayıcı sayacı
- ☐ C4 - Kabul testi 4: sayaç ve kayıtlar
- ☐ C5 - Kabul testi 5: paket düşürme
- ☐ C6 - Uç–merkez kaynak eşitliği
- ☐ C7 - İşçi CPU eşlemesi
- ☐ C8 - D ölçümü
- ☐ C9 - L ölçümü ve ek çıktılar

</details>

<details open>
<summary>☐ <b>M7 - Pilotlar ve kilit</b> [Ömer Faruk GÜNER, %0,0]</summary>

Bekler: M6a, M6b

- ☐ B21 - Yapılandırma genişletmesi
- ☐ C10 - Kuyruk sınırı pilotu
- ☐ C14 - Koşu otomasyonu
- ☐ C11 - Nihai yapılandırma pilotları
- ☐ C12 - H hesabı
- ☐ C13 - Protokol ve ortam kilidi

</details>

<details open>
<summary>☐ <b>M8a - Ana deneyler</b> [Ömer Faruk GÜNER, %0,0]</summary>

Bekler: M7

- ☐ D1 - Ana koşular 1–10
- ☐ D2 - Ana koşular 11–20
- ☐ D3 - Ana koşular 21–30
- ☐ D4 - Yeniden koşular ve kayıt
- ☐ D5 - Veri bütünlüğü

</details>

<details open>
<summary>☐ <b>M8b - Analiz ve rapor</b> [Miraç BOZACIOĞLU, %0,0]</summary>

Bekler: M8a

- ☐ E1b - Eşleştirme analizi, gerçek veri
- ☐ E2b - İyileşme analizi, gerçek veri
- ☐ E3b - Bootstrap, gerçek veri
- ☐ E4b - Karar tablosu, gerçek veri
- ☐ E5b - Sansürlü koşu analizi, gerçek veri
- ☐ E6 - Ek ölçülerin incelenmesi
- ☐ E7 - Sonuç raporu

</details>

Ayrıntı ve bitti ölçütleri: `planlama/gelistirme_agaci.md`.
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
