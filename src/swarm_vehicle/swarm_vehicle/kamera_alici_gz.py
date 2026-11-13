"""Kamera alıcısının gz-transport tarafı (B8): aracın kamera konusuna DOĞRUDAN abone olur (ros_gz_bridge yok), kareleri `kamera_alici.KameraAlici` mantığına verir,
her kare olayını koşu klasöründe KENDİ dosyasına (kayit/kamera_alici_<araç kimliği>.jsonl) `kare_olay` şemasıyla yazar. Kabul edilen görev kareleri iç kuyruğa verilir;
kuyruk tüketicisi (bu sürümde) yalnız sayar ve numarayı kaydeder, kareyi bellekte biriktirmez (çıkarım işçisi sonraki adımda bağlanır). Görüntü verisi saklanmaz;
yalnız boyutu denetlenir (CAM_WIDTH × CAM_HEIGHT × 3 bayt, RGB8, sıkıştırmasız).
Hata enjeksiyonu (yalnız test, varsayılan kapalı): ortam değişkeni KAMERA_ENJEKSIYON (bkz. kamera_alici.Enjeksiyon); durumu aracın günlüğüne yazılır.
Kanal: gz-transport geri çağrı iş parçacığı → (isteğe bağlı gecikme hattı iş parçacığı) → mantık (kilit altında) → kuyruk → tüketici iş parçacığı.
"""
import collections
import json
import os
import queue
import threading
import time

from .kamera_alici import Enjeksiyon, KameraAlici


class KameraAliciGz:
    def __init__(self, ham, arac_no, arac_kimligi, kayit_yol, log, enjeksiyon_metni=None):
        self.ham, self.arac_no, self.arac_kimligi, self.log = ham, arac_no, arac_kimligi, log
        self.hz = int(float(ham["CAM_RATE_HZ"]))
        self.w, self.h = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
        onek = ham["SIM_MODEL"].removeprefix("gz_")
        self.konu = (f"/world/{ham['SIM_WORLD']}/model/{onek}_{arac_no - 1}/link/{ham['KAMERA_LINK']}/sensor/{ham['KAMERA_ALGILAYICI']}/image")
        self.kayit_yol = kayit_yol
        self._dosya_kilit = threading.Lock()
        self._k = threading.RLock()
        self.enj = Enjeksiyon(enjeksiyon_metni if enjeksiyon_metni is not None else os.environ.get("KAMERA_ENJEKSIYON", ""))
        self.alici = KameraAlici(arac_kimligi, self.hz, self._yaz, self._kuyruga, ham.get("KARE_NUMARALAMA", "izgara"))
        self._q = queue.SimpleQueue()
        self.tuketilen, self.tuketilen_son = 0, -1
        self.alinan, self.boyut_hatasi, self.ilk_bilgi = 0, 0, None
        self.dusurulen, self._tutulan = [], []
        self._bekleme = collections.deque()
        self._dur = threading.Event()
        self._ipler = []
        self._node = None
        self.ilk_damga_ns = None

    # --- kayıt ve kuyruk ----------------------------------------------------------------------------------------------------------------------
    def _yaz(self, d):
        if self.kayit_yol:
            with self._dosya_kilit, open(self.kayit_yol, "a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def _kuyruga(self, n, damga_ns, mono_ns):
        self._q.put(n)

    def _tuket(self):
        while not self._dur.is_set() or not self._q.empty():
            try:
                n = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
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
            return self.alici.tarama_basladi(t_s_ns)

    def tarama_bitti(self, t_b_ns):
        with self._k:
            return self.alici.tarama_bitti(t_b_ns)

    def son_numara(self):
        return self.alici.son_gorev_numarasi

    def kapat(self):
        self._dur.set()
        for t in self._ipler:
            t.join(2)
        with self._k:
            a = self.alici
            self.log("kamera_alici_ozet", alinan=self.alinan, gorev=a.sayac["gorev"], kare_alinamadi=a.sayac["kare_alinamadi"], gec_geldi=a.sayac["gec_geldi"],
                     gorev_oncesi=a.sayac["gorev_oncesi"], kapanis_sonrasi=a.sayac["kapanis_sonrasi"], izgara_disi=a.sayac["izgara_disi"], tekrar=a.sayac["tekrar"],
                     boyut_hatasi=self.boyut_hatasi, n_ilk=a.n_ilk, n_son=a.n_son, kuyruktan_tuketilen=self.tuketilen, son_tuketilen=self.tuketilen_son,
                     dusurulen=",".join(map(str, self.dusurulen)) or "yok", gorev_siniri_asildi=a.sayac["gorev_siniri_asildi"])
