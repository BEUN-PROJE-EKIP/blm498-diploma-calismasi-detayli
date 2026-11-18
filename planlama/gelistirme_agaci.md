# Geliştirme ağacı ve ilerleme

Kaynak: proje el kitabı v1.3.2 (Çalışma Takvimi, Yöntem, Risk Yönetimi) ve GŞÖA v2 (FR-1…FR-31). Bu dosya projenin **tek ilerleme kaynağıdır**; README'deki ilerleme çubuğu bu dosyadan hesaplanır.

## Kurallar

- Bir madde **yalnız kabul ölçütü sağlandığında** işaretlenir (`[x]`). Ölçüt geçmeden, "neredeyse bitti" diye işaretlenmez.
- **Ağırlık:** iş paketi ağırlıkları el kitabındaki **resmî yüzdelerdir** (toplam 100). Paket içinde her maddenin göreli ağırlığı `w` ile verilir (zorluk ve emek için 1–3).
- **Yüzde** = Σ (paket ağırlığı × paketteki biten madde `w` toplamı ÷ paketteki tüm madde `w` toplamı).
- **`w0` = isteğe bağlı madde:** yüzdeye girmez (payda ve pay dışı); yapılırsa ek analiz olarak raporlanır. A paketinde A planı (hazır veri) bu şekildedir: gerekçe aşağıda, "Veri planı kararı".
- README'de yalnız kilometre taşı ağacı görünür (M satırı, sorumlu, M oranı, bekledikleri; altında `✔`/`☐` kimlik ve kısa ad); ayrıntı, bitti ölçütü ve ilgili gereksinim yalnız bu dosyadadır.
- **Haftalar** 2027 bahar dönemine göre 1 Şubat 2027 - 28 Mayıs 2027 arasıdır; 8-14 Mart (Ramazan Bayramı), 29 Mart - 4 Nisan (vize) ve 17-23 Mayıs (Kurban Bayramı) haftaları sayılmaz. Yeni madde eklenirse ağırlıklar yeniden dengelenir ve bu dosyada gerekçesi yazılır.
- Her madde: `kimlik · ağırlık · M · tür · kısa ad · açıklama · ilgili gereksinim · bitti ölçütü`. **M:** maddenin ait olduğu kilometre taşı (aşağıdaki tablo); bir madde tek bir M'ye ve tek bir türe aittir. **Tür:** `geliştirme` (kod, altyapı, araç, test yazımı) ya da `çalıştırma` (makine işi: üretim, eğitim, pilot, ana koşu, analizin gerçek veriyle yapılması, rapor yazımı). **Kısa ad:** en çok 6 kelime; README'de görünen ad. Madde, kimliğinin harfiyle (K, A, B, C, D, E) bir iş paketine ait sayılır; ağırlık hesabı paket üzerinden yapılır.
- **Genel tamamlanma** yukarıdaki yüzde formülüyle (bütün maddeler, makine işi dahil). **Geliştirme oranı** = Σ (paket ağırlığı × `w` ÷ paket toplam `w`) biten `geliştirme` maddeleri üzerinden ÷ aynı toplam bütün `geliştirme` maddeleri üzerinden. **M oranı** aynı formül, yalnız o M'nin maddeleri üzerinden. `w0` maddeler hiçbir orana girmez.
- **Tek sahip:** her kilometre taşının tek sahibi vardır; maddelerde ayrı sorumlu alanı yoktur (madde, bulunduğu kilometre taşının sahibine aittir).
- **İş sırası:** dosyada maddeler kilometre taşına göre gruplanır ve her grupta **iş sırasıyla** (yukarıdan aşağı, sıradaki iş en üstteki bitmemiş madde) dizilir. İsteğe bağlı (`w0`) maddeler grubun sonundadır.
- **Alt kilometre taşı:** aynı kişiye ait **ardışık** maddeler bir kilometre taşı olur; sahiplik değişirse kilometre taşı aynı kuralla yeniden bölünür ve `a`, `b`, `c`… eki alır (M6 → M6a, M6b; M8 → M8a, M8b).
- **Bağımlılık yalnız kilometre taşı düzeyinde** (`Bekler` sütunu) tutulur; madde düzeyinde bağımlılık bilinçli olarak izlenmez (bakım maliyeti ve bayatlama riski: maddeler ilerledikçe çizge eskir, yanlış güven verir). Maddenin başlamak için neyi beklediği, ölçütünden ve kilometre taşının `Bekler` satırından okunur.
- **Bölünen maddeler:** iki kilometre taşına ya da iki türe yayılan işler tek madde olarak tutulmaz. A4 → A4a (üretim kodu) + A4b (görüntülerin üretimi); E1–E5 → `a` (analiz betiği, sentetik veriyle sınanmış, M6a) + `b` (gerçek verilerle, M8b). Ağırlık: A4 (w2) → A4a w1 + A4b w1; E1–E4 (w2) → `a` w1 + `b` w1; E5 (w1) → `a` w1 + `b` w1 (E paketinin toplam `w`'si 12'den 13'e çıktı; E'de biten madde olmadığından genel oran değişmedi). Eski kimlikler (A4, E1…E5) kullanılmaz.
- Kapsam dışı (belge): dinamik yeniden bölgeleme, kayıp araç görevini devralma, formasyon (FR-6); gerçek uçuş veya gömülü donanım doğrulaması; operasyonel yeterlilik iddiası.

