#!/usr/bin/env python3
"""Konum hesaplayıcı geometri denetimi için test işareti aracı (YALNIZ test aracı; PX4'e, araç sürecine ve yer istasyonuna dokunmaz; dünya dosyası ve sahne üretimi değişmez).

Koşu başladıktan sonra Gazebo'ya (gz `create` hizmeti) bilinen ENU konumlarına düz, yüksek karşıtlıklı (saf kırmızı, ışıktan bağımsız) işaretler ekler; işaretler aracın rotası altına
ve görüntü kenarlarına yakın düşecek biçimde, rotadan (`rota.uret`) türetilen konumlara konur. Aracın kamera konusuna ikinci bir abone olarak her görev karesinde basit renk eşiğiyle
işaretleri bulur (çıkarım modeli kullanılmaz) ve işaret merkezlerini piksel olarak kaydeder.

Kullanım:  python araclar/deneme/konum_isaret.py --arac N [--ofset-m 16] [--boyut-m 1.2]
Çıktı (koşu klasörü): `konum_isaretleri.json` (işaretlerin gerçek ENU konumları; yalnız değerlendirmede kullanılır, hesaplayıcıya verilmez) ve `konum_isaret_kareler.jsonl`
  (her ızgara karesi için {"n", "damga_ns", "bloblar": [{"cx", "cy", "alan_px"}]}; serbest biçimli test çıktısı, şema değildir).
Sonlanma: SIGTERM/SIGINT ile tamponu boşaltıp çıkar. Ortam: GZ_PARTITION, GZ_IP, setup/env.sh. Çıkış: 0 tamam, 1 hata, 2 kullanım.
"""
import json
import os
import signal
import sys
import threading
import time

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

from swarm_vehicle.ucus import rota  # noqa: E402

ESIK_KIRMIZI, ESIK_DIGER = 200, 60
MIN_ALAN_PX = 30


def isaret_konumlari(ham, arac, ofset_m):
    """Aracın rotasından işaret konumları (ENU): ilk üç şerit izinde yanal ofsetler {−ofset, 0, +ofset} ve iz boyunca farklı oranlarda. Rota yoksa ValueError."""
    d = rota.uret(ham)
    kim = int(ham["UAV_SYS_IDS"].split()[arac - 1])
    r = next(x for x in d["rotalar"] if x["arac_kimligi"] == kim)
    noktalar = r["noktalar"]
    izler = [(noktalar[i], noktalar[i + 1]) for i in range(0, len(noktalar) - 1, 2)]
    if len(izler) < 3:
        raise ValueError("rotada en az üç şerit izi gerekli")
    yarim_genislik = d["serit"]["iz_genisligi_m"] / 2
    if ofset_m >= yarim_genislik:
        raise ValueError(f"ofset ({ofset_m} m) iz yarı genişliğinden ({yarim_genislik:.2f} m) küçük olmalı")
    orani = (0.25, 0.55, 0.8)
    sonuc = []
    for j, (yan) in enumerate((-ofset_m, 0.0, ofset_m)):
        for i in range(3):
            (cx, y_a), (_, y_b) = izler[i]
            y = y_a + (y_b - y_a) * orani[(i + j) % 3]
            sonuc.append({"ad": f"konum_isareti_{len(sonuc)}", "x": cx + yan, "y": y, "iz": i, "yanal_m": yan})
    return sonuc


def sdf_uret(ad, x, y, boyut):
    return f"""<?xml version="1.0"?>
<sdf version="1.9"><model name="{ad}"><static>true</static><pose>{x!r} {y!r} 0.011 0 0 0</pose>
<link name="l"><visual name="v"><geometry><box><size>{boyut!r} {boyut!r} 0.02</size></box></geometry>
<material><ambient>1 0 0 1</ambient><diffuse>1 0 0 1</diffuse><emissive>1 0 0 1</emissive><specular>0 0 0 1</specular></material></visual></link></model></sdf>"""


