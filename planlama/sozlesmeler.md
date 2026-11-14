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
| `alan` | nesne | `cerceve: "yerel_ENU"`, `merkez_m: [0, 0]`, `genislik_m`, `yukseklik_m`. **Bütün sahnelerde yapılandırmadaki alanla aynıdır** (`ALAN_*`). **Kilitli** (M1 1.7, 2026-11-14) 300 m × 300 m: `x ∈ [−150, 150]`, `y ∈ [−150, 150]`. |
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
| `SIM_MODEL` | `gz_x500_mono_cam_down` | PX4'ün x500 + aşağı bakan kamera adı (havaçerçevesi bu adla eşleşir); model dosyası `araclar/kamera_uret.py` ile üretilir (§10); koşu betiği ve araç süreci kullanır |
| `SIM_MODEL_TEMEL` | `gz_x500` | kamerasız temel gövde (PX4'ün x500 modeli); eski K aşaması test ve ölçüm betikleri (araç kimlik testi, kamera ve yayım ölçümleri) bunu kullanır |
| `KAMERA_LINK`, `KAMERA_ALGILAYICI`, `CAM_CLIP_NEAR_M`, `CAM_CLIP_FAR_M` | `camera_link`, `camera`, 0,1, 200 | varsayım (üretilen modeldeki adlar ve kırpma düzlemleri) |
| `KARE_NUMARALAMA` | `izgara` | belge/K9 (yedek yol uygulanmaz; başka değer açık hata verir) |
| `PX4A_HAZIRLIK_SN`, `PX4A_IRTIFA_TOLERANS_M` | 240, 1 | varsayım (hazırlık evresi üst sınırı, gerçek saniye; kalkışta ve ilk noktada irtifa kabul payı, m) |
| `PX4A_YON_ESIK_DERECE`, `PX4A_YON_HIZ_ESIK_MS`, `PX4A_YON_SN` | 3, 0,3, 30 | varsayım (hazırlığın son adımı: ilk noktada konum tutarak ilk tarama doğrusunun yönüne dönüş; bitiş ölçütü: yaw farkı ≤ eşik derece ve yatay hız ≤ eşik m/s; üst sınır gerçek saniye, aşılırsa hazırlık hatası; yön rotadan hesaplanır) |
| `DURUM_YAYIN_HZ` | 2 | belge (durum 2 Hz) |
| `KONU_DURUM`, `KONU_TARAMA_BASLAT`, `KONU_TARAMA_BITIS`, `KONU_COMPLETE` | bkz. §9 | varsayım (konu adları) |
| `ARAC_KAPANIS_BEKLE_SN`, `ARAC_SIM_SAAT_SN` | 3, 30 | varsayım (TAMAMLANDI sonrası durum yayımı sürdürme süresi; gz saatinin ilk gelişi için üst sınır, gerçek saniye) |
| `PX4A_KABUL_YARICAPI_M` | 2 | varsayım (her görev öğesinin kabul yarıçapı, m; PX4'ün öntanımlı kabul yarıçapı 10 m "son noktaya ulaşıldı" anını son noktadan uzağa kaydırır; NAV_ACC_RAD gibi gezinme parametreleri değiştirilmez, değer öğe başına yazılır; tek PX4 parametre yazımı kalkış irtifasıdır, bkz. kararlar) |
| `PX4A_HEARTBEAT_SN`, `PX4A_BASLAT_TOLERANS_M` | 5, 1 | varsayım (bağlantıdan sonra HEARTBEAT kaynak kimliğini okuma bekleme üst sınırı, gerçek sn; görev başlatmadan önce aracın ilk noktada sayılması için kabul yarıçapına ve irtifa payına eklenen ek pay, m) |
| `ISCI_ARKA_UC`, `ISCI_CPU_ONNX` | `gpu`, `.generated/models/yolo26s.onnx` | belge/kararlar (kilitli deney yolu GPU; `cpu` yalnız B planı yapı uyumu için, deneylerde kullanılmaz) |
| `ISCI_MANTIKSAL_CPU`, `ISCI_CPU_SABITLE` | 2, 1 | belge (işçiye aynı fiziksel çekirdeğe ait iki mantıksal CPU)/varsayım (varsayılan açık; araç sırasına göre çekirdek çifti çalışma anında okunan topolojiden seçilir) |
| `ISCI_ISINMA_KARE`, `ISCI_HAZIR_SN`, `ISCI_KARE_ZAMAN_ASIMI_SN` | 5, 300, 30 | varsayım (ısınma çıkarımı sayısı; işçinin hazır olması için üst sınır, gerçek sn; tek kare için işçi zaman aşımı, gerçek sn) |
| `ISCI_YENIDEN_BASLAT_MAKS`, `ISCI_KAPANIS_BEKLE_SN`, `ISCI_KAYNAK_SN` | 3, 60, 1 | varsayım (işçi ölümü/zaman aşımında yeniden başlatma üst sınırı; COMPLETE sonrası kare sonuçlarının tamamlanması için üst sınır; işçi kaynak örnekleme aralığı, gerçek sn) |
| `MODEL_ESLEME_COCO` | `person=insan` | varsayım (COCO ön eğitimli ağırlıkla yalnız M1 boru hattı sınaması; proje modeli iki sınıflı olacak ve birebir eşlenir) |

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
  kayit/gazebo_damga.jsonl        Gazebo damga bileşeni: her araç kamera karesi için `uretim` olayı (8.3; kaynak gazebo_damga; kosu.sh baslat yüklemesi)
  kayit/kamera_alici_<arac>.jsonl kamera alıcısı: görev karesi, kare alınamadı, geç geldi, yok sayılan kare kayıtları (8.3, 10.1; kaynak kamera_alicisi)
  kayit/cikarim_iscisi_<arac>.jsonl çıkarım işçisi: her işlenen kare için `cikarim_basi` ve `cikarim_sonu` (8.3, 10.2; kaynak cikarim_iscisi)
  kayit/kare_sonuc_<arac>.jsonl   araç sürecinin kare sonuçları: her görev numarası için tam bir kayıt (8.6)
  kayit/isci_kaynak_<arac>.jsonl  çıkarım işçisinin periyodik GPU kullanımı/belleği, ana bellek ve CPU kaydı (8.7)
  kayit/arac_sureci_<arac>.jsonl  araç sürecinin kare sonucu gönderim kaydı: her FrameResult yayımı için `kare_olay` `gonderim` (8.3; kaynak arac_sureci)
  kayit/yer_istasyonu_kare.jsonl  yer istasyonu alıcısının kare sonucu kullanılabilirlik kaydı: her kabul edilen sonuç için `kare_olay` `kullanilabilir` (8.3; kaynak yer_istasyonu; üç araç aynı dosyada, araç kimliği alanıyla ayrılır)
  cikarim_isci_<arac>.log         çıkarım işçisinin standart hata günlüğü (serbest biçim; hazır bilgisi, kare hataları, kapanış özeti)
  uretim/                         koşu için üretilen araç modeli (modeller/) ve Gazebo sunucu yapılandırması (server.config); config/deney.env'den, PX4 dosyalarına dokunmadan
  gorus_deneme.jsonl, gorus_ornek_*.png  yalnız kamera yönelim denemesinin çıktısı (serbest biçim, depoya girmez)
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
| `yapilandirma_sha256`, `ortam_kilidi_sha256`, `rota_sha256` | `config/deney.env`, `setup/locks/sha256sums.txt` ve `config/bolge_rota.json` özetleri. Rota dosyası sahne dosyasından girdi almaz; aynı rota özeti bütün sahnelerde aynıdır (bölge ve rota dosyaları tüm sahnelerde aynı). `rota_sha256` sürüm 1'de 2026-11-14'ten itibaren zorunludur (bu tarihten önceki geliştirme koşularının `kosu.json` dosyalarında yoktur). |
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
| `olay` | `uretim`, `kuyruga_giris`, `aktarim_tamam`, `cikarim_basi`, `cikarim_sonu`, `kullanilabilir` [belge: üretim, uygulama kuyruğuna giriş, ilgili aktarımın tamamlanması, çıkarım başlangıcı, çıkarım bitişi, kullanılabilirlik]; ayrıca araç sürecinin `gonderim` kaydı [varsayım: aşama değil, tanı kaydı: araç kare sonucunu yayım kuyruğundan DDS'e verdi; `mono_ns` = yayım çağrısının döndüğü an; `sim_damga_ns` = karenin ızgara damgası; yalnız kaynak `arac_sureci` yazar]; ayrıca kamera alıcısının YEREL kayıtları `kayip_tespit`, `gec_geldi` ve `yok_sayildi` (aşağıda; zaman aşaması değildir, ağa gönderilmez) [varsayım: belge "geç geldi" kaydının yalnız yerel kayda yazılacağını söyler, olay adını söylemez]. |
| `mono_ns` | `CLOCK_MONOTONIC` ns, **pozitif tam sayı**; ya da `"uygulanmaz"`. [belge] Uygulanmayan aktarım aşaması "uygulanmaz" gösterilir, sıfır süreli gerçek aktarım gibi yorumlanmaz: `0`, boş (`null`) ve ondalık değer reddedilir. [varsayım] `"uygulanmaz"` yalnız `kuyruga_giris` ve `aktarim_tamam` için yazılabilir. |
| `sonuc_durumu` | `kullanilabilir` olayında zorunlu: `sonuc` (STATUS_DETECTIONS) \| `tespit_yok` (STATUS_NO_DETECTION) \| `kare_alinamadi` (STATUS_FRAME_NOT_RECEIVED) \| `islem_hatasi` (STATUS_PROCESSING_ERROR) [varsayım, kullanıcı kararı 2026-11-14: belge işlem hatasını kullanılabilirlik ve t1 koşulunda anmaz; işlem hatası t1'i ENGELLEMEZ, ayrı sayılır; gecikme L'ye, "sonuç üreten kare" oranına ve "kare alınamadı" oranına GİRMEZ] (`kullanilabilir` yer istasyonunda sonucun/kaydın kullanılabilir olduğu andır; kayıp tespitinde bunu alıcı değil yer istasyonu yazar). `kayip_tespit` olayında yalnız `kare_alinamadi`. Dört durum ayrıdır ve karışmaz. **`gec_geldi` burada YOKTUR**: belge geç gelen kareyi işlemez ve ağa göndermez, yalnız yerel kayda "geç geldi" yazar; bu yüzden yer istasyonunda kullanılabilir bir durum değil, kamera alıcısının yerel olayıdır (`olay: gec_geldi`). |
| `neden` | Yalnız `yok_sayildi` olayında zorunlu: `gorev_oncesi` (damga n_ilk'ten önce ya da tarama başlamadan) \| `kapanis_sonrasi` (n_son'dan büyük kare) \| `izgara_disi` (n türetilemedi; `n = "izgara_disi"`) \| `tekrar` (numara zaten görev karesi olarak kabul edilmişti). |

Zamanlar ondalık saniye değildir; ölçekleme ve yuvarlama yapılmaz [belge]. Bir dosyada aynı (araç, `n`, damga, olay) ikinci kez yazılamaz (yerel `gec_geldi`/`yok_sayildi` kayıtları için alım anı `mono_ns` de anahtardadır; aynı kare birden çok kez gelebilir). Örnekler: `config/ornek/kare_olay_gazebo_damga_ornek.jsonl`, `config/ornek/kare_olay_yer_istasyonu_ornek.jsonl`, `config/ornek/kare_olay_kamera_alici_ornek.jsonl`.

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

### 8.6 Kare sonucu kaydı (`tur: "kare_sonuc"`, JSON Lines, taslak sürüm)

Araç süreci (B10), kamera alıcısının kabul ettiği HER görev numarası için ve alıcının "kare alınamadı" kaydı yazdığı her numara için **tam bir** `swarm_msgs/FrameResult` üretir; bu kayıt, o iletinin yerel kopyasıdır. Bu sürümde ileti ağa **gönderilmez** (B11); yerel kancaya verilir ve `kayit/kare_sonuc_<arac_kimligi>.jsonl` dosyasına yazılır. Satır başına bir kayıt:

| Alan | Açıklama |
|---|---|
| `surum`, `tur` | `1`, `"kare_sonuc"` |
| `arac_kimligi` | `UAV_SYS_IDS` değeri; dosyada hep aynı. |
| `n`, `sim_damga_ns` | Izgara kare numarası ve `n · 10⁹ / CAM_RATE_HZ` ns (kare sonucu yalnız ızgara numaralı görev karelerine aittir; `numbering_mode = NUMBERING_GRID`). Dosyada her `n` **bir kez** bulunur. |
| `durum` | **Dört durum ayrıdır ve karışmaz** [belge]: `tespit` (`STATUS_DETECTIONS`; çıkarım bitti, proje sınıfında en az bir tespit), `tespit_yok` (`STATUS_NO_DETECTION`; çıkarım BAŞARIYLA bitti, proje sınıfında tespit yok), `islem_hatasi` (`STATUS_PROCESSING_ERROR`; kare alındı ama işlenemedi: işçi hatası, ölümü, zaman aşımı, bozuk görüntü, kapanışta işlenememe), `kare_alinamadi` (`STATUS_FRAME_NOT_RECEIVED`; alıcıya ulaşmayan görev karesi). |
| `tespit_sayisi`, `tespitler` | `tespit` durumunda en az bir öğe, diğer üç durumda **boş liste** (boş liste + `islem_hatasi` "tespit yok" demek değildir). Öğe: `sinif` (`MODEL_SINIFLAR` adı), `sinif_no` (o listedeki sıra: insan 0, enkaz 1 = `Detection.CLASS_*`), `guven` ([`INF_CONF`, 1]), `kutu` ([x_min, y_min, x_maks, y_maks] piksel, orijin sol üst, görüntü içinde), `konum` (**null**: tahmini konum B14'tür; `has_position = false`), `aday` (**false**: birleştirme adayı B15'tir; `candidate = false`). |
| `atilan_sinif_disi` | Çıkarımın bulduğu ama proje sınıfına eşlenmediği için atılan tespit sayısı (COCO ön eğitimli ağırlıkta `person` dışındaki sınıflar). `kare_alinamadi` için 0. |
| `hata` | `islem_hatasi` durumunda boş olmayan metin; diğer durumlarda `null`. |
| `mono_ns` | Kare sonucunun araç sürecinde oluşturulduğu an, `CLOCK_MONOTONIC` ns (pozitif tam sayı). |

[varsayım] Sınıf eşlemesi: işçi modelin kendi sınıf adını döndürür; araç süreci adı `MODEL_SINIFLAR`'daki bir ada eşitse birebir kullanır (M5 modeli), değilse `MODEL_ESLEME_COCO` tablosuna bakar (COCO ön eğitimli ağırlık, yalnız M1 boru hattı sınaması: `person → insan`); tabloda olmayan sınıf atılır ve `atilan_sinif_disi` ile sayılır. Çıkarım bitip hiç proje sınıfı tespiti kalmazsa durum `tespit_yok`'tur. Doğrulayıcı: `sozlesme_dogrula.py <dosya>.jsonl` (ilk dolu satırdaki `tur`). Örnek: `config/ornek/kare_sonuc_ornek.jsonl`.

### 8.7 İşçi kaynak kaydı (`tur: "isci_kaynak"`, JSON Lines, taslak sürüm)

Çıkarım işçisi, kendi sürecinin kaynak kullanımını `ISCI_KAYNAK_SN` aralıkla (gerçek saniye) `kayit/isci_kaynak_<arac_kimligi>.jsonl` dosyasına yazar [belge: GPU kullanımı ve GPU belleği süreç başına periyodik; ana bellek]. Alanlar: `surum`, `tur`, `arac_kimligi`, `isci_pid`, `mono_ns` (`CLOCK_MONOTONIC` ns), `gpu_kullanim_yuzde` (NVML `nvmlDeviceGetProcessUtilization`: son örneklemeden beri sürecin SM kullanımı, 0–100 tam sayı; NVML yoksa `null`), `gpu_bellek_mib` (NVML `nvmlDeviceGetComputeRunningProcesses`: sürecin GPU belleği; yoksa `null`), `ana_bellek_rss_mib` (`/proc/self/statm`), `cpu_yuzde` (sürecin CPU süresi / geçen süre, tek mantıksal CPU = %100; ilk kayıtta `null`). `sudo` gerekmez. Bellek ve GPU için üst sınır konmaz [belge]. Örnek: `config/ornek/isci_kaynak_ornek.jsonl`.

## 9. ROS 2 konuları (taslak)

Belge konu adlarını ve QoS değerlerini **tanımlamaz**; aşağıdaki her ad ve ayar **[varsayım]**dır. Adlar `config/deney.env`'de (`KONU_*`) tek yerde durur. **Kesin QoS B11/M2'de belirlenir (U14, U21)**; bu bölüm yalnız bu sürümün çalışan ayarıdır. Bütün araç süreçleri ve yer istasyonu aynı Fast DDS profilini (`config/fastdds_profil.xml`) ve ölçülen sürü ağını kullanır; araç süreci kendi adresini `SWARM_BIND_ADDR` ile alır.

| Konu (varsayım) | Tür | Yayımlayan → abone | QoS (varsayım) |
|---|---|---|---|
| `/swarm/vehicle_state` (`KONU_DURUM`) | `swarm_msgs/VehicleState` | her araç, 2 Hz [belge] → diğer araçlar ve yer istasyonu | reliable, volatile, keep_last 10 |
| `/swarm/scan_start` (`KONU_TARAMA_BASLAT`) | `swarm_msgs/ScanStart` | yer istasyonu (görev koordinatörü), bir kez (t0) → araçlar | reliable, transient_local, keep_last 1 |
| `/swarm/scan_finished` (`KONU_TARAMA_BITIS`) | `swarm_msgs/ScanFinished` | her araç, rota bitince bir kez → yer istasyonu (ve diğer araçlar) | reliable, transient_local, keep_last 10 |
| `/swarm/complete` (`KONU_COMPLETE`) | `swarm_msgs/Complete` | yer istasyonu, bir kez (t1) → araçlar | reliable, transient_local, keep_last 1 |
| `/swarm/frame_result` (`KONU_KARE_SONUC`) | `swarm_msgs/FrameResult` | her araç, her görev numarası için bir kez, dört durum dahil (uçta mod, B11) → yer istasyonu | reliable [belge], transient_local, keep_last 1000 (`QOS_KARE_SONUC_*`) |

- **Tek durum konusu:** üç araç ve yer istasyonu aynı konuya yayımlar/abone olur; durum iletisi `vehicle_id` taşır [belge: "ortak durum konusu"]. Araç, kendi iletisini kayda almaz.
- **Kontrol iletileri** (başlatma, bitiş, COMPLETE) kaybolmamalıdır [belge: WAIT'ten yalnız COMPLETE ile çıkılır]: reliable. **transient_local** seçilmesinin gerekçesi, yazıcının aboneyi sonradan keşfetmesi durumunda (keşif sırası belirsizdir) iletinin yine de teslim edilmesidir; eski bir koşunun iletisi ise durum makinesinin kurallarıyla (BARIYER_BEKLE dışında başlatma yok sayılır, görev kimliği eşleşmeyen COMPLETE yok sayılır) etkisizdir. Derinlik 1: yalnız son başlatma/COMPLETE tutulur.
- **Kare sonucu konusu** (uçta mod): belge kare sonucu iletilerinin ve "kare alınamadı" kayıtlarının aynı DDS konusundan reliable QoS ile gönderilmesini ister [belge]; konu adı, geçmiş ve dayanıklılık [varsayım]. **keep_last 1000**: bir koşuda araç başına görev karesi 382–383 (300 m alanda ölçüm; 360 m adayında 563); derinlik bunu aştığı için yazma geçmişi hiçbir onaysız iletiyi düşürmez (keep_last küçük derinlikte reliable yazıcının yavaş abonede eski iletiyi düşürebilmesi risk U14'tür) ve yayım kare işleme iş parçacığını bloke etmez (keep_all kaynak sınırına dayanınca yayımı bloke edebilir). **transient_local**: yer istasyonu yayımcıyı sonradan keşfetse bile yayımlanmış iletiler teslim edilir (keşif sırası belirsiz); araç süreçleri koşu başına yeni başlar, eski koşu iletisi yoktur. Araç yayımı kare işleme iş parçacığından ayrı kuyruklu bir iş parçacığında yapılır; araç TAMAMLANDI'dan sonra bütün iletilerin onayını (`wait_for_all_acked`, üst sınır `KARE_SONUC_ACK_SN`) bekler. Her ileti SHM değil, UDPv4 ve sürü ağı adresi üzerinden gider (profilde yerleşik taşımalar, data-sharing ve intraprocess teslimi kapalı; `config/fastdds_profil.xml`). Yer istasyonu eşleşmiş yayımcı sayısını izler; deneme koordinatörü bariyeri bütün araç yayımcılarıyla eşleşmeden açmaz (`KARE_SONUC_ESLESME_SN`).
- **Durum iletisi** 2 Hz sürekli akıştır; kaybolan bir ileti sonraki ile telafi edilir, geç katılana eski durum verilmez: volatile.
- Araç komut konusu bu sürümde **yoktur** (komut türleri belgede tanımsız).
- Durum yayımı duvar saati zamanlayıcısıyla (2 Hz) yapılır; ayrıca her durum geçişinde bir ek ileti yayımlanır [varsayım: 2 Hz'lik akış yarım saniyeden kısa süren bir durumu — örneğin tarama bitişini en son yapan aracın WAIT'ini — kaçırabilir]; iletideki `sim_stamp` simülasyon saatidir [varsayım: RTF ≈ 1; ölçüm sim zamanına göre de raporlanır].

## 10. Araç kamerası, damga bileşeni ve kamera alıcısı

**Araç modeli (B6).** `araclar/kamera_uret.py model <klasör>`, PX4'ün `x500` modelini `<include>` ederek gövdeye (`base_link`) sabit, aşağı bakan (pitch +90°) bir kamera bağlantısı ekleyen modeli `config/deney.env` değerlerinden üretir: `CAM_WIDTH`×`CAM_HEIGHT`, `R8G8B8` (sıkıştırmasız), `CAM_RATE_HZ` (simülasyon zamanında), yatay görüş açısı `CAM_HFOV_RAD` (kilitli 65°), `KAL_KAMERA_KONUM_Z_M` yüksekliği. `araclar/kosu.sh baslat` her koşuda bunu `kosu/uretim/modeller/` altına üretir ve yalnız PX4 başlatma sürecinde `PX4_GZ_MODELS` değişkenini oraya çevirir (PX4 aynı adlı modeli buradan yükler; PX4 kaynak ağacı değişmez). Görüntüde **yukarı = aracın ileri yönü (+x gövde), sağ = gövdenin sağı**; görüntünün yatay ekseni uçuş yönüne diktir (§3, §4). Görüntü konusu: `/world/<dünya>/model/<model>_<örnek>/link/<KAMERA_LINK>/sensor/<KAMERA_ALGILAYICI>/image`. Kalibrasyon dosyası: `python3 araclar/kamera_uret.py kalibrasyon` → `config/kamera_kalibrasyon.json` (`--check` güncel değilse çıkış 1).

**Damga bileşeni (B7).** `src/yayim_damga` (Gazebo sistem eklentisi), sunucu sürecinde her araç kamerasının görüntü konusuna süreç içi abone olur; üretim anı geri çağrıda okunan `CLOCK_MONOTONIC`'tur (kararlar: kare yayımlanma anı). `kosu.sh baslat`, eklentiyi PX4'ün sunucu yapılandırmasının bir kopyasına ekler (`GZ_SIM_SERVER_CONFIG_PATH`; PX4'ün fizik, sensör, IMU ve köprü eklentileri aynen yüklenir) ve `kayit/gazebo_damga.jsonl`'a her kare için `kare_olay` (`kaynak: gazebo_damga`, `olay: uretim`) yazar. Araç kimliği, görüntü konusunun ait olduğu en üst model adından (`<SIM_MODEL öneksiz>_<örnek>`) `UAV_SYS_IDS` sırasıyla bulunur; eşleşmeyen kamera kaydedilmez ve günlüğe uyarı yazılır. Koşular SIGTERM ile durdurulur (Gazebo en son); SIGKILL'de son ≤ 1 sn kayıt kaybolabilir.

### 10.1 Kamera alıcısı kuralları (B8)

Kaynak `kamera_alicisi`, dosya `kayit/kamera_alici_<arac>.jsonl`. Her kamera karesi için, `n = CAM_RATE_HZ · t_sim` (tam sayı aritmetiğiyle) türetilir; damga ızgaraya oturmuyorsa `izgara_disi` (görev karesi sayılmaz; K9). `n_ilk = ceil(2·t_s)`, `n_son = floor(2·t_b)`; damgası `t_s` ya da `t_b`'ye eşit kare görev karesidir. Kayıtlar:

| Durum | Kayıt |
|---|---|
| Görev karesi ([n_ilk, n_son]) iç kuyruğa verildi | `olay: kuyruga_giris`, `mono_ns` = kuyruğa verilme anı [varsayım: belge alıcının alım anı için ayrı bir aşama tanımlamaz; "uygulama kuyruğuna giriş" aşamasıdır] |
| Aralıkta olup alınmamış numara, daha büyük numaralı kare geldiğinde (ya da n_son'dan büyük ilk kareyle) | `olay: kayip_tespit`, `sonuc_durumu: kare_alinamadi`, `sim_damga_ns` = `n · 10⁹ / CAM_RATE_HZ`, `mono_ns` = kaybın tespit edildiği an (yalnız `kamera_alicisi`; yer istasyonu kaydı `kullanilabilir` B11'de ayrıca yazılır) |
| Kayıp kaydı yazılmış numarayla sonradan gelen kare | `olay: gec_geldi`; işlenmez, iç kuyruğa ve ağa verilmez (kayıp kaydı kesindir) |
| Görev girdisi olmayan kare | `olay: yok_sayildi`, `neden` (§8.3) |

**t_s sınır durumu.** Tarama başlatma bildirimi (t_s okuması bir saat adımı eski olabilir) bir karenin gelişinden hemen sonra yapılabilir. Bildirimden önceki son 1 saniyede "görev öncesi" sayılmış ve numarası `n_ilk`'e eşit ya da büyük kare görev karesi olarak kabul edilir: iç kuyruğa verilir, `kuyruga_giris` kaydı ayrıca yazılır (aynı numaranın daha önceki `yok_sayildi`/`gorev_oncesi` kaydı dosyada kalır; görev sınıfı `kuyruga_giris` ile belirlenir) ve `kayip_tespit` yazılmaz. Özet sayacı: `gorev_oncesi_kabul`. Kapanış karesi hiç gelmeden süreç kapanırsa sondaki kayıplar araç süreci kapanışında aynı kuralla yazılır (`kapanis_zorla`).

Hiçbir numara hem görev karesi hem `kare_alinamadi` olamaz. Yedek yol (alıcı numarası `k`) uygulanmaz (K9): `KARE_NUMARALAMA` `izgara` dışında bir değerse alıcı açık hata verir. Hata enjeksiyonu yalnız testler içindir: ortam değişkeni `KAMERA_ENJEKSIYON` (`bekle=<sn>;dusur=<n>,…;gecik=<n>,…`; `+k` = `n_ilk + k`, `son` = `n_son`), varsayılan kapalıdır ve durumu (`kapali` ya da açık değer) her araç günlüğüne `kamera_enjeksiyon` olayıyla yazılır.

### 10.2 Çıkarım işçisi (B9) ve kare sonucu akışı (B10)

**Süreç yapısı [belge].** Uçta modda her araç sürecinin başlattığı AYRI bir alt süreç, çıkarım işçisidir (`src/swarm_vehicle/swarm_vehicle/cikarim_isci.py`); araç süreciyle IP kullanmayan bir kanalla (`socket.socketpair(AF_UNIX)`) haberleşir; işçide `rclpy`, gz-transport, DDS ve ağ soketi yoktur (kanıt: işçinin soketleri yalnız `unix`, `rclpy_yuklu=false`). Alt süreç `subprocess.Popen` ile taze bir yorumlayıcıda başlar (`multiprocessing` fork/spawn seçilmedi: araç sürecinin rclpy/DDS/MAVSDK durumu miras kalmasın). Kanal çerçevesi: `!II` (JSON başlığı uzunluğu, yük uzunluğu) + JSON başlık + ham yük; 921 600 baytlık RGB8 görüntü alıcıdaki bayt nesnesinden doğrudan gönderilir.

**Çıkarım ayarları (kilitli, yalnız `INF_*`).** GPU yolu (PyTorch + CUDA, `INF_GPU_MODEL` = YOLO26L, `.generated/models/`; ağırlık İNDİRİLMEZ, `YOLO_OFFLINE`): FP32, batch=1, `imgsz` 640, güven `INF_CONF`, `max_det` 300, **`nms=False`**. Kanıt (işçi her başlangıçta ve her karede denetler): Ultralytics başlığı uçtan uca (`end2end=True`) kipindedir, başlığın ham çıktısı `[1, 300, 6]`'dır (NMS'li yol `[1, 4+nc, N]` verir) ve `torchvision.ops.nms` ısınmadan sonra hiç çağrılmaz; biri bozulursa kare işlem hatası olur. Ön işleme: RGB8 → BGR (Ultralytics numpy girdi sözleşmesi) → letterbox (`imgsz`'e oranı koruyarak, 114 dolgu, [0,1] FP32); kutular özgün 640×480 piksel koordinatına geri çevrilir. **B planı yapı uyumu:** `ISCI_ARKA_UC=cpu` aynı arayüzle `ISCI_CPU_ONNX` (YOLO26s, NMS'siz ONNX) + ONNX Runtime CPU ile çalışır ve aynı sonuç yapısını döndürür; kararlar gereği deneylerde kullanılmaz.

**Zamanlar.** `cikarim_basi` = işçinin kare çerçevesini okuyup işleme başladığı an; `cikarim_sonu` = sonucun işçide ana belleğe alındığı an (`torch.cuda.synchronize()` ve `.cpu()` sonrası) [belge]. Her ikisi `kayit/cikarim_iscisi_<arac>.jsonl` dosyasına `kare_olay` (`kaynak: cikarim_iscisi`) olarak yazılır. İşçi hatası döndüğü karede de ikisi yazılır (sonu = hata sonucunun oluştuğu an); işçinin ölümünde yalnız `cikarim_basi` kalır (ölüm enjeksiyonunda ölmeden hemen önce yazılır). Süreç içi kare sonucu zamanı `kare_sonuc.mono_ns`'tir.

**Hazırlık [belge].** İşçi araç süreci başlarken başlatılır; modeli yükler ve `ISCI_ISINMA_KARE` ısınma çıkarımı yapar (hazırlık evresinde, kalkışla paralel); araç, işçi `hazir` bildirmeden BARIYER_BEKLE'ye geçmez; ısınma ve yükleme süresi araç günlüğünde (`isci_hazir`, `isci_hazir_bekleme_bitti`). İşçi başlatılamazsa araç HAZIR'dan ilerlemez (çıkış kodu 1).

**CPU eşlemesi [belge].** `ISCI_CPU_SABITLE=1` iken işçi, çalışma anında `/sys/devices/system/cpu/cpu*/topology/thread_siblings_list`'ten okunan çekirdek kümelerinden, araç sırasına göre `k`. kümenin `ISCI_MANTIKSAL_CPU` mantıksal CPU'suna `sched_setaffinity` ile sabitlenir (üç araç için çakışmayan, aynı fiziksel çekirdeğe ait çiftler); eşleme araç günlüğüne yazılır. Diğer süreçlerin bu kümenin dışında tutulması bu sürümde yoktur (M6).

**Kuyruk [varsayım: belgede iç kuyruğun yapısı yok].** Alıcının iç kuyruğu bellek içidir ve sınırsızdır; tüketici tek iş parçacığıdır, uçuştaki kare sayısı 1'dir; işçi geride kalırsa sıradaki kareler bekler (atılmaz) ve kuyruk derinliği araç günlüğüne (`kuyruk_derinligi`) ve özet satırına (`kuyruk_maks`) yazılır. Disk destekli kuyruk B13'tür; `kuyruga_giris` olayının anlamı bu sürümde "alıcının iç kuyruğa verme anı" olarak kalır (B13'te kesinleşir).

**İşçi ölümü ve zaman aşımı [varsayım: belgede işçi ölümü kuralı yok].** İşçi bir kareyi işlerken ölürse ya da `ISCI_KARE_ZAMAN_ASIMI_SN` içinde yanıt vermezse (işçi öldürülür): o kare `islem_hatasi` olur (hata metni nedeni yazar); işçi yeniden başlatılır (en çok `ISCI_YENIDEN_BASLAT_MAKS` kez; yeni işçi de ısınır); yeni işçi hazır olana dek sıradaki kareler kuyrukta bekler ve sonra işlenir (en az kare kaybı). Sınır aşılırsa ya da model yüklenemezse kalan kareler `islem_hatasi` olur; hiçbir durumda "tespit yok" yazılmaz. Test enjeksiyonu (varsayılan kapalı; durumu araç günlüğüne `isci_enjeksiyon_durumu` olarak yazılır): ortam değişkeni `ISCI_ENJEKSIYON=hata=<belirteç,…>;olum=<belirteç,…>` (`+k` = `n_ilk + k`).

**Kare sonucu tamlığı.** COMPLETE sonrası araç süreci kuyruğun boşalmasını bekler (`ISCI_KAPANIS_BEKLE_SN`); süre dolarsa kapanış karesi gelmemişse sondaki kayıpları yazdırır, hâlâ sonuçsuz kalan numaralar için `islem_hatasi` yazar (kayıtta hata metni "kapanışta işlenemedi"). Araç günlüğünün `kare_sonuclari_tamam` satırı dört durumun sayısını, `cift_sonuc` (ikinci sonuç denemesi, 0 beklenir) ve işçi başlatma/yeniden başlatma sayılarını verir.
