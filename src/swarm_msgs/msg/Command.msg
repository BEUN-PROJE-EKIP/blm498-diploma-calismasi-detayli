# Komut: yer istasyonu → araç komut konusu → px4_adapter yolundan iletilir; komutlar araç kimliği, sıra numarası ve onay durumu içerir [belge].
# Not: belge komut türünü/parametrelerini tanımlamaz; bu alanlar bu mesajda YOKTUR (raporda soru olarak yazılıdır).

uint8 ACK_UNKNOWN=0         # varsayılan: ayarlanmamış (geçerli değildir)
uint8 ACK_PENDING=1         # gönderildi, onay bekleniyor [varsayım: belge onay durumu değerlerini saymaz]
uint8 ACK_ACCEPTED=2        # kabul edildi [varsayım]
uint8 ACK_REJECTED=3        # reddedildi [varsayım]

uint8 vehicle_id            # komutun gideceği/ilgili olduğu araç (1, 2, 3) [belge]
uint32 sequence             # komut sıra numarası [belge]
uint8 ack_state             # onay durumu: ACK_* [belge: onay durumu]
