"""Yer istasyonu kare sonucu alıcısı (B11, uçta mod): ortak kare sonucu konusuna (`KONU_KARE_SONUC`, reliable) ve tarama bitişi konusuna abone olur, sonuç defterini doldurur ve
her geçerli sonuç için sonucun yer istasyonunda KULLANILABİLİR olduğu anı `kare_olay` (`kaynak: yer_istasyonu`, `olay: kullanilabilir`) olarak `kayit/yer_istasyonu_kare.jsonl` dosyasına yazar.

Bu modül görev koordinatörünün (`gorev_koordinatoru`) parçasıdır; test sürücüsü deneme koordinatörü de kullanır. rclpy düğümü dışarıdan verilir (aynı iş parçacığında `spin` edilir): abone geri çağrısı hafiftir
(defter güncellemesi + kuyruğa koyma); diske yazmayı ayrı bir iş parçacığı yapar. Kullanılabilirlik anı = geri çağrının başladığı `CLOCK_MONOTONIC` (iletinin alıcıya teslim edildiği an).
Durum eşlemesi (`sonuc_durumu`): STATUS_DETECTIONS → `sonuc`, STATUS_NO_DETECTION → `tespit_yok`, STATUS_FRAME_NOT_RECEIVED → `kare_alinamadi`, STATUS_PROCESSING_ERROR → `islem_hatasi`
(dört durum ayrıdır; işlem hatası "tespit yok" ya da "kare alınamadı" olarak yazılmaz). STATUS_UNKNOWN ya da ızgara dışı numaralandırma geçersiz sayılır ve sayılır/günlüğe yazılır.
Eşleşme: abonenin eşleşmiş yayımcı sayısı (`get_publisher_count`) izlenir; her artışın anı `eslesme_anlari`'na girer (keşif gecikmesiyle ilk sonuçların kaybolmaması için bariyer bunu bekler).
"""
import json
import queue
import threading
import time

from swarm_vehicle import rota as _rota

from .sonuc_defteri import SonucDefteri

_NS = 10 ** 9


