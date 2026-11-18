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

Mevcut anahtarlar (ağ, kimlik/port, kamera, çıkarım, eğitim) değişmedi; tek istisna: `MAVSDK_GRPC_PORTS` 50051–50053 → 20051–20053 (2026-11-16, `planlama/kararlar.md`: belgelenmiş sapma) ve `MERKEZI_TCP_PORT_TABAN` 47200 → 27200 (Linux geçici port aralığının dışına). Eklenenler:

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
| `BIRLESTIRME_ARALIK_M` | 2,5 | belge, kilitli (FR-19: aynı sınıf ve adayın sabit ilk konumuna en fazla 2,5 m; hedef birleştirme B15 ve nihai rapor doğrulayıcısı (§11.1) buradan okur) |
| `DEGERLENDIRME_ESLESME_ESIK_M` | 5 | belge, kilitli (FR-28: doğru sınıf ve en fazla 5 m yatay uzaklık şartıyla bire bir atama; değerlendirme B18, `araclar/degerlendirme.py` buradan okur) |
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
| `POZ_ARALIK_SINIR_MS` | 100 | belge (öngörülen değer; protokolde kilitlenir): kareyi çevreleyen iki telemetri örneği arasındaki en büyük süre, ms; sınıra eşitlik geçerli, aşım → o kare konumsuz |
| `POZ_BEKLE_SN` | 0,25 | varsayım (kare anı en son örnekten sonraysa sonraki örnek için en çok bekleme, gerçek sn; bekleme ölçüme dahildir) |
| `POZ_TAMPON_SN` | 60 | varsayım (poz tamponunun saklama penceresi, kaynak sn) |
| `ZEMIN_Z_M` | 0 | belge (bilinen düz zemin)/varsayım (değer): konum hesaplayıcının ışını kesiştirdiği düz zemin düzleminin ortak yerel ENU'daki yüksekliği (m; z yukarı); dünya dosyasındaki zemin düzlemi z = 0'dadır. Test anahtarı (yalnız ortam değişkeni, varsayılan kapalı): `KONUM_TEST_SAHTE=x1,y1,x2,y2[;...]` çıkarım işçisinin başarılı yanıtına sabit piksel kutulu sahte tespit ekler |
| `MERKEZI_TCP_PORT_TABAN` | 27200 | varsayım (merkezi mod: araç sırası k için yer istasyonunun `GCS_ADDR` üzerindeki dinleme portu = taban + k − 1) |
| `SENTETIK_YUK_PORT_TABAN` | 27100 | varsayım (yalnız test aracı: `dds_doygunluk_testi.sh` sentetik yük dinleme portu, araç sırası k için taban + k − 1; deneyin kendisinde kullanılmaz) |
| `MERKEZI_BAGLAN_SN`, `MERKEZI_BOSALT_SN` | 60, 60 | varsayım (araç kanalının bağlanma denemesi üst sınırı; TAMAMLANDI sonrası gönderim kuyruğunun boşalması için üst sınır; gerçek sn) |
| `MERKEZI_KUYRUK_KAYIT_SN` | 1 | varsayım (gönderim kuyruğu derinliği kaydı aralığı, gerçek sn) |
| `MERKEZI_YUK_MAKS_BAYT` | 16777216 | varsayım (alıcının kabul ettiği en büyük yük uzunluğu; 640 × 480 × 3 = 921 600 bayt) |
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

