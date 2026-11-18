"""Poz tamponu birim testleri (ROS 2 ve MAVSDK gerekmez). Çalıştırma: python3 src/swarm_vehicle/test/test_poz_tamponu.py"""
import json
import math
import os
import random
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle.cikarim import kare_isleyici as ki  # noqa: E402
from swarm_vehicle.ucus import poz_tamponu as pt  # noqa: E402
from swarm_vehicle.ucus import rota  # noqa: E402

MS = 10 ** 6
Q0 = (1.0, 0.0, 0.0, 0.0)


def yaw_q(derece):
    h = math.radians(derece) / 2
    return (math.cos(h), 0.0, 0.0, math.sin(h))      # NED'de z aşağı: pozitif yaw = saat yönü


def tampon(aralik_ms=100, bekle_sn=0.0, tampon_sn=30):
    return pt.PozTamponu(aralik_ms * MS, bekle_sn, tampon_sn)


class Enterpolasyon(unittest.TestCase):
    def test_konum_dogrusal(self):
        b = tampon()
        b.ekle(0, (0, 0, 0), Q0)
        b.ekle(40 * MS, (4, -8, 2), Q0)
        s = b.sorgula(10 * MS)
        self.assertTrue(s.gecerli)
        for a, e in zip(s.konum, (1, -2, 0.5)):
            self.assertAlmostEqual(a, e, places=9)
        self.assertEqual((s.t1_ns, s.t2_ns), (0, 40 * MS))
        self.assertAlmostEqual(s.aralik_ms, 40.0)

    def test_slerp_90_derece_ortasi_45(self):
        b = tampon()
        b.ekle(0, (0, 0, 0), yaw_q(0))
        b.ekle(50 * MS, (0, 0, 0), yaw_q(90))
        s = b.sorgula(25 * MS)
        for a, e in zip(s.q, yaw_q(45)):
            self.assertAlmostEqual(a, e, places=9)

    def test_slerp_ceyrek_nokta(self):
        q = pt.slerp(yaw_q(0), yaw_q(90), 0.25)
        for a, e in zip(q, yaw_q(22.5)):
            self.assertAlmostEqual(a, e, places=9)

    def test_isaret_donmesi(self):
        """q ve −q aynı dönmedir: kısa yol seçilmeli, sonuç 270° uzun yoldan geçmemeli."""
        a, b = yaw_q(10), tuple(-v for v in yaw_q(50))
        for q1, q2 in ((a, b), (b, a)):
            s = pt.slerp(q1, q2, 0.5)
            orta = yaw_q(30)
            self.assertAlmostEqual(abs(sum(x * y for x, y in zip(s, orta))), 1.0, places=9)

    def test_normalizasyon(self):
        b = tampon()
        b.ekle(0, (0, 0, 0), tuple(3 * v for v in yaw_q(0)))        # birim değil girdi
        b.ekle(50 * MS, (0, 0, 0), yaw_q(120))
        s = b.sorgula(20 * MS)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in s.q)), 1.0, places=12)

    def test_cok_yakin_kuaterniyonlar(self):
        q1, q2 = yaw_q(10.0), yaw_q(10.0 + 1e-7)
        s = pt.slerp(q1, q2, 0.5)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in s)), 1.0, places=12)
        self.assertTrue(all(math.isfinite(v) for v in s))
        for a, e in zip(s, yaw_q(10.0 + 5e-8)):
            self.assertAlmostEqual(a, e, places=9)
        self.assertEqual(tuple(round(v, 12) for v in pt.slerp(q1, q1, 0.3)), tuple(round(v, 12) for v in q1))     # özdeş girdi

    def test_tam_ornek_ani(self):
        b = tampon()
        b.ekle(0, (0, 0, 0), Q0)
        b.ekle(30 * MS, (3, 0, 0), yaw_q(30))
        b.ekle(60 * MS, (6, 0, 0), yaw_q(60))
        s = b.sorgula(30 * MS)
        self.assertTrue(s.gecerli)
        self.assertEqual((s.t1_ns, s.t2_ns, s.aralik_ms), (30 * MS, 30 * MS, 0.0))
        self.assertEqual(s.konum, (3.0, 0.0, 0.0))
        s = b.sorgula(60 * MS)                        # en son örnek anı da tam örnektir (bekleme yok)
        self.assertTrue(s.gecerli)
        self.assertEqual(s.konum, (6.0, 0.0, 0.0))