def bloklari_bul(rgb, numpy, cv2):
    """RGB8 görüntüde saf kırmızı bölgeleri bulur: [{cx, cy, alan_px}] (yoğunluk ağırlıksız geometrik merkez, piksel; orijin sol üst piksel köşesi)."""
    maske = ((rgb[:, :, 0] >= ESIK_KIRMIZI) & (rgb[:, :, 1] <= ESIK_DIGER) & (rgb[:, :, 2] <= ESIK_DIGER)).astype(numpy.uint8)
    n, _, st, merkez = cv2.connectedComponentsWithStats(maske, connectivity=8)
    cikti = []
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= MIN_ALAN_PX:
            # connectedComponents merkezi piksel-indeks çerçevesindedir (ilk pikselin merkezi 0,0); sürekli piksel çerçevesine (sol üst köşe orijin) +0,5 ile taşınır
            cikti.append({"cx": float(merkez[i][0]) + 0.5, "cy": float(merkez[i][1]) + 0.5, "alan_px": int(st[i, cv2.CC_STAT_AREA]),
                          "x": int(st[i, cv2.CC_STAT_LEFT]), "y": int(st[i, cv2.CC_STAT_TOP]), "w": int(st[i, cv2.CC_STAT_WIDTH]), "h": int(st[i, cv2.CC_STAT_HEIGHT])})
    return cikti


def ana(argv):
    arac, ofset, boyut = 0, 16.0, 1.2
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            arac = int(a.pop(0))
        elif k == "--ofset-m" and a:
            ofset = float(a.pop(0))
        elif k == "--boyut-m" and a:
            boyut = float(a.pop(0))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    ham = rota.deney_env_oku()
    if not 1 <= arac <= len(ham["UAV_SYS_IDS"].split()):
        print(__doc__, file=sys.stderr)
        return 2
    klasor = rota.aktif_kosu_klasoru()
    if not klasor:
        print("(-) yaşayan koşu yok (araclar/kosu.sh baslat)", file=sys.stderr)
        return 1
    import cv2
    import numpy
    from gz.msgs10.boolean_pb2 import Boolean
    from gz.msgs10.entity_factory_pb2 import EntityFactory
    from gz.msgs10.image_pb2 import Image
    from gz.transport13 import Node
    from swarm_vehicle.kamera.kamera_alici import n_hesapla

    hz = int(float(ham["CAM_RATE_HZ"]))
    w, h = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
    isaretler = isaret_konumlari(ham, arac, ofset)
    gz = Node()
    dunya = ham["SIM_WORLD"]
    for i in isaretler:
        istek = EntityFactory()
        istek.sdf = sdf_uret(i["ad"], i["x"], i["y"], boyut)
        ok, yanit = gz.request(f"/world/{dunya}/create", istek, EntityFactory, Boolean, 5000)
        if not (ok and yanit.data):
            print(f"(-) işaret eklenemedi: {i['ad']} (ok={ok})", file=sys.stderr)
            return 1
    with open(os.path.join(klasor, "konum_isaretleri.json"), "w", encoding="utf-8") as f:
        json.dump({"arac": arac, "boyut_m": boyut, "zemin_z_m": 0.0, "isaretler": isaretler}, f, indent=1)
    onek = ham["SIM_MODEL"].removeprefix("gz_")
    konu = f"/world/{dunya}/model/{onek}_{arac - 1}/link/{ham['KAMERA_LINK']}/sensor/{ham['KAMERA_ALGILAYICI']}/image"
    kilit = threading.Lock()
    f = open(os.path.join(klasor, "konum_isaret_kareler.jsonl"), "a", encoding="utf-8")
    sayac = {"kare": 0, "izgara": 0}

    def kare(m):
        damga = m.header.stamp.sec * 10 ** 9 + m.header.stamp.nsec
        n = n_hesapla(damga, hz)
        sayac["kare"] += 1
        if n is None or (m.width, m.height) != (w, h) or len(m.data) != w * h * 3:
            return
        rgb = numpy.frombuffer(m.data, dtype=numpy.uint8).reshape(h, w, 3)
        bloklar = bloklari_bul(rgb, numpy, cv2)
        with kilit:
            if f.closed:
                return
            f.write(json.dumps({"n": n, "damga_ns": damga, "bloklar": bloklar}, separators=(",", ":")) + "\n")
            sayac["izgara"] += 1

    if not gz.subscribe(Image, konu, kare):
        print(f"(-) kamera konusuna abonelik kurulamadı: {konu}", file=sys.stderr)
        return 1
    dur = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: dur.set())
    signal.signal(signal.SIGINT, lambda *_: dur.set())
    print(f"ISARET basladi isaret={len(isaretler)} konu={konu}", flush=True)
    while not dur.wait(0.5):
        with kilit:
            f.flush()
    with kilit:
        f.flush()
        f.close()
    print(f"ISARET bitti kare={sayac['kare']} izgara={sayac['izgara']}", flush=True)
    os._exit(0)                                   # gz-transport düğümünün yorumlayıcı kapanışındaki çökmesini önler; veriler yukarıda boşaltıldı


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
