"""Kare sonucu yayımcısı (B11, uçta mod): kare işleyicinin kancasından gelen `FrameResult` iletilerini DDS'e verir (rclpy'siz saf mantık; gerçek yayım işlevi dışarıdan verilir).

Neden kuyruk + ayrı iş parçacığı: kancayı çağıran kare işleme iş parçacığı (çıkarım işçisinin sonucunu bekleyen tüketici) DDS yayımında bloke olmamalıdır: reliable yayımcı yazma geçmişi
dolarsa ya da ağ yavaşsa `publish` bekleyebilir; bu, bir sonraki karenin çıkarımını geciktirirdi. `ver` yalnız kuyruğa koyar (bloke etmez), yayımı tek bir iş parçacığı sırayla yapar
(sıra korunur). Kuyruk bellek içidir ve sınırsızdır (kare başına tek küçük ileti; bir koşuda araç başına en çok birkaç yüz).

Her yayım yerel kayda yazılır: `kayit/arac_sureci_<araç>.jsonl`, `kare_olay` (`kaynak: arac_sureci`, `olay: gonderim`, `mono_ns` = yayım çağrısının döndüğü an, `sim_damga_ns` = karenin
ızgara damgası). Kapanışta kuyruk boşalır ve yayımcının bütün iletilerinin abonelerce onaylanması (`bekle_onay`) beklenir; süre dolarsa açık uyarı günlüğe yazılır.
Test enjeksiyonu (yalnız test, varsayılan kapalı), ortam değişkeni KARE_SONUC_ENJEKSIYON: `gecik=<belirteç>:<sn>[,...]`; belirteç `+k` (n_ilk + k) ya da mutlak numara (`son` desteklenmez: n_son, son karelerin sonucu yayımlandıktan sonra bilinir). O numaranın
iletisi yayımlanmadan önce <sn> gerçek saniye tutulur (diğer iletiler akmaya devam eder); gecikme yalnız yayımı etkiler, yerel kare sonucu kaydı ve araç durum makinesi değişmez.
"""
import json
import os
import queue
import threading
import time

_NS = 10 ** 9


class YayinEnjeksiyonu:
    def __init__(self, metin=""):
        self.gecik = []                      # [(belirteç, saniye)]
        for parca in [p for p in (metin or "").split(";") if p.strip()]:
            anahtar, _, deger = parca.partition("=")
            if anahtar.strip() != "gecik":
                raise ValueError(f"KARE_SONUC_ENJEKSIYON: bilinmeyen anahtar '{anahtar.strip()}'")
            for t in [x for x in deger.split(",") if x.strip()]:
                belirtec, _, sn = t.strip().rpartition(":")
                if not belirtec:
                    raise ValueError(f"KARE_SONUC_ENJEKSIYON: 'gecik' için <belirteç>:<sn> gerekli (bulunan: {t!r})")
                self.gecik.append((belirtec, float(sn)))

    @property
    def acik(self):
        return bool(self.gecik)

    @staticmethod
    def _coz(belirtec, n_ilk):
        if belirtec.startswith("+"):
            return None if n_ilk is None else n_ilk + int(belirtec[1:])
        return int(belirtec)

    def gecikme_sn(self, n, n_ilk):
        for belirtec, sn in self.gecik:
            if self._coz(belirtec, n_ilk) == n:
                return sn
        return 0.0

    def ozet(self):
        return ";".join(f"gecik={b}:{sn:g}" for b, sn in self.gecik) if self.acik else "kapali"


