# Görev: bir araca bölge ve sabit rota atar (FR-1, FR-7). Bölge/rota biçimi planlama/sozlesmeler.md içindeki bölge/rota dosyasıyla aynı
# alanları taşır. Koordinatlar yerel ENU (orijin alanın merkezi; x doğu, y kuzey), metre.

string mission_id           # ortak görev kimliği; tarama başlatma mesajındaki kimlikle eşleşir [belge: ortak görev kimlikli tarama başlatma]
uint8 vehicle_id            # atanan araç (1, 2, 3) [belge]
string region_id            # atanan bölgenin kimliği (örn. B1) [belge: her araca bir bölge]

# Bölge dikdörtgeni (yerel ENU, m) [belge: çakışmayan bölgeler; dikdörtgen biçimi varsayımdır]
float64 region_x_min
float64 region_x_max
float64 region_y_min
float64 region_y_max

# Rota [belge: sabit rota; irtifa yerden 30 m sabit]
geometry_msgs/Point[] waypoints   # yatay rota noktaları (x doğu, y kuzey); z = rota irtifası (m)
float32 altitude_m               # görev irtifası (30 m sabit) [belge]
float32 speed_ms                 # rota hızı (m/s) [varsayım: belgede sayısal değer yok; geçici, pilotta belirlenir]
