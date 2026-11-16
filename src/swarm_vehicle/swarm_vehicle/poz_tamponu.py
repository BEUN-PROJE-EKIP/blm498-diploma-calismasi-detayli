"""Poz tamponu ve kare–poz enterpolasyonu (FR-17, FR-18; B14'ün ilk yarısı). Yalnız standart kitaplık (rclpy ve MAVSDK içe aktarılmaz).

Belge (merkezi mod): her görüntü iletisi, kare üretim anına eşlenmiş canlı PX4 konum/yönelim tahminini taşır; eşleme KAYNAK zamanına göre enterpolasyonla yapılır
(konum doğrusal, yönelim küresel); kareyi çevreleyen iki telemetri örneği arasındaki süre sınırı (öngörülen 100 ms) aşarsa o karenin tespitleri konumsuz kaydedilir; iki mod aynı
kuralı kullanır; poz için gereken bekleme süresi ölçüm dışında bırakılmaz; gecikmiş kare en son alınan 2 Hz durum mesajıyla konumlandırılmaz.
Bu modülde "en son örnek" ya da durum mesajı HİÇBİR durumda yedek değildir: geçerli poz yoksa neden ile geçersiz döner.

Örnek: kaynak zamanı (PX4 `time_usec` → ns), konum NED (m), yönelim kuaterniyonu wxyz (gövde FRD → NED), alınma monotonik ns.
İş parçacığı güvenlidir: adapter'ın asyncio iş parçacığı `ekle` çağırır, araç süreci `sorgula` çağırır.
"""
import bisect
import json
import math
import queue
import threading
import time

_NS = 10 ** 9

# geçersizlik nedenleri
ARALIK_ASILDI, TAMPON_DISI, BEKLEME_ASILDI = "aralik_asildi", "tampon_disi", "bekleme_asildi"
NEDENLER = (ARALIK_ASILDI, TAMPON_DISI, BEKLEME_ASILDI)
# ekleme ret nedenleri
RED_GERI, RED_YINELENEN, RED_GECERSIZ = "geriye_giden", "yinelenen", "gecersiz_deger"


def _normalize(q):
    n = math.sqrt(sum(v * v for v in q))
    if not n or not math.isfinite(n):
        raise ValueError("kuaterniyon normu sıfır ya da sonlu değil")
    return tuple(v / n for v in q)


def slerp(q1, q2, f):
    """Küresel doğrusal enterpolasyon (wxyz). Kısa yol: iç çarpım < 0 ise q2 işaret değiştirir. Çok yakın kuaterniyonlarda (iç çarpım > 0,9995) sayısal kararlı yol:
    normalize edilmiş doğrusal enterpolasyon. Sonuç birim kuaterniyondur."""
    a, b = _normalize(q1), _normalize(q2)
    d = sum(x * y for x, y in zip(a, b))
    if d < 0.0:
        b, d = tuple(-v for v in b), -d
    if d > 0.9995:
        return _normalize(tuple(x + f * (y - x) for x, y in zip(a, b)))
    teta = math.acos(min(1.0, d))
    s = math.sin(teta)
    w1, w2 = math.sin((1.0 - f) * teta) / s, math.sin(f * teta) / s
    return _normalize(tuple(w1 * x + w2 * y for x, y in zip(a, b)))


class PozSonuc:
    """Bir kare için poz sorgusunun sonucu. `gecerli` False ise `neden` doludur ve konum/yönelim None'dır."""
    __slots__ = ("gecerli", "neden", "t1_ns", "t2_ns", "aralik_ms", "bekleme_ms", "konum", "q")

    def __init__(self, gecerli, neden, t1_ns, t2_ns, aralik_ms, bekleme_ms, konum, q):
        self.gecerli, self.neden, self.t1_ns, self.t2_ns = gecerli, neden, t1_ns, t2_ns
        self.aralik_ms, self.bekleme_ms, self.konum, self.q = aralik_ms, bekleme_ms, konum, q

    def __repr__(self):
        return f"PozSonuc(gecerli={self.gecerli}, neden={self.neden}, t1={self.t1_ns}, t2={self.t2_ns}, aralik_ms={self.aralik_ms}, bekleme_ms={self.bekleme_ms})"


