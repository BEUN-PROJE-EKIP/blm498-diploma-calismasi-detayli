# Kontrol Paneli (sunum aracı)

İHA sürüsü simülasyonunu sunumlarda göstermek için web tabanlı kontrol paneli. **Projeden bağımsızdır:** deney akışının parçası değildir, GŞÖA gereksinimi karşılamaz ve ölçüm yapılan koşularda kullanılmaz. Harita kamerası GPU'ya ek render yükü getirir.

```
┌──────────────────────── KONTROL PANELİ ────────────────────────┐
│   İHA1 CAM          │   İHA2 CAM           │   İHA3 CAM         │
├──────────────────────────────────┬─────────────────────────────┤
│ Sistem: başlat/durdur  │ 1 Mod   │                        [⤢]  │
│ + kontrol listesi      │ 2 Görev │      Genel harita           │
├────────────────────────┼─────────┤  (Gazebo kuş bakışı, canlı) │
│ 3 Toplu kalkış         │ 6 Manuel│                             │
│ 4 Toplu iniş           │ (kol)   │                             │
└────────────────────────┴─────────┴─────────────────────────────┘
```

## Kurulum ve çalıştırma

Node.js/npm gerekir (yalnız arayüzü derlemek için; kendi terminalinizde kurun). Ardından:

```bash
kontrol_paneli/calistir.sh --derle   # ilk sefer: React arayüzünü derler, sonra paneli açar
kontrol_paneli/calistir.sh           # sonraki seferler
```

Tarayıcıda: <http://127.0.0.1:8090>. Arayüz üzerinde çalışırken: `cd kontrol_paneli/frontend && npm run dev` (<http://127.0.0.1:5173>, API isteklerini 8090'a yönlendirir).

## Tuşlar ne yapar

| Tuş | Ne yapar |
|---|---|
| **Sistemi başlat** | `araclar/kosu.sh baslat` → Gazebo (başsız) + 3 × PX4 SITL. Yaşayan bir koşu varsa ona bağlanır. Kontrol listesi: sürü ağı (tc), Gazebo saati, PX4 bağlantıları, konum/ev noktası, 3 kamera, harita kamerası. |
| **1 · Mod seçimi** | Uçta / Merkezi (koşu düzeyinde mimari modu). |
| **2 · Görevi başlat** | `kosu.sh durdur` → `kosu.sh baslat --yer-istasyonu var --mimari <mod>`: projenin kendi görev akışı (yer istasyonu + 3 araç süreci) temiz bir koşuyla başlar. Araçlar yerde olmalıdır. |
| **3 · Toplu kalkış** | Bağlı tüm İHA'lar `CAM_ALT_M` (30 m) irtifaya kalkar; yalnız kalkış. Görev sürerken kapalıdır. |
| **4 · Toplu iniş** | Havadaki tüm İHA'lar bulundukları yere iner; yalnız iniş. |
| **6 · Manuel sürüş** | Fiziksel oyun kolu (Gamepad API, Mod 2): sol çubuk irtifa/dönüş, sağ çubuk ileri/yan; LB/RB İHA seçer, START sürüşü başlatır/bitirir. Offboard hız kontrolüdür; 0,5 sn komut gelmezse araç durur. Görev sürerken kapalıdır. |
| **⤢ (harita)** | Haritayı tam ekran açar; Esc ile kapanır. |

## Nasıl çalışır

- **Arka uç** (`backend/`, yalnız standart kitaplık + projede kurulu paketler): HTTP sunucusu, `/api/olaylar` (Server-Sent Events, 2 Hz durum), MJPEG kamera akışları, POST komutları.
- **Kameralar:** gz-transport ile aracın kamera konusuna doğrudan abone olunur (`ros_gz_bridge` kullanılmaz). Görüntüler JPEG'e çevrilir.
- **Harita:** koşu başlayınca dünyaya yalnız çalışma anında tepeden bakan bir kamera eklenir (`/world/<dünya>/create`). Sahne dosyalarına dokunulmaz. İHA işaretleri `pose/info` konusundan çizilir.
- **Uçuş:** panelin kendi `mavsdk_server`'ları (gRPC 20061-20063) PX4'ün GCS bağlantı portuna (18570+i) bağlanır. Projenin `px4_adapter` hattı (14540-14542, gRPC 20051-20053) değişmez. `kosu.sh baslat` başka `mavsdk_server` görünce koşuyu reddettiği için panel bunları yalnız koşu açıkken çalıştırır ve `baslat`'tan önce kapatır.
- **Yapılandırma:** paylaşılan değerler (dünya, model, kimlikler, irtifa, konu adları) `config/deney.env`'den okunur. Panele özgü değerler `panel_ayar.json` dosyasındadır.
