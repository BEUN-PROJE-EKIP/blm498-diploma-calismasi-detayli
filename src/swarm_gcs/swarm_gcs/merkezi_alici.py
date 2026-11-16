"""Yer istasyonu merkezi mod alıcısı (B12; FR-14, FR-15, FR-12): araç başına TCP görüntü kanalını dinler, iletileri doğrular ve araç başına işleme kuyruğuna verir. rclpy kullanılmaz (DDS yok).

Akış (araç başına): dinleme soketi (`GCS_ADDR:MERKEZI_TCP_PORT_TABAN + k − 1`) → bağlantı kabulü (kaynak adres = aracın `UAVn_ADDR`'ı olmalı; başkası reddedilir ve günlüğe yazılır) → okuma iş parçacığı
(akış çözücü; iletiler parçalı gelebilir) → doğrulama (porta göre beklenen araç kimliği, sihirli değer/sürüm, artan kare numarası) → `alim` kare olayı → araç başına işleme kuyruğu (SINIRSIZ, atma yok) →
işleme iş parçacığı (araca ayrılmış çıkarım işçisi: `KareIsleyici` → kare sonucu) → sonuç defteri.
Sonuç, uçta moddaki AYNI mantıksal yapıdır: `KareIsleyici` (swarm_vehicle) aynı dört durumu, aynı kayıt şemasını (`kayit/kare_sonuc_<araç>.jsonl`) ve aynı kancayı (→ `SonucAlici.sonuc_ver` → sonuç defteri +
`kullanilabilir` kaydı) kullanır; "kare alınamadı" iletisi aynı yapıya (`STATUS_FRAME_NOT_RECEIVED`) çevrilir. Alınan poz sonuç kaydında `poz` alanında saklanır (B14 kullanacak; `has_position` bu sürümde False).
Doğrulama kuralları: tekrar eden numara ve geriye giden numara SAYILIR ve günlüğe yazılır (işlenmez); atlanan numara (boşluk) sayılır ve günlüğe yazılır (kayıp kare ancak "kare alınamadı" iletisiyle bildirilir; eksik numara COMPLETE'i
engeller); aralık dışı numara sonuç defterinde sayılır (tarama bitişi bildirimi gelince). Bozuk ileti açık hata: bağlantı kapatılır, `hata` alanı dolar. Bağlantı koptuğunda yeniden bağlanma yoktur.
Temiz kapanış: bağlantı yarım iletisiz kapanırsa ve o aracın sonuç defteri tamam değilse (tarama bitişi gelmemiş ya da [n_ilk, n_son] eksik; alınan her ileti işlendikten sonra denetlenir) kanal hatası doldurulur
(`bağlantı araç tamamlanmadan kapandı`); defter tamamken kapanış normaldir. İşleme kuyruğu derinliği (`MERKEZI_KUYRUK_KAYIT_SN` aralıkla) `isleme_yaz` ile kaydedilir.
Test anahtarları (yalnız test, varsayılan kapalı): ortam değişkeni MERKEZI_ENJEKSIYON=`okuma_dur=<başlangıç_sn>:<süre_sn>` (ilk ileti alındıktan <başlangıç_sn> sonra <süre_sn> sn okuma durur; geri basınç sınaması) ve
MERKEZI_SHA=1 (alınan görüntü baytlarının SHA-256'sı `kayit/merkezi_sha_alim_<araç>.jsonl` dosyasına yazılır).
"""
import hashlib
import os
import queue
import socket
import threading
import time

from swarm_vehicle import goruntu_ileti as gi
from swarm_vehicle import port_denetimi as _port

_NS = 10 ** 9


def okuma_dur_ayristir(metin):
    """MERKEZI_ENJEKSIYON → (başlangıç_sn, süre_sn) ya da None."""
    if not (metin or "").strip():
        return None
    anahtar, _, deger = metin.strip().partition("=")
    if anahtar != "okuma_dur":
        raise ValueError(f"MERKEZI_ENJEKSIYON: bilinmeyen anahtar '{anahtar}'")
    b, _, d = deger.partition(":")
    return float(b), float(d)