## Kilometre taşları

Tek kaynak bu tablodur (`araclar/ilerleme.py` okur). Her kilometre taşının **tek sahibi** vardır. `Bekler`: o kilometre taşının başlayabilmesi için bitmesi gereken kilometre taşları (yalnız M düzeyinde; bağımlılık madde düzeyinde izlenmez). Sıra ve ayrıntı: [`yol_haritası`](yol_haritasi.md).

| M | Ad | Sorumlu | Makine | Bekler |
|---|---|---|---|---|
| K | Kurulum ve doğrulama | Ömer Faruk GÜNER | 7950X | — |
| M0 | Sözleşmeler | Ömer Faruk GÜNER | 7950X | K |
| M1 | Tek araç iskeleti | Ömer Faruk GÜNER | 7950X | M0 |
| M2 | Üç araç | Ömer Faruk GÜNER | 7950X | M1 |
| M3 | Merkezi mod ve izleme | Ömer Faruk GÜNER | 7950X | M2 |
| M4 | Veri hattı | Ömer Faruk GÜNER | 7950X | M1 |
| M5 | Model | Ömer Faruk GÜNER | 7950X | M4 |
| M6a | Değerlendirme ve analiz yazılımı | Miraç BOZACIOĞLU | 8945HX | M0 |
| M6b | Bütünleşik koşu ve kabul testleri | Ömer Faruk GÜNER | 7950X | M3, M5, M6a |
| M7 | Pilotlar ve kilit | Ömer Faruk GÜNER | 7950X | M6a, M6b |
| M8a | Ana deneyler | Ömer Faruk GÜNER | 7950X | M7 |
| M8b | Analiz ve rapor | Miraç BOZACIOĞLU | 8945HX | M8a |

Bağımlılık gerekçeleri: **M6b → M6a:** C9 (precision, FP/görev) için B18 eşleştirmesi gerekir. **M7 → M6a:** karar kuralı kodu protokol kilidinden önce yazılıp sınanmış olmalıdır (FR-30). **M4 → M1:** alan kilidi (U23).

## Paket ağırlıkları

Madde, kimliğinin harfiyle (K, A, B, C, D, E) bir iş paketine aittir; paket ağırlıkları el kitabındaki resmî yüzdelerdir (toplam 100). Maddeler aşağıda paketlere göre değil kilometre taşlarına göre gruplanır.

| Paket | Tarih | Ad | Ağırlık |
|---|---|---|---|
| K | 1 Şubat 2027 - 14 Şubat 2027 | Kurulum ve doğrulama testleri | 10 |
| A | 15 Şubat 2027 - 21 Mart 2027 | Veri ve model | 20 |
| B | 15 Şubat 2027 - 21 Mart 2027 | Sürü yazılımı | 25 |
| C | 22 Mart 2027 - 18 Nisan 2027 | Kabul testleri ve pilot koşular | 20 |
| D | 19 Nisan 2027 - 9 Mayıs 2027 | Ana deneyler | 15 |
| E | 10 Mayıs 2027 - 28 Mayıs 2027 | Analiz ve raporlama | 10 |

## K · Kurulum ve doğrulama

