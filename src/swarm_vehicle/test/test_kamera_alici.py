"""Kamera alıcısı saf mantık birim testleri (ROS 2, MAVSDK, gz gerekmez). Çalıştırma: python3 src/swarm_vehicle/test/test_kamera_alici.py
Beklenenler elle hesaplanmıştır (hz = 2: n = 2·t; damga ns = n · 5·10^8)."""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle.kamera import kamera_alici as ka  # noqa: E402

NS = 10 ** 9
YARIM = NS // 2


def damga(n):
    return n * YARIM


class Cihaz:
    """Alıcıyı kuran, kayıtları ve kuyruğa verilenleri toplayan test düzeneği."""

    def __init__(self, t_s=10.0, t_b=None):
        self.kayit, self.kuyruk = [], []
        self.a = ka.KameraAlici(1, 2, self.kayit.append, lambda n, d, m: self.kuyruk.append(n))
        self.mono = 1000
        if t_s is not None:
            self.a.tarama_basladi(int(round(t_s * NS)))
        if t_b is not None:
            self.a.tarama_bitti(int(round(t_b * NS)))

    def ver(self, *numaralar):
        for n in numaralar:
            self.mono += 1
            self.a.kare(damga(n), self.mono)

    def olaylar(self, olay, **kosul):
        return [r for r in self.kayit if r["olay"] == olay and all(r.get(k) == v for k, v in kosul.items())]

    def alinamadi(self):
        return sorted(r["n"] for r in self.olaylar("kayip_tespit", sonuc_durumu="kare_alinamadi"))


class KuyrukAsamalari(unittest.TestCase):
    """B13: `kuyruga_giris` disk kuyruğuna yazıldıktan sonraki an; uçta modda `aktarim_tamam` = "uygulanmaz"; taşan kare için kayıt yazılmaz."""

    def test_uc_modda_aktarim_tamam_uygulanmaz_ve_giris_yazma_sonrasi(self):
        kayit = []
        a = ka.KameraAlici(1, 2, kayit.append, lambda n, d, m: 5_000_000 + m)         # geri çağrı yazma sonrası anı döndürür
        a.tarama_basladi(10 * NS)
        a.kare(damga(20), 1000)
        gir = [r for r in kayit if r["olay"] == "kuyruga_giris"]
        akt = [r for r in kayit if r["olay"] == "aktarim_tamam"]
        self.assertEqual([(r["n"], r["mono_ns"]) for r in gir], [(20, 5_001_000)])
        self.assertEqual([(r["n"], r["mono_ns"], r["kaynak"]) for r in akt], [(20, "uygulanmaz", "kamera_alicisi")])

    def test_merkezi_modda_alici_aktarim_tamam_yazmaz(self):
        kayit = []
        a = ka.KameraAlici(1, 2, kayit.append, lambda n, d, m: None, aktarim_uygulanmaz=False)
        a.tarama_basladi(10 * NS)
        a.kare(damga(20), 1000)
        self.assertEqual([r["olay"] for r in kayit if r["n"] == 20], ["kuyruga_giris"])
        self.assertEqual(kayit[-1]["mono_ns"], 1000, "geri çağrı anı döndürmezse alım anı kullanılır")

    def test_kuyruga_alinamayan_kare_icin_kayit_yazilmaz_ama_sayilir(self):
        kayit = []
        a = ka.KameraAlici(1, 2, kayit.append, lambda n, d, m: n != 21 and None)       # n=21 taşar (False)
        a.tarama_basladi(10 * NS)
        for n in (20, 21, 22):
            a.kare(damga(n), 1000 + n)
        self.assertEqual([r["n"] for r in kayit if r["olay"] == "kuyruga_giris"], [20, 22])
        self.assertEqual([r["n"] for r in kayit if r["olay"] == "aktarim_tamam"], [20, 22])
        self.assertEqual((a.sayac["gorev"], a.sayac["kuyruga_alinamadi"]), (3, 1))
        self.assertEqual([r for r in kayit if r["olay"] == "kayip_tespit"], [], "taşan kare 'kare alınamadı' değildir; sessiz atlama yok, açık hata çağıranda")


