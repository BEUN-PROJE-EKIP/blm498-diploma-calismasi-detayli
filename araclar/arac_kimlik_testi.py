#!/usr/bin/env python3
"""Araç bağlantı/kimlik testleri ve simülasyon/PX4 zaman ekseni ölçümü.

Kullanım:  python araclar/arac_kimlik_testi.py {tek|uc|zaman}
Kimlik, port ve ad alanı değerleri ortam değişkenlerinden okunur (setup/arac_kimlik_testi.sh, config/deney.env'den verir):
UAV_SYS_IDS, UAV_NAMESPACES, PX4_MAVLINK_PORTS, MAVSDK_GRPC_PORTS, SIM_WORLD, ZAMAN_SURE_SN.
Her sonuç satırı "SONUC <gecti|kaldi> <ad> | <ayrıntı>" biçimindedir; kaldı varsa çıkış kodu 1.
Arm/kalkış yoktur; yerde bağlantı, kimlik ve telemetri akışı vardır.

Kimlik doğrulama yöntemi: bağlı sistemin MAV_SYS_ID parametresi MAVSDK param eklentisiyle okunur ve beklenenle karşılaştırılır.
Komutlar yalnız Komutcu üzerinden gider; Komutcu beklenen kimlik doğrulanmadan hiçbir komut göndermez (FR-8).
"""
import asyncio
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

KALDI = 0


def sonuc(gecti, ad, ayrinti):
    global KALDI
    if not gecti:
        KALDI += 1
    print(f"SONUC {'gecti' if gecti else 'kaldi'} {ad} | {ayrinti}", flush=True)


def olcum(ad, ayrinti):
    """Ölçüm/bilgi satırı: geçti/kaldı sayılmaz (test betikleri bilgi olarak yazar)."""
    print(f"OLCUM {ad} | {ayrinti}", flush=True)


def yapilandirma():
    def ints(k):
        return [int(x) for x in os.environ[k].split()]
    return {
        "sys_ids": ints("UAV_SYS_IDS"),
        "ns": os.environ["UAV_NAMESPACES"].split(),
        "udp": ints("PX4_MAVLINK_PORTS"),
        "grpc": ints("MAVSDK_GRPC_PORTS"),
        "world": os.environ.get("SIM_WORLD", "default"),
        "sure": float(os.environ.get("ZAMAN_SURE_SN", "70")),
    }


class KimlikHatasi(Exception):
    pass


class Komutcu:
    """Beklenen sistem kimliği doğrulanmadan komut göndermeyen sarmalayıcı."""

    def __init__(self, system, beklenen):
        self.system = system
        self.beklenen = beklenen
        self.gonderilen = 0
        self.gercek = None

    async def dogrula(self):
        self.gercek = await asyncio.wait_for(self.system.param.get_param_int("MAV_SYS_ID"), 15)
        if self.gercek != self.beklenen:
            raise KimlikHatasi(f"beklenen sistem kimliği {self.beklenen}, bağlı sistem {self.gercek}")

    async def komut(self, islev, *arg):
        await self.dogrula()          # her komuttan önce; uyuşmazlıkta istisna, komut gönderilmez
        self.gonderilen += 1
        return await islev(*arg)


async def baglan(grpc_port):
    from mavsdk import System
    s = System(mavsdk_server_address="127.0.0.1", port=grpc_port)
    await s.connect()
    async def bekle():
        async for st in s.core.connection_state():
            if st.is_connected:
                return
    await asyncio.wait_for(bekle(), 60)
    return s


async def ilk(akis, sn=60):
    async def al():
        async for x in akis:
            return x
    return await asyncio.wait_for(al(), sn)


