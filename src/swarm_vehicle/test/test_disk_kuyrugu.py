"""Disk destekli kuyruk birim testleri (ROS 2, MAVSDK ve gz gerekmez). Çalıştırma: python3 src/swarm_vehicle/test/test_disk_kuyrugu.py"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle.kamera import disk_kuyrugu as dk  # noqa: E402


class Gunluk:
    def __init__(self):
        self.satirlar = []

    def __call__(self, olay, **kv):
        self.satirlar.append((olay, kv))

    def ad(self, olay):
        return [kv for o, kv in self.satirlar if o == olay]


class Temel(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.kok = self._t.name
        self.dizin = os.path.join(self.kok, "kuyruk", "deneme_1")
        self.gunluk = Gunluk()
        self._kuyruklar = []

    def tearDown(self):
        for q in self._kuyruklar:
            q._yazani_kapat()
        self._t.cleanup()

    def kuyruk(self, alt_sinir_mb=0, bolut_mb=1, **ek):
        ek.setdefault("bayt_olc", lambda o: len(o[2]))
        q = dk.DiskKuyrugu("deneme_1", self.dizin, alt_sinir_mb, bolut_mb, log=self.gunluk, tasma_yol=os.path.join(self.kok, "tasma.jsonl"), **ek)
        self._kuyruklar.append(q)
        return q

    def bolutler(self):
        return sorted(f for f in os.listdir(self.dizin) if f.startswith("bolut_")) if os.path.isdir(self.dizin) else []


class Sira(Temel):
    def test_fifo_bak_cikar_ve_sayaclar(self):
        q = self.kuyruk()
        for n in range(5):
            q.koy((n, 1, bytes([n]) * 1000), n=n)
        self.assertEqual(q.derinlik(), (5, 5000))
        for n in range(5):
            self.assertEqual(q.bak(0.1)[0], n)
            self.assertEqual(q.bak(0.1)[0], n, "bak öğeyi çıkarmaz")
            self.assertEqual(q.derinlik()[0], 5 - n)
            self.assertEqual(q.cikar(), (n, 1, bytes([n]) * 1000))
        self.assertEqual(q.derinlik(), (0, 0))
        self.assertIsNone(q.bak(0.05))
        s = q.sayaclar()
        self.assertEqual((s["giren"], s["cikan"], s["giren_bayt"], s["cikan_bayt"], s["maks_ileti"], s["maks_bayt"]), (5, 5, 5000, 5000, 5, 5000))

    def test_al_bekle_ve_cikar(self):
        q = self.kuyruk()
        self.assertIsNone(q.al(0.05))
        q.koy((7, 1, b"x"))
        self.assertEqual(q.al(0.5), (7, 1, b"x"))
        self.assertIsNone(q.al(0.05))

    def test_bolut_acilir_ve_tuketilince_silinir(self):
        q = self.kuyruk(bolut_mb=0.01)                 # ≈10 KiB bölüt
        for n in range(30):
            q.koy((n, 1, b"a" * 4000))
        self.assertGreater(len(self.bolutler()), 3)
        self.assertGreater(q.disk_bayt(), 100_000)
        ilk = len(self.bolutler())
        for n in range(30):
            self.assertEqual(q.cikar()[0], n)
            self.assertLessEqual(len(self.bolutler()), ilk)
        self.assertEqual(self.bolutler(), [], "tamamen tüketilen bölütler silinmeli")
        self.assertEqual(q.disk_bayt(), 0)
        q.koy((99, 1, b"y"))                           # boşalan kuyruk yeniden kullanılır
        self.assertEqual(q.cikar()[0], 99)

    def test_buyuk_ogeler_bolutu_asabilir(self):
        q = self.kuyruk(bolut_mb=0.001)                # bölüt 1 KiB'dan küçük; her öğe 2 MiB
        buyuk = os.urandom(2 << 20)
        for n in range(3):
            q.koy((n, 1, buyuk))
        for n in range(3):
            o = q.cikar()
            self.assertEqual((o[0], o[2]), (n, buyuk))

    def test_bellekte_oge_baytlari_tutulmaz(self):
        q = self.kuyruk()
        for n in range(20):
            q.koy((n, 1, b"z" * 100_000))
        self.assertEqual(q.derinlik(), (20, 2_000_000))
        self.assertGreaterEqual(q.disk_bayt(), 2_000_000)
        self.assertTrue(all(len(giris) == 4 and all(isinstance(x, int) for x in giris) for giris in q._d), "bellekte yalnız (bölüt, konum, uzunluk, bayt) üst bilgisi")
        self.assertIsNone(q._bas)

    def test_eszamanli_yazar_okuyucu(self):
        q = self.kuyruk(bolut_mb=0.05)
        N = 400
        alinan = []

        def uret():
            for n in range(N):
                q.koy((n, 1, bytes([n % 256]) * 5000))

        def tuket():
            while len(alinan) < N:
                o = q.bak(0.2)
                if o is None:
                    continue
                alinan.append(o[0])
                q.cikar()
        ts = [threading.Thread(target=uret), threading.Thread(target=tuket)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        self.assertEqual(alinan, list(range(N)))
        self.assertEqual(q.derinlik(), (0, 0))

    def test_eski_bolutlu_dizin_reddedilir(self):
        os.makedirs(self.dizin)
        open(os.path.join(self.dizin, "bolut_00000000.kuy"), "wb").close()
        with self.assertRaises(RuntimeError):
            self.kuyruk()


class Duzeltmeler(Temel):
    def test_koy_yazma_sonrasi_ani_kilit_altinda_dondurur(self):
        q = self.kuyruk()
        t0 = time.monotonic_ns()
        t = q.koy((1, 1, b"a"))
        self.assertTrue(t0 <= t <= time.monotonic_ns())
        # tüketici kareyi koy'un döndürdüğü andan ÖNCE alamaz: yazma sonrası an, notify_all'dan önce alınır
        alinan = []
        q2 = self.kuyruk_ad("b")
        th = threading.Thread(target=lambda: alinan.append((q2.al(5), time.monotonic_ns())))
        th.start()
        time.sleep(0.1)
        t2 = q2.koy((2, 1, b"b"))
        th.join(5)
        self.assertLessEqual(t2, alinan[0][1])

    def kuyruk_ad(self, ad):
        q = dk.DiskKuyrugu(ad, os.path.join(self.kok, "kuyruk", ad), 0, 1, log=self.gunluk, bayt_olc=lambda o: len(o[2]))
        self._kuyruklar.append(q)
        return q

    def test_okuma_hatasinda_sayaclar_bozulmaz(self):
        q = self.kuyruk()
        q.koy((1, 1, b"a" * 10))
        q.koy((2, 1, b"b" * 10))
        os.remove(os.path.join(self.dizin, self.bolutler()[0]))
        with self.assertRaises(Exception):
            q.cikar()
        self.assertEqual(q.derinlik(), (2, 20))
        self.assertEqual(q.sayaclar()["cikan"], 0)

    def test_kapat_bos_degilken_yazici_kapanir_ve_gecici_ust_silinir(self):
        ust = os.path.join(self.kok, "gecici_ust")
        os.makedirs(ust)
        q = dk.DiskKuyrugu("g", os.path.join(ust, "g"), 0, 1, log=self.gunluk, gecici_ust=ust)
        self._kuyruklar.append(q)
        q.koy((1, 1, b"a"))
        q.kapat()
        self.assertTrue(q._yazan_f is None, "yazıcı tanıtıcısı kapandı")
        self.assertTrue(os.path.isdir(ust), "boş değil: dizin ve üst dizin yerinde")
        q.cikar()
        self.assertFalse(os.path.exists(ust), "boşalınca dizin ve geçici üst dizin silindi")

    def test_tasma_kaydi_yazilamazsa_gunluge_yazilir(self):
        q = dk.DiskKuyrugu("t", os.path.join(self.kok, "t"), 0, 1, log=self.gunluk, tasma_yol=os.path.join(self.kok, "yok_dizin", "k.jsonl"), test_tasma_n=1)
        self._kuyruklar.append(q)
        with self.assertRaises(dk.KuyrukTasmasi):
            q.koy((1, 1, b"a"), n=1)
        self.assertEqual(len(self.gunluk.ad("tasma_kaydi_yazilamadi")), 1)
        self.assertEqual(self.gunluk.ad("tasma_kaydi_yazilamadi")[0]["seviye"], "(-)")


class Kapanis(Temel):
    def test_bos_kuyruk_kapaninca_dizin_silinir(self):
        q = self.kuyruk()
        q.koy((1, 1, b"a"))
        q.cikar()
        q.kapat()
        self.assertFalse(os.path.exists(self.dizin))
        q.kapat()                                      # idempotent
        with self.assertRaises(RuntimeError):
            q.koy((2, 1, b"b"))

    def test_bos_olmayan_kuyruk_dizinde_kalir_ve_gunluge_yazilir(self):
        q = self.kuyruk()
        q.koy((1, 1, b"a"))
        q.koy((2, 1, b"b"))
        q.kapat()
        self.assertTrue(os.path.isdir(self.dizin))
        self.assertEqual(len(self.bolutler()), 1)
        k = self.gunluk.ad("kuyruk_kapandi_bos_degil")
        self.assertEqual(len(k), 1)
        self.assertEqual((k[0]["kalan_ileti"], k[0]["seviye"]), (2, "(!)"))
        self.assertEqual(q.cikar()[0], 1)              # kapalıyken de boşaltılabilir
        self.assertEqual(q.cikar()[0], 2)
        self.assertFalse(os.path.exists(self.dizin), "son öğe de çıkınca dizin silinir")

    def test_bak_kapali_bos_kuyrukta_beklemeden_doner(self):
        q = self.kuyruk()
        q.kapat()
        t0 = time.monotonic()
        self.assertIsNone(q.bak(5))
        self.assertLess(time.monotonic() - t0, 1)


class Tasma(Temel):
    def test_yazma_hatasi_tasma_olur_ve_oge_atilmaz(self):
        q = self.kuyruk(test_tasma_n=4)
        for n in range(1, 4):
            q.koy((n, 1, b"a" * 100), n=n)
        with self.assertRaises(dk.KuyrukTasmasi):
            q.koy((4, 1, b"a" * 100), n=4)
        self.assertEqual(q.derinlik()[0], 3, "taşan öğe kuyruğa alınmadı (çağıran sahip; sessiz atma yok)")
        self.assertEqual(q.sayaclar()["giren"], 3)
        with self.assertRaises(dk.KuyrukTasmasi):      # taşma sonrası hiçbir öğe sessizce alınmaz/atılmaz
            q.koy((5, 1, b"a"), n=5)
        self.assertEqual([q.cikar()[0] for _ in range(3)], [1, 2, 3], "taşmadan önce kabul edilen öğeler okunabilir")

    def test_tasma_gunluk_ve_kayit(self):
        q = self.kuyruk(test_tasma_n=2)
        q.koy((1, 1, b"a" * 10), n=1)
        with self.assertRaises(dk.KuyrukTasmasi):
            q.koy((2, 1, b"a" * 10), n=2)
        g = self.gunluk.ad("kuyruk_tasmasi")
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]["seviye"], g[0]["kuyruk"], g[0]["n"], g[0]["ileti"]), ("(-)", "deneme_1", 2, 1))
        with open(os.path.join(self.kok, "tasma.jsonl"), encoding="utf-8") as f:
            satirlar = [json.loads(s) for s in f]
        self.assertEqual(len(satirlar), 1)
        k = satirlar[0]
        self.assertEqual((k["tur"], k["kuyruk"], k["n"], k["ileti"]), ("kuyruk_tasmasi", "deneme_1", 2, 1))
        self.assertIn("yazma hatası", k["neden"])
        self.assertGreater(k["bos_alan_bayt"], 0)

    def test_bos_alan_alt_sinirin_altinda(self):
        bos = [10 * dk.MIB]
        q = self.kuyruk(alt_sinir_mb=5, bos_alan=lambda: bos[0])
        q.koy((1, 1, b"a" * 1000), n=1)
        bos[0] = 5 * dk.MIB + 500                      # öğeden sonra alt sınırın altına inecek
        with self.assertRaises(dk.KuyrukTasmasi) as e:
            q.koy((2, 1, b"a" * 1000), n=2)
        self.assertIn("alt sınır", str(e.exception))
        self.assertEqual(q.derinlik()[0], 1)
        self.assertEqual(self.gunluk.ad("kuyruk_tasmasi")[0]["bos_alan_bayt"], 5 * dk.MIB + 500)

    def test_gercek_enospc_tasmadir(self):
        q = self.kuyruk()
        q.koy((1, 1, b"a"))

        class Bozuk:
            def write(self, _):
                raise OSError(28, "No space left on device")

            def flush(self):
                pass

            def close(self):
                pass
        q._yazani_kapat()
        q._yazan_f = Bozuk()
        q._yazan = 0
        with self.assertRaises(dk.KuyrukTasmasi):
            q.koy((2, 1, b"b"), n=2)
        self.assertEqual(q.derinlik()[0], 1)

    def test_test_anahtari_ayristirma(self):
        self.assertEqual(dk.test_tasma_ayristir("gonderim:40", "gonderim_1"), 40)
        self.assertEqual(dk.test_tasma_ayristir("isleme:3;gonderim_2:9", "gonderim_2"), 9)
        self.assertIsNone(dk.test_tasma_ayristir("isleme:3", "gonderim_1"))
        self.assertIsNone(dk.test_tasma_ayristir("", "gonderim_1"))
        for bozuk in ("gonderim", "gonderim:0", ":3", "gonderim:x"):
            with self.assertRaises(ValueError):
                dk.test_tasma_ayristir(bozuk, "gonderim_1")


if __name__ == "__main__":
    unittest.main()
