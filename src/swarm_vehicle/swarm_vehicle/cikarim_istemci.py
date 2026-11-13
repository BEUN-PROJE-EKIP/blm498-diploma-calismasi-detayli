"""Çıkarım işçisinin araç süreci tarafındaki istemcisi (B9): işçiyi ALT SÜREÇ olarak başlatır, IP kullanmayan kanaldan kare gönderir/sonuç alır, işçi ölümünü ve zaman aşımını yönetir.
Yalnız standart kitaplık (rclpy/gz/torch içe aktarılmaz); işçi ayrı bir yorumlayıcıda çalışır.

Alt süreç yöntemi: `subprocess.Popen` + `socket.socketpair(AF_UNIX)` (`multiprocessing` değil). Gerekçe: işçi taze bir yorumlayıcıda başlar; araç sürecinin rclpy/DDS/gz-transport durumu, iş parçacıkları ve
MAVSDK bağlantıları işçiye MİRAS KALMAZ (fork bunları kopyalardı; `spawn` da ana modülü yeniden içe aktarırdı). Kanala yalnız tek soket ucu devredilir (`pass_fds`); işçi ağ soketi açmaz.
Kare başına tek iş: kare gönderilir, sonuç beklenir (uçuştaki kare sayısı 1); sıradaki kareler araç tarafı kuyruğunda bekler (kare atılmaz).
İşçi ölümü/zaman aşımı kuralı [varsayım: belgede işçi ölümü kuralı yok]: o kare işlem hatası olur; işçi ISCI_YENIDEN_BASLAT_MAKS kez yeniden başlatılır (yeni işçi hazır olana dek sıradaki kareler BEKLER,
atılmaz; yeniden başlatılan işçi de ısınmayı yapar). Sınır aşılırsa ya da model yüklenemezse kalan kareler işlem hatası olur ("tespit yok" yazılmaz).
"""
import os
import socket
import subprocess
import sys
import threading

from . import cikarim_yardimci as Y


