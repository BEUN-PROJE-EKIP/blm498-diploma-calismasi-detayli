# Uçta Yapay Zekâ Destekli İHA Sürüsü (BLM497): Afet Bölgelerinde Haberleşme Altyapısından Bağımsız Çalışma

Bu bir **simülasyon deneyidir**; gerçek uçuş ya da gömülü donanım doğrulaması ve operasyonel yeterlilik iddiası yoktur.

**[İlerleme](#kilometre-taşları-ve-ilerleme) · [Gereksinimler](#sistem-gereksinimleri) · [Kurulum](#kurulum) · [Doğru kuruldu mu?](#doğru-kuruldu-mu) · [Nasıl çalışıyoruz](#nasıl-çalışıyoruz) · [Klasörler](#klasörler)**

---


## Kilometre taşları ve ilerleme

Kendi işlerin için: kilometre taşında adının yazdığı satırlar; sıradaki iş, bitmemiş en üstteki maddedir. Ayrıntı ve bitti ölçütleri: `planlama/gelistirme_agaci.md`.

<!-- ILERLEME:BASLA -->
**Genel tamamlanma: %30,5** (31 / 80 madde; kod ve makine işi dahil)

`██████░░░░░░░░░░░░░░` %30,5

**Geliştirme oranı: %47,5** (31 / 55 geliştirme maddesi; yalnız kod ve altyapı işi)

`█████████░░░░░░░░░░░` %47,5

**Ana hedefler** (belgeye göre; ana amaç uçta ve merkezi modun beş ölçütle karşılaştırılmasıdır). Bir hedef, paketlerindeki bütün maddeler bitince tamamlanır.

| | Hedef | Paketler | Tamamlanma |
|---|---|---|---|
| ◐ | **1.** Sürü sistemi: üç İHA, dört sürü işlevi, uçta ve merkezi mod | B | `████████████████░░░░` %81,8 |
| ☐ | **2.** Görüntü işleme: YOLO26 modeli, veri hattı ve eğitim | A | `░░░░░░░░░░░░░░░░░░░░` %0,0 |
| ◐ | **3.** Deney düzeneği: başkalarının da çalıştırabileceği kilitli, tekrarlanabilir simülasyon ortamı | K, C | `███████░░░░░░░░░░░░░` %33,3 |
| ☐ | **4.** Deney sonuçları: 30 sahnede 60 koşu ve karar kuralına göre rapor | D, E | `░░░░░░░░░░░░░░░░░░░░` %0,0 |

**Tamamlanan ana hedef: 0 / 4**

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
<summary>◐ <b>M3 - Merkezi mod ve izleme</b> [Ömer Faruk GÜNER, %60,0]</summary>

Bekler: yok, başlayabilir

- ✔ B12 - Merkezi mod
- ☐ B13 - Disk kuyrukları ve aşama damgaları
- ✔ B14 - Poz enterpolasyonu ve konum hesabı
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
<summary>◐ <b>M6a - Değerlendirme ve analiz yazılımı</b> [Miraç BOZACIOĞLU, %22,8]</summary>

Bekler: yok, başlayabilir

- ✔ B18 - Değerlendirme yazılımı
- ☐ E1a - Eşleştirme analiz betiği
- ☐ E2a - İyileşme analiz betiği
- ☐ E3a - Bootstrap betiği
- ☐ E4a - Karar kuralı betiği
- ☐ E5a - Sansürlü koşu betiği

</details>

<details open>
<summary>☐ <b>M6b - Bütünleşik koşu ve kabul testleri</b> [Mikail DEĞER, %0,0]</summary>

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
<summary>☐ <b>M7 - Pilotlar ve kilit</b> [Mikail DEĞER, %0,0]</summary>

Bekler: M6a, M6b

- ☐ B21 - Yapılandırma genişletmesi
- ☐ C10 - Kuyruk sınırı pilotu
- ☐ C14 - Koşu otomasyonu
- ☐ C11 - Nihai yapılandırma pilotları
- ☐ C12 - H hesabı
- ☐ A12 - Çıkarım ayarları kilidi
- ☐ C13 - Protokol ve ortam kilidi

</details>

<details open>
<summary>☐ <b>M8a - Ana deneyler</b> [Mikail DEĞER, %0,0]</summary>

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

## Sistem gereksinimleri

| Gerekli | Ne olmalı? |
|---|---|
| İşletim sistemi | **Kubuntu/Ubuntu 24.04**, kurulum dili **İngilizce** (Kubuntu'da "Normal installation") |
| İşlemci | En az 12 mantıksal işlemci |
| Bellek / disk | En az 28 GB RAM, en az 100 GB boş disk |
| Ekran kartı | NVIDIA, 12 GB bellek önerilir |
| Diğer | İnternet ve yönetici (sudo) şifresi |

Denenen makine: AMD Ryzen 9 7950X + NVIDIA RTX 5070 (sürücü 595.99.02). Kurulum betiği başlamadan bunları kendisi kontrol eder; eksik varsa **hiçbir şey kurmadan durur** ve neyin eksik olduğunu yazar. Ubuntu paketlerinin sürümleri sabitlenmemiştir; başka tarihte yapılan kurulumda farklı çıkabilir.

---

## Kurulum

Hepsi **Konsole**'da yapılır; komutları kopyalayıp yapıştır.

**1. Sistemi güncelle ve NVIDIA sürücüsünü kur.** Kurulum betikleri sürücüye **dokunmaz**, yalnız doğrular; sürücüyü sen kurarsın:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y build-essential dkms linux-headers-$(uname -r) git
sudo apt install -y nvidia-driver-595-open
sudo reboot
```

Yeniden açılınca `nvidia-smi` çalışmalı ve `CUDA Version: 13.2` (ya da üstü) görünmeli. Olmuyorsa aşağıdaki [Sorun giderme](#sorun-giderme) bölümüne bak.

**2. Projeyi indir.** Depo özeldir; GitHub hesabının depoya erişimi olmalı (`git clone` kimlik sorar).

```bash
cd ~ && git clone https://github.com/omerfarukguner/blm498-diploma-calismasi.git && cd blm498-diploma-calismasi
```

**3. Kurulumu başlat.**

```bash
./setup/install_all.sh
```

Önce bilgisayarı kontrol eder, sonra **sudo şifreni bir kez** sorar; ROS 2, Gazebo, PX4, Python ortamı ve proje derlemesini kurar (**15-60 dk**; Konsole'u kapatma, bilgisayarı uyutma). `Ctrl + C` ile durdurabilirsin; aynı komut kaldığı yerden devam eder. Satır başları: `(+)` başarılı, `(-)` hata, `(!)` uyarı, `(i)` bilgi. Kısa rapor: `.generated/kurulum_raporu.md`.

**4. Her yeni terminalde** (ROS 2 ve Python ortamı kendiliğinden açılmaz):

```bash
source setup/env.sh
```

**5. Bilgisayarı yeniden başlatırsan** ağ ayarı silinir; tekrar uygula:

```bash
./setup/60_ag_emulasyon_tc.sh
```

> **Uyarı:** kurulumdan **sonra** `apt upgrade` / `apt full-upgrade` çalıştırma; paket sürümleri kilitlidir. 1. adımdaki güncelleme yalnız kurulumdan **önce** yapılır.

*(İsteğe bağlı gizlilik: yapay zekâ kitaplığı varsayılan olarak anonim kullanım bilgisi gönderir; kapatmak için `.venv/bin/yolo settings sync=False`.)*

---

## Doğru kuruldu mu?

Üç komut, sırayla (toplam ~7 dk); her birinde **hiç `(-)` olmamalı**. Çalışırken bilgisayarı başka işler için kullanma, aynı anda yalnız birini çalıştır.

| # | Komut | Süre | Ne görmelisin? |
|---|---|---|---|
| 1 | `./setup/verify_all.sh` | ~1 dk | Sekiz bileşenin (00…60) hepsi `(+)`; son satır `(+) Tüm doğrulamalar geçti` |
| 2 | `./setup/runtime_smoke.sh` | ~30 sn | Gazebo, ROS 2, PX4 ve yapay zekâ birlikte çalışır; `0 başarısız` ve son satır `(+) Çalışma zamanı duman testleri tamamlandı…` |
| 3 | `./araclar/kosu.sh baslat --arac 1 --yer-istasyonu var` <br> `./araclar/kosu.sh bekle` <br> `./araclar/kosu.sh durdur` | ~15 sn + ~4,5 dk + ~1 sn | Tam tek araç görevi: `baslat` sonunda `(+) Koşu başladı…`; `bekle` görev bitince `(+) Yer istasyonu tamamlandı (çıkış 0)` ve çıkış kodu 0; `durdur` sonunda `(+) Koşu: durdur tamamlandı (bitiş durumu: tamamlandi)` |

Koşular başsızdır (görsel arayüz yok). İzlemek için başka terminalde, koşunun bölümüyle bağlan: `GZ_PARTITION=<bölüm> GZ_IP=127.0.0.1 gz sim -g` (bölüm adı koşu klasöründeki `kosu.json` içinde `gz_partition`). **Önizleme açıkken yapılan koşu ölçüm sayılmaz**; ölçümden önce pencereyi kapat.

<details>
<summary><b>Ölçüm testleri</b> (K aşaması; yalnız ölçüm yapmak istersen)</summary>

Kurulum doğrulaması için gerekmez. Her biri `(-)` içermemeli; aynı anda yalnız biri çalışır.

| Komut | Ne ölçer? | Süre |
|---|---|---|
| `./setup/dds_profil_dogrula.sh` | ROS 2 haberleşmesi yalnız proje ağını kullanıyor mu | birkaç dk |
| `./setup/arac_kimlik_testi.sh` | 1 ve 3 İHA bağlantısı, kimlik doğrulama, zaman ekseni | ~2 dk |
| `./setup/kamera_olcum_testi.sh` | Kamera görüntü zamanları ve görüş açısı | 15 dk'dan uzun |
| `./setup/yuk_olcum_testi.sh gpu` | 3 İHA + 3 kamera + yapay zekâ birlikte; ekran kartı yeterli mi | ~10-15 dk |
| `./setup/egitim_bellek_denemesi.sh` | Model eğitimi ekran kartı belleğine sığıyor mu | birkaç dk |

</details>

<details>
<summary><b>Geliştirici testleri</b> (yazılımı değiştirdiğinde)</summary>

Yazılım bileşenlerini sınar; çoğu başsız Gazebo + PX4 açar ve kendi artığını toplar. **Aynı anda yalnız biri** çalışsın (ortak portlar). Ortak ön koşullar: kurulum tamam (`verify_all` hepsi `(+)`; proje derlemesi kurulumun 50. adımıdır), sürü ağı uygulanmış (`./setup/60_ag_emulasyon_tc.sh`), `ros2 daemon` kapalı. `araclar/kosu.sh baslat` her koşudan önce projeyi yeniden derler. Alt küme için test adı verilir (örn. `./setup/arac_sureci_testi.sh birim`); `--dry-run` ne yapacağını yazar, süreç başlatmaz. Süreler geliştirme makinesindendir; ölçüm testleri (`alan_pilot_testi`, `yuk_olcum_testi`) görsel istemci açıkken çalıştırılmamalıdır.

| Komut | Ne sınar? | Süre | Ek ön koşul |
|---|---|---|---|
| `./setup/sozlesme_testi.sh` | Sözleşme dosyası doğrulayıcısı (simülasyon yok) | < 1 dk | — |
| `./setup/swarm_msgs_testi.sh` | `swarm_msgs` mesaj paketi | < 1 dk | — |
| `./setup/kosu_testi.sh` | `araclar/kosu.sh`: başlat/durdur/temizle, koşu üst verisi, çöküş ve zorla kapatma | ~3-4 dk | PX4 derlenmiş; `cmake` |
| `./setup/px4_adapter_testi.sh` | `px4_adapter` (kimlik koruması, görev yükleme, hazırlık), bölge/rota üretimi, tek komut yolu | ~8 dk | — |
| `./setup/arac_sureci_testi.sh` | Araç süreci ve görev durum makinesi (tek ve üç araç) | ~10 dk | — |
| `./setup/kamera_alici_testi.sh` | Kamera, damga bileşeni, kamera alıcısı: kayıp ve geç kare senaryoları | ~5 dk (`birim kayip`) | `cmake` |
| `./setup/cikarim_isci_testi.sh` | Çıkarım işçisi ve kare sonucu: GPU/CPU arka uçları, hata ve işçi ölümü | ~15 dk | model ağırlıkları (`.generated/models/`) |
| `./setup/uc_mod_testi.sh` | Uçta mod: kare sonuçları reliable DDS ile yer istasyonuna (alt kümeler: `birim`, `tek`, `hata`, `uc`, `gecikme`) | ~25 dk | model ağırlıkları |
| `./setup/yer_istasyonu_testi.sh` | Yer istasyonu görev koordinatörü: görev ataması, bariyer/t0, COMPLETE/t1, izleme (alt kümeler: `birim`, `uc`, `komut`, `mission`, `bayat`) | ~25 dk | model ağırlıkları |
| `./setup/dds_doygunluk_testi.sh` | Doygun hatta DDS canlılığı **ölçümü** (risk U21; alt kümeler: `birim`, `s0`, `s1`, `s2`). Ölçüm "sorun var" derse bu test hatası değildir | ~45-60 dk | model ağırlıkları |
| `./setup/merkezi_mod_testi.sh` | Merkezi mod: araç başına TCP görüntü kanalı ve yer istasyonunda çıkarım (tek araç; alt kümeler: `birim`, `tek`, `hata`, `basinc`). `./araclar/kosu.sh baslat --arac 1 --yer-istasyonu var --mimari merkezi` ile elle de çalışır | ~45 dk (tamamı) | model ağırlıkları |
| `./setup/poz_tamponu_testi.sh` | Telemetri tamponu ve kare–poz enterpolasyonu: telemetri hızı, her görev karesi için poz kaydı, Gazebo gerçek pozuyla karşılaştırma, PX4 − sim zaman farkı (alt kümeler: `birim`, `tek`, `hata`) | ~16 dk (tamamı) | — |
| `./setup/konum_testi.sh` | Konum hesaplayıcı: ışın–zemin kesişimi (NED→ENU), bilinen işaretlerle konum hatası, rota boyunca ve iki modda (uçta/merkezi) aynı sonuç, odometri zaman kayması ölçümü (alt kümeler: `birim`, `isaret`, `rota`, `iki_mod`, `kayma`, `kayip`) | ~30 dk (tamamı) | model ağırlıkları |
| `./setup/alan_pilot_testi.sh` | Alan ve rota mini pilotu: üç araç tam rotayı uçar; süre, yönelim, kapsama ölçülür | ~5 dk | model ağırlıkları |

**Tek komutla uçta modda üç araçlı koşu:**

```bash
./araclar/kosu.sh baslat --arac 3 --yer-istasyonu var   # Gazebo + 3 PX4 + yer istasyonu + 3 araç süreci
./araclar/kosu.sh bekle                                 # yer istasyonu bitene dek bekler; çıkış kodu 0 = koşu tamam
./araclar/kosu.sh durdur
```

`--yer-istasyonu` verilmezse yalnız Gazebo ve PX4 başlar (kendi bağdaştırıcısını bağlayan testler için); `bekle` yalnız `--yer-istasyonu var` ile çalışır. Koşu klasörü: `.generated/kosular/<kimlik>/`.

</details>

<details id="sorun-giderme">
<summary><b>Sorun giderme</b></summary>

- **Kurulum hiç başlamadı, `(-)` satırları var:** betik başlamadan önce bilgisayarı kontrol eder; `(-)` satırı neyin eksik olduğunu yazar (RAM, disk, dil, sürücü…). Düzeltip tekrar çalıştır; bu aşamada hiçbir şey kurulmaz.
- **Kurulum bir adımda durdu:** `./setup/install_all.sh` komutunu tekrar çalıştır (bitmiş adımları atlar). Yine olmuyorsa en yeni günlüğü ekibe gönder: `ls -t .generated/logs | head -3`.
- **`nvidia-smi` çalışmıyor ya da CUDA 13.2'den düşük:** paket bulunamazsa `sudo apt update` sonrası tekrar dene, ya da **Driver Manager** ile NVIDIA'nın **open** sürücüsünü seç. Sürücü kurulu görünüp hata veriyorsa en yaygın neden **Secure Boot**'tur: BIOS'tan kapat. CUDA düşükse daha yeni bir open sürücü kur.
- **Yeniden başlattım, kontroller ağ hatası veriyor:** normal; `./setup/60_ag_emulasyon_tc.sh` çalıştır.
- **Bir test arkasında süreç bıraktı, sonraki test `(-)` veriyor:** `ros2 daemon stop` çalıştırıp tekrar dene; takılı koşu varsa `./araclar/kosu.sh temizle`.

</details>

---

## Nasıl çalışıyoruz

1. **İşin:** `planlama/gelistirme_agaci.md` kilometre taşı tablosunda adın yazan M'ler; sıradaki iş, bitmemiş en üstteki madde. Bir maddeye başlamadan ekibe haber ver. Sorumluluk yalnız iş bölümüdür; herkes her dosyada çalışabilir.
2. **Commit ve push:** `main`'e doğrudan commit ve push serbest; istersen dal + PR kullan. Push'tan önce `git pull`; force push yapma. Commit mesajı Türkçe: `alan: kısa açıklama`.
3. **Bitti demek:** maddenin **"Bitti:" ölçütü** gerçekten sağlanınca ağaçta `[x]` yap. README ilerlemesini `python3 araclar/ilerleme.py --yaz` ile yenile (asistan bunu madde bitince sormadan yapar).
4. **Büyük değişiklikten sonra:** `./setup/verify_all.sh` hepsi `(+)`; `setup/` ya da `config/` değiştiyse `./setup/lock_ozet.sh` ile özetleri yenile.
5. **Kilitli değerler** (25 Mbit/s ağ profili, çıkarım ayarları, karar kuralları, kilit dosyaları) sonuçlara bakılarak değiştirilmez. Yapay zekâ asistanıyla çalışıyorsan ona önce `CLAUDE.md`'yi okut; tüm kurallar orada.

**Yapay zekâ asistanıyla başlarken.** Proje klasöründe Claude Code'u aç ve ilk mesaj olarak şunu yaz:

```text
Ben <Ad SOYAD>. CLAUDE.md'deki "Göreve başlarken" adımlarını uygula.
```

Asistan `sudo`, `apt upgrade` ve `git push` çalıştırmaz; kurulumu ve push'u sen kendi Konsole'unda yaparsın. Bu depoda sahiplik yasağı yoktur; asistan her dosyada çalışabilir (`CLAUDE.md`, "Sorumluluklar").

---

## Klasörler

| Klasör | İçinde ne var? |
|---|---|
| `setup/` | Kurulum, kontrol, ölçüm ve test betikleri (`install_all.sh`, `verify_all.sh`…); sürümler `setup/versions.env` |
| `config/` | Deney ayarları (adresler, portlar, ağ hızı, kamera, çıkarım, eğitim) ve ROS 2 haberleşme profili |
| `src/` | ROS 2 paketleri (`swarm_msgs`, `swarm_vehicle`, `swarm_gcs`) ve Gazebo damga bileşeni (`yayim_damga`) |
| `araclar/` | Yardımcı programlar (koşu betiği `kosu.sh`, ilerleme hesabı, ölçüm araçları) |
| `araclar/degerlendirme/` | Değerlendirme ve analiz yazılımı (M6a): hedef eşleştirmesi (B18) ve analiz betikleri; testleri `test/` altında |
| `planlama/` | Hedef ağacı ve kilometre taşları (ilerlemenin kaynağı), yol haritası, mimari, sözleşmeler, kararlar, riskler |
| `docs/` | Kaynak belgeler (şartname ve proje el kitabı); **değiştirilmez** |
| `third_party/`, `.venv/`, `.generated/` | Kurulumla oluşur (PX4 kaynağı, Python ortamı, rapor/günlük/model/ölçüm kayıtları); depoya girmez |
