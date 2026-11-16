"""Durum makinesi birim testleri (ROS 2 ve MAVSDK gerekmez). Çalıştırma: python3 src/swarm_vehicle/test/test_durum_makinesi.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle import durum_makinesi as dm  # noqa: E402

S = dm.DurumMakinesi


def bariyerde():
    m = S()
    assert m.hazir()
    return m


def taramada(mid="G1", t_s=10 * 10 ** 9):
    m = bariyerde()
    assert m.tarama_baslat(mid, t_s)
    return m


def waitte():
    m = taramada()
    assert m.son_nokta(50 * 10 ** 9)
    return m


class IzinliGecisler(unittest.TestCase):
    def test_tam_dizi(self):
        m = S()
        self.assertEqual(m.durum, dm.STATE_HAZIR)
        self.assertTrue(m.hazir())
        self.assertEqual(m.durum, dm.STATE_BARIYER_BEKLE)
        self.assertTrue(m.tarama_baslat("G1", 10 * 10 ** 9))
        self.assertEqual((m.durum, m.mission_id, m.t_s_ns), (dm.STATE_TARAMA, "G1", 10 * 10 ** 9))
        self.assertTrue(m.son_nokta(60 * 10 ** 9))
        self.assertEqual((m.durum, m.t_b_ns), (dm.STATE_WAIT, 60 * 10 ** 9))
        self.assertTrue(m.complete("G1"))
        self.assertEqual(m.durum, dm.STATE_TAMAMLANDI)
        self.assertEqual(sum(1 for o in m.olaylar if o.startswith("gecis")), 4)
        self.assertFalse(any(o.startswith("yok_sayildi") for o in m.olaylar))

    def test_durum_degerleri_mesajla_ayni(self):
        self.assertEqual([dm.STATE_HAZIR, dm.STATE_BARIYER_BEKLE, dm.STATE_TARAMA, dm.STATE_WAIT, dm.STATE_TAMAMLANDI], [1, 2, 3, 4, 5])


class YasakGecisler(unittest.TestCase):
    def yok(self, m, durum, ne):
        once = (m.durum, m.mission_id, m.t_s_ns, m.t_b_ns, len(m.olaylar))
        self.assertFalse(ne())
        self.assertEqual((m.durum, m.mission_id, m.t_s_ns, m.t_b_ns), once[:4])
        self.assertEqual(m.durum, durum)
        self.assertEqual(len(m.olaylar), once[4] + 1)
        self.assertTrue(m.olaylar[-1].startswith("yok_sayildi"))

    def test_bariyer_oncesi_tarama_baslat(self):
        m = S()
        self.yok(m, dm.STATE_HAZIR, lambda: m.tarama_baslat("G1", 1))

    def test_tarama_baslat_tekrar_ve_tarama_icinde(self):
        m = taramada()
        self.yok(m, dm.STATE_TARAMA, lambda: m.tarama_baslat("G2", 5))
        self.assertEqual(m.mission_id, "G1")

    def test_hazir_yalniz_hazirda(self):
        for m, d in ((bariyerde(), dm.STATE_BARIYER_BEKLE), (taramada(), dm.STATE_TARAMA), (waitte(), dm.STATE_WAIT)):
            self.yok(m, d, m.hazir)

    def test_complete_baska_durumlarda(self):
        for m, d in ((S(), dm.STATE_HAZIR), (bariyerde(), dm.STATE_BARIYER_BEKLE), (taramada(), dm.STATE_TARAMA)):
            self.yok(m, d, lambda m=m: m.complete("G1"))

    def test_wait_ikinci_son_nokta(self):
        m = waitte()
        self.yok(m, dm.STATE_WAIT, lambda: m.son_nokta(70 * 10 ** 9))
        self.assertEqual(m.t_b_ns, 50 * 10 ** 9)

    def test_son_nokta_tarama_disinda(self):
        for m, d in ((S(), dm.STATE_HAZIR), (bariyerde(), dm.STATE_BARIYER_BEKLE)):
            self.yok(m, d, lambda m=m: m.son_nokta(1))

    def test_yanlis_mission_id_complete(self):
        m = waitte()
        self.yok(m, dm.STATE_WAIT, lambda: m.complete("YANLIS"))
        self.yok(m, dm.STATE_WAIT, lambda: m.complete(""))
        self.assertTrue(m.complete("G1"))

    def test_yanlis_mission_id_tarama_baslat(self):
        m = S(beklenen_mission_id="G1")
        m.hazir()
        self.yok(m, dm.STATE_BARIYER_BEKLE, lambda: m.tarama_baslat("G9", 1))
        self.assertTrue(m.tarama_baslat("G1", 1))

    def test_bos_mission_id_tarama_baslat(self):
        m = bariyerde()
        self.yok(m, dm.STATE_BARIYER_BEKLE, lambda: m.tarama_baslat("", 1))

    def test_tamamlandidan_geri_donus_yok(self):
        m = waitte()
        m.complete("G1")
        for ne in (m.hazir, lambda: m.tarama_baslat("G1", 1), lambda: m.son_nokta(1), lambda: m.complete("G1")):
            self.yok(m, dm.STATE_TAMAMLANDI, ne)


class KareAraligi(unittest.TestCase):
    NS = 10 ** 9

    def test_sinir_degerleri(self):
        # elle hesap: n_ilk = ceil(2·t_s), n_son = floor(2·t_b)
        beklenen = [
            (10.0, 20, 20),     # tam saniye: 2·10 = 20
            (10.25, 21, 20),    # 20,5 → ceil 21; floor 20
            (10.5, 21, 21),     # tam buçuk: 21 → 21
            (10.75, 22, 21),    # 21,5 → 22; 21
            (0.0, 0, 0),
        ]
        for t, n_ilk, n_son in beklenen:
            ns = round(t * self.NS)
            self.assertEqual(dm.kare_araligi(ns, ns), (n_ilk, n_son), t)

    def test_ns_inceligi(self):
        self.assertEqual(dm.kare_araligi(10 * self.NS + 1, 10 * self.NS - 1), (21, 19))      # 20,000000002 → 21 ; 19,999999998 → 19
        self.assertEqual(dm.kare_araligi(10 * self.NS, 10 * self.NS + 499999999), (20, 20))   # 20,999999998 → 20

    def test_hz_parametresi_tek_kaynak(self):
        """Kare hızı parametredir (CAM_RATE_HZ): 4 Hz için n = 4·t; öntanımlı 2 Hz davranışı değişmez."""
        self.assertEqual(dm.kare_araligi(10 * self.NS, 10 * self.NS, 4), (40, 40))
        self.assertEqual(dm.kare_araligi(int(10.1 * self.NS), int(10.6 * self.NS), 4), (41, 42))      # ceil(40,4)=41; floor(42,4)=42
        self.assertEqual(dm.kare_araligi(int(10.25 * self.NS), int(60.5 * self.NS)), dm.kare_araligi(int(10.25 * self.NS), int(60.5 * self.NS), 2))
        m = dm.DurumMakinesi(hz=4)
        m.hazir()
        m.tarama_baslat("G1", int(10.25 * self.NS))
        m.son_nokta(int(60.5 * self.NS))
        self.assertEqual(m.kare_araligi(), (41, 242))

    def test_hz_tam_sayi_degilse_hata(self):
        for kotu in (2.5, 0, -2, "x", None):
            with self.assertRaises(ValueError, msg=repr(kotu)):
                dm.kare_araligi(0, 0, kotu)
            with self.assertRaises(ValueError, msg=repr(kotu)):
                dm.DurumMakinesi(hz=kotu)
        self.assertEqual(dm.kare_araligi(0, self.NS, 2.0), (0, 2))             # 2.0 tam sayı değeri: kabul

    def test_makine_aralik(self):
        m = S()
        self.assertIsNone(m.kare_araligi())
        m.hazir()
        m.tarama_baslat("G1", int(10.25 * self.NS))
        m.son_nokta(int(60.5 * self.NS))
        self.assertEqual(m.kare_araligi(), (21, 121))


if __name__ == "__main__":
    unittest.main(verbosity=1)
