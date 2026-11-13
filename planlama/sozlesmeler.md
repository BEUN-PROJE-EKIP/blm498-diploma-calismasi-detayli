# Sözleşme dosyaları: sahne, bölge/rota, kamera kalibrasyonu, hedef listesi

Bu belge, sürü yazılımı ile veri üretim hattının **ortak kullandığı dosya biçimlerini** sabitler. Proje el kitabı ve GŞÖA bu dosyaların yalnızca varlığını ve içereceği bilgiyi söyler ("sahne dosyası hedef kimliklerini, sınıflarını ve konumlarını içerir"); **alanlar, birimler ve dosya biçimi belgede yazılı değildir** ve burada tasarlanmıştır. Belgede yazılı olan her kural **[belge]**, burada seçilen her değer **[varsayım]** olarak işaretlidir; varsayımlar pilotlarda doğrulanır veya değişir, [belge] kuralları değişmez.

Doğrulayıcı: `araclar/sozlesme_dogrula.py` (yalnız standart kitaplık). Eşikler ve aralıklar `config/deney.env` içindeki anahtarlardan okunur; bu belge yalnız biçimi anlatır. Örnekler: `config/ornek/` (geçerli) ve `config/ornek/bozuk/` (doğrulayıcının reddetmesi gereken). Test: `./setup/sozlesme_testi.sh`.

## 1. Genel kurallar

- **Dosya biçimi:** UTF-8 JSON, tek nesne. Her dosyada `surum` (şimdi `1`) ve `tur` bulunur; bilinmeyen alan **hatadır** (yazım hatalarını yakalamak için).
- **Kimlikler:** 1–64 karakter, yalnız harf, rakam, `_` ve `-`.
- **Koordinat çerçevesi (yerel ENU):** orijin alanın merkezi; `x` = doğu (E), `y` = kuzey (N), `z` = yukarı (U); birim metre. Yer düzlemi `z = 0`. PX4 NED çıktısı bu çerçeveye açıkça çevrilir [belge: NED→ENU dönüşümü açık yapılır].
- **Yönelim (hedefler):** derece, [0, 360); yerel ENU'da `+x` (doğu) ekseninden **saat yönünün tersine** ölçülür (yer düzleminde matematiksel açı).
- **Yazı kuralları:** sayılar JSON sayısıdır; ondalık ayracı nokta.

## 2. Sahne dosyası (`tur: "sahne"`)