class KameraAliciGzDisk(unittest.TestCase):
    """B13: kamera alıcısının iç kuyruğu disk destekli (gz içe aktarılmadan; geri çağrı elle çağrılır). Tüketici iş parçacığı kareleri sırayla alır; taşmada kare ATILMAZ ama kuyruğa girmez: açık hata."""

    def _kur(self, tasma=None):
        import tempfile
        from swarm_vehicle.ucus import rota
        from swarm_vehicle.kamera.kamera_alici_gz import KameraAliciGz
        self._gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self._gecici.cleanup)
        ham = dict(rota.deney_env_oku())
        kayit = os.path.join(self._gecici.name, "kamera_alici_1.jsonl")
        self.alinan, self.loglar = [], []
        with mock.patch.dict(os.environ, {"KUYRUK_TEST_TASMA": tasma or ""}):
            g = KameraAliciGz(ham, 1, 1, kayit, lambda o, **kv: self.loglar.append((o, kv)), enjeksiyon_metni="", tuketici=lambda n, d, m, v, w, h: self.alinan.append((n, len(v))),
                              kuyruk_dizin=os.path.join(self._gecici.name, "kuyruk", "kamera_1"), tasma_yol=os.path.join(self._gecici.name, "tasma.jsonl"))
        self.g, self.kayit_yol = g, kayit
        return g

    @staticmethod
    def _mesaj(n, boyut=1000):
        class S:
            pass
        m = S()
        m.header = S()
        m.header.stamp = S()
        m.header.stamp.sec, m.header.stamp.nsec = divmod(n * 500_000_000, 10 ** 9)
        m.width, m.height, m.data, m.pixel_format_type = 640, 480, bytes([n % 256]) * boyut, 3
        return m

    def _olaylar(self):
        import json
        with open(self.kayit_yol, encoding="utf-8") as f:
            return [json.loads(x) for x in f]

    def test_kareler_diskten_sirayla_tuketilir_ve_olaylar_yazma_sonrasi(self):
        g = self._kur()
        g.alici.tarama_basladi(10 * NS)
        th = threading.Thread(target=g._tuket)
        th.start()
        for n in range(20, 26):
            g._gz_geri_cagrisi(self._mesaj(n))
        sinir = time.monotonic() + 5
        while len(self.alinan) < 6 and time.monotonic() < sinir:
            time.sleep(0.02)
        g._dur.set()
        th.join(5)
        self.assertEqual(self.alinan, [(n, 1000) for n in range(20, 26)])
        ol = self._olaylar()
        self.assertEqual([r["n"] for r in ol if r["olay"] == "kuyruga_giris"], list(range(20, 26)))
        self.assertEqual([(r["n"], r["mono_ns"]) for r in ol if r["olay"] == "aktarim_tamam"], [(n, "uygulanmaz") for n in range(20, 26)])
        self.assertEqual(g.hata, None)
        g.kapat()
        self.assertFalse(os.path.exists(os.path.join(self._gecici.name, "kuyruk", "kamera_1")), "boş kuyruk dizini kapanışta silinir")

    def test_tasma_acik_hata_kare_sessiz_atilmaz(self):
        g = self._kur(tasma="kamera_1:3")
        g.alici.tarama_basladi(10 * NS)
        for n in range(20, 26):
            g._gz_geri_cagrisi(self._mesaj(n))
        self.assertIn("kamera kuyruğu taştı", g.hata)
        self.assertEqual((g.tasan, g._q.derinlik()[0]), (4, 2), "6 kare: 2 kuyrukta, 4'ü taşma sonrası kuyruğa alınamadı (sayıldı; sessiz kayıp yok)")
        ol = self._olaylar()
        self.assertEqual([r["n"] for r in ol if r["olay"] == "kuyruga_giris"], [20, 21], "kuyruğa alınamayan kare için kuyruga_giris yazılmaz")
        self.assertEqual(g.alici.sayac["kuyruga_alinamadi"], 4)
        self.assertEqual(len([1 for o, kv in self.loglar if o == "kamera_kuyrugu_hata"]), 1)
        self.assertEqual(len([1 for o, kv in self.loglar if o == "kuyruk_tasmasi"]), 1)
        self.assertEqual([o for o, kv in self.loglar if o == "test_anahtari_acik"], ["test_anahtari_acik"])
        g.kapat()
        self.assertTrue(os.path.isdir(os.path.join(self._gecici.name, "kuyruk", "kamera_1")), "kuyrukta kalan 2 kare dizinde bırakıldı")


