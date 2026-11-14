"""Kare sonucu yayımcısı ve QoS ayarı birim testleri (ROS 2 gerekmez). Çalıştırma: python3 src/swarm_vehicle/test/test_sonuc_yayin.py"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle import rota  # noqa: E402
from swarm_vehicle import sonuc_yayin as sy  # noqa: E402


class QosAyari(unittest.TestCase):
    def test_gercek_yapilandirma(self):
        a = rota.kare_sonuc_qos_ayar(rota.deney_env_oku())
        self.assertEqual(a["guvenilirlik"], "reliable")
        self.assertEqual((a["gecmis"], a["dayaniklilik"]), ("keep_last", "transient_local"))
        self.assertGreaterEqual(a["derinlik"], 600)                 # bir koşudaki en büyük görev karesi sayısından (360 m adayı: 563) büyük

    def test_gecersiz_degerler(self):
        ham = rota.deney_env_oku()
        for anahtar, deger in (("QOS_KARE_SONUC_GUVENILIRLIK", "best_effort"), ("QOS_KARE_SONUC_GECMIS", "x"), ("QOS_KARE_SONUC_DAYANIKLILIK", "kalici"),
                               ("QOS_KARE_SONUC_DERINLIK", "0"), ("QOS_KARE_SONUC_DERINLIK", "abc")):
            with self.assertRaises(ValueError, msg=f"{anahtar}={deger}"):
                rota.kare_sonuc_qos_ayar(dict(ham, **{anahtar: deger}))
        eksik = dict(ham)
        del eksik["QOS_KARE_SONUC_DERINLIK"]
        with self.assertRaises(ValueError):
            rota.kare_sonuc_qos_ayar(eksik)


class Enjeksiyon(unittest.TestCase):
    def test_ayristirma(self):
        e = sy.YayinEnjeksiyonu("gecik=+3:2.5,77:1")
        self.assertEqual(e.gecikme_sn(13, 10), 2.5)
        self.assertEqual(e.gecikme_sn(77, 10), 1.0)
        self.assertEqual(e.gecikme_sn(14, 10), 0.0)
        self.assertFalse(sy.YayinEnjeksiyonu("").acik)
        with self.assertRaises(ValueError):
            sy.YayinEnjeksiyonu("dusur=+1")
        with self.assertRaises(ValueError):
            sy.YayinEnjeksiyonu("gecik=+1")


class Yayinci(unittest.TestCase):
    def kur(self, yayinla, enj="", onay=None):
        klasor = tempfile.mkdtemp()
        yol = os.path.join(klasor, "arac_sureci_1.jsonl")
        y = sy.SonucYayinci(1, 2, yayinla, yol, lambda *a, **k: None, enjeksiyon_metni=enj, onay_bekle=onay)
        y.baslat()
        return y, yol

    def test_ver_bloke_etmez_ve_sira_korunur(self):
        alinan = []

        def yavas(m):
            time.sleep(0.2)
            alinan.append(m)
        y, yol = self.kur(yavas)
        t0 = time.monotonic()
        for n in range(5):
            y.ver(f"m{n}", 20 + n)
        self.assertLess(time.monotonic() - t0, 0.1)                 # kare işleme iş parçacığı yayımı beklemez
        tamam, onay = y.kapat(10.0)
        self.assertTrue(tamam and onay)
        self.assertEqual(alinan, [f"m{n}" for n in range(5)])
        satirlar = [json.loads(s) for s in open(yol, encoding="utf-8")]
        self.assertEqual([s["n"] for s in satirlar], [20, 21, 22, 23, 24])
        self.assertTrue(all(s["olay"] == "gonderim" and s["kaynak"] == "arac_sureci" and s["arac_kimligi"] == 1 for s in satirlar))
        self.assertEqual(satirlar[0]["sim_damga_ns"], 10 * 10 ** 9)  # n / 2 s
        self.assertEqual(sorted(s["mono_ns"] for s in satirlar), [s["mono_ns"] for s in satirlar])

    def test_yayim_hatasi_sayilir_ve_akis_surer(self):
        alinan = []

        def bazen_hata(m):
            if m == "kotu":
                raise RuntimeError("yayım hatası")
            alinan.append(m)
        y, _ = self.kur(bazen_hata)
        for n, m in enumerate(("a", "kotu", "b")):
            y.ver(m, n)
        tamam, _ = y.kapat(5.0)
        self.assertTrue(tamam)
        self.assertEqual((alinan, y.hata_sayisi, y.yayimlanan), (["a", "b"], 1, 2))

    def test_gecikmeli_yayim_digerlerini_tutmaz(self):
        zamanlar = {}

        def yayinla(m):
            zamanlar[m] = time.monotonic()
        y, _ = self.kur(yayinla, enj="gecik=+1:0.6")
        y.n_ilk = 20
        t0 = time.monotonic()
        for n in range(3):
            y.ver(f"m{n}", 20 + n)
        tamam, _ = y.kapat(5.0)
        self.assertTrue(tamam)
        self.assertLess(zamanlar["m0"] - t0, 0.3)
        self.assertLess(zamanlar["m2"] - t0, 0.3)                   # sonraki ileti geciken iletiyi beklemedi
        self.assertGreaterEqual(zamanlar["m1"] - t0, 0.55)         # +1 numaralı ileti ≈ 0,6 sn tutuldu

    def test_onay_zaman_asimi_uyari(self):
        gunluk = []
        klasor = tempfile.mkdtemp()
        y = sy.SonucYayinci(1, 2, lambda m: None, os.path.join(klasor, "x.jsonl"), lambda olay, **kv: gunluk.append(olay), onay_bekle=lambda sn: False)
        y.baslat()
        y.ver("a", 20)
        tamam, onay = y.kapat(2.0)
        self.assertTrue(tamam)
        self.assertFalse(onay)
        self.assertIn("sonuc_yayin_uyari", gunluk)


if __name__ == "__main__":
    unittest.main()