class PozTamponu:
    """Kaynak zamanına göre sıralı telemetri tamponu.
    aralik_sinir_ns: çevreleyen iki örnek arasındaki en büyük süre (eşitlik geçerli); bekle_sn: kare anı en son örnekten sonraysa sonraki örnek için en çok bekleme (gerçek sn);
    tampon_sn: saklama penceresi (en yeni kaynak zamanından geriye, kaynak sn)."""

    def __init__(self, aralik_sinir_ns, bekle_sn, tampon_sn, saat_ns=time.monotonic_ns):
        if aralik_sinir_ns <= 0 or bekle_sn < 0 or tampon_sn <= 0:
            raise ValueError("aralik_sinir_ns > 0, bekle_sn >= 0, tampon_sn > 0 olmalı")
        self.aralik_sinir_ns, self.bekle_sn, self.tampon_ns = int(aralik_sinir_ns), float(bekle_sn), int(tampon_sn * _NS)
        self._saat = saat_ns
        self._k = threading.Condition()
        self._t = []          # kaynak ns, artan
        self._o = []          # (konum, q) ikilileri; _t ile aynı sırada
        self.eklenen = 0
        self.reddedilen = {RED_GERI: 0, RED_YINELENEN: 0, RED_GECERSIZ: 0}

    def ekle(self, kaynak_ns, konum, q):
        """Örnek ekler. Dönen: (kabul, ret_nedeni). Geriye giden/yinelenen kaynak zamanı ve sonlu olmayan değerler reddedilir ve SAYILIR (sessiz değil)."""
        try:
            konum = tuple(float(v) for v in konum)
            q = _normalize(tuple(float(v) for v in q))
            ok = len(konum) == 3 and all(math.isfinite(v) for v in konum) and len(q) == 4
        except (TypeError, ValueError):
            ok = False
        with self._k:
            if not ok:
                self.reddedilen[RED_GECERSIZ] += 1
                return False, RED_GECERSIZ
            kaynak_ns = int(kaynak_ns)
            if self._t and kaynak_ns <= self._t[-1]:
                neden = RED_YINELENEN if kaynak_ns == self._t[-1] else RED_GERI
                self.reddedilen[neden] += 1
                return False, neden
            self._t.append(kaynak_ns)
            self._o.append((konum, q))
            self.eklenen += 1
            sinir = kaynak_ns - self.tampon_ns
            k = bisect.bisect_left(self._t, sinir)
            if k > 0:
                del self._t[:k], self._o[:k]
            self._k.notify_all()
            return True, None

    def boyut(self):
        with self._k:
            return len(self._t)

    def sayaclar(self):
        with self._k:
            return {"eklenen": self.eklenen, **{f"reddedilen_{k}": v for k, v in self.reddedilen.items()}, "tampon_boyut": len(self._t)}

    def sorgula(self, t_ns):
        """t_ns (kare üretim anı, kaynak ekseninde) için poz. Çevreleyen iki örnek t1 <= t <= t2; konum doğrusal, yönelim slerp; tam örnek anında o örnek.
        t2 - t1 > aralık sınırı → geçersiz (aralik_asildi). t ilk örnekten önce → geçersiz (tampon_disi). t en son örnekten sonraysa sonraki örnek için en çok `bekle_sn`
        beklenir; dolarsa geçersiz (bekleme_asildi). Bekleme süresi `bekleme_ms` alanında her durumda bildirilir."""
        t_ns = int(t_ns)
        basla = self._saat()
        sinir = basla + int(self.bekle_sn * _NS)
        with self._k:
            while True:
                if self._t and t_ns < self._t[0]:
                    return self._sonuc(False, TAMPON_DISI, basla)
                if self._t and t_ns <= self._t[-1]:
                    break
                kalan = sinir - self._saat()
                if kalan <= 0:
                    return self._sonuc(False, BEKLEME_ASILDI, basla)
                self._k.wait(kalan / _NS)
            i = bisect.bisect_left(self._t, t_ns)
            if self._t[i] == t_ns:
                konum, q = self._o[i]
                return self._sonuc(True, None, basla, t_ns, t_ns, konum, q)
            t1, t2 = self._t[i - 1], self._t[i]
            if t2 - t1 > self.aralik_sinir_ns:
                return self._sonuc(False, ARALIK_ASILDI, basla, t1, t2)
            f = (t_ns - t1) / (t2 - t1)
            (k1, q1), (k2, q2) = self._o[i - 1], self._o[i]
            konum = tuple(a + f * (b - a) for a, b in zip(k1, k2))
            return self._sonuc(True, None, basla, t1, t2, konum, slerp(q1, q2, f))

    def _sonuc(self, gecerli, neden, basla, t1=None, t2=None, konum=None, q=None):
        aralik = None if t1 is None or t2 is None else (t2 - t1) / 1e6
        return PozSonuc(gecerli, neden, t1, t2, aralik, (self._saat() - basla) / 1e6, konum, q)


