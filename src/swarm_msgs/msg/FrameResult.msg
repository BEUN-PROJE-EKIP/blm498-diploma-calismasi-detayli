# Kare sonucu (FR-12): her işlenmiş kare için tespit bulunsun bulunmasın bir kare sonuç iletisi üretilir. Alıcıya ulaşmayan görev karesi
# için aynı yapıda "kare alınamadı" kaydı üretilir.
# DÖRT durum birbirine KODLANMAZ: tespit var, açık "tespit yok", işlem hatası, "kare alınamadı". "Tespit yok" yalnız çıkarım başarıyla
# bitti ve tespit bulunmadı demektir; "işlem hatası" ve "kare alınamadı" boş tespit listesiyle taşınsa bile "tespit yok" sayılmaz [belge].

# İşlem tamamlanma durumu [belge: ortak başlık işlem tamamlanma durumunu içerir]
uint8 STATUS_UNKNOWN=0              # varsayılan: ayarlanmamış (hiçbir sonuç değildir; "tespit yok" ile karıştırılmaz)
uint8 STATUS_DETECTIONS=1           # çıkarım bitti, en az bir tespit var (detections boş değildir)
uint8 STATUS_NO_DETECTION=2         # çıkarım bitti, açıkça "tespit yok" (detections boştur) [belge]
uint8 STATUS_PROCESSING_ERROR=3     # kare alındı ama işlenemedi; "tespit yok" DEĞİLDİR [belge]
uint8 STATUS_FRAME_NOT_RECEIVED=4   # "kare alınamadı": alıcıya ulaşmayan görev karesi; detections boştur [belge]

uint8 NUMBERING_UNKNOWN=0
uint8 NUMBERING_GRID=1              # ızgara yolu: frame_number = n = 2 * t_sim; sim_stamp = n / 2 s (ızgara damgası) [belge]
uint8 NUMBERING_FALLBACK=2          # yedek yol: kare numarası türetilmez; sim_stamp damga kaydındaki simülasyon zaman damgasıdır [belge]

uint8 vehicle_id                    # araç kimliği (1, 2, 3) [belge]
uint8 numbering_mode                # NUMBERING_GRID | NUMBERING_FALLBACK
int64 frame_number                  # kare numarası (yalnız ızgara yolunda anlamlı; yedek yolda 0) [belge]
builtin_interfaces/Time sim_stamp   # karenin simülasyon zaman damgası [belge]
uint8 status                        # STATUS_*
Detection[] detections              # tespit listesi; STATUS_DETECTIONS dışında boştur