class Sinirlar(unittest.TestCase):
    def test_aralik_sinira_esit_gecerli_bir_ns_fazla_gecersiz(self):
        b = tampon(aralik_ms=100)
        b.ekle(0, (0, 0, 0), Q0)
        b.ekle(100 * MS, (1, 0, 0), Q0)
        self.assertTrue(b.sorgula(50 * MS).gecerli)
        c = tampon(aralik_ms=100)
        c.ekle(0, (0, 0, 0), Q0)
        c.ekle(100 * MS + 1, (1, 0, 0), Q0)
        s = c.sorgula(50 * MS)
        self.assertFalse(s.gecerli)
        self.assertEqual(s.neden, pt.ARALIK_ASILDI)
        self.assertEqual((s.t1_ns, s.t2_ns), (0, 100 * MS + 1))
        self.assertIsNone(s.konum)
        self.assertIsNone(s.q)

    def test_tampon_oncesi(self):
        b = tampon()
        b.ekle(100 * MS, (0, 0, 0), Q0)
        b.ekle(140 * MS, (0, 0, 0), Q0)
        s = b.sorgula(99 * MS)
        self.assertEqual((s.gecerli, s.neden), (False, pt.TAMPON_DISI))

    def test_pencere_budamasi_ve_tampon_disi(self):
        b = tampon(tampon_sn=1)
        for k in range(0, 2001, 40):
            b.ekle(k * MS, (k, 0, 0), Q0)
        self.assertLessEqual(b.boyut(), 1000 // 40 + 2)
        s = b.sorgula(100 * MS)                        # budanmış bölge
        self.assertEqual((s.gecerli, s.neden), (False, pt.TAMPON_DISI))
        self.assertTrue(b.sorgula(1900 * MS).gecerli)                                  # pencere içi sorgu geçerli

    def test_tampon_sonrasi_bekleme_olmadan(self):
        b = tampon(bekle_sn=0.0)
        b.ekle(0, (0, 0, 0), Q0)
        b.ekle(40 * MS, (0, 0, 0), Q0)
        s = b.sorgula(50 * MS)
        self.assertEqual((s.gecerli, s.neden), (False, pt.BEKLEME_ASILDI))

    def test_bos_tampon(self):
        s = tampon().sorgula(0)
        self.assertEqual((s.gecerli, s.neden), (False, pt.BEKLEME_ASILDI))

    def test_en_son_ornek_yedek_degil(self):
        """Kare anı son örnekten sonra ve örnek gelmiyorsa 'son örnek' kullanılmaz."""
        b = tampon()
        b.ekle(0, (0, 0, 0), Q0)
        s = b.sorgula(1000 * MS)
        self.assertFalse(s.gecerli)
        self.assertIsNone(s.konum)


class Bekleme(unittest.TestCase):
    def test_baska_is_parcacigi_ornek_eklerse_doner(self):
        b = tampon(bekle_sn=2.0)
        b.ekle(0, (0, 0, 0), Q0)
        b.ekle(40 * MS, (4, 0, 0), Q0)

        def ekle():
            time.sleep(0.15)
            b.ekle(80 * MS, (8, 0, 0), Q0)
        th = threading.Thread(target=ekle)
        th.start()
        t0 = time.monotonic()
        s = b.sorgula(60 * MS)
        gecen = time.monotonic() - t0
        th.join()
        self.assertTrue(s.gecerli)
        self.assertAlmostEqual(s.konum[0], 6.0, places=9)
        self.assertLess(gecen, 1.0)
        self.assertGreaterEqual(s.bekleme_ms, 100)
        self.assertLess(s.bekleme_ms, 1000)

    def test_eklenmezse_bekleme_asildi_ve_sure(self):
        b = tampon(bekle_sn=0.2)
        b.ekle(0, (0, 0, 0), Q0)
        t0 = time.monotonic()
        s = b.sorgula(50 * MS)
        gecen = time.monotonic() - t0
        self.assertEqual((s.gecerli, s.neden), (False, pt.BEKLEME_ASILDI))
        self.assertGreaterEqual(gecen, 0.19)
        self.assertLess(gecen, 1.0)
        self.assertGreaterEqual(s.bekleme_ms, 190)

    def test_bekleme_sonrasi_aralik_asildi(self):
        """Sonraki örnek geç gelirse kare yine çevrelenir ama aralık sınırı aşılmıştır."""
        b = tampon(aralik_ms=100, bekle_sn=2.0)
        b.ekle(0, (0, 0, 0), Q0)
        th = threading.Timer(0.1, lambda: b.ekle(500 * MS, (5, 0, 0), Q0))
        th.start()
        s = b.sorgula(250 * MS)
        th.join()
        self.assertEqual((s.gecerli, s.neden), (False, pt.ARALIK_ASILDI))

    def test_bekleme_alani_dogrudan_sorguda_sifira_yakin(self):
        b = tampon()
        b.ekle(0, (0, 0, 0), Q0)
        b.ekle(40 * MS, (0, 0, 0), Q0)
        self.assertLess(b.sorgula(20 * MS).bekleme_ms, 50)


class Ekleme(unittest.TestCase):
    def test_geriye_giden_ve_yinelenen_reddi_ve_sayac(self):
        b = tampon()
        self.assertEqual(b.ekle(100 * MS, (0, 0, 0), Q0), (True, None))
        self.assertEqual(b.ekle(100 * MS, (9, 9, 9), Q0), (False, pt.RED_YINELENEN))
        self.assertEqual(b.ekle(60 * MS, (9, 9, 9), Q0), (False, pt.RED_GERI))
        self.assertEqual(b.ekle(140 * MS, (4, 0, 0), Q0), (True, None))
        c = b.sayaclar()
        self.assertEqual((c["eklenen"], c["reddedilen_yinelenen"], c["reddedilen_geriye_giden"], c["tampon_boyut"]), (2, 1, 1, 2))
        self.assertEqual(b.sorgula(100 * MS).konum, (0.0, 0.0, 0.0))           # reddedilen örnek tamponu bozmadı

    def test_gecersiz_degerler(self):
        b = tampon()
        for konum, q in (((float("nan"), 0, 0), Q0), ((0, 0, 0), (0, 0, 0, 0)), ((0, 0), Q0), ((0, 0, 0), (1, 0, 0))):
            self.assertEqual(b.ekle(1, konum, q), (False, pt.RED_GECERSIZ))
        self.assertEqual(b.sayaclar()["reddedilen_gecersiz_deger"], 4)

    def test_es_zamanli_ekleme_ve_okuma(self):
        b = tampon(bekle_sn=0.0, tampon_sn=100)
        durdur = threading.Event()
        hatalar = []

        def yazar():
            for k in range(0, 4000):
                b.ekle(k * 10 * MS, (k * 0.1, 0, 0), yaw_q(k % 90))
            durdur.set()

        def okur():
            rnd = random.Random(1)
            while not durdur.is_set():
                try:
                    t = rnd.randrange(0, 40000 * MS)
                    s = b.sorgula(t)
                    if s.gecerli and abs(s.konum[0] - t / 1e6 / 100) > 1e-6:             # konum = kaynak_ms / 100: doğrusal enterpolasyon tam olmalı
                        hatalar.append(("konum_yanlis", t, s))
                except Exception as e:  # noqa: BLE001
                    hatalar.append(("istisna", repr(e)))
        ths = [threading.Thread(target=okur) for _ in range(3)] + [threading.Thread(target=yazar)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(30)
        self.assertEqual(hatalar, [])
        self.assertEqual(b.sayaclar()["eklenen"], 4000)


class Kayitlar(unittest.TestCase):
    def test_kare_poz_kaydi_alanlari(self):
        b = tampon()
        b.ekle(0, (0, 0, 0), Q0)
        b.ekle(40 * MS, (4, 0, 0), Q0)
        k = pt.kare_poz_kaydi(1, 7, 20 * MS, b.sorgula(20 * MS))
        self.assertEqual((k["tur"], k["n"], k["gecerli"], k["neden"]), ("kare_poz", 7, True, None))
        json.dumps(k)
        k = pt.kare_poz_kaydi(1, 8, 500 * MS, b.sorgula(500 * MS))
        self.assertEqual((k["gecerli"], k["neden"], k["konum_ned_m"], k["q_wxyz"]), (False, pt.BEKLEME_ASILDI, None, None))

    def test_satir_yazici_bloke_etmez_ve_kapanista_bosaltir(self):
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "t.jsonl")
            y = pt.SatirYazici(yol)
            t0 = time.monotonic()
            for k in range(5000):
                y.ver(pt.telemetri_kaydi(1, k, k, (0, 0, 0), Q0, True, None))
            self.assertLess(time.monotonic() - t0, 1.0)
            y.kapat()
            with open(yol, encoding="utf-8") as f:
                satirlar = f.read().splitlines()
            self.assertEqual(len(satirlar), 5000)
            self.assertEqual([json.loads(s)["kaynak_ns"] for s in satirlar], list(range(5000)))

    def test_yolsuz_yazici_sessiz_degil_ama_zararsiz(self):
        y = pt.SatirYazici(None)
        y.ver({"a": 1})
        y.kapat()


class YaziciHatalari(unittest.TestCase):
    def test_nan_null_yazilir_standart_json(self):
        k = pt.telemetri_kaydi(1, 5, 6, (float("nan"), 1.0, float("inf")), (1.0, 0.0, 0.0, float("-inf")), False, pt.RED_GECERSIZ)
        self.assertEqual((k["konum_ned_m"], k["q_wxyz"]), ([None, 1.0, None], [1.0, 0.0, 0.0, None]))
        metin = json.dumps(k, allow_nan=False)                      # standart dışı NaN/Infinity olamaz
        self.assertNotIn("NaN", metin)
        self.assertNotIn("Infinity", metin)

    def test_nan_ornegi_tampona_girmez_ve_kayda_null_yazilir(self):
        b = tampon()
        kabul, red = b.ekle(1, (float("nan"), 0, 0), Q0)
        self.assertEqual((kabul, red), (False, pt.RED_GECERSIZ))
        with tempfile.TemporaryDirectory() as d:
            y = pt.SatirYazici(os.path.join(d, "t.jsonl"))
            y.ver(pt.telemetri_kaydi(1, 1, 1, (float("nan"), 0, 0), Q0, kabul, red))
            y.kapat()
            with open(os.path.join(d, "t.jsonl"), encoding="utf-8") as f:
                satir = f.read()
            self.assertEqual(json.loads(satir)["konum_ned_m"], [None, 0.0, 0.0])
            self.assertNotIn("NaN", satir)

    def test_dosya_acilamazsa_gunluge_yazilir_ve_dusenler_sayilir(self):
        olaylar = []
        y = pt.SatirYazici("/yok/boyle/bir/dizin/t.jsonl", lambda olay, **kv: olaylar.append((olay, kv)))
        for k in range(10):
            y.ver({"k": k})
        y.kapat()
        o = y.ozet()
        self.assertEqual((o["yazilan"], o["dusen"]), (0, 10))
        self.assertIn("acilamadi", o["hata"])
        self.assertEqual([e[0] for e in olaylar], ["satir_yazici_hata"])      # ilk hata bir kez yazılır, kayıplar sayılır

    def test_yazma_hatasi_sayilir(self):
        olaylar = []
        with tempfile.TemporaryDirectory() as d:
            y = pt.SatirYazici(os.path.join(d, "t.jsonl"), lambda olay, **kv: olaylar.append(olay))
            y.ver({"iyi": 1})
            y.ver({"kotu": float("nan")})                              # allow_nan=False: ValueError
            y.ver({"iyi": 2})
            y.kapat()
        o = y.ozet()
        self.assertEqual(o["yazilan"] + o["dusen"], 3)
        self.assertEqual((o["yazilan"], o["dusen"]), (2, 1))           # serileştirme kayıt kayıt: yalnız hatalı kayıt düşer
        self.assertIn("serilestirilemedi", o["hata"])
        self.assertEqual(olaylar, ["satir_yazici_hata"])

    def test_nan_iceren_grupta_gecerli_kayitlar_yazilir(self):
        """Aynı toplu yazımdaki geçerli kayıtlar tek hatalı kayıt yüzünden düşmez."""
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "t.jsonl")
            with mock.patch.object(pt.threading.Thread, "start", lambda self: None):    # iş parçacığı başlamasın: kuyruk önce dolar, hepsi tek grupta işlenir (deterministik)
                y = pt.SatirYazici(yol)
            for k in range(5):
                y._q.put({"iyi": k})
            y._q.put({"kotu": float("nan")})
            for k in range(5, 10):
                y._q.put({"iyi": k})
            y._q.put(None)
            y._th.run()                                                # yazıcı döngüsünü bu iş parçacığında çalıştır
            y._th = None
            y._kapali = True
            with open(yol, encoding="utf-8") as f:
                satirlar = [json.loads(x) for x in f]
        o = y.ozet()
        self.assertEqual([x["iyi"] for x in satirlar], list(range(10)))
        self.assertEqual((o["yazilan"], o["dusen"], o["kapali_sonrasi"]), (10, 1, 0))

    def test_kapat_iki_kez_guvenli_ve_ilk_cagri_belli(self):
        with tempfile.TemporaryDirectory() as d:
            y = pt.SatirYazici(os.path.join(d, "t.jsonl"))
            y.ver({"a": 1})
            self.assertTrue(y.kapat())                                  # kapatmayı gerçekten yapan çağrı
            self.assertFalse(y.kapat())                                 # ikinci çağrı: zararsız, özet günlüğü yazılmaz
            self.assertEqual(y.ozet()["yazilan"], 1)
        self.assertFalse(pt.SatirYazici(None).kapat())                  # yolsuz yazıcı: özet gürültüsü yok (False)

    def test_iki_is_parcacigi_ayni_anda_kapat_ikisi_de_yazma_bitince_doner(self):
        """İkinci çağıran da yazıcı iş parçacığını bekler: ikisi döndüğünde yazıcı ölü, hiçbir kayıt kuyrukta unutulmamış (os._exit yarışı)."""
        for tur in range(10):
            with tempfile.TemporaryDirectory() as d:
                yol = os.path.join(d, "t.jsonl")
                y = pt.SatirYazici(yol)
                th = y._th
                for k in range(20000):
                    y.ver({"k": k, "dolgu": "x" * 50})
                donus, sonuc = [], []

                def kapat():
                    sonuc.append(y.kapat())
                    donus.append((not th.is_alive(), y.ozet()))
                ths = [threading.Thread(target=kapat) for _ in range(2)]
                for t in ths:
                    t.start()
                for t in ths:
                    t.join()
                self.assertEqual(sorted(sonuc), [False, True])              # özet günlüğünü yalnız biri yazar
                for olu, o in donus:
                    self.assertTrue(olu, tur)                                # iki çağrı da yazıcı bitmeden dönmedi
                    self.assertTrue(o["tamam"])
                    self.assertEqual(o["yazilan"] + o["dusen"] + o["kapali_sonrasi"], o["verilen"])
                with open(yol, encoding="utf-8") as f:
                    self.assertEqual(sum(1 for _ in f), 20000)

    def test_zaman_asimi_acik_uyari_ve_tamam_false(self):
        olaylar = []
        engel = threading.Event()
        with tempfile.TemporaryDirectory() as d:
            gercek = pt.json.dumps
            with mock.patch.object(pt.json, "dumps", lambda *a, **k: (engel.wait(5), gercek(*a, **k))[1]):    # yazıcı iş parçacığı serileştirmede takılır
                y = pt.SatirYazici(os.path.join(d, "t.jsonl"), lambda olay, **kv: olaylar.append((olay, kv)))
                y.KAPAT_BEKLE_SN = 0.2
                for k in range(5):
                    y.ver({"k": k})
                time.sleep(0.1)
                y.kapat()
                y.kapat()                                                    # ikinci çağrı: uyarı bir kez yazılır
                o = y.ozet()
                self.assertFalse(o["tamam"])
                self.assertEqual([e[0] for e in olaylar].count("satir_yazici_zaman_asimi"), 1)
                self.assertEqual(o["verilen"], 5)
                engel.set()
                y._th.join(5)
                self.assertTrue(y.ozet()["tamam"])
                self.assertEqual(y.ozet()["yazilan"] + y.ozet()["dusen"] + y.ozet()["kapali_sonrasi"], 5)

    def test_es_zamanli_ver_ve_kapat_hicbir_kayit_kaybolmaz(self):
        """Eşzamanlı `ver`/`kapat`: yazılan + düşen + kapalı_sonrası == verilen (kayıt işaretten sonra kuyrukta unutulmaz)."""
        for tur in range(30):
            with tempfile.TemporaryDirectory() as d:
                y = pt.SatirYazici(os.path.join(d, "t.jsonl"))
                verilen = [0] * 4

                def uret(i):
                    for k in range(300):
                        y.ver({"i": i, "k": k})
                        verilen[i] += 1
                ths = [threading.Thread(target=uret, args=(i,)) for i in range(4)]
                for t in ths:
                    t.start()
                time.sleep(0.002 * (tur % 5))
                y.kapat()
                for t in ths:
                    t.join()
                y.kapat()
                o = y.ozet()
                self.assertEqual(o["yazilan"] + o["dusen"] + o["kapali_sonrasi"], sum(verilen), (tur, o))
                self.assertEqual(o["verilen"], sum(verilen))
                with open(os.path.join(d, "t.jsonl"), encoding="utf-8") as f:
                    self.assertEqual(sum(1 for _ in f), o["yazilan"])

    def test_kapanis_sonrasi_gelenler_sayilir(self):
        olaylar = []
        with tempfile.TemporaryDirectory() as d:
            y = pt.SatirYazici(os.path.join(d, "t.jsonl"), lambda olay, **kv: olaylar.append(olay))
            y.ver({"a": 1})
            y.kapat()
            for k in range(4):
                y.ver({"gec": k})
            y.kapat()                                                   # tekrar çağrılabilir
        o = y.ozet()
        self.assertEqual((o["yazilan"], o["kapali_sonrasi"], o["dusen"]), (1, 4, 0))
        self.assertEqual(olaylar, ["satir_yazici_kapali_sonrasi"])        # ilk gelen günlüğe yazılır


