"""Bölge ve rota üretimi ile yapılandırma okuma (yalnız standart kitaplık; rclpy ve MAVSDK içe aktarılmaz).

Girdi `config/deney.env`'dir (ALAN_*, ROTA_*, CAM_*, UAV_SYS_IDS). Çıktı `planlama/sozlesmeler.md` §3'teki bölge/rota sözlüğüdür:
alan, bölge sayısı kadar eşit genişlikte şerit bölgeye (x ekseninde yan yana) ayrılır; her bölgede y boyunca giden yılan (serpantin)
şerit izleri üretilir. Sabit sayı yoktur; çıktı belirlenimcidir (aynı girdi → aynı bayt).
"""
import json
import math
import os
import re

def _kok_bul():
    """Depo kökü: PROJE_ROOT ortam değişkeni (setup/env.sh verir; kurulu paket için gerekli), yoksa kaynak ağacındaki konumdan."""
    ortam = os.environ.get("PROJE_ROOT")
    if ortam and os.path.isfile(os.path.join(ortam, "config", "deney.env")):
        return ortam
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


KOK = _kok_bul()

_SATIR = re.compile(r'^([A-Z][A-Z0-9_]*)=(?:"([^"]*)"|(\S*))')

GEREKLI = ("ALAN_MERKEZ_X_M ALAN_MERKEZ_Y_M ALAN_GENISLIK_M ALAN_YUKSEKLIK_M ALAN_BOLGE_SAYISI ROTA_IRTIFA_M ROTA_ORTUSME_MIN_M ROTA_HIZ_MS "
           "CAM_WIDTH CAM_HEIGHT CAM_HFOV_DEG CAM_HFOV_RAD UAV_SYS_IDS").split()

# Yuvarlama payı: iki ondalık hane (cm). Kapsama yönünde (dışa doğru) yuvarlanır; ortusme_min_m için ayrıca küçük bir güvenlik payı bırakılır.
_ONDALIK = 2
_ORTUSME_PAYI_M = 0.01


def varsayilan_deney_env():
    """DENEY_ENV ortam değişkeni varsa onu, yoksa depodaki config/deney.env yolunu verir."""
    return os.environ.get("DENEY_ENV") or os.path.join(KOK, "config", "deney.env")


def aktif_kosu_klasoru():
    """Yaşayan koşunun klasörü (araclar/kosu.sh `aktif` işaretinden); yoksa None."""
    aktif = os.path.join(KOK, ".generated", "kosular", "aktif")
    if not os.path.isfile(aktif):
        return None
    with open(aktif, encoding="utf-8") as f:
        kimlik = f.read().strip()
    klasor = os.path.join(KOK, ".generated", "kosular", kimlik)
    return klasor if kimlik and os.path.isdir(klasor) else None