async def tek():
    c = yapilandirma()
    s = await baglan(c["grpc"][0])
    k = Komutcu(s, c["sys_ids"][0])
    await k.dogrula()
    sonuc(k.gercek == c["sys_ids"][0], "tek_kimlik",
          f"MAV_SYS_ID={k.gercek} (beklenen {c['sys_ids'][0]}), UDP {c['udp'][0]}, gRPC {c['grpc'][0]}, ad alanı /{c['ns'][0]}; yöntem: MAVSDK param MAV_SYS_ID")
    await k.komut(s.telemetry.set_rate_position, 2.0)
    sonuc(k.gonderilen == 1, "tek_dogru_kimlikle_komut", f"gönderilen komut sayısı={k.gonderilen} (set_rate_position)")
    yanlis = c["sys_ids"][1]
    kk = Komutcu(s, yanlis)
    try:
        await kk.komut(s.telemetry.set_rate_position, 2.0)
        sonuc(False, "tek_yanlis_kimlik_reddi", f"beklenen {yanlis} ile komut GÖNDERİLDİ (gönderilen={kk.gonderilen})")
    except KimlikHatasi as e:
        sonuc(kk.gonderilen == 0, "tek_yanlis_kimlik_reddi", f"reddedildi: {e}; gönderilen komut sayısı={kk.gonderilen}")
    h = await ilk(s.telemetry.health())
    p = await ilk(s.telemetry.position())
    olcum("tek_akis", f"health global={h.is_global_position_ok} local={h.is_local_position_ok} home={h.is_home_position_ok}; "
          f"konum lat={p.latitude_deg:.6f} lon={p.longitude_deg:.6f} yuk={p.absolute_altitude_m:.1f}")


async def uc():
    c = yapilandirma()
    n = len(c["sys_ids"])
    sistemler = await asyncio.gather(*[baglan(g) for g in c["grpc"][:n]])
    komutcular = [Komutcu(sistemler[i], c["sys_ids"][i]) for i in range(n)]
    for i, k in enumerate(komutcular):
        await k.dogrula()
        sonuc(k.gercek == c["sys_ids"][i], f"uc_kimlik_{i + 1}",
              f"/{c['ns'][i]}: MAV_SYS_ID={k.gercek} (beklenen {c['sys_ids'][i]}), UDP {c['udp'][i]}, gRPC {c['grpc'][i]}")
    for i in range(n):
        diger = (i + 1) % n
        kk = Komutcu(sistemler[i], c["sys_ids"][diger])
        try:
            await kk.komut(sistemler[i].telemetry.set_rate_position, 2.0)
            sonuc(False, f"uc_capraz_{i + 1}", f"UDP {c['udp'][i]} bağlantısına kimlik-{c['sys_ids'][diger]} beklentisiyle komut GÖNDERİLDİ")
        except KimlikHatasi as e:
            sonuc(kk.gonderilen == 0, f"uc_capraz_{i + 1}", f"UDP {c['udp'][i]} + kimlik-{c['sys_ids'][diger]} beklentisi reddedildi: {e}; gönderilen={kk.gonderilen}")

    async def akis(i):
        s = sistemler[i]
        h = await ilk(s.telemetry.health())
        p = await ilk(s.telemetry.position())
        return i, h, p
    sonuclar = await asyncio.gather(*[akis(i) for i in range(n)])
    konumlar = set()
    for i, h, p in sonuclar:
        konumlar.add((round(p.latitude_deg, 6), round(p.longitude_deg, 6)))
        olcum(f"uc_akis_{i + 1}", f"/{c['ns'][i]} MAV_SYS_ID={c['sys_ids'][i]} health global={h.is_global_position_ok} local={h.is_local_position_ok} "
              f"konum lat={p.latitude_deg:.6f} lon={p.longitude_deg:.6f}")
    sonuc(len(konumlar) == n, "uc_ayri_konum", f"{len(konumlar)}/{n} farklı başlangıç konumu")


