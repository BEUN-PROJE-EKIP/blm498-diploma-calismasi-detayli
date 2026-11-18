#!/usr/bin/env python3
"""Kamera görüş yönü ve eksen denemesi (YALNIZ test): aşağı bakan kameranın görüntüsünde, yere konan bilinen bir işaretin yerini Gazebo pozundan öngörülen yerle karşılaştırır.

Kullanım:  python araclar/kamera_gorus_deneme.py [--arac-sirasi 1] [--dx 8] [--sure-sn S]     (GZ_PARTITION, GZ_IP ortam değişkenleriyle; setup/env.sh)
- Koşu klasöründe (yaşayan koşu) kırmızı, 3 × 3 × 0,05 m bir yer işareti modeli üretir ve sunucuya ekler: araç ROTASININ İLK DOĞRUSUNUN (x sabit, y boyunca) --dx m doğusuna, y = 0'a.
- Aracın kamera konusuna abone olur; her karede kırmızı piksellerin ağırlık merkezini bulur ve Gazebo model pozundan (en yakın simülasyon anındaki poz) öngörülen piksel konumuyla
  karşılaştırır: gövde çerçevesi FLU (x ileri, y sol, z yukarı); kamera gövdeye pitch +90° bağlı (optik eksen = gövde −z); görüntüde yukarı = gövde +x, sağ = gövde −y.
  Öngörü: u = cx − fx·d_y/derinlik, v = cy − fy·d_x/derinlik; d = R_gövdeᵀ (P_dünya − P_kamera), derinlik = −d_z; fx = (genişlik/2)/tan(HFOV/2) (kalibrasyon).
- Kayıt: koşu klasöründe gorus_deneme.jsonl; örnek görüntüler (ilk görünme, merkeze en yakın, son görünme) gorus_ornek_*.png (depoya girmez). SIGTERM ya da süre sonunda özet satırı yazar.
Çıkış 0. Yalnız test düzeneğidir; alıcıdan bağımsızdır (kendi gz aboneliği).
"""
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

import numpy as np  # noqa: E402
from swarm_vehicle.ucus import rota  # noqa: E402