class KareIsleyiciPozKilidi(unittest.TestCase):
    def kur(self, d):
        b = tampon(bekle_sn=1.0)
        for ms in range(14000, 16001, 40):                              # 14,0 … 16,0 sn kaynak; n=30 (15,0 sn) kapsanır, n=40 (20,0 sn) kapsanmaz
            b.ekle(ms * MS, (ms / 100.0, 0, 0), Q0)
        yol = os.path.join(d, "kare_poz.jsonl")
        return b, yol, ki.KareIsleyici(rota.deney_env_oku(), 1, None, None, lambda *a, **kw: None, None, poz_tamponu=b, poz_yol=yol)

    def test_kayip_poz_beklerken_cagri_bloke_olmaz_sira_korunur(self):
        """`kayip` (gz geri çağrısından gelir) poz beklemesini ayrı iş parçacığında tamamlar: çağrı hemen döner, sonuçlar sırayla ve her numara bir kez yazılır."""
        with tempfile.TemporaryDirectory() as d:
            b, yol, k = self.kur(d)
            t0 = time.monotonic()
            k.kayip(40, 1)                                              # kapsanmayan kare: poz bekleniyor (en çok 1 sn)
            k.kayip(30, 1)                                              # kapsanan kare
            self.assertLess(time.monotonic() - t0, 0.2)                 # çağıran beklemedi
            self.assertFalse(k.defter.var_mi(40))
            self.assertTrue(k.kayip_bekle(5))
            self.assertTrue(k.defter.var_mi(40) and k.defter.var_mi(30))
            k.poz_yazici.kapat()
            with open(yol, encoding="utf-8") as f:
                kayitlar = [json.loads(x) for x in f]
            self.assertEqual([r["n"] for r in kayitlar], [40, 30])      # çağrı sırası
            self.assertEqual({r["n"]: (r["gecerli"], r["neden"]) for r in kayitlar}, {30: (True, None), 40: (False, pt.BEKLEME_ASILDI)})

    def test_defterin_reddettigi_numaraya_ikinci_kare_poz_yazilmaz(self):
        with tempfile.TemporaryDirectory() as d:
            b, yol, k = self.kur(d)
            k.kayip(30, 1)
            k.kayip(30, 2)                                              # ikinci sonuç reddedilir: ikinci kare_poz da yazılmaz
            self.assertTrue(k.kayip_bekle(5))
            k.poz_yazici.kapat()
            with open(yol, encoding="utf-8") as f:
                self.assertEqual(len(f.readlines()), 1)
            self.assertEqual(k.defter.cift_sayisi, 1)


if __name__ == "__main__":
    unittest.main()