class Numaralandirma(unittest.TestCase):
    def test_izgara(self):
        self.assertEqual(ka.n_hesapla(10 * NS, 2), 20)
        self.assertEqual(ka.n_hesapla(10 * NS + YARIM, 2), 21)
        self.assertIsNone(ka.n_hesapla(10 * NS + 4 * 10 ** 6, 2))      # 10,004 s: ızgara dışı (K9)
        self.assertIsNone(ka.n_hesapla(10 * NS - 1, 2))

    def test_n_ilk_n_son_sinir_degerleri(self):
        # elle: n_ilk = ceil(2·t_s), n_son = floor(2·t_b)
        for t, ilk, son in ((10.0, 20, 20), (10.25, 21, 20), (10.5, 21, 21), (10.75, 22, 21), (0.0, 0, 0)):
            ns = round(t * NS)
            self.assertEqual((ka.n_ilk_hesapla(ns, 2), ka.n_son_hesapla(ns, 2)), (ilk, son), t)

    def test_yedek_yol_acik_hata(self):
        with self.assertRaises(ka.YedekYolHatasi):
            ka.KameraAlici(1, 2, kip="yedek")


class GorevKabulu(unittest.TestCase):
    def test_normal_ardisik(self):
        c = Cihaz(t_s=10.0, t_b=12.0)             # n_ilk = 20, n_son = 24
        self.assertEqual((c.a.n_ilk, c.a.n_son), (20, 24))
        c.ver(19, 20, 21, 22, 23, 24, 25)
        self.assertEqual(c.kuyruk, [20, 21, 22, 23, 24])
        self.assertEqual(c.alinamadi(), [])
        self.assertEqual(c.a.son_gorev_numarasi, 24)
        self.assertEqual([r["neden"] for r in c.olaylar("yok_sayildi")], ["gorev_oncesi", "kapanis_sonrasi"])
        self.assertTrue(c.a.kapali)                # kapanış n_son'dan büyük ilk karenin (25) gelmesiyle olur

    def test_ortada_tek_kayip(self):
        c = Cihaz(10.0, 12.0)
        c.ver(20, 21, 23, 24, 25)                  # 22 yok
        self.assertEqual(c.alinamadi(), [22])
        self.assertEqual(c.kuyruk, [20, 21, 23, 24])
        # kayıp, sonraki kare gelince üretilir: "kare alınamadı" kaydı n=23'ün kuyruga_giris kaydından önce yazılır (zaman sırası)
        sira = [(r["olay"], r["n"]) for r in c.kayit if r["n"] in (22, 23)]
        self.assertEqual(sira, [("kayip_tespit", 22), ("kuyruga_giris", 23), ("aktarim_tamam", 23)])

    def test_ardisik_coklu_kayip(self):
        c = Cihaz(10.0, 12.0)
        c.ver(20, 23, 24, 25)                      # 21, 22 yok
        self.assertEqual(c.alinamadi(), [21, 22])
        self.assertEqual(c.kuyruk, [20, 23, 24])

    def test_ilk_gorev_karesi_kaybi(self):
        c = Cihaz(10.0, 12.0)
        c.ver(21, 22, 23, 24, 25)                  # 20 (n_ilk) yok
        self.assertEqual(c.alinamadi(), [20])
        self.assertEqual(c.kuyruk, [21, 22, 23, 24])

    def test_sondaki_kayip_n_sondan_buyuk_ilk_kareyle_kapanir(self):
        c = Cihaz(10.0, 12.0)
        c.ver(20, 21, 22)                          # 23, 24 yok; kapanış karesi henüz gelmedi
        self.assertEqual(c.alinamadi(), [])
        c.ver(25)                                  # n_son = 24'ten büyük ilk kare
        self.assertEqual(c.alinamadi(), [23, 24])
        self.assertEqual(c.kuyruk, [20, 21, 22])   # 25 görev girdisi değil
        self.assertEqual(c.olaylar("yok_sayildi")[-1]["neden"], "kapanis_sonrasi")
        c.ver(26)                                  # kapanıştan sonra: yeniden "kare alınamadı" üretilmez
        self.assertEqual(c.alinamadi(), [23, 24])

    def test_n_son_kaybi(self):
        c = Cihaz(10.0, 12.0)
        c.ver(20, 21, 22, 23, 25)                  # n_son = 24 kayıp
        self.assertEqual(c.alinamadi(), [24])

    def test_kayittan_sonra_ayni_numara_gec_geldi(self):
        c = Cihaz(10.0, 12.0)
        c.ver(20, 21, 23)                          # 22 için kayıt yazıldı
        self.assertEqual(c.alinamadi(), [22])
        c.ver(22)                                  # geç gelen
        self.assertEqual(c.kuyruk, [20, 21, 23])   # işlenmez / kuyruğa verilmez
        self.assertEqual([r["n"] for r in c.olaylar("gec_geldi")], [22])
        self.assertEqual(c.alinamadi(), [22])      # kayıt kesin: değişmedi
        self.assertEqual(c.a.sayac["gec_geldi"], 1)

    def test_kapanis_sonrasi_gec_gelen_kayip(self):
        c = Cihaz(10.0, 12.0)
        c.ver(20, 21, 22, 25)                      # 23, 24 kayıt; kapanış
        c.ver(23)
        self.assertEqual([r["n"] for r in c.olaylar("gec_geldi")], [23])
        self.assertEqual(c.kuyruk, [20, 21, 22])

    def test_tekrar_numara(self):
        c = Cihaz(10.0, 12.0)
        c.ver(20, 21, 21, 22)
        self.assertEqual(c.kuyruk, [20, 21, 22])
        self.assertEqual([r["neden"] for r in c.olaylar("yok_sayildi")], ["tekrar"])

    def test_izgara_disi(self):
        c = Cihaz(10.0, 12.0)
        c.a.kare(20 * YARIM + 4 * 10 ** 6, 5)      # 10,004 s
        c.ver(20, 21)
        self.assertEqual(c.kuyruk, [20, 21])
        self.assertEqual(c.a.sayac["izgara_disi"], 1)
        self.assertEqual(c.olaylar("yok_sayildi")[0]["n"], "izgara_disi")

    def test_t_s_t_b_ızgara_aninda_ve_bucuk(self):
        # t_s = 10,0 → n_ilk 20 (damgası t_s'ye eşit kare görev karesi); t_b = 12,0 → n_son 24 (damgası t_b'ye eşit kare görev karesi)
        c = Cihaz(10.0, 12.0)
        c.ver(20, 24)
        self.assertEqual(c.kuyruk, [20, 24])
        # t_s = 10,25 → n_ilk 21; t_b = 12,25 → n_son 24
        c = Cihaz(10.25, 12.25)
        self.assertEqual((c.a.n_ilk, c.a.n_son), (21, 24))
        c.ver(20, 21, 24, 25)
        self.assertEqual(c.kuyruk, [21, 24])
        # t_s = 10,5 → n_ilk 21; t_b = 12,5 → n_son 25
        c = Cihaz(10.5, 12.5)
        self.assertEqual((c.a.n_ilk, c.a.n_son), (21, 25))

    def test_gorev_oncesi_ve_sonrasi_gorev_girdisi_degil(self):
        c = Cihaz(10.0, 12.0)
        c.ver(5, 19, 20, 24, 25, 30)
        self.assertEqual(c.kuyruk, [20, 24])
        self.assertEqual(c.alinamadi(), [21, 22, 23])     # 24 gelince 21..23 kayıp
        self.assertEqual(c.a.sayac["gorev_oncesi"], 2)
        self.assertEqual(c.a.sayac["kapanis_sonrasi"], 2)

    def test_tarama_baslamadan_gelen_kareler(self):
        c = Cihaz(t_s=None)
        c.ver(3, 4, 5)
        self.assertEqual(c.kuyruk, [])
        self.assertEqual(c.a.sayac["gorev_oncesi"], 3)

    def test_tarama_bitmeden_sonraki_kare_aralik_dolar(self):
        c = Cihaz(10.0, None)
        c.ver(20, 21, 22)
        self.assertIsNone(c.a.n_son)
        c.a.tarama_bitti(int(11.0 * NS))              # n_son = 22
        c.ver(23)
        self.assertEqual(c.kuyruk, [20, 21, 22])
        self.assertEqual(c.alinamadi(), [])

    def test_hicbir_numara_hem_gorev_hem_kayip_olmaz(self):
        import random
        for tohum in range(50):
            r = random.Random(tohum)
            c = Cihaz(10.0, 20.0)                      # n_ilk 20, n_son 40
            for n in range(15, 50):
                if r.random() < 0.3:
                    continue                           # kayıp
                c.ver(n)
            for n in range(15, 50):
                if r.random() < 0.3:
                    c.ver(n)                           # geç / tekrar gelenler
            gorev, kayip = set(c.kuyruk), set(c.alinamadi())
            self.assertFalse(gorev & kayip, tohum)
            self.assertLessEqual(gorev | kayip, set(range(20, 41)))
            self.assertEqual(len(c.kuyruk), len(gorev))            # her numara en çok bir kez kuyruğa verildi
            self.assertEqual(len(c.alinamadi()), len(kayip))       # her numara için en çok bir kayıp


