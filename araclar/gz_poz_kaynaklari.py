#!/usr/bin/env python3
"""Gazebo poz kaynaklarının karşılaştırma kaydedicisi (YALNIZ test aracı; PX4'e ve araç sürecine dokunmaz): `pose/info`, `dynamic_pose/info` ve adında `pose` geçen diğer poz konularını
(Pose_V ya da Pose) aynı koşuda dinler; her ileti için ileti başlığı damgasını (simülasyon zamanı), alım anını (CLOCK_MONOTONIC) ve aracın model/gövde pozunu yazar.
Amaç: gerçek poz kaynağının damgasının ve değerlerinin kaynaklar arasında aynı an için tutarlı olup olmadığını ölçmek (odometri zaman kayması incelemesi).

Kullanım:  python araclar/gz_poz_kaynaklari.py --arac N
Çıktı (koşu klasörü): `gz_poz_kaynaklari.jsonl` (serbest biçimli test çıktısı, şema değildir):
  {"k":"poz","konu":<konu adı>,"damga_ns","mono_ns","ad":<varlık adı>,"p":[x,y,z],"q":[w,x,y,z]}   yalnız model (`<SIM_MODEL öneksiz>_<örnek>`) ve `base_link` varlıkları
  {"k":"konular","liste":[[konu, ileti türü], ...]}                                                başlangıçta bulunan poz konuları
Sonlanma: SIGTERM/SIGINT ile tamponu boşaltıp çıkar. Ortam: GZ_PARTITION, GZ_IP, setup/env.sh. Çıkış: 0 tamam, 1 hata, 2 kullanım.
"""
import json
import os
import signal
import sys
import threading
import time

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

from swarm_vehicle.ucus import rota  # noqa: E402


def ana(argv):
    arac = 0
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            arac = int(a.pop(0))
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
    from gz.msgs10.pose_pb2 import Pose
    from gz.msgs10.pose_v_pb2 import Pose_V
    from gz.transport13 import Node
    ad = f"{ham['SIM_MODEL'].removeprefix('gz_')}_{arac - 1}"
    gz = Node()
    konular = []
    for _ in range(50):                               # konu keşfi gecikebilir
        konular = [t for t in gz.topic_list() if "pose" in t.lower()]
        if any(t.endswith("/pose/info") for t in konular) and any(t.endswith("/dynamic_pose/info") for t in konular):
            break
        time.sleep(0.2)
    liste = []
    for t in konular:
        tur = ""
        try:
            yayincilar = gz.topic_info(t)[0]
            tur = yayincilar[0].msg_type_name if yayincilar else ""
        except Exception:  # noqa: BLE001
            pass
        if not tur and t.endswith("/info"):
            tur = "gz.msgs.Pose_V"                   # tür okunamazsa: `.../info` konuları Pose_V taşır
        liste.append([t, tur])
    f = open(os.path.join(klasor, "gz_poz_kaynaklari.jsonl"), "a", encoding="utf-8")
    kilit = threading.Lock()
    sayac = {}

    def yaz(d):
        f.write(json.dumps(d, separators=(",", ":")) + "\n")

    with kilit:
        yaz({"k": "konular", "liste": liste})

    def poz_yaz(konu, damga, mono, p):
        if p.name not in (ad, "base_link"):
            return
        with kilit:
            if f.closed:
                return
            sayac[konu] = sayac.get(konu, 0) + 1
            yaz({"k": "poz", "konu": konu, "damga_ns": damga, "mono_ns": mono, "ad": p.name, "p": [p.position.x, p.position.y, p.position.z],
                 "q": [p.orientation.w, p.orientation.x, p.orientation.y, p.orientation.z]})

    def vc(konu):
        def geri(m):
            mono = time.monotonic_ns()
            damga = m.header.stamp.sec * 10 ** 9 + m.header.stamp.nsec
            for p in m.pose:
                poz_yaz(konu, damga, mono, p)
        return geri

    def tek(konu):
        def geri(m):
            mono = time.monotonic_ns()
            poz_yaz(konu, m.header.stamp.sec * 10 ** 9 + m.header.stamp.nsec, mono, m)
        return geri

    abone = []
    for konu, tur in liste:
        if tur.endswith("Pose_V") and gz.subscribe(Pose_V, konu, vc(konu)):
            abone.append(konu)
        elif tur.endswith(".Pose") and gz.subscribe(Pose, konu, tek(konu)):
            abone.append(konu)
    if not abone:
        print("(-) hiçbir poz konusuna abone olunamadı (GZ_PARTITION/GZ_IP doğru mu?)", file=sys.stderr)
        return 1
    dur = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: dur.set())
    signal.signal(signal.SIGINT, lambda *_: dur.set())
    print(f"POZ_KAYNAKLARI basladi model={ad} konular={abone}", flush=True)
    while not dur.wait(0.5):
        with kilit:
            f.flush()
    with kilit:
        f.flush()
        f.close()
    print(f"POZ_KAYNAKLARI bitti {json.dumps(sayac)}", flush=True)
    os._exit(0)                                   # gz-transport düğümünün yorumlayıcı kapanışındaki çökmesini önler; veriler yukarıda boşaltıldı


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
