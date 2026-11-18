"""İlk tarama doğrusu yönü ve yaw hesabı birim testleri (ROS 2 ve MAVSDK gerekmez). Çalıştırma: python3 src/swarm_vehicle/test/test_rota_yon.py"""
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle.ucus import rota  # noqa: E402

KOK = rota.KOK


class IlkDogruYonu(unittest.TestCase):
    def test_kuzey_dogu_guney_bati(self):
        self.assertAlmostEqual(rota.ilk_dogru_yonu_derece([(0, 0), (0, 10)]), 0.0)
        self.assertAlmostEqual(rota.ilk_dogru_yonu_derece([(0, 0), (10, 0)]), 90.0)
        self.assertAlmostEqual(rota.ilk_dogru_yonu_derece([(0, 0), (0, -10)]), 180.0)
        self.assertAlmostEqual(rota.ilk_dogru_yonu_derece([(0, 0), (-10, 0)]), 270.0)
        self.assertAlmostEqual(rota.ilk_dogru_yonu_derece([(5, 5), (15, 15)]), 45.0)

    def test_yon_yok(self):
        self.assertIsNone(rota.ilk_dogru_yonu_derece([]))
        self.assertIsNone(rota.ilk_dogru_yonu_derece([(1, 1)]))
        self.assertIsNone(rota.ilk_dogru_yonu_derece([(1, 1), (1, 1)]))

    def test_gercek_rota_kuzey(self):
        """Üretilen rotada her aracın ilk bacağı y boyunca kuzeye gider (0°)."""
        with open(os.path.join(KOK, "config", "bolge_rota.json"), encoding="utf-8") as f:
            d = json.load(f)
        for r in d["rotalar"]:
            self.assertAlmostEqual(rota.ilk_dogru_yonu_derece(r["noktalar"]), 0.0, places=6)


class YawVeFark(unittest.TestCase):
    @staticmethod
    def kuat_z(derece):
        h = math.radians(derece) / 2
        return (math.cos(h), 0.0, 0.0, math.sin(h))      # NED'de aşağı eksen etrafında dönüş = saat yönünde yaw

    def test_yaw(self):
        for d in (0, 45, 90, 179, 270, 359):
            self.assertAlmostEqual(rota.yaw_ned_derece(self.kuat_z(d)), d, places=6)
        self.assertAlmostEqual(rota.yaw_ned_derece(self.kuat_z(-105)), 255.0, places=6)

    def test_fark_sarma(self):
        self.assertAlmostEqual(rota.aci_farki_derece(10, 350), 20.0)
        self.assertAlmostEqual(rota.aci_farki_derece(350, 10), -20.0)
        self.assertAlmostEqual(rota.aci_farki_derece(0, 0), 0.0)
        self.assertAlmostEqual(abs(rota.aci_farki_derece(0, 180)), 180.0)

    def test_hazirlik_bitis_olcutu(self):
        """Gerçek ölçümden: yaw ≈ −105° (255°), hedef 0° → fark 105° (eşik üstü); yaw 358° → fark −2° (eşik 3° altı)."""
        self.assertGreater(abs(rota.aci_farki_derece(rota.yaw_ned_derece(self.kuat_z(-105)), 0.0)), 3)
        self.assertLessEqual(abs(rota.aci_farki_derece(rota.yaw_ned_derece(self.kuat_z(358)), 0.0)), 3)


if __name__ == "__main__":
    unittest.main()
