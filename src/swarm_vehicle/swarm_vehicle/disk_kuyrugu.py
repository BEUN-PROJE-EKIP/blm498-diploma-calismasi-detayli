"""Disk destekli FIFO uygulama kuyruğu (B13). Kare verisi (görüntü baytları) taşıyan üç uygulama kuyruğu bu tek sınıfı kullanır: araç gönderim kuyruğu (merkezi mod), araç kamera kuyruğu
(kamera alıcısı → tüketici; iki modda), yer istasyonu işleme kuyruğu (merkezi mod). rclpy/MAVSDK/gz içe aktarılmaz (birim testli).

Belge: "Uygulama kuyrukları disk destekli tutulur; kapasite taşması sessiz kare atlamaya dönüştürülmez." Bu yüzden:
- Öğe baytları diske yazılır: kuyruk dizininde ekleme yapılan bölüt dosyaları (`bolut_<sıra>.kuy`); öğe `pickle` ile serileştirilir. Bellekte yalnız üst bilgi tutulur (bölüt, konum, uzunluk, bayt) ve başındaki
  öğenin okunmuş kopyası (en çok bir öğe). Tamamen tüketilen bölüt silinir. `fsync` yoktur [varsayım: çökme sonrası kurtarma kapsam dışı; yazılan baytlar işletim sistemi önbelleğine verilir].
- Sıra (FIFO) ve "atma yok" korunur; `bak` öğeyi çıkarmaz (gönderim/işlem bitince `cikar`); `al` = bekle + çıkar.
- Kapasite: yazma hatası (ör. ENOSPC) ya da yazmadan sonra boş alan `alt_sinir_mb`'nin altına inecekse öğe KUYRUĞA ALINMAZ ve atılmaz: `KuyrukTasmasi` fırlatılır, `(-)` günlük satırı (`kuyruk_tasmasi`) ve
  `kayit/kuyruk_tasmasi_<ad>.jsonl` kaydı yazılır; çağıran bileşen açık hatayla durur. Yeniden deneme yoktur, bellekte tutmaya geri düşülmez; taşma sonrası her `koy` yine `KuyrukTasmasi` fırlatır.
- Kapanış: `kapat()` kuyruk boşsa bölütleri ve dizini siler; boş değilse kalan öğe sayısı günlüğe yazılır ve dizin yerinde kalır.
Test anahtarı (YALNIZ test, varsayılan kapalı): ortam değişkeni KUYRUK_TEST_TASMA=`<kuyruk adı öneki>:<n>[;...]` → adı o önekle başlayan kuyruğun n'inci `koy` çağrısı yapay ENOSPC hatası alır (öğe yazılmaz).
"""
import collections
import errno
import json
import os
import pickle
import shutil
import sys
import threading
import time

MIB = 1 << 20


class KuyrukTasmasi(RuntimeError):
    """Kuyruk kapasitesi tükendi (yazma hatası ya da boş alan alt sınırın altında): öğe kuyruğa alınmadı ve ATILMADI; bileşen açık hatayla durmalıdır."""


def test_tasma_ayristir(metin, ad):
    """KUYRUK_TEST_TASMA → bu kuyruk adı için yapay taşma yapılacak yazma numarası (1 tabanlı) ya da None. Bozuk değer ValueError."""
    for parca in [p for p in (metin or "").split(";") if p.strip()]:
        onek, _, n = parca.strip().partition(":")
        if not onek or not n.strip().isdigit() or int(n) < 1:
            raise ValueError(f"KUYRUK_TEST_TASMA: '<kuyruk adı öneki>:<n>' bekleniyordu (verilen: {parca!r})")
        if ad.startswith(onek):
            return int(n)
    return None


def kuyruk_olustur(ad, dizin, ham, log=None, tasma_yol=None, bayt_olc=None, ortam=None, gecici_ust=None):
    """Yapılandırmadan (`KUYRUK_DISK_ALT_SINIR_MB`, `KUYRUK_BOLUT_MB`) ve test anahtarından (`KUYRUK_TEST_TASMA`) `DiskKuyrugu` kurar; üç uygulama kuyruğu da buradan kurulur."""
    env = os.environ if ortam is None else ortam
    n = test_tasma_ayristir(env.get("KUYRUK_TEST_TASMA", ""), ad)
    if n is not None and log is not None:
        log("test_anahtari_acik", seviye="(!)", anahtar="KUYRUK_TEST_TASMA", kuyruk=ad, yazma_no=n, uyari="TEST ANAHTARI ACIK: bu kuyruğun belirtilen yazması yapay ENOSPC alır; koşu yarida_kaldi biter")
    return DiskKuyrugu(ad, dizin, float(ham["KUYRUK_DISK_ALT_SINIR_MB"]), float(ham["KUYRUK_BOLUT_MB"]), log=log, tasma_yol=tasma_yol, bayt_olc=bayt_olc, test_tasma_n=n, gecici_ust=gecici_ust)


