# Protokol kararları kaydı

Deney protokolüne giren kararlar, gerekçeleriyle burada tutulur. Kilitli değerler sonuçlara bakılarak değiştirilmez. Bu bir simülasyon deneyidir; gerçek donanım ya da operasyonel yeterlilik iddiası yoktur.

| Tarih | Karar | Gerekçe / ölçüm | Durum |
|---|---|---|---|
| 2026-11-12 | **Çıkarım yolu: GPU, YOLO26L** (B planı CPU/YOLO26s kullanılmaz) | K11: 3 araç + 3 kamera + 3 GPU işçisi + Gazebo birlikte, her işçi 2 kare/s'yi sürekli işledi (642/642 kare, taşma yok, RTF 1,0000); doygunlukta işçi başına ≈43 kare/s (≈21 kat pay), GPU belleği toplam ≈3 GiB. Belge kuralı: GPU ile 2 kare/s işlenebiliyorsa GPU. CPU yolu da yeterli çıktı (üç işçi 2 kare/s, doygunlukta ≈6,7 kare/s), yani B planı hazır ama seçilmedi | karar verildi |
| 2026-11-12 | **Kamera damgaları ve kare sırası doğrulandı; yedek yola geçilmez** | K9: ilk kare hariç tüm karelerde damga 0,5 s'nin tam katı, sıra bozulmuyor (tek kamera, PX4 açıkken, üç kamera). Her oturumun ilk karesi ızgara dışı: kare numarası yalnız damga ızgaraya tam oturuyorsa türetilir, oturmayan kare "ızgara dışı" kaydedilir ve görev karesi sayılmaz | karar verildi |
| 2026-11-12 | **Çoklu yayın keşif duyuruları sınırlayıcıya alındı** | Fast DDS 2.14.7 duyuruları 239.255.0.1'e göndermeyi profille kapatamıyor (alıcı yok); `tc` ikinci süzgeci ile D'ye dahil. Belgedeki "çoklu yayın kullanılmaz" ifadesinden bilinen sapma | karar verildi |
| 2026-11-12 | **Veri planı: B (yalnız Gazebo) birinci öncelik ve sabit; A isteğe bağlı** | A planı yalnız zaman kalırsa, ana deneylerden sonra ek analiz olarak denenir; model kilidini değiştirmez; sonucu önceden varsayılmaz | karar verildi |
| 2026-11-12 | **Kamera yatay görüş açısı: 65°–70° aralığı; insan hedefi yatan insan** | Ölçüt (kabul, ölçülmüş değer değil): yatan insanın dar kenarı ≥ 8 piksel. Kesin değer aday açılarda piksel ölçümüyle seçilir | ölçüm bekleniyor |
