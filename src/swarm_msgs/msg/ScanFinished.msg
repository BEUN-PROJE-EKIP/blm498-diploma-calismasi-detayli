# Tarama bitişi: her araç rotasının son noktasına ulaşınca paylaşır ve WAIT durumuna geçer (FR-4).
# Kare numaralandırma kuralı: ızgara yolunda n = 2 * t_sim, bildirimde n_ilk ve n_son; yedek yolda (damgalar doğrulanmazsa) alıcı numarası k,
# bildirimde t_s, t_b ve k_son [belge]. Her yolda yalnız ilgili alanlar anlamlıdır; kullanılmayan alanlar 0'dır.

uint8 NUMBERING_UNKNOWN=0   # varsayılan: ayarlanmamış (geçerli değildir)
uint8 NUMBERING_GRID=1      # ızgara yolu: n = 2 * t_sim [belge]
uint8 NUMBERING_FALLBACK=2  # yedek yol: alıcının kesintisiz numarası k [belge]

string mission_id           # ortak görev kimliği [belge]
uint8 vehicle_id            # bildirimi yapan araç (1, 2, 3)
uint8 numbering_mode        # NUMBERING_GRID | NUMBERING_FALLBACK

# Izgara yolu
int64 n_first               # n_ilk = ceil(2 * t_s): ilk görev karesi numarası [belge]
int64 n_last                # n_son = floor(2 * t_b): son görev karesi numarası [belge]

# Yedek yol
builtin_interfaces/Time t_s # tarama başlatma mesajının alındığı simülasyon saati [belge]
builtin_interfaces/Time t_b # tarama bitişinin simülasyon zamanı [belge]
int64 k_last                # k_son: son alıcı numarası [belge]
