"""Kamera alıcısının gz-transport tarafı (B8): aracın kamera konusuna DOĞRUDAN abone olur (ros_gz_bridge yok), kareleri `kamera_alici.KameraAlici` mantığına verir,
her kare olayını koşu klasöründe KENDİ dosyasına (kayit/kamera_alici_<araç kimliği>.jsonl) `kare_olay` şemasıyla yazar. Kabul edilen görev kareleri iç kuyruğa (numara + görüntü baytları) verilir; kuyruk tüketicisi `tuketici(n, damga_ns, mono_ns, veri, w, h)` geri çağrısını çağırır (araç süreci:
çıkarım işçisine gönderir; geri çağrı yoksa yalnız sayar). İç kuyruk disk destekli `DiskKuyrugu`dur (`<koşu>/kuyruk/kamera_<araç>/`, B13): sınırsızdır, kare atılmaz; kapasite taşmasında (`KuyrukTasmasi`) kare ATILMAZ ama kuyruğa da girmez: açık hata (`hata` alanı, günlük `kamera_kuyrugu_hata`, `kuyruk_tasmasi` kaydı), araç süreci hata çıkışı yapar. Görüntü baytları yalnız son
birkaç karenin önbelleğinde (damgaya göre) ve kuyruktaki karelerde tutulur. Kare boyutu denetlenir (CAM_WIDTH × CAM_HEIGHT × 3 bayt, RGB8, sıkıştırmasız); bozuk boyutlu kare de
kuyruğa girer (işçi onu işlem hatası yapar).
Hata enjeksiyonu (yalnız test, varsayılan kapalı): ortam değişkeni KAMERA_ENJEKSIYON (bkz. kamera_alici.Enjeksiyon); durumu aracın günlüğüne yazılır.
Kanal: gz-transport geri çağrı iş parçacığı → (isteğe bağlı gecikme hattı iş parçacığı) → mantık (kilit altında) → kuyruk → tüketici iş parçacığı.
"""
import collections
import json
import os
import threading
import time

from .disk_kuyrugu import KuyrukTasmasi, kuyruk_olustur
from .kamera_alici import Enjeksiyon, KameraAlici


