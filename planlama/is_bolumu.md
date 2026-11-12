# İş bölümü

Üç kişilik ekipte hangi iş paketini kimin üstlendiği burada tutulur. **Kesin bir bölüşüm yoktur; aşağıdaki çalışma paketleri bir taslaktır ve tek kişilik aşamaların (M1) bitiminde kesinleştirilir.** Paketler ve ağırlıkları [`gelistirme_agaci.md`](gelistirme_agaci.md) dosyasındadır; her paketin maddeleri orada listelidir.

| İş paketi | Tarih | Ağırlık | Sorumlu | Yardımcı | Not |
|---|---|---|---|---|---|
| K · Kurulum ve doğrulama testleri | 1 Şubat 2027 - 14 Şubat 2027 | %10 | — | — | |
| A · Veri ve model | 15 Şubat 2027 - 21 Mart 2027 | %20 | — | — | |
| B · Sürü yazılımı | 15 Şubat 2027 - 21 Mart 2027 | %25 | — | — | |
| C · Kabul testleri ve pilot koşular | 22 Mart 2027 - 18 Nisan 2027 | %20 | — | — | |
| D · Ana deneyler | 19 Nisan 2027 - 9 Mayıs 2027 | %15 | — | — | |
| E · Analiz ve raporlama | 10 Mayıs 2027 - 28 Mayıs 2027 | %10 | — | — | |

## Çalışma paketleri (taslak)

Aşağıdaki iki paket, sürü hattının geri kalanından bağımsız ve bitti ölçütleri nesnel olan işlerdir. Gerisi (sürü yazılımı, kabul testleri, pilotlar, ana deneyler) ana ekipte kalır. Her paketin yapılacaklar listesi ve kapı komutu, paket kesinleştiğinde ayrı bir dosyaya yazılır. Aşama adları için bkz. [`yol_haritasi.md`](yol_haritasi.md).

| Paket | Maddeler (ağaç) | Aşama | Yaklaşık pay | Gerekli donanım | Sorumlu |
|---|---|---|---|---|---|
| **Veri ve Model** | A1, A2, A3, A4, A5, A7, A9, A10, A12, A13 | M4, M5 | %20 | Gazebo ve GPU (RTX 5070, 12 GB) | — |
| **Değerlendirme** | B18, E1, E2, E3, E4, E5, E6, E7 (E7 taslaktır; rapor metninin son hâlini rapor yazarı hazırlar) | M6 ve M8 | %11 | GPU gerekmez | — |
| Ana ekip | Kalan her şey (B2–B15, C1–C14, D1–D5) | M1, M2, M3, M6, M7, M8 | kalan | Ana makine | Ömer Faruk |

Notlar:
- **Veri ve Model tek kişide kalır:** etiket yöntemi, kamera ve alan geometrisi veri setini, veri seti de modeli doğrudan etkiler; zincirin ortasında devir yapılmaz.
- **B18 Değerlendirme paketindedir:** E1 eşleştirmeyi B18'in kodu üzerinden yapar.
- **B15 (hedef birleştirme) ana ekipte kalır:** ortak COMPLETE koşulunun parçasıdır (FR-5).
- Kilitli değerler (görüş açısı, batch, çıkarım ayarları, kuyruk, H, karar kuralı) ve `setup/`, `config/`, `src/swarm_*` ana ekibin onayıyla değişir (bkz. `.github/CODEOWNERS`).
- Pay oranları ağaçtaki madde ağırlıklarından hesaplanmış yaklaşık değerlerdir; efor ölçüsü değildir.

## Nasıl doldurulur

- **Sorumlu:** paketin ilerlemesini takip eden ve incelemede ilk söz sahibi olan kişi. Maddelerin hepsini tek kişi yapmak zorunda değil.
- **Yardımcı:** paketin işini birlikte yürüten kişi (varsa).
- Madde seviyesinde aynı anda iki kişi aynı işe başlamasın: bir maddeye başlamadan önce ekibe haber ver. Sorumluluk bir maddeye özel olarak değişirse "Not" sütununa yaz.
- 15 Şubat 2027 - 21 Mart 2027 arasında iki paket (A ve B) paralel yürür; bu yüzden en az iki kişinin başlangıçta ayrı paketlere dağılması gerekir.