def deney_env_oku(yol=None):
    """`KEY="değer"` satırlarını sözlüğe okur (bash'te `source` edilen dosyayla aynı basit biçim)."""
    yol = yol or varsayilan_deney_env()
    veri = {}
    with open(yol, encoding="utf-8") as f:
        for satir in f:
            m = _SATIR.match(satir.strip())
            if m:
                veri[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return veri


def sayi(metin):
    """Yapılandırma sayısı: tam sayıysa int, değilse float (çıktı JSON'unda `300` ile `300.0` ayrımı korunur)."""
    f = float(metin)
    return int(f) if f == int(f) else f


def _asagi(v):
    return math.floor(round(v * 10 ** _ONDALIK, 6)) / 10 ** _ONDALIK + 0.0


def _yukari(v):
    return math.ceil(round(v * 10 ** _ONDALIK, 6)) / 10 ** _ONDALIK + 0.0


def _yakin(v):
    return round(v, _ONDALIK) + 0.0


def uret(ham):
    """Yapılandırma sözlüğünden (deney_env_oku çıktısı) bölge/rota sözlüğünü üretir."""
    eksik = [k for k in GEREKLI if k not in ham]
    if eksik:
        raise ValueError("yapılandırmada eksik anahtar: " + ", ".join(eksik))
    mx, my = sayi(ham["ALAN_MERKEZ_X_M"]), sayi(ham["ALAN_MERKEZ_Y_M"])
    gen, yuk = sayi(ham["ALAN_GENISLIK_M"]), sayi(ham["ALAN_YUKSEKLIK_M"])
    n_bolge = int(ham["ALAN_BOLGE_SAYISI"])
    irtifa, ortusme, hiz = sayi(ham["ROTA_IRTIFA_M"]), sayi(ham["ROTA_ORTUSME_MIN_M"]), sayi(ham["ROTA_HIZ_MS"])
    w_px, h_px = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
    hfov_deg, hfov_rad = float(ham["CAM_HFOV_DEG"]), float(ham["CAM_HFOV_RAD"])
    arac_kimlikleri = [int(x) for x in ham["UAV_SYS_IDS"].split()]
    if n_bolge < 1 or n_bolge > len(arac_kimlikleri):
        raise ValueError(f"ALAN_BOLGE_SAYISI ({n_bolge}) 1..{len(arac_kimlikleri)} aralığında olmalı (UAV_SYS_IDS uzunluğu)")
    if n_bolge != len(arac_kimlikleri):
        raise ValueError(f"her araca bir bölge: ALAN_BOLGE_SAYISI ({n_bolge}) = UAV_SYS_IDS uzunluğu ({len(arac_kimlikleri)}) olmalı")

    w = 2 * irtifa * math.tan(hfov_rad / 2)          # iz genişliği (m)
    yarim_boy = (w / 2) * h_px / w_px                # iz boyunca yarı kamera ayak izi (m); görüntünün yatay ekseni uçuş yönüne diktir
    x0, y0 = mx - gen / 2, my - yuk / 2
    bolge_gen = gen / n_bolge

    bolgeler, rotalar = [], []
    for k in range(n_bolge):
        bx0, bx1 = x0 + k * bolge_gen, x0 + (k + 1) * bolge_gen
        by0, by1 = y0, y0 + yuk
        bolgeler.append({"bolge_kimligi": f"B{k + 1}", "arac_kimligi": arac_kimlikleri[k],
                         "x_min": sayi(repr(bx0)), "x_max": sayi(repr(bx1)), "y_min": sayi(repr(by0)), "y_max": sayi(repr(by1))})
        # şerit izi sayısı: ilk iz sol kenarı, son iz sağ kenarı kapsar; komşu örtüşmesi >= ortusme (+ yuvarlama payı)
        if bx1 - bx0 <= w:
            merkezler = [_yakin((bx0 + bx1) / 2)]
        else:
            m = math.ceil((bx1 - bx0 - w) / (w - ortusme - _ORTUSME_PAYI_M) - 1e-9) + 1
            ilk, son = bx0 + w / 2, bx1 - w / 2
            adim = (son - ilk) / (m - 1)
            merkezler = [_asagi(ilk)] + [_yakin(ilk + i * adim) for i in range(1, m - 1)] + [_yukari(son)]
        if by1 - by0 <= 2 * yarim_boy:
            raise ValueError(f"bölge {k + 1} y boyu ({by1 - by0:g} m) iz ayak izi boyundan ({2 * yarim_boy:.2f} m) kısa")
        y_alt, y_ust = _asagi(by0 + yarim_boy), _yukari(by1 - yarim_boy)
        noktalar = []
        for i, cx in enumerate(merkezler):
            ucu = (y_alt, y_ust) if i % 2 == 0 else (y_ust, y_alt)   # yılan: bir iz kuzeye, sonraki güneye
            noktalar.append([cx, ucu[0]])
            noktalar.append([cx, ucu[1]])
        rotalar.append({"arac_kimligi": arac_kimlikleri[k], "noktalar": noktalar})

    return {
        "surum": 1, "tur": "bolge_rota",
        "alan": {"cerceve": "yerel_ENU", "merkez_m": [mx, my], "genislik_m": gen, "yukseklik_m": yuk},
        "irtifa_m": irtifa, "hiz_ms": hiz,
        "serit": {"hfov_derece": hfov_deg, "iz_genisligi_m": round(w, 3), "ortusme_min_m": ortusme},
        "bolgeler": bolgeler, "rotalar": rotalar,
    }


def json_metni(d):
    """Belirlenimci seri hâli: 2 boşluk girinti, UTF-8, sonda satır sonu."""
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def rota_oku(yol, arac_kimligi):
    """Bölge/rota dosyasından bir aracın rotasını [(x, y), ...] (yerel ENU, m) ve bölge kimliğini okur."""
    with open(yol, encoding="utf-8") as f:
        d = json.load(f)
    rota = next((r for r in d["rotalar"] if r["arac_kimligi"] == arac_kimligi), None)
    bolge = next((b for b in d["bolgeler"] if b["arac_kimligi"] == arac_kimligi), None)
    if rota is None or bolge is None:
        raise KeyError(f"araç {arac_kimligi} için rota ya da bölge yok: {yol}")
    return [(float(x), float(y)) for x, y in rota["noktalar"]], bolge["bolge_kimligi"]
