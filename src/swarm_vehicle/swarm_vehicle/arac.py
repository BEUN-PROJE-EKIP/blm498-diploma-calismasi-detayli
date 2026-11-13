"""Araç süreci: her İHA için tek bir ROS 2 düğümü (/uav_N): px4_adapter + durum/görev modülü + görev durum makinesi (FR-2, FR-3, FR-4, FR-5 araç tarafı, FR-7).

Kullanım:  python -m swarm_vehicle.arac <araç sırası 1..N>      (rclpy, swarm_msgs ve MAVSDK aynı süreçte: ROS kurulu ve .venv etkin ortam; setup/env.sh)
Akış (GŞÖA 7.4, 7.5): bağlan → kimlik → rota yükle → HAZIR → hazırlık (kalkış + ilk nokta; t0 ÖNCESİ) → BARIYER_BEKLE (yayımı hazır bildirimidir) →
tarama başlatma mesajı (t_s = o anki simülasyon saati) → görevi başlat → TARAMA → son nokta (t_b) → tarama bitişi yayımı → WAIT → eşleşen COMPLETE → TAMAMLANDI.
İş parçacıkları: ana iş parçacığı ROS yürütücüsü; bağdaştırıcının döngü iş parçacığı (MAVSDK asenkron döngüsü, son nokta geri çağrısı burada çalışır);
akış iş parçacığı (engelleyen bağdaştırıcı çağrıları); gz-transport saat geri çağrısı. Durum makinesine erişim tek kilitle serileşir.
Çıkış kodları: 0 TAMAMLANDI; 1 beklenmeyen hata; 2 yapılandırma/kullanım; 3 kimlik doğrulanamadı (HAZIR'a geçilmez); 143 SIGTERM.
Simülasyon zamanı gz-transport'tan doğrudan okunur (ros_gz_bridge yok). 2 Hz durum yayımı duvar saati zamanlayıcısıyla yapılır [varsayım: RTF ≈ 1]; her durum geçişinde ayrıca bir ek ileti yayımlanır (2 Hz'lik akış yarım saniyeden kısa süren durumu — ör. en son bitiren aracın WAIT'i — kaçırmasın).
"""
import json
import os
import signal
import sys
import threading
import time

from . import rota as _rota
from .durum_makinesi import (AD, STATE_BARIYER_BEKLE, STATE_HAZIR, STATE_TAMAMLANDI, STATE_TARAMA, STATE_WAIT, DurumMakinesi)

CIKIS_KIMLIK = 3


