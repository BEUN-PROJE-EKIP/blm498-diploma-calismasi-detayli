"""Merkezi mod araç tarafı (FR-14, FR-15): araç başına TCP görüntü kanalının gönderim kuyruğu, göndericisi ve ileti hazırlayıcısı. rclpy/MAVSDK/gz içe aktarılmaz (birim testli).

Akış: kamera alıcısının kuyruk tüketicisi → `IletiHazirlayici` (poz sorgusu [bekleme dahil, kuyruğa girişten ÖNCE ve kayda geçer] → ileti kodlama) → gönderim kuyruğu (`DiskKuyrugu`, FIFO) → `Gonderici` iş parçacığı → TCP.
- Gönderim kuyruğu: araç başına FIFO; HİÇBİR kare atılmaz. Soket dolunca gönderici bekler (geri basınç), kuyruk büyür [belge: TCP geri basıncı nedeniyle üretilmiş kareler atılmaz, kuyrukta korunur].
  Kuyruk disk destekli `DiskKuyrugu`dur (disk_kuyrugu.py; `koy`/`bak`/`cikar`/`derinlik`/`kapat`; öğe = (n, tür, ileti baytları), sayaç baytı = ileti baytı): kapasite taşması (yazma hatası ya da boş alan alt sınırın altı)
  kare atlamaz, açık hata verir: `kuyruk_tasmasi` günlük/kaydı, kanal hatayla durur (koşu `yarida_kaldi`), sonraki kareler kuyruğa alınmaz ve `dusen` olarak SAYILIR (sessiz kayıp yok).
- "Kare alınamadı" iletileri görüntü iletileriyle AYNI kuyruğa girer ve sırasını korur (kuyruğa giriş sırası numara sırasıdır: kamera alıcısı her iki türü aynı tüketici iş parçacığına sıralı verir).
- Bağlantı: kaynak adres (`UAVn_ADDR`) bağlanır (bind), hedef `GCS_ADDR:port`; ölçülen sürü ağı (lo üzerindeki htb) üzerinden gider, yerel döngü adresi kullanılmaz. Yeniden bağlanma YOKTUR [varsayım]:
  bağlantı kopar ya da yazma hatası olursa gönderici durur, hata `hata` alanında ve günlükte açıktır, kuyruktaki iletiler sayılır (sessiz kayıp yok); koşu tamamlanamaz.
- Kayıtlar: her ileti için `kare_olay` `gonderim_kuyrugu` (kuyruğa giriş anı) ve `gonderim` (son bayt sokete yazıldı) [kaynak `arac_sureci`]; kuyruk derinliği periyodik `kuyruk_durumu` kaydı. `kuyruga_giris` (aşama damgası) araç tarafında kamera alıcısının disk kuyruğuna yazıldığında kamera alıcısı tarafından yazılır; `gonderim_kuyrugu` bu gönderim kuyruğuna girişin tanı kaydıdır.
"""
import hashlib
import socket
import threading
import time

from . import goruntu_ileti as gi
from ..kamera.disk_kuyrugu import KuyrukTasmasi
from ..ucus import poz_tamponu as pz

_NS = 10 ** 9


