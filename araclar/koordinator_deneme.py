#!/usr/bin/env python3
"""Deneme koordinatörü (YALNIZ test sürücüsü; asıl yer istasyonu görev koordinatörü `swarm_gcs.gorev_koordinatoru`'dur ve olağan akışı o yürütür; bu betik olumsuz senaryolar — erken/yanlış olaylar, gecikme/eksik sonuç —
ve Gazebo model pozu kaydı gibi test ölçümleri için kullanılır; PX4'e dokunmaz, hedef birleştirme yoktur). Araçların beklediği `Mission` iletilerini de yayımlar (aynı `gorev.py` mantığı; ortak görev kimliği = ScanStart kimliği).

Kullanım:  python araclar/koordinator_deneme.py --arac N [--erken-scan-start] [--erken-complete] [--yanlis-complete] [--yanlis-bekle-sn S] [--zaman-asimi-sn S] [--sonuc-zaman-asimi-sn S]
  --arac N               beklenen araç sayısı (UAV_SYS_IDS'in ilk N değeri)
  --erken-scan-start     araçlar BARIYER_BEKLE'ye geçmeden ("ERKEN" kimlikli) bir tarama başlatma yayımlar: araçlar yok saymalı
  --erken-complete       tarama başlatmadan 5 sn sonra (araçlar TARAMA'dayken) doğru kimlikli bir COMPLETE yayımlar: araçlar yok saymalı
  --sonuc-zaman-asimi-sn tarama bitişleri alındıktan sonra kare sonuçlarını bekleme üst sınırı (öntanımlı: genel --zaman-asimi-sn'den kalan); dolarsa COMPLETE YAYIMLANMAZ, çıkış 1 (yalnız test)
  --yanlis-complete      bütün tarama bitişleri alınınca önce YANLIŞ kimlikli COMPLETE, --yanlis-bekle-sn (öntanımlı 6) sonra doğru COMPLETE yayımlar
Akış: N aracın BARIYER_BEKLE durumunu görünce VE kare sonucu konusunda N yayımcıyla eşleşince (keşif gecikmesiyle t0 sonrası ilk sonuçlar kaybolmasın) bir tarama başlatma yayımlar (t0: monotonik ns + simülasyon ns);
N tarama bitişi alınınca VE her aracın [n_ilk, n_son] aralığındaki her numara için tam bir kare sonucu (dört durumdan biri; yer istasyonu alıcı modülü `swarm_gcs.sonuc_alici`) gelince COMPLETE yayımlar (t1);
N aracın TAMAMLANDI durumunu görünce çıkar. Hedef birleştirme koşulu (FR-5) yoktur: "birleştirme yok (M3)" günlüğe yazılır. Kaydı koşu klasöründe `koordinator_deneme.jsonl` (serbest biçimli, test çıktısı; şema değildir). Gazebo model pozları
t0 anında ve her tarama bitişi alındığında kaydedilir (bağımsız doğrulama). Ortam: GZ_PARTITION, GZ_IP, setup/env.sh. Çıkış: 0 tamam, 1 zaman aşımı/hata, 2 kullanım.
"""
import json
import os
import sys
import threading
import time

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_gcs"))

from swarm_vehicle import rota  # noqa: E402
from swarm_vehicle.durum_makinesi import AD  # noqa: E402