| Alan | Tür / aralık | Açıklama |
|---|---|---|
| `surum`, `tur` | `1`, `"sahne"` | |
| `sahne_kimligi` | kimlik | Örn. `S-TEST-0001`. |
| `bolum` | `egitim` \| `dogrulama` \| `test` | [belge] Üç veri bölümü. |
| `tohum` | tam sayı ≥ 0 | Sahneyi üreten rastgele tohum [belge: tohumlar bölümler arasında ayrılır]. |
| `alan` | nesne | `cerceve: "yerel_ENU"`, `merkez_m: [0, 0]`, `genislik_m`, `yukseklik_m`. **Bütün sahnelerde yapılandırmadaki alanla aynıdır** (`ALAN_*`). [varsayım] 300 m × 300 m: `x ∈ [−150, 150]`, `y ∈ [−150, 150]`. |
| `isik` | nesne | `gunes_azimut_derece` ∈ [0, 360) (yerel ENU'da `+x` ekseninden saat yönünün tersine, güneşin bulunduğu yön), `gunes_yukseklik_derece` ∈ [`SAHNE_GUNES_YUKSEKLIK_MIN/MAKS_DERECE`] (20–85, [varsayım]). Işık tohumla değişir [belge]. |
| `zemin` | nesne | `gorunum_varyanti` ∈ `SAHNE_ZEMIN_VARYANTLARI` ([varsayım] `zemin_a/b/c`). |
| `hedefler` | liste | Aşağıda. |

**Hedef** (`hedefler[i]`):

| Alan | Açıklama |
|---|---|
| `kimlik` | Sahne içinde tekil (örn. `H01`). |
| `sinif` | `insan` \| `enkaz` [belge: görünür insan, görünür enkaz yığını]. |
| `x`, `y` | Hedef merkezi, yerel ENU metre. Alan kenarından en az `ALAN_KENAR_PAYI_M` içeride ([varsayım] 5 m). |
| `yonelim_derece` | Yönelim (yukarıdaki kural). |
| `gorunum_varyanti` | Sınıfa özel doku/renk varyantı (`SAHNE_INSAN_VARYANTLARI`, `SAHNE_ENKAZ_VARYANTLARI`; [varsayım] `insan_a/b/c/test`, `enkaz_a/b/c/test`). [belge] Her sınıfın en az bir varyantı **yalnız test bölümünde** kullanılır: `SAHNE_TEST_OZEL_*` varyantları (`insan_test`, `enkaz_test`) eğitim ve doğrulama sahnelerinde bulunamaz. |

**Kurallar:**
- [belge] Test sahnesinde **15 insan + 15 enkaz** (toplam 30) ve hedef merkezleri arası **en az 10 m**.
- [belge] Hedefler birbirini örtmez; kasıtlı kısmi örtülme yoktur. Bu, merkezler arası uzaklık kuralıyla sağlanır; ayrıca sahne üretici hedefleri görüş hattını kesen yapı koymaz (üretici kapsamı).
- [varsayım] Eğitim/doğrulama sahnesinde her sınıftan en az 1, toplam en çok 40 hedef; merkezler arası en az 6 m (`SAHNE_MERKEZ_MESAFE_DIGER_M`, `SAHNE_DIGER_HEDEF_MAKS`).
- Hedefler alanın içindedir (kenar payı ile).

Örnek (kısaltılmış; tam dosya: `config/ornek/sahne_ornek_test.json`):

```json
{
  "surum": 1, "tur": "sahne", "sahne_kimligi": "S-TEST-0001", "bolum": "test", "tohum": 20260001,
  "alan": {"cerceve": "yerel_ENU", "merkez_m": [0, 0], "genislik_m": 300, "yukseklik_m": 300},
  "isik": {"gunes_azimut_derece": 135.0, "gunes_yukseklik_derece": 55.0},
  "zemin": {"gorunum_varyanti": "zemin_b"},
  "hedefler": [
    {"kimlik": "H01", "sinif": "insan", "x": -9.77, "y": 99.13, "yonelim_derece": 59.0, "gorunum_varyanti": "insan_a"}
  ]
}
```

## 3. Bölge ve rota dosyası (`tur: "bolge_rota"`)

[belge] Alan **üç çakışmayan bölgeye** ayrılır; her araca bir bölge ve **sabit rota**; düzen **bütün pilot ve ana koşu sahnelerinde aynıdır** (bu yüzden dosya sahne dosyasından bağımsızdır). [belge] İrtifa yerden 30 m sabit. [belge] Komşu şerit izleri **en az 2 m örtüşür**, rota bölgenin tamamını kapsar, iz genişliği `w = 2 · 30 · tan(HFOV / 2)`, HFOV `CAM_HFOV_RAD` (kilitli 65°) → `w = 38,224 m`.

| Alan | Açıklama |
|---|---|
| `alan` | Sahne dosyasındakiyle aynı. |
| `irtifa_m` | `ROTA_IRTIFA_M` (30) ile aynı. |
| `hiz_ms` | `ROTA_HIZ_MS` ile aynı pozitif sayı. [varsayım] Geçici 5 m/s; belgede sayısal değer yok, pilotta (M7) belirlenip kilitlenir. |
| `serit` | `hfov_derece` (= `CAM_HFOV_DEG`), `iz_genisligi_m` (= `w`, ±0,01), `ortusme_min_m` (≥ `ROTA_ORTUSME_MIN_M`). |
| `bolgeler` | `ALAN_BOLGE_SAYISI` (3) dikdörtgen: `bolge_kimligi`, `arac_kimligi`, `x_min`, `x_max`, `y_min`, `y_max` (alan içinde, birbirini örtmeyen, **birlikte alanın tamamını kaplayan**). [varsayım] 100 m × 300 m şeritler: `B1` x ∈ [−150, −50], `B2` [−50, 50], `B3` [50, 150]. Her araç kimliği (`UAV_SYS_IDS`) tek bölgeye atanır. |
| `rotalar` | Araç başına bir rota: `arac_kimligi`, `noktalar` = `[[x, y], …]` (yerel ENU, m; irtifa `irtifa_m`). Tüm noktalar aracın bölgesindedir. |

**Şerit planı kuralı (doğrulanan):** rota, `y` boyunca giden (x sabit) tarama doğrularından oluşur. Doğruların merkezleri arası uzaklık `a` için komşu iz örtüşmesi `w − a ≥ 2 m`; ilk iz bölgenin sol kenarını (`merkez − w/2 ≤ x_min`), son iz sağ kenarını kapsar; iz boyunca ucu `y_min`/`y_max`'ı iz boyu yarı ayak iziyle (`w/2 · 480/640 = 14,33 m`) kapsar. Görüntünün yatay ekseni uçuş yönüne diktir [belge], bu yüzden iz genişliği `x` yönündedir. Örnekte her bölge 3 yılan (serpantin) izidir: merkezler `x_min + w/2`, ortası, `x_max − w/2` (komşu iz örtüşmesi 7,35 m).

**Üretim:** `config/bolge_rota.json`, `python3 araclar/rota_uret.py` ile `config/deney.env`'den üretilir (belirlenimci; `--check` dosyanın güncel olup olmadığını denetler); alan boyutu kilitli değildir (U23), bu yüzden dosya 1.7'de yeniden üretilebilir.

## 4. Kamera kalibrasyon dosyası (`tur: "kamera_kalibrasyon"`)

[belge] Kamera 640 × 480, gövdeye sabit, aşağı bakan; optik eksen gövdenin aşağı eksenine paralel, görüntünün yatay ekseni uçuş yönüne dik; kalibrasyon dosyasında **tek sabit kamera–araç dönüşümü** vardır ve iki modda aynıdır. [varsayım] Gerçek kalibrasyon yoktur: ideal iğne deliği modeli.

| Alan | Açıklama |
|---|---|
| `kalibrasyon_kimligi` | Örn. `KAL-65-640x480-v1`; kare kayıtları bu kimliği taşır [belge: kamera kalibrasyon kimliği]. |
| `kamera_kimligi` | Örn. `kamera_1`. |
| `cozunurluk` | `genislik_px` = 640, `yukseklik_px` = 480 (`CAM_WIDTH`, `CAM_HEIGHT`). |
| `hfov_derece` | `CAM_HFOV_DEG` (65, kilitli). |
| `ic_parametreler` | `fx = (genişlik/2) / tan(HFOV/2)` (= 502,2994), `fy = fx` (kare piksel), `cx = genişlik/2` (320), `cy = yükseklik/2` (240). Piksel koordinatı: orijin sol üst piksel köşesi, `x` sağa, `y` aşağı. |
| `bozulma` | `"yok"`. |
| `arac_kamera` | `arac_cercevesi: "FLU"` (x ileri, y sol, z yukarı), `kamera_cercevesi: "OpenCV"` (x sağ, y aşağı, z optik eksen ileri), `R` (3 × 3, kamera → gövde), `t_m` (gövde çerçevesinde kamera konumu). |

Aşağı bakan kamera için `R = [[0, −1, 0], [−1, 0, 0], [0, 0, −1]]` (kamera x → gövde −y; kamera y → gövde −x; optik eksen z → gövde −z). Görüntüde **yukarı = uçuş yönü (+x gövde)**, **sağ = gövdenin sağı**. Bu, ölçüm sahnesinde kullanılan düzenle (gövdeye `pitch +90°`) tutarlıdır. `t_m = [0, 0, KAL_KAMERA_KONUM_Z_M]` = `[0, 0, 0,10]` m (ölçüm sahnesindeki x500 + kamera düzeniyle aynı).

Dönüşüm: gövde çerçevesindeki nokta `p_gövde = R · p_kamera + t`. Yerde ENU'ya çevirme (kutu merkezinden çıkan ışının düz zeminle kesiştirilmesi) konum hesaplayıcının işidir [belge].

## 5. Hedef listesi (`tur: "hedef_listesi"`)

Etiket ve değerlendirme girdisi: sahne dosyasındaki hedeflerden **türetilen düz liste**; kayıt eşleştirmesi (kimlik, sınıf, konum) buna dayanır.

```json
{"surum": 1, "tur": "hedef_listesi", "sahne_kimligi": "S-TEST-0001", "bolum": "test",
 "hedefler": [{"kimlik": "H01", "sinif": "insan", "x": -9.77, "y": 99.13}]}
```

Üretim: `python3 araclar/sozlesme_dogrula.py --hedef-listesi-uret sahne.json` (geçerli sahne gerekir). Doğrulama: `--sahne sahne.json` verilirse liste, sahneden türetilenle **birebir aynı** olmalıdır.

## 6. Yapılandırma anahtarları (B21: tek dosya `config/deney.env`)

Mevcut anahtarlar (ağ, kimlik/port, kamera, çıkarım, eğitim) değişmedi. Eklenenler:

| Anahtar | Değer | Kaynak |
|---|---|---|
| `ALAN_MERKEZ_X_M`, `ALAN_MERKEZ_Y_M` | 0, 0 | varsayım |
| `ALAN_GENISLIK_M`, `ALAN_YUKSEKLIK_M` | 300, 300 | varsayım |
| `ALAN_KENAR_PAYI_M` | 5 | varsayım |
| `ALAN_BOLGE_SAYISI` | 3 | belge |
| `ROTA_IRTIFA_M` | 30 | belge |
| `ROTA_ORTUSME_MIN_M` | 2 | belge |
| `ROTA_HIZ_MS` | 5 (geçici) | varsayım |
| `SAHNE_BOLUMLER`, `SAHNE_SINIFLAR` | `egitim dogrulama test`, `insan enkaz` | belge |
| `SAHNE_TEST_INSAN`, `SAHNE_TEST_ENKAZ`, `SAHNE_MERKEZ_MESAFE_TEST_M` | 15, 15, 10 | belge |
| `SAHNE_MERKEZ_MESAFE_DIGER_M`, `SAHNE_DIGER_HEDEF_MAKS` | 6, 40 | varsayım |
| `SAHNE_*_VARYANTLARI`, `SAHNE_TEST_OZEL_*`, `SAHNE_ZEMIN_VARYANTLARI` | varyant adları | belge (test'e özel varyant kuralı) / varsayım (adlar) |
| `SAHNE_GUNES_YUKSEKLIK_MIN/MAKS_DERECE` | 20, 85 | varsayım |
| `KAL_KAMERA_KONUM_Z_M` | 0,10 | varsayım (ölçüm sahnesi düzeni) |
| `MODEL_SINIFLAR` | `insan enkaz` | belge |
| `KOSU_TEST_SAHNE_SAYISI`, `KOSU_MIMARILER`, `KOSU_ESZAMANLI` | 30, `ucta merkezi`, 0 | belge |
| `KOSU_SIRA_TOHUMU` | 20260101 | varsayım (ana deney öncesi kaydedilir ve kilitlenir) |
| `KOSU_ARAC_SAYISI` | 1 | varsayım (koşu betiğinin varsayılan araç sayısı) |
| `KOSU_GZ_HAZIR_SN`, `KOSU_PX4_HAZIR_SN` | 60, 90 | varsayım (hazır olma bekleme üst sınırları, saniye) |
| `KOSU_KAPANIS_SN` | 30 | varsayım (süreç grubu başına SIGTERM sonrası bekleme üst sınırı, saniye) |
| `PX4A_BAGLAN_SN`, `PX4A_KOMUT_SN`, `PX4A_HAZIR_SN`, `PX4A_KAPAT_SN` | 60, 20, 90, 5 | varsayım (px4_adapter zaman aşımları, gerçek saniye: bağlanma, tek komut/okuma, ev konumu ve arm edilebilirlik, mavsdk_server'a SIGTERM sonrası bekleme) |
| `PX4A_HAZIRLIK_SN`, `PX4A_IRTIFA_TOLERANS_M` | 240, 1 | varsayım (hazırlık evresi üst sınırı, gerçek saniye; kalkışta ve ilk noktada irtifa kabul payı, m) |
| `DURUM_YAYIN_HZ` | 2 | belge (durum 2 Hz) |
| `KONU_DURUM`, `KONU_TARAMA_BASLAT`, `KONU_TARAMA_BITIS`, `KONU_COMPLETE` | bkz. §9 | varsayım (konu adları) |
| `ARAC_KAPANIS_BEKLE_SN`, `ARAC_SIM_SAAT_SN` | 3, 30 | varsayım (TAMAMLANDI sonrası durum yayımı sürdürme süresi; gz saatinin ilk gelişi için üst sınır, gerçek saniye) |
| `PX4A_KABUL_YARICAPI_M` | 2 | varsayım (her görev öğesinin kabul yarıçapı, m; PX4'ün öntanımlı kabul yarıçapı 10 m "son noktaya ulaşıldı" anını son noktadan uzağa kaydırır; PX4 parametresi değiştirilmez, değer öğe başına yazılır) |

Betikler ve doğrulayıcı bu anahtarları yalnızca bu dosyadan okur; mevcut test ve ölçüm betikleri `source` ile okumaya devam eder (yeni anahtarlar eski betikleri etkilemez).

## 7. Doğrulama çıktısı

Hata mesajları Türkçe ve alan yoluyla verilir, örn.:

```
HATA …/sahne_yakin_hedefler.json: hedefler: 'H01' ile 'H02' merkezleri arası 7.00 m (en az 10 m olmalı)
HATA …/rota_irtifa_25.json: irtifa_m: sabit irtifa 30 m olmalı (bulunan: 25)
SONUÇ: GEÇERSİZ (1 hata)
```

Çıkış kodu 0 = geçerli, 1 = geçersiz, 2 = kullanım/okuma hatası. Sürüm değişirse (`surum`) doğrulayıcı ve bu belge birlikte güncellenir; sahne, rota ve kalibrasyon dosyaları deney paketinde saklanır [belge].

## 8. Koşu kaydı (taslak sürüm)

Bir koşunun başlatılması, durdurulması ve kayıt düzeni. Bu bölüm **taslak sürümdür**: kuyruk ve aktarım alanları B13'te dolacak; bunun için dosyalarda `surum` alanı vardır. Belgede yazılı olan kural **[belge]**, burada seçilen değer **[varsayım]** olarak işaretlidir.

### 8.1 Koşu klasörü düzeni

```
.generated/kosular/<kosu_kimligi>/
  kosu.json                       koşu üst verisi (başlatma yazar; durdurma/temizleme tamamlar)
  gz_sunucu.log, px4_<i>.log      süreç günlükleri
  arac_<arac_kimligi>.log         araç süreci olay günlüğü (durum geçişleri, yok sayılan olaylar, t_s/t_b, tarama bitişi; satır: ISO saat, monotonik ns, sim_ns, olay, anahtar=değer)
  koordinator_deneme.jsonl        yalnız deneme koordinatörü test çıktısı (serbest biçim, şema değildir)
  px4_adapter_<arac_kimligi>.log  px4_adapter olay günlüğü (satır başına: ISO saat, monotonik ns, olay, anahtar=değer; yeni şema değil)
  calisma/px4_<i>/                PX4 örneği çalışma klasörü
  kayit/<kaynak>[_<arac>].jsonl   kare olay kayıtları (8.3); her bileşen KENDİ dosyasına yazar
  kayit/arac_durum_<arac>.jsonl   araç sürecinin DİĞER araçlardan aldığı durumlar (8.5)
.generated/kosular/aktif          yaşayan koşunun kimliği (varsa); durdurma/temizleme siler
```

[belge] Bileşenler birbirinin dosyasına yazmaz; birleştirme değerlendirmede **araç kimliği + kare numarası** üzerinden yapılır. Kaynak bileşenler: `gazebo_damga`, `kamera_alicisi`, `arac_sureci`, `cikarim_iscisi`, `yer_istasyonu`. Dosya adı `kayit/<kaynak>.jsonl` ya da araç başına yazan bileşenlerde `kayit/<kaynak>_<arac_kimligi>.jsonl`. Koşu klasörü silinmez; yollar depo köküne göredir.

### 8.2 Koşu üst verisi (`tur: "kosu_ustveri"`, `kosu.json`)

| Alan | Açıklama |
|---|---|
| `surum`, `tur` | `1`, `"kosu_ustveri"` |
| `kosu_kimligi` | Kimlik kuralı; `kosu_<YYYYAAGG>_<SSDDSS>`. |
| `baslangic`, `bitis` | `{duvar_iso, monotonik_ns}`: saat dilimli ISO 8601 duvar saati ve `CLOCK_MONOTONIC` ns (pozitif tam sayı). Koşu sürerken `bitis` `null`. |
| `depo` | `commit` (40 onaltılık), `calisma_agaci_temiz` (bool). |
| `yapilandirma_sha256`, `ortam_kilidi_sha256` | `config/deney.env` ve `setup/locks/sha256sums.txt` özetleri. |
| `arac_sayisi`, `arac_kimlikleri` | 1…`UAV_SYS_IDS` uzunluğu; kimlikler `UAV_SYS_IDS` değerleri (MAV_SYS_ID). |
| `mimari_modu` | Şimdilik `"yok"`; sonraki adımlarda `KOSU_MIMARILER` değerleri. |
| `sahne_kimligi` | Şimdilik `null`; sonra sahne dosyasının kimliği. |
| `dunya`, `model`, `gz_partition` | `SIM_WORLD`, `SIM_MODEL` ve koşuya özgü izole Gazebo bölümü. |
| `surecler` | `{ad, pid, grup}` listesi (`gz_sunucu`, `px4_<i>`). |
| `bitis_durumu` | `null` (sürüyor) \| `tamamlandi` \| `zorla_kapatildi` \| `yarida_kaldi`. `bitis` ile birlikte dolu ya da birlikte `null`. |
| `zorla_kapatilan` | Yalnız `zorla_kapatildi` iken, SIGKILL ile kapatılan süreç adları (sessiz değil, açıkça yazılır). |

Kullanıcı adı, makine adı ve mutlak yol **yazılmaz**; doğrulayıcı `/` ile başlayan (mutlak yol) her metni reddeder. Örnek: `config/ornek/kosu_ustveri_ornek.json`.

### 8.3 Kare olay kaydı (`tur: "kare_olay"`, JSON Lines)

Satır başına bir kayıt; bir kare için her aşama ayrı kayıttır.

| Alan | Açıklama |
|---|---|
| `surum`, `tur` | `1`, `"kare_olay"` |
| `kaynak` | Kaydı yazan bileşen (8.1). Bir dosyadaki bütün kayıtların kaynağı aynıdır. |
| `arac_kimligi` | `UAV_SYS_IDS` değeri. |
| `n` | Kare numarası: damga ızgaraya tam oturuyorsa `n = CAM_RATE_HZ · t_sim` (2·t_sim) tam sayısı; oturmuyorsa `"izgara_disi"`. **Yuvarlama yoktur** (risk U16); doğrulayıcı iki yönde de denetler. |
| `sim_damga_ns` | Simülasyon damgası (`header.stamp`), ns, tam sayı. |
| `olay` | `uretim`, `kuyruga_giris`, `aktarim_tamam`, `cikarim_basi`, `cikarim_sonu`, `kullanilabilir` [belge: üretim, uygulama kuyruğuna giriş, ilgili aktarımın tamamlanması, çıkarım başlangıcı, çıkarım bitişi, kullanılabilirlik]. |
| `mono_ns` | `CLOCK_MONOTONIC` ns, **pozitif tam sayı**; ya da `"uygulanmaz"`. [belge] Uygulanmayan aktarım aşaması "uygulanmaz" gösterilir, sıfır süreli gerçek aktarım gibi yorumlanmaz: `0`, boş (`null`) ve ondalık değer reddedilir. [varsayım] `"uygulanmaz"` yalnız `kuyruga_giris` ve `aktarim_tamam` için yazılabilir. |
| `sonuc_durumu` | Yalnız `kullanilabilir` olayında zorunlu: `sonuc` \| `tespit_yok` \| `kare_alinamadi` \| `gec_geldi`. Dört durum ayrıdır ve karışmaz. |

Zamanlar ondalık saniye değildir; ölçekleme ve yuvarlama yapılmaz [belge]. Bir dosyada aynı (araç, `n`, damga, olay) ikinci kez yazılamaz. Örnekler: `config/ornek/kare_olay_gazebo_damga_ornek.jsonl`, `config/ornek/kare_olay_yer_istasyonu_ornek.jsonl`.

### 8.4 Koşu betiği

`araclar/kosu.sh baslat [--arac N] | durdur | durum | temizle` (hepsi `--dry-run` destekler). `baslat` önce başka `gz sim`/`ruby`/`px4`/`mavsdk_server` süreci ya da bitmemiş koşu olmadığını denetler; Gazebo sunucusunu, sonra N PX4 SITL örneğini ayrı süreç gruplarında başlatır. `durdur` SIGTERM ile ters sırada (PX4'ler, **Gazebo en son**: sunucuda çalışan kayıt bileşeninin son boşaltmayı yapması için) kapatır; `KOSU_KAPANIS_SN` dolarsa SIGKILL uygular ve `kosu.json`'a `zorla_kapatildi` yazar. `temizle` bu betiğin başlattığı süreç gruplarını kapatır, koşu klasörünü silmez, `yarida_kaldi` yazar. `durdur` ve `temizle`, `MAVSDK_GRPC_PORTS` üzerinde dinleyen yetim `mavsdk_server` süreçlerini de (bağdaştırıcı kapatmadıysa) önce SIGTERM ile kapatır ve kosu.json süreç listesine `mavsdk_server_<gRPC portu>` adıyla yazar.

### 8.5 Araç durum kaydı (`tur: "arac_durum_kaydi"`, JSON Lines, taslak sürüm)

Her araç süreci, ortak durum konusundan (bkz. §9) aldığı **diğer araçların** durum iletilerini kendi dosyasına (`kayit/arac_durum_<arac_kimligi>.jsonl`) yazar [belge: her araç diğer iki aracın durumunu alıp kaydeder, FR-2]. Aracın kendi geçişleri bu dosyaya yazılmaz; `arac_<arac_kimligi>.log` dosyasındadır [varsayım: ayrı dosya]. Satır başına bir kayıt:

| Alan | Açıklama |
|---|---|
| `surum`, `tur` | `1`, `"arac_durum_kaydi"` |
| `arac_kimligi` | Kaydı yazan araç (`UAV_SYS_IDS` değeri); bir dosyada hep aynı. |
| `kaynak_arac_kimligi` | Durumu yayımlayan araç (`UAV_SYS_IDS` değeri); `arac_kimligi`'nden farklı. |
| `durum` | `HAZIR`, `BARIYER_BEKLE`, `TARAMA`, `WAIT`, `TAMAMLANDI` (`VehicleState.STATE_*` adları). |
| `sim_damga_ns` | İletideki `sim_stamp` (yayımlayanın simülasyon saati), ns, tam sayı. |
| `alinma_mono_ns` | İletinin alındığı an, `CLOCK_MONOTONIC` ns, pozitif tam sayı; dosyada geriye gitmez. |

Ondalık saniye yazılmaz. Doğrulayıcı: `sozlesme_dogrula.py <dosya>.jsonl` (ilk dolu satırdaki `tur` ile ayrılır). Örnek: `config/ornek/arac_durum_kaydi_ornek.jsonl`.

## 9. ROS 2 konuları (taslak)

Belge konu adlarını ve QoS değerlerini **tanımlamaz**; aşağıdaki her ad ve ayar **[varsayım]**dır. Adlar `config/deney.env`'de (`KONU_*`) tek yerde durur. **Kesin QoS B11/M2'de belirlenir (U14, U21)**; bu bölüm yalnız bu sürümün çalışan ayarıdır. Bütün araç süreçleri ve yer istasyonu aynı Fast DDS profilini (`config/fastdds_profil.xml`) ve ölçülen sürü ağını kullanır; araç süreci kendi adresini `SWARM_BIND_ADDR` ile alır.

| Konu (varsayım) | Tür | Yayımlayan → abone | QoS (varsayım) |
|---|---|---|---|
| `/swarm/vehicle_state` (`KONU_DURUM`) | `swarm_msgs/VehicleState` | her araç, 2 Hz [belge] → diğer araçlar ve yer istasyonu | reliable, volatile, keep_last 10 |
| `/swarm/scan_start` (`KONU_TARAMA_BASLAT`) | `swarm_msgs/ScanStart` | yer istasyonu (görev koordinatörü), bir kez (t0) → araçlar | reliable, transient_local, keep_last 1 |
| `/swarm/scan_finished` (`KONU_TARAMA_BITIS`) | `swarm_msgs/ScanFinished` | her araç, rota bitince bir kez → yer istasyonu (ve diğer araçlar) | reliable, transient_local, keep_last 10 |
| `/swarm/complete` (`KONU_COMPLETE`) | `swarm_msgs/Complete` | yer istasyonu, bir kez (t1) → araçlar | reliable, transient_local, keep_last 1 |

- **Tek durum konusu:** üç araç ve yer istasyonu aynı konuya yayımlar/abone olur; durum iletisi `vehicle_id` taşır [belge: "ortak durum konusu"]. Araç, kendi iletisini kayda almaz.
- **Kontrol iletileri** (başlatma, bitiş, COMPLETE) kaybolmamalıdır [belge: WAIT'ten yalnız COMPLETE ile çıkılır]: reliable. **transient_local** seçilmesinin gerekçesi, yazıcının aboneyi sonradan keşfetmesi durumunda (keşif sırası belirsizdir) iletinin yine de teslim edilmesidir; eski bir koşunun iletisi ise durum makinesinin kurallarıyla (BARIYER_BEKLE dışında başlatma yok sayılır, görev kimliği eşleşmeyen COMPLETE yok sayılır) etkisizdir. Derinlik 1: yalnız son başlatma/COMPLETE tutulur.
- **Durum iletisi** 2 Hz sürekli akıştır; kaybolan bir ileti sonraki ile telafi edilir, geç katılana eski durum verilmez: volatile.
- Araç komut konusu bu sürümde **yoktur** (komut türleri belgede tanımsız).
- Durum yayımı duvar saati zamanlayıcısıyla (2 Hz) yapılır; ayrıca her durum geçişinde bir ek ileti yayımlanır [varsayım: 2 Hz'lik akış yarım saniyeden kısa süren bir durumu — örneğin tarama bitişini en son yapan aracın WAIT'ini — kaçırabilir]; iletideki `sim_stamp` simülasyon saatidir [varsayım: RTF ≈ 1; ölçüm sim zamanına göre de raporlanır].