Sabit portlar Linux geçici port aralığının (`/proc/sys/net/ipv4/ip_local_port_range`, öntanımlı 32768–60999) dışında olmalıdır; `sozlesme_dogrula.py` ve portu açan bileşenler aralığı çalışma anında okuyup denetler. DDS portları `ROS_DOMAIN_ID`'ye bağlıdır (7400 + 250 × alan kimliği, 250 port); öntanımlı 42'de 17900–18149 aralığındadır ve sabit portlarla çakışmaz; alan kimliği değiştirilirse çakışma olabilir (kod değişmez).

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
  kayit/kare_sonuc_<arac>.jsonl   kare sonuçları: her görev numarası için tam bir kayıt (8.6). Uçta modda araç sürecinin, merkezi modda yer istasyonunun yazdığı dosya (aynı şema; merkezi modda `poz` alanı dolu)
  kayit/gonderim_kuyrugu_<arac>.jsonl  merkezi mod: gönderim kuyruğu derinliği, periyodik (8.12; `tur: kuyruk_durumu`)
  kayit/isleme_kuyrugu_<arac>.jsonl    merkezi mod: yer istasyonunun araç başına işleme kuyruğu derinliği, periyodik (8.12; `tur: isleme_kuyrugu`)
  kayit/merkezi_sha_<arac>.jsonl, kayit/merkezi_sha_alim_<arac>.jsonl  yalnız test (MERKEZI_SHA=1): araçta gönderilen / yer istasyonunda alınan görüntü baytlarının SHA-256'sı; serbest biçim, şema değildir
  kayit/telemetri_<arac>.jsonl    px4_adapter'ın aldığı her odometri örneği: kaynak zamanı, konum, yönelim, kabul/ret (8.10; `tur: telemetri`)
  kayit/kare_poz_<arac>.jsonl     araç sürecinin her görev numarası için kare üretim anındaki enterpolasyonlu PX4 pozu ya da geçersizlik nedeni (8.11; `tur: kare_poz`)
  kayit/isci_kaynak_<arac>.jsonl  çıkarım işçisinin periyodik GPU kullanımı/belleği, ana bellek ve CPU kaydı (8.7)
  kayit/arac_sureci_<arac>.jsonl  araç sürecinin kare sonucu gönderim kaydı: her FrameResult yayımı için `kare_olay` `gonderim` (8.3; kaynak arac_sureci)
  yer_istasyonu.log, yer_istasyonu.out, yer_istasyonu.cikis  yer istasyonu görev koordinatörünün metin günlüğü (ISO saat, monotonik ns, olay, anahtar=değer), standart çıktısı ve çıkış kodu (`kosu.sh bekle` okur)
  arac_<k>.out, arac_<k>.cikis    araç sürecinin standart çıktısı ve çıkış kodu (kosu.sh --yer-istasyonu ile başlatıldıysa)
  kayit/yer_istasyonu_gorev.jsonl yer istasyonu görev olay kaydı: Mission ataması, hazır bildirimleri, eşleşme, t0, tarama bitişleri, son sonuç, t1, TAMAMLANDI, zaman aşımı (8.9; `tur: gorev_olay`)
  kayit/yer_istasyonu_durum.jsonl yer istasyonu izleme kaydı (serbest biçim, şema değildir): araç durum/ilerleme değişimleri, `IZLEME_OZET_SN` özetleri, bayat durum uyarıları
  kayit/yer_istasyonu_durum_ham.jsonl yer istasyonu izleme ham kaydı (serbest biçim): her `VehicleState` iletisinin alım anı (mono), yer istasyonu sim saati ve iletideki sim damgası (DDS canlılık ölçümü)
  gz_gercek_poz.jsonl             yalnız poz tamponu denemesinde (setup/poz_tamponu_testi.sh tek; araclar/poz_gercek_kayit.py): Gazebo gerçek model pozu ve simülasyon saati; serbest biçim, şema değildir
  tc_ornek.jsonl, sentetik_yuk.jsonl  yalnız doygun hat denemesinde (setup/dds_doygunluk_testi.sh): tc 1:10/bfifo sayaç örnekleri (araclar/tc_izle.py) ve sentetik yük kaydı (araclar/sentetik_yuk.py); serbest biçim
  kayit/yer_istasyonu_komut.jsonl komut yolu iskeleti kaydı (serbest biçim): komut gönderimi ve onay (yalnız test/elle kullanımda yazılır)
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
| `yapilandirma_sha256`, `ortam_kilidi_sha256`, `rota_sha256`, `kaynak_sha256` | `config/deney.env`, `setup/locks/sha256sums.txt` ve `config/bolge_rota.json` özetleri. Rota dosyası sahne dosyasından girdi almaz; aynı rota özeti bütün sahnelerde aynıdır (bölge ve rota dosyaları tüm sahnelerde aynı). `rota_sha256` sürüm 1'de 2026-11-14'ten itibaren zorunludur (bu tarihten önceki geliştirme koşularının `kosu.json` dosyalarında yoktur). `kaynak_sha256`: koşudan hemen önce derlenen kaynağın özeti (sürüm 1'de 2026-11-14'ten itibaren zorunlu): `src/` altındaki dosyaların (git'in izlediği ve izlenmeyen ama `.gitignore` dışı olanların) sıralı "yol, içerik SHA-256" satırlarının SHA-256'sı; git commit'inden bağımsızdır, kirli çalışma ağacında da doğrudur; `araclar/kosu.sh baslat` her koşuda derleme yaptığından `install/` bu kaynaktan derlenmiştir. |
| `arac_sayisi`, `arac_kimlikleri` | 1…`UAV_SYS_IDS` uzunluğu; kimlikler `UAV_SYS_IDS` değerleri (MAV_SYS_ID). |
| `mimari_modu` | `kosu.sh baslat --mimari` değeri (öntanımlı `ucta`; `KOSU_MIMARILER`: `ucta` \| `merkezi`). Ya da `"yok"` (eski kayıtlar). |
| `sahne_kimligi` | Şimdilik `null`; sonra sahne dosyasının kimliği. |
| `dunya`, `model`, `gz_partition` | `SIM_WORLD`, `SIM_MODEL` ve koşuya özgü izole Gazebo bölümü. |
| `surecler` | `{ad, pid, grup}` listesi (`gz_sunucu`, `px4_<i>`). |
| `bitis_durumu` | `null` (sürüyor) \| `tamamlandi` \| `zorla_kapatildi` \| `yarida_kaldi`. `bitis` ile birlikte dolu ya da birlikte `null`. |
| `zorla_kapatilan` | Yalnız `zorla_kapatildi` iken, SIGKILL ile kapatılan süreç adları (sessiz değil, açıkça yazılır). |
| `test_anahtarlari` | **İsteğe bağlı** (eski kayıtlarda yok): `kosu.sh baslat` anında ortamda dolu olan test anahtarlarının adları (`KONUM_TEST_SAHTE`, `KAMERA_ENJEKSIYON`, `MERKEZI_SHA`, `MERKEZI_ARAC_ENJEKSIYON`, `ISCI_ENJEKSIYON`, `MERKEZI_ENJEKSIYON`); değerler yazılmaz. Boş liste = test anahtarı yok. |

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
| `olay` | `uretim`, `kuyruga_giris`, `aktarim_tamam`, `cikarim_basi`, `cikarim_sonu`, `kullanilabilir` [belge: üretim, uygulama kuyruğuna giriş, ilgili aktarımın tamamlanması, çıkarım başlangıcı, çıkarım bitişi, kullanılabilirlik]; ayrıca araç sürecinin `gonderim_kuyrugu` (merkezi mod: iletinin gönderim kuyruğuna girdiği an) ve `gonderim` kayıtları [varsayım: aşama değil, tanı kaydı: uçta modda araç kare sonucunu yayım kuyruğundan DDS'e verdi; merkezi modda iletinin son baytı sokete yazıldı; `mono_ns` = yayım çağrısının döndüğü an; `sim_damga_ns` = karenin ızgara damgası; yalnız kaynak `arac_sureci` yazar]; yer istasyonunun merkezi moddaki `alim` kaydı (iletinin tam alındığı an; yalnız kaynak `yer_istasyonu` yazar) [varsayım: aşama değil, tanı kaydı; aşama damgaları B13'tedir]; ayrıca kamera alıcısının YEREL kayıtları `kayip_tespit`, `gec_geldi` ve `yok_sayildi` (aşağıda; zaman aşaması değildir, ağa gönderilmez) [varsayım: belge "geç geldi" kaydının yalnız yerel kayda yazılacağını söyler, olay adını söylemez]. |
| `mono_ns` | `CLOCK_MONOTONIC` ns, **pozitif tam sayı**; ya da `"uygulanmaz"`. [belge] Uygulanmayan aktarım aşaması "uygulanmaz" gösterilir, sıfır süreli gerçek aktarım gibi yorumlanmaz: `0`, boş (`null`) ve ondalık değer reddedilir. [varsayım] `"uygulanmaz"` yalnız `kuyruga_giris` ve `aktarim_tamam` için yazılabilir. |
| `sonuc_durumu` | `kullanilabilir` olayında zorunlu: `sonuc` (STATUS_DETECTIONS) \| `tespit_yok` (STATUS_NO_DETECTION) \| `kare_alinamadi` (STATUS_FRAME_NOT_RECEIVED) \| `islem_hatasi` (STATUS_PROCESSING_ERROR) [varsayım, kullanıcı kararı 2026-11-14: belge işlem hatasını kullanılabilirlik ve t1 koşulunda anmaz; işlem hatası t1'i ENGELLEMEZ, ayrı sayılır; gecikme L'ye, "sonuç üreten kare" oranına ve "kare alınamadı" oranına GİRMEZ] (`kullanilabilir` yer istasyonunda sonucun/kaydın kullanılabilir olduğu andır; kayıp tespitinde bunu alıcı değil yer istasyonu yazar). `kayip_tespit` olayında yalnız `kare_alinamadi`. Dört durum ayrıdır ve karışmaz. **`gec_geldi` burada YOKTUR**: belge geç gelen kareyi işlemez ve ağa göndermez, yalnız yerel kayda "geç geldi" yazar; bu yüzden yer istasyonunda kullanılabilir bir durum değil, kamera alıcısının yerel olayıdır (`olay: gec_geldi`). |
| `neden` | Yalnız `yok_sayildi` olayında zorunlu: `gorev_oncesi` (damga n_ilk'ten önce ya da tarama başlamadan) \| `kapanis_sonrasi` (n_son'dan büyük kare) \| `izgara_disi` (n türetilemedi; `n = "izgara_disi"`) \| `tekrar` (numara zaten görev karesi olarak kabul edilmişti). |

Zamanlar ondalık saniye değildir; ölçekleme ve yuvarlama yapılmaz [belge]. Bir dosyada aynı (araç, `n`, damga, olay) ikinci kez yazılamaz (yerel `gec_geldi`/`yok_sayildi` kayıtları için alım anı `mono_ns` de anahtardadır; aynı kare birden çok kez gelebilir). Örnekler: `config/ornek/kare_olay_gazebo_damga_ornek.jsonl`, `config/ornek/kare_olay_yer_istasyonu_ornek.jsonl`, `config/ornek/kare_olay_kamera_alici_ornek.jsonl`.

### 8.4 Koşu betiği

`araclar/kosu.sh baslat [--arac N] [--yer-istasyonu var|yok] | durdur | durum | temizle | bekle [--sure-sn S]` (hepsi `--dry-run` destekler). `baslat` önce başka `gz sim`/`ruby`/`px4`/`mavsdk_server` süreci ya da bitmemiş koşu olmadığını denetler; Gazebo sunucusunu, sonra N PX4 SITL örneğini ayrı süreç gruplarında başlatır. **`--yer-istasyonu` verilmezse yalnız Gazebo + PX4 başlar** (PX4'e kendi bağdaştırıcısıyla bağlanan testler için eski davranış); `--yer-istasyonu var` ardından yer istasyonu görev koordinatörünü (`yer_istasyonu`) ve N araç sürecini (`arac_<k>`) başlatır (sıra: Gazebo → PX4'ler → yer istasyonu → araç süreçleri; hazır ölçütleri: koordinatör `KOORDINATOR hazir`, araç günlüğünde `basladi`); `--yer-istasyonu yok` araç süreçlerini başlatır, koordinatörü başlatmaz (deneme koordinatörüyle olumsuz testler). `bekle` yer istasyonu çıkana dek bekler ve çıkış kodunu döndürür (0 tamam; 1 zaman aşımı/hata; 124 bekleme süresi doldu; 3 koordinatör kodsuz öldü). `durdur` SIGTERM ile önce araç süreçlerini ve yer istasyonunu, sonra yetim mavsdk_server'ları, sonra PX4'leri, **Gazebo en son** (sunucuda çalışan kayıt bileşeninin son boşaltmayı yapması için) kapatır; kendiliğinden çıkış 0 ile bitmiş araç/yer istasyonu süreci ölü sayılmaz; `KOSU_KAPANIS_SN` dolarsa SIGKILL uygular ve `kosu.json`'a `zorla_kapatildi` yazar. `temizle` bu betiğin başlattığı süreç gruplarını kapatır, koşu klasörünü silmez, `yarida_kaldi` yazar. **Erken araç çıkışı (kullanıcı kararı 2026-11-16):** `--yer-istasyonu var` koşusunda COMPLETE yayımlanmadan önce herhangi bir araç süreci çıkarsa (çıkış kodu ne olursa olsun; t0 öncesi ya da sonrası) yer istasyonu gecikmesiz biter: COMPLETE yayımlanmaz, `hata` olayı (`neden: arac_erken_cikti`, §8.9) ve `arac_erken_cikti` günlük satırı yazılır, çıkış kodu 1 (`bekle` 1 döndürür); ardından `durdur` (ya da `temizle`) kalan süreçleri her zamanki sırayla kapatır ve ölü süreç bulunduğundan `bitis_durumu = yarida_kaldi` yazar. Algılama süreç çıkışına dayanır: araç sürecini saran kabuk, süreç çıkınca çıkış kodunu `arac_<k>.cikis` dosyasına yazar (k = 1..N) ve yer istasyonu bu dosyaları ana döngüsünde okur; DDS durum iletisinin bayatlamasına (`IZLEME_BAYAT_SN`) dayanmaz ve `bekle` çağrılmasa da çalışır. COMPLETE'ten sonraki olağan araç çıkışı bu kurala girmez. Süreç grubunun tamamı sarmalayıcıyla birlikte öldürülürse (`.cikis` yazılmaz) algılama `durdur`/`temizle` aşamasına kalır. `durdur` ve `temizle`, `MAVSDK_GRPC_PORTS` üzerinde dinleyen yetim `mavsdk_server` süreçlerini de (bağdaştırıcı kapatmadıysa) önce SIGTERM ile kapatır ve kosu.json süreç listesine `mavsdk_server_<gRPC portu>` adıyla yazar.

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
| `tespit_sayisi`, `tespitler` | `tespit` durumunda en az bir öğe, diğer üç durumda **boş liste** (boş liste + `islem_hatasi` "tespit yok" demek değildir). Öğe: `sinif` (`MODEL_SINIFLAR` adı), `sinif_no` (o listedeki sıra: insan 0, enkaz 1 = `Detection.CLASS_*`), `guven` ([`INF_CONF`, 1]), `kutu` ([x_min, y_min, x_maks, y_maks] piksel, orijin sol üst, görüntü içinde), `konum` (`[dogu_m, kuzey_m]` ortak yerel ENU, m; ya da **null** = konumsuz, `has_position = false`; bkz. §10.4), `konum_neden` (`null` konum doluyken; konum `null` iken zorunlu: `poz_yok` = kare için geçerli poz yok ya da kare–poz kullanılamadı (merkezi modda yüklü dosyadan farklı kalibrasyon kimliği dahil), `kesisim_yok` = ışın zemine doğru değil/paralel ya da kesişim kameranın arkasında), `aday` (**false**: birleştirme adayı B15'tir; `candidate = false`). Konumlu tespit yalnız geçerli kare–pozla üretilir (`poz.gecerli` false iken konum `null`). |
| `atilan_sinif_disi` | Çıkarımın bulduğu ama proje sınıfına eşlenmediği için atılan tespit sayısı (COCO ön eğitimli ağırlıkta `person` dışındaki sınıflar). `kare_alinamadi` için 0. |
| `hata` | `islem_hatasi` durumunda boş olmayan metin; diğer durumlarda `null`. |
| `mono_ns` | Kare sonucunun oluşturulduğu an (uçta modda araç sürecinde, merkezi modda yer istasyonunda), `CLOCK_MONOTONIC` ns (pozitif tam sayı). |
| `poz` | **İsteğe bağlı, yalnız merkezi modda**: görüntü iletisinin başlığından alınan kare–poz (tespitlerin konumu bu pozla hesaplanır, §10.4). Alanlar `kare_poz` kaydındakilerle aynı kurallarla (§8.11): `gecerli`, `neden`, `t1_ns`, `t2_ns`, `aralik_ms`, `konum_ned_m`, `q_wxyz` (`bekleme_ms` yoktur). Uçta modda alan bulunmaz. |

[varsayım] Sınıf eşlemesi: işçi modelin kendi sınıf adını döndürür; araç süreci adı `MODEL_SINIFLAR`'daki bir ada eşitse birebir kullanır (M5 modeli), değilse `MODEL_ESLEME_COCO` tablosuna bakar (COCO ön eğitimli ağırlık, yalnız M1 boru hattı sınaması: `person → insan`); tabloda olmayan sınıf atılır ve `atilan_sinif_disi` ile sayılır. Çıkarım bitip hiç proje sınıfı tespiti kalmazsa durum `tespit_yok`'tur. Doğrulayıcı: `sozlesme_dogrula.py <dosya>.jsonl` (ilk dolu satırdaki `tur`). Örnek: `config/ornek/kare_sonuc_ornek.jsonl`.

### 8.7 İşçi kaynak kaydı (`tur: "isci_kaynak"`, JSON Lines, taslak sürüm)

Çıkarım işçisi, kendi sürecinin kaynak kullanımını `ISCI_KAYNAK_SN` aralıkla (gerçek saniye) `kayit/isci_kaynak_<arac_kimligi>.jsonl` dosyasına yazar [belge: GPU kullanımı ve GPU belleği süreç başına periyodik; ana bellek]. Alanlar: `surum`, `tur`, `arac_kimligi`, `isci_pid`, `mono_ns` (`CLOCK_MONOTONIC` ns), `gpu_kullanim_yuzde` (NVML `nvmlDeviceGetProcessUtilization`: son örneklemeden beri sürecin SM kullanımı, 0–100 tam sayı; NVML yoksa `null`), `gpu_bellek_mib` (NVML `nvmlDeviceGetComputeRunningProcesses`: sürecin GPU belleği; yoksa `null`), `ana_bellek_rss_mib` (`/proc/self/statm`), `cpu_yuzde` (sürecin CPU süresi / geçen süre, tek mantıksal CPU = %100; ilk kayıtta `null`). `sudo` gerekmez. Bellek ve GPU için üst sınır konmaz [belge]. Örnek: `config/ornek/isci_kaynak_ornek.jsonl`.

### 8.9 Görev olay kaydı (`tur: "gorev_olay"`, JSON Lines, taslak sürüm)

Yer istasyonu görev koordinatörünün (`/gcs/mission_coordinator`) koşu kaydı: `kayit/yer_istasyonu_gorev.jsonl`. Satır başına bir olay; `kare_olay` (§8.3) kare aşamalarının kaydıdır, bu kayıt görev düzeyindedir. Örnek: `config/ornek/gorev_olay_ornek.jsonl`.

| Alan | Açıklama |
|---|---|
| `surum`, `tur` | `1`, `"gorev_olay"` |
| `olay` | `gorev_atandi` (araç, mission_id: Mission yayımlandı), `hazir` (araç: ilk BARIYER_BEKLE alındı), `eslesme` (`yayimci`: sayı her DEĞİŞTİĞİNDE yazılır, artış ve azalış dahil; uçta modda kare sonucu konusunda eşleşmiş yayımcı sayısı, merkezi modda kanalı bağlı (kaynak adresi doğrulanmış) ve çıkarım işçisi hazır araç sayısı), `t0` (ScanStart yayımlandı; `mission_id`), `tarama_bitisi` (araç, `n_ilk`, `n_son`), `son_sonuc` (bütün bitişler ve bütün kare sonuçları tamam: COMPLETE koşulu sağlandı), `t1` (Complete yayımlandı; `mission_id`, `t1_eksi_son_bitis_ns`), `tamamlandi` (araç: TAMAMLANDI alındı), `zaman_asimi` (üst süre doldu; COMPLETE yayımlanmadı), `birlestirme_yok` (hedef birleştirme M3'tedir), `yok_sayildi` (erken/yinelenen/yanlış kimlikli olay; `neden`), `hata` (açık hata; `neden`: ör. `kanal_hatasi` — merkezi mod görüntü kanalı hatası; `arac_erken_cikti` — COMPLETE'ten önce bir araç SÜRECİ çıktı, `arac_kimligi` o araç, `ayrinti` = `cikis_kodu=<k> evre=t0_oncesi\|t0_sonrasi`; `merkezi_baslatma_hatasi` — merkezi mod dinleme başlatılamadı (port aralığı ihlali ya da bağlama hatası), `ayrinti` = hata metni, koşu başlamaz). |
| `mono_ns` | `CLOCK_MONOTONIC` ns, pozitif tam sayı; kayıt sırası monotoniktir (olay, yazıldığı andan itibaren). `t0` ve `t1` için yayımlama anıdır (T = t1 − t0). |
| `sim_ns` | Yer istasyonunun gz-transport saatinden simülasyon saati (ns) ya da `null` (saat henüz/hiç alınmadıysa). T = t1 − t0 hem `mono_ns` hem `sim_ns` farkıyla hesaplanır. |
| `arac_kimligi`, `mission_id`, `n_ilk`, `n_son`, `t_s_ns`, `t_b_ns`, `yayimci`, `t1_eksi_son_bitis_ns`, `neden`, `ayrinti` | İsteğe bağlı/olaya özgü alanlar. `t_s_ns`/`t_b_ns`: ızgara yolunda `ScanFinished` t_s/t_b taşımadığı için `null` (belge: kullanılmayan alanlar 0); araç günlüğündeki `tarama_bitis_yayimlandi` satırı taşır. |

Dosya kuralları: en çok bir `t0` ve bir `t1`; `t1` ancak `t0` ve `son_sonuc` olaylarından sonra yazılabilir (COMPLETE yalnız bütün kare sonuçlarından sonra); `mono_ns` geriye gitmez. Yedek yol (`NUMBERING_FALLBACK`) bu sürümde `hata` (`yedek_yol_desteklenmiyor`) olarak reddedilir (M3/B13).

### 8.10 Telemetri kaydı (`tur: "telemetri"`, JSON Lines, taslak sürüm)

[belge] PX4 konum/yönelim telemetrisi yüksek hızda alınır ve kaynak zamanına göre saklanır; bu kayıt bunun kanıtıdır. `px4_adapter`, `telemetry.odometry()` akışından aldığı HER örneği (kabul edilen ya da reddedilen) `kayit/telemetri_<arac_kimligi>.jsonl` dosyasına yazar. Yazma ayrı bir yazıcı iş parçacığıdır (kuyruk; adapter akışını bloke etmez). PX4'e hiçbir şey yazılmaz (hız komutu yok). Alanlar: `surum`, `tur`, `arac_kimligi`, `kaynak_ns` (PX4 `time_usec` × 1000), `alinma_mono_ns` (`CLOCK_MONOTONIC`), `konum_ned_m` ([kuzey, doğu, aşağı], PX4 yerel NED, orijin: aracın ev konumu), `q_wxyz` (gövde FRD → NED, birim kuaterniyon), `kabul` (tampona eklendi mi), `red_neden` (`null` | `geriye_giden` | `yinelenen` | `gecersiz_deger` | `enjeksiyon` [yalnız test anahtarı]). Sonlu olmayan değerler (NaN/inf) standart dışı JSON olarak yazılmaz: `konum_ned_m`/`q_wxyz` içinde `null` olur ve kayıt `kabul: false`, `red_neden: gecersiz_deger` taşır (yalnız bu durumda null ve birim olmayan kuaterniyon geçerlidir). Yazıcı hataları (açılamama, yazılamama) ve kapanıştan sonra gelen kayıtlar sayılır ve araç/adapter günlüğüne yazılır; sessizce atılmaz. Kabul edilen örneklerde `kaynak_ns` kesin artar. Örnek: `config/ornek/telemetri_ornek.jsonl`.

### 8.11 Kare–poz kaydı (`tur: "kare_poz"`, JSON Lines, taslak sürüm)

[belge] Her görüntü iletisi, karenin üretildiği ana eşlenmiş canlı PX4 poz tahminini taşır; eşleme **kaynak zamanına** göre yapılır: kare üretim anı `t` (ızgara damgası, `n · 10⁹ / CAM_RATE_HZ` ns; PX4 `time_usec` ile aynı eksen kabul edilir, K8) için `t`'yi çevreleyen iki örnek `t1 ≤ t ≤ t2`; konum doğrusal, yönelim küresel (kısa yol, normalize). Tam örnek anında o örnek (`t1 = t2`, `aralik_ms = 0`). `t2 − t1 > POZ_ARALIK_SINIR_MS` ise geçerli poz yoktur (`aralik_asildi`); `t` ilk örnekten önceyse `tampon_disi`; `t` en son örnekten sonraysa sonraki örnek için en çok `POZ_BEKLE_SN` beklenir, dolarsa `bekleme_asildi`. Hiçbir durumda en son örnek ya da 2 Hz durum mesajı yedek olarak kullanılmaz: geçerli poz yokken `konum_ned_m` ve `q_wxyz` `null`'dır. Bekleme süresi her kayıtta `bekleme_ms` olarak yazılır (ölçüm dışında bırakılmaz).

Araç süreci, kare sonucunu ürettiği her görev numarası için (kare alınamadı ve işlem hatası numaraları dahil) **tam bir** kayıt yazar: `kayit/kare_poz_<arac_kimligi>.jsonl`. Alanlar: `surum`, `tur`, `arac_kimligi`, `n`, `kare_ns`, `gecerli`, `neden` (`null` | `aralik_asildi` | `tampon_disi` | `bekleme_asildi` | `hata`), `t1_ns`, `t2_ns` (`aralik_asildi` ve geçerli pozda dolu, diğerlerinde `null`), `aralik_ms`, `bekleme_ms`, `konum_ned_m`, `q_wxyz`. `hata` yalnız bu araç içi kayıtta bulunur (poz sorgusu istisna verdi; kayıt yine de yazılır ve sayılır; o karenin tespitleri `poz_yok` ile konumsuz kalır); ağ iletisi ve kare sonucundaki `poz` alanı bu nedeni taşımaz. Tespitlerin konumu bu pozla hesaplanır (§10.4); poz kare sonucuna uçta modda girmez, merkezi modda iletiden gelen `poz` alanı olarak saklanır. Kare işleme iş parçacığı en çok `POZ_BEKLE_SN` bloke olabilir; "kare alınamadı" yolu (gz kamera geri çağrısından gelir) poz beklemesiyle geri çağrıyı bloke etmez: aynı bekleme sınırı ve aynı kurallarla ayrı bir iş parçacığında, çağrı sırasıyla tamamlanır (her numara bir kez). Doğrulayıcı: `sozlesme_dogrula.py <dosya>.jsonl`. Örnek: `config/ornek/kare_poz_ornek.jsonl`.

### 8.12 Kuyruk durum kayıtları (`tur: "kuyruk_durumu"` ve `"isleme_kuyrugu"`, JSON Lines, taslak sürüm)

[belge] Her koşunun gerçek üretim hızı, kare sayısı ve kuyruk durumu kaydedilir. Merkezi modda her araç süreci, TCP görüntü kanalının gönderim kuyruğunu `MERKEZI_KUYRUK_KAYIT_SN` aralıkla (ve kapanışta bir kez daha) `kayit/gonderim_kuyrugu_<arac_kimligi>.jsonl` dosyasına yazar. Alanlar: `surum`, `tur`, `arac_kimligi`, `mono_ns` (`CLOCK_MONOTONIC`), `ileti` / `bayt` (kuyrukta bekleyen, gönderimi tamamlanmamış ileti sayısı ve bayt), `giren_ileti` (kuyruğa giren toplam), `gonderilen_ileti` / `gonderilen_bayt` (son baytı sokete yazılan toplam). Tutarlılık: `ileti = giren_ileti − gonderilen_ileti`; zaman ve toplam sayaçlar geriye gitmez. Örnek: `config/ornek/kuyruk_durumu_ornek.jsonl`.

[varsayım] Araç kuyruğu yalnız **ağ kaynaklı** birikmeyi gösterir; merkezdeki **çıkarım** birikmesi ayrı görünsün diye yer istasyonu da her aracın işleme kuyruğunu `MERKEZI_KUYRUK_KAYIT_SN` aralıkla (ve kapanışta bir kez daha) `kayit/isleme_kuyrugu_<arac_kimligi>.jsonl` dosyasına yazar. Alanlar: `surum`, `tur` (`isleme_kuyrugu`), `arac_kimligi`, `mono_ns` (yer istasyonu `CLOCK_MONOTONIC`; araç saatiyle doğrudan karşılaştırılmaz), `ileti` (işleme kuyruğunda bekleyen ya da işlenmekte olan ileti sayısı), `giren_ileti` (kuyruğa giren toplam), `islenen_ileti` (işlenmesi biten toplam). Tutarlılık: `ileti = giren_ileti − islenen_ileti`; zaman ve toplam sayaçlar geriye gitmez. Örnek: `config/ornek/isleme_kuyrugu_ornek.jsonl`.

## 9. ROS 2 konuları (taslak)

Belge konu adlarını ve QoS değerlerini **tanımlamaz**; aşağıdaki her ad ve ayar **[varsayım]**dır. Adlar `config/deney.env`'de (`KONU_*`) tek yerde durur. **Kesin QoS B11/M2'de belirlenir (U14, U21)**; bu bölüm yalnız bu sürümün çalışan ayarıdır. Bütün araç süreçleri ve yer istasyonu aynı Fast DDS profilini (`config/fastdds_profil.xml`) ve ölçülen sürü ağını kullanır; araç süreci kendi adresini `SWARM_BIND_ADDR` ile alır.

| Konu (varsayım) | Tür | Yayımlayan → abone | QoS (varsayım) |
|---|---|---|---|
| `/swarm/vehicle_state` (`KONU_DURUM`) | `swarm_msgs/VehicleState` | her araç, 2 Hz [belge] → diğer araçlar ve yer istasyonu | reliable, volatile, keep_last 10 |
| `/swarm/scan_start` (`KONU_TARAMA_BASLAT`) | `swarm_msgs/ScanStart` | yer istasyonu (görev koordinatörü), bir kez (t0) → araçlar | reliable, transient_local, keep_last 1 |
| `/swarm/scan_finished` (`KONU_TARAMA_BITIS`) | `swarm_msgs/ScanFinished` | her araç, rota bitince bir kez → yer istasyonu (ve diğer araçlar) | reliable, transient_local, keep_last 10 |
| `/swarm/complete` (`KONU_COMPLETE`) | `swarm_msgs/Complete` | yer istasyonu, bir kez (t1) → araçlar | reliable, transient_local, keep_last 1 |
| `/swarm/mission` (`KONU_GOREV`) | `swarm_msgs/Mission` | yer istasyonu (görev koordinatörü), her araç için bir ileti (`vehicle_id`) → araçlar (kendi `vehicle_id`'sini süzer) | reliable, transient_local, keep_last 10 |
| `<ad alanı>/command` (`KONU_KOMUT`, örn. `/uav_2/command`) | `swarm_msgs/Command` | yer istasyonu → ilgili araç (komut yolu iskeleti; koşu akışında kullanılmaz) | reliable, volatile, keep_last 10 |
| `/gcs/command_ack` (`KONU_KOMUT_ONAY`) | `swarm_msgs/Command` | araç → yer istasyonu (aynı `vehicle_id` ve `sequence`, `ack_state`) | reliable, transient_local, keep_last 20 |
| `/swarm/frame_result` (`KONU_KARE_SONUC`) | `swarm_msgs/FrameResult` | her araç, her görev numarası için bir kez, dört durum dahil (uçta mod, B11) → yer istasyonu | reliable [belge], transient_local, keep_last 1000 (`QOS_KARE_SONUC_*`) |

- **Tek durum konusu:** üç araç ve yer istasyonu aynı konuya yayımlar/abone olur; durum iletisi `vehicle_id` taşır [belge: "ortak durum konusu"]. Araç, kendi iletisini kayda almaz.
- **Kontrol iletileri** (başlatma, bitiş, COMPLETE) kaybolmamalıdır [belge: WAIT'ten yalnız COMPLETE ile çıkılır]: reliable. **transient_local** seçilmesinin gerekçesi, yazıcının aboneyi sonradan keşfetmesi durumunda (keşif sırası belirsizdir) iletinin yine de teslim edilmesidir; eski bir koşunun iletisi ise durum makinesinin kurallarıyla (BARIYER_BEKLE dışında başlatma yok sayılır, görev kimliği eşleşmeyen COMPLETE yok sayılır) etkisizdir. Derinlik 1: yalnız son başlatma/COMPLETE tutulur.
- **Mission ve görev ataması** [varsayım]: belge rotanın kalkıştan önce `px4_adapter` ile PX4'e yüklendiğini, yer istasyonu komutlarının araç kimliği/sıra/onay taşıdığını söyler; M0'da tanımlı `Mission` iletisini kullanıyoruz. Yer istasyonu `config/bolge_rota.json`'ı (tek doğru kaynak; SHA-256'sı koşu üst verisinde `rota_sha256`) okur ve her araca kendi Mission'ını ortak `mission_id` ile yayımlar. Araç rotayı PX4'e yüklemeden önce kendi Mission'ını bekler (`GOREV_BEKLE_SN`), yerel `bolge_rota.json` ile BİREBİR karşılaştırır (araç, bölge, noktalar, irtifa, hız) ve yalnız eşitse, Mission'daki noktalardan yükler; uyuşmazlık açık hata (araç çıkış kodu 4, yükleme yok), Mission gelmezse çıkış kodu 5. `ScanStart`/`Complete` aynı `mission_id`'yi taşır (araç farklı kimlikli tarama başlatmayı yok sayar). transient_local: araç koordinatörden sonra başlasa da Mission'ı alır.
- **Komut yolu iskeleti** [varsayım; kullanıcı kararı 2026-11-14]: belge komut türlerini tanımlamaz → tür uydurulmaz ve PX4'e hiçbir şey yazılmaz. `swarm_gcs.komut_arayuzu` (`komut_gonder` aracı) araç komut konusuna `Command` gönderir (`ack_state = ACK_PENDING`); araç `px4_adapter.komut_isle`'ye iletir (`_yaz` çağırmaz): yanlış araç, tekrar ya da geriye giden sıra ve (denetimi geçen komut için) "komut türü belgede tanımlı değil" nedenleriyle `ACK_REJECTED` döner; onay aynı `vehicle_id` ve `sequence` ile ortak onay konusundan yayımlanır. Komut gönderimi yalnız test/elle kullanım içindir; koordinatör komut göndermez.
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

### 10.3 Merkezi mod: TCP görüntü kanalı ve yer istasyonu çıkarımı (B12)

**Mod seçimi [belge: iki mimari].** Koşu düzeyindedir: `kosu.sh baslat --mimari ucta|merkezi` (öntanımlı `ucta`); değer `kosu.json` `mimari_modu` alanına yazılır ve araç süreçlerine ile yer istasyonuna `MIMARI_MODU` ortam değişkeniyle verilir. Merkezi modda araç sürecinde çıkarım işçisi **başlatılmaz** ve `FrameResult` DDS'ten **yayımlanmaz**; uçta modda TCP kanalı **açılmaz**. İki mod aynı kaynak-zaman eşleme ve enterpolasyon kuralını (§8.11), aynı sonuç yapısını (§8.6) ve aynı sonuç defterini kullanır.

**Kanal [belge: araç başına TCP görüntü kanalı].** Her araç için ayrı TCP bağlantısı. Yer istasyonu `GCS_ADDR:(MERKEZI_TCP_PORT_TABAN + k − 1)` üzerinde dinler (k: `UAV_SYS_IDS` içindeki 1 tabanlı sıra), araç `UAVk_ADDR` kaynak adresiyle bağlanır; trafik ölçülen sürü ağından (lo üzerindeki htb) geçer, 127.0.0.1 kullanılmaz. Kaynak adresi beklenenden farklı bağlantı reddedilir ve günlüğe yazılır [varsayım: bağlantı kimliği = port + kaynak adres; ayrı bir "merhaba" iletisi yoktur]. Kanal bariyerden **önce** kurulur: koordinatör bariyeri ancak her araç BARIYER_BEKLE bildirdiyse, her aracın kanalı bağlı ve kaynak adresi doğrulanmışsa ve her araç için yer istasyonu çıkarım işçisi hazırsa açar. Bağlantı koparsa yeniden bağlanma YOKTUR [varsayım]: açık hata, COMPLETE yayımlanmaz, koşu tamamlanamaz; sessiz kayıp yoktur. Bağlantının yarım iletisiz (temiz) kapanması da, aracın sonuç defteri o anda tamam değilse (tarama bitişi gelmemiş ya da `[n_ilk, n_son]` eksik; alınan bütün iletiler işlendikten sonra denetlenir) açık kanal hatasıdır ve koordinatör koşuyu zaman aşımını beklemeden hatayla sonlandırır; defter tamamken kapanış normaldir.

**Kimlik denetimi [varsayım].** Bariyerdeki "kanal bağlı ve kimliği doğrulandı" koşulu yalnız **kaynak adres** (`UAVn_ADDR`) ve **port** eşleşmesine dayanır; ayrı bir tanışma (merhaba) iletisi yoktur. Araç kimliği ayrıca her iletide denetlenir (porta göre beklenen kimlikle eşleşmeyen ileti açık hatadır); bağlantı kurulduktan sonra ilk iletiye kadar kimlik doğrulaması bu iki bilgiyle sınırlıdır.

**İleti [belge alanları; kodlama varsayım].** Küçük-endian, sabit başlık + değişken uzunluklu kalibrasyon kimliği + sabit poz bloğu + yük. Üretimin monotonik zamanı iletide **taşınmaz** [belge; gecikme hesabında Gazebo damga kaydından, araç kimliği ve sim damgasıyla eklenir].

| Bölüm | Biçim | Alanlar |
|---|---|---|
| 1 (33 bayt) | `<4sBBBIqqIH` | sihirli değer `SWGI`; sürüm (1); ileti türü (1 `goruntu` \| 2 `kare_alinamadi`); numaralandırma kipi (1 ızgara); araç kimliği (u32); kare numarası (i64); sim damgası (i64, ns); yük uzunluğu (u32); kalibrasyon kimliği uzunluğu (u16) |
| 2 | UTF-8 | kamera kalibrasyon kimliği (`config/kamera_kalibrasyon.json` `kalibrasyon_kimligi`; en çok 256 bayt) |
| 3 (74 bayt) | `<BB3d4dqq` | poz geçerli (0/1); poz neden kodu (0 yok \| 1 `aralik_asildi` \| 2 `tampon_disi` \| 3 `bekleme_asildi`); konum NED (3 × f64); kuaterniyon wxyz (4 × f64); t1 ns (i64; yoksa −1); t2 ns (i64; yoksa −1). Poz geçersizse konum/kuaterniyon sıfırdır ve alıcı bunları kullanmaz |
| 4 | bayt | yük: görüntü iletisinde Gazebo'dan gelen 640 × 480 RGB8 baytları değiştirilmeden (921 600); `kare_alinamadi` iletisinde yük uzunluğu **0** |

`kare_alinamadi` iletisi görüntü iletileriyle **aynı gönderim kuyruğunda, numara sırasını koruyarak** gider ve §8.6'daki `STATUS_FRAME_NOT_RECEIVED` kaydıyla aynı alanları taşır (poz da sorgulanır); ölçülen ağdan geçtiği için D'ye dahildir. Poz, kare üretim anına (ızgara damgası) §8.11 kuralıyla eşlenir; poz beklemesi kuyruğa girişten önce yapılır ve `kare_poz` kaydına yazılır (ölçüm dışı bırakılmaz). 2 Hz durum mesajı ya da "en son örnek" asla yedek değildir.

**Gönderim kuyruğu [belge: üretilmiş kareler atılmaz].** Araç başına FIFO; TCP geri basıncında (soket dolu) gönderici bekler ve kuyruk büyür, hiçbir kare atılmaz. Bu sürümde bellek içi ve sınırsızdır; disk destekli sürüm B13'tedir (arayüz: `koy`/`bak`/`cikar`/`derinlik`). Kuyruk derinliği periyodik kaydedilir (§8.12); kapanışta gerçek üretim hızı, kare sayısı ve kuyruk özeti araç günlüğüne (`merkezi_ozet`) yazılır.

**Araçta ileti hazırlama hatası.** Poz sorgusu ya da kodlama istisna atarsa, ya da görüntü baytları önbellekte bulunamazsa (boş yük), araç kareyi sessizce düşürmez ve **boş yüklü görüntü iletisi asla gönderilmez**: hata araç günlüğüne yazılır, kanal açık hatayla durdurulup kapatılır, araç süreci hatayla çıkar ve yer istasyonu eksik defteri açık hata olarak görür (koşu tamamlanamaz). Uçta modda bu durum farklıdır: boş görüntü çıkarım işçisine gider ve o kare `islem_hatasi` olur; iki mod arasındaki bu fark kasıtlıdır (merkezi kanal gönderilen baytın bozulmaması için kapanır).

**Alıcı doğrulaması.** Porta göre beklenen araç kimliği, sihirli değer ve sürüm, tür, uzunluklar denetlenir; bozuk ileti açık hatadır (bağlantı kapatılır). Kare numarası artan olmalıdır: tekrar eden ve geriye giden numara sayılır, günlüğe yazılır ve işlenmez; atlanan numara (boşluk) sayılır ve günlüğe yazılır (kayıp kare ancak `kare_alinamadi` iletisiyle bildirilir). Aralık dışı numara sonuç defterinde sayılır.

**Yer istasyonu çıkarımı.** Yer istasyonu sürecinde araç başına bir çıkarım işçisi (alt süreç; uçta moddaki `IsciIstemcisi` sınıfı, aynı model, aynı `INF_*`; araç k'nın akışı uçta moddaki araç k'nın işçisinin aldığı **aynı CPU kümesini** alır: `cpu_ata(k, …)`) çalışır; her araç için sınırsız bir işleme kuyruğu vardır (atma yok). Sonuç, uçta moddaki aynı mantıksal yapıdır (dört durum; `kare_alinamadi` iletisi `STATUS_FRAME_NOT_RECEIVED`'a çevrilir; işçi hatası `islem_hatasi`) ve aynı sonuç defterine / `kullanilabilir` kaydına teslim edilir. COMPLETE koşulu değişmez. Kayıtlar: araçta `gonderim_kuyrugu` ve `gonderim`, yer istasyonunda `alim` (§8.3), mevcut `cikarim_basi`/`cikarim_sonu`/`kullanilabilir`; işleme kuyruğu derinliği §8.12'deki `isleme_kuyrugu` kaydıdır.

**Test anahtarları (yalnız test, varsayılan kapalı).** Araç: `KONUM_TEST_SAHTE` (çıkarım yanıtına sabit piksel kutulu sahte tespit; açıkken günlükte `(!)` satırı, `konum_ozeti` sayacı ve `kosu.json` `test_anahtarlari` izi bırakır), `POZ_TEST_DURDUR` (telemetri örneklerini bir pencerede tampona eklemez), `KAMERA_ENJEKSIYON` (kare kaybı), `MERKEZI_SHA=1` (gönderilen görüntü SHA-256'sı), `MERKEZI_ARAC_ENJEKSIYON=kanal_kapat=<n>` (n numaralı iletiden sonra kanalı bilerek temiz kapatır; yer istasyonu açık hata vermelidir). Yer istasyonu: `ISCI_ENJEKSIYON` (işçi hatası), `MERKEZI_ENJEKSIYON=okuma_dur=<başlangıç_sn>:<süre_sn>` (ilk iletiden `başlangıç_sn` sonra `süre_sn` boyunca okumayı durdurur: geri basınç), `MERKEZI_SHA=1` (alınan görüntü SHA-256'sı).

### 10.4 Konum hesaplayıcı (B14; FR-17, FR-18)

[belge] Tespitin yatay konumu; kamera iç parametreleri, sabit kamera–araç dönüşümü ve kare üretim anına enterpolasyonla eşlenmiş PX4 konum/yönelim tahmini kullanılarak üretilir; kutu merkezinden çıkan ışın bilinen düz zemin düzlemiyle kesiştirilir ve ortak yerel ENU'ya çevrilir; PX4 NED verisi bu dönüşümde **açıkça** ENU'ya çevrilir. Aynı kod (`swarm_vehicle.konum_hesap`) iki modda da kullanılır: uçta modda araç süreci o karenin `kare_poz` sonucunu (yeni sorgu ve ikinci bekleme yok), merkezi modda yer istasyonu görüntü iletisinin başlığındaki pozu kullanır; merkezde gecikmiş kare 2 Hz durum mesajıyla konumlandırılmaz. [varsayım: belgede yok; sessiz yanlış konumu önlemek için] Kalibrasyon dosyası (`config/kamera_kalibrasyon.json`) okunamaz ya da bozuksa süreç başlamaz (açık hata). [belge] Testlerde hedeflerin gerçek koordinatı hesaplayıcıya verilmez.

Zincir: kutu merkezi `(u, v) = ((x_min + x_maks)/2, (y_min + y_maks)/2)` → OpenCV ışını `((u − cx)/fx, (v − cy)/fy, 1)` → gövde FLU (`R`) → gövde FRD `(x, −y, −z)` → NED (PX4 kuaterniyonu wxyz, gövde FRD → NED; kamera konumu = poz konumu + döndürülmüş `t_m`) → **açık NED → ENU** `x = x0 + doğu`, `y = y0 + kuzey`, `z = z0 − aşağı` (`x0, y0, z0` = o aracın `UAV_START_POSES` konumu; tek fonksiyon `ned_den_enu`; adaptörün `konum_enu_m` değeri de bunu çağırır) → ENU'da düz zemin düzlemi `z = ZEMIN_Z_M` ile kesişim. Çıktı `(doğu, kuzey) = (x, y)`.

Konumsuz kalma [belge FR-18]: kare için geçerli poz yoksa `poz_yok` (kare–poz nedeni `kare_poz` kaydında ayrıca korunur); ışının geçerli kesişimi yoksa (zemine doğru değil ya da paralel, kesişim kameranın arkasında, kutu sonlu değil) `kesisim_yok`. Kesişim için mesafe sınırı **yoktur** (belgede yok); kesişim mesafesi dağılımı araç/yer istasyonu günlüğündeki `konum_ozeti` satırında raporlanır. Konumsuz tespit konumsal birleştirmeye alınmaz ve ayrı konumsuz rapor olur [belge; birleştirme B15'tir]. `candidate` bu aşamada her tespitte false'tur.

**Kayıp kare ve sıra (kabul edilmiş davranış).** Uçta modda "kare alınamadı" sonucu gz kamera geri çağrısından gelir; poz tamponu varken poz beklemesi (en çok `POZ_BEKLE_SN`) geri çağrıyı bloke etmesin diye ayrı tek bir iş parçacığında tamamlanır (geri çağrı beklemeden döner; sıra korunur, her numara bir kez). Tek iş parçacığı olduğundan **sıradaki kayıp işler art arda tamamlanır**: pozu hazır bir kayıp karenin önünde bekleyen bir kare varsa o kare için en çok `POZ_BEKLE_SN` beklenir (telemetri durmuşken birikmiş k iş ≈ k × `POZ_BEKLE_SN`). Bu bir hata değil, kabul edilmiş davranıştır. Kapanışta kuyrukta bekleyen işler hesaba katılır (bekleme süresi `bekleyen + zorla + 1` iş kadar uzar); süre yetmezse açık günlük satırı (`kapanis_kayip_kuyrugu_bosalmadi`) yazılır ve kalan numaralar `islem_hatasi` olur. Günlükteki `kayip_cagri_maks_ms`, **yalnız `kayip()` çağrısının dönme süresidir** (gz geri çağrısının bloke olabileceği süre); poz beklemesini kapsamaz, o `kare_poz` kaydında `bekleme_ms` olarak ölçülür.

**Test anahtarı izi.** `KONUM_TEST_SAHTE` açıkken araç süreci ve yer istasyonu başlangıçta açık bir `test_anahtari_acik` günlük satırı (`seviye=(!)`) yazar; `konum_ozeti`'nde `sahte_tespit=<eklenen sahte tespit sayısı>` bulunur; koşu üst verisinde (`kosu.json`) `test_anahtarlari` listesi ortamda dolu olan test anahtarlarının adlarını taşır (değerler yazılmaz). Gerçek koşu kayıtlarında liste boş olmalıdır.

## 11. Değerlendirme arayüzleri (taslak sürüm)

Değerlendirme ve analiz yazılımının (B18, E1a–E5a; M6a) girdileri, onları **üreten** kilometre taşlarından (B15: M3; C8, C9: M6b) önce burada sabitlenir ("önce arayüz"). Terimler yalnız proje el kitabının terimler tablosundaki tanımlardan alınır; **yeni tanım uydurulmaz**; belgede açık olmayan her alan **[varsayım]** etiketlidir ve gerekirse M3/M6b'de depo sahibince kesinleşir. Değişiklik depo sahibinin onayıyla ve iki tarafa (üreten, okuyan) bildirilerek yapılır. Üç dosya da tek JSON nesnesidir (§1 genel kurallar: `surum`, `tur`, bilinmeyen alan hata, mutlak yol yazılamaz); `mod` değeri `KOSU_MIMARILER` anahtarındaki ad olarak yazılır (`ucta` | `merkezi`; kosu.json `mimari_modu` ile aynı). Doğrulama: `araclar/sozlesme_dogrula.py`; örnekler `config/ornek/*_ornek.json`, bozuk örnekler `config/ornek/bozuk/`. Bu bölüm yalnız **biçimi** sabitler; dosyaların üretimi ve okunması ilgili kilometre taşlarının işidir.

### 11.1 Nihai hedef raporu (`tur: "nihai_rapor"`)

Üreten: B15 (hedef birleştirme; M3). Okuyan: B18 (değerlendirme; M6a). Koşu başına bir dosya; yer istasyonunda **nihai hedef birleştirmesi tamamlandıktan sonra** yazılır. Birleştirme kuralı [belge]: tespitler üretim zamanı, araç ve kare numarası sırasıyla işlenir; aynı sınıftaki bir tespit mevcut adayın **sabit ilk konumuna en fazla `BIRLESTIRME_ARALIK_M` (2,5 m)** uzaklıktaysa o adaya eklenir, değilse yeni aday açılır; nihai konum, adaydaki **en yüksek güvenli** tespitin konumudur; gerçek hedef kimliği birleştirmede kullanılmaz (bu yüzden raporda gerçek hedef kimliği alanı **yoktur**; eşleştirme değerlendirmede yapılır).

| Alan | Tür / birim | Zorunluluk | Etiket | Açıklama |
|---|---|---|---|---|
| `surum`, `tur` | `1`, `"nihai_rapor"` | zorunlu | | |
| `kosu_kimligi`, `sahne_kimligi` | kimlik (§1) | zorunlu | [varsayım] | Koşu ve sahne kimlikleri (kosu.json ile aynı). |
| `mod` | `KOSU_MIMARILER` | zorunlu | [varsayım] | `ucta` \| `merkezi`. |
| `raporlar` | liste | zorunlu | [belge] | Nihai raporlar; hiç rapor üretilmeyen koşuda **boş liste** (P "tanımsız"). |
| `raporlar[].rapor_kimligi` | kimlik | zorunlu | [varsayım] | Koşu içinde tekil; gerçek hedef kimliği değildir. |
| `raporlar[].sinif` | `MODEL_SINIFLAR` | zorunlu | [belge] | `insan` \| `enkaz`. |
| `raporlar[].konum` | `{x_m, y_m}` ENU, m ya da `null` | zorunlu | [belge] | En yüksek güvenli tespitin konumu. `null` = **konumsuz rapor** (FP sayılır [belge]). |
| `raporlar[].ilk_konum` | `{x_m, y_m}` ya da `null` | zorunlu | [belge] | Adayın sabit ilk konumu; `konum` ile birlikte dolu/`null`; dolu iken aralarındaki yatay uzaklık ≤ `BIRLESTIRME_ARALIK_M`. |
| `raporlar[].guven` | sayı, `[INF_CONF, 1]` | zorunlu | [belge] | En yüksek tespit güveni (güven eşiği altı tespit yoktur). |
| `raporlar[].tespit_sayisi` | tam sayı ≥ 1 | zorunlu | [varsayım] | Adaya eklenen tespit sayısı. |
| `raporlar[].ilk_tespit`, `raporlar[].en_yuksek_guven_tespiti` | `{arac_kimligi, n, uretim_mono_ns}` | zorunlu | [varsayım] | Üreten araç (`UAV_SYS_IDS`), kare numarası ve karenin üretim anı (monotonik ns, t_üretim [belge]). `ilk_tespit` en yüksek güvenli tespitten sonra olamaz; tek tespitli adayda ikisi aynıdır. |

**Eşleştirme (B18, `araclar/degerlendirme.py`).** [belge, FR-28] Nihai rapor ile gerçek hedef (§5 hedef listesi; aynı `sahne_kimligi` zorunlu), doğru sınıf ve en fazla `DEGERLENDIRME_ESLESME_ESIK_M` (5 m, eşik dahil) yatay uzaklık şartıyla Macar algoritmasıyla bire bir atanır. TP = atanan benzersiz gerçek hedef, FP = atanmayan rapor (fazladan kopyalar ve konumsuz raporlar dahil), FN = atanmayan gerçek hedef; R = 100·TP/N (%), precision = TP/(TP+FP). Tanımsız değer sıfır yazılmaz: TP+FP = 0 ise precision `null`, N = 0 ise R `null`. [varsayım] Atama kuralı: önce TP en büyük, eşit TP'li atamalar arasında toplam yatay uzaklık en küçük; sınıf başına tek `linear_sum_assignment` çağrısıyla (uygun olmayan çiftlere her uygun atamadan büyük maliyet). Raporlar ve hedefler kimliğe göre sıralanarak işlenir (dosya sırası sonucu değiştirmez); gerçek hedef kimliği atama ölçütü değildir. Çıktı (JSON): toplam ve sınıf bazlı `n, tp, fp, fn, r_yuzde, precision`, `konumsuz_rapor`, `eslesmeler[] {rapor_kimligi, hedef_kimligi, sinif, uzaklik_m}`, `eslesmeyen_raporlar[] {rapor_kimligi, sinif, neden: konumsuz|eslesmedi}`, `eslesmeyen_hedefler[] {hedef_kimligi, sinif}`.

### 11.2 Koşu ölçüm özeti (`tur: "kosu_olcum"`)

Üreten: C8, C9 (M6b). Okuyan: E2a–E5a (M6a analiz betikleri; gerçek verilerle E2b–E5b, M8b). Koşu başına bir dosya. Tanımlar [belge, el kitabı terimler tablosu]: **T = t1 − t0** (s; t0 başlangıç bariyerini açıp tarama başlatma mesajının yayımlandığı an, t1 ortak COMPLETE mesajının yayımlandığı an); **D** = t0–t1 penceresinde sınırlayıcının gönderilmiş bayt sayaçlarının farkı, **MB = 10⁶ bayt**, düşen paketler dahil değil, t1 sayacı COMPLETE gönderilmeden okunur, **COMPLETE baytları D'ye girmez ve ayrıca kaydedilir**; **B = 8D/T** (Mbit/s; ortalama ağ trafik hızıdır, bağlantı kapasitesi değildir); **L = t_kullanılabilir − t_üretim** (s), her sahne ve mod için pozitif ve negatif bütün **başarılı** kare sonuçları üzerinden **ortanca ve 95. yüzdelik**; "kare alınamadı" ve işlem hatası kareleri L'ye girmez. İki oran ayrıdır, paydaları beklenen görev karesi sayısıdır: **sonuç üreten kare oranı** (kullanılabilir kare sonucu bulunan kareler) ve **kare alınamadı oranı** (yalnız "kare alınamadı" kaydı üretilen kareler; işlem hatası olan kareler bu orana girmez). Geç gelen kare sayısı ayrıca raporlanır.

| Alan | Tür / birim | Zorunluluk | Etiket | Açıklama |
|---|---|---|---|---|
| `surum`, `tur` | `1`, `"kosu_olcum"` | zorunlu | | |
| `kosu_kimligi`, `sahne_kimligi`, `mod` | §11.1 ile aynı | zorunlu | [varsayım] | |
| `tamamlandi` | bool | zorunlu | [belge] | Koşu t1'e ulaştı mı. |
| `tamamlanamadi` | `null` ya da `{neden, gozlenen_sure_s, kismi_trafik_mb}` | zorunlu | [varsayım] | `tamamlandi = false` iken zorunlu nesne: `neden` ∈ `zaman_asimi`, `kuyruk_tasmasi`, `surec_olumu`, `diger`; `gozlenen_sure_s` > 0 (sağdan sansürlü süre, s); `kismi_trafik_mb` ≥ 0 ya da `null` (E5a: sansürlü gösterim, kısmi trafik). |
| `t0_mono_ns`, `t1_mono_ns` | pozitif tam sayı (monotonik ns) ya da `null` | zorunlu | [belge] | `t1_mono_ns` tamamlanamayan koşuda `null`; `t0` hiç yayımlanmadıysa `null`. |
| `t_s` | sayı, s | zorunlu | [belge] | T; tamamlanan koşuda dolu ve `(t1 − t0)/10⁹` ile uyumlu (1 ms), aksi `null`. |
| `d_mb` | sayı ≥ 0, MB (10⁶ bayt) | zorunlu | [belge] | D; tamamlanan koşuda dolu, aksi `null`. §11.3'teki `d_bayt` / 10⁶ ile aynı olmalıdır (ayrı dosyalar arası uyum M6b'de denetlenir). |
| `complete_bayt` | tam sayı ≥ 0 | zorunlu | [belge] | COMPLETE baytları (D dışında); tamamlanan koşuda dolu, aksi `null`. |
| `b_mbit_s` | sayı, Mbit/s | zorunlu | [belge] | B = 8·`d_mb`/`t_s` (göreli 10⁻⁶); tamamlanmayan koşuda `null`. |
| `l` | `{ornek_sayisi, ortanca_s, p95_s}` | zorunlu | [belge]/[varsayım] | Başarılı kare sonuçları üzerinden; `ortanca_s` ≤ `p95_s`; `ornek_sayisi` = 0 ise ikisi `null` (gecikme sıfır yazılmaz [belge]); `ornek_sayisi` ≤ pozitif + negatif. Alan adları [varsayım]. |
| `kare_sayilari` | `{beklenen, pozitif, negatif, kare_alinamadi, islem_hatasi, gec_geldi}` | zorunlu | [belge]/[varsayım] | Tam sayılar ≥ 0. Dört durum (`pozitif` = tespitli sonuç, `negatif` = "tespit yok", `kare_alinamadi`, `islem_hatasi`) toplamı `beklenen`'i aşamaz; **tamamlanan koşuda eşittir** (t1 koşulu: her beklenen kare için sonuç ya da "kare alınamadı" kaydı). İşlem hatası, 2026-11-14 işlem hatası kararıyla tutarlı olarak ayrı sayılır ve t1'i engellemez. |
| `sonuc_orani` | sayı `[0, 1]` ya da `null` | zorunlu | [belge]/[varsayım] | (`pozitif` + `negatif`)/`beklenen`; `beklenen` = 0 ise `null`. Birim [varsayım]: oran, yüzde değil. |
| `kare_alinamadi_orani` | sayı `[0, 1]` ya da `null` | zorunlu | [belge]/[varsayım] | `kare_alinamadi`/`beklenen`. |
| `kaynak_kayitlar` | `{gorev_olay, kare_olay[], sayac_kaydi}` | zorunlu | [varsayım] | Koşu klasörüne göreli dosya yolları: `gorev_olay` (§8.9), `kare_olay` (§8.3; her kaynak için bir dosya), `sayac_kaydi` (§11.3). Mutlak yol ve `..` yazılamaz. |

### 11.3 Sınırlayıcı bayt kaydı (`tur: "sayac_kaydi"`)

Üreten: C8 (M6b). Okuyan: C8/C9 (11.2'deki D bu kayıttan hesaplanır). Koşu başına bir dosya. [belge] Ölçülen ağın bütün trafiği tek ortak kapasite sınırlayıcıdan geçer; D, sınırlayıcının t0 ve t1 anlarında okunan **gönderilmiş bayt sayaçlarının farkıdır**; her gönderim sınırlayıcının çıkışında bir kez sayılır; kuyruktan çıkmadan düşen paketler D'ye eklenmez, **düşme sayısı ve bekleyen talep ayrı sayaçlardan raporlanır**; **t1 sayacı COMPLETE gönderilmeden okunur**, COMPLETE baytları D'ye girmez ve ayrıca kaydedilir.

| Alan | Tür / birim | Zorunluluk | Etiket | Açıklama |
|---|---|---|---|---|
| `surum`, `tur` | `1`, `"sayac_kaydi"` | zorunlu | | |
| `kosu_kimligi`, `mod` | §11.1 ile aynı | zorunlu | [varsayım] | |
| `sinirlayici` | `{cihaz, sinif}` | zorunlu | [varsayım] | `cihaz`: ağ aygıtı adı (boş olmayan metin); `sinif`: ölçülen sürü ağının sınıfı, `"1:10"` (`setup/60_ag_emulasyon_tc.sh`). |
| `t0`, `t1` | okuma | zorunlu | [belge] | Okuma = `{mono_ns, gonderilen_bayt, gonderilen_paket, dusen_paket, bekleyen_talep}`: monotonik ns (pozitif) ve **birikimli** sayaçlar (tam sayı ≥ 0). `t1` okuması COMPLETE gönderilmeden önce yapılır. |
| `complete_sonrasi` | okuma ya da `null` | zorunlu | [varsayım] | COMPLETE'in araçlara ulaşmasından sonraki okuma; okunmadıysa `null`. |
| `d_bayt` | tam sayı ≥ 0, bayt | zorunlu | [belge] | `t1.gonderilen_bayt − t0.gonderilen_bayt` (D, bayt cinsinden; MB için 10⁶'ya bölünür). |
| `complete_bayt` | tam sayı ≥ 0 ya da `null` | zorunlu | [belge] | `complete_sonrasi.gonderilen_bayt − t1.gonderilen_bayt`; `complete_sonrasi` `null` ise `null`. |

Doğrulayıcı kuralları: okumalar zamanda geriye gitmez; birikimli sayaçlar (bayt, paket, düşen paket) `t0` → `t1` → `complete_sonrasi` sırasında azalmaz; `d_bayt` ve `complete_bayt` okumalardan türeyen farklara eşittir. Bu kayıt D'nin tek kaynağıdır; "ağın atlanmadığının kanıtı" yerine geçmez (sayaç–kayıt tutarlılığı C4'ün işidir).
