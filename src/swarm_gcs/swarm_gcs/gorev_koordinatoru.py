"""Yer istasyonu görev koordinatörü: `/gcs/mission_coordinator` düğümü (FR-2, FR-3, FR-4, FR-5 [hedef birleştirme hariç], FR-7) + izleme + komut arayüzü + kare sonucu alıcısı (tek yer istasyonu süreci).

Kullanım:  python -m swarm_gcs.gorev_koordinatoru --arac N [--zaman-asimi-sn S]      (setup/env.sh ortamı; araclar/kosu.sh baslat --yer-istasyonu var bunu başlatır)
Akış [belge: "Haberleşme Mimarisi"; planlama/sozlesmeler.md §9]: `config/bolge_rota.json` okunur; her araca kendi `Mission`'ı (ortak mission_id) ortak konudan yayımlanır → araçlar kendi Mission'larını yerel dosyayla
karşılaştırıp rotayı yükler, hazır olunca BARIYER_BEKLE bildirir → N araç BARIYER_BEKLE VE kare sonucu konusunda N yayımcıyla eşleşme → `ScanStart` (t0 = yayımlama anı) → N `ScanFinished` VE sonuç defteri tamam
(her aracın [n_ilk, n_son] aralığındaki her numara için tam bir sonuç; dört durumdan biri) → `Complete` (t1 = yayımlama anı) → N araç TAMAMLANDI → çıkış 0.
Hedef birleştirme (FR-5, B15) M3'tedir: "birleştirme yok" kaydı yazılır. Yedek yol numaralandırması (M3/B13) açık hata ile reddedilir. Zaman aşımı yalnız üst sınırdır (GCS_UST_SN / --zaman-asimi-sn; H değil):
aşılırsa COMPLETE yayımlanmaz, açık hata, çıkış 1. Komut gönderilmez (komut arayüzü yalnız test/elle kullanım içindir).
Kayıtlar (koşu klasörü): `kayit/yer_istasyonu_gorev.jsonl` (`gorev_olay`, §8.9), `kayit/yer_istasyonu_kare.jsonl` (`kullanilabilir`), `kayit/yer_istasyonu_durum.jsonl` (izleme; serbest biçim: durum değişimleri +
`IZLEME_OZET_SN` özetleri + bayat uyarıları), `kayit/yer_istasyonu_komut.jsonl` (komut/onay; serbest biçim), `kayit/yer_istasyonu_durum_ham.jsonl` (her durum iletisinin alım anı; serbest biçim), `yer_istasyonu.log` (metin günlüğü).
Test anahtarı (yalnız test, varsayılan kapalı): ortam değişkeni GOREV_ENJEKSIYON=`sapma=<araç>`: o aracın Mission'ının ilk noktası 1 m kaydırılır (araç yerel dosyayla uyuşmazlık görür, yüklemez).
Çıkış kodları: 0 tamam; 1 zaman aşımı/hata (COMPLETE yayımlanmadı); 2 kullanım/yapılandırma.
"""
import json
import os
import signal
import sys
import threading
import time

from swarm_vehicle import gorev as _gorev
from swarm_vehicle import rota

from .gorev_kayit import GorevKaydi
from .gorev_mantik import FAZ_HATA, Koordinasyon
from .izleme import DurumIzleyici


class Gunluk:
    """`yer_istasyonu.log`: satır = ISO saat, monotonik ns, olay, anahtar=değer (araç günlüğüyle aynı biçim)."""

    def __init__(self, yol):
        self.yol = yol

    def __call__(self, olay, **kv):
        satir = f"{time.strftime('%Y-%m-%dT%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} {time.monotonic_ns()} {olay}" + "".join(f" {k}={v}" for k, v in kv.items())
        if self.yol:
            with open(self.yol, "a", encoding="utf-8") as f:
                f.write(satir + "\n")


