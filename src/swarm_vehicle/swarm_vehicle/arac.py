"""Araç süreci: her İHA için tek bir ROS 2 düğümü (/uav_N): px4_adapter + durum/görev modülü + görev durum makinesi (FR-2, FR-3, FR-4, FR-5 araç tarafı, FR-7).

Kullanım:  python -m swarm_vehicle.arac <araç sırası 1..N>      (rclpy, swarm_msgs ve MAVSDK aynı süreçte: ROS kurulu ve .venv etkin ortam; setup/env.sh)
Akış (GŞÖA 7.4, 7.5): bağlan → kimlik → kendi Mission'ını bekle ve yerel bolge_rota.json ile birebir karşılaştır (uyuşmazlık = açık hata, yükleme yok) → rotayı Mission'dan yükle → HAZIR → hazırlık (kalkış + ilk nokta; t0 ÖNCESİ; çıkarım işçisi bu sırada başlar, modeli yükler ve ısınır) →
çıkarım işçisi hazır → BARIYER_BEKLE (yayımı hazır bildirimidir; işçi hazır olmadan geçilmez) →
tarama başlatma mesajı (t_s = o anki simülasyon saati) → görevi başlat → TARAMA → son nokta (t_b) → tarama bitişi yayımı → WAIT → eşleşen COMPLETE → TAMAMLANDI.
İş parçacıkları: ana iş parçacığı ROS yürütücüsü; bağdaştırıcının döngü iş parçacığı (MAVSDK asenkron döngüsü, son nokta geri çağrısı burada çalışır);
akış iş parçacığı (engelleyen bağdaştırıcı çağrıları); gz-transport saat geri çağrısı. Durum makinesine erişim tek kilitle serileşir.
Çıkış kodları: 0 TAMAMLANDI; 1 beklenmeyen hata; 2 yapılandırma/kullanım; 3 kimlik doğrulanamadı (HAZIR'a geçilmez); 4 Mission yerel dosyayla uyuşmuyor (yükleme yok); 5 Mission zamanında gelmedi; 143 SIGTERM.
Çıkarım işçisi bu sürecin ALT SÜRECİDİR (cikarim_istemci.py; IP kullanmayan AF_UNIX kanal); kabul edilen her görev karesi işçiye gider, her görev numarası için tam bir kare sonucu
(`swarm_msgs/FrameResult`) üretilir, yerel kayda (`kayit/kare_sonuc_<araç>.jsonl`) yazılır, `kare_sonucu_kancasi`na verilir ve uçta modda ortak konudan (`KONU_KARE_SONUC`, reliable) yer istasyonuna yayımlanır (`sonuc_yayin.py`; yayım kare işleme iş parçacığını bloke etmez; kapanışta bütün iletilerin onayı beklenir).
Merkezi mod (`MIMARI_MODU=merkezi`, kosu.sh --mimari merkezi): araçta çıkarım işçisi BAŞLATILMAZ ve `FrameResult` yayımlanmaz; kamera alıcısının görev kareleri ve "kare alınamadı" kayıtları aynı sırayla poz sorgusundan geçip
(`goruntu_kanali.IletiHazirlayici`) araç başına TCP görüntü kanalının gönderim kuyruğuna girer (`goruntu_kanali.Gonderici`; kaynak adres `UAVn_ADDR`, hedef `GCS_ADDR:MERKEZI_TCP_PORT_TABAN+k-1`). Kanal bariyerden ÖNCE kurulur
(hazırlıktan sonra bağlı değilse süreç açık hata ile çıkar); TAMAMLANDI'dan sonra kuyruk boşalır ve kanal kapanır.
Simülasyon zamanı gz-transport'tan doğrudan okunur (ros_gz_bridge yok); gz-transport `GZ_IP=127.0.0.1` ile kilitlenir (başka değer verilmişse süreç açık hata ile çıkar). 2 Hz durum yayımı duvar saati zamanlayıcısıyla yapılır [varsayım: RTF ≈ 1]; her durum geçişinde ayrıca bir ek ileti yayımlanır (2 Hz'lik akış yarım saniyeden kısa süren durumu — ör. en son bitiren aracın WAIT'i — kaçırmasın).
"""
import json
import os
import signal
import sys
import threading
import time

from . import gorev as _gorev
from . import rota as _rota
from .cikarim_istemci import IsciIstemcisi
from .kamera_alici import n_ilk_hesapla
from .kamera_alici_gz import KameraAliciGz
from .kare_isleyici import KareIsleyici
from .konum_hesap import KonumHesaplayici
from .sonuc_yayin import SonucYayinci
from .durum_makinesi import (AD, STATE_BARIYER_BEKLE, STATE_HAZIR, STATE_TAMAMLANDI, STATE_TARAMA, STATE_WAIT, DurumMakinesi)

CIKIS_KIMLIK = 3
CIKIS_MISSION_UYUSMUYOR = 4        # alınan Mission yerel bolge_rota.json ile birebir eşit değil: yükleme yok
CIKIS_MISSION_ZAMAN = 5             # GOREV_BEKLE_SN içinde kendi Mission'ı gelmedi
CIKIS_TEST = 70                     # YALNIZ test: ARAC_TEST_CIKIS ile bilerek (kapanış adımı olmadan) çıkış
GZ_IP_YEREL = "127.0.0.1"


