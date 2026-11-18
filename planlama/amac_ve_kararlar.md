# Bu deponun amacı ve karar bekleyen sorular

> Bu içerik önceden `README.md` içindeydi; GitHub ana sayfasında yalnız ilerleme görünsün diye buraya taşındı. Mikail oturum açınca `CLAUDE.md` ("Göreve başlarken", 2. adım) bu dosyadaki **Karar bekleyen sorular** bölümünü gösterir.

## Bu deponun amacı

Bu depo **detaylı dünya deposudur**: projenin tamamının detaylı (yıkık şehir) dünyayla yapılıp yapılamayacağını öğrenmek için açıldı. Ana depo sade dünyayla ayrı devam eder; sonuca göre hangisinin proje olacağına ekip karar verir. Detaylı dünya: `mikail/deneme-yikik-sehir` dalı (`deneme/yikik_sehir/`); model ve doku dosyaları depoda değil, ayrı arşivle paylaşılır.

**Kurallar:** belge (GŞÖA, el kitabı) ana odaktır; belgeden yalnız detaylı dünyayı kilitliyorsa sapılır ve bu açıkça sorulur. Ekibin kararları, varsayımları ve kilitli değerleri gerekirse değişebilir; karar Mikail'indir. Her değişiklik `planlama/kararlar.md`'ye yazılır. Ayrıntı: `CLAUDE.md`, "Esneklik kuralı".

**Yanıtlanacak sorular** (hepsi "evet" ise detaylı dünya proje olabilir):

| # | Soru | Neden kritik |
|---|---|---|
| 1 | **Cevap anahtarı:** sahnedeki moloz parçaları ve yıkık binalar ne olacak? Hepsi hedef listesine mi girecek, yoksa "enkaz" tanımı mı değişecek (ör. yalnız belirli yığınlar hedef, gerisi arka plan)? | Çözülmezse hedef listesinde olmayan her moloz yanlış alarm (FP) sayılır; precision ve FP ölçümü anlamsız olur. **En büyük soru.** |
| 2 | **Test kuralı:** test sahnesinde tam 15 insan + 15 enkaz ve hedef merkezleri arası ≥ 10 m detaylı şehirde sağlanabiliyor mu? | Belge kuralı (GŞÖA) |
| 3 | **Yüksek yapılar:** binalar ve kule (≈24 m) düz zemin varsayımını, "kısmi örtülme yok" kuralını ve 30 m uçuşu bozuyor mu? | Konum hesabı düz zemine dayanır; 30 m irtifa belgede |
| 4 | **Eğitim verisi:** 7.200 eğitim + 1.200 doğrulama görüntüsü ve etiketleri detaylı şehirlerden, tohumla (60 + 10 + 30 farklı sahne) üretilebiliyor mu? | M4 ve M5 tamamen buna bağlı |
| 5 | **Performans:** Mikail'in makinesinde (7500F) 3 İHA + PX4 + YOLO ile simülasyon gerçek zamanlı (RTF ≈ 1) dönüyor mu? | RTF düşerse ölçümler bozulur. Ön ölçüm (7950X, PX4 ve YOLO olmadan, 3 kamera): RTF 1,00, dünya +845 MiB GPU belleği |
| 6 | **Koşu altyapısı:** `araclar/kosu.sh` sahne dünyasını açabiliyor mu (`GZ_SIM_RESOURCE_PATH`)? | Bu yapılmadan hiçbir koşu başlamaz; ilk iş |

Önerilen sıra: önce 6 ve 5 (makine ve altyapı kaldırıyor mu), sonra 1–3 (tasarım kararları), en son 4 (en uzun iş).

### Karar bekleyen sorular

Soru 4, 5 ve 6 ölçüm ve iştir. Soru 1, 2 ve 3 ise **karar** ister. Kararı Mikail verir (`CLAUDE.md`, "Esneklik kuralı"); 1. karar projenin özünü etkilediği için ekiple konuşulması önerilir. Verilen karar `planlama/kararlar.md`'ye yazılır ve burada **Seçilen** satırı doldurulur.

#### Karar 1: Hangi moloz "hedef"? (soru 1)

**Durum:** detaylı şehirde ~1046 moloz parçası ve 23 yıkık bina var; sistemin bulması gereken yalnız 15 enkaz hedefi tanımlı.
**Neden sorun:** sonuç, cevap anahtarına (hedef listesi) göre puanlanır. Model gerçek bir molozu bulsa bile o moloz listede yoksa **yanlış alarm (FP)** sayılır; model haksız yere kötü görünür, precision ve FP/görev anlamsızlaşır.

