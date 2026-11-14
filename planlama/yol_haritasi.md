# Yol haritası: kabul testlerine ve ana deneylere giden sıra

Bu dosya, [`gelistirme_agaci.md`](gelistirme_agaci.md) maddelerinin **hangi sırayla ve hangi bağımlılıklarla** yapılacağını anlatır. Maddelerin kendisi, ağırlıkları ve bitti ölçütleri ağaçtadır; burası onları aşamalara (milestone) böler. Bu bir simülasyon deneyidir; gerçek uçuş ya da operasyonel yeterlilik iddiası yoktur.

## Yöntem

Tek ekip, tek bilgisayar ve birbirine bağlı parçalar için hafif ama disiplinli bir yöntem:

1. **Önce sözleşme.** Birden çok parçanın paylaştığı arayüzler (sahne dosyası şeması, kamera ve kalibrasyon dosyası, ROS 2 mesajları, deney yapılandırması) kod yazılmadan sabitlenir. Sonradan değişirse bütün parçalar etkilenir.
2. **Yürüyen iskelet.** Tek aracın uçtan uca (Gazebo, PX4, araç süreci, kamera, çıkarım, sonuç, yer istasyonu, değerlendirme) *kaba ama çalışan* bir hattı en baştan kurulur; sonra parçalar iyileştirilir. Parçaları ayrı ayrı mükemmelleştirip sonda birleştirmek, entegrasyon sürprizlerini en pahalı ana bırakır.
3. **Kapı kuralı.** Her aşama (milestone) yalnızca kendi entegrasyon testini geçtiğinde biter. Madde bitti ölçütü ağaçta durur; aşamanın kapısı bir önceki parçalarla *birlikte* çalıştığını da sınar.
4. **Riski öne al.** En belirsiz işler (çok süreçli koordinasyon, kayıp kare mantığı, kesme testi) erken denenir.
5. **Kilit disiplini.** Kilitli değerler (25 Mbit/s, çıkarım ayarları, görüş açısı, batch, karar kuralları) sonuçlara bakılarak değiştirilmez; her karar [`kararlar.md`](kararlar.md) dosyasına gerekçesiyle yazılır, riskler [`riskler.md`](riskler.md) dosyasında izlenir.

## Belgede olanlar ve açık bırakılanlar

| Konu | Belgede ne var? | Bu haritada nasıl ele alınıyor? |
|---|---|---|
| Alan ve bölgeler | Alan üç çakışmayan bölgeye ayrılır, her araca bir bölge ve sabit rota; düzen tüm sahnelerde aynı (FR-1). **Alanın boyutu yazılı değil.** | Tasarım varsayımı olarak 300 m × 300 m, üç bölge 100 m × 300 m. Pilotlarda (C11) doğrulanır, gerekirse değiştirilir. |
| İrtifa ve kamera | 30 m sabit; 640 × 480, 2 kare/s, aşağı bakan; görüş açısı ölçülerek belirlenir. | Yapıldı: 65°, kilitli. |
| Uçuş hızı, rota uzunluğu, tarama süresi | **Pilotlarda belirlenir**, sayısal değer yok. | M7'de pilotla; M1–M6'da geçici bir hız kullanılır. |
| Sahne, rota, kalibrasyon dosyaları | Deney paketinde saklanır; sahne dosyası hedef kimliklerini, sınıflarını ve konumlarını içerir. **Dosya biçimi yazılı değil.** | M0'da biçim tasarlanır ve sabitlenir. |
| Model | A planı ve B planı; B birinci öncelik (kararlar.md). | M5. |

## Bağımlılık zinciri

```
Sözleşmeler (sahne şeması, alan, kamera, mesajlar, yapılandırma)
   │
   ├─ Sürü hattı: rota → PX4 adaptörü → araç süreci → yer istasyonu
   │              kamera → damga → alıcı → çıkarım → sonuç → uçta/merkezi mod → kuyruk → konum → birleştirme
   │
   └─ Veri hattı: sahne üretici → bölümler → etiket → görüntü → kontrol → eğitim pilotu → eğitim → epoch → kilit
                          │                                                       │
                          └──────────── ikisi birleşir: değerlendirme + iki modda tam koşu ─────────┘
                                          → kabul testleri → pilotlar → kilitler → otomasyon → ana deneyler → analiz
```

- Sürü hattı ve veri hattı **yalnızca pilotlarda (C11) buluşur**; pilotlar nihai modelle çalışır.
- Üç yer aynı kaynağı paylaşır ve ardışık çalışmalıdır: Gazebo ve GPU. Eğitim ana koşularla eşzamanlı yapılmaz (belge).

## Aşamalar

Yürütme sırası: **M0 → M1 → [M2 → M3] ve [M4 → M5] (iki ayrı hat, paralel) → M6 → M7 → M8.** Sürü hattı (M2, M3) ile veri hattı (M4, M5) birbirinin koduna bağlı değildir; yalnız sözleşmeleri (M0) ve M1'de kilitlenen alanı paylaşır. Numaralar içerik gruplarıdır.