def rss_zirve_mib():
    """Sürecin ana bellek zirvesi (VmHWM, MiB); okunamazsa None."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for s in f:
                if s.startswith("VmHWM:"):
                    return round(int(s.split()[1]) / 1024, 1)
    except (OSError, ValueError):
        pass
    return None


def olay(arac_kimligi, n, damga_ns, ad, mono_ns=None):
    """`kare_olay` kaydı (kaynak `arac_sureci`); mono_ns verilmezse şimdiki an."""
    return {"surum": 1, "tur": "kare_olay", "kaynak": "arac_sureci", "arac_kimligi": int(arac_kimligi), "n": int(n), "sim_damga_ns": int(damga_ns), "olay": ad, "mono_ns": time.monotonic_ns() if mono_ns is None else int(mono_ns)}


class Gonderici:
    """TCP göndericisi (tek iş parçacığı; kuyruğu sırayla boşaltır). `olay_yaz(sözlük)` ve `kuyruk_yaz(sözlük)` bloke etmeyen yazıcılardır (SatirYazici.ver)."""

    def __init__(self, arac_kimligi, hz, kaynak_adres, hedef, kuyruk, log, olay_yaz=None, kuyruk_yaz=None, kuyruk_kayit_sn=1.0, ongonderim_bekle=None, temiz_kapat_n=None):
        self.arac_kimligi, self.hz, self.kaynak_adres, self.hedef = int(arac_kimligi), int(hz), kaynak_adres, hedef
        self.kuyruk, self.log, self._olay_yaz, self._kuyruk_yaz = kuyruk, log, olay_yaz, kuyruk_yaz
        self.kuyruk_kayit_sn = float(kuyruk_kayit_sn)
        self.sock = None
        self.bagli = threading.Event()
        self.hata = None                       # açık hata metni (bağlanamadı / kopma / yazma hatası); doluysa gönderici durmuştur
        self.baglanti_mono_ns = None
        self.gonderilen = self.gonderilen_bayt = 0
        self._dur = threading.Event()
        self._bitti = threading.Event()
        self._ipler = []
        self._son_gonderilen_n = None
        self._kayit_kilit = threading.Lock()   # kuyruk durumu kaydı: anlık görüntü + mono_ns + yazıcıya verme tek kilit altında (sıra geriye gitmez)
        self._kapanis_kilit = threading.Lock()
        self._kapanis_sonucu = None            # bosalt_ve_kapat ilk çağrının sonucu (ikinci çağrı günlük/kayıt üretmez)
        self.temiz_kapat_n = temiz_kapat_n     # YALNIZ test: bu numaranın gönderiminden sonra kanal bilerek TEMİZ kapatılır (hata işaretlenmez); yer istasyonu açık hata vermelidir

    def hata_ver(self, metin):
        """Kanalı açık hatayla durdurur (ileti hazırlama hatası gibi gönderimin dışındaki nedenler): hata kaydedilir, gönderim durur, bağlantı kapatılır (yer istasyonu eksik defteri açık hatayla görür). Tekrar çağrı ilk hatayı korur."""
        if self.hata is None:
            self.hata = metin
            self.log("goruntu_kanali_hata", neden=str(metin).replace(" ", "_"))
        self._dur.set()
        self._soketi_kapat()

    def durdu_mu(self):
        """Gönderici iş parçacığı sona erdi mi (hata, bilerek kapatma ya da kapanış)."""
        return self._bitti.is_set()

    def _soketi_kapat(self):
        s = self.sock
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    # --- bağlanma ---------------------------------------------------------------------------------------------------------------------------
    def baslat(self, baglan_sn):
        """Bağlantı iş parçacığını başlatır (en çok baglan_sn sn dener); bağlanınca gönderim döngüsü aynı iş parçacığında sürer."""
        self._ipler = [threading.Thread(target=self._calis, args=(float(baglan_sn),), name="goruntu_gonderici", daemon=True),
                       threading.Thread(target=self._kuyruk_kaydi, name="goruntu_kuyruk_kaydi", daemon=True)]
        for t in self._ipler:
            t.start()

    def bagli_bekle(self, sure_sn):
        """Bağlanana (ya da hata/zaman aşımına) dek bekler → True (bağlı) / False (hata: `self.hata`)."""
        sinir = time.monotonic() + sure_sn
        while time.monotonic() < sinir and self.hata is None:
            if self.bagli.wait(0.1):
                return True
        return self.bagli.is_set()

    def _baglan(self, baglan_sn):
        sinir = time.monotonic() + baglan_sn
        son = None
        while not self._dur.is_set():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind((self.kaynak_adres, 0))
                s.settimeout(3.0)
                s.connect(self.hedef)
                s.settimeout(None)                     # gönderim bloke olur (geri basınç)
                self.sock = s
                return True
            except OSError as e:
                s.close()
                son = e
                if time.monotonic() > sinir:
                    break
                time.sleep(0.25)
        self.hata = f"bağlanılamadı ({self.kaynak_adres} → {self.hedef[0]}:{self.hedef[1]}, {baglan_sn:g} sn): {son!r}"
        return False

    def _calis(self, baglan_sn):
        try:
            if not self._baglan(baglan_sn):
                self.log("goruntu_kanali_hata", neden=str(self.hata).replace(" ", "_"))
                return
            self.baglanti_mono_ns = time.monotonic_ns()
            self.log("goruntu_kanali_baglandi", kaynak=self.kaynak_adres, hedef=f"{self.hedef[0]}:{self.hedef[1]}")
            self.bagli.set()
            while True:
                if self.hata is not None:
                    break
                try:
                    oge = self.kuyruk.bak(0.2)
                except Exception as e:  # noqa: BLE001  (disk okuma hatası: açık hata, sessiz durma yok)
                    self.hata_ver(f"gönderim kuyruğu okunamadı: {e!r}")
                    return
                if oge is None:
                    if self._dur.is_set():
                        break
                    continue
                n, _tur, veri = oge
                try:
                    self.sock.sendall(veri)
                except OSError as e:
                    if self.hata is None:
                        self.hata = f"gönderim hatası (kanal koptu?): {e!r}; kuyrukta {self.kuyruk.derinlik()[0]} ileti kaldı"
                        self.log("goruntu_kanali_hata", neden=self.hata.replace(" ", "_"))
                    return
                if self._olay_yaz is not None:
                    self._olay_yaz(olay(self.arac_kimligi, n, n * _NS // self.hz, "gonderim"))
                self.kuyruk.cikar()
                self.gonderilen += 1
                self.gonderilen_bayt += len(veri)
                self._son_gonderilen_n = n
                if self.temiz_kapat_n is not None and n >= self.temiz_kapat_n:
                    self.log("goruntu_kanali_enjeksiyon_temiz_kapatildi", n=n)
                    self._dur.set()
                    self._soketi_kapat()
                    return
        finally:
            self._bitti.set()

    def _kuyruk_kaydi(self):
        """Kuyruk derinliği (ileti, bayt) periyodik kaydı [belge: kuyruk durumu kaydedilecek]."""
        while not self._dur.wait(self.kuyruk_kayit_sn):
            self.durum_kaydet()

    def durum_kaydet(self):
        if self._kuyruk_yaz is None:
            return
        with self._kayit_kilit:                    # periyodik iş parçacığı ile kapanış kaydı aynı anda yazamaz; dosyada mono_ns ve toplam sayaçlar geriye gitmez
            k = self.kuyruk.sayaclar()             # tek kilit altında tutarlı anlık görüntü
            self._kuyruk_yaz({"surum": 1, "tur": "kuyruk_durumu", "arac_kimligi": self.arac_kimligi, "mono_ns": time.monotonic_ns(), "ileti": k["bekleyen"], "bayt": k["bekleyen_bayt"],
                              "giren_ileti": k["giren"], "gonderilen_ileti": k["cikan"], "gonderilen_bayt": k["cikan_bayt"]})

    # --- kapanış ----------------------------------------------------------------------------------------------------------------------------
    def bosalt_ve_kapat(self, bosalt_sn):
        """Kuyruğun boşalmasını bekler (en çok bosalt_sn); sonra göndericiyi durdurur ve soketi kapatır. Dönen: kuyruk boşaldı mı. Boşalmadıysa kalan sayı günlüğe yazılır.
        İdempotent: ikinci ve sonraki çağrılar ilk sonucu döner, günlük ya da kuyruk kaydı üretmez. Kapanış kuyruk kaydı, periyodik iş parçacığı durup birleştikten sonra yazılır."""
        with self._kapanis_kilit:
            if self._kapanis_sonucu is None:
                self._kapanis_sonucu = self._kapat_gercek(bosalt_sn)
            return self._kapanis_sonucu

    def _kapat_gercek(self, bosalt_sn):
        bos = self.kuyruk.bos_bekle(bosalt_sn) if self.hata is None else False
        self._dur.set()
        self.kuyruk.kapat()
        for t in self._ipler:
            t.join(5)
        self.durum_kaydet()                        # periyodik iş parçacığı bitti: kapanış kaydı sonuncu ve en büyük mono_ns'tir
        s = self.sock
        if s is not None:
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            s.close()
        it, by = self.kuyruk.derinlik()
        self.log("goruntu_kanali_kapandi", bosaldi=bos, kalan_ileti=it, kalan_bayt=by, hata=str(self.hata).replace(" ", "_") if self.hata else "yok", **{f"kuyruk_{k}": v for k, v in self.kuyruk.sayaclar().items()},
                 gonderilen=self.gonderilen, gonderilen_bayt=self.gonderilen_bayt)
        return bos and it == 0


class IletiHazirlayici:
    """Kamera alıcısının tüketici iş parçacığındaki iş: poz sorgusu → kare_poz kaydı → ileti → gönderim kuyruğu (sırayla; görüntü ve kare alınamadı iletileri tek akışta).
    Poz beklemesi kuyruğa girişten ÖNCE yapılır ve `kare_poz` kaydındaki `bekleme_ms` alanına yazılır (ölçüm dışında bırakılmaz). 2 Hz durum mesajı ya da "en son örnek" asla kullanılmaz."""

    def __init__(self, arac_kimligi, hz, poz_tamponu, kalibrasyon_kimligi, kuyruk, log, olay_yaz=None, poz_yaz=None, sha_yaz=None, hata_bildir=None):
        self.hata_bildir = hata_bildir                 # hata_bildir(metin): kanalı açık hatayla durdurur (Gonderici.hata_ver)
        self.hata = None                               # ilk hazırlama hatası; doluysa hiçbir ileti kuyruğa girmez
        self.dusen = 0                                 # hata sonrası kuyruğa alınmayan kare sayısı
        self.tasan = 0                                 # kuyruk taşması nedeniyle kuyruğa alınamayan kare sayısı (atılmadı: açık hata; bkz. kuyruk_tasmasi kaydı)
        self.arac_kimligi, self.hz = int(arac_kimligi), int(hz)
        self.poz_tamponu, self.kalibrasyon_kimligi, self.kuyruk, self.log = poz_tamponu, kalibrasyon_kimligi, kuyruk, log
        self._olay_yaz, self._poz_yaz, self._sha_yaz = olay_yaz, poz_yaz, sha_yaz
        self.goruntu_sayisi = self.kayip_sayisi = 0
        self.poz_bekleme_ms = []
        self.poz_gecersiz = {}
        self.son_n = None

    def _poz(self, n, damga_ns):
        s = self.poz_tamponu.sorgula(damga_ns)
        self.poz_bekleme_ms.append(s.bekleme_ms)
        if not s.gecerli:
            self.poz_gecersiz[s.neden] = self.poz_gecersiz.get(s.neden, 0) + 1
        if self._poz_yaz is not None:
            self._poz_yaz(pz.kare_poz_kaydi(self.arac_kimligi, n, damga_ns, s))
        return gi.Poz.sonuctan(s)

    def _hata(self, n, metin):
        """Hazırlama hatası: sessizce düşme yok, bozuk/boş yüklü ileti gönderilmez; günlüğe yazılır ve kanal açık hatayla durdurulur."""
        if self.hata is None:
            self.hata = f"ileti hazırlanamadı (n={n}): {metin}"
            self.log("hata", neden=self.hata.replace(" ", "_"))
            if self.hata_bildir is not None:
                self.hata_bildir(self.hata)

    def _gonder(self, tur, n, damga_ns, veri):
        if self.hata is not None:
            self.dusen += 1                            # kanal zaten hatalı; kare kuyruğa alınmaz (açık hata günlükte)
            return
        try:
            if tur == gi.TUR_GORUNTU and not veri:
                raise ValueError("görüntü baytları önbellekte bulunamadı (boş yük)")
            self._gonder_kodla(tur, n, damga_ns, veri)
        except KuyrukTasmasi as e:
            self.tasan += 1
            self._hata(n, f"kuyruk taştı: {e}")
        except Exception as e:  # noqa: BLE001
            self._hata(n, repr(e))

    def _gonder_kodla(self, tur, n, damga_ns, veri):
        poz = self._poz(n, damga_ns)
        veri_b = b"" if veri is None else veri
        b = gi.kodla(gi.Ileti(tur, self.arac_kimligi, n, damga_ns, self.kalibrasyon_kimligi, poz, veri_b))
        if self._sha_yaz is not None and tur == gi.TUR_GORUNTU:
            self._sha_yaz({"n": n, "sha256": hashlib.sha256(veri_b).hexdigest(), "bayt": len(veri_b)})
        yazildi_ns = self.kuyruk.koy((n, tur, b), n=n)
        if self._olay_yaz is not None:                  # öğe diske yazıldıktan SONRA (taşmada kayıt yazılmaz); zaman = kuyruğun yazma sonrası anı
            self._olay_yaz(olay(self.arac_kimligi, n, damga_ns, "gonderim_kuyrugu", yazildi_ns))
        self.son_n = n

    def goruntu(self, n, damga_ns, mono_ns, veri, w, h):
        """Kamera alıcısı kuyruk tüketicisi geri çağrısı (kare atılmaz)."""
        self.goruntu_sayisi += 1
        self._gonder(gi.TUR_GORUNTU, n, damga_ns, veri)

    def kayip(self, n, mono_ns):
        """Alıcı bu numara için 'kare alınamadı' kaydı yazdı: aynı kuyrukta, sırasını koruyarak yük 0 iletisi."""
        self.kayip_sayisi += 1
        self._gonder(gi.TUR_KARE_ALINAMADI, n, n * _NS // self.hz, None)
