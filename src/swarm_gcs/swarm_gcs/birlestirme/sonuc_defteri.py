"""Yer istasyonu sonuç defteri (B11; saf mantık, rclpy'siz): her araç için tarama bitişinde bildirilen [n_ilk, n_son] aralığının her numarasına tam bir kare sonucunun geldiğini sayar.

Kurallar: (1) aynı araç ve numara ikinci kez gelirse ilki kabul kalır, ikincisi `tekrar` olarak sayılır ve kaydedilir; (2) aralık dışı numara sayılır ve kaydedilir, aralığı tamamlamaz;
(3) tarama bitişinden ÖNCE gelen sonuçlar tutulur (sıra garanti değildir; reliable DDS farklı yayımcıların iletileri arasında sıra vermez) ve aralık bilinince sınıflanır; (4) bir numara, dört durumdan
(tespit, tespit_yok, islem_hatasi, kare_alinamadi) biriyle geldiğinde "tamam" sayılır [kullanıcı kararı 2026-11-14: işlem hatası COMPLETE'i engellemez; planlama/kararlar.md]; durumlar ayrı sayılır
ve birbirine çevrilmez. İş parçacığı güvenlidir (Condition); sorgular ve bekleme bu kilidi kullanır.
"""
import threading
import time

DURUMLAR = ("tespit", "tespit_yok", "islem_hatasi", "kare_alinamadi")


class SonucDefteri:
    def __init__(self, arac_kimlikleri):
        self.arac_kimlikleri = [int(a) for a in arac_kimlikleri]
        self._k = threading.Condition()
        self.beklenen = {}                                      # araç → (n_ilk, n_son)
        self._gelen = {a: {} for a in self.arac_kimlikleri}      # araç → {n: kayıt}; aralık bilinmiyorsa hepsi burada
        self._aralik_disi = {a: {} for a in self.arac_kimlikleri}
        self.tekrarlar = []                                     # (araç, n, durum, mono_ns): ikinci ve sonraki gelişler
        self.bilinmeyen_arac = []                               # (araç, n, durum, mono_ns): beklenen araçlar dışından
        self.tamam_mono_ns = None                               # hepsi_tamam'ın ilk doğru olduğu an (son kabul edilen sonucun alım anı ya da son aralığın bildirildiği an; hangisi geç)

    # --- yazma ---------------------------------------------------------------------------------------------------------------------------
    def aralik_ayarla(self, arac, n_ilk, n_son, mono_ns=None):
        """Tarama bitişinden gelen aralık. Önceden gelmiş aralık dışı sonuçlar ayrılır. Aynı araç için ikinci bildirim aralığı değiştirmez (False)."""
        arac = int(arac)
        with self._k:
            if arac not in self._gelen or arac in self.beklenen:
                return False
            self.beklenen[arac] = (int(n_ilk), int(n_son))
            for n in [n for n in self._gelen[arac] if not n_ilk <= n <= n_son]:
                self._aralik_disi[arac][n] = self._gelen[arac].pop(n)
            self._tamam_guncelle(mono_ns)
            self._k.notify_all()
            return True

    def ekle(self, arac, n, durum, mono_ns, **ek):
        """Dönen: 'kabul' | 'tekrar' | 'aralik_disi' | 'bilinmeyen_arac'. Aralık henüz bilinmiyorsa numara tutulur ('kabul'); aralık dışı olduğu sonradan anlaşılabilir."""
        arac, n = int(arac), int(n)
        if durum not in DURUMLAR:
            raise ValueError(f"bilinmeyen durum: {durum!r}")
        kayit = {"arac": arac, "n": n, "durum": durum, "mono_ns": int(mono_ns), **ek}
        with self._k:
            if arac not in self._gelen:
                self.bilinmeyen_arac.append((arac, n, durum, int(mono_ns)))
                return "bilinmeyen_arac"
            if n in self._gelen[arac] or n in self._aralik_disi[arac]:
                self.tekrarlar.append((arac, n, durum, int(mono_ns)))
                return "tekrar"
            ar = self.beklenen.get(arac)
            if ar is not None and not ar[0] <= n <= ar[1]:
                self._aralik_disi[arac][n] = kayit
                return "aralik_disi"
            self._gelen[arac][n] = kayit
            self._tamam_guncelle(mono_ns)
            self._k.notify_all()
            return "kabul"

    def _tamam_guncelle(self, mono_ns):
        if self.tamam_mono_ns is None and self._hepsi_tamam_kilitli():
            self.tamam_mono_ns = int(mono_ns) if mono_ns is not None else time.monotonic_ns()

    # --- sorgular -----------------------------------------------------------------------------------------------------------------------
    def _eksikler_kilitli(self, arac):
        ar = self.beklenen.get(arac)
        if ar is None:
            return None
        return [n for n in range(ar[0], ar[1] + 1) if n not in self._gelen[arac]]

    def eksikler(self, arac):
        """Aralığı bilinen aracın eksik numaraları; aralık bilinmiyorsa None."""
        with self._k:
            return self._eksikler_kilitli(int(arac))

    def aralik_disi(self, arac):
        with self._k:
            return sorted(self._aralik_disi[int(arac)])

    def arac_tamam(self, arac):
        with self._k:
            e = self._eksikler_kilitli(int(arac))
            return e is not None and not e

    def _hepsi_tamam_kilitli(self):
        return all(self._eksikler_kilitli(a) == [] for a in self.arac_kimlikleri)

    def hepsi_tamam(self):
        with self._k:
            return self._hepsi_tamam_kilitli()

    def bekle_hepsi_tamam(self, sure_sn):
        sinir = time.monotonic() + sure_sn
        with self._k:
            while not self._hepsi_tamam_kilitli():
                kalan = sinir - time.monotonic()
                if kalan <= 0:
                    return False
                self._k.wait(min(kalan, 0.2))
            return True

    def kayit(self, arac, n):
        with self._k:
            return self._gelen[int(arac)].get(int(n))

    def kabul_edilenler(self):
        """Aralıkta kabul edilmiş bütün sonuç kayıtları (hedef birleştirme girdisi; aralık dışı ve tekrarlar yoktur), araç ve numara sırasıyla."""
        with self._k:
            return [self._gelen[a][n] for a in sorted(self._gelen) for n in sorted(self._gelen[a])]

    def sayilar(self):
        """Araç başına {'beklenen', 'gelen', 'eksik', 'tekrar', 'aralik_disi', 'durumlar': {...}}; aralık bilinmiyorsa beklenen/eksik None."""
        with self._k:
            cikti = {}
            for a in self.arac_kimlikleri:
                ar = self.beklenen.get(a)
                d = {x: 0 for x in DURUMLAR}
                for k in self._gelen[a].values():
                    d[k["durum"]] += 1
                cikti[a] = {"beklenen": None if ar is None else ar[1] - ar[0] + 1, "gelen": len(self._gelen[a]), "eksik": None if ar is None else len(self._eksikler_kilitli(a)),
                            "tekrar": sum(1 for t in self.tekrarlar if t[0] == a), "aralik_disi": len(self._aralik_disi[a]), "durumlar": d}
            return cikti