class Kayit:
    def __init__(self, yol):
        self.yol, self.kilit, self.gecmis = yol, threading.Lock(), []

    def yaz(self, olay, **kv):
        d = {"mono_ns": time.monotonic_ns(), "olay": olay, **kv}
        if self.yol:
            with self.kilit, open(self.yol, "a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        self.gecmis.append(d)

    def oku(self, olay):
        """Bu süreçte yazılmış kayıtlardan verilen olay adına ait olanlar."""
        return [x for x in self.gecmis if x["olay"] == olay]


def ana(argv):
    n_arac, erken_start, erken_complete, yanlis_complete, yanlis_bekle, zaman_asimi, sonuc_zaman_asimi = 0, False, False, False, 6.0, 1500.0, None
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k == "--erken-scan-start":
            erken_start = True
        elif k == "--erken-complete":
            erken_complete = True
        elif k == "--yanlis-complete":
            yanlis_complete = True
        elif k == "--yanlis-bekle-sn" and a:
            yanlis_bekle = float(a.pop(0))
        elif k == "--zaman-asimi-sn" and a:
            zaman_asimi = float(a.pop(0))
        elif k == "--sonuc-zaman-asimi-sn" and a:
            sonuc_zaman_asimi = float(a.pop(0))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    ham = rota.deney_env_oku()
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()]
    if not 1 <= n_arac <= len(kimlikler):
        print(__doc__, file=sys.stderr)
        return 2
    kimlikler = kimlikler[:n_arac]
    if not os.environ.get("FASTRTPS_DEFAULT_PROFILES_FILE"):
        print("(-) FASTRTPS_DEFAULT_PROFILES_FILE tanımsız: setup/env.sh ile ortamı kurun", file=sys.stderr)
        return 2
    os.environ["SWARM_BIND_ADDR"] = ham["GCS_ADDR"]

    import rclpy
    from gz.msgs10.clock_pb2 import Clock
    from gz.msgs10.pose_v_pb2 import Pose_V
    from gz.transport13 import Node as GzNode
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from swarm_gcs.sonuc_alici import SonucAlici
    from swarm_msgs.msg import Complete, ScanFinished, ScanStart, VehicleState

    klasor = rota.aktif_kosu_klasoru()
    kayit = Kayit(os.path.join(klasor, "koordinator_deneme.jsonl") if klasor else None)
    kilit = threading.Lock()
    sim = {"ns": None}
    pozlar = {}

    def saat(m):
        sim["ns"] = m.sim.sec * 10 ** 9 + m.sim.nsec

    def poz(m):
        with kilit:
            for p in m.pose:
                pozlar[p.name] = (p.position.x, p.position.y, p.position.z)
    gz = GzNode()
    dunya = ham["SIM_WORLD"]
    if not (gz.subscribe(Clock, f"/world/{dunya}/clock", saat) and gz.subscribe(Pose_V, f"/world/{dunya}/pose/info", poz)):
        print("(-) gz aboneliği kurulamadı", file=sys.stderr)
        return 1
    model = ham["SIM_MODEL"].removeprefix("gz_")

    def poz_ozeti():
        with kilit:
            return {str(k): [round(v, 3) for v in pozlar.get(f"{model}_{i}", (None, None, None))] if f"{model}_{i}" in pozlar else None
                    for i, k in enumerate(kimlikler)}

    rclpy.init()
    dugum = Node("mission_coordinator_deneme", namespace="/gcs")
    kimlik = f"G_{time.strftime('%Y%m%d_%H%M%S')}"

    def kontrol(derinlik):
        return QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=derinlik, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    qos_durum = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
    son_durum, bitisler, tamam = {}, {}, set()

    def durum_geldi(m):
        d = AD.get(m.state, f"BILINMEYEN_{m.state}")
        kayit.yaz("durum", arac=int(m.vehicle_id), durum=d, sim_damga_ns=m.sim_stamp.sec * 10 ** 9 + m.sim_stamp.nanosec,
                  ilerleme=[m.mission_item_current, m.mission_item_total], son_kare=int(m.last_frame_number), sim_ns=sim["ns"])
        with kilit:
            son_durum[int(m.vehicle_id)] = d
            if d == "TAMAMLANDI":
                tamam.add(int(m.vehicle_id))

    def bitis_geldi(m):
        with kilit:
            bitisler[int(m.vehicle_id)] = (m.mission_id, int(m.n_first), int(m.n_last))
        kayit.yaz("tarama_bitis", arac=int(m.vehicle_id), mission_id=m.mission_id, n_first=int(m.n_first), n_last=int(m.n_last), sim_ns=sim["ns"], pozlar=poz_ozeti())
    alici = SonucAlici(dugum, ham, kimlikler, os.path.join(klasor, "kayit", "yer_istasyonu_kare.jsonl") if klasor else None,
                       lambda olay, **kv: kayit.yaz("alici_" + olay, **kv))
    dugum.create_timer(1.0, lambda: kayit.yaz("poz", sim_ns=sim["ns"], pozlar=poz_ozeti()))      # her saniye Gazebo model pozları (bağımsız doğrulama)
    dugum.create_subscription(VehicleState, ham["KONU_DURUM"], durum_geldi, qos_durum)
    dugum.create_subscription(ScanFinished, ham["KONU_TARAMA_BITIS"], bitis_geldi, kontrol(10))
    pub_start = dugum.create_publisher(ScanStart, ham["KONU_TARAMA_BASLAT"], kontrol(1))
    from geometry_msgs.msg import Point
    from swarm_msgs.msg import Mission
    from swarm_vehicle import gorev as gorev_mod
    pub_mission = dugum.create_publisher(Mission, ham["KONU_GOREV"], kontrol(10))
    br = gorev_mod.bolge_rota_oku(os.path.join(KOK, "config", "bolge_rota.json"))
    for k_ in kimlikler:                      # araçlar rotayı yüklemeden önce kendi Mission'larını bekler (transient_local: araçlar sonradan başlasa da alır)
        pub_mission.publish(gorev_mod.mesaj_doldur(Mission, Point, gorev_mod.mission_sozlugu(br, k_, kimlik)))
    pub_complete = dugum.create_publisher(Complete, ham["KONU_COMPLETE"], kontrol(1))

    def spin_bekle(kosul, sn, ne):
        sinir = time.monotonic() + sn
        while not kosul():
            if time.monotonic() > sinir:
                kayit.yaz("zaman_asimi", beklenen=ne)
                print(f"(-) zaman aşımı: {ne}", file=sys.stderr)
                return False
            rclpy.spin_once(dugum, timeout_sec=0.05)
        return True

    def bekle_suresi(sn):
        t = time.monotonic() + sn
        while time.monotonic() < t:
            rclpy.spin_once(dugum, timeout_sec=0.05)

    sinir_ns = time.monotonic() + zaman_asimi
    kayit.yaz("basladi", arac_sayisi=n_arac, mission_id=kimlik, erken_scan_start=erken_start, erken_complete=erken_complete, yanlis_complete=yanlis_complete)
    kayit.yaz("birlestirme_yok", ayrinti="hedef birleştirme (FR-5, B15) M3'tedir; COMPLETE koşulunda yoktur")
    try:
        if erken_start:
            m = ScanStart()
            m.mission_id = "ERKEN"
            pub_start.publish(m)
            kayit.yaz("erken_scan_start_yayimlandi", mission_id="ERKEN", sim_ns=sim["ns"], pozlar=poz_ozeti())
        if not spin_bekle(lambda: all(son_durum.get(k) == "BARIYER_BEKLE" for k in kimlikler), sinir_ns - time.monotonic(), "tüm araçlar BARIYER_BEKLE"):
            return 1
        esles_sinir = time.monotonic() + float(ham["KARE_SONUC_ESLESME_SN"])
        if not spin_bekle(lambda: alici.eslesen_yayinci() >= n_arac, esles_sinir - time.monotonic(), f"kare sonucu konusunda {n_arac} yayımcıyla eşleşme"):
            return 1
        kayit.yaz("eslesme_tamam", yayimci=alici.eslesen_yayinci(), anlar=alici.eslesme_anlari)
        kayit.yaz("bariyer_acilis_oncesi", son_durum=dict(son_durum), pozlar=poz_ozeti())
        m = ScanStart()
        m.mission_id = kimlik
        t0_sim, t0_mono = sim["ns"], time.monotonic_ns()
        pozlar_t0 = poz_ozeti()
        pub_start.publish(m)
        kayit.yaz("t0", mission_id=kimlik, sim_ns=t0_sim, t0_mono_ns=t0_mono, pozlar=pozlar_t0)
        print(f"KOORDINATOR t0 mission_id={kimlik} sim_ns={t0_sim}", flush=True)
        if erken_complete:
            bekle_suresi(5.0)
            c = Complete()
            c.mission_id = kimlik
            pub_complete.publish(c)
            kayit.yaz("erken_complete_yayimlandi", mission_id=kimlik, sim_ns=sim["ns"], son_durum=dict(son_durum))
        if not spin_bekle(lambda: len(bitisler) == n_arac, sinir_ns - time.monotonic(), "tüm tarama bitişleri"):
            return 1
        if yanlis_complete:
            c = Complete()
            c.mission_id = "YANLIS_" + kimlik
            pub_complete.publish(c)
            kayit.yaz("yanlis_complete_yayimlandi", mission_id=c.mission_id, sim_ns=sim["ns"], son_durum=dict(son_durum))
            bekle_suresi(yanlis_bekle)
            kayit.yaz("yanlis_complete_sonrasi", son_durum=dict(son_durum))
        kalan = sinir_ns - time.monotonic() if sonuc_zaman_asimi is None else min(sonuc_zaman_asimi, sinir_ns - time.monotonic())
        if not spin_bekle(lambda: alici.defter.hepsi_tamam(), kalan, "bütün araçların bütün kare sonuçları (COMPLETE yayımlanmadı)"):
            kayit.yaz("sonuclar_eksik", sayilar={str(a): v for a, v in alici.defter.sayilar().items()})
            return 1
        kayit.yaz("sonuclar_tamam", sayilar={str(a): v for a, v in alici.defter.sayilar().items()}, son_sonuc_mono_ns=alici.son_sonuc_mono_ns, tamam_mono_ns=alici.defter.tamam_mono_ns,
                  gecersiz=alici.gecersiz, tekrar=len(alici.defter.tekrarlar), bilinmeyen_arac=len(alici.defter.bilinmeyen_arac))
        c = Complete()
        c.mission_id = kimlik
        t1_sim, t1_mono = sim["ns"], time.monotonic_ns()
        pub_complete.publish(c)
        son_bitis_mono = max((x["mono_ns"] for x in kayit.oku("tarama_bitis")), default=None)
        kayit.yaz("t1", mission_id=kimlik, sim_ns=t1_sim, t1_mono_ns=t1_mono, son_tarama_bitis_mono_ns=son_bitis_mono, son_sonuc_mono_ns=alici.son_sonuc_mono_ns,
                  t1_eksi_son_bitis_s=None if son_bitis_mono is None else (t1_mono - son_bitis_mono) / 1e9, t1_eksi_son_sonuc_s=(t1_mono - alici.son_sonuc_mono_ns) / 1e9)
        print(f"KOORDINATOR t1 mission_id={kimlik} sim_ns={t1_sim}", flush=True)
        if not spin_bekle(lambda: len(tamam) == n_arac, sinir_ns - time.monotonic(), "tüm araçlar TAMAMLANDI"):
            return 1
        bekle_suresi(1.0)
        kayit.yaz("bitti", son_durum=dict(son_durum))
        print("KOORDINATOR bitti", flush=True)
        return 0
    finally:
        alici.kapat()
        dugum.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    kod = ana(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(kod)   # gz-transport Node'unun yorumlayıcı kapanışındaki yıkımı "terminate called" ile çekirdek dökümü üretiyordu; kayıtlar yukarıda kapatıldı