class KayipKaydiOlayi(unittest.TestCase):
    def test_kayip_kaydi_kullanilabilir_degil(self):
        c = Cihaz(10.0, 12.0)
        c.ver(20, 22, 23, 24, 25)
        self.assertEqual(c.olaylar("kullanilabilir"), [])               # alıcı "kullanılabilir" yazmaz
        kayip = c.olaylar("kayip_tespit")
        self.assertEqual([(r["n"], r["sonuc_durumu"], r["kaynak"]) for r in kayip], [(21, "kare_alinamadi", "kamera_alicisi")])
        self.assertEqual(kayip[0]["sim_damga_ns"], 21 * YARIM)


class TsSiniri(unittest.TestCase):
    """t_s sınır durumu: tarama başlatma bildirimi, damgası t_s'ye eşit karenin gelişinden SONRA yapılır (t_s okuması bir saat adımı eski)."""

    def test_kare_bildirimden_once_gelir_gorev_karesi_olur(self):
        c = Cihaz(t_s=None)
        c.ver(19, 20)                                          # 20 → damga 10,0 s; bildirim henüz yok → "görev öncesi" sayılır
        self.assertEqual(c.kuyruk, [])
        c.a.tarama_basladi(int(9.99 * NS), c.mono + 1000)      # eski t_s = 9,99 s → n_ilk = 20; kare 20 bildirimden 1 µs önce gelmişti
        self.assertEqual(c.a.n_ilk, 20)
        self.assertEqual(c.kuyruk, [20])                       # görev karesi olarak iç kuyruğa verildi
        self.assertEqual(c.alinamadi(), [])                    # kayip_tespit YOK
        self.assertEqual([r["n"] for r in c.olaylar("kuyruga_giris")], [20])
        self.assertEqual(c.a.sayac["gorev_oncesi_kabul"], 1)
        c.ver(21)
        self.assertEqual(c.kuyruk, [20, 21])
        self.assertEqual(c.alinamadi(), [])

    def test_bir_saniyeden_eski_kare_kabul_edilmez(self):
        c = Cihaz(t_s=None)
        c.ver(20)
        c.a.tarama_basladi(int(9.99 * NS), c.mono + 2 * NS)    # kare 2 sn önce geldi: kabul edilmez
        self.assertEqual(c.kuyruk, [])
        c.ver(21)
        self.assertEqual(c.alinamadi(), [20])                  # 20 sonradan kayıp sayılır (alıcı kuralı)

    def test_n_ilk_den_kucuk_kare_kabul_edilmez(self):
        c = Cihaz(t_s=None)
        c.ver(19)
        c.a.tarama_basladi(10 * NS, c.mono + 10)               # n_ilk = 20; kare 19 < 20
        self.assertEqual(c.kuyruk, [])
        self.assertEqual(c.a.sayac["gorev_oncesi_kabul"], 0)

    def test_mono_verilmezse_eski_davranis(self):
        c = Cihaz(t_s=None)
        c.ver(20)
        c.a.tarama_basladi(int(9.99 * NS))
        self.assertEqual(c.kuyruk, [])