| Aşama | Maddeler | Adımlar | Kapı (bitti sayılması için) |
|---|---|---|---|
| **M0 Sözleşmeler** ✔ | B1 ve sahne, rota, kalibrasyon biçimleri | Mesaj paketi, sahne/rota/kalibrasyon/hedef listesi biçimleri ve doğrulayıcı | Dosyalar kilitli; şema doğrulaması geçer; mesaj paketi derlenir (B21 "tüm başlatma dosyaları tek dosyadan okur" ölçütü M1 ve M7'de kapanır) |
| **M1 Tek araç iskeleti** ✔ | B2 (tek bölge), B3, B4 (tek araç), B6, B7, B8, B9 (hazır ağırlıkla), B10 | 1.1 Gazebo sunucusunda kare yayımlanma anının nasıl kaydedileceği keşfi (B7, FR-23). 1.2 Koşu başlat/durdur/temizle betiği ve tek kayıt şeması. 1.3 B3 `px4_adapter` ve B2 tek bölge rota. 1.4 B4 araç süreci ve durum makinesi. 1.5 B6 kamera, B7 damga, B8 alıcı. 1.6 B9, B10 çıkarım işçisi. 1.7 Alan ve rota mini pilotu, alan kilidi | Her görev karesi için sonuç ya da "kare alınamadı"; durum geçişleri testli; kayıp ve geç kare senaryoları testli; alan ve bölge geometrisi `config/deney.env`'de kilitli |
| **M2 Üç araç** (hat 1) ✔ | B2 (üç bölge), B5, B11 | 2.1 Üç bölge ve rotalar. 2.2 Yer istasyonu, ortak başlangıç, COMPLETE. 2.3 Uçta mod. 2.4 M3'ten önce: merkezi mod doygunluğunda DDS canlılığı deneyi (sentetik yük) | Üç araç ortak başlar, ortak biter; t0 ve t1 doğru anlarda; 2.4 sonucu riskler dosyasında |
| **M3 Merkezi mod ve izleme** (hat 1) | B12, B13, B14, B15 | Merkezi mod, disk destekli kuyruklar, konum hesabı, hedef birleştirme | İki modda tam koşu kayıpsız; bilinen pozda konum hatası < 5 m; birleştirme testleri |
| **M4 Veri hattı** (hat 2) | A1, A2, A3, A4, A5, A12 | A1 sahne üretici kodu M1 sırasında da yazılabilir; A2 listeleri ve A4 görüntüleri alan kilidinden sonra üretilir | Tohumdan aynı sahne; bölümler ayrık; sayılar tamam; etiket kontrolü yapıldı |
| **M5 Model** (hat 2) | A7, A9, A10, A11 (kayıt), A13 | Eğitim süresi pilotu, B planı eğitimi (`nms=False` açık), epoch seçimi, özetler. Eğitim sürerken aynı GPU'da Gazebo çalıştırılmaz | Seçilen epoch kayıtlı; model ve veri özetleri kilitli |
| **M6 Değerlendirme ve kabul** | B18, B19, C1–C9 | Eşleştirme yazılımı, bütünleşik koşu, beş kabul testi, ölçümler. Ayrıca E1–E5 analiz betikleri sentetik veriyle yazılıp sınanır (E maddeleri M8'de gerçek sonuçla kapanır) | Beş kabul testi iki modda geçer; analiz betikleri sentetik örnekte doğru |
| **M7 Pilotlar ve kilit** | C10–C14, B21 | Kuyruk sınırı, 6 pilot, H, protokol kilidi (karar kuralı kodu dahil), koşu otomasyonu | Bir çift otomatik koşar; H ve protokol kilidi yazılı |
| **M8 Ana deneyler ve analiz** | D1–D5, E1–E7 | 30 sahne × 2 mod, gerçek verilerle analiz, rapor | Her koşu tamamlandı ya da "tamamlanamadı" kayıtlı; tablolar ve rapor |

## Neden bu sıra?

- **M0 önce:** sahne dosyasını hem sahne üretici (A1) üretir hem değerlendirme (B18) ve tam koşu (B19) okur; alanı hem A1 kurar hem rota (B2) kullanır; kamerayı hem veri üretimi hem sürü yazılımı kullanır. Bunlar sonradan değişirse iki hat birden bozulur.
- **M1 hemen sonra:** en büyük belirsizlikler (PX4 görev yükleme, kamera akışı, kare kayıp mantığı, yayımlanma anı kaydı) burada çıkar; en ucuz zamanda görünür olurlar. Alan boyutu belgede yazılı değildir ve sahne listeleri ile görüntüleri ona dayanır; bu yüzden M4'ün liste ve görüntü üretimi alan kilidini bekler.
- **M2, M3 ayrı hat:** en riskli iş (çok süreçli koordinasyon, merkezi moddaki doygun hat) erken denenir. 25 Mbit/s hattında üç kameranın ham yükü 44,2368 Mbit/s olduğu için (GŞÖA 6.5) DDS mesajlarının doygun hatta ulaşıp ulaşmadığı M3'ten önce (2.4) sınanır; bu bir hipotezdir, ölçülmeden varsayılmaz.
- **M4, M5 ayrı hat:** sürü kodundan bağımsızdır; yalnız sözleşmelere ve alan kilidine bağlıdır. Eğitim büyük GPU belleği ister (batch=16 için ayrılan tepe bellek yaklaşık 10,8 GiB, bkz. `kararlar.md`); aynı GPU'yu Gazebo kamerası da kullanabilir (GŞÖA 5.2), bu yüzden eğitim sürerken Gazebo çalıştırılmaz.
- **M6'dan önce M5:** pilotlar (M7) nihai modelle yapılır, çünkü tarama süresi ve ağ yükü model çıkarım süresini içerir.
- **Analiz betikleri M6'da:** karar kuralı veri toplanmadan kilitlenmelidir (FR-30, GŞÖA 6.6); kuralın kodu da kilitten önce sentetik veriyle sınanmış olmalıdır.

## Başlıca riskler

Ayrıntı ve izleme [`riskler.md`](riskler.md) dosyasındadır. Bu haritayı en çok etkileyenler: çok süreçli koordinasyon (M2), merkezi moddaki kuyruk ve geri basınç (M3), eğitimin 14 haftalık takvime sığması (A7), kabul testlerindeki kesme testi (M6), gerçek zaman faktörü ve zaman aşımı H'nin pilotlarda belirlenmesi (M7).