def kare_poz_kaydi(arac_kimligi, n, kare_ns, s):
    """`kare_poz` kaydı (planlama/sozlesmeler.md §8.11)."""
    return {"surum": 1, "tur": "kare_poz", "arac_kimligi": int(arac_kimligi), "n": int(n), "kare_ns": int(kare_ns), "gecerli": bool(s.gecerli), "neden": s.neden,
            "t1_ns": s.t1_ns, "t2_ns": s.t2_ns, "aralik_ms": s.aralik_ms, "bekleme_ms": s.bekleme_ms,
            "konum_ned_m": list(s.konum) if s.konum is not None else None, "q_wxyz": list(s.q) if s.q is not None else None}


def _sonlu(v):
    """Sonlu sayı ya da None: NaN/inf standart JSON'a yazılamaz (`NaN`), kayıtta null olur."""
    v = float(v)
    return v if math.isfinite(v) else None


def telemetri_kaydi(arac_kimligi, kaynak_ns, alinma_ns, konum, q, kabul, red_neden):
    """`telemetri` kaydı (planlama/sozlesmeler.md §8.10). Sonlu olmayan (NaN/inf) değerler `null` yazılır; böyle bir örnek tampona zaten `gecersiz_deger` ile reddedilir."""
    return {"surum": 1, "tur": "telemetri", "arac_kimligi": int(arac_kimligi), "kaynak_ns": int(kaynak_ns), "alinma_mono_ns": int(alinma_ns),
            "konum_ned_m": [_sonlu(v) for v in konum], "q_wxyz": [_sonlu(v) for v in q], "kabul": bool(kabul), "red_neden": red_neden}