def dogru_regresyon(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx if sxx else 0.0


async def zaman():
    c = yapilandirma()
    from gz.transport13 import Node
    from gz.msgs10.clock_pb2 import Clock
    son = {"sim": None, "sim_t": None, "sys": None, "imu": None, "imu_t": None, "unix": None, "unix_t": None}

    def clock_cb(m):
        son["sim"] = m.sim.sec + m.sim.nsec * 1e-9
        son["sys"] = m.system.sec + m.system.nsec * 1e-9
        son["sim_t"] = time.monotonic()
    node = Node()
    if not node.subscribe(Clock, f"/world/{c['world']}/clock", clock_cb):
        sonuc(False, "zaman_gz_abonelik", f"/world/{c['world']}/clock aboneliği kurulamadı")
        return
    s = await baglan(c["grpc"][0])
    await s.telemetry.set_rate_imu(50.0)
    await s.telemetry.set_rate_unix_epoch_time(5.0)

    async def imu():
        async for x in s.telemetry.imu():
            son["imu"] = x.timestamp_us * 1e-6
            son["imu_t"] = time.monotonic()

    async def unix():
        async for x in s.telemetry.unix_epoch_time():
            son["unix"] = x * 1e-6
            son["unix_t"] = time.monotonic()
    gorevler = [asyncio.create_task(imu()), asyncio.create_task(unix())]
    t_bas = time.monotonic()
    while (son["sim"] is None or son["imu"] is None or son["unix"] is None) and time.monotonic() - t_bas < 30:
        await asyncio.sleep(0.1)
    if son["sim"] is None or son["imu"] is None:
        sonuc(False, "zaman_veri", f"sim saati={son['sim']} PX4 imu zamanı={son['imu']} alınamadı")
        for g in gorevler:
            g.cancel()
        return
    ornek = []
    t0 = time.monotonic()
    aralik = float(os.environ.get("ZAMAN_ARALIK_SN", "0.5"))
    while time.monotonic() - t0 < c["sure"]:
        await asyncio.sleep(aralik)
        now = time.monotonic()
        ornek.append({
            "wall": now - t0, "sim": son["sim"], "sys": son["sys"], "imu": son["imu"], "unix": son["unix"],
            "yas_sim": now - son["sim_t"], "yas_imu": now - son["imu_t"],
            "yas_unix": (now - son["unix_t"]) if son["unix_t"] else 0.0,
        })
    for g in gorevler:
        g.cancel()
    # Ölçü: fark = PX4 imu zamanı (time_usec, önyükleme saati) - sim saati. "ham": okunan son değerler; "yaş düzeltmeli":
    # her değer kendi okuma yaşı kadar ilerletilerek (hız ≈ 1) örnekleme anına taşınır (yaş farkı kesikliliği ham farkı oynatır).
    sim = [o["sim"] for o in ornek]
    wall = [o["wall"] for o in ornek]
    fark = [o["imu"] - o["sim"] for o in ornek]
    fark_k = [(o["imu"] + o["yas_imu"]) - (o["sim"] + o["yas_sim"]) for o in ornek]
    rtf = (sim[-1] - sim[0]) / (wall[-1] - wall[0])
    px4_hiz = (ornek[-1]["imu"] - ornek[0]["imu"]) / (wall[-1] - wall[0])
    yas = max(max(o["yas_sim"], o["yas_imu"]) for o in ornek)

    def ozet(ad, f):
        e = dogru_regresyon(sim, f)
        return (f"{ad}: ilk={f[0]:+.4f}s son={f[-1]:+.4f}s degisim={f[-1] - f[0]:+.4f}s min={min(f):+.4f} max={max(f):+.4f} "
                f"egim={e * 1e6:+.1f}us/s")
    print("ZAMAN_HAM  wall_s  sim_s  px4_imu_s  fark_s(px4-sim)  fark_yas_duzeltmeli_s  yas_sim_ms  yas_imu_ms", flush=True)
    sec = list(zip(ornek, fark, fark_k))
    for o, f, fk in sec[:5] + sec[-3:]:
        print(f"ZAMAN_HAM  {o['wall']:7.2f} {o['sim']:9.3f} {o['imu']:9.3f} {f:+9.4f} {fk:+9.4f} {o['yas_sim'] * 1000:6.0f} {o['yas_imu'] * 1000:6.0f}", flush=True)
    olcum("zaman_olcum",
          f"n={len(ornek)} aralik={aralik}s sure={wall[-1]:.0f}sn | {ozet('ham', fark)} | {ozet('yas_duzeltmeli', fark_k)} | "
          f"sim_RTF={rtf:.4f} px4_imu_hizi={px4_hiz:.4f} en_buyuk_okuma_yasi={yas * 1000:.0f}ms")
    u = [(o["unix"] + o["yas_unix"], o["sys"] + o["yas_sim"], o["sim"]) for o in ornek if o["unix"] and o["sys"]]
    if u:
        d = [a - b for a, b, _ in u]
        ue = dogru_regresyon([c_ for _, _, c_ in u], d)
        print(f"ZAMAN_UNIX  px4 SYSTEM_TIME(unix) - gz gerçek saat(system) (yaş düzeltmeli): ilk={d[0]:+.4f}s son={d[-1]:+.4f}s egim={ue * 1e6:+.1f}us/s (n={len(u)})", flush=True)


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else ""
    islev = {"tek": tek, "uc": uc, "zaman": zaman}.get(mod)
    if islev is None:
        print("Kullanım: arac_kimlik_testi.py {tek|uc|zaman}", file=sys.stderr)
        return 2
    try:
        asyncio.run(asyncio.wait_for(islev(), 300))
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sonuc(False, f"{mod}_istisna", f"{type(e).__name__}: {e}")
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(main())