class IsciIstemcisi:
    def __init__(self, ham, arac_no, arac_kimligi, klasor, log, enjeksiyon_metni=None, arka_uc=None, kare_zaman_asimi_sn=None):
        self.ham, self.arac_no, self.arac_kimligi, self.klasor, self.log = ham, arac_no, arac_kimligi, klasor, log
        self.arka_uc = arka_uc
        self.hazir_sn = float(ham["ISCI_HAZIR_SN"])
        self.zaman_asimi_sn = float(kare_zaman_asimi_sn if kare_zaman_asimi_sn is not None else ham["ISCI_KARE_ZAMAN_ASIMI_SN"])
        self.yeniden_maks = int(ham["ISCI_YENIDEN_BASLAT_MAKS"])
        self.enj = Y.IsciEnjeksiyon(enjeksiyon_metni if enjeksiyon_metni is not None else os.environ.get("ISCI_ENJEKSIYON", ""))
        self.n_ilk = None                    # enjeksiyon belirteçleri (+k) için; araç süreci tarama başlayınca verir
        self._k = threading.RLock()
        self.p = None
        self.sock = None
        self.bilgi = None                    # son `hazir` iletisi
        self.kalici_hata = None              # model yüklenemedi / yeniden başlatma sınırı aşıldı
        self.yeniden = 0                     # yapılan yeniden başlatma sayısı
        self.baslatma = 0                    # toplam başlatma sayısı (ilk dahil)
        self.pidler = []
        self.cpu_aciklama = None
        self._tampon = bytearray(int(ham["CAM_WIDTH"]) * int(ham["CAM_HEIGHT"]) * 3)

    # --- alt süreç --------------------------------------------------------------------------------------------------------------------------
    def _cpu_secimi(self):
        if self.ham.get("ISCI_CPU_SABITLE", "0") != "1":
            return [], "sabitleme kapalı (ISCI_CPU_SABITLE=0)"
        try:
            kumeler = Y.cpu_cekirdek_kumeleri()
            return Y.cpu_ata(self.arac_no, kumeler, int(self.ham["ISCI_MANTIKSAL_CPU"]), izinli=os.sched_getaffinity(0))
        except OSError as e:
            return [], f"CPU topolojisi okunamadı: {e}"

    def baslat(self):
        """İşçiyi başlatır (hazır olmasını BEKLEMEZ). Zaten çalışıyorsa bir şey yapmaz."""
        with self._k:
            if self.p is not None and self.p.poll() is None:
                return
            ana, cocuk = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            cpu, aciklama = self._cpu_secimi()
            self.cpu_aciklama = aciklama
            komut = [sys.executable, "-m", "swarm_vehicle.cikarim_isci", "--fd", str(cocuk.fileno()), "--arac-kimligi", str(self.arac_kimligi), "--arac-sirasi", str(self.arac_no)]
            if cpu:
                komut += ["--cpu", ",".join(map(str, cpu))]
            if self.arka_uc:
                komut += ["--arka-uc", self.arka_uc]
            if self.klasor:
                komut += ["--kayit-klasoru", self.klasor]
            cikti = open(os.path.join(self.klasor, f"cikarim_isci_{self.arac_kimligi}.log"), "a", encoding="utf-8") if self.klasor else subprocess.DEVNULL
            try:
                self.p = subprocess.Popen(komut, pass_fds=[cocuk.fileno()], stdin=subprocess.DEVNULL, stdout=cikti, stderr=cikti)
            finally:
                cocuk.close()
                if cikti is not subprocess.DEVNULL:
                    cikti.close()
            self.sock = ana
            self.bilgi = None
            self.baslatma += 1
            self.pidler.append(self.p.pid)
            self.log("isci_baslatildi", pid=self.p.pid, baslatma=self.baslatma, cpu_eslemesi=aciklama.replace(" ", "_"), arka_uc=self.arka_uc or self.ham["ISCI_ARKA_UC"])

    def _oldur(self):
        p, s = self.p, self.sock
        self.p, self.sock, self.bilgi = None, None, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass
        if p is not None and p.poll() is None:
            p.kill()
        if p is not None:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                pass

    def _ilk_ileti(self, sure_sn):
        """`hazir` iletisini bekler → True (hazır) / False. Başarısızlıkta nedeni `self.kalici_hata`/yeniden başlatma ile işler."""
        self.sock.settimeout(max(sure_sn, 0.1))
        try:
            baslik, _ = Y.cerceve_oku(self.sock)
        except socket.timeout:
            self.log("isci_hazir_zaman_asimi", sure_s=f"{sure_sn:.0f}")
            return False, f"işçi {sure_sn:.0f} sn içinde hazır olmadı"
        except (Y.KanalKapandi, OSError, ValueError) as e:
            kod = self.p.poll() if self.p else None
            return False, f"işçi hazır olmadan kapandı (çıkış kodu {kod}; {e!r})"
        if baslik.get("tur") == "hazir_degil":
            self.kalici_hata = f"işçi modeli yükleyemedi/ısınamadı: {baslik.get('hata')}"
            return False, self.kalici_hata
        if baslik.get("tur") != "hazir":
            return False, f"beklenmeyen ilk ileti: {baslik.get('tur')}"
        self.bilgi = baslik
        self.log("isci_hazir", pid=baslik["pid"], arka_uc=baslik["arka_uc"], model=baslik["model"], cihaz=str(baslik["cihaz"]).replace(" ", "_"), yukleme_s=baslik["yukleme_s"],
                 isinma_s=baslik["isinma_s"], isinma_kare=len(baslik["isinma_ms"]), cpu=",".join(map(str, baslik["cpu"])), rclpy_yuklu=baslik["rclpy_yuklu"],
                 uc_uca=str(baslik["uc_uca"]).replace(" ", ""))
        return True, None

    def hazir_bekle(self, sure_sn=None):
        """İşçi hazır olana dek bekler (ısınma dahil) → hazır iletisi (sözlük) ya da None (başarısız; neden `kalici_hata`/günlük)."""
        with self._k:
            sure_sn = self.hazir_sn if sure_sn is None else sure_sn
            if self.bilgi is not None:
                return self.bilgi
            if self.p is None:
                self.baslat()
            ok, neden = self._ilk_ileti(sure_sn)
            if ok:
                return self.bilgi
            self.kalici_hata = self.kalici_hata or neden
            self.log("isci_hazir_degil", neden=str(neden).replace(" ", "_"))
            self._oldur()
            return None

    # --- kare işleme ------------------------------------------------------------------------------------------------------------------------
    def _hata_yaniti(self, n, damga_ns, neden):
        return {"tur": "sonuc", "n": n, "damga_ns": damga_ns, "durum": "hata", "hata": neden, "tespitler": [], "basi_ns": None, "sonu_ns": None}

    def _is_basarisiz(self, neden):
        """Çalışan işçiyi sonlandırır; yeniden başlatma hakkı varsa yeni işçiyi başlatır (hazır olmasını sıradaki `isle` bekler)."""
        self._oldur()
        if self.yeniden < self.yeniden_maks:
            self.yeniden += 1
            self.log("isci_yeniden_baslatiliyor", neden=neden.replace(" ", "_"), yeniden=f"{self.yeniden}/{self.yeniden_maks}")
            self.baslat()
        else:
            self.kalici_hata = f"işçi yeniden başlatma sınırı aşıldı ({self.yeniden_maks}); son neden: {neden}"
            self.log("isci_yeniden_baslatma_siniri", neden=neden.replace(" ", "_"))

    def isle(self, n, damga_ns, veri, w, h):
        """Bir kareyi işçide işler (engelleyen). Dönen: işçi yanıtı sözlüğü; hata durumunda {"durum": "hata", "hata": ...}. Her çağrı için tam bir yanıt döner (istisna fırlatmaz)."""
        with self._k:
            while self.bilgi is None:
                if self.kalici_hata:
                    return self._hata_yaniti(n, damga_ns, self.kalici_hata)
                if self.p is None:
                    self.baslat()
                ok, neden = self._ilk_ileti(self.hazir_sn)
                if ok:
                    break
                if self.kalici_hata:
                    self._oldur()
                    return self._hata_yaniti(n, damga_ns, self.kalici_hata)
                self._is_basarisiz(neden)                           # hazır olamayan işçi de yeniden başlatma hakkından yer
            karar = self.enj.karar(n, self.n_ilk)
            baslik = {"tur": "kare", "n": n, "damga_ns": damga_ns, "w": w, "h": h, "bicim": "rgb8"}
            if karar:
                baslik["enj"] = karar
                self.log("isci_enjeksiyon", n=n, tur=karar)
            try:
                self.sock.settimeout(self.zaman_asimi_sn)
                Y.cerceve_yaz(self.sock, baslik, veri)
                yanit, _ = Y.cerceve_oku(self.sock, self._tampon)
            except socket.timeout:
                neden = f"işçi zaman aşımı (kare {self.zaman_asimi_sn:g} sn içinde işlenmedi)"
                self._is_basarisiz(neden)
                return self._hata_yaniti(n, damga_ns, neden)
            except (Y.KanalKapandi, OSError, ValueError) as e:
                kod = None
                if self.p is not None:
                    try:
                        kod = self.p.wait(5)
                    except subprocess.TimeoutExpired:
                        pass
                neden = f"işçi süreci öldü (çıkış kodu {kod}; {type(e).__name__})"
                self._is_basarisiz(neden)
                return self._hata_yaniti(n, damga_ns, neden)
            if yanit.get("tur") != "sonuc" or yanit.get("n") != n:
                neden = f"işçi yanıtı beklenmeyen kareye ait (beklenen {n}, gelen {yanit.get('n')})"
                self._is_basarisiz(neden)
                return self._hata_yaniti(n, damga_ns, neden)
            return yanit

    # --- kapanış ----------------------------------------------------------------------------------------------------------------------------
    def kapat(self, bekle_sn=15):
        with self._k:
            if self.sock is not None:
                try:
                    self.sock.settimeout(2)
                    Y.cerceve_yaz(self.sock, {"tur": "dur"})
                except OSError:
                    pass
            p = self.p
            if p is not None:
                try:
                    p.wait(bekle_sn)
                except subprocess.TimeoutExpired:
                    self.log("isci_kapanmadi_olduruluyor", pid=p.pid)
                    p.kill()
                    p.wait(10)
                self.log("isci_kapandi", pid=p.pid, cikis_kodu=p.returncode)
            self._oldur()

    def ozet(self):
        return {"baslatma": self.baslatma, "yeniden": self.yeniden, "pidler": list(self.pidler), "kalici_hata": self.kalici_hata}
