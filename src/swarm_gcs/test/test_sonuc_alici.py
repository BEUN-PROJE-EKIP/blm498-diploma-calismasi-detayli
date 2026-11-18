"""Yer istasyonu kare sonucu alıcısı birim testleri (yalnız ROS 2 ortamı yüklüyse: setup/env.sh + install/setup.bash; yoksa atlanır). Çalıştırma: python3 src/swarm_gcs/test/test_sonuc_alici.py"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "swarm_vehicle"))
try:
    from swarm_msgs.msg import Detection, FrameResult
    from rclpy.qos import QoSProfile  # noqa: F401
    ROS = True
except ImportError:
    ROS = False

if ROS:
    from swarm_gcs.uc_mod.sonuc_alici import SonucAlici
    from swarm_vehicle.ucus import rota


def ileti(arac, n, durum, sinif_no=None, guven=0.8, konum=(1.0, 2.0)):
    m = FrameResult()
    m.vehicle_id, m.numbering_mode, m.frame_number, m.status = arac, FrameResult.NUMBERING_GRID, n, durum
    m.sim_stamp.sec, m.sim_stamp.nanosec = n // 2, (n % 2) * 500_000_000
    if sinif_no is not None:
        d = Detection()
        d.class_id, d.confidence = sinif_no, guven
        d.has_position = konum is not None
        d.east, d.north = (konum or (0.0, 0.0))
        m.detections.append(d)
    return m


@unittest.skipUnless(ROS, "ROS 2 ortamı (swarm_msgs, rclpy) yüklü değil")
class Alici(unittest.TestCase):
    def setUp(self):
        self.ham = rota.deney_env_oku()
        dugum = mock.MagicMock()
        self.log = []
        self.a = SonucAlici(dugum, self.ham, [1, 2], None, lambda olay, **kv: self.log.append((olay, kv)))
        self.a.defter.aralik_ayarla(1, 0, 20)

    def test_gecerli_tespit_deftere_tespit_ve_sim_damgasiyla_girer(self):
        self.a._sonuc_geldi(ileti(1, 7, FrameResult.STATUS_DETECTIONS, 1, 0.9, (3.0, 4.0)))
        k = self.a.defter.kayit(1, 7)
        self.assertEqual(k["sim_damga_ns"], 3_500_000_000)
        self.assertEqual(k["tespitler"], [{"sinif": self.ham["MODEL_SINIFLAR"].split()[1], "guven": k["tespitler"][0]["guven"], "konum": [3.0, 4.0]}])
        self.assertAlmostEqual(k["tespitler"][0]["guven"], 0.9, places=6)
        self.assertEqual(self.a.gecersiz, 0)

    def test_konumsuz_tespit_konum_none(self):
        self.a._sonuc_geldi(ileti(1, 8, FrameResult.STATUS_DETECTIONS, 0, 0.5, None))
        self.assertIsNone(self.a.defter.kayit(1, 8)["tespitler"][0]["konum"])

    def test_sinif_no_aralik_disi_cokmez_gecersiz_sayilir(self):
        for kotu in (2, 7, 255):
            self.a._sonuc_geldi(ileti(1, 9, FrameResult.STATUS_DETECTIONS, kotu))
        self.assertEqual(self.a.gecersiz, 3)
        self.assertIsNone(self.a.defter.kayit(1, 9), "geçersiz ileti deftere girmez")
        self.assertTrue(all(o == "sonuc_gecersiz" for o, _ in self.log))
        self.a._sonuc_geldi(ileti(1, 9, FrameResult.STATUS_DETECTIONS, 0))        # sonradan gelen geçerli ileti kabul edilir
        self.assertIsNotNone(self.a.defter.kayit(1, 9))

    def test_merkezi_sonuc_ver_tespit_ve_sim_damgasi(self):
        self.a.sonuc_ver(1, 11, "tespit", 5_500_000_000, [{"sinif": "insan", "guven": 0.7, "konum": [1.0, 1.0], "kutu": [0, 0, 1, 1]}])
        k = self.a.defter.kayit(1, 11)
        self.assertEqual((k["sim_damga_ns"], k["tespitler"]), (5_500_000_000, [{"sinif": "insan", "guven": 0.7, "konum": [1.0, 1.0]}]))


if __name__ == "__main__":
    unittest.main()