class SatirYazici:
    """JSON Lines yazıcısı: `ver` kuyruğa koyar ve ASLA bloke etmez (ayrı yazıcı iş parçacığı; adapter akışı disk gecikmesinden etkilenmesin). Kapanışta kuyruk boşalır.
    Kuyruk sınırsızdır (50 Hz × ~200 bayt ≈ 10 KB/s; sınır koymak sessiz kayıp olurdu).
    Hatalar SESSİZ DEĞİLDİR: dosya açılamaz ya da yazılamazsa ilk hata `log(olay, **alanlar)` ile yazılır, sonraki kayıtlar `dusen` olarak sayılır; `kapat()` sonrası gelen kayıtlar
    `kapali_sonrasi` olarak sayılır (ilki günlüğe yazılır); `ozet()` bütün sayaçları verir ve kapanışta günlüğe yazılması çağıranın işidir. `yol` boşsa yazıcı kapalıdır (yazma istenmemiştir)."""

    KAPAT_BEKLE_SN = 10                               # kapat() içinde yazıcı iş parçacığını bekleme üst sınırı (test için değiştirilebilir)

    def __init__(self, yol, log=None):
        self.yol = yol
        self._log = log
        self._q = queue.SimpleQueue()
        self._k = threading.Lock()
        self.yazilan = self.dusen = self.kapali_sonrasi = 0
        self.verilen = 0                              # `ver` ile verilen kayıt sayısı: yazilan + dusen + kapali_sonrasi == verilen (kapanış bittikten sonra)
        self._zaman_asimi_bildirildi = False
        self.hata = None
        self._kapali = False
        self._th = None
        if yol:
            self._th = threading.Thread(target=self._calis, name="satir_yazici", daemon=True)
            self._th.start()

    def _bildir(self, olay, **kv):
        if self._log is not None:
            try:
                self._log(olay, yol=self.yol, **kv)
            except Exception:  # noqa: BLE001  (günlük hatası yazıcıyı durdurmasın)
                pass

    def ver(self, kayit):
        if self.yol is None:
            return
        with self._k:                                 # kuyruğa koyma da kilit altında: kapat() bitiş işaretini araya sokamaz
            self.verilen += 1
            if self._kapali:
                self.kapali_sonrasi += 1
                ilk = self.kapali_sonrasi == 1
            else:
                ilk = None
                self._q.put(kayit)
        if ilk:
            self._bildir("satir_yazici_kapali_sonrasi", ayrinti="kapatıldıktan sonra kayıt geldi; yazılmadı, sayılıyor")

    def _hata(self, ne, e):
        with self._k:
            ilk = self.hata is None
            if ilk:
                self.hata = f"{ne}: {e!r}"
        if ilk:
            self._bildir("satir_yazici_hata", ne=ne, hata=repr(e))

    def _calis(self):
        f = None
        try:
            f = open(self.yol, "a", encoding="utf-8")
        except OSError as e:
            self._hata("acilamadi", e)
        while True:
            k = self._q.get()
            if k is None:
                break
            satirlar = [k]
            while True:                               # kuyrukta birikenleri tek seferde yaz
                try:
                    k = self._q.get_nowait()
                except queue.Empty:
                    break
                if k is None:
                    self._q.put(None)
                    break
                satirlar.append(k)
            if f is None:
                with self._k:
                    self.dusen += len(satirlar)
                continue
            metin, gecerli = [], 0
            for x in satirlar:                        # kayıt kayıt serileştir: yalnız hatalı kayıt düşer
                try:
                    metin.append(json.dumps(x, ensure_ascii=False, allow_nan=False) + "\n")
                    gecerli += 1
                except (ValueError, TypeError) as e:
                    self._hata("serilestirilemedi", e)
                    with self._k:
                        self.dusen += 1
            if not metin:
                continue
            try:
                f.write("".join(metin))
                f.flush()
                with self._k:
                    self.yazilan += gecerli
            except (OSError, ValueError, TypeError) as e:
                self._hata("yazilamadi", e)
                with self._k:
                    self.dusen += gecerli
                if isinstance(e, OSError):
                    try:
                        f.close()
                    except OSError:
                        pass
                    f = None
        if f is not None:
            f.close()

    def ozet(self):
        """Sayaçlar. `tamam`: kapatıldı ve yazıcı iş parçacığı bitti (False ise kuyrukta yazılmamış kayıt kalmış olabilir: `satir_yazici_zaman_asimi` günlüğe yazılmıştır)."""
        with self._k:
            th = self._th
            return {"yazilan": self.yazilan, "dusen": self.dusen, "kapali_sonrasi": self.kapali_sonrasi, "verilen": self.verilen,
                    "tamam": self._kapali and (th is None or not th.is_alive()), "hata": self.hata}

    def kapat(self):
        """Kuyruğu boşaltıp kapatır. Her çağrı yazıcı iş parçacığının bitmesini bekler (en çok 10 sn; bitiş işareti yalnız bir kez konur), böylece ikinci çağıran da yazma bitmeden dönmez
        (çıkıştaki `os._exit` yazıcıyı yazarken öldürmesin). Süre dolarsa `satir_yazici_zaman_asimi` günlüğe yazılır ve `ozet()['tamam']` False olur.
        Dönen: bu çağrı kapatmayı başlatan ilk çağrıysa True (özet günlüğünü yalnız ilk çağıran yazar); sonrakiler ve yolsuz yazıcı için False."""
        with self._k:
            ilk = not self._kapali and self._th is not None
            self._kapali = True
            th = self._th                             # referans korunur: her çağrı aynı iş parçacığını bekler
        if ilk:
            self._q.put(None)
        if th is not None:
            th.join(self.KAPAT_BEKLE_SN)
            if th.is_alive():
                with self._k:
                    bildir = not self._zaman_asimi_bildirildi
                    self._zaman_asimi_bildirildi = True
                if bildir:
                    self._bildir("satir_yazici_zaman_asimi", kuyrukta_kalan=self._q.qsize(), ayrinti="yazıcı iş parçacığı 10 sn içinde bitmedi; kuyrukta yazılmamış kayıt kalmış olabilir")
        return ilk