- [x] **K1** · w2 · K · geliştirme · Temel yazılım kurulumu · Ubuntu 24.04, ROS 2 Jazzy, Gazebo Harmonic 8.15, PX4 v1.16.0, MAVSDK-Python 3.17.4 + mavsdk_server kurulumu; Gazebo grafik arayüzsüz, yalnız sunucu modunda çalışır · FR-31 · Bitti: `verify_all.sh` hepsi `(+)`, sıfırdan kurulum yeniden üretildi
- [x] **K2a** · w1 · K · geliştirme · Ortam kilidi ve özet listesi · Ortam kilidi: sürümler (`versions.env`), Python kilidi (pip `-c`, PyTorch/Ultralytics dahil), PX4 commit kaydı, SHA-256 özet listesi, kurulum raporu · FR-31 · Bitti: `lock_ozet.sh --check` `(+)`, venv kilitle birebir aynı
- [x] **K2b** · w1 · K · geliştirme · apt ve NVIDIA sürüm kaydı · Ortam kilidi: apt paketlerinin ve NVIDIA sürücüsü/CUDA bileşenlerinin **tam sürüm listesi** kaydı · FR-31 · Bitti: liste depoda ve `lock_ozet`'e dahil
- [x] **K3** · w1 · K · geliştirme · GPU ve CUDA uyum testi · NVIDIA sürücüsü, CUDA ve PyTorch CUDA derlemesi uyum testi (RTX 5070, sm_120) · GŞÖA 6.2 · Bitti: `torch.cuda` GPU matris çarpımı CPU ile uyuşuyor, sürüm sabit
- [x] **K4** · w1 · K · geliştirme · Ultralytics ve MAVSDK sürüm kilidi · Ultralytics (8.4.210) ve MAVSDK-Python (3.17.4) sürümlerinin birlikte çalışma testinde sabitlenmesi · FR-31 · Bitti: sürümler `versions.env` ve kilitte, duman testleri geçti
- [x] **K5** · w1 · K · geliştirme · gz-transport Python doğrulaması · gz-transport Python bağlamalarının çalıştığının doğrulanması (gerçek mesaj alışverişi) · GŞÖA 5.3 · Bitti: `/clock` ve `Image` gidiş-dönüş testi geçti (`protobuf` 7.36.2)
- [x] **K6** · w1 · K · geliştirme · Fast DDS profili · Fast DDS XML profili (yalnız UDPv4; SHM, data-sharing, intraprocess kapalı; sabit tek yayın keşif) ve ROS 2 tarafından uygulandığının doğrulanması · FR-21 · Bitti: profil depoda, uygulandığı testle gösterilir
- [x] **K7** · w2 · K · geliştirme · Bağlantı ve kimlik testleri · Tek araç ve üç araç bağlantı/kimlik testleri: MAV_SYS_ID 1–3, UDP 14540–14542, gRPC 20051–20053, ad alanı /uav_1–/uav_3, beklenen sistem kimliği doğrulanmadan komut yok · FR-2, FR-8 · Bitti: kabul tablosu "Tek araç" ve "Üç araç" geçer
- [x] **K8** · w1 · K · geliştirme · Simülasyon ve PX4 zaman ekseni · Tek araç: simülasyon zamanı ile PX4 zaman damgalarının aynı eksende olduğunun doğrulanması · FR-17 · Bitti: test kaydı
- [x] **K9** · w1 · K · geliştirme · Kamera damga ve sıra ölçümü · Tek araç: Gazebo kamera damgalarının 0,5 s'nin tam katı ve karelerin sırayla teslim edildiğinin doğrulanması; doğrulanmazsa iki mod için yedek yola geçiş kararı · FR-10, FR-11 · Bitti: sonuç ve karar kaydı
- [x] **K10** · w1 · K · geliştirme · Kamera görüş açısı kilidi · Kameranın yatay görüş açısının 30 m'den hedef piksel boyutu ölçülerek belirlenmesi ve 3. hafta başında kilitlenmesi · GŞÖA 5.2 · Bitti: değer `config/deney.env`'de kilitli (protokol kilidine C13'te girer)
- [x] **K11** · w2 · K · geliştirme · Üç araç yük ölçümü · Üç araç + üç kamera + üç GPU işçisi + Gazebo birlikte: işçi başına kare/s, gerçek zaman faktörü, GPU belleği ölçümü (nms=False) · FR-15, FR-24 · Bitti: ölçüm kaydı
- [x] **K12** · w1 · K · geliştirme · GPU/CPU kararı · GPU/CPU kararı: araç başına 2 kare/s sağlanıyor mu; sağlanmıyorsa YOLO26s + ONNX Runtime CPU hız ölçümü, NMS'siz çıktı kontrolü, B planı kararı · FR-15 · Bitti: karar protokole yazılır
- [x] **K13** · w1 · K · geliştirme · Eğitim batch denemesi · Eğitim denemesi: batch=16 GPU belleğine sığıyor mu (sığmazsa bellek ölçütüyle en büyük değer), eğitim içi doğrulama nms=False kullanıyor mu · GŞÖA 6.2 · Bitti: değer kilitlenir
- [x] **B16** · w1 · K · geliştirme · Ağ emülasyonu betiği · Ağ emülasyonu betiği: loopback 10.10.0.0/24, tek ortak htb sınırlayıcı 25 Mbit/s, bayt sınırlı FIFO, geri alma ve doğrulama · FR-20 · Bitti: `--verify` 16/16, sürü ağı ≈ 25 Mbit/s, yerel trafik sınırsız
- [x] **B17** · w1 · K · geliştirme · Kuyruk sınırı 4 MiB · Sınırlayıcı kuyruk sınırının el kitabındaki öngörülen değere (4 MiB) getirilmesi ve yeniden doğrulanması (eskiden yapılandırmada 256 KiB idi) · FR-20 · Bitti: `config/deney.env` 4 MiB, `--verify` geçer; kesin değer pilotta kilitlenir
- [x] **B20** · w1 · K · geliştirme · Yapılandırma ağ bölümü · Deney yapılandırma dosyasının ağ ve port bölümü (adresler, kuyruk, portlar, kimlikler) · GŞÖA 5.1 · Bitti: `config/deney.env` `source` ile yüklenir, betikler buradan okur

## M0 · Sözleşmeler

- [x] **B1** · w2 · M0 · geliştirme · swarm_msgs mesaj paketi · `swarm_msgs`: durum, görev, tarama başlatma/bitiş, COMPLETE, kare sonucu, "kare alınamadı", komut (araç kimliği, sıra numarası, onay durumu) mesaj tanımları · FR-2, FR-3, FR-4, FR-12 · Bitti: paket derlenir, mesajlar tanımlı

## M1 · Tek araç iskeleti

- [x] **B3** · w3 · M1 · geliştirme · PX4 bağdaştırıcısı · `px4_adapter`: araç başına ayrı MAVSDK System ve mavsdk_server; sistem kimliği doğrulaması; rotanın yerden 30 m görev (mission) olarak yüklenmesi; PX4'e komut yazan tek modül · FR-7, FR-8 · Bitti: üç araçta görev yüklenir ve başlatılır
- [x] **B4** · w3 · M1 · geliştirme · Araç süreci ve durum makinesi · Araç süreci (`swarm_vehicle`): tek ROS 2 düğümü /uav_N, durum/görev modülü, 2 Hz durum, diğer iki aracın durumunu alma ve kaydetme, durum makinesi (HAZIR → BARİYER_BEKLE → TARAMA → WAIT → TAMAMLANDI) · FR-2, FR-4 · Bitti: durum geçişleri test edilir
- [x] **B6** · w1 · M1 · geliştirme · Araç kamerası · Araç gövdesine sabit, aşağı bakan kamera (640 × 480 RGB8, sıkıştırmasız, 2 kare/s) ve kalibrasyon dosyası · FR-9 · Bitti: üç araçta kare üretimi
- [x] **B7** · w2 · M1 · geliştirme · Gazebo damga bileşeni · Gazebo sunucusunda damga bileşeni: araç kimliği, simülasyon zamanı, kare numarası (n = 2·t_sim), üretim anının monotonik zamanı · FR-10, FR-23 · Bitti: kayıtlar kamera alıcısıyla birleşir
- [x] **B8** · w3 · M1 · geliştirme · Kamera alıcısı · Kamera alıcısı: gz-transport doğrudan abone (ros_gz_bridge yok), kare numaralandırma, "kare alınamadı" ve "geç geldi" kuralları; damgalar doğrulanmazsa yedek yol · FR-10, FR-11 · Bitti: kayıp ve geç gelen kare senaryoları testli
- [x] **B9** · w3 · M1 · geliştirme · Çıkarım işçisi · Çıkarım işçisi (alt süreç, IP kullanmayan yerel kanal): YOLO26L, GPU, FP32, batch=1, nms=False, güven 0,25; B planında YOLO26s + ONNX Runtime CPU · FR-13, FR-15, FR-16 · Bitti: iki yolda aynı sonuç yapısı
- [x] **B10** · w1 · M1 · geliştirme · Kare sonuç iletisi · Kare sonuç iletisi: tespit yoksa açık "tespit yok", işlem hatası ve "kare alınamadı" "tespit yok" olarak kodlanmaz · FR-12 · Bitti: üç durum ayrı testli
- [x] **B2** · w2 · M1 · geliştirme · Bölgeler ve şerit rotaları · Alanın üç çakışmayan tarama bölgesine ayrılması, şerit planı (w = 2·30·tan(görüş açısı/2), komşu izler ≥ 2 m örtüşür), rota dosyaları · FR-1 · Bitti: bölge ve rota dosyaları tüm sahnelerde aynı

## M2 · Üç araç

- [x] **B11** · w2 · M2 · geliştirme · Uçta mod iletişimi · Uçta mod: kare sonuçları, "kare alınamadı" kayıtları reliable DDS QoS ile; durum ve görev mesajları DDS ile · FR-13 · Bitti: yer istasyonunda alınır
- [x] **B5** · w3 · M2 · geliştirme · Yer istasyonu koordinatörü · Yer istasyonu (`swarm_gcs`): `/gcs/mission_coordinator` (hazır bildirimleri, başlangıç bariyeri, t0; COMPLETE koşulları, t1), izleme ve komut arayüzü · FR-3, FR-5 · Bitti: t0 ve t1 doğru anlarda yayımlanır

## M3 · Merkezi mod ve izleme

- [x] **B12** · w3 · M3 · geliştirme · Merkezi mod · Merkezi mod: araç başına TCP kanalı, sıkıştırmasız görüntü, geri basınçta kare atılmaz; her iletide araç kimliği, kare numarası, simülasyon zamanı, kamera kalibrasyon kimliği ve kare üretim anına eşlenmiş canlı PX4 konum/yönelim tahmini; yer istasyonunda üç çıkarım işçisi · FR-14 · Bitti: üç araç akışı kayıpsız
- [x] **B13** · w2 · M3 · geliştirme · Disk kuyrukları ve aşama damgaları · Disk destekli uygulama kuyrukları; kare başına aşama zaman damgaları (üretim, kuyruğa giriş, aktarım, çıkarım başı/sonu, kullanılabilirlik) · GŞÖA 6.8 · Bitti: kapasite taşması sessiz kare atlamaz
- [x] **B14** · w3 · M3 · geliştirme · Poz enterpolasyonu ve konum hesabı · Kare–poz enterpolasyonu (konum doğrusal, yönelim küresel) ve konum hesaplayıcı (NED→ENU, kutu merkezinden ışın–zemin kesişimi, aralık sınırı 100 ms); telemetri yüksek hızda alınıp kaynak zamanına göre saklanır, merkezde gecikmiş kare 2 Hz durum mesajıyla konumlandırılmaz · FR-17, FR-18 · Bitti: bilinen pozda konum hatası < 5 m
- [ ] **B15** · w2 · M3 · geliştirme · Hedef birleştirme · Hedef birleştirme: üretim zamanına göre işleme, aynı sınıf ve ilk konuma ≤ 2,5 m ise aday, en yüksek güvenli tespitin konumu · FR-19 · Bitti: birim testleri

## M4 · Veri hattı

- [ ] **A1** · w3 · M4 · geliştirme · Sahne üreticisi · Gazebo sahne üreticisi: iki sınıf (görünür insan, görünür enkaz yığını); ışık, konum, yönelim tohumla; kısmi örtülme yok; hedefler birbirini örtmez · FR-16, FR-26 · Bitti: tohumdan aynı sahne yeniden üretilir; seçilen insan ve enkaz modelleriyle K10 piksel ölçümü tekrarlandı ve sonuç depo sahibine bildirildi (kararlar.md)
- [ ] **A2** · w2 · M4 · geliştirme · Eğitim, doğrulama, test sahneleri · 60 eğitim + 10 doğrulama + 30 test sahnesi; yerleşim, tohum ve görünüm varyantı bölümler arasında ayrık; test hedef merkezleri ≥ 10 m; test sahnesinde 15 insan + 15 enkaz · FR-26 · Bitti: bölümler ayrık, listeler SHA-256'lı
- [ ] **A3** · w2 · M4 · geliştirme · Etiket üretim yöntemi · Etiket üretimi: Gazebo sınır kutusu kamerası (olmazsa hedef sınır kutularının izdüşümü); yöntem pilotta kilitlenir · GŞÖA 6.1 · Bitti: yöntem seçildi ve kilitlendi
- [ ] **A4a** · w1 · M4 · geliştirme · Görüntü ve etiket üretim kodu · 7.200 eğitim + 1.200 doğrulama görüntüsünü ve etiketlerini üreten kod (yerden 30 m, test koşularıyla aynı kamera ayarları) · GŞÖA 6.2 · Bitti: kod bir deneme kümesini üretir; aynı tohumla görüntü ve etiketler yeniden üretilir
- [ ] **A4b** · w1 · M4 · çalıştırma · Eğitim ve doğrulama görüntüleri üretimi · 7.200 eğitim + 1.200 doğrulama görüntüsü ve etiketlerinin üretimi, yerden 30 m, test koşularıyla aynı kamera ayarları · GŞÖA 6.2 · Bitti: sayılar tamam, listeler kayıtlı
- [ ] **A5** · w1 · M4 · çalıştırma · Etiket görsel kontrolü · Etiketlerin %10'u sahne ve sınıf bazında tabakalı görsel kontrol; sistematik hata ilgili bölümün tümünde düzeltilir · GŞÖA 6.1 · Bitti: kontrol kaydı

## M5 · Model

- [ ] **A7** · w1 · M5 · çalıştırma · Eğitim süresi pilotu · Eğitim süresinin pilotta ölçülmesi, 14 haftalık takvime uygunluk değerlendirmesi (not: ön tahmin A4a'nın deneme kümesiyle M4 sürerken yapılabilir; kesin ölçüm A4b'den sonra tam veriyle) · GŞÖA 6.2 · Bitti: ölçüm kaydı
- [ ] **A9** · w2 · M5 · çalıştırma · B planı modeli eğitimi · B veri planı modeli (yalnız Gazebo) aynı ayarlarla eğitimi; eğitim çağrısında `nms=False` açıkça verilir (K13 bulgusu: verilmezse eğitim içi doğrulama NMS'li) · FR-15, FR-16 · Bitti: her epoch ağırlığı saklı
- [ ] **A10** · w1 · M5 · çalıştırma · Epoch seçimi · Epoch seçimi: Gazebo doğrulama sahnelerinde iki sınıf ortalama AP50'yi en çoklayan epoch (eşitlikte erken) · GŞÖA 6 · Bitti: B modeli için (A planı yapılırsa onun için de) seçilen epoch kayıtlı
- [ ] **A13** · w1 · M5 · çalıştırma · Model ve veri özetleri · Model ve veri dosyalarının nihai SHA-256 özetleri (6. hafta sonu) · FR-31 · Bitti: özet listesi kilitli
- [ ] **A6** · w0 · M5 · çalıştırma · Hazır veri seti · (isteğe bağlı) Hazır veri seti: akademik lisanslı, havadan çekilmiş; künye, lisans, SHA-256; sınıf eşleme tablosu ve örneklem kontrolü; yalnız eğitim bölümüne · GŞÖA 6.1 · Bitti: künye ve eşleme protokole yazılı
- [ ] **A8** · w0 · M5 · çalıştırma · A planı modeli eğitimi · (isteğe bağlı, ana deneylerden sonra, model kilidini değiştirmez) A veri planı modeli (hazır veri + Gazebo) eğitimi: 50 epoch, batch=16, 640, nms=False (eğitim çağrısında `nms=False` açıkça verilir; verilmezse eğitim içi doğrulama NMS'li başlıkla çalışır, K13 bulgusu), save_period=1 · FR-15, FR-16 · Bitti: her epoch ağırlığı saklı
- [ ] **A11** · w0 · M5 · çalıştırma · Veri planı kaydı · Veri planı (kullanıcı kararı): **B planı (yalnız Gazebo) birinci öncelik ve sabittir**; A planı isteğe bağlı ek deney olarak yalnız zaman kalırsa, ana deneylerden sonra denenir ve sonucu (beklenen/düşük çıkması dahil, önceden varsayılmadan) raporlanır; ana deneylerde kullanılan model kilidini ve seçimi değiştirmez · GŞÖA 6 · Bitti: karar ve gerekçe kayıtlı; A uygulanırsa ek analiz tablosu

## M6a · Değerlendirme ve analiz yazılımı

- [ ] **B18** · w2 · M6a · geliştirme · Değerlendirme yazılımı · Değerlendirme yazılımı: sınıf ve ≤ 5 m şartıyla Macar algoritmasıyla bire bir atama; TP, FP, FN, R, precision · FR-28 · Bitti: sentetik örneklerde doğru
- [ ] **E1a** · w1 · M6a · geliştirme · Eşleştirme analiz betiği · Hedef eşleştirme ve R, precision, FP; iki mod için mutlak ve sınıf bazlı (betik; sentetik veriyle sınanmış) · FR-24, FR-28 · Bitti: betik sentetik örneklerde beklenen çıktıyı üretir, biçim sabit
- [ ] **E2a** · w1 · M6a · geliştirme · İyileşme analiz betiği · D, B, T için sahne başına yüzde iyileşme; L için medyan ve 95. yüzdelik farkları (betik; sentetik veriyle sınanmış) · FR-29 · Bitti: betik sentetik örneklerde beklenen çıktıyı üretir, biçim sabit
- [ ] **E3a** · w1 · M6a · geliştirme · Bootstrap betiği · %95 percentile bootstrap, 10.000 yeniden örnekleme, eşleştirme bozulmadan (betik; sentetik veriyle sınanmış) · FR-29 · Bitti: betik sentetik örneklerde beklenen çıktıyı üretir, biçim sabit
- [ ] **E4a** · w1 · M6a · geliştirme · Karar kuralı betiği · Ölçüt ölçüt karar kuralı; R için üç sonuçlu kural; tek ortak başarı kararı yok; "fark gösterilemedi" eşdeğerlik değil (betik; sentetik veriyle sınanmış) · FR-30 · Bitti: betik sentetik örneklerde beklenen çıktıyı üretir, biçim sabit
- [ ] **E5a** · w1 · M6a · geliştirme · Sansürlü koşu betiği · Tamamlanamayan koşular: sansürlü süre gösterimi, kısmi trafik, tamamlanan çiftlerle koşullu analiz (betik; sentetik veriyle sınanmış) · FR-27 · Bitti: betik sentetik örneklerde beklenen çıktıyı üretir, biçim sabit

## M6b · Bütünleşik koşu ve kabul testleri

- [ ] **B19** · w3 · M6b · geliştirme · Bütünleşik işlev testi · Bütünleşik işlev testi, iki modda: bölge paylaşımı, ortak başlangıç, ilerleme bildirimi, ortak tamamlanma; her görev karesi için sonuç veya "kare alınamadı" (not: koşular sahne dünya dosyasıyla yapılır; sahne yükleme yeteneği bu maddede, B21 yalnız ayarları tek dosyada toplar) · FR-1, FR-2, FR-3, FR-4, FR-5 · Bitti: iki modda tam koşu tamamlanır
- [ ] **C1** · w1 · M6b · geliştirme · Kabul testi 1: ağ adresleri · Ağ sınırı kabul testi 1: ölçülen DDS ve görüntü kanalı soketleri yalnız 10.10.0.x adreslerini kullanır · FR-25 · Bitti: süreç ve soket kaydı
- [ ] **C2** · w2 · M6b · geliştirme · Kabul testi 2: yerel trafik · Kabul testi 2: yerel trafik üretilirken D sayacı artmaz; yer istasyonu bileşenleri ve çıkarım alt süreçlerinde DDS yok · FR-25 · Bitti: sayaç ve ROS 2 çizge kaydı
- [ ] **C3** · w1 · M6b · geliştirme · Kabul testi 3: sınırlayıcı sayacı · Kabul testi 3: bilinen boyutlu gönderim sınırlayıcıdan geçer, bir kez sayılır, burst ≥ en büyük paket · FR-25 · Bitti: sayaç = gönderilen
- [ ] **C4** · w2 · M6b · geliştirme · Kabul testi 4: sayaç ve kayıtlar · Kabul testi 4: sayaçlar ile kare ve mesaj sıra kayıtları karşılaştırılır, açıklanmamış boşluk yok · FR-25, FR-22 · Bitti: boşluklar açıklanmış
- [ ] **C5** · w2 · M6b · geliştirme · Kabul testi 5: paket düşürme · Kabul testi 5: eşleşmeden sonra %100 paket düşürme, her iki modda; uygulama teslimi durur, Gazebo–PX4/MAVLink sürer, kaldırılınca devam eder · FR-25 · Bitti: iki modda geçti
- [ ] **C6** · w3 · M6b · geliştirme · Uç–merkez kaynak eşitliği · Uç/merkez ve kaynak eşitliği doğrulaması: aynı sahne, rota, tohum, kamera, ağırlık özeti, GPU, FP32, batch, nms=False, güven; bellek ve GPU kayıtları · GŞÖA 5.3 · Bitti: kabul tablosu satırı geçer
- [ ] **C7** · w2 · M6b · geliştirme · İşçi CPU eşlemesi · İşçi CPU eşlemesi: işçi başına aynı fiziksel çekirdeğe ait iki mantıksal CPU, çakışmasız, diğer süreçler dışarıda; iki modda aynı eşleme · GŞÖA 5.2 · Bitti: eşleme kaydı
- [ ] **C8** · w2 · M6b · geliştirme · D ölçümü · D ölçümü: t0 ve t1 anlarında sınırlayıcı gönderilmiş bayt sayaçları; COMPLETE baytları ayrı · FR-22 · Bitti: D, T, B hesaplanır
- [ ] **C9** · w2 · M6b · geliştirme · L ölçümü ve ek çıktılar · L ölçümü ve ek çıktılar (precision, FP/görev, konum hatası, tamamlanamayan oranı, hazırlık süresi, RTF, kare sayısı, GPU kullanımı/belleği) · FR-23, FR-24 · Bitti: kayıtlar üretilir

## M7 · Pilotlar ve kilit

- [ ] **B21** · w1 · M7 · geliştirme · Yapılandırma genişletmesi · Deney yapılandırma dosyasının genişletilmesi: sahne, rota, model, koşu, çıkarım ayarları · GŞÖA 5.1 · Bitti: tüm başlatma dosyaları tek dosyadan okur
- [ ] **C10** · w2 · M7 · çalıştırma · Kuyruk sınırı pilotu · Ayar pilotları: ortak FIFO kuyruk sınırının kesin değeri · FR-20 · Bitti: değer pilotla belirlenip kilitlenir
- [ ] **C14** · w2 · M7 · geliştirme · Koşu otomasyonu · Koşu otomasyonu: 30 sahne × 2 mod, çift içi sıra kaydedilen rastgele tohumla, eşzamanlı çalıştırma yok, eğitim de ana koşularla eşzamanlı yapılmaz, başlatma dosyaları tek yapılandırmadan · FR-26 · Bitti: tam bir çift otomatik koşar
- [ ] **C11** · w3 · M7 · çalıştırma · Nihai yapılandırma pilotları · Nihai yapılandırmayla pilotlar: 3 doğrulama sahnesi × 2 mod = 6 koşu; rota uzunluğu, hız, tarama süresi, RTF; her hedef ≥ 1 karenin görüş alanında · FR-27 · Bitti: 6 pilot tamam
- [ ] **C12** · w1 · M7 · çalıştırma · H hesabı · Tp, Sp, Dp ve H = 60·⌈2·max(Tp, Sp + 8Dp/C)/60⌉ hesabı · FR-27 · Bitti: H kilitli
- [ ] **A12** · w1 · M7 · geliştirme · Çıkarım ayarları kilidi · Çıkarım ayarlarının sabitlenmesi: güven 0,25; nms=False; max_det 300; FP32; batch=1 · FR-15 · Bitti: protokol kilidinde
- [ ] **C13** · w2 · M7 · çalıştırma · Protokol ve ortam kilidi · Kalan protokol değerleri (telemetri aralık sınırı vb.); ortam kilidi ve protokol kilidi (etiketli commit + SHA-256 listesi) · FR-31 · Bitti: etiket atılmış, kilit tamam

## M8a · Ana deneyler

- [ ] **D1** · w4 · M8a · çalıştırma · Ana koşular 1–10 · Ana koşular: sahne 1–10 (her biri iki modda) · FR-26, FR-27 · Bitti: her koşu tamamlanmış ya da "tamamlanamadı" kayıtlı
- [ ] **D2** · w4 · M8a · çalıştırma · Ana koşular 11–20 · Ana koşular: sahne 11–20 · FR-26, FR-27 · Bitti: aynı
- [ ] **D3** · w4 · M8a · çalıştırma · Ana koşular 21–30 · Ana koşular: sahne 21–30 · FR-26, FR-27 · Bitti: aynı
- [ ] **D4** · w1 · M8a · çalıştırma · Yeniden koşular ve kayıt · Teknik geçersizlik halinde ilgili çiftin iki mod için yeniden çalıştırılması; tamamlanamayan koşuların kaydı (dışlama yok) · FR-27 · Bitti: kayıtlar eksiksiz
- [ ] **D5** · w1 · M8a · çalıştırma · Veri bütünlüğü · Koşu verilerinin bütünlüğü: dosya özetleri, sayaç–kayıt tutarlılığı · FR-31 · Bitti: özet listesi

## M8b · Analiz ve rapor

- [ ] **E1b** · w1 · M8b · çalıştırma · Eşleştirme analizi, gerçek veri · Hedef eşleştirme ve R, precision, FP; iki mod için mutlak ve sınıf bazlı (gerçek ana koşu verileriyle) · FR-24, FR-28 · Bitti: tablo
- [ ] **E2b** · w1 · M8b · çalıştırma · İyileşme analizi, gerçek veri · D, B, T için sahne başına yüzde iyileşme; L için medyan ve 95. yüzdelik farkları (gerçek ana koşu verileriyle) · FR-29 · Bitti: tablo
- [ ] **E3b** · w1 · M8b · çalıştırma · Bootstrap, gerçek veri · %95 percentile bootstrap, 10.000 yeniden örnekleme, eşleştirme bozulmadan (gerçek ana koşu verileriyle) · FR-29 · Bitti: güven aralıkları
- [ ] **E4b** · w1 · M8b · çalıştırma · Karar tablosu, gerçek veri · Ölçüt ölçüt karar kuralı; R için üç sonuçlu kural; tek ortak başarı kararı yok; "fark gösterilemedi" eşdeğerlik değil (gerçek ana koşu verileriyle) · FR-30 · Bitti: karar tablosu
- [ ] **E5b** · w1 · M8b · çalıştırma · Sansürlü koşu analizi, gerçek veri · Tamamlanamayan koşular: sansürlü süre gösterimi, kısmi trafik, tamamlanan çiftlerle koşullu analiz (gerçek ana koşu verileriyle) · FR-27 · Bitti: tablo
- [ ] **E6** · w1 · M8b · çalıştırma · Ek ölçülerin incelenmesi · RTF, kare sayısı, rota sapması, konum hatası ve birleştirme hatalarının incelenmesi · GŞÖA 6.8 · Bitti: inceleme notu
- [ ] **E7** · w2 · M8b · çalıştırma · Sonuç raporu · Sonuçların raporlanması (simülasyon sınırları ve varsayımlar açıkça belirtilerek) · FR-30 · Bitti: rapor