class KanalDurumu:
    """Bir aracın kanalının sayaçları ve durumu."""

    def __init__(self, arac_kimligi, port, beklenen_adres):
        self.arac_kimligi, self.port, self.beklenen_adres = arac_kimligi, port, beklenen_adres
        self.bagli = False
        self.baglanti_mono_ns = self.kapanis_mono_ns = None
        self.ilk_alim_mono_ns = self.son_alim_mono_ns = None
        self.hata = None
        self.alinan_ileti = self.goruntu = self.kare_alinamadi = 0
        self.alinan_bayt = 0
        self.tekrar = self.geriye = self.atlanan = self.kalibrasyon_uyumsuz = 0
        self.reddedilen_baglanti = 0
        self.son_n = None
        self.islenen = 0
        self.kuyruga_giren = 0
        self.islem_kuyrugu_maks = 0
        self.temiz_kapandi = False


class MerkeziAlici:
    def __init__(self, ham, arac_kimlikleri, log, islemciler, olay_yaz=None, sha_yaz=None, enjeksiyon_metni=None, kalibrasyon_kimligi=None, defter_tamam=None, isleme_yaz=None, port_denetimi=True):
        """islemciler: {araç kimliği: işleyici}; işleyici `goruntu(n, damga_ns, mono_ns, veri, w, h, merkez_poz=...)` ve `kayip(n, mono_ns, merkez_poz=...)` sağlar (KareIsleyici).
        olay_yaz(sözlük): `alim` kare olayları (bloke etmez). sha_yaz(araç, sözlük): yalnız test (MERKEZI_SHA=1).
        defter_tamam(araç) → bool: aracın sonuç defteri tamam mı (temiz kapanış denetimi; None ise denetim yok). isleme_yaz(araç, sözlük): işleme kuyruğu durum kaydı (bloke etmez; None ise kayıt yok)."""
        self.ham, self.log = ham, log
        self.kimlikler = [int(a) for a in arac_kimlikleri]
        tum = [int(a) for a in ham["UAV_SYS_IDS"].split()]
        self.islemciler, self._olay_yaz, self._sha_yaz = islemciler, olay_yaz, sha_yaz
        self._defter_tamam, self._isleme_yaz = defter_tamam, isleme_yaz
        self._kayit_kilit = threading.Lock()                 # kuyruk durumu kaydı: anlık görüntü + mono_ns + yazıcıya verme tek kilit altında (sıra geriye gitmez)
        self._say_kilit = threading.Lock()                   # işleme kuyruğu sayaçları (giren/işlenen) tutarlı okunsun
        self.kuyruk_kayit_sn = float(ham["MERKEZI_KUYRUK_KAYIT_SN"])
        self.hz = int(float(ham["CAM_RATE_HZ"]))
        self.w, self.h = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
        self.kal = kalibrasyon_kimligi
        self.port_denetimi = port_denetimi   # birim testleri işletim sisteminin verdiği (geçici aralıktaki) boş portları kullanır; gerçek koşuda hep açık
        self.yuk_maks = int(ham["MERKEZI_YUK_MAKS_BAYT"])
        self.okuma_dur = okuma_dur_ayristir(enjeksiyon_metni if enjeksiyon_metni is not None else os.environ.get("MERKEZI_ENJEKSIYON", ""))
        self._dur = threading.Event()
        self.durum, self._dinle, self._kuyruk, self._ipler = {}, {}, {}, []
        taban = int(ham["MERKEZI_TCP_PORT_TABAN"])
        for a in self.kimlikler:
            sira = tum.index(a) + 1
            self.durum[a] = KanalDurumu(a, taban + sira - 1, ham[f"UAV{sira}_ADDR"])
            self._kuyruk[a] = queue.SimpleQueue()
        self.gcs_adres = ham["GCS_ADDR"]
        self._ilk_alim_mono = None

    # --- başlatma ---------------------------------------------------------------------------------------------------------------------------
    def baslat(self):
        if self.port_denetimi:   # hiçbir soket açılmadan önce: sabit dinleme portları geçici port aralığının dışında olmalı
            for a in self.kimlikler:
                _port.denetle(self.durum[a].port, f"merkezi mod dinleme (araç {a})")
        for a in self.kimlikler:
            d = self.durum[a]
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.gcs_adres, d.port))                 # ölçülen sürü ağı adresi; yerel döngü adresi kullanılmaz
            s.listen(1)
            s.settimeout(0.5)
            self._dinle[a] = s
            self.log("merkezi_dinleme", arac=a, adres=f"{self.gcs_adres}:{d.port}", beklenen_kaynak=d.beklenen_adres)
            for ad, hedef in (("oku", self._oku_dongusu), ("isle", self._isle_dongusu)):
                t = threading.Thread(target=hedef, args=(a,), name=f"merkezi_{ad}_{a}", daemon=True)
                t.start()
                self._ipler.append(t)
        if self._isleme_yaz is not None:
            t = threading.Thread(target=self._kuyruk_kaydi, name="merkezi_kuyruk_kaydi", daemon=True)
            t.start()
            self._ipler.append(t)

    def bagli_mi(self, arac):
        d = self.durum[int(arac)]
        return d.bagli and d.hata is None

    def hata_var(self):
        """Açık kanal hatası olan araçlar: {araç: metin}. Koordinatörün ana döngüsü sık çağırır; temiz kapanmış kanalların defter denetimi de buradadır."""
        for a in self.kimlikler:
            self._kapanis_denetle(a)
        return {a: d.hata for a, d in self.durum.items() if d.hata}

    def _kapanis_denetle(self, a):
        """Bağlantı yarım iletisiz (temiz) kapandıysa: alınan her ileti işlendikten sonra aracın sonuç defteri hâlâ tamam değilse açık hata (yeniden bağlanma yok; koşu tamamlanamaz)."""
        d = self.durum[a]
        if not d.temiz_kapandi or d.hata or self._defter_tamam is None:
            return
        with self._say_kilit:
            islendi = d.islenen >= d.kuyruga_giren
        if not islendi or self._defter_tamam(a):
            return
        d.hata = f"bağlantı araç tamamlanmadan kapandı ({d.alinan_ileti} ileti alınmıştı; sonuç defteri tamam değil)"
        self.log("merkezi_kanal_hatasi", arac=a, neden=d.hata.replace(" ", "_"))

    # --- okuma ------------------------------------------------------------------------------------------------------------------------------
    def _kabul(self, a):
        d, s = self.durum[a], self._dinle[a]
        while not self._dur.is_set():
            try:
                c, adr = s.accept()
            except socket.timeout:
                continue
            except OSError:
                return None
            if adr[0] != d.beklenen_adres:
                d.reddedilen_baglanti += 1
                self.log("merkezi_baglanti_reddedildi", arac=a, kaynak=f"{adr[0]}:{adr[1]}", beklenen=d.beklenen_adres)
                c.close()
                continue
            return c, adr
        return None

    def _oku_dongusu(self, a):
        d = self.durum[a]
        try:
            kabul = self._kabul(a)
            if kabul is None:
                return
            c, adr = kabul
            c.settimeout(1.0)
            d.bagli, d.baglanti_mono_ns = True, time.monotonic_ns()
            self.log("merkezi_baglandi", arac=a, kaynak=f"{adr[0]}:{adr[1]}", port=d.port)
            cozucu = gi.AkisCozucu(beklenen_arac=a, yuk_maks=self.yuk_maks)
            tampon = bytearray(1 << 20)
            gorunum = memoryview(tampon)
            while not self._dur.is_set():
                self._okuma_dur_bekle(d)
                try:
                    k = c.recv_into(tampon)
                except socket.timeout:
                    continue
                except OSError as e:
                    d.hata = f"okuma hatası: {e!r}"
                    break
                if k == 0:
                    if cozucu.bekleyen_bayt():
                        d.hata = f"bağlantı yarım iletiyle kapandı ({cozucu.bekleyen_bayt()} bayt bekliyordu; {cozucu.cozulen} ileti alınmıştı)"
                    break
                d.alinan_bayt += k
                try:
                    iletiler = cozucu.besle(bytes(gorunum[:k]))
                except gi.IletiHatasi as e:
                    d.hata = f"bozuk ileti: {e}"
                    break
                mono = time.monotonic_ns()
                for il in iletiler:
                    self._ileti(a, il, mono)
            d.kapanis_mono_ns = time.monotonic_ns()
            d.bagli = False
            if d.hata:
                self.log("merkezi_kanal_hatasi", arac=a, neden=d.hata.replace(" ", "_"))
            else:
                d.temiz_kapandi = True
                self.log("merkezi_kanal_kapandi", arac=a, alinan=d.alinan_ileti, alinan_bayt=d.alinan_bayt)
            try:
                c.close()
            except OSError:
                pass
        except Exception as e:  # noqa: BLE001
            d.hata = f"beklenmeyen okuma hatası: {e!r}"
            d.bagli = False
            self.log("merkezi_kanal_hatasi", arac=a, neden=d.hata.replace(" ", "_"))

    def _okuma_dur_bekle(self, d):
        """Test anahtarı: ilk iletiden `başlangıç_sn` sonra `süre_sn` boyunca OKUMAYI durdurur (TCP geri basıncı; gönderici bekler, kuyruk büyür)."""
        if self.okuma_dur is None or self._ilk_alim_mono is None:
            return
        bas, sure = self.okuma_dur
        simdi = (time.monotonic_ns() - self._ilk_alim_mono) / _NS
        if bas <= simdi < bas + sure:
            self.log("merkezi_okuma_durdu", arac=d.arac_kimligi, sure_sn=f"{bas + sure - simdi:.1f}")
            self._dur.wait(bas + sure - simdi)
            self.log("merkezi_okuma_surdu", arac=d.arac_kimligi)

    def _ileti(self, a, il, mono):
        d = self.durum[a]
        d.alinan_ileti += 1
        if self._ilk_alim_mono is None:
            self._ilk_alim_mono = mono
        d.ilk_alim_mono_ns = d.ilk_alim_mono_ns or mono
        d.son_alim_mono_ns = mono
        if self.kal is not None and il.kalibrasyon_kimligi != self.kal:
            d.kalibrasyon_uyumsuz += 1
            self.log("merkezi_kalibrasyon_uyusmuyor", arac=a, n=il.n, alinan=il.kalibrasyon_kimligi, beklenen=self.kal)
        if d.son_n is not None:
            if il.n == d.son_n:
                d.tekrar += 1
                self.log("merkezi_tekrar_numara", arac=a, n=il.n)
                return
            if il.n < d.son_n:
                d.geriye += 1
                self.log("merkezi_geriye_giden_numara", arac=a, n=il.n, son=d.son_n)
                return
            if il.n > d.son_n + 1:
                d.atlanan += il.n - d.son_n - 1
                self.log("merkezi_atlanan_numara", arac=a, ilk=d.son_n + 1, son=il.n - 1)
        d.son_n = il.n
        if il.goruntu_mu:
            d.goruntu += 1
        else:
            d.kare_alinamadi += 1
        if self._olay_yaz is not None:
            self._olay_yaz({"surum": 1, "tur": "kare_olay", "kaynak": "yer_istasyonu", "arac_kimligi": a, "n": il.n, "sim_damga_ns": il.damga_ns, "olay": "alim", "mono_ns": mono})
        if self._sha_yaz is not None and il.goruntu_mu:
            self._sha_yaz(a, {"n": il.n, "sha256": hashlib.sha256(il.yuk).hexdigest(), "bayt": len(il.yuk)})
        with self._say_kilit:
            d.kuyruga_giren += 1
        self._kuyruk[a].put((il, mono))
        d.islem_kuyrugu_maks = max(d.islem_kuyrugu_maks, self._kuyruk[a].qsize())

    # --- işleme -----------------------------------------------------------------------------------------------------------------------------
    def _isle_dongusu(self, a):
        d, q, isl = self.durum[a], self._kuyruk[a], self.islemciler[a]
        istemci = getattr(isl, "istemci", None)
        while not (self._dur.is_set() and q.empty()):
            try:
                il, mono = q.get(timeout=0.2)
            except queue.Empty:
                continue
            if istemci is not None and getattr(istemci, "n_ilk", 1) is None:
                istemci.n_ilk = il.n                       # işçi enjeksiyonu belirteçleri (+k): ilk ileti n_ilk'tir (kare alınamadı iletileri de sıradadır)
            poz = il.poz
            try:
                if il.goruntu_mu:
                    isl.goruntu(il.n, il.damga_ns, mono, il.yuk, self.w, self.h, merkez_poz=poz)
                else:
                    isl.kayip(il.n, mono, merkez_poz=poz)
            except Exception as e:  # noqa: BLE001
                self.log("merkezi_isleme_hatasi", arac=a, n=il.n, hata=repr(e))
            with self._say_kilit:
                d.islenen += 1

    def _kuyruk_kaydi(self):
        """İşleme kuyruğu derinliğinin periyodik kaydı (araç kuyruğu yalnız ağ kaynaklı birikmeyi gösterir; merkezdeki çıkarım birikmesi burada ayrı görünür)."""
        while not self._dur.wait(self.kuyruk_kayit_sn):
            self.kuyruk_durumu_kaydet()

    def kuyruk_durumu_kaydet(self):
        if self._isleme_yaz is None:
            return
        with self._kayit_kilit:                                        # periyodik iş parçacığı ile kapanış kaydı aynı anda yazamaz
            for a in self.kimlikler:
                d = self.durum[a]
                with self._say_kilit:
                    giren, islenen = d.kuyruga_giren, d.islenen        # tek kilit altında tutarlı anlık görüntü
                self._isleme_yaz(a, {"surum": 1, "tur": "isleme_kuyrugu", "arac_kimligi": a, "mono_ns": time.monotonic_ns(), "ileti": giren - islenen,
                                     "giren_ileti": giren, "islenen_ileti": islenen})

    # --- kapanış ----------------------------------------------------------------------------------------------------------------------------
    def kuyruk_bos_mu(self):
        return all(q.empty() for q in self._kuyruk.values())

    def ozet(self):
        return {a: {"alinan_ileti": d.alinan_ileti, "goruntu": d.goruntu, "kare_alinamadi": d.kare_alinamadi, "alinan_bayt": d.alinan_bayt, "tekrar": d.tekrar, "geriye": d.geriye,
                    "atlanan": d.atlanan, "kalibrasyon_uyumsuz": d.kalibrasyon_uyumsuz, "reddedilen_baglanti": d.reddedilen_baglanti, "islenen": d.islenen,
                    "islem_kuyrugu_maks": d.islem_kuyrugu_maks, "hata": d.hata} for a, d in self.durum.items()}

    def kapat(self):
        self._dur.set()
        for s in self._dinle.values():
            try:
                s.close()
            except OSError:
                pass
        for t in self._ipler:
            t.join(3)
        self.kuyruk_durumu_kaydet()                      # kapanışta bir kez daha: periyodik iş parçacığı durduktan sonra (en büyük mono_ns sonuncudur)

