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

Önerilen yürütme sırası: **M0 → M1 → M4 → M5 → M2 → M3 → M6 → M7 → M8.** Numaralar içerik gruplarıdır. Model eğitimi (M5) GPU'yu tek başına ister ve gözetimsiz çalışabilir; eğitim sürerken Gazebo gerektirmeyen yazılım işleri yapılabilir.

| Aşama | Maddeler | İçerik | Kapı (bitti sayılması için) |
|---|---|---|---|
| **M0 Sözleşmeler** | B1, B21 ve yeni: sahne şeması, alan tanımı, kamera kalibrasyon dosyası | Mesaj paketi, tek yapılandırma dosyası, sahne dosyası biçimi, alan/bölge tanımı | Dosyalar kilitli; şema doğrulama testi geçer; mesaj paketi derlenir; tüm betikler yapılandırmayı tek dosyadan okur |
| **M1 Tek araç iskeleti** | B2 (tek bölge), B3, B4 (tek araç), B6, B7, B8, B9 (hazır ağırlıkla), B10 | Bir araç bir bölgeyi tarar, kare alınır, damgalanır, çıkarılır | Her görev karesi için sonuç ya da "kare alınamadı"; durum geçişleri testli; kayıp ve geç kare senaryoları testli |
| **M4 Veri hattı** | A1, A2, A3, A4, A5, A12 | Sahne üretici, bölümler, etiket, görüntüler | Tohumdan aynı sahne; bölümler ayrık; sayılar tamam; etiket kontrolü yapıldı |
| **M5 Model** | A7, A9, A10, A11 (kayıt), A13 | Eğitim süresi pilotu, B planı eğitimi, epoch seçimi, dosya özetleri | Seçilen epoch kayıtlı; model ve veri özetleri kilitli |
| **M2 Üç araç** | B2 (üç bölge), B5, B11 | Yer istasyonu, ortak başlangıç, ilerleme, COMPLETE, uçta mod | Üç araç ortak başlar, ortak biter; t0 ve t1 doğru anlarda |
| **M3 Merkezi mod ve izleme** | B12, B13, B14, B15 | Merkezi mod, kuyruklar, konum hesabı, hedef birleştirme | İki modda tam koşu kayıpsız; bilinen pozda konum hatası < 5 m; birleştirme testleri |
| **M6 Değerlendirme ve kabul** | B18, B19, C1–C9 | Eşleştirme yazılımı, bütünleşik koşu, beş kabul testi, ölçümler | Beş kabul testi iki modda geçer |
| **M7 Pilotlar ve kilit** | C10–C14 | Kuyruk sınırı, 6 pilot, H, protokol kilidi, koşu otomasyonu | Bir çift otomatik koşar; H ve protokol kilidi yazılı |
| **M8 Ana deneyler ve analiz** | D1–D5, E1–E7 | 30 sahne × 2 mod, analiz, rapor | Her koşu tamamlandı ya da "tamamlanamadı" kayıtlı; tablolar ve rapor |

## Neden bu sıra?

- **M0 önce:** sahne dosyasını hem sahne üretici (A1) üretir hem değerlendirme (B18) ve tam koşu (B19) okur; alanı hem A1 kurar hem rota (B2) kullanır; kamerayı hem veri üretimi hem sürü yazılımı kullanır. Bunlar sonradan değişirse iki hat birden bozulur.
- **M1 hemen sonra:** en büyük belirsizlikler (PX4 görev yükleme, kamera akışı, kare kayıp mantığı) burada çıkar; en ucuz zamanda görünür olurlar.
- **M4, M5 sürü hattının ortasında:** sahne üretici (A1) M2, M3 testleri için gereken dünyaları da üretir. Eğitim uzun GPU süresi gerektirir; Gazebo gerektirmeyen yazılım işleri sürerken çalıştırılabilir.
- **M6'dan önce M5:** pilotlar (M7) nihai modelle yapılır, çünkü tarama süresi ve ağ yükü model çıkarım süresini içerir.

## Başlıca riskler

Ayrıntı ve izleme [`riskler.md`](riskler.md) dosyasındadır. Bu haritayı en çok etkileyenler: çok süreçli koordinasyon (M2), merkezi moddaki kuyruk ve geri basınç (M3), eğitimin 14 haftalık takvime sığması (A7), kabul testlerindeki kesme testi (M6), gerçek zaman faktörü ve zaman aşımı H'nin pilotlarda belirlenmesi (M7).