def gz_ip_ayarla(ortam):
    """gz-transport'un yalnız yerel döngü arayüzünde kalmasını güvenceye alır [belge: 127.0.0.1 üzerinden gz-transport]: GZ_IP tanımsızsa 127.0.0.1 yapar; başka bir değerse ValueError."""
    mevcut = ortam.get("GZ_IP")
    if mevcut and mevcut != GZ_IP_YEREL:
        raise ValueError(f"GZ_IP={mevcut!r}: gz-transport yalnız {GZ_IP_YEREL} üzerinde çalışabilir (görüntü trafiği sürü ağına girmemeli); değişkeni kaldırın ya da {GZ_IP_YEREL} yapın")
    ortam["GZ_IP"] = GZ_IP_YEREL


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
        self._log_kilit = threading.RLock()            # sinyal işleyicisi ana iş parçacığı log() içindeyken de log() çağırabilir (aynı iş parçacığı: yeniden girilebilir)
        self._node = self._akis_ip = self._rclpy = None
        self._yay_kilit = threading.Lock()
        self.klasor = _rota.aktif_kosu_klasoru()
        self.log_yol = os.path.join(self.klasor, f"arac_{self.arac_kimligi}.log") if self.klasor else None
        self.kayit_yol = os.path.join(self.klasor, "kayit", f"arac_durum_{self.arac_kimligi}.jsonl") if self.klasor else None
        self.adapter = None
        self.kamera = None
        self.kamera_yol = os.path.join(self.klasor, "kayit", f"kamera_alici_{self.arac_kimligi}.jsonl") if self.klasor else None
        self.sonuc_yol = os.path.join(self.klasor, "kayit", f"kare_sonuc_{self.arac_kimligi}.jsonl") if self.klasor else None
        self.poz_yol = os.path.join(self.klasor, "kayit", f"kare_poz_{self.arac_kimligi}.jsonl") if self.klasor else None
        self.yayinci_yol = os.path.join(self.klasor, "kayit", f"arac_sureci_{self.arac_kimligi}.jsonl") if self.klasor else None
        self.yayinci = None
        self.pub_sonuc = None
        self.mimari = os.environ.get("MIMARI_MODU", "ucta")
        self.merkezi = self.mimari == "merkezi"
        self.kanal_olay_yol = self.yayinci_yol                           # merkezi mod: `gonderim_kuyrugu` ve `gonderim` kare olayları (kaynak arac_sureci)
        self.kuyruk_yol = os.path.join(self.klasor, "kayit", f"gonderim_kuyrugu_{self.arac_kimligi}.jsonl") if self.klasor else None
        self.sha_yol = os.path.join(self.klasor, "kayit", f"merkezi_sha_{self.arac_kimligi}.jsonl") if self.klasor and os.environ.get("MERKEZI_SHA") == "1" else None   # YALNIZ test: gönderilen görüntü baytlarının SHA-256'sı
        self.kanal = self.hazirlayici = self.kuyruk = None
        self._yazicilar = []
        self.atanan_gorev = None                      # alınan ve doğrulanan Mission sözlüğü (gorev.py)
        self.mission_olayi = threading.Event()
        self.pub_onay = None
        self._tarama_mono = None
        self._kapat_sonrasi_sn = self._temiz_kapat_bekle_sn()
        self._test_cikis = self._test_cikis_ayristir(os.environ.get("ARAC_TEST_CIKIS", ""), self.arac_kimligi)
        self._sus = self._sus_ayristir(os.environ.get("ARAC_DURUM_SUS", ""), self.arac_kimligi)   # YALNIZ test: (başlangıç_sn, süre_sn) tarama başından; durum yayımı bu pencerede susar
        self.isci = None
        self.isleyici = None
        self.kare_sonucu_kancasi = None          # isteğe bağlı yerel kanca: callable(FrameResult); DDS yayımı ayrıdır (self.yayinci)
        self.kare_sonucu_mesaj_sayisi = 0
        self._FrameResult = self._Detection = None

    @staticmethod
    def _test_cikis_ayristir(metin, arac_kimligi):
        """YALNIZ test: ARAC_TEST_CIKIS=`<araç kimliği>:bariyer` (araç BARIYER_BEKLE'ye geçince, t0'dan önce) ya da `<araç kimliği>:tarama:<sn>` (tarama başladıktan sn gerçek saniye sonra) → o araç süreci kapanış adımı
        olmadan (çökme gibi) `os._exit(70)` ile çıkar; yer istasyonu COMPLETE'ten önceki araç çıkışını gecikmesiz açık hatayla sonlandırmalı. Boşsa ya da başka aracın anahtarıysa None (öntanımlı kapalı)."""
        parca = metin.strip().split(":")
        if not metin.strip():
            return None
        if int(parca[0]) != arac_kimligi:
            return None
        if len(parca) == 2 and parca[1] == "bariyer":
            return ("bariyer", 0.0)
        if len(parca) == 3 and parca[1] == "tarama":
            return ("tarama", float(parca[2]))
        raise ValueError(f"ARAC_TEST_CIKIS: '<araç>:bariyer' ya da '<araç>:tarama:<sn>' bekleniyordu (verilen: {metin!r})")

    def _test_cikis_yap(self):
        self.log("test_cikis", evre=self._test_cikis[0], cikis_kodu=CIKIS_TEST)
        _cik(CIKIS_TEST)

    @staticmethod
    def _sus_ayristir(metin, arac_kimligi):
        """ARAC_DURUM_SUS: `<başlangıç_sn>:<süre_sn>` (bütün araçlar) ya da `<araç>:<başlangıç_sn>:<süre_sn>` (yalnız o araç); boşsa kapalı."""
        parca = metin.strip().split(":")
        if not metin.strip():
            return None
        if len(parca) == 3:
            return (float(parca[1]), float(parca[2])) if int(parca[0]) == arac_kimligi else None
        return float(parca[0]), float(parca[1])

    def _poz_durdur_kurala(self):
        """YALNIZ test: POZ_TEST_DURDUR=`<başlangıç_sn>:<süre_sn>` (bütün araçlar) ya da `<araç>:<başlangıç_sn>:<süre_sn>`; tarama başından (gerçek sn) itibaren bu pencerede gelen telemetri
        örnekleri tampona EKLENMEZ (aralık sınırı aşımı enjeksiyonu). Boşsa None (öntanımlı kapalı). Telemetri kaydı yine yazılır (`kabul: false`, `red_neden: enjeksiyon`)."""
        pencere = self._sus_ayristir(os.environ.get("POZ_TEST_DURDUR", ""), self.arac_kimligi)
        if pencere is None:
            return None
        return lambda: self._tarama_mono is not None and pencere[0] <= time.monotonic() - self._tarama_mono < pencere[0] + pencere[1]

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
        if self._sus is not None and self._tarama_mono is not None and self._sus[0] <= time.monotonic() - self._tarama_mono < self._sus[0] + self._sus[1]:
            return                                    # test anahtarı ARAC_DURUM_SUS: durum yayımı bu pencerede susar (izleme bayat uyarısını sınamak için); akış değişmez
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
            m.last_frame_number = self.kamera.son_numara()    # son numaralanan görev karesi; yoksa -1
            self.pub_durum.publish(m)

    def _kare_sonucu_uret(self, kayit):
        """Kare sonucu kaydından `FrameResult` iletisini oluşturur, yerel kancaya verir ve DDS yayım kuyruğuna koyar."""
        from . import kare_sonuc as ks
        m = ks.mesaj_olustur(kayit, self._FrameResult, self._Detection, self._zaman)
        self.kare_sonucu_mesaj_sayisi += 1
        if self.kare_sonucu_kancasi is not None:
            self.kare_sonucu_kancasi(m)
        if self.yayinci is not None:
            self.yayinci.ver(m, kayit["n"])               # kuyruğa koyar, bloke etmez; DDS yayımı ayrı iş parçacığında

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
            self._tarama_mono = time.monotonic()
        if ok:
            if self.isci is not None:
                self.isci.n_ilk = n_ilk_hesapla(t_s, self.kamera.hz)   # işçi enjeksiyonu belirteçleri (+k) için; kareler kuyruğa girmeden önce
                if self.yayinci is not None:
                    self.yayinci.n_ilk = self.isci.n_ilk            # yayım enjeksiyonu belirteçleri (+k) için
            self.kamera.tarama_basladi(t_s)           # görev karesi kabulü t_s'den başlar
            self.log("tarama_baslat_alindi", mission_id=m.mission_id, t_s_ns=t_s)
            self._yayinla()                           # geçiş anında ek yayım (TARAMA)
            self.baslat_olayi.set()

    def _mission_geldi(self, m):
        """Ortak Mission konusu: yalnız bu aracın Mission'ı alınır (ilk geçerli olan; ikincisi yok sayılır ve günlüğe yazılır)."""
        if int(m.vehicle_id) != self.arac_kimligi:
            return
        if self.atanan_gorev is not None:
            self.log("mission_tekrar_yok_sayildi", mission_id=m.mission_id)
            return
        self.atanan_gorev = _gorev.mesajdan_sozluk(m)
        self.log("mission_alindi", mission_id=m.mission_id, bolge=m.region_id, nokta=len(m.waypoints))
        self.mission_olayi.set()

    def _komut_geldi(self, m):
        """Komut yolu iskeleti: komut px4_adapter.komut_isle'ye iletilir (PX4'e yazmaz); onay (vehicle_id = bu araç, aynı sıra) ortak onay konusuna yayımlanır."""
        ack, neden = self.adapter.komut_isle(m.vehicle_id, m.sequence)
        a = self._Command()
        a.vehicle_id, a.sequence, a.ack_state = self.arac_kimligi, m.sequence, ack
        self.pub_onay.publish(a)
        self.log("komut_alindi", vehicle_id=int(m.vehicle_id), sequence=int(m.sequence), ack="ACK_REJECTED" if ack == 3 else ack, neden=neden)

    def _mission_bekle(self, sure_sn):
        """Bu aracın Mission'ı gelene dek bekler (GOREV_BEKLE_SN). Dönen: Mission sözlüğü ya da None (zaman aşımı)."""
        sinir = time.monotonic() + sure_sn
        while not self.mission_olayi.wait(0.2):
            if self.dur_olayi.is_set():
                raise InterruptedError("Mission beklenirken durduruldu")
            if time.monotonic() > sinir:
                return None
        return self.atanan_gorev

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
        self.kamera.tarama_bitti(self.t_b_ns)         # yeni görev karesi kabulü durur; n_son belirlenir (zaman damgası hemen alınır)
        self.log("son_nokta_geri_cagrisi", ilerleme=bilgi["ilerleme"], px4_zaman_us=bilgi["px4_zaman_us"], t_b_ns=self.t_b_ns)
        self.son_nokta_olayi.set()

    # --- akış iş parçacığı ------------------------------------------------------------------------------------------------------------------
    def _bekle(self, olay, ne):
        while not olay.wait(0.2):
            if self.dur_olayi.is_set():
                raise InterruptedError(f"{ne} beklenirken durduruldu")
            if self.merkezi and self.kanal.durdu_mu():                  # merkezi mod: kanal hatayla (ya da bilerek) durduysa COMPLETE hiç gelmez; açık hata
                if self._kapat_sonrasi_sn > 0:
                    self.log("test_kanal_kapandi_bekleniyor", sn=self._kapat_sonrasi_sn)
                    self.dur_olayi.wait(self._kapat_sonrasi_sn)
                raise RuntimeError(f"{ne} beklenirken görüntü kanalı durdu (hata: {self.kanal.hata or 'yok'}); koşu tamamlanamaz")

    def _akis(self):
        from swarm_msgs.msg import ScanFinished
        try:
            if not self.adapter.baglan():
                self.log("hata", neden="kimlik doğrulanamadı; HAZIR'a geçilmez")
                self.cikis_kodu = CIKIS_KIMLIK
                return
            yerel_yol = os.path.join(_rota.KOK, "config", "bolge_rota.json")
            self.log("mission_bekleniyor", sure_sn=self.ham["GOREV_BEKLE_SN"])
            mission = self._mission_bekle(float(self.ham["GOREV_BEKLE_SN"]))
            if mission is None:
                self.log("hata", neden=f"kendi Mission'ı {self.ham['GOREV_BEKLE_SN']} sn içinde gelmedi; rota yüklenmedi")
                self.cikis_kodu = CIKIS_MISSION_ZAMAN
                return
            fark = _gorev.mission_karsilastir(mission, _gorev.bolge_rota_oku(yerel_yol), self.arac_kimligi)
            if fark:
                self.log("mission_uyusmuyor", mission_id=mission["mission_id"], fark="; ".join(fark).replace(" ", "_"))
                self.log("hata", neden="Mission yerel bolge_rota.json ile uyuşmuyor; rota yüklenmedi (açık hata)")
                self.cikis_kodu = CIKIS_MISSION_UYUSMUYOR
                return
            self.log("mission_dogrulandi", mission_id=mission["mission_id"], bolge=mission["region_id"], yerel_sha256=_gorev.dosya_sha256(yerel_yol)[:16])
            with self.kilit:
                self.sm.beklenen_mission_id = mission["mission_id"]       # farklı kimlikli tarama başlatma yok sayılır
            noktalar, bolge = _gorev.mission_noktalari(mission), mission["region_id"]
            y = self.adapter.gorev_yukle(noktalar)
            self.log("rota_yuklendi", bolge=bolge, oge_sayisi=y["oge_sayisi"], sure_s=f"{y['sure_s']:.2f}")
            self.yayin_acik = True                                     # HAZIR: rota PX4'e yüklü, kalkış öncesi
            self.log("durum", durum=AD[STATE_HAZIR])
            h = self.adapter.hazirlik()
            self.log("hazirlik_bitti", kalkis_sure_s=f"{h['kalkis_sure_s']:.1f}", gidis_sure_s=f"{h['gidis_sure_s']:.1f}", donus_sure_s=f"{h['donus_sure_s']:.1f}", sure_s=f"{h['sure_s']:.1f}")
            if self.merkezi:
                if not self.kanal.bagli_bekle(float(self.ham["MERKEZI_BAGLAN_SN"])):          # kanal bariyerden ÖNCE bağlı olmalı
                    self.log("hata", neden=f"görüntü kanalı bağlı değil: {self.kanal.hata}")
                    self.cikis_kodu = 1
                    return
                self.log("goruntu_kanali_hazir", baglanti_mono_ns=self.kanal.baglanti_mono_ns)
            else:
                t_isci = time.monotonic()
                bilgi = self.isci.hazir_bekle()                         # model yükleme + ısınma hazırlık evresindedir; işçi hazır olmadan BARIYER_BEKLE'ye geçilmez
                if bilgi is None:
                    self.log("hata", neden=f"çıkarım işçisi hazır olamadı: {self.isci.kalici_hata}")
                    self.cikis_kodu = 1
                    return
                self.log("isci_hazir_bekleme_bitti", ek_bekleme_s=f"{time.monotonic() - t_isci:.1f}", isinma_s=bilgi["isinma_s"], yukleme_s=bilgi["yukleme_s"], rclpy_yuklu=bilgi["rclpy_yuklu"])
            with self.kilit:
                self.sm.hazir()
            self.log("durum", durum=AD[STATE_BARIYER_BEKLE])
            self._yayinla()                           # geçiş anında ek yayım (BARIYER_BEKLE = hazır bildirimi)
            if self._test_cikis and self._test_cikis[0] == "bariyer":
                self._test_cikis_yap()
            self._bekle(self.baslat_olayi, "tarama başlatma")
            self.log("durum", durum=AD[STATE_TARAMA])
            b = self.adapter.gorev_baslat()
            self.log("gorev_basladi", sure_s=f"{b['sure_s']:.3f}")
            zamanlayici = None
            if self._test_cikis and self._test_cikis[0] == "tarama":
                zamanlayici = threading.Timer(self._test_cikis[1], self._test_cikis_yap)
                zamanlayici.daemon = True
                zamanlayici.start()
            self._bekle(self.son_nokta_olayi, "son nokta")
            if zamanlayici is not None:
                zamanlayici.cancel()                  # test çıkışı tarama bittikten sonra tetiklenmesin
            with self.kilit:
                self.sm.son_nokta(self.t_b_ns)
                aralik = self.sm.kare_araligi()
                mission_id, t_s_ns = self.sm.mission_id, self.sm.t_s_ns
            self._yayinla()                           # geçiş anında ek yayım (WAIT): COMPLETE'ten önce de gözlenebilsin
            if aralik != (self.kamera.alici.n_ilk, self.kamera.alici.n_son):
                raise RuntimeError(f"kare aralığı uyuşmuyor: durum makinesi {aralik}, alıcı {(self.kamera.alici.n_ilk, self.kamera.alici.n_son)}")
            m = ScanFinished()
            m.mission_id, m.vehicle_id, m.numbering_mode = mission_id, self.arac_kimligi, ScanFinished.NUMBERING_GRID
            m.n_first, m.n_last = aralik
            self.pub_bitis.publish(m)
            self.log("tarama_bitis_yayimlandi", mission_id=mission_id, n_first=aralik[0], n_last=aralik[1], t_s_ns=t_s_ns, t_b_ns=self.t_b_ns)
            self.log("durum", durum=AD[STATE_WAIT])
            self._bekle(self.complete_olayi, "COMPLETE")
            self.log("durum", durum=AD[STATE_TAMAMLANDI])
            if self.merkezi:
                self._kanali_bosalt(aralik)                                # COMPLETE yalnız merkezdeki son sonuçtan sonra gelir; yine de kuyruk ve kanal kapanmadan önce boşalır
            else:
                self._sonuclari_tamamla(aralik)                            # her görev numarası için tam bir kare sonucu
                self.yayinci.kapat(float(self.ham["KARE_SONUC_ACK_SN"]))   # yayım kuyruğu boşalır; bütün FrameResult iletileri abonelerce onaylanana dek (üst sınır) beklenir
            self.dur_olayi.wait(float(self.ham["ARAC_KAPANIS_BEKLE_SN"]))   # dinleyiciler son durumu alsın
        except InterruptedError as e:
            self.log("durduruldu", ayrinti=str(e))
        except Exception as e:  # noqa: BLE001
            import traceback
            self.log("hata", neden=repr(e), iz=traceback.format_exc().replace("\n", " | "))
            self.cikis_kodu = 1
        finally:
            self.dur_olayi.set()

    def _kanali_bosalt(self, aralik):
        """Merkezi mod kapanışı: kamera iç kuyruğu ve gönderim kuyruğu boşalır, kanal kapanır; her koşunun gerçek üretim hızı, kare sayısı ve kuyruk durumu günlüğe yazılır."""
        from .goruntu_kanali import rss_zirve_mib
        n_ilk, n_son = aralik
        t0 = time.monotonic()
        zamaninda, zorla, _ = self.isleyici_beklenen_tamamla(n_ilk, n_son)
        bos = self.kanal.bosalt_ve_kapat(float(self.ham["MERKEZI_BOSALT_SN"]))
        u = self.hazirlayici
        pb = sorted(u.poz_bekleme_ms)
        self.log("merkezi_ozet", beklenen=n_son - n_ilk + 1, goruntu=u.goruntu_sayisi, kare_alinamadi=u.kayip_sayisi, uretilen=u.goruntu_sayisi + u.kayip_sayisi, gonderilen=self.kanal.gonderilen,
                 kuyruk_bosaldi=bos, bekleme_s=f"{time.monotonic() - t0:.1f}", zorla_kayip=",".join(map(str, zorla)) or "yok", kamera_kuyruk_maks=self.kamera.kuyruk_maks,
                 gercek_uretim_hz=f"{self._uretim_hizi():.3f}", kuyruk_maks_ileti=self.kuyruk.maks_ileti, kuyruk_maks_bayt=self.kuyruk.maks_bayt, rss_zirve_mib=rss_zirve_mib())
        if pb:
            self.log("poz_ozeti", adet=len(pb), gecersiz=",".join(f"{k}:{v}" for k, v in sorted(u.poz_gecersiz.items())) or "yok", bekleme_medyan_ms=f"{pb[len(pb) // 2]:.2f}",
                     bekleme_p95_ms=f"{pb[min(len(pb) - 1, int(0.95 * len(pb)))]:.2f}", bekleme_en_buyuk_ms=f"{pb[-1]:.2f}", **{f"tampon_{k}": v for k, v in self.adapter.poz.sayaclar().items()})
        self._yazicilari_kapat()
        if not bos:
            raise RuntimeError(f"gönderim kuyruğu boşalmadı: {self.kuyruk.derinlik()} (kanal hatası: {self.kanal.hata})")

    def _yazicilari_kapat(self):
        """Bütün kayıt yazıcılarını (kanal/kuyruk/poz/SHA yazıcıları ve uçta moddaki poz yazıcısı) idempotent kapatır; `satir_yazici_ozet` her yazıcı için yalnız ilk kapanışta yazılır
        (başarılı yolda kapanış `_kanali_bosalt`'ta, hata/sinyal yolunda `calistir` finally'sinde olur)."""
        yazicilar = list(self._yazicilar)
        if self.isleyici is not None and self.isleyici.poz_yazici is not None:
            yazicilar.append(self.isleyici.poz_yazici)
        for y in yazicilar:
            if y.kapat():
                self.log("satir_yazici_ozet", yol=os.path.basename(y.yol or "-"), **y.ozet())

    def isleyici_beklenen_tamamla(self, n_ilk, n_son):
        """Kamera alıcısı kapanış karesi gelmediyse sondaki kayıpları şimdi yazdırır ve iç kuyruğun boşalmasını (kısa) bekler. Dönen: (zamanında, zorla kayıp numaraları, None)."""
        zorla = list(self.kamera.kapanis_kapat_zorla() or [])
        sinir = time.monotonic() + float(self.ham["MERKEZI_BOSALT_SN"])
        while self.kamera.tuketilen_son < n_son and time.monotonic() < sinir:
            time.sleep(0.05)
        return self.kamera.tuketilen_son >= n_son, zorla, None

    def _uretim_hizi(self):
        """Gerçek (duvar saati) üretim hızı: gz kamera geri çağrılarının (alınan − 1) / (son − ilk alım anı) değeri, kare/sn (RTF ≈ 1 ise CAM_RATE_HZ'ye yakın)."""
        k = self.kamera
        if k.ilk_alim_mono_ns is None or k.son_alim_mono_ns <= k.ilk_alim_mono_ns or k.alinan < 2:
            return 0.0
        return (k.alinan - 1) * 1e9 / (k.son_alim_mono_ns - k.ilk_alim_mono_ns)

    def _sonuclari_tamamla(self, aralik):
        """COMPLETE sonrası: kuyruk boşalıp [n_ilk, n_son] için bütün kare sonuçları gelene dek bekler (ISCI_KAPANIS_BEKLE_SN); süre dolarsa kalan numaralar için kayıp/işlem hatası yazar."""
        n_ilk, n_son = aralik
        t0 = time.monotonic()
        zamaninda, zorla, hatali = self.isleyici.kapanis_tamamla(n_ilk, n_son, float(self.ham["ISCI_KAPANIS_BEKLE_SN"]), self.kamera.kapanis_kapat_zorla)
        s = self.isleyici.defter.durum_sayilari()
        self.log("kare_sonuclari_tamam", zamaninda=zamaninda, bekleme_s=f"{time.monotonic() - t0:.1f}", beklenen=n_son - n_ilk + 1, yazilan=len(self.isleyici.defter.kayitlar),
                 tespit=s["tespit"], tespit_yok=s["tespit_yok"], islem_hatasi=s["islem_hatasi"], kare_alinamadi=s["kare_alinamadi"], cift_sonuc=self.isleyici.defter.cift_sayisi,
                 zorla_kayip=",".join(map(str, zorla)) or "yok", kapanista_islem_hatasi=",".join(map(str, hatali)) or "yok", mesaj=self.kare_sonucu_mesaj_sayisi,
                 atilan_sinif_disi=self.isleyici.atilan_toplam, kuyruk_maks=self.kamera.kuyruk_maks, isci_baslatma=self.isci.baslatma, isci_yeniden=self.isci.yeniden)
        pb = sorted(self.isleyici.poz_bekleme_ms)
        if pb:
            self.log("poz_ozeti", adet=len(pb), gecersiz=",".join(f"{k}:{v}" for k, v in sorted(self.isleyici.poz_gecersiz.items())) or "yok",
                     bekleme_medyan_ms=f"{pb[len(pb) // 2]:.2f}", bekleme_p95_ms=f"{pb[min(len(pb) - 1, int(0.95 * len(pb)))]:.2f}", bekleme_en_buyuk_ms=f"{pb[-1]:.2f}",
                     **{f"tampon_{k}": v for k, v in self.adapter.poz.sayaclar().items()})
        self.log("konum_ozeti", **self.isleyici.konum_ozeti())
        sm = sorted(self.isleyici.sureler_ms)
        if sm:
            self.log("cikarim_sureleri", adet=len(sm), medyan_ms=f"{sm[len(sm) // 2]:.2f}", p99_ms=f"{sm[min(len(sm) - 1, int(0.99 * len(sm)))]:.2f}", en_buyuk_ms=f"{sm[-1]:.2f}")

    @staticmethod
    def _temiz_kapat_n():
        """YALNIZ test: MERKEZI_ARAC_ENJEKSIYON=`kanal_kapat=<n>` → n numaralı iletinin gönderiminden sonra kanal bilerek temiz kapatılır (yer istasyonu açık hata vermeli). Varsayılan kapalı."""
        m = os.environ.get("MERKEZI_ARAC_ENJEKSIYON", "").strip()
        if not m:
            return None
        anahtar, _, deger = m.partition("=")
        if anahtar != "kanal_kapat":
            raise ValueError(f"MERKEZI_ARAC_ENJEKSIYON: bilinmeyen anahtar '{anahtar}'")
        return int(deger.partition(":")[0])

    @staticmethod
    def _temiz_kapat_bekle_sn():
        """YALNIZ test: `kanal_kapat=<n>:<sn>` → kanal kapandıktan sonra araç süreci açık hatayla çıkmadan önce `sn` saniye daha yaşar (yer istasyonunda kanal hatasının süreç çıkışından ayırt edilmesi için). Varsayılan 0."""
        deger = os.environ.get("MERKEZI_ARAC_ENJEKSIYON", "").partition("=")[2]
        return float(deger.partition(":")[2] or 0)

    def _merkezi_kur(self):
        """Merkezi mod bileşenleri: gönderim kuyruğu, göndericisi, ileti hazırlayıcısı ve kamera alıcısı (tüketici = ileti hazırlayıcısı; kare alınamadı da aynı kuyruktan, sırasıyla)."""
        from .goruntu_kanali import GonderimKuyrugu, Gonderici, IletiHazirlayici
        from .poz_tamponu import SatirYazici
        h = self.ham
        kal = _rota.kalibrasyon_kimligi_oku()
        yaz = lambda yol: SatirYazici(yol, self.log) if yol else None  # noqa: E731
        olay_y, kuyruk_y, poz_y, sha_y = yaz(self.kanal_olay_yol), yaz(self.kuyruk_yol), yaz(self.poz_yol), yaz(self.sha_yol)
        self._yazicilar = [y for y in (olay_y, kuyruk_y, poz_y, sha_y) if y is not None]
        self.kuyruk = GonderimKuyrugu()
        hz = int(float(h["CAM_RATE_HZ"]))
        self.kanal = Gonderici(self.arac_kimligi, hz, self.adres, (h["GCS_ADDR"], int(h["MERKEZI_TCP_PORT_TABAN"]) + self.arac_no - 1), self.kuyruk, self.log,
                               olay_yaz=olay_y.ver if olay_y else None, kuyruk_yaz=kuyruk_y.ver if kuyruk_y else None, kuyruk_kayit_sn=float(h["MERKEZI_KUYRUK_KAYIT_SN"]),
                               temiz_kapat_n=self._temiz_kapat_n())
        self.hazirlayici = IletiHazirlayici(self.arac_kimligi, hz, self.adapter.poz, kal, self.kuyruk, self.log, olay_yaz=olay_y.ver if olay_y else None,
                                    poz_yaz=poz_y.ver if poz_y else None, sha_yaz=sha_y.ver if sha_y else None,
                                    hata_bildir=self.kanal.hata_ver)
        self.kamera = KameraAliciGz(h, self.arac_no, self.arac_kimligi, self.kamera_yol, self.log, tuketici=self.hazirlayici.goruntu, kayip_ver=self.hazirlayici.kayip, kayip_sirali=True)
        self.log("merkezi_mod", kalibrasyon_kimligi=kal, hedef=f"{h['GCS_ADDR']}:{int(h['MERKEZI_TCP_PORT_TABAN']) + self.arac_no - 1}", kaynak=self.adres, sha_kaydi=bool(self.sha_yol))

    # --- giriş -----------------------------------------------------------------------------------------------------------------------------
    def calistir(self):
        """Kurulum dahil her yol `_kapanis` ile biter (kurulum hatasında da yazıcılar, adaptör, işçi alt süreci kapanır; kapanış adımları None-güvenlidir)."""
        if not os.environ.get("FASTRTPS_DEFAULT_PROFILES_FILE"):
            print("(-) FASTRTPS_DEFAULT_PROFILES_FILE tanımsız: setup/env.sh ile ortamı kurun", file=sys.stderr)
            return 2
        try:
            return self._calistir_govde()
        except BaseException:
            if not self.cikis_kodu:
                self.cikis_kodu = 1                                        # `kapandi` satırı hatayı yansıtsın; çıkış kodunu üst katman belirler
            raise
        finally:
            self._kapanis()

    def _kapanis(self):
        """Kapanış adımları tek tek korunur: biri hata verirse (`kapanis_adimi_hatasi`) sonrakiler yine çalışır, çıkış kodu değişmez. `_yazicilari_kapat` her zaman çalışır; `kapandi` en sonda koşulsuz."""
        self.dur_olayi.set()
        adimlar = (("akis", lambda: self._akis_ip.join(10) if self._akis_ip is not None else None),
                   ("adapter", lambda: self.adapter.kapat() if self.adapter is not None else None),
                   ("kamera", lambda: self.kamera.kapat() if self.kamera is not None else None),
                   ("isci", lambda: self.isci.kapat() if self.isci is not None else None),
                   ("kanal", lambda: self.kanal.bosalt_ve_kapat(0.1) if self.kanal is not None else None),     # idempotent: başarılı yolda zaten kapandıysa günlük üretmez
                   ("yazicilar", self._yazicilari_kapat),                                                      # kanal kapandıktan sonra: kuyruktaki satırlar yazılır ve sayılır
                   ("node", lambda: self._node.destroy_node() if self._node is not None else None),
                   ("rclpy", lambda: self._rclpy.shutdown() if self._rclpy is not None and self._rclpy.ok() else None))
        for ad, adim in adimlar:
            try:
                adim()
            except Exception as e:  # noqa: BLE001
                try:
                    self.log("kapanis_adimi_hatasi", adim=ad, hata=repr(e))
                except Exception:  # noqa: BLE001
                    pass
        self.log("kapandi", cikis_kodu=self.cikis_kodu)

    def _calistir_govde(self):
        os.environ["SWARM_BIND_ADDR"] = self.adres                    # Fast DDS profili: yalnız bu sürecin sürü adresi
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from swarm_msgs.msg import Command, Complete, Mission, ScanFinished, ScanStart, VehicleState
        from . import px4_adapter
        self._rclpy = rclpy
        self._Command = Command

        from swarm_msgs.msg import Detection, FrameResult
        self._FrameResult, self._Detection = FrameResult, Detection
        self.sm = DurumMakinesi(gunluk=lambda s: self.log("durum_makinesi", ayrinti=s), hz=float(self.ham["CAM_RATE_HZ"]))
        self.saat_baslat()
        if not self.merkezi:
            self.isci = IsciIstemcisi(self.ham, self.arac_no, self.arac_kimligi, self.klasor, self.log)
        self.adapter = px4_adapter.Px4Adapter(self.arac_no, deney_env=self.ham, son_nokta_geri_cagrisi=self._son_nokta_geri_cagrisi)
        self.adapter.poz_durdur = self._poz_durdur_kurala()            # YALNIZ test (POZ_TEST_DURDUR); öntanımlı None
        if self.merkezi:
            self._merkezi_kur()
        else:
            self.isleyici = KareIsleyici(self.ham, self.arac_kimligi, self.isci, self.sonuc_yol, self.log, self._kare_sonucu_uret, poz_tamponu=self.adapter.poz, poz_yol=self.poz_yol,
                                         konum_hesaplayici=KonumHesaplayici.yapilandirmadan(self.ham, self.arac_kimligi))
            self.kamera = KameraAliciGz(self.ham, self.arac_no, self.arac_kimligi, self.kamera_yol, self.log, tuketici=self.isleyici.goruntu, kayip_ver=self.isleyici.kayip)
            self.log("isci_enjeksiyon_durumu", durum=self.isci.enj.ozet())
            self.isci.baslat()                                         # alt süreç: model yükleme ve ısınma hazırlık evresiyle paralel sürer
        self.kamera.baslat()
        if self.merkezi:
            self.kanal.baslat(float(self.ham["MERKEZI_BAGLAN_SN"]))     # bağlanma hazırlık evresiyle paralel sürer; bariyerden önce bağlı olmalı
        rclpy.init()
        node = self._node = Node("vehicle", namespace=self.ad_alani)
        qos_durum = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)

        def kontrol(derinlik):
            return QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=derinlik, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        h = self.ham
        self.pub_durum = node.create_publisher(VehicleState, h["KONU_DURUM"], qos_durum)
        self.pub_bitis = node.create_publisher(ScanFinished, h["KONU_TARAMA_BITIS"], kontrol(10))
        if not self.merkezi:
            qa = _rota.kare_sonuc_qos_ayar(h)
            qos_sonuc = QoSProfile(history=HistoryPolicy.KEEP_LAST if qa["gecmis"] == "keep_last" else HistoryPolicy.KEEP_ALL, depth=qa["derinlik"], reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.TRANSIENT_LOCAL if qa["dayaniklilik"] == "transient_local" else DurabilityPolicy.VOLATILE)
            self.pub_sonuc = node.create_publisher(FrameResult, h["KONU_KARE_SONUC"], qos_sonuc)
            from rclpy.duration import Duration
            self.yayinci = SonucYayinci(self.arac_kimligi, self.kamera.hz, self.pub_sonuc.publish, self.yayinci_yol, self.log,
                                        onay_bekle=lambda sn: self.pub_sonuc.wait_for_all_acked(Duration(seconds=sn)))
            self.yayinci.baslat()
        qos_gorev = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        qos_komut = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
        qos_onay = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=20, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.pub_onay = node.create_publisher(Command, h["KONU_KOMUT_ONAY"], qos_onay)
        node.create_subscription(Mission, h["KONU_GOREV"], self._mission_geldi, qos_gorev)
        node.create_subscription(Command, h["KONU_KOMUT"], self._komut_geldi, qos_komut)
        node.create_subscription(VehicleState, h["KONU_DURUM"], self._durum_geldi, qos_durum)
        node.create_subscription(ScanStart, h["KONU_TARAMA_BASLAT"], self._tarama_baslat_geldi, kontrol(1))
        node.create_subscription(Complete, h["KONU_COMPLETE"], self._complete_geldi, kontrol(1))
        node.create_timer(1.0 / float(h["DURUM_YAYIN_HZ"]), self._yayinla)
        self._es_son = {}

        def eslesme_izle():
            """Yayımcıların eşleşmiş abone sayısı: her değişim günlüğe yazılır (eşleşme kaybı/yeniden eşleşme gözlemi)."""
            for ad, pub in (("durum", self.pub_durum), ("kare_sonuc", self.pub_sonuc), ("tarama_bitis", self.pub_bitis)):
                if pub is None:
                    continue
                n = pub.get_subscription_count()
                if self._es_son.get(ad) != n:
                    self._es_son[ad] = n
                    self.log("eslesme_degisti", kaynak=ad, sayi=n)
        node.create_timer(0.5, eslesme_izle)

        def durdur(signum, _):
            self.log("sinyal", numara=signum)
            self.cikis_kodu = 128 + signum
            self.dur_olayi.set()
        signal.signal(signal.SIGTERM, durdur)
        signal.signal(signal.SIGINT, durdur)
        self.log("basladi", arac_kimligi=self.arac_kimligi, ad_alani=self.ad_alani, adres=self.adres, dunya=self.dunya, gz_ip=os.environ.get("GZ_IP"), mimari=self.mimari, isci_enjeksiyon=self.isci.enj.ozet() if self.isci is not None else "yok")
        self._akis_ip = threading.Thread(target=self._akis, name="arac_akis", daemon=True)
        self._akis_ip.start()
        while rclpy.ok() and not self.dur_olayi.is_set():
            rclpy.spin_once(node, timeout_sec=0.1)
        return self.cikis_kodu


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 1 or not a[0].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    try:
        gz_ip_ayarla(os.environ)                                      # gz-transport içe aktarılmadan ÖNCE: yalnız 127.0.0.1
        ham = _rota.deney_env_oku()
        arac_no = int(a[0])
        if not 1 <= arac_no <= len(ham["UAV_SYS_IDS"].split()):
            print(f"(-) araç sırası 1..{len(ham['UAV_SYS_IDS'].split())} olmalı", file=sys.stderr)
            return 2
        mimari = os.environ.get("MIMARI_MODU", "ucta")
        if mimari not in ham["KOSU_MIMARILER"].split():
            print(f"(-) MIMARI_MODU={mimari!r}: {ham['KOSU_MIMARILER'].split()} değerlerinden biri olmalı", file=sys.stderr)
            return 2
        return Arac(arac_no, ham).calistir()
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        print(f"(-) {type(e).__name__}: {e}", file=sys.stderr)
        return 2


def _cik(kod):
    """Kapat → boşalt → `os._exit` (yer istasyonu `gorev_koordinatoru.main` ile aynı sıra). Kayıt yazıcıları ve günlük `calistir()` içinde kapanmış olur; burada yalnız akışlar boşaltılır.
    Neden: gz-transport pybind11 yıkıcısı yorumlayıcı kapanışında `dec_ref() PyGILState_Check()` hatasıyla çöküp çıkış kodunu 134 yapabiliyor."""
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.flush()
        except (OSError, ValueError):
            pass
    os._exit(kod)


def giris():
    """Süreç giriş noktası (`python -m swarm_vehicle.arac` ve `ros2 run` / `arac` komutu): `main()` sonucu ile `os._exit`; kaçan istisna önce günlüğe, sonra çıkış 1."""
    try:
        kod = main()
    except BaseException:  # noqa: BLE001  (kaçan istisna: önce günlüğe, sonra çıkış 1)
        import traceback
        print("(-) beklenmeyen istisna: " + traceback.format_exc().replace("\n", " | "), file=sys.stderr)
        kod = 1
    _cik(kod if isinstance(kod, int) else 1)


if __name__ == "__main__":
    giris()