class DiskKuyrugu:
    def __init__(self, ad, dizin, alt_sinir_mb, bolut_mb, log=None, tasma_yol=None, bayt_olc=None, test_tasma_n=None, bos_alan=None, gecici_ust=None):
        """ad: kuyruk adı (günlük ve kayıtlarda). dizin: bölütlerin yazıldığı dizin (yoksa oluşturulur; içinde eski bölüt varsa açık hata). alt_sinir_mb: boş alan alt sınırı.
        bolut_mb: bölüt dosyasının yaklaşık büyüklüğü (bir öğe bölütü aşabilir; bölüt öğe sınırında kapanır). bayt_olc(öğe) → sayaçlardaki bayt (öntanımlı: serileştirilmiş uzunluk).
        tasma_yol: taşma kaydının JSON Lines dosyası (None: yalnız günlük). test_tasma_n: yapay ENOSPC için yazma numarası. bos_alan(): boş bayt (öntanımlı: dizinin diski). gecici_ust: yalnız test/duman düzenekleri için geçici üst dizin; kuyruk boşken kapanışta dizinle birlikte silinir."""
        self.ad, self.dizin = ad, dizin
        self.alt_sinir = int(float(alt_sinir_mb) * MIB)
        self.bolut_bayt = max(1, int(float(bolut_mb) * MIB))
        self._log, self._tasma_yol, self._bayt_olc = log, tasma_yol, bayt_olc
        self._test_tasma_n = test_tasma_n
        self._gecici_ust = gecici_ust
        self._bos_alan = bos_alan or (lambda: shutil.disk_usage(self.dizin).free)
        os.makedirs(dizin, exist_ok=True)
        eski = [f for f in os.listdir(dizin) if f.startswith("bolut_")]
        if eski:
            raise RuntimeError(f"kuyruk dizininde önceki koşudan kalma bölüt var ({len(eski)} dosya): {dizin}")
        self._k = threading.Condition()
        self._d = collections.deque()              # (bölüt, konum, uzunluk, bayt)
        self._bolutler = {}                        # bölüt → {"yol", "kalan", "boyut"}
        self._yazan = None                         # yazılan bölüt numarası ya da None
        self._yazan_f = None
        self._sonraki_bolut = 0
        self._bas = None                           # başındaki öğenin okunmuş kopyası (bak)
        self._bayt = 0
        self._disk_bayt = 0
        self._kapali = False
        self._temiz = False
        self._yazma_say = 0
        self.tasma = None                          # taşma bilgisi (sözlük) ya da None
        self.giren = self.cikan = 0
        self.giren_bayt = self.cikan_bayt = 0
        self.maks_ileti = self.maks_bayt = self.maks_disk_bayt = 0

    # --- yazma ------------------------------------------------------------------------------------------------------------------------------
    def _bolut_ac(self):
        no = self._sonraki_bolut
        self._sonraki_bolut += 1
        yol = os.path.join(self.dizin, f"bolut_{no:08d}.kuy")
        self._yazan_f = open(yol, "xb")
        self._bolutler[no] = {"yol": yol, "kalan": 0, "boyut": 0}
        self._yazan = no

    def _yazani_kapat(self):
        if self._yazan_f is not None:
            try:
                self._yazan_f.close()
            except OSError:
                pass
        self._yazan_f, self._yazan = None, None

    def _tasma_ver(self, neden, bayt, n, bos):
        """Taşma: açık hata (günlük `(-)` + kayıt) ve istisna; öğe atılmaz, kuyruğa da alınmaz."""
        self.tasma = {"neden": neden, "n": n, "bayt": int(bayt), "ileti": len(self._d), "kuyruk_bayt": self._bayt, "bos_alan_bayt": bos, "alt_sinir_bayt": self.alt_sinir}
        kayit = {"surum": 1, "tur": "kuyruk_tasmasi", "kuyruk": self.ad, "n": "bilinmiyor" if n is None else n, "mono_ns": time.monotonic_ns(), "neden": neden, "oge_bayt": int(bayt),
                 "ileti": len(self._d), "kuyruk_bayt": self._bayt, "bos_alan_bayt": bos, "alt_sinir_bayt": self.alt_sinir}
        if self._tasma_yol:
            try:
                with open(self._tasma_yol, "a", encoding="utf-8") as f:
                    f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
            except OSError as e:                    # kayıt yazılamıyorsa (disk dolu) sessiz geçilmez: günlük + stderr; istisna yine de açık hatayı bildirir
                print(f"(-) tasma_kaydi_yazilamadi kuyruk={self.ad} hata={e!r}", file=sys.stderr, flush=True)
                if self._log is not None:
                    self._log("tasma_kaydi_yazilamadi", seviye="(-)", kuyruk=self.ad, hata=repr(e).replace(" ", "_"))
        if self._log is not None:
            self._log("kuyruk_tasmasi", seviye="(-)", kuyruk=self.ad, n=kayit["n"], neden=neden.replace(" ", "_"), ileti=kayit["ileti"], kuyruk_bayt=self._bayt, oge_bayt=int(bayt),
                      bos_alan_bayt=bos if bos is not None else "bilinmiyor", alt_sinir_bayt=self.alt_sinir, ayrinti="öğe atılmadı ve kuyruğa alınmadı; bileşen açık hatayla duracak")
        raise KuyrukTasmasi(f"kuyruk '{self.ad}' taştı ({neden}; n={kayit['n']}, kuyrukta {kayit['ileti']} ileti / {self._bayt} bayt, boş alan {bos})")

    def koy(self, oge, n=None):
        """Öğeyi sona ekler (diske yazar) ve yazma sonrası `CLOCK_MONOTONIC` ns değerini döndürür. Kapasite yoksa `KuyrukTasmasi` (öğe kuyruğa alınmaz, atılmaz). n: yalnız taşma kaydında kullanılan kare numarası."""
        blob = pickle.dumps(oge, protocol=pickle.HIGHEST_PROTOCOL)
        uz = len(blob)
        with self._k:
            if self._kapali:
                raise RuntimeError(f"kuyruk '{self.ad}' kapalı")
            if self.tasma is not None:
                raise KuyrukTasmasi(f"kuyruk '{self.ad}' daha önce taştı ({self.tasma['neden']}); yeni öğe alınmaz")
            self._yazma_say += 1
            bos = None
            try:
                bos = self._bos_alan()
            except OSError:
                pass
            if bos is not None and bos - uz < self.alt_sinir:
                self._tasma_ver("boş alan alt sınırın altında", uz, n, bos)
            try:
                if self._test_tasma_n is not None and self._yazma_say == self._test_tasma_n:
                    raise OSError(errno.ENOSPC, "TEST: yapay ENOSPC (KUYRUK_TEST_TASMA)")
                if self._yazan is None or self._bolutler[self._yazan]["boyut"] >= self.bolut_bayt:
                    self._yazani_kapat()
                    self._bolut_ac()
                konum = self._bolutler[self._yazan]["boyut"]
                self._yazan_f.write(blob)
                self._yazan_f.flush()
            except OSError as e:
                self._tasma_ver(f"yazma hatası: {e!r}", uz, n, bos)
            b = self._bolutler[self._yazan]
            b["boyut"] += uz
            b["kalan"] += 1
            self._disk_bayt += uz
            bayt = self._bayt_olc(oge) if self._bayt_olc is not None else uz
            self._d.append((self._yazan, konum, uz, bayt))
            self._bayt += bayt
            self.giren += 1
            self.giren_bayt += bayt
            self.maks_ileti = max(self.maks_ileti, len(self._d))
            self.maks_bayt = max(self.maks_bayt, self._bayt)
            self.maks_disk_bayt = max(self.maks_disk_bayt, self._disk_bayt)
            yazildi_ns = time.monotonic_ns()      # yazma sonrası an: kilit altında, tüketici uyandırılmadan ÖNCE (tüketici kareyi bu andan önce almış görünmez)
            self._k.notify_all()
            return yazildi_ns

    # --- okuma ------------------------------------------------------------------------------------------------------------------------------
    def _oku(self, giris):
        no, konum, uz, _bayt = giris
        with open(self._bolutler[no]["yol"], "rb") as f:
            f.seek(konum)
            blob = f.read(uz)
        if len(blob) != uz:
            raise RuntimeError(f"kuyruk '{self.ad}' bölütü eksik okundu (bölüt {no}, konum {konum}, {len(blob)}/{uz} bayt)")
        return pickle.loads(blob)

    def bak(self, zaman_asimi):
        """Başındaki öğeyi ÇIKARMADAN verir; yoksa zaman_asimi sn bekler → öğe ya da None."""
        with self._k:
            if not self._d and not self._kapali:
                self._k.wait(zaman_asimi)
            if not self._d:
                return None
            if self._bas is None:
                self._bas = self._oku(self._d[0])
            return self._bas

    def _cikar_kilitli(self):
        giris = self._d[0]
        oge = self._bas if self._bas is not None else self._oku(giris)     # önce oku: okuma hatasında kuyruk ve sayaçlar bozulmaz
        self._d.popleft()
        self._bas = None
        no, _konum, uz, bayt = giris
        self._bayt -= bayt
        self.cikan += 1
        self.cikan_bayt += bayt
        b = self._bolutler[no]
        b["kalan"] -= 1
        if b["kalan"] == 0 and (no != self._yazan or not self._d):    # tüketilen bölüt silinir (yazılan bölüt yalnız kuyruk boşken)
            if no == self._yazan:
                self._yazani_kapat()
            try:
                os.remove(b["yol"])
            except OSError:
                pass
            self._disk_bayt -= b["boyut"]
            del self._bolutler[no]
        self._temizle_dene()
        self._k.notify_all()
        return oge

    def cikar(self):
        """Başındaki öğeyi çıkarır (gönderim/işlem tamamlandı) ve döndürür."""
        with self._k:
            return self._cikar_kilitli()

    def al(self, zaman_asimi):
        """Bekle + çıkar: öğe varsa çıkarıp döndürür; zaman_asimi sn içinde gelmezse None."""
        with self._k:
            if not self._d and not self._kapali:
                self._k.wait(zaman_asimi)
            if not self._d:
                return None
            return self._cikar_kilitli()

    # --- durum ------------------------------------------------------------------------------------------------------------------------------
    def derinlik(self):
        """(bekleyen ileti sayısı, bekleyen bayt)."""
        with self._k:
            return len(self._d), self._bayt

    def bos_mu(self):
        with self._k:
            return not self._d

    def bos_bekle(self, sure_sn):
        sinir = time.monotonic() + sure_sn
        with self._k:
            while self._d:
                kalan = sinir - time.monotonic()
                if kalan <= 0:
                    return False
                self._k.wait(min(kalan, 0.2))
            return True

    def disk_bayt(self):
        with self._k:
            return self._disk_bayt

    def sayaclar(self):
        with self._k:
            return {"giren": self.giren, "cikan": self.cikan, "giren_bayt": self.giren_bayt, "cikan_bayt": self.cikan_bayt, "maks_ileti": self.maks_ileti, "maks_bayt": self.maks_bayt,
                    "bekleyen": len(self._d), "bekleyen_bayt": self._bayt, "disk_bayt": self._disk_bayt, "maks_disk_bayt": self.maks_disk_bayt}

    # --- kapanış ----------------------------------------------------------------------------------------------------------------------------
    def _temizle_dene(self):
        """Kapalı ve boş kuyruğun bölütlerini ve dizinini siler (kilit altında çağrılır). Boş değilse dokunmaz."""
        if not self._kapali or self._d or self._temiz:
            return
        self._yazani_kapat()
        for b in self._bolutler.values():
            try:
                os.remove(b["yol"])
            except OSError:
                pass
        self._bolutler.clear()
        self._disk_bayt = 0
        try:
            os.rmdir(self.dizin)
        except OSError:
            pass
        if self._gecici_ust:
            try:
                os.rmdir(self._gecici_ust)
            except OSError:
                pass
        self._temiz = True

    def kapat(self):
        """Kuyruğu kapatır (yeni öğe alınmaz; bekleyenler uyanır). Kuyruk boşsa dizin silinir; boş değilse kalan öğe sayısı günlüğe yazılır ve dizin yerinde kalır. İdempotent."""
        with self._k:
            ilk = not self._kapali
            self._kapali = True
            self._yazani_kapat()                  # kuyruk boş olmasa da yazıcı dosya tanıtıcısı kapanır (kapalı kuyruğa yazılmaz; okuma dosyayı yeniden açar)
            self._temizle_dene()
            if ilk and self._d and self._log is not None:
                self._log("kuyruk_kapandi_bos_degil", seviye="(!)", kuyruk=self.ad, kalan_ileti=len(self._d), kalan_bayt=self._bayt, dizin=os.path.basename(self.dizin.rstrip("/")),
                          ayrinti="kalan öğeler dizinde bırakıldı (silinmedi)")
            self._k.notify_all()