class KameraAliciGz:
    def __init__(self, ham, arac_no, arac_kimligi, kayit_yol, log, enjeksiyon_metni=None, tuketici=None, kayip_ver=None, kayip_sirali=False, kuyruk_dizin=None, tasma_yol=None, aktarim_uygulanmaz=True):
        self.ham, self.arac_no, self.arac_kimligi, self.log = ham, arac_no, arac_kimligi, log
        self.hz = int(float(ham["CAM_RATE_HZ"]))
        self.w, self.h = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
        onek = ham["SIM_MODEL"].removeprefix("gz_")
        self.konu = (f"/world/{ham['SIM_WORLD']}/model/{onek}_{arac_no - 1}/link/{ham['KAMERA_LINK']}/sensor/{ham['KAMERA_ALGILAYICI']}/image")
        self.kayit_yol = kayit_yol
        self._dosya_kilit = threading.Lock()
        self._k = threading.RLock()
        self.enj = Enjeksiyon(enjeksiyon_metni if enjeksiyon_metni is not None else os.environ.get("KAMERA_ENJEKSIYON", ""))
        self._kayip_tuketici = kayip_ver if kayip_sirali else None     # merkezi mod: 'kare alınamadı' da görüntülerle AYNI kuyruktan, sırasını koruyarak tüketilir
        self.alici = KameraAlici(arac_kimligi, self.hz, self._yaz, self._kuyruga, ham.get("KARE_NUMARALAMA", "izgara"), self._kayip_kuyruga if kayip_sirali else kayip_ver, aktarim_uygulanmaz=aktarim_uygulanmaz)
        self.tuketici = tuketici
        if kuyruk_dizin is None:                        # yalnız birim/duman testleri: geçici dizin (koşu içinde araç süreci her zaman koşu klasörünü verir)
            import tempfile
            gecici_ust = tempfile.mkdtemp(prefix="kamera_kuyrugu_")
            kuyruk_dizin = os.path.join(gecici_ust, f"kamera_{arac_kimligi}")
        else:
            gecici_ust = None
        self._kayip_sirali = bool(kayip_sirali)
        self._q = kuyruk_olustur(f"kamera_{arac_kimligi}", kuyruk_dizin, ham, log, tasma_yol=tasma_yol, gecici_ust=gecici_ust)
        self.hata = None                                 # ilk kuyruk taşması metni (doluysa araç süreci hata çıkışı yapar)
        self.tasan = 0                                   # kuyruğa alınamayan kare sayısı (atılmadı: açık hata)
        self._veri = collections.OrderedDict()           # damga_ns → (genişlik, yükseklik, bayt): son kareler (kuyruğa verilirken görüntüyü bulmak için)
        self.kuyruk_maks = 0
        self.tuketilen, self.tuketilen_son = 0, -1
        self.alinan, self.boyut_hatasi, self.ilk_bilgi = 0, 0, None
        self.dusurulen, self._tutulan = [], []
        self._bekleme = collections.deque()
        self._dur = threading.Event()
        self._ipler = []
        self._node = None
        self.ilk_damga_ns = None
        self.ilk_alim_mono_ns = self.son_alim_mono_ns = None     # gz geri çağrılarının ilk/son alım anı (gerçek üretim hızı için)

    # --- kayıt ve kuyruk ----------------------------------------------------------------------------------------------------------------------
    def _yaz(self, d):
        if self.kayit_yol:
            with self._dosya_kilit, open(self.kayit_yol, "a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def _koy(self, n, oge):
        """Kareyi disk kuyruğuna yazar. Dönen: yazma sonrası mono_ns; taşmada False (kare atılmadı, kuyruğa alınmadı; açık hata kaydı)."""
        try:
            yazildi_ns = self._q.koy(oge, n=n)
        except KuyrukTasmasi as e:
            self.tasan += 1
            if self.hata is None:
                self.hata = f"kamera kuyruğu taştı: {e}"
                self.log("kamera_kuyrugu_hata", seviye="(-)", neden=str(e).replace(" ", "_"))
            return False
        except Exception as e:  # noqa: BLE001  (beklenmeyen disk/serileştirme hatası da açık hata: sessiz kayıp yok)
            self.tasan += 1
            if self.hata is None:
                self.hata = f"kamera kuyruğuna yazılamadı: {e!r}"
                self.log("kamera_kuyrugu_hata", seviye="(-)", neden=repr(e).replace(" ", "_"))
            return False
        self.kuyruk_maks = max(self.kuyruk_maks, self._q.derinlik()[0])
        return yazildi_ns                                 # `DiskKuyrugu.koy`un yazma sonrası anı (tüketici kareyi bu andan önce almış görünmez)

    def _kuyruga(self, n, damga_ns, mono_ns):
        w, h, veri = self._veri.get(damga_ns, (0, 0, b""))
        return self._koy(n, (n, damga_ns, mono_ns, veri, w, h))

    def _kayip_kuyruga(self, n, mono_ns):
        self._koy(n, (n, n * 10 ** 9 // self.hz, mono_ns, None, 0, 0))       # veri None: 'kare alınamadı' işareti

    def _tuket(self):
        while not self._dur.is_set() or not self._q.bos_mu():
            try:
                oge = self._q.al(0.2)
            except Exception as e:  # noqa: BLE001  (disk okuma hatası: açık hata, kuyruk durur)
                if self.hata is None:
                    self.hata = f"kamera kuyruğu okunamadı: {e!r}"
                    self.log("kamera_kuyrugu_hata", seviye="(-)", neden=repr(e).replace(" ", "_"))
                return
            if oge is None:
                continue
            n, damga, mono, veri, w, h = oge
            if veri is None:
                try:
                    self._kayip_tuketici(n, mono)
                except Exception as e:  # noqa: BLE001
                    self.log("tuketici_hatasi", n=n, hata=repr(e))
            elif self.tuketici is not None:
                derinlik = self._q.derinlik()[0]
                if derinlik >= 1:
                    self.log("kuyruk_derinligi", n=n, bekleyen=derinlik)
                try:
                    self.tuketici(n, damga, mono, veri, w, h)
                except Exception as e:  # noqa: BLE001
                    self.log("tuketici_hatasi", n=n, hata=repr(e))
            self.tuketilen += 1
            self.tuketilen_son = n

    # --- gz-transport -----------------------------------------------------------------------------------------------------------------------
    def baslat(self):
        from gz.msgs10.image_pb2 import Image
        from gz.transport13 import Node
        self._node = Node()
        if not self._node.subscribe(Image, self.konu, self._gz_geri_cagrisi):
            raise RuntimeError(f"kamera konusuna abonelik kurulamadı: {self.konu}")
        self.log("kamera_alici_basladi", konu=self.konu, hz=self.hz, boyut=f"{self.w}x{self.h}", kayit=os.path.basename(self.kayit_yol or "-"))
        self.log("kamera_enjeksiyon", durum=self.enj.ozet())
        self._ipler = [threading.Thread(target=self._tuket, name="kamera_tuketici", daemon=True)]
        if self.enj.bekle_sn > 0:
            self._ipler.append(threading.Thread(target=self._bekleme_hatti, name="kamera_bekleme", daemon=True))
        for t in self._ipler:
            t.start()

    def _gz_geri_cagrisi(self, m):
        mono = time.monotonic_ns()                        # alım anı: geri çağrının girişi
        damga = m.header.stamp.sec * 10 ** 9 + m.header.stamp.nsec
        self.alinan += 1
        if self.ilk_alim_mono_ns is None:
            self.ilk_alim_mono_ns = mono
        self.son_alim_mono_ns = mono
        self._veri[damga] = (m.width, m.height, m.data)
        while len(self._veri) > 16:
            self._veri.popitem(last=False)
        if self.ilk_bilgi is None:
            self.ilk_bilgi = (m.width, m.height, len(m.data), int(m.pixel_format_type))
            self.ilk_damga_ns = damga
            self.log("kamera_ilk_kare", genislik=m.width, yukseklik=m.height, bayt=len(m.data), piksel_bicimi=int(m.pixel_format_type), damga_ns=damga)
        if (m.width, m.height) != (self.w, self.h) or len(m.data) != self.w * self.h * 3:
            self.boyut_hatasi += 1
        if self.enj.bekle_sn > 0:
            self._bekleme.append((mono + int(self.enj.bekle_sn * 1e9), damga))
            return
        self._isle(damga, mono)

    def _bekleme_hatti(self):
        while not self._dur.is_set():
            simdi = time.monotonic_ns()
            while self._bekleme and self._bekleme[0][0] <= simdi:
                _, damga = self._bekleme.popleft()
                self._isle(damga, time.monotonic_ns())
            time.sleep(0.01)

    def _isle(self, damga, mono):
        from .kamera_alici import n_hesapla
        with self._k:
            n = n_hesapla(damga, self.hz)
            if n is not None and self.enj.dusur_mu(n, self.alici):
                self.dusurulen.append(n)
                return
            if n is not None and self.enj.gecik_mi(n, self.alici) and n not in self.alici.alinamadi and (n, damga) not in self._tutulan:
                self._tutulan.append((n, damga))          # kayıp kaydı yazılana dek tutulur
                return
            self.alici.kare(damga, mono)
            for n2, d2 in list(self._tutulan):
                if n2 in self.alici.alinamadi:            # kayıt yazıldı: şimdi teslim et (→ "geç geldi")
                    self._tutulan.remove((n2, d2))
                    self.alici.kare(d2, time.monotonic_ns())

    # --- araç sürecinden gelen olaylar --------------------------------------------------------------------------------------------------------
    def tarama_basladi(self, t_s_ns):
        with self._k:
            return self.alici.tarama_basladi(t_s_ns, time.monotonic_ns())

    def tarama_bitti(self, t_b_ns):
        with self._k:
            return self.alici.tarama_bitti(t_b_ns)

    def son_numara(self):
        return self.alici.son_gorev_numarasi

    def kapanis_kapat_zorla(self):
        """Kapanış karesi gelmediyse sondaki kayıpları şimdi kapatır (bkz. KameraAlici.kapat_zorla). Dönen: kayıp numaraları."""
        with self._k:
            return self.alici.kapat_zorla(time.monotonic_ns())

    def kapat(self):
        self._dur.set()
        for t in self._ipler:
            t.join(2)
        kalan, _ = self._q.derinlik()                    # kapanışta kuyrukta kalan (tüketilmemiş) öğe sayısı
        sy = self._q.sayaclar()
        self._q.kapat()                                   # boşsa dizin silinir; değilse kalan öğe sayısı günlüğe yazılır, dizin yerinde kalır
        with self._k:
            a = self.alici
            self.log("kamera_alici_ozet", alinan=self.alinan, gorev=a.sayac["gorev"], kare_alinamadi=a.sayac["kare_alinamadi"], gec_geldi=a.sayac["gec_geldi"],
                     gorev_oncesi=a.sayac["gorev_oncesi"], kapanis_sonrasi=a.sayac["kapanis_sonrasi"], izgara_disi=a.sayac["izgara_disi"], tekrar=a.sayac["tekrar"],
                     boyut_hatasi=self.boyut_hatasi, n_ilk=a.n_ilk, n_son=a.n_son, kuyruktan_tuketilen=self.tuketilen, son_tuketilen=self.tuketilen_son, kuyruk_maks=self.kuyruk_maks, kuyruga_alinamadi=self.tasan, kuyruga_giren=sy["giren"], kuyrukta_kalan=kalan, kayip_kuyruga=a.sayac["kare_alinamadi"] if self._kayip_sirali else 0, son_n=a.son_gorev_numarasi, disk_kuyruk_maks_bayt=sy["maks_disk_bayt"], kuyruk_hata=str(self.hata or "yok").replace(" ", "_"), gorev_oncesi_kabul=a.sayac["gorev_oncesi_kabul"], kapanis_zorla=a.sayac["kapanis_zorla"],
                     dusurulen=",".join(map(str, self.dusurulen)) or "yok", gorev_siniri_asildi=a.sayac["gorev_siniri_asildi"])
