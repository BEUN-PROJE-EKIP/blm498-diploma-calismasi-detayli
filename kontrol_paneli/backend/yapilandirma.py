"""Panel yapılandırması: paylaşılan değerler config/deney.env'den (tek kaynak), panele özgü değerler panel_ayar.json'dan okunur."""
import json
import math
import os
import re
from dataclasses import dataclass, field

PANEL_DIZINI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KOK_DIZIN = os.path.dirname(PANEL_DIZINI)
_SATIR = re.compile(r'^([A-Z_][A-Z0-9_]*)="?([^"]*)"?\s*$')


def deney_env_oku(yol):
    """deney.env'deki KEY="değer" satırlarını okur (değişken açılımı yapılmaz; panelin okuduğu anahtarlar düz değerdir)."""
    ham = {}
    with open(yol, encoding="utf-8") as f:
        for satir in f:
            m = _SATIR.match(satir.strip())
            if m:
                ham[m.group(1)] = m.group(2)
    return ham


@dataclass
class Arac:
    no: int              # 1, 2, 3 (PX4 örneği no − 1)
    sys_id: int
    baslangic: tuple     # (x, y, z) dünya ENU, m
    grpc_port: int
    gcs_udp_port: int          # PX4'ün GCS bağlantısının dinlediği port (18570 + örnek)
    aktarma_px4_port: int      # aktarıcının PX4'e konuştuğu SABİT yerel port
    aktarma_mavsdk_port: int   # mavsdk_server'ın bağlandığı aktarıcı portu
    kamera_konusu: str
    model_adi: str


@dataclass
class Yapilandirma:
    ham: dict
    ayar: dict
    dunya: str
    araclar: list = field(default_factory=list)
    kalkis_irtifa_m: float = 30.0

    @property
    def kosu_kok(self):
        return os.path.join(KOK_DIZIN, ".generated", "kosular")

    @property
    def kosu_betigi(self):
        return os.path.join(KOK_DIZIN, "araclar", "kosu.sh")


def harita_kapsamini_ayarla(h, kok=KOK_DIZIN):
    """Harita kamerasını görev alanının tamamını (kenar payıyla) görecek biçimde konumlandırır (yerinde günceller).

    Kamera aşağı bakar; yatay görüş açısı hfov, düşey açı en-boy oranından. Gereken yükseklik iki eksenin büyüğüdür.
    """
    if h.get("kapsama", "elle") != "bolge_rota":
        return h
    with open(os.path.join(kok, "config", "bolge_rota.json"), encoding="utf-8") as f:
        alan = json.load(f)["alan"]
    pay = float(h.get("kenar_payi_m", 0))
    gen, yuk = float(alan["genislik_m"]) + 2 * pay, float(alan["yukseklik_m"]) + 2 * pay
    tan_y = math.tan(float(h["hfov_rad"]) / 2)
    tan_d = tan_y * float(h["yukseklik_px"]) / float(h["genislik_px"])
    h["merkez_m"] = [float(v) for v in alan["merkez_m"]]
    h["yukseklik_m"] = round(max(gen / 2 / tan_y, yuk / 2 / tan_d), 1)
    h["uzak_kirpma_m"] = max(float(h["uzak_kirpma_m"]), h["yukseklik_m"] * 1.5)
    return h


def yukle():
    ham = deney_env_oku(os.environ.get("DENEY_ENV", os.path.join(KOK_DIZIN, "config", "deney.env")))
    with open(os.path.join(PANEL_DIZINI, "panel_ayar.json"), encoding="utf-8") as f:
        ayar = json.load(f)
    harita_kapsamini_ayarla(ayar["harita"])
    dunya = ham["SIM_WORLD"]
    onek = ham["SIM_MODEL"].removeprefix("gz_")
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()]
    pozlar = [tuple(float(v) for v in p.split(",")) for p in ham["UAV_START_POSES"].split()]
    grpc = ayar["mavsdk_grpc_portlari"]
    if len(grpc) < len(kimlikler):
        raise ValueError("panel_ayar.json: mavsdk_grpc_portlari araç sayısından az")
    araclar = []
    for i, sid in enumerate(kimlikler):
        model = f"{onek}_{i}"
        araclar.append(Arac(
            no=i + 1, sys_id=sid, baslangic=pozlar[i], grpc_port=int(grpc[i]),
            gcs_udp_port=int(ayar["px4_gcs_udp_taban"]) + i,
            aktarma_px4_port=int(ayar["px4_tarafi_port_taban"]) + i,
            aktarma_mavsdk_port=int(ayar["mavsdk_tarafi_port_taban"]) + i,
            kamera_konusu=f"/world/{dunya}/model/{model}/link/{ham['KAMERA_LINK']}/sensor/{ham['KAMERA_ALGILAYICI']}/image",
            model_adi=model))
    return Yapilandirma(ham=ham, ayar=ayar, dunya=dunya, araclar=araclar, kalkis_irtifa_m=float(ham.get("CAM_ALT_M", "30")))