def ana(argv):
    n_arac, ust_sn = 0, None
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k == "--zaman-asimi-sn" and a:
            ust_sn = float(a.pop(0))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    ham = rota.deney_env_oku()
    tum = [int(x) for x in ham["UAV_SYS_IDS"].split()]
    if not 1 <= n_arac <= len(tum):
        print(__doc__, file=sys.stderr)
        return 2
    kimlikler = tum[:n_arac]
    if not os.environ.get("FASTRTPS_DEFAULT_PROFILES_FILE"):
        print("(-) FASTRTPS_DEFAULT_PROFILES_FILE tanımsız: setup/env.sh ile ortamı kurun", file=sys.stderr)
        return 2
    os.environ["SWARM_BIND_ADDR"] = ham["GCS_ADDR"]
    ust_sn = ust_sn if ust_sn is not None else float(os.environ.get("GCS_UST_SN") or ham["GCS_UST_SN"])      # ortam değişkeni yapılandırmayı yalnız o çağrı için geçersiz kılar (test amaçlı)

    import rclpy
    from geometry_msgs.msg import Point
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from swarm_msgs.msg import Complete, Mission, ScanFinished, ScanStart, VehicleState

    from .komut_arayuzu import KomutArayuzu
    from .sonuc_alici import SonucAlici

    klasor = rota.aktif_kosu_klasoru()
    yol = (lambda ad: os.path.join(klasor, ad)) if klasor else (lambda ad: None)
    log = Gunluk(yol("yer_istasyonu.log"))
    gorev = GorevKaydi(yol(os.path.join("kayit", "yer_istasyonu_gorev.jsonl")))
    durum_yol = yol(os.path.join("kayit", "yer_istasyonu_durum.jsonl"))
    ham_yol = yol(os.path.join("kayit", "yer_istasyonu_durum_ham.jsonl"))     # her VehicleState iletisi: alım anı (mono), yer istasyonu sim saati, iletideki sim damgası (DDS canlılık ölçümü)

    sim = {"ns": None}
    try:
        from gz.msgs10.clock_pb2 import Clock
        from gz.transport13 import Node as GzNode
        gz = GzNode()
        if not gz.subscribe(Clock, f"/world/{ham['SIM_WORLD']}/clock", lambda m: sim.__setitem__("ns", m.sim.sec * 10 ** 9 + m.sim.nsec)):
            log("gz_saat_yok", neden="abonelik kurulamadı; kayıtlarda sim_ns null olur")
    except Exception as e:  # noqa: BLE001
        log("gz_saat_yok", neden=repr(e))

    mission_id = f"G_{time.strftime('%Y%m%d_%H%M%S')}"
    kor = Koordinasyon(kimlikler, mission_id)
    izle = DurumIzleyici(kimlikler, ham["IZLEME_BAYAT_SN"], ham["IZLEME_OZET_SN"])
    rclpy.init()
    dugum = Node("mission_coordinator", namespace="/gcs")
    alici = SonucAlici(dugum, ham, kimlikler, yol(os.path.join("kayit", "yer_istasyonu_kare.jsonl")), log)
    komut = KomutArayuzu(dugum, ham, kimlikler, yol(os.path.join("kayit", "yer_istasyonu_komut.jsonl")))
    _ = komut        # komut arayüzü hazır (abone ve yayımcılar açık); koşu akışında komut gönderilmez

    def kontrol(derinlik):
        return QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=derinlik, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    qos_durum = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
    pub_mission = dugum.create_publisher(Mission, ham["KONU_GOREV"], kontrol(10))
    pub_start = dugum.create_publisher(ScanStart, ham["KONU_TARAMA_BASLAT"], kontrol(1))
    pub_complete = dugum.create_publisher(Complete, ham["KONU_COMPLETE"], kontrol(1))

    def yaz_olaylar(olaylar):
        for o in olaylar:
            o = dict(o)
            ad = o.pop("olay")
            gorev.yaz(ad, sim_ns=sim["ns"], **o)
            log("gorev_" + ad, **o)

    def durum_yaz(olaylar):
        for o in olaylar:
            d = {"mono_ns": time.monotonic_ns(), "sim_ns": sim["ns"], **o}
            if durum_yol:
                with open(durum_yol, "a", encoding="utf-8") as f:
                    f.write(json.dumps(d, ensure_ascii=False) + "\n")
            if o["olay"] != "ozet":
                print(f"IZLEME {DurumIzleyici.satir(o)}", flush=True)

    def durum_geldi(m):
        mono = time.monotonic_ns()
        if ham_yol:
            with open(ham_yol, "a", encoding="utf-8") as f:
                f.write(json.dumps({"mono_ns": mono, "sim_ns": sim["ns"], "arac": int(m.vehicle_id), "durum": int(m.state), "yayim_sim_ns": m.sim_stamp.sec * 10 ** 9 + m.sim_stamp.nanosec,
                                    "ilerleme": [int(m.mission_item_current), int(m.mission_item_total)], "son_kare": int(m.last_frame_number)}) + "\n")
        yaz_olaylar(kor.durum_geldi(m.vehicle_id, m.state, mono))
        durum_yaz(izle.durum_geldi(m.vehicle_id, m.state, (m.mission_item_current, m.mission_item_total), m.last_frame_number, mono))

    def bitis_geldi(m):
        mono = time.monotonic_ns()
        olaylar = kor.bitis_geldi(m.vehicle_id, m.mission_id, m.numbering_mode == ScanFinished.NUMBERING_GRID, m.n_first, m.n_last, mono)
        for o in olaylar:
            if o["olay"] == "tarama_bitisi":
                o["t_s_ns"] = o["t_b_ns"] = None       # ızgara yolunda ScanFinished t_s/t_b taşımaz (belge: kullanılmayan alanlar 0); araç günlüğünde (tarama_bitis_yayimlandi)
        yaz_olaylar(olaylar)
    durum_abone = dugum.create_subscription(VehicleState, ham["KONU_DURUM"], durum_geldi, qos_durum)
    durum_yayimci = {"sayi": None}
    dugum.create_subscription(ScanFinished, ham["KONU_TARAMA_BITIS"], bitis_geldi, kontrol(10))

    # --- görev ataması ---------------------------------------------------------------------------------------------------------------------
    yerel = os.path.join(rota.KOK, "config", "bolge_rota.json")
    br = _gorev.bolge_rota_oku(yerel)
    sapma = None
    enj = os.environ.get("GOREV_ENJEKSIYON", "").strip()
    if enj:
        anahtar, _, deger = enj.partition("=")
        if anahtar != "sapma":
            print(f"(-) GOREV_ENJEKSIYON: bilinmeyen anahtar '{anahtar}'", file=sys.stderr)
            return 2
        sapma = int(deger)
    log("basladi", mission_id=mission_id, arac=n_arac, rota_sha256=_gorev.dosya_sha256(yerel)[:16], enjeksiyon=enj or "kapali", ust_sn=ust_sn)
    for k in kimlikler:
        d = _gorev.mission_sozlugu(br, k, mission_id)
        ek = {}
        if sapma == k:
            d = _gorev.enjeksiyon_sapma(d)
            ek["ayrinti"] = "test enjeksiyonu: ilk nokta 1 m kaydırıldı"
        pub_mission.publish(_gorev.mesaj_doldur(Mission, Point, d))
        yaz_olaylar([{"olay": "gorev_atandi", "arac_kimligi": k, "mission_id": mission_id, **ek}])
    yaz_olaylar([{"olay": "birlestirme_yok", "ayrinti": "hedef birleştirme (FR-5, B15) M3'tedir; COMPLETE koşulunda yoktur"}])
    print(f"KOORDINATOR hazir mission_id={mission_id} arac={n_arac}", flush=True)

    # --- ana döngü --------------------------------------------------------------------------------------------------------------------------
    kod = 1
    dur = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: dur.set())
    signal.signal(signal.SIGINT, lambda *_: dur.set())
    sinir = time.monotonic() + ust_sn
    try:
        while rclpy.ok() and not dur.is_set():
            rclpy.spin_once(dugum, timeout_sec=0.05)
            yaz_olaylar(kor.eslesme_guncelle(alici.eslesen_yayinci()))
            n_dy = durum_abone.get_publisher_count()
            if n_dy != durum_yayimci["sayi"]:
                durum_yayimci["sayi"] = n_dy
                log("durum_eslesme_degisti", yayimci=n_dy)
            kor.sonuclar_guncelle(alici.defter.hepsi_tamam())
            durum_yaz(izle.kontrol(time.monotonic_ns()))
            eylem = kor.sonraki()
            if eylem == "scan_start":
                t0_mono = time.monotonic_ns()
                msg = ScanStart()
                msg.mission_id = mission_id
                pub_start.publish(msg)
                kor.scan_start_yapildi(t0_mono, sim["ns"])
                gorev.yaz("t0", sim_ns=sim["ns"], mono_ns=t0_mono, mission_id=mission_id)
                log("t0", mission_id=mission_id)
                print(f"KOORDINATOR t0 mission_id={mission_id} sim_ns={sim['ns']}", flush=True)
            elif eylem == "complete":
                yaz_olaylar([{"olay": "son_sonuc"}])
                t1_mono = time.monotonic_ns()
                msg = Complete()
                msg.mission_id = mission_id
                pub_complete.publish(msg)
                kor.complete_yapildi(t1_mono, sim["ns"])
                son_bitis = max(b[2] for b in kor.bitis.values())
                gorev.yaz("t1", sim_ns=sim["ns"], mono_ns=t1_mono, mission_id=mission_id, t1_eksi_son_bitis_ns=t1_mono - son_bitis)
                log("t1", mission_id=mission_id)
                print(f"KOORDINATOR t1 mission_id={mission_id} sim_ns={sim['ns']}", flush=True)
            elif eylem == "kapat":
                kor.kapatildi()
                for _ in range(10):                       # son durum iletileri (TAMAMLANDI) işlensin
                    rclpy.spin_once(dugum, timeout_sec=0.05)
                durum_yaz(izle.kontrol(time.monotonic_ns(), yalniz_ozet=True))
                print("KOORDINATOR bitti", flush=True)
                kod = 0
                break
            if kor.faz == FAZ_HATA:
                print(f"(-) KOORDINATOR hata: {kor.hata_nedeni}", file=sys.stderr, flush=True)
                break
            if time.monotonic() > sinir:
                neden = kor.zaman_asimi()
                gorev.yaz("zaman_asimi", sim_ns=sim["ns"], neden=neden or "ust_sure", ayrinti=json.dumps({str(a): v for a, v in alici.defter.sayilar().items()}, ensure_ascii=False))
                print(f"(-) KOORDINATOR zaman aşımı: {neden}", file=sys.stderr, flush=True)
                break
    finally:
        alici.kapat()
        dugum.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        if dur.is_set() and kod != 0:
            log("sinyal_ile_kapandi")
            kod = 143
    return kod


def main():
    kod = ana(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(kod)      # gz-transport Node yıkımı kapanışta çekirdek dökümü üretmesin (koordinator_deneme.py ile aynı gerekçe)


if __name__ == "__main__":
    main()
