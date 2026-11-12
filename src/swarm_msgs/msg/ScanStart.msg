# Tarama başlatma: yer istasyonundaki görev koordinatörü (/gcs/mission_coordinator) üç aracın hazır bildirimini (VehicleState.STATE_BARIYER_BEKLE) aldıktan sonra başlangıç
# bariyerini açar ve bu mesajı yayımlar; yayımlama anı t0'dır (FR-3). Araç bu mesajı almadan taramaya başlamaz.
# Araç mesajı aldığı andaki simülasyon saatini t_s olarak kendisi kaydeder (n_ilk = ceil(2 * t_s)); bu mesajda t_s taşınmaz [belge].

string mission_id           # ortak görev kimliği [belge]
