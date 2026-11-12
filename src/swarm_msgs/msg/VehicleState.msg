# Araç durumu: her araç görev durumunu 2 Hz ile ortak durum konusuna yayımlar; diğer iki araç ve yer istasyonu alıp kaydeder (FR-2).
# Koordinat/zaman: simülasyon zamanı builtin_interfaces/Time olarak taşınır (saniye + nanosaniye).

# Durum makinesi durumları [belge: GŞÖA 7.4, Şekil 4]; adlar belgedeki gibi (ASCII).
# "Hazır bildirimi": araç başlangıç konumunda hazır olduğunda BARIYER_BEKLE durumuna geçer ve bunu bu mesajla yayımlar (ayrı bir hazır
# mesajı yoktur); görev koordinatörü üç aracın BARIYER_BEKLE durumunu alınca bariyeri açar ve tarama başlatma mesajını yayımlar
# [belge: GŞÖA 7.4, FR-3].
uint8 STATE_UNKNOWN=0        # varsayılan: ayarlanmamış (geçerli bir durum değildir)
uint8 STATE_HAZIR=1          # kalkıştan önce rota PX4'e görev olarak yüklü; başlangıç konumuna hazırlanıyor [belge: GŞÖA 7.4]
uint8 STATE_BARIYER_BEKLE=2  # başlangıç konumunda hazır olduğunu bildirdi, başlangıç bariyerini (tarama başlatma mesajını) bekliyor [belge: GŞÖA 7.4]
uint8 STATE_TARAMA=3         # tarama başlatma mesajı alındı; px4_adapter görevi başlattı, rota izleniyor [belge: GŞÖA 7.4]
uint8 STATE_WAIT=4           # rota bitti, tarama bitişi bildirildi; yalnız ortak COMPLETE ile çıkılır [belge: GŞÖA 7.4]
uint8 STATE_TAMAMLANDI=5     # ortak COMPLETE alındı [belge: GŞÖA 7.4]

uint8 vehicle_id           # araç kimliği (1, 2, 3; ad alanı /uav_N ve PX4 MAV_SYS_ID ile aynı) [belge]
uint8 state                # yukarıdaki STATE_* değerlerinden biri
builtin_interfaces/Time sim_stamp   # durumun yayımlandığı simülasyon zamanı [varsayım: belge kaynak zamanı kullanır]
uint32 mission_item_current # görev (mission) ilerlemesi: o an hedeflenen görev öğesi [belge: görev ilerlemesi; iki sayı varsayımı]
uint32 mission_item_total   # görev öğesi sayısı; son noktaya ulaşınca tarama bitişi bildirilir [belge]
int64 last_frame_number     # son işlenen/numaralanan görev karesi numarası; yok ise -1 [tasarım: son kare numarası; yedek yolda alıcı numarası k]
