"""Kare işleyici (B10): kamera alıcısının kuyruğundaki görev karesini çıkarım işçisine verir, işçi yanıtından ya da alıcının kayıp kaydından HER görev numarası için tam bir kare sonucu üretir,
yerel kayda yazar ve kancaya verir (uçta modda kanca DDS yayımına, merkezi modda yer istasyonu sonuç defterine bağlıdır).
Yalnız standart kitaplık (rclpy yok): ileti oluşturma kancayı çağıran tarafa (arac.py) bırakılmıştır.
Sonucu olmayan numara kalmaz: kapanışta kalan numaralar için (işçi/zaman sınırı) `islem_hatasi` yazılır — "tespit yok" ASLA varsayılmaz.
Tespitin yatay konumu (FR-17, FR-18) bu sınıfta, sonuç kaydı oluşmadan önce AYNI konum hesaplayıcıyla (`konum_hesap`) iki modda da hesaplanır: poz uçta modda o karenin
`kare_poz` sonucudur (yeni sorgu yok), merkezi modda görüntü iletisinin başlığındaki pozdur. Geçerli poz yoksa `konum_neden = poz_yok`, kesişim yoksa `kesisim_yok`; konumlu tespitte
`konum = [doğu_m, kuzey_m]`. `candidate` (birleştirme adayı, B15) her tespitte False'tur (`aday: false`).
Test anahtarı (YALNIZ test, varsayılan kapalı): ortam değişkeni KONUM_TEST_SAHTE = `x1,y1,x2,y2[;x1,y1,x2,y2...]`: çıkarım işçisinin BAŞARILI yanıtına bu sabit kutulu sahte tespitler eklenir
(sınıf eşlemesi ve tespit yolu atlanmaz).
"""
import math
import os
import queue
import threading
import time

from . import kare_sonuc as ks
from . import konum_hesap as kh
from . import poz_tamponu as pz
from .cikarim_yardimci import SinifEsleme

_NS = 10 ** 9


def sahte_tespitleri_ayristir(metin):
    """KONUM_TEST_SAHTE → [[x1, y1, x2, y2], ...] (boş metin: boş liste). Bozuk değer ValueError."""
    kutular = []
    for parca in [p for p in (metin or "").split(";") if p.strip()]:
        v = [float(x) for x in parca.split(",")]
        if len(v) != 4 or not all(math.isfinite(x) for x in v):
            raise ValueError(f"KONUM_TEST_SAHTE: kutu 'x1,y1,x2,y2' olmalı: '{parca}'")
        kutular.append(v)
    return kutular


