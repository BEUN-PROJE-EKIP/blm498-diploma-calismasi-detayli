#!/usr/bin/env python3
"""Alan pilotu gözlemcisi (YALNIZ ölçüm; PX4'e hiçbir şey yazmaz): Gazebo model pozlarını ve PX4 yönelim/konum/hız telemetrisini koşu klasörüne kaydeder.

Kullanım:  python araclar/alan_pilot_olcum.py --arac N [--gz-aralik-sn 0.05]
Kaynaklar:
  Gazebo (gerçek değer): /world/<dünya>/pose/info (model pozları; dünya çerçevesi ENU, gövde FLU), /world/<dünya>/clock. Her araç modeli `<SIM_MODEL öneksiz>_<örnek>`.
  PX4 tahmini (salt okuma): aracın bağdaştırıcısının zaten başlattığı mavsdk_server'a (MAVSDK_GRPC_PORTS) ikinci istemci olarak bağlanır
    (yalnız telemetry.attitude_quaternion ve telemetry.position_velocity_ned akışları; ayar/komut/parametre yazılmaz, akış hızı DEĞİŞTİRİLMEZ).
Çıktı: koşu klasöründe `alan_pilot_olcum.jsonl` (serbest biçimli test çıktısı; şema değildir). Satır türleri:
  {"k":"gz","a":<araç sırası 1..N>,"mono_ns","sim_ns","p":[x,y,z],"q":[w,x,y,z]}   Gazebo model pozu (sim_ns: pozu taşıyan iletinin simülasyon damgası)
  {"k":"att","a","mono_ns","sim_ns","q":[w,x,y,z],"px4_us"}                      PX4 yönelim tahmini (FRD→NED); sim_ns = alım anındaki simülasyon saati
  {"k":"pv","a","mono_ns","sim_ns","n":[kuzey,doğu,aşağı],"v":[vn,ve,vd]}          PX4 yerel konum/hız tahmini (NED, PX4 yerel orijini)
Sonlanma: SIGTERM/SIGINT ile tamponu boşaltıp çıkar. Ortam: GZ_PARTITION, GZ_IP, setup/env.sh (venv). Çıkış: 0 tamam, 1 hata, 2 kullanım.
"""
import asyncio
import json
import os
import signal
import sys
import threading
import time

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

from swarm_vehicle import rota  # noqa: E402


class Yazici:
    def __init__(self, yol):
        self.f = open(yol, "a", encoding="utf-8")
        self.kilit = threading.Lock()
        self.sayac = {}

    def yaz(self, d):
        with self.kilit:
            self.f.write(json.dumps(d, separators=(",", ":")) + "\n")
            self.sayac[d["k"]] = self.sayac.get(d["k"], 0) + 1

    def bosalt(self):
        with self.kilit:
            self.f.flush()

    def kapat(self):
        with self.kilit:
            self.f.flush()
            self.f.close()


