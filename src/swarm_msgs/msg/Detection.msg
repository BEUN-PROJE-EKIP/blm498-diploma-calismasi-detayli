# Tek tespit (kare sonucundaki tespit listesinin öğesi) [belge: sınıf, güven puanı, görüntü kutusu, tahmini konum, "aday" durumu].

uint8 CLASS_HUMAN=0         # insan [belge: iki sınıf; sıra MODEL_SINIFLAR "insan enkaz" ile aynı: varsayım]
uint8 CLASS_DEBRIS=1        # enkaz yığını

uint8 class_id              # CLASS_HUMAN | CLASS_DEBRIS
float32 confidence          # güven puanı [0, 1] (çıkarım güven eşiği 0,25 üstü) [belge]

# Görüntü kutusu: piksel koordinatı, orijin sol üst köşe, x sağa y aşağı [belge: görüntü kutusu; xyxy biçimi varsayımdır]
float32 box_x_min
float32 box_y_min
float32 box_x_max
float32 box_y_max

# Tahmini konum: kutu merkezinden çıkan ışının düz zeminle kesişimi, yerel ENU (m) [belge]. Geçerli kesişim veya geçerli poz yoksa konumsuzdur
# (has_position = false); konumsuz tespit konumsal birleştirmeye alınmaz [belge].
bool has_position
float64 east
float64 north

# "aday" durumu [belge: kare sonucu bölümü: tespit listesi sınıf, güven puanı, görüntü kutusu, tahmini konum ve "aday" durumunu içerir].
# "Aday", sağlık/canlılık onayı DEĞİLDİR; hedef birleştirmedeki birleştirme adayı anlamındadır (anlamın ayrıntısı birleştirme modülünde netleşir).
bool candidate
