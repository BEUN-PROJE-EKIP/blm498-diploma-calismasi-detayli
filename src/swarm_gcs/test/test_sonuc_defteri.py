"""Sonuç defteri birim testleri (ROS 2 gerekmez). Çalıştırma: python3 src/swarm_gcs/test/test_sonuc_defteri.py"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "swarm_vehicle"))
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


class TaramaBitisiGorevKimligi(unittest.TestCase):
    """SonucAlici tarama bitişi: geçerli görev kimliğiyle uyuşmayan ileti deftere yazılmaz (ROS 2 gerekmez: düğümsüz nesne kurulur)."""

    def _alici(self, mission_id):
        from types import SimpleNamespace
        from swarm_gcs.sonuc_alici import SonucAlici
        a = SonucAlici.__new__(SonucAlici)
        a.log = lambda olay, **kv: a.gunluk.append((olay, kv))
        a.gunluk = []
        a.defter = SonucDefteri([1, 2])
        a.mission_id, a.yok_sayilan_bitis = mission_id, 0
        return a, SimpleNamespace

    def test_uyusmayan_gorev_kimligi_deftere_yazilmaz(self):
        a, NS = self._alici("G1")
        a._bitis_geldi(NS(mission_id="ESKI", vehicle_id=1, n_first=10, n_last=12))
        self.assertIsNone(a.defter.eksikler(1))                         # aralık ayarlanmadı
        self.assertEqual(a.yok_sayilan_bitis, 1)
        olay, kv = a.gunluk[0]
        self.assertEqual((olay, kv["neden"], kv["alinan"], kv["beklenen"]), ("tarama_bitis_yok_sayildi", "mission_id_uyusmuyor", "ESKI", "G1"))
        a._bitis_geldi(NS(mission_id="G1", vehicle_id=1, n_first=10, n_last=12))
        self.assertEqual(a.defter.eksikler(1), [10, 11, 12])             # doğru kimlik kabul edilir
        self.assertEqual(a.yok_sayilan_bitis, 1)

    def test_kimlik_verilmediyse_denetim_yok(self):
        a, NS = self._alici(None)
        a._bitis_geldi(NS(mission_id="HERHANGI", vehicle_id=2, n_first=1, n_last=2))
        self.assertEqual(a.defter.eksikler(2), [1, 2])


if __name__ == "__main__":
    unittest.main()