class SonucYayinci:
    def __init__(self, arac_kimligi, hz, yayinla, kayit_yol, log, enjeksiyon_metni=None, onay_bekle=None):
        """yayinla(mesaj): gerçek DDS yayımı. onay_bekle(sn) -> bool: bütün yayımların onaylanmasını bekler (None: bekleme yok)."""
        self.arac_kimligi, self.hz, self.log = int(arac_kimligi), int(hz), log
        self._yayinla, self._onay_bekle, self.kayit_yol = yayinla, onay_bekle, kayit_yol
        self.enj = YayinEnjeksiyonu(enjeksiyon_metni if enjeksiyon_metni is not None else os.environ.get("KARE_SONUC_ENJEKSIYON", ""))
        self.n_ilk = None
        self._q = queue.SimpleQueue()
        self._dosya_kilit = threading.Lock()
        self._is = None
        self._zamanlayicilar = []
        self._k = threading.Lock()
        self.verilen = self.yayimlanan = self.hata_sayisi = 0
        self.kuyruk_maks = 0

    def baslat(self):
        self._is = threading.Thread(target=self._calis, name="sonuc_yayin", daemon=True)
        self._is.start()
        self.log("sonuc_yayin_basladi", enjeksiyon=self.enj.ozet())

    def ver(self, mesaj, n):
        """Kare işleme iş parçacığından çağrılır: yalnız kuyruğa koyar, bloke etmez."""
        with self._k:
            self.verilen += 1
        self._q.put((n, mesaj))
        self.kuyruk_maks = max(self.kuyruk_maks, self._q.qsize())

    def _yaz_gonderim(self, n):
        if not self.kayit_yol:
            return
        d = {"surum": 1, "tur": "kare_olay", "kaynak": "arac_sureci", "arac_kimligi": self.arac_kimligi, "n": n, "sim_damga_ns": n * _NS // self.hz,
             "olay": "gonderim", "mono_ns": time.monotonic_ns()}
        with self._dosya_kilit, open(self.kayit_yol, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def _yayimla_simdi(self, n, mesaj):
        try:
            self._yayinla(mesaj)
        except Exception as e:  # noqa: BLE001
            with self._k:
                self.hata_sayisi += 1
            self.log("sonuc_yayin_hatasi", n=n, hata=repr(e))
            return
        self._yaz_gonderim(n)
        with self._k:
            self.yayimlanan += 1

    def _calis(self):
        while True:
            oge = self._q.get()
            if oge is None:
                return
            n, mesaj = oge
            gecikme = self.enj.gecikme_sn(n, self.n_ilk)
            if gecikme > 0:
                self.log("sonuc_yayin_gecikmeli", n=n, gecikme_sn=gecikme)
                t = threading.Timer(gecikme, self._yayimla_simdi, args=(n, mesaj))
                t.daemon = True
                with self._k:
                    self._zamanlayicilar.append(t)
                t.start()
            else:
                self._yayimla_simdi(n, mesaj)

    def kapat(self, bekle_sn):
        """Kuyruğu boşaltır (gecikmeli iletiler dahil), yayımcı onaylarını bekler. Dönen: (hepsi_yayimlandi, onaylandi)."""
        self._q.put(None)
        if self._is is not None:
            self._is.join(max(bekle_sn, 1.0))
        sinir = time.monotonic() + bekle_sn
        for t in list(self._zamanlayicilar):
            t.join(max(0.0, sinir - time.monotonic()))
        with self._k:
            tamam = self.yayimlanan + self.hata_sayisi >= self.verilen
        onay = True
        if tamam and self._onay_bekle is not None:
            onay = bool(self._onay_bekle(max(0.0, sinir - time.monotonic())))
        if not tamam:
            self.log("sonuc_yayin_uyari", neden="kapanışta yayımlanmamış ileti var", verilen=self.verilen, yayimlanan=self.yayimlanan, hata=self.hata_sayisi)
        elif not onay:
            self.log("sonuc_yayin_uyari", neden="iletiler abonelerce onaylanmadı (zaman aşımı)", bekle_sn=bekle_sn)
        self.log("sonuc_yayin_ozet", verilen=self.verilen, yayimlanan=self.yayimlanan, hata=self.hata_sayisi, onaylandi=onay, kuyruk_maks=self.kuyruk_maks)
        return tamam, onay
