"""Görev atama mantığı (saf, rclpy'siz): `config/bolge_rota.json` ↔ `swarm_msgs/Mission` (FR-1, FR-2, FR-7).

Tasarım [varsayım; belge "rota kalkıştan önce yüklenir" + "yer istasyonundan gelen görev komutları" der, M0'da tanımlı `Mission` iletisini kullanır]: yer istasyonu `bolge_rota.json`'ı okur ve her araca kendi
Mission'ını (ortak `mission_id`, bölge, rota noktaları, irtifa, hız) yayımlar; araç rotayı PX4'e yüklemeden önce kendi Mission'ını bekler, yerel `bolge_rota.json` ile BİREBİR karşılaştırır (noktalar, bölge,
irtifa, hız) ve yalnız eşitse yükler (yüklemeyi aldığı Mission'dan yapar). Uyuşmazlık = açık hata, yükleme yok. Tek doğru kaynak `bolge_rota.json` (SHA-256 koşu üst verisinde: `rota_sha256`).
Bu modül Mission iletisini sözlük olarak ele alır; ileti nesnesine dönüşüm (`mesaj_doldur`, `mesajdan_sozluk`) yalnız alan adlarını kullanır (rclpy içe aktarılmaz).
"""
import hashlib
import json

# float32 alanlar (altitude_m, speed_ms) için karşılaştırma payı; koordinatlar float64'tür (tam eşitlik, yalnız kayan nokta gürültüsü payı)
_NOKTA_PAYI = 1e-9
_F32_PAYI = 1e-4


def bolge_rota_oku(yol):
    with open(yol, encoding="utf-8") as f:
        return json.load(f)


def dosya_sha256(yol):
    with open(yol, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def mission_sozlugu(bolge_rota, arac_kimligi, mission_id):
    """Bölge/rota sözlüğünden bir aracın Mission sözlüğü. Araç için rota ya da bölge yoksa KeyError."""
    rota = next((r for r in bolge_rota["rotalar"] if r["arac_kimligi"] == arac_kimligi), None)
    bolge = next((b for b in bolge_rota["bolgeler"] if b["arac_kimligi"] == arac_kimligi), None)
    if rota is None or bolge is None:
        raise KeyError(f"araç {arac_kimligi} için rota ya da bölge yok")
    irtifa, hiz = float(bolge_rota["irtifa_m"]), float(bolge_rota["hiz_ms"])
    return {"mission_id": mission_id, "vehicle_id": int(arac_kimligi), "region_id": bolge["bolge_kimligi"],
            "region_x_min": float(bolge["x_min"]), "region_x_max": float(bolge["x_max"]), "region_y_min": float(bolge["y_min"]), "region_y_max": float(bolge["y_max"]),
            "waypoints": [(float(x), float(y), irtifa) for x, y in rota["noktalar"]], "altitude_m": irtifa, "speed_ms": hiz}


def mission_karsilastir(mission, bolge_rota, arac_kimligi):
    """Alınan Mission sözlüğünü yerel bölge/rota dosyasıyla karşılaştırır. Dönen: uyuşmazlık metinleri listesi (boş = birebir eşit)."""
    try:
        beklenen = mission_sozlugu(bolge_rota, arac_kimligi, mission["mission_id"])
    except KeyError as e:
        return [str(e)]
    fark = []
    if int(mission["vehicle_id"]) != int(arac_kimligi):
        fark.append(f"vehicle_id {mission['vehicle_id']} ≠ {arac_kimligi}")
    if mission["region_id"] != beklenen["region_id"]:
        fark.append(f"region_id {mission['region_id']!r} ≠ {beklenen['region_id']!r}")
    for k in ("region_x_min", "region_x_max", "region_y_min", "region_y_max"):
        if abs(float(mission[k]) - beklenen[k]) > _NOKTA_PAYI:
            fark.append(f"{k} {mission[k]} ≠ {beklenen[k]}")
    for k in ("altitude_m", "speed_ms"):
        if abs(float(mission[k]) - beklenen[k]) > _F32_PAYI:
            fark.append(f"{k} {mission[k]} ≠ {beklenen[k]}")
    a, b = list(mission["waypoints"]), beklenen["waypoints"]
    if len(a) != len(b):
        fark.append(f"rota nokta sayısı {len(a)} ≠ {len(b)}")
    else:
        for i, (p, q) in enumerate(zip(a, b)):
            d = max(abs(float(p[0]) - q[0]), abs(float(p[1]) - q[1]), abs(float(p[2]) - q[2]) if len(p) > 2 else 0.0)
            if d > _NOKTA_PAYI:
                fark.append(f"nokta {i}: ({p[0]}, {p[1]}) ≠ ({q[0]}, {q[1]})")
                break
    return fark


def mission_noktalari(mission):
    """Mission'dan PX4'e yüklenecek yatay rota noktaları [(x, y), ...]."""
    return [(float(p[0]), float(p[1])) for p in mission["waypoints"]]


def mesaj_doldur(mesaj_sinifi, nokta_sinifi, d):
    """Mission sözlüğünden `swarm_msgs/Mission` iletisi (sınıflar dışarıdan verilir; rclpy gerekmez)."""
    m = mesaj_sinifi()
    m.mission_id, m.vehicle_id, m.region_id = d["mission_id"], int(d["vehicle_id"]), d["region_id"]
    m.region_x_min, m.region_x_max, m.region_y_min, m.region_y_max = d["region_x_min"], d["region_x_max"], d["region_y_min"], d["region_y_max"]
    for x, y, z in d["waypoints"]:
        p = nokta_sinifi()
        p.x, p.y, p.z = x, y, z
        m.waypoints.append(p)
    m.altitude_m, m.speed_ms = d["altitude_m"], d["speed_ms"]
    return m


def mesajdan_sozluk(m):
    return {"mission_id": m.mission_id, "vehicle_id": int(m.vehicle_id), "region_id": m.region_id,
            "region_x_min": m.region_x_min, "region_x_max": m.region_x_max, "region_y_min": m.region_y_min, "region_y_max": m.region_y_max,
            "waypoints": [(p.x, p.y, p.z) for p in m.waypoints], "altitude_m": m.altitude_m, "speed_ms": m.speed_ms}


def enjeksiyon_sapma(d, sapma_m=1.0):
    """YALNIZ test (GOREV_ENJEKSIYON): Mission'ın ilk noktasını x ekseninde `sapma_m` kaydırır (yerel dosyayla uyuşmazlık üretmek için)."""
    d = dict(d)
    w = list(d["waypoints"])
    x, y, z = w[0]
    w[0] = (x + sapma_m, y, z)
    d["waypoints"] = w
    return d