| Seçenek | Ne demek | Artı | Eksi |
|---|---|---|---|
| **A** Her şey hedef | Bütün moloz ve yıkık binalar hedef listesine girer | Cevap anahtarı tam | Belge test sahnesinde **tam 15 enkaz** diyor; 1000+ hedef belgeyle çelişir |
| **B** Enkaz tanımı daralır | Yalnız belirli bir tür hedeftir (ör. yıkık ev); geri kalan moloz arka plandır, model ikisini ayırt etmeyi öğrenir | Detaylı görünüm korunur; gerçekçi | Arka plan, hedeften görsel olarak **açıkça farklı** olmalı; benzerse FP artar. Tanım yazılı ve ölçülebilir olmalı |
| **C** Arka plan molozu azalır | 15 enkaz hedefi kalır; diğer moloz kaldırılır ya da moloza benzemeyen öğelere (araç, yol izi, leke) çevrilir | Ölçüm en temiz | Detaylı görünüm azalır, sade dünyaya yaklaşır |

**Öneri: B.** Hedef = yıkık ev (ana depodaki A1 tanımıyla aynı, Collapsed House ve varyantları). Arka plandaki moloz yıkık eve benzemeyen biçimde kalır: yassı, dağınık, küçük parçalar; ev biçiminde yığın yok. Ön koşul: 30 m görüntülerinde arka plan molozu ile yıkık evin karışmadığı gözle ve bir deneme eğitimiyle (FP sayısı) sınanır; karışıyorsa C'ye geçilir.
**Seçilen:** —

#### Karar 2: Yüksek yapılar kalsın mı? (soru 3)

**Durum:** şehirde katlı yıkık binalar ve ≈ 24 m'lik bir kule var; İHA'lar yerden 30 m'de uçar (belge).
**Neden sorun:** (a) konum hesabı "yer düz" varsayımına dayanır; yüksek yapılar bunu bozar. (b) Bina bir hedefin önünü kapatırsa kısmi örtülme olur; belgede örtülme yoktur. (c) 24 m'lik kule 30 m'deki kameraya 6 m kalır ve görüşü kapatır.

| Seçenek | Ne demek | Artı | Eksi |
|---|---|---|---|
| **A** Yüksek yapılar kalkar | Yalnız alçak yıkık yapılar kalır (≤ 5 m, ana depodaki `ENKAZ_YUKSEKLIK_MAKS_M` ile aynı) | Konum hesabı ve örtülme kuralı korunur; belgeyle çelişki yok | Şehir siluetinin bir kısmı gider |
| **B** Kalır, hedefler uzak tutulur | Binalar kalır; hedefler binalardan, örtülme olmayacak uzaklıkta yerleşir | Görünüm zengin kalır | Her sahnede örtülme denetimi gerekir; kule görüşü yine kapatır; kenarda kesik bina görüntüleri FP üretebilir |
| **C** İrtifa yükselir | Uçuş 30 m'den yükseğe alınır | Yapılar sorun olmaz | **Belgeden sapma** (FR-7: 30 m); insanlar daha da küçülür (30 m'de zaten 6–8 px); önerilmez |

**Öneri: A.** 5 m'yi aşan yapılar (kule, katlı binalar) sahneden çıkarılır; alçak yıkık yapılar, araçlar ve arka plan kalır. Belgeyle çelişki doğurmayan tek seçenek budur.
**Seçilen:** —

#### Karar 3: 100 sahne nasıl üretilecek? (soru 2 ve 4)

**Durum:** proje 60 eğitim + 10 doğrulama + 30 test sahnesi ister; her sahne tohumdan otomatik üretilir, bölümler ayrıktır. Test sahnesinde tam 15 insan + 15 enkaz ve hedef merkezleri arası ≥ 10 m (belge). Detaylı şehir şu an **tek, elle hazırlanmış** bir sahnedir.

| Seçenek | Ne demek | Artı | Eksi |
|---|---|---|---|
| **A** Şehir sabit, hedefler değişir | Yollar, yapılar ve arka plan her sahnede aynı; tohumla yalnız hedeflerin yeri, yönü, görünüm varyantı ve ışık değişir | Az iş; mevcut sahne üreticisine yakın | Model aynı arka planı ezberleyebilir; eğitim ve test arka planı aynı olur |
| **B** Şehir de her sahnede üretilir | Yapı ve moloz dağılımı da tohumla değişir | En gerçekçi; ezber riski yok | En çok iş: şehir üreticisi yazılmalı; her sahnede yerleşim ve örtülme denetimi |
| **C** Birkaç sabit şehir | 3–5 farklı şehir düzeni hazırlanır; eğitim, doğrulama ve test **ayrı** düzenlerden seçilir; hedefler tohumla değişir | Ezber riski azalır, iş makul | A'dan fazla, B'den az iş |

**Öneri: önce A, gerekirse C.** Fizibilite için en hızlı yol A: mevcut şehirde hedefler tohumla yerleşir, 15 + 15 ve ≥ 10 m kuralı üreticide denetlenir. Deneme eğitiminde arka plan ezberi görülürse (doğrulamada iyi, farklı düzende kötü) C'ye geçilir. B fizibilite için gereksiz büyük iş.
**Seçilen:** —