class KayipGeriCagrisiVeZorlaKapatma(unittest.TestCase):
    def test_kayip_geri_cagrisi_her_kayip_icin_bir_kez(self):
        kayiplar = []
        a = ka.KameraAlici(1, 2, None, None, kayip_ver=lambda n, m: kayiplar.append(n))
        a.tarama_basladi(10 * NS)
        a.tarama_bitti(12 * NS)
        for n in (20, 23, 24, 25):
            a.kare(n * YARIM, 1000 + n)
        self.assertEqual(kayiplar, [21, 22])

    def test_kapat_zorla_sondaki_kayiplari_kapatir(self):
        c = Cihaz(10.0, 12.0)                                   # n_ilk 20, n_son 24
        c.ver(20, 21, 22)                                       # 23, 24 gelmedi; kapanış karesi (25) de gelmedi
        self.assertEqual(c.a.kapat_zorla(5000), [23, 24])
        self.assertEqual(c.alinamadi(), [23, 24])
        self.assertEqual(c.a.kapat_zorla(6000), [])             # ikinci çağrı bir şey yazmaz
        c.ver(25)
        self.assertEqual(c.alinamadi(), [23, 24])


class EnjeksiyonCozumu(unittest.TestCase):
    def test_kapali(self):
        self.assertFalse(ka.Enjeksiyon("").acik)
        self.assertEqual(ka.Enjeksiyon("").ozet(), "kapali")

    def test_belirtecler(self):
        e = ka.Enjeksiyon("bekle=0.6;dusur=+20,+60,+61,son;gecik=+100")
        c = Cihaz(10.0, 12.0)
        self.assertTrue(e.acik)
        self.assertEqual(e.bekle_sn, 0.6)
        # n_ilk = 20, n_son = 24: +20 → 40, +60 → 80, +61 → 81, son → 24; gecik +100 → 120
        self.assertTrue(all(e.dusur_mu(n, c.a) for n in (40, 80, 81, 24)))
        self.assertFalse(any(e.dusur_mu(n, c.a) for n in (20, 41, 82)))
        self.assertTrue(e.gecik_mi(120, c.a))
        self.assertFalse(e.gecik_mi(121, c.a))

    def test_bilinmeyen_anahtar(self):
        with self.assertRaises(ValueError):
            ka.Enjeksiyon("xyz=1")


if __name__ == "__main__":
    unittest.main(verbosity=1)