def kuat_matris(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def ana(argv):
    sira, dx, sure = 1, 8.0, 3000.0
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--arac-sirasi" and a:
            sira = int(a.pop(0))
        elif k == "--dx" and a:
            dx = float(a.pop(0))
        elif k == "--sure-sn" and a:
            sure = float(a.pop(0))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    ham = rota.deney_env_oku()
    klasor = rota.aktif_kosu_klasoru()
    if not klasor:
        print("(-) yaşayan koşu yok", file=sys.stderr)
        return 2
    from gz.msgs10.image_pb2 import Image
    from gz.msgs10.pose_v_pb2 import Pose_V
    from gz.transport13 import Node
    from PIL import Image as PilImage

    w, h = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
    fx = (w / 2) / math.tan(float(ham["CAM_HFOV_RAD"]) / 2)
    cx, cy = w / 2, h / 2
    kam_z = float(ham["KAL_KAMERA_KONUM_Z_M"])
    arac_kimligi = int(ham["UAV_SYS_IDS"].split()[sira - 1])
    noktalar, _ = rota.rota_oku(os.path.join(KOK, "config", "bolge_rota.json"), arac_kimligi)
    bx, by, bz = noktalar[0][0] + dx, 0.0, 0.05                    # ilk doğrunun doğusunda 8 m, y = 0; kutunun üst yüzü z = 0,05 m
    model = ham["SIM_MODEL"].removeprefix("gz_") + f"_{sira - 1}"
    konu = f"/world/{ham['SIM_WORLD']}/model/{model}/link/{ham['KAMERA_LINK']}/sensor/{ham['KAMERA_ALGILAYICI']}/image"

    sdf = os.path.join(klasor, "gorus_isaret.sdf")
    with open(sdf, "w", encoding="utf-8") as f:
        f.write(f"""<?xml version="1.0"?><sdf version="1.9"><model name="gorus_isaret"><static>true</static><pose>{bx:g} {by:g} 0.025 0 0 0</pose>
<link name="l"><visual name="v"><geometry><box><size>3 3 0.05</size></box></geometry>
<material><ambient>1 0 0 1</ambient><diffuse>1 0 0 1</diffuse><emissive>1 0 0 1</emissive></material></visual></link></model></sdf>""")
    r = subprocess.run(["gz", "service", "-s", f"/world/{ham['SIM_WORLD']}/create", "--reqtype", "gz.msgs.EntityFactory", "--reptype", "gz.msgs.Boolean", "--timeout", "10000",
                        "--req", f'sdf_filename: "{sdf}", name: "gorus_isaret"'], capture_output=True, text=True, check=False)
    print(f"GORUS isaret eklendi: ({bx:g}, {by:g}) çıkış {r.returncode} {r.stdout.strip()}", flush=True)

    kayit = open(os.path.join(klasor, "gorus_deneme.jsonl"), "a", encoding="utf-8")
    kilit = threading.Lock()
    pozlar = deque(maxlen=400)       # (sim_ns, (x, y, z), (qx, qy, qz, qw))
    ornekler = {}
    sonuclar = []
    dur = threading.Event()

    def poz_geldi(m):
        sim = m.header.stamp.sec * 10 ** 9 + m.header.stamp.nsec
        for p in m.pose:
            if p.name == model:
                with kilit:
                    pozlar.append((sim, (p.position.x, p.position.y, p.position.z), (p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w)))

    def goruntu_geldi(m):
        sim = m.header.stamp.sec * 10 ** 9 + m.header.stamp.nsec
        img = np.frombuffer(m.data, dtype=np.uint8).reshape(m.height, m.width, 3)
        kirmizi = (img[:, :, 0] > 180) & (img[:, :, 1] < 70) & (img[:, :, 2] < 70)
        sayi = int(kirmizi.sum())
        with kilit:
            en_yakin = min(pozlar, key=lambda p: abs(p[0] - sim), default=None)
        if en_yakin is None or abs(en_yakin[0] - sim) > 30_000_000:
            return
        _, c, q = en_yakin
        kam = np.array(c) + kuat_matris(q) @ np.array([0.0, 0.0, kam_z])
        d = kuat_matris(q).T @ (np.array([bx, by, bz]) - kam)
        derinlik = -d[2]
        pu, pv = cx - fx * d[1] / derinlik, cy - fx * d[0] / derinlik
        gorunur_beklenen = bool(0 <= pu < w and 0 <= pv < h)
        satir = {"sim_ns": sim, "poz": [round(v, 3) for v in c], "kirmizi_piksel": sayi, "beklenen_goruntude": gorunur_beklenen, "oncul_uv": [round(pu, 1), round(pv, 1)]}
        if sayi >= 30:
            ys, xs = np.nonzero(kirmizi)
            u, v = float(xs.mean()), float(ys.mean())
            satir.update(olculen_uv=[round(u, 1), round(v, 1)], hata_px=round(math.hypot(u - pu, v - pv), 2))
            sonuclar.append((sim, u, v, pu, pv, abs(v - cy)))
            for ad, kosul in (("ilk", "ilk" not in ornekler), ("merkez", "merkez" not in ornekler or abs(v - cy) < ornekler["merkez"][0]), ("son", True)):
                if kosul:
                    ornekler[ad] = (abs(v - cy), img.copy())
        with kilit:
            kayit.write(json.dumps(satir) + "\n")
            kayit.flush()

    node = Node()
    node.subscribe(Pose_V, f"/world/{ham['SIM_WORLD']}/pose/info", poz_geldi)
    if not node.subscribe(Image, konu, goruntu_geldi):
        print(f"(-) abonelik kurulamadı: {konu}", file=sys.stderr)
        return 1
    signal.signal(signal.SIGTERM, lambda *_: dur.set())
    signal.signal(signal.SIGINT, lambda *_: dur.set())
    dur.wait(sure)
    for ad, (_, im) in ornekler.items():
        PilImage.fromarray(im).save(os.path.join(klasor, f"gorus_ornek_{ad}.png"))
    hatalar = [math.hypot(s[1] - s[3], s[2] - s[4]) for s in sonuclar]
    ozet = {"ozet": True, "tespit_sayisi": len(sonuclar), "en_buyuk_hata_px": round(max(hatalar), 2) if hatalar else None,
            "ortalama_hata_px": round(sum(hatalar) / len(hatalar), 2) if hatalar else None,
            "u_araligi": [round(min(s[1] for s in sonuclar), 1), round(max(s[1] for s in sonuclar), 1)] if sonuclar else None,
            "v_araligi": [round(min(s[2] for s in sonuclar), 1), round(max(s[2] for s in sonuclar), 1)] if sonuclar else None,
            "yaklasik_beklenen_u": round(cx + fx * dx / float(ham["ROTA_IRTIFA_M"]), 1)}
    with kilit:
        kayit.write(json.dumps(ozet) + "\n")
        kayit.close()
    print("GORUS " + json.dumps(ozet), flush=True)
    os._exit(0)     # gz-transport yıkım sorunundan kaçın (bkz. koordinatör)


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
