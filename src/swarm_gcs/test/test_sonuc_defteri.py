"""Sonuç defteri birim testleri (ROS 2 gerekmez). Çalıştırma: python3 src/swarm_gcs/test/test_sonuc_defteri.py"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_gcs.sonuc_defteri import DURUMLAR, SonucDefteri  # noqa: E402


class Defter(unittest.TestCase):
    def test_tam_ve_eksik(self):
        d = SonucDefteri([1, 2])
        self.assertTrue(d.aralik_ayarla(1, 10, 12))
        self.assertTrue(d.aralik_ayarla(2, 20, 21))
        self.assertEqual(d.eksikler(1), [10, 11, 12])
        for n in (10, 11):
            self.assertEqual(d.ekle(1, n, "tespit_yok", 100 + n), "kabul")
        self.assertEqual(d.eksikler(1), [12])
        self.assertFalse(d.arac_tamam(1))
        self.assertEqual(d.ekle(1, 12, "tespit", 112), "kabul")
        self.assertTrue(d.arac_tamam(1))
        self.assertFalse(d.hepsi_tamam())
        d.ekle(2, 20, "tespit_yok", 200)
        d.ekle(2, 21, "kare_alinamadi", 210)
        self.assertTrue(d.hepsi_tamam())
        self.assertEqual(d.tamam_mono_ns, 210)

    def test_dort_durum_ayri_ve_hepsi_tamam_sayilir(self):
        """Dört durum ayrı sayılır; işlem hatası da "numara tamam" sayılır (COMPLETE'i engellemez), ama durumlar karışmaz."""
        d = SonucDefteri([1])
        d.aralik_ayarla(1, 0, 3)
        for n, durum in enumerate(DURUMLAR):
            d.ekle(1, n, durum, 50 + n)
        self.assertTrue(d.hepsi_tamam())
        self.assertEqual(d.sayilar()[1]["durumlar"], {"tespit": 1, "tespit_yok": 1, "islem_hatasi": 1, "kare_alinamadi": 1})
        with self.assertRaises(ValueError):
            d.ekle(1, 9, "gec_geldi", 1)

    def test_tekrar_ilk_kabul_kalir(self):
        d = SonucDefteri([1])
        d.aralik_ayarla(1, 5, 6)
        self.assertEqual(d.ekle(1, 5, "tespit", 10), "kabul")
        self.assertEqual(d.ekle(1, 5, "tespit_yok", 20), "tekrar")
        self.assertEqual(d.kayit(1, 5)["durum"], "tespit")
        self.assertEqual(d.tekrarlar, [(1, 5, "tespit_yok", 20)])
        self.assertEqual(d.sayilar()[1]["tekrar"], 1)
        self.assertEqual(d.eksikler(1), [6])

    def test_aralik_disi_sayilir_ve_tamamlamaz(self):
        d = SonucDefteri([1])
        d.aralik_ayarla(1, 5, 6)
        self.assertEqual(d.ekle(1, 4, "tespit_yok", 1), "aralik_disi")
        self.assertEqual(d.ekle(1, 7, "tespit_yok", 2), "aralik_disi")
        self.assertEqual(d.aralik_disi(1), [4, 7])
        self.assertEqual(d.eksikler(1), [5, 6])
        self.assertEqual(d.ekle(1, 4, "tespit_yok", 3), "tekrar")          # aralık dışı numaranın ikinci gelişi de tekrar sayılır

    def test_bitisten_once_gelen_sonuclar_tutulur(self):
        d = SonucDefteri([1])
        self.assertIsNone(d.eksikler(1))
        self.assertFalse(d.arac_tamam(1))
        for n in (5, 6, 9):                                                 # aralık bilinmiyor: hepsi tutulur
            self.assertEqual(d.ekle(1, n, "tespit_yok", n), "kabul")
        self.assertFalse(d.hepsi_tamam())
        d.aralik_ayarla(1, 5, 6, mono_ns=99)
        self.assertEqual(d.aralik_disi(1), [9])                             # aralık bilinince sınıflanır
        self.assertTrue(d.hepsi_tamam())
        self.assertEqual(d.tamam_mono_ns, 99)                               # aralığın bildirildiği an tamamlanma anıdır (sonuçlar daha önce gelmişti)
        self.assertFalse(d.aralik_ayarla(1, 0, 100))                        # ikinci bildirim aralığı değiştirmez
        self.assertEqual(d.beklenen[1], (5, 6))

    def test_bilinmeyen_arac(self):
        d = SonucDefteri([1])
        self.assertEqual(d.ekle(7, 1, "tespit", 5), "bilinmeyen_arac")
        self.assertEqual(d.bilinmeyen_arac, [(7, 1, "tespit", 5)])
        self.assertFalse(d.aralik_ayarla(7, 0, 1))

    def test_bekle_hepsi_tamam(self):
        d = SonucDefteri([1])
        d.aralik_ayarla(1, 0, 1)
        d.ekle(1, 0, "tespit_yok", 1)
        self.assertFalse(d.bekle_hepsi_tamam(0.3))
        t = threading.Timer(0.2, d.ekle, args=(1, 1, "tespit_yok", 2))
        t.start()
        baslangic = time.monotonic()
        self.assertTrue(d.bekle_hepsi_tamam(5.0))
        self.assertGreaterEqual(time.monotonic() - baslangic, 0.15)
        t.join()


if __name__ == "__main__":
    unittest.main()
