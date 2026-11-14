"""Kare işleyici (B10): kamera alıcısının kuyruğundaki görev karesini çıkarım işçisine verir, işçi yanıtından ya da alıcının kayıp kaydından HER görev numarası için tam bir kare sonucu üretir,
yerel kayda yazar ve yerel kancaya (bu sürümde ağa gönderilmez; B11 bağlanacak) verir.
Yalnız standart kitaplık (rclpy yok): ileti oluşturma kancayı çağıran tarafa (arac.py) bırakılmıştır.
Sonucu olmayan numara kalmaz: kapanışta kalan numaralar için (işçi/zaman sınırı) `islem_hatasi` yazılır — "tespit yok" ASLA varsayılmaz.
`has_position` (konum, B14) ve `candidate` (birleştirme adayı, B15) bu sürümde her tespitte False'tur; kayıtta `konum: null`, `aday: false`.
"""
import threading
import time

from . import kare_sonuc as ks
from .cikarim_yardimci import SinifEsleme

_NS = 10 ** 9


class KareIsleyici:
    def __init__(self, ham, arac_kimligi, istemci, kayit_yol, log, kanca=None):
        self.arac_kimligi, self.istemci, self.log, self.kanca = int(arac_kimligi), istemci, log, kanca
        self.hz = int(float(ham["CAM_RATE_HZ"]))
        self.esleme = SinifEsleme.yapilandirmadan(ham)
        self.defter = ks.SonucDefteri()
        self.yazici = ks.KayitYazici(kayit_yol)
        self.kapaniyor = False
        self._k = threading.Lock()
        self._bitir_kilit = threading.Lock()    # bir sonucun defter + yazma + kanca adımları bölünmez; kapanış bekleyicisi bunu bekler
        self.sureler_ms = []                    # işlenen karelerin işçi içi (cikarim_sonu − cikarim_basi) süreleri
        self.atilan_toplam = 0

    # --- sonuç üretimi ----------------------------------------------------------------------------------------------------------------------
    def _bitir(self, n, damga_ns, durum, tespitler=(), atilan=0, hata=None):
        with self._bitir_kilit:
            return self._bitir_kilitli(n, damga_ns, durum, tespitler, atilan, hata)

    def _bitir_kilitli(self, n, damga_ns, durum, tespitler, atilan, hata):
        kayit = ks.kayit_olustur(self.arac_kimligi, n, damga_ns, durum, tespitler, atilan, hata, time.monotonic_ns())
        if not self.defter.ekle(kayit):
            self.log("kare_sonuc_cift", n=n, durum=durum, ayrinti="bu numara için zaten sonuç var; ikinci sonuç yazılmadı")
            return False
        self.yazici.yaz(kayit)
        if durum != ks.TESPIT_YOK:
            self.log("kare_sonuc", n=n, durum=durum, tespit=len(kayit["tespitler"]), hata=(hata or "-").replace(" ", "_"))
        if self.kanca is not None:
            try:
                self.kanca(kayit)
            except Exception as e:  # noqa: BLE001
                self.log("kare_sonuc_kancasi_hatasi", n=n, hata=repr(e))
        return True

    def goruntu(self, n, damga_ns, mono_ns, veri, w, h):
        """Alıcı kuyruğu tüketicisi (tek iş parçacığı): kareyi işçide işler ve sonucunu yazar. Her çağrı bir numaraya tam bir sonuç üretir."""
        if self.kapaniyor and self.defter.var_mi(n):
            return
        yanit = self.istemci.isle(n, damga_ns, veri, w, h)
        durum, tespitler, atilan, hata = ks.durum_belirle(yanit, self.esleme)
        if yanit.get("basi_ns") and yanit.get("sonu_ns"):
            self.sureler_ms.append((yanit["sonu_ns"] - yanit["basi_ns"]) / 1e6)
        self.atilan_toplam += atilan
        self._bitir(n, damga_ns, durum, tespitler, atilan, hata)

    def kayip(self, n, mono_ns):
        """Alıcı bu numara için "kare alınamadı" kaydı yazdı: tespit taşımayan kare sonucu."""
        self._bitir(n, n * _NS // self.hz, ks.KARE_ALINAMADI)

    # --- kapanış ----------------------------------------------------------------------------------------------------------------------------
    def kapanis_tamamla(self, n_ilk, n_son, bekle_sn, alici_kapat_zorla):
        """[n_ilk, n_son] için bütün sonuçlar gelene dek bekler. Süre dolarsa: kapanış karesi gelmediyse sondaki kayıpları alıcıya yazdırır (`alici_kapat_zorla`), hâlâ sonuçsuz kalan numaralar
        için `islem_hatasi` yazar (işlenemedi). Dönen: (tamam_zamaninda, zorla_kayip_numaralari, islem_hatasi_numaralari)."""
        zamaninda = self.defter.bekle_tamam(n_ilk, n_son, bekle_sn)
        with self._bitir_kilit:     # defter son numarayı görünce bekleyici uyanır; sürmekte olan son _bitir'in yazması ve kancası bitmeden dönülmez
            pass
        zorla, hatali = [], []
        if not zamaninda:
            zorla = list(alici_kapat_zorla() or [])
            self.kapaniyor = True
            for n in self.defter.eksikler(n_ilk, n_son):
                self._bitir(n, n * _NS // self.hz, ks.ISLEM_HATASI, hata=f"kapanışta işlenemedi (kuyruk {bekle_sn:g} sn içinde boşalmadı)")
                hatali.append(n)
        return zamaninda, zorla, hatali