class SonucAlici:
    def __init__(self, dugum, ham, arac_kimlikleri, kayit_yol=None, log=None, dds_sonuc=True, mission_id=None):
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from swarm_msgs.msg import FrameResult, ScanFinished
        self._FR = FrameResult
        self.ham, self.log = ham, log or (lambda *a, **k: None)
        self.hz = int(float(ham["CAM_RATE_HZ"]))
        self.arac_kimlikleri = [int(a) for a in arac_kimlikleri]
        self.defter = SonucDefteri(self.arac_kimlikleri)
        self.mission_id = mission_id                     # geçerli görev kimliği; uyuşmayan ScanFinished deftere yazılmaz (None: denetim yok)
        self.yok_sayilan_bitis = 0
        self.kayit_yol = kayit_yol
        self.gecersiz = 0
        self.eslesme_anlari = []                         # [(mono_ns, eşleşmiş yayımcı sayısı)]
        self._q = queue.SimpleQueue()
        self._dur = threading.Event()
        self._yazici = None
        self.son_sonuc_mono_ns = None                    # kabul edilen son sonucun alım anı
        self.kabul_sayisi = 0
        self._sayac_kilit = threading.Lock()
        self._siniflar = ham["MODEL_SINIFLAR"].split()    # Detection.class_id → sınıf adı (CLASS_HUMAN=0 insan, CLASS_DEBRIS=1 enkaz; sıra MODEL_SINIFLAR ile aynı)
        qa = _rota.kare_sonuc_qos_ayar(ham)
        qos = QoSProfile(history=HistoryPolicy.KEEP_LAST if qa["gecmis"] == "keep_last" else HistoryPolicy.KEEP_ALL, depth=qa["derinlik"], reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL if qa["dayaniklilik"] == "transient_local" else DurabilityPolicy.VOLATILE)
        kontrol = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        # dds_sonuc=False (merkezi mod): kare sonuçları DDS'ten gelmez; merkezde üretilir ve `sonuc_ver` ile teslim edilir. Tarama bitişi aboneliği her iki modda aynıdır.
        self._abone = dugum.create_subscription(FrameResult, ham["KONU_KARE_SONUC"], self._sonuc_geldi, qos) if dds_sonuc else None
        self._bitis_abone = dugum.create_subscription(ScanFinished, ham["KONU_TARAMA_BITIS"], self._bitis_geldi, kontrol)
        self._durum_ad = {FrameResult.STATUS_DETECTIONS: ("tespit", "sonuc"), FrameResult.STATUS_NO_DETECTION: ("tespit_yok", "tespit_yok"),
                          FrameResult.STATUS_PROCESSING_ERROR: ("islem_hatasi", "islem_hatasi"), FrameResult.STATUS_FRAME_NOT_RECEIVED: ("kare_alinamadi", "kare_alinamadi")}
        if kayit_yol:
            self._yazici = threading.Thread(target=self._yaz_dongusu, name="sonuc_alici_yazici", daemon=True)
            self._yazici.start()

    # --- abone geri çağrıları (hafif) -------------------------------------------------------------------------------------------------------
    def _sonuc_geldi(self, m):
        mono = time.monotonic_ns()
        if m.numbering_mode != self._FR.NUMBERING_GRID or m.status not in self._durum_ad:
            self.gecersiz += 1
            self.log("sonuc_gecersiz", arac=int(m.vehicle_id), n=int(m.frame_number), durum=int(m.status), numaralandirma=int(m.numbering_mode))
            return
        if any(not 0 <= d.class_id < len(self._siniflar) for d in m.detections):      # bilinmeyen sınıf numarası: geri çağrı çökmesin; geçersiz iletiyle aynı yol
            self.gecersiz += 1
            self.log("sonuc_gecersiz", arac=int(m.vehicle_id), n=int(m.frame_number), durum=int(m.status), neden="sinif_no_aralik_disi")
            return
        durum, sonuc_durumu = self._durum_ad[m.status]
        tespitler = [{"sinif": self._siniflar[d.class_id], "guven": float(d.confidence), "konum": [float(d.east), float(d.north)] if d.has_position else None} for d in m.detections]
        self._kabul(int(m.vehicle_id), int(m.frame_number), durum, sonuc_durumu, m.sim_stamp.sec * _NS + m.sim_stamp.nanosec, mono, tespitler)

    def sonuc_ver(self, arac, n, durum, sim_damga_ns, tespitler=()):
        """Merkezi mod: merkezde üretilen kare sonucunu (durum: tespit | tespit_yok | islem_hatasi | kare_alinamadi) uçta moddaki ile AYNI yoldan (defter + `kullanilabilir` kaydı) teslim eder.
        `tespitler`: kayıttaki tespitler (`sinif`, `guven`, `konum`); hedef birleştirme girdisi olarak deftere işlenir. Kullanılabilirlik anı = sonucun yer istasyonunda oluştuğu an."""
        mono = time.monotonic_ns()
        sonuc_durumu = {"tespit": "sonuc", "tespit_yok": "tespit_yok", "islem_hatasi": "islem_hatasi", "kare_alinamadi": "kare_alinamadi"}[durum]
        self._kabul(int(arac), int(n), durum, sonuc_durumu, int(sim_damga_ns), mono,
                    [{"sinif": t["sinif"], "guven": float(t["guven"]), "konum": t.get("konum")} for t in tespitler])

    def olay_ekle(self, kayit):
        """Yer istasyonu kare olay kaydını (ör. merkezi modda `aktarim_tamam`) `kullanilabilir` kayıtlarıyla aynı dosyaya yazar (tek yazıcı)."""
        if self.kayit_yol:
            self._q.put(kayit)

    def _kabul(self, arac, n, durum, sonuc_durumu, sim_damga_ns, mono, tespitler=()):
        sonuc = self.defter.ekle(arac, n, durum, mono, tespitler=list(tespitler), sim_damga_ns=int(sim_damga_ns))   # hedef birleştirme girdisi: tespitler + sıralama anahtarı (sim damgası)
        if sonuc != "kabul" and sonuc != "aralik_disi":
            self.log("sonuc_" + sonuc, arac=arac, n=n, durum=durum)
            return
        if sonuc == "aralik_disi":
            self.log("sonuc_aralik_disi", arac=arac, n=n, durum=durum)
            return
        with self._sayac_kilit:                          # merkezi modda araç başına işleme iş parçacıkları aynı anda çağırır
            self.kabul_sayisi += 1
            self.son_sonuc_mono_ns = mono
        self._q.put({"surum": 1, "tur": "kare_olay", "kaynak": "yer_istasyonu", "arac_kimligi": arac, "n": n, "sim_damga_ns": sim_damga_ns,
                     "olay": "kullanilabilir", "mono_ns": mono, "sonuc_durumu": sonuc_durumu})

    def _bitis_geldi(self, m):
        mono = time.monotonic_ns()
        if not self.bitis_kabul(m.mission_id, int(m.vehicle_id)):
            return
        if self.defter.aralik_ayarla(int(m.vehicle_id), int(m.n_first), int(m.n_last), mono):
            self.log("tarama_bitis_alindi", arac=int(m.vehicle_id), n_ilk=int(m.n_first), n_son=int(m.n_last))

    def bitis_kabul(self, mission_id, arac):
        """Tarama bitişi geçerli görev kimliğiyle uyuşuyor mu (koordinatör `gorev_mantik.bitis_geldi` ile aynı kural). Uyuşmazsa yok sayılır, neden günlüğe yazılır."""
        if self.mission_id is not None and mission_id != self.mission_id:
            self.yok_sayilan_bitis += 1
            self.log("tarama_bitis_yok_sayildi", neden="mission_id_uyusmuyor", arac=int(arac), alinan=mission_id, beklenen=self.mission_id)
            return False
        return True

    # --- eşleşme --------------------------------------------------------------------------------------------------------------------------------
    def eslesen_yayinci(self):
        """Abonenin eşleştiği yayımcı sayısı; her artış `eslesme_anlari`'na (mono_ns, sayı) olarak girer."""
        n = self._abone.get_publisher_count() if self._abone is not None else 0
        if not self.eslesme_anlari or self.eslesme_anlari[-1][1] != n:
            self.eslesme_anlari.append((time.monotonic_ns(), n))
            self.log("eslesme_degisti", yayimci=n)
        return n

    # --- yazma ----------------------------------------------------------------------------------------------------------------------------------
    def _yaz_dongusu(self):
        with open(self.kayit_yol, "a", encoding="utf-8") as f:
            while True:
                try:
                    d = self._q.get(timeout=0.2)
                except queue.Empty:
                    if self._dur.is_set():
                        return
                    f.flush()
                    continue
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def kapat(self):
        self._dur.set()
        if self._yazici is not None:
            self._yazici.join(5)
