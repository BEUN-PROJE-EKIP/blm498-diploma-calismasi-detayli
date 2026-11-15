#!/usr/bin/env python3
"""Gazebo gerçek poz kaydedicisi (YALNIZ test aracı; PX4'e ve araç sürecine dokunmaz): bir aracın model pozunu ve simülasyon saatini koşu klasörüne yazar.
Bağımsız doğrulama kaynağıdır: PX4 tahmininin (kare–poz enterpolasyonu) gerçek pozla karşılaştırılması (araclar/poz_analiz.py) ve PX4 zamanı − sim saati farkının yeniden ölçümü içindir.

Kullanım:  python araclar/poz_gercek_kayit.py --arac N [--aralik-sn 0.01]
Kaynak: /world/<dünya>/pose/info (model pozları; dünya çerçevesi ENU, gövde FLU; ileti başlığındaki damga simülasyon zamanıdır) ve /world/<dünya>/clock.
  Seçim gerekçesi: `pose/info`, diğer ölçüm araçlarının da kullandığı, model pozlarını simülasyon damgalı ileti başlığıyla veren konudur; böylece gerçek poz sim ekseninde, kare damgalarıyla doğrudan karşılaştırılır. Araç modeli `<SIM_MODEL öneksiz>_<örnek>`.
Çıktı: koşu klasöründe `gz_gercek_poz.jsonl` (serbest biçimli test çıktısı; şema değildir):
  {"k":"poz","mono_ns","sim_ns","p":[x,y,z],"q":[w,x,y,z]}   model pozu; sim_ns = pozu taşıyan iletinin simülasyon damgası, mono_ns = alım anı (CLOCK_MONOTONIC)
  {"k":"saat","mono_ns","sim_ns"}                              simülasyon saati (alım anıyla; yaklaşık her 0,1 sim sn)
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

from swarm_vehicle import rota  # noqa: E402


def ana(argv):
    arac, aralik = 0, 0.01
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            arac = int(a.pop(0))
        elif k == "--aralik-sn" and a:
            aralik = float(a.pop(0))
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
    from gz.msgs10.clock_pb2 import Clock
    from gz.msgs10.pose_v_pb2 import Pose_V
    from gz.transport13 import Node
    ad = f"{ham['SIM_MODEL'].removeprefix('gz_')}_{arac - 1}"
    f = open(os.path.join(klasor, "gz_gercek_poz.jsonl"), "a", encoding="utf-8")
    kilit = threading.Lock()
    son = {"poz": -1, "saat": -1}
    n = {"poz": 0, "saat": 0}

    def yaz(d):
        with kilit:
            if f.closed:
                return
            f.write(json.dumps(d, separators=(",", ":")) + "\n")
            n[d["k"]] += 1

    def poz(m):
        t = m.header.stamp.sec * 10 ** 9 + m.header.stamp.nsec
        if t - son["poz"] < aralik * 10 ** 9:
            return
        for p in m.pose:
            if p.name == ad:
                son["poz"] = t
                yaz({"k": "poz", "mono_ns": time.monotonic_ns(), "sim_ns": t, "p": [p.position.x, p.position.y, p.position.z],
                     "q": [p.orientation.w, p.orientation.x, p.orientation.y, p.orientation.z]})
                return

    def saat(m):
        t = m.sim.sec * 10 ** 9 + m.sim.nsec
        if t - son["saat"] < 10 ** 8:
            return
        son["saat"] = t
        yaz({"k": "saat", "mono_ns": time.monotonic_ns(), "sim_ns": t})
    gz = Node()
    dunya = ham["SIM_WORLD"]
    if not (gz.subscribe(Clock, f"/world/{dunya}/clock", saat) and gz.subscribe(Pose_V, f"/world/{dunya}/pose/info", poz)):
        print("(-) gz aboneliği kurulamadı (GZ_PARTITION/GZ_IP doğru mu?)", file=sys.stderr)
        return 1
    dur = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: dur.set())
    signal.signal(signal.SIGINT, lambda *_: dur.set())
    print(f"KAYIT basladi model={ad} dosya={klasor}/gz_gercek_poz.jsonl", flush=True)
    while not dur.wait(0.5):
        with kilit:
            f.flush()
    with kilit:
        f.flush()
        f.close()
    print(f"KAYIT bitti poz={n['poz']} saat={n['saat']}", flush=True)
    os._exit(0)                                   # gz-transport düğümünün yorumlayıcı kapanışındaki yıkıcısı `terminate called` ile çöküyor; veriler yukarıda boşaltıldı


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