class KareIsleyici:
    def __init__(self, ham, arac_kimligi, istemci, kayit_yol, log, kanca=None, poz_tamponu=None, poz_yol=None, konum_hesaplayici=None, sahte_tespit_metni=None):
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
        self.poz_tamponu = poz_tamponu          # isteğe bağlı: her görev numarası için kare üretim anındaki poz sorgulanır ve kaydedilir (konum hesabı bu pozu kullanır)
        self.poz_yazici = pz.SatirYazici(poz_yol, log) if poz_tamponu is not None else None
        self.poz_bekleme_ms = []
        self.poz_gecersiz = {}
        self.konum_hesaplayici = konum_hesaplayici   # verilmezse (yalnız birim testleri) bütün tespitler `poz_yok` ile konumsuz kalır
        self.konum_sayac = {"konumlu": 0, "poz_yok": 0, "kesisim_yok": 0}
        self.mesafeler_m = []                        # konumlu tespitlerin kamera–kesişim uzaklığı (dağılım raporu için)
        self.sahte_tespit = sahte_tespitleri_ayristir(sahte_tespit_metni if sahte_tespit_metni is not None else os.environ.get("KONUM_TEST_SAHTE", ""))
        self.sahte_tespit_sayisi = 0                 # test anahtarıyla eklenen toplam sahte tespit (konum_ozeti ve koşu günlüğünde görünür)
        if self.sahte_tespit:
            self.log("test_anahtari_acik", seviye="(!)", anahtar="KONUM_TEST_SAHTE", kutu_sayisi=len(self.sahte_tespit),
                     uyari="TEST ANAHTARI ACIK: çıkarım yanıtlarına sahte tespit eklenir; bu koşunun tespit sayıları gerçek değildir")
        # kayıp kare yolu (gz kamera geri çağrısından gelir): poz beklemesi o geri çağrıyı bloke etmesin diye ayrı iş parçacığında tamamlanır (yalnız poz tamponu varken; tek iş parçacığı = sıra korunur)
        self._kayip_q = queue.SimpleQueue()
        self._kayip_k = threading.Condition()
        self._kayip_bekleyen = 0
        self._kayip_th = None
        self.kayip_cagri_maks_ms = 0.0               # `kayip()` çağrısının dönme süresi en çok (gz geri çağrısının bloke olma süresi)

    # --- sonuç üretimi ----------------------------------------------------------------------------------------------------------------------
    def _bitir(self, n, damga_ns, durum, tespitler=(), atilan=0, hata=None, merkez_poz=None, kalibrasyon_uyumsuz=False):
        poz = self._poz_sorgula(n, damga_ns)         # bekleme dahil KİLİT DIŞINDA; sonuç yayımından (kanca) önce
        with self._bitir_kilit:
            return self._bitir_kilitli(n, damga_ns, durum, tespitler, atilan, hata, poz, merkez_poz, kalibrasyon_uyumsuz)

    def _konumla(self, n, tespitler, poz, merkez_poz, kalibrasyon_uyumsuz):
        """Her tespite yatay konumu (ya da konumsuzluk nedenini) yazar. Poz: merkezi modda iletinin başlığındaki poz (`merkez_poz`), uçta modda o karenin `kare_poz` sonucu (`poz`)."""
        kullan = merkez_poz if merkez_poz is not None else poz
        if kalibrasyon_uyumsuz and tespitler:
            self.log("konum_kalibrasyon_uyusmuyor", n=n, tespit=len(tespitler), ayrinti="iletideki kalibrasyon kimliği yüklü dosyanınkiyle aynı değil; bu karenin tespitleri konumsuz")
        sonuclar = []
        for t in tespitler:
            if kalibrasyon_uyumsuz or self.konum_hesaplayici is None:
                s = kh.KonumSonucu(None, kh.NEDEN_POZ_YOK)
            else:
                s = self.konum_hesaplayici.hesapla(t["kutu"], kullan)
            t["konum"] = [s.konum[0], s.konum[1]] if s.konum is not None else None
            t["konum_neden"] = s.neden
            sonuclar.append(s)
        return sonuclar

    def _konum_say(self, sonuclar):
        for s in sonuclar:
            if s.konum is not None:
                self.konum_sayac["konumlu"] += 1
                self.mesafeler_m.append(s.mesafe_m)
            else:
                self.konum_sayac[s.neden] += 1

    def _bitir_kilitli(self, n, damga_ns, durum, tespitler, atilan, hata, poz=None, merkez_poz=None, kalibrasyon_uyumsuz=False):
        sonuclar = self._konumla(n, tespitler, poz, merkez_poz, kalibrasyon_uyumsuz)
        kayit = ks.kayit_olustur(self.arac_kimligi, n, damga_ns, durum, tespitler, atilan, hata, time.monotonic_ns(), merkez_poz.sozluk() if merkez_poz is not None else None)
        if not self.defter.ekle(kayit):
            self.log("kare_sonuc_cift", n=n, durum=durum, ayrinti="bu numara için zaten sonuç var; ikinci sonuç yazılmadı")
            return False
        self._konum_say(sonuclar)
        self.yazici.yaz(kayit)
        self._poz_yaz(n, damga_ns, poz)
        if durum != ks.TESPIT_YOK:
            self.log("kare_sonuc", n=n, durum=durum, tespit=len(kayit["tespitler"]), hata=(hata or "-").replace(" ", "_"))
        if self.kanca is not None:
            try:
                self.kanca(kayit)
            except Exception as e:  # noqa: BLE001
                self.log("kare_sonuc_kancasi_hatasi", n=n, hata=repr(e))
        return True

    def _poz_sorgula(self, n, damga_ns):
        """Kare üretim anındaki poz (kaynak-zamanı enterpolasyonu) sorgulanır; en çok POZ_BEKLE_SN bloke olur (bekleme ölçüme dahildir). Numara için zaten sonuç varsa sorgulanmaz.
        Poz sorgusu istisna verirse geçersiz (`hata`) sonuç döner; kare sonucu yine üretilir. Dönen: `PozSonuc` ya da None (poz tamponu yok)."""
        if self.poz_tamponu is None or self.defter.var_mi(n):
            return None
        basla = time.monotonic_ns()
        try:
            return self.poz_tamponu.sorgula(damga_ns)
        except Exception as e:  # noqa: BLE001
            self.log("kare_poz_hatasi", n=n, hata=repr(e))
            # her numara için tam bir `kare_poz` kaydı: geçersiz, neden `hata`; tespitler `poz_yok` ile konumsuz kalır
            return pz.PozSonuc(False, pz.HATA, None, None, None, (time.monotonic_ns() - basla) / 1e6, None, None)

    def _poz_yaz(self, n, damga_ns, s):
        """Sonuç defterine girmiş numara için tam bir `kare_poz` kaydı yazar (defter reddettiyse çağrılmaz: bir numaraya tek kayıt). Kilit altında yalnız kuyruğa koyar."""
        if s is None:
            return
        self.poz_bekleme_ms.append(s.bekleme_ms)
        if not s.gecerli:
            self.poz_gecersiz[s.neden] = self.poz_gecersiz.get(s.neden, 0) + 1
        self.poz_yazici.ver(pz.kare_poz_kaydi(self.arac_kimligi, n, damga_ns, s))

    def goruntu(self, n, damga_ns, mono_ns, veri, w, h, merkez_poz=None, kalibrasyon_uyumsuz=False):
        """Alıcı kuyruğu tüketicisi (tek iş parçacığı): kareyi işçide işler ve sonucunu yazar. Her çağrı bir numaraya tam bir sonuç üretir."""
        if self.kapaniyor and self.defter.var_mi(n):
            return
        yanit = self.istemci.isle(n, damga_ns, veri, w, h)
        if self.sahte_tespit and isinstance(yanit, dict) and yanit.get("durum") == "tamam":     # YALNIZ test anahtarı: gerçek tespit yolu ve sınıf eşlemesi atlanmaz
            yanit = dict(yanit)
            yanit["tespitler"] = list(yanit.get("tespitler", [])) + [{"sinif_adi": self.esleme.siniflar[0], "guven": 0.99, "kutu": list(k)} for k in self.sahte_tespit]
            self.sahte_tespit_sayisi += len(self.sahte_tespit)
        durum, tespitler, atilan, hata = ks.durum_belirle(yanit, self.esleme)
        if yanit.get("basi_ns") and yanit.get("sonu_ns"):
            self.sureler_ms.append((yanit["sonu_ns"] - yanit["basi_ns"]) / 1e6)
        self.atilan_toplam += atilan
        self._bitir(n, damga_ns, durum, tespitler, atilan, hata, merkez_poz, kalibrasyon_uyumsuz)

    def kayip(self, n, mono_ns, merkez_poz=None, kalibrasyon_uyumsuz=False):
        """Alıcı bu numara için "kare alınamadı" kaydı yazdı: tespit taşımayan kare sonucu. Çağıran gz kamera geri çağrısı olabilir: poz tamponu varken (uçta mod) poz beklemesi (en çok
        POZ_BEKLE_SN) ayrı bir iş parçacığında tamamlanır, bu çağrı beklemeden döner; aynı kural, aynı bekleme sınırı, her numara bir kez, sıra korunur (tek iş parçacığı)."""
        basla = time.monotonic_ns()
        damga = n * _NS // self.hz
        if self.poz_tamponu is None:
            self._bitir(n, damga, ks.KARE_ALINAMADI, merkez_poz=merkez_poz, kalibrasyon_uyumsuz=kalibrasyon_uyumsuz)
        else:
            with self._kayip_k:
                self._kayip_bekleyen += 1
                if self._kayip_th is None:
                    self._kayip_th = threading.Thread(target=self._kayip_dongusu, name="kayip_sonuc", daemon=True)
                    self._kayip_th.start()
            self._kayip_q.put((n, damga, merkez_poz, kalibrasyon_uyumsuz))
        self.kayip_cagri_maks_ms = max(self.kayip_cagri_maks_ms, (time.monotonic_ns() - basla) / 1e6)

    def _kayip_dongusu(self):
        while True:
            n, damga, merkez_poz, uyumsuz = self._kayip_q.get()
            try:
                self._bitir(n, damga, ks.KARE_ALINAMADI, merkez_poz=merkez_poz, kalibrasyon_uyumsuz=uyumsuz)
            except Exception as e:  # noqa: BLE001
                self.log("kayip_sonuc_hatasi", n=n, hata=repr(e))
            finally:
                with self._kayip_k:
                    self._kayip_bekleyen -= 1
                    self._kayip_k.notify_all()

    def konum_ozeti(self):
        """Günlük için konum özeti: tespit sayıları (konumlu / poz_yok / kesisim_yok), kesişim mesafesi dağılımı (m) `kayip()` çağrısının en uzun dönme süresi (ms; yalnız çağrının kendisi, poz beklemesi ayrı iş parçacığında olduğundan bunu kapsamaz) ve test anahtarıyla eklenen sahte tespit sayısı."""
        m = sorted(self.mesafeler_m)
        d = {**self.konum_sayac, "kayip_cagri_maks_ms": f"{self.kayip_cagri_maks_ms:.2f}", "sahte_tespit": self.sahte_tespit_sayisi}
        if m:
            d.update(mesafe_min_m=f"{m[0]:.2f}", mesafe_medyan_m=f"{m[len(m) // 2]:.2f}", mesafe_p95_m=f"{m[min(len(m) - 1, int(0.95 * len(m)))]:.2f}", mesafe_en_buyuk_m=f"{m[-1]:.2f}")
        return d

    def kayip_bekle(self, sn):
        """Kuyruktaki kayıp kare sonuçları bitene dek en çok `sn` (gerçek sn) bekler. True: kuyruk boş."""
        sinir = time.monotonic() + sn
        with self._kayip_k:
            while self._kayip_bekleyen > 0:
                kalan = sinir - time.monotonic()
                if kalan <= 0:
                    return False
                self._kayip_k.wait(min(kalan, 0.2))
            return True

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
            bekle = self.poz_tamponu.bekle_sn if self.poz_tamponu is not None else 0.0
            with self._kayip_k:
                bekleyen = self._kayip_bekleyen          # kapanıştan önce birikmiş kayıp işler de sırayla (her biri en çok POZ_BEKLE_SN) tamamlanır
            if not self.kayip_bekle(2.0 + (bekleyen + len(zorla) + 1) * (bekle + 0.1)):      # zorla kapatılan kayıplar kendi iş parçacığında tamamlansın; sonra eksikler hesaplanır
                self.log("kapanis_kayip_kuyrugu_bosalmadi", bekleyen=self._kayip_bekleyen, ayrinti="kayıp kare işleri süre içinde bitmedi; kalan numaralar islem_hatasi olur")
            for n in self.defter.eksikler(n_ilk, n_son):
                self._bitir(n, n * _NS // self.hz, ks.ISLEM_HATASI, hata=f"kapanışta işlenemedi (kuyruk {bekle_sn:g} sn içinde boşalmadı)")
                hatali.append(n)
        if self.poz_yazici is not None and self.poz_yazici.kapat():          # özet adı her yolda aynı (`satir_yazici_ozet`); ikinci kapanışta tekrar yazılmaz
            self.log("satir_yazici_ozet", yol=os.path.basename(self.poz_yazici.yol or "-"), **self.poz_yazici.ozet())
        return zamaninda, zorla, hatali