class Arac:
    """Düğüm ve akış mantığı. rclpy ve swarm_msgs yalnız `calistir` içinde içe aktarılır (modül rclpy'siz yüklenebilsin)."""

    def __init__(self, arac_no, ham):
        self.ham = ham
        self.arac_no = arac_no
        kimlikler = ham["UAV_SYS_IDS"].split()
        self.arac_kimligi = int(kimlikler[arac_no - 1])
        self.ad_alani = ham["UAV_NAMESPACES"].split()[arac_no - 1]
        self.adres = ham[f"UAV{arac_no}_ADDR"]
        self.dunya = ham["SIM_WORLD"]
        self.kilit = threading.Lock()
        self.sm = None
        self.yayin_acik = False
        self.baslat_olayi = threading.Event()
        self.son_nokta_olayi = threading.Event()
        self.complete_olayi = threading.Event()
        self.dur_olayi = threading.Event()
        self.t_b_ns = None
        self.cikis_kodu = 0
        self._sim_ns = None
        self._sim_kilit = threading.Lock()
        self._log_kilit = threading.Lock()
        self._yay_kilit = threading.Lock()
        self.klasor = _rota.aktif_kosu_klasoru()
        self.log_yol = os.path.join(self.klasor, f"arac_{self.arac_kimligi}.log") if self.klasor else None
        self.kayit_yol = os.path.join(self.klasor, "kayit", f"arac_durum_{self.arac_kimligi}.jsonl") if self.klasor else None
        self.adapter = None

    # --- günlük ---------------------------------------------------------------------------------------------------------------------------
    def log(self, olay, **kv):
        satir = f"{time.strftime('%Y-%m-%dT%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} {time.monotonic_ns()} sim_ns={self.sim_ns()} {olay}" \
            + "".join(f" {k}={v}" for k, v in kv.items())
        if self.log_yol:
            with self._log_kilit, open(self.log_yol, "a", encoding="utf-8") as f:
                f.write(satir + "\n")

    def kayit_yaz(self, d):
        if self.kayit_yol:
            with self._log_kilit, open(self.kayit_yol, "a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    # --- simülasyon saati (gz-transport) ------------------------------------------------------------------------------------------------------
    def sim_ns(self):
        with self._sim_kilit:
            return self._sim_ns

    def _saat_al(self, m):
        with self._sim_kilit:
            self._sim_ns = m.sim.sec * 10 ** 9 + m.sim.nsec

    def saat_baslat(self):
        from gz.msgs10.clock_pb2 import Clock
        from gz.transport13 import Node
        self._gz = Node()
        if not self._gz.subscribe(Clock, f"/world/{self.dunya}/clock", self._saat_al):
            raise RuntimeError(f"/world/{self.dunya}/clock aboneliği kurulamadı (GZ_PARTITION/GZ_IP doğru mu?)")
        sinir = time.monotonic() + float(self.ham["ARAC_SIM_SAAT_SN"])
        while self.sim_ns() is None:
            if time.monotonic() > sinir:
                raise RuntimeError("gz simülasyon saati gelmedi")
            time.sleep(0.05)

    # --- ROS ------------------------------------------------------------------------------------------------------------------------------
    def _zaman(self, ns):
        from builtin_interfaces.msg import Time
        t = Time()
        t.sec, t.nanosec = divmod(max(ns, 0), 10 ** 9)
        return t

    def _yayinla(self):
        if not self.yayin_acik:
            return
        from swarm_msgs.msg import VehicleState
        with self._yay_kilit:                         # zamanlayıcı (ana iş parçacığı) ve geçiş yayımları (akış/yürütücü) birbirine girmesin
            d = self.adapter.durum()
            m = VehicleState()
            with self.kilit:
                m.state = self.sm.durum
            m.vehicle_id = self.arac_kimligi
            m.sim_stamp = self._zaman(self.sim_ns() or 0)
            cur, tot = d["gorev_ilerleme"]
            m.mission_item_current, m.mission_item_total = max(cur, 0), max(tot, 0)
            m.last_frame_number = -1                  # kamera bu sürümde yok
            self.pub_durum.publish(m)

    def _durum_geldi(self, m):
        if m.vehicle_id == self.arac_kimligi:
            return
        self.kayit_yaz({"surum": 1, "tur": "arac_durum_kaydi", "arac_kimligi": self.arac_kimligi, "kaynak_arac_kimligi": int(m.vehicle_id),
                        "durum": AD.get(m.state, f"BILINMEYEN_{m.state}"),
                        "sim_damga_ns": m.sim_stamp.sec * 10 ** 9 + m.sim_stamp.nanosec, "alinma_mono_ns": time.monotonic_ns()})

    def _tarama_baslat_geldi(self, m):
        t_s = self.sim_ns()
        with self.kilit:
            ok = self.sm.tarama_baslat(m.mission_id, t_s)
        if ok:
            self.log("tarama_baslat_alindi", mission_id=m.mission_id, t_s_ns=t_s)
            self._yayinla()                           # geçiş anında ek yayım (TARAMA)
            self.baslat_olayi.set()

    def _complete_geldi(self, m):
        with self.kilit:
            ok = self.sm.complete(m.mission_id)
        if ok:
            self.log("complete_alindi", mission_id=m.mission_id)
            self._yayinla()                           # geçiş anında ek yayım (TAMAMLANDI)
            self.complete_olayi.set()

    def _son_nokta_geri_cagrisi(self, bilgi):
        """Bağdaştırıcının döngü iş parçacığında çalışır: yalnız zamanı yakalar ve akış iş parçacığını uyandırır."""
        self.t_b_ns = self.sim_ns()
        self.log("son_nokta_geri_cagrisi", ilerleme=bilgi["ilerleme"], px4_zaman_us=bilgi["px4_zaman_us"], t_b_ns=self.t_b_ns)
        self.son_nokta_olayi.set()

    # --- akış iş parçacığı ------------------------------------------------------------------------------------------------------------------
    def _bekle(self, olay, ne):
        while not olay.wait(0.2):
            if self.dur_olayi.is_set():
                raise InterruptedError(f"{ne} beklenirken durduruldu")

    def _akis(self):
        from swarm_msgs.msg import ScanFinished
        try:
            if not self.adapter.baglan():
                self.log("hata", neden="kimlik doğrulanamadı; HAZIR'a geçilmez")
                self.cikis_kodu = CIKIS_KIMLIK
                return
            noktalar, bolge = _rota.rota_oku(os.path.join(_rota.KOK, "config", "bolge_rota.json"), self.arac_kimligi)
            y = self.adapter.gorev_yukle(noktalar)
            self.log("rota_yuklendi", bolge=bolge, oge_sayisi=y["oge_sayisi"], sure_s=f"{y['sure_s']:.2f}")
            self.yayin_acik = True                                     # HAZIR: rota PX4'e yüklü, kalkış öncesi
            self.log("durum", durum=AD[STATE_HAZIR])
            h = self.adapter.hazirlik()
            self.log("hazirlik_bitti", kalkis_sure_s=f"{h['kalkis_sure_s']:.1f}", gidis_sure_s=f"{h['gidis_sure_s']:.1f}", sure_s=f"{h['sure_s']:.1f}")
            with self.kilit:
                self.sm.hazir()
            self.log("durum", durum=AD[STATE_BARIYER_BEKLE])
            self._yayinla()                           # geçiş anında ek yayım (BARIYER_BEKLE = hazır bildirimi)
            self._bekle(self.baslat_olayi, "tarama başlatma")
            self.log("durum", durum=AD[STATE_TARAMA])
            b = self.adapter.gorev_baslat()
            self.log("gorev_basladi", sure_s=f"{b['sure_s']:.3f}")
            self._bekle(self.son_nokta_olayi, "son nokta")
            with self.kilit:
                self.sm.son_nokta(self.t_b_ns)
                aralik = self.sm.kare_araligi()
                mission_id, t_s_ns = self.sm.mission_id, self.sm.t_s_ns
            self._yayinla()                           # geçiş anında ek yayım (WAIT): COMPLETE'ten önce de gözlenebilsin
            m = ScanFinished()
            m.mission_id, m.vehicle_id, m.numbering_mode = mission_id, self.arac_kimligi, ScanFinished.NUMBERING_GRID
            m.n_first, m.n_last = aralik
            self.pub_bitis.publish(m)
            self.log("tarama_bitis_yayimlandi", mission_id=mission_id, n_first=aralik[0], n_last=aralik[1], t_s_ns=t_s_ns, t_b_ns=self.t_b_ns)
            self.log("durum", durum=AD[STATE_WAIT])
            self._bekle(self.complete_olayi, "COMPLETE")
            self.log("durum", durum=AD[STATE_TAMAMLANDI])
            self.dur_olayi.wait(float(self.ham["ARAC_KAPANIS_BEKLE_SN"]))   # dinleyiciler son durumu alsın
        except InterruptedError as e:
            self.log("durduruldu", ayrinti=str(e))
        except Exception as e:  # noqa: BLE001
            import traceback
            self.log("hata", neden=repr(e), iz=traceback.format_exc().replace("\n", " | "))
            self.cikis_kodu = 1
        finally:
            self.dur_olayi.set()

    # --- giriş -----------------------------------------------------------------------------------------------------------------------------
    def calistir(self):
        if not os.environ.get("FASTRTPS_DEFAULT_PROFILES_FILE"):
            print("(-) FASTRTPS_DEFAULT_PROFILES_FILE tanımsız: setup/env.sh ile ortamı kurun", file=sys.stderr)
            return 2
        os.environ["SWARM_BIND_ADDR"] = self.adres                    # Fast DDS profili: yalnız bu sürecin sürü adresi
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from swarm_msgs.msg import Complete, ScanFinished, ScanStart, VehicleState
        from . import px4_adapter

        self.sm = DurumMakinesi(gunluk=lambda s: self.log("durum_makinesi", ayrinti=s))
        self.saat_baslat()
        self.adapter = px4_adapter.Px4Adapter(self.arac_no, deney_env=self.ham, son_nokta_geri_cagrisi=self._son_nokta_geri_cagrisi)
        rclpy.init()
        node = Node("vehicle", namespace=self.ad_alani)
        qos_durum = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)

        def kontrol(derinlik):
            return QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=derinlik, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        h = self.ham
        self.pub_durum = node.create_publisher(VehicleState, h["KONU_DURUM"], qos_durum)
        self.pub_bitis = node.create_publisher(ScanFinished, h["KONU_TARAMA_BITIS"], kontrol(10))
        node.create_subscription(VehicleState, h["KONU_DURUM"], self._durum_geldi, qos_durum)
        node.create_subscription(ScanStart, h["KONU_TARAMA_BASLAT"], self._tarama_baslat_geldi, kontrol(1))
        node.create_subscription(Complete, h["KONU_COMPLETE"], self._complete_geldi, kontrol(1))
        node.create_timer(1.0 / float(h["DURUM_YAYIN_HZ"]), self._yayinla)

        def durdur(signum, _):
            self.log("sinyal", numara=signum)
            self.cikis_kodu = 128 + signum
            self.dur_olayi.set()
        signal.signal(signal.SIGTERM, durdur)
        signal.signal(signal.SIGINT, durdur)
        self.log("basladi", arac_kimligi=self.arac_kimligi, ad_alani=self.ad_alani, adres=self.adres, dunya=self.dunya)
        akis = threading.Thread(target=self._akis, name="arac_akis", daemon=True)
        akis.start()
        try:
            while rclpy.ok() and not self.dur_olayi.is_set():
                rclpy.spin_once(node, timeout_sec=0.1)
        finally:
            self.dur_olayi.set()
            akis.join(10)
            self.adapter.kapat()
            node.destroy_node()
            rclpy.shutdown()
            self.log("kapandi", cikis_kodu=self.cikis_kodu)
        return self.cikis_kodu


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 1 or not a[0].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    try:
        ham = _rota.deney_env_oku()
        arac_no = int(a[0])
        if not 1 <= arac_no <= len(ham["UAV_SYS_IDS"].split()):
            print(f"(-) araç sırası 1..{len(ham['UAV_SYS_IDS'].split())} olmalı", file=sys.stderr)
            return 2
        return Arac(arac_no, ham).calistir()
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        print(f"(-) {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