def ana(argv):
    n_arac, aralik = 0, 0.05
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k == "--gz-aralik-sn" and a:
            aralik = float(a.pop(0))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    ham = rota.deney_env_oku()
    grpc = [int(x) for x in ham["MAVSDK_GRPC_PORTS"].split()]
    if not 1 <= n_arac <= len(grpc):
        print(__doc__, file=sys.stderr)
        return 2
    klasor = rota.aktif_kosu_klasoru()
    if not klasor:
        print("(-) yaşayan koşu yok (araclar/kosu.sh baslat)", file=sys.stderr)
        return 1
    yazici = Yazici(os.path.join(klasor, "alan_pilot_olcum.jsonl"))

    from gz.msgs10.clock_pb2 import Clock
    from gz.msgs10.pose_v_pb2 import Pose_V
    from gz.transport13 import Node as GzNode
    from mavsdk import System

    sim = {"ns": None}
    son_yaz = {}
    onek = ham["SIM_MODEL"].removeprefix("gz_")
    modeller = {f"{onek}_{i}": i + 1 for i in range(n_arac)}

    def saat(m):
        sim["ns"] = m.sim.sec * 10 ** 9 + m.sim.nsec

    def poz(m):
        t_msg = m.header.stamp.sec * 10 ** 9 + m.header.stamp.nsec if m.header.HasField("stamp") else None
        t = t_msg if t_msg else sim["ns"]
        for p in m.pose:
            idx = modeller.get(p.name)
            if idx is None or t is None:
                continue
            if t - son_yaz.get(idx, -10 ** 18) < aralik * 10 ** 9:
                continue
            son_yaz[idx] = t
            yazici.yaz({"k": "gz", "a": idx, "mono_ns": time.monotonic_ns(), "sim_ns": t,
                        "p": [round(p.position.x, 4), round(p.position.y, 4), round(p.position.z, 4)],
                        "q": [round(p.orientation.w, 6), round(p.orientation.x, 6), round(p.orientation.y, 6), round(p.orientation.z, 6)]})
    gz = GzNode()
    dunya = ham["SIM_WORLD"]
    if not (gz.subscribe(Clock, f"/world/{dunya}/clock", saat) and gz.subscribe(Pose_V, f"/world/{dunya}/pose/info", poz)):
        print("(-) gz aboneliği kurulamadı (GZ_PARTITION/GZ_IP doğru mu?)", file=sys.stderr)
        return 1

    dur = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: dur.set())
    signal.signal(signal.SIGINT, lambda *_: dur.set())

    async def baglan(port):
        s = System(mavsdk_server_address="127.0.0.1", port=port)
        await s.connect()

        async def bekle():
            async for st in s.core.connection_state():
                if st.is_connected:
                    return
        await asyncio.wait_for(bekle(), 120)
        return s

    async def att_akisi(idx, s):
        async for q in s.telemetry.attitude_quaternion():
            yazici.yaz({"k": "att", "a": idx, "mono_ns": time.monotonic_ns(), "sim_ns": sim["ns"],
                        "q": [round(q.w, 6), round(q.x, 6), round(q.y, 6), round(q.z, 6)], "px4_us": int(q.timestamp_us)})

    async def pv_akisi(idx, s):
        async for pv in s.telemetry.position_velocity_ned():
            yazici.yaz({"k": "pv", "a": idx, "mono_ns": time.monotonic_ns(), "sim_ns": sim["ns"],
                        "n": [round(pv.position.north_m, 3), round(pv.position.east_m, 3), round(pv.position.down_m, 3)],
                        "v": [round(pv.velocity.north_m_s, 3), round(pv.velocity.east_m_s, 3), round(pv.velocity.down_m_s, 3)]})

    async def calis():
        sistemler = await asyncio.gather(*[baglan(grpc[i]) for i in range(n_arac)])
        print(f"OLCUM baglandi araclar={n_arac} gz_modeller={sorted(modeller)}", flush=True)
        gorevler = []
        for i, s in enumerate(sistemler):
            gorevler.append(asyncio.create_task(att_akisi(i + 1, s)))
            gorevler.append(asyncio.create_task(pv_akisi(i + 1, s)))
        while not dur.is_set():
            await asyncio.sleep(0.5)
            yazici.bosalt()
            for g in gorevler:
                if g.done() and not g.cancelled() and g.exception() is not None:
                    print(f"(-) akış hatası: {g.exception()!r}", file=sys.stderr, flush=True)
                    dur.set()
        for g in gorevler:
            g.cancel()
        await asyncio.gather(*gorevler, return_exceptions=True)

    kod = 0
    try:
        asyncio.run(calis())
    except Exception as e:  # noqa: BLE001
        print(f"(-) gözlemci hatası: {e!r}", file=sys.stderr, flush=True)
        kod = 1
    yazici.kapat()
    print("OLCUM kapandi " + " ".join(f"{k}={v}" for k, v in sorted(yazici.sayac.items())), flush=True)
    return kod


if __name__ == "__main__":
    kod_ = ana(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(kod_)   # gz-transport Node yıkımı kapanışta çekirdek dökümü üretmesin (koordinator_deneme.py ile aynı gerekçe)
