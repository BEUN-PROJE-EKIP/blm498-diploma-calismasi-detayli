"""Sistem yöneticisi: Gazebo + PX4 koşusunu projenin kendi betiğiyle (araclar/kosu.sh) başlatır, durdurur ve izler.

Panel koşuyu kendisi kurmaz; yalnız kosu.sh'ı çağırır ve koşu üst verisini (.generated/kosular/aktif, kosu.json) okur.
  - "Sistemi başlat":  kosu.sh baslat                      (Gazebo + 3 PX4; görev süreçleri yok)
  - "Görevi başlat":   kosu.sh durdur → kosu.sh baslat --yer-istasyonu var --mimari <ucta|merkezi>
    (projenin görev akışı başlangıç bariyeri için araçların yerde, başlangıç konumunda olmasını bekler; bu yüzden temiz bir koşu açılır)
"""
import collections
import json
import os
import re
import subprocess
import threading
import time

from yapilandirma import KOK_DIZIN

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
MIMARILER = ("ucta", "merkezi")


class SistemYoneticisi:
    def __init__(self, yap, partition_degisti, baslatmadan_once):
        self.yap = yap
        self._partition_degisti = partition_degisti   # geri çağrı: (partition | None)
        self._baslatmadan_once = baslatmadan_once     # kosu.sh baslat'tan önce (panelin mavsdk_server'larını kapatır)
        self._k = threading.Lock()
        self.gunluk = collections.deque(maxlen=200)
        self.islem = None            # o an yürüyen işlem adı ("baslat", "durdur", "gorev") ya da None
        self.son_hata = None
        self.kosu = None             # dict: kimlik, partition, mimari, gorev_cikis
        self._son_partition = None
        self.ag_kurulu = None
        self._durdur = threading.Event()
        threading.Thread(target=self._izle, name="sistem-izle", daemon=True).start()

    # ---- günlük ---------------------------------------------------------------------------
    def _yaz(self, satir, tur="bilgi"):
        satir = _ANSI.sub("", satir.rstrip())
        if not satir:
            return
        if satir.startswith("(-)"):
            tur = "hata"
        elif satir.startswith("(+)"):
            tur = "basari"
        elif satir.startswith("(!)"):
            tur = "uyari"
        self.gunluk.append({"t": time.time(), "tur": tur, "metin": satir})

    # ---- koşu durumu ----------------------------------------------------------------------
    def _kosu_oku(self):
        aktif = os.path.join(self.yap.kosu_kok, "aktif")
        try:
            with open(aktif, encoding="utf-8") as f:
                kimlik = f.read().strip()
            kdir = os.path.join(self.yap.kosu_kok, kimlik)
            with open(os.path.join(kdir, "kosu.json"), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return None
        if d.get("bitis") is not None:
            return None
        surecler = {s.get("ad") for s in d.get("surecler", [])}
        gorev_cikis = None
        try:
            with open(os.path.join(kdir, "yer_istasyonu.cikis"), encoding="utf-8") as f:
                gorev_cikis = int(f.read().strip() or "-1")
        except (OSError, ValueError):
            pass
        return {"kimlik": kimlik, "partition": d.get("gz_partition"), "mimari": d.get("mimari_modu", "yok"),
                "gorev_var": "yer_istasyonu" in surecler, "gorev_cikis": gorev_cikis, "dizin": kdir}

    def _izle(self):
        tur = 0
        while not self._durdur.wait(1.0):
            if tur % 5 == 0:
                self.ag_kurulu = self._ag_durumu()
            tur += 1
            k = self._kosu_oku()
            with self._k:
                self.kosu = k
            # Başlatma sürerken koşu dosyası erken yazılır; Gazebo ayağa kalkmadan bağlanmak zararsızdır (abonelik bekler).
            part = k["partition"] if k else None
            if part != self._son_partition:
                self._son_partition = part
                try:
                    self._partition_degisti(part)
                except Exception as e:  # noqa: BLE001 — izleme döngüsü ölmemeli
                    self._yaz(f"(-) Bağlantı yenilenemedi: {e}")

    # ---- komutlar -------------------------------------------------------------------------
    def _calistir(self, *arg):
        if arg and arg[0] == "baslat":
            self._baslatmadan_once()
        self._yaz(f"(i) $ araclar/kosu.sh {' '.join(arg)}")
        p = subprocess.Popen(["bash", self.yap.kosu_betigi, *arg], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, cwd=KOK_DIZIN,
                             start_new_session=True)
        for satir in p.stdout:
            self._yaz(satir)
        return p.wait()

    def _arka_planda(self, ad, is_):
        with self._k:
            if self.islem:
                return False, f"Şu an başka bir işlem sürüyor: {self.islem}"
            self.islem, self.son_hata = ad, None

        def calis():
            try:
                is_()
            except Exception as e:  # noqa: BLE001
                self.son_hata = str(e)
                self._yaz(f"(-) {e}")
            finally:
                with self._k:
                    self.islem = None
        threading.Thread(target=calis, name=f"sistem-{ad}", daemon=True).start()
        return True, "başlatıldı"

    def sistemi_baslat(self):
        def is_():
            if self._kosu_oku():
                self._yaz("(+) Yaşayan koşu bulundu; panel ona bağlanıyor.")
                return
            if self._calistir("baslat") != 0:
                raise RuntimeError("Sistem başlatılamadı (ayrıntı günlükte)")
        return self._arka_planda("baslat", is_)

    def sistemi_durdur(self):
        def is_():
            if not self._kosu_oku():
                self._yaz("(i) Yaşayan koşu yok.")
                return
            if self._calistir("durdur") != 0:
                raise RuntimeError("Durdurma hatayla bitti (ayrıntı günlükte)")
        return self._arka_planda("durdur", is_)

    def gorevi_baslat(self, mimari, havada_arac_var):
        if mimari not in MIMARILER:
            return False, f"Geçersiz mod: {mimari}"
        if havada_arac_var:
            return False, "Görev için araçların yerde olması gerekir; önce toplu iniş yapın."

        def is_():
            if self._kosu_oku():
                self._yaz("(i) Görev için temiz koşu açılıyor: mevcut koşu durduruluyor.")
                if self._calistir("durdur") != 0:
                    raise RuntimeError("Mevcut koşu durdurulamadı")
            if self._calistir("baslat", "--yer-istasyonu", "var", "--mimari", mimari) != 0:
                raise RuntimeError("Görev koşusu başlatılamadı (ayrıntı günlükte)")
        return self._arka_planda("gorev", is_)

    # ---- durum ----------------------------------------------------------------------------
    @staticmethod
    def _ag_durumu():
        """Sürü ağı (setup/60_ag_emulasyon_tc.sh) kurulu mu? Salt okunur denetim; sudo gerekmez."""
        try:
            adr = subprocess.run(["ip", "-o", "addr", "show", "dev", "lo"], capture_output=True, text=True, timeout=3).stdout
            qd = subprocess.run(["tc", "qdisc", "show", "dev", "lo"], capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        return ("10.10.0." in adr) and ("htb" in qd)

    def durum(self):
        with self._k:
            k, islem = self.kosu, self.islem
        if islem:
            ad = {"baslat": "baslatiliyor", "durdur": "durduruluyor", "gorev": "gorev_hazirlaniyor"}[islem]
        elif k and k["gorev_var"]:
            ad = "gorev" if k["gorev_cikis"] is None else "gorev_bitti"
        elif k:
            ad = "hazir"
        else:
            ad = "kapali"
        return {"durum": ad, "islem": islem, "hata": self.son_hata, "kosu": k, "ag_kurulu": self.ag_kurulu,
                "gunluk": list(self.gunluk)[-60:]}

    def kapat(self):
        self._durdur.set()
