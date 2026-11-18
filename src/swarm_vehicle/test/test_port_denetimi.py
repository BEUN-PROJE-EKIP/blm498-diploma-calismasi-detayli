"""Sabit port / geçici port aralığı denetimi birim testleri (ROS 2 gerekmez). Çalıştırma: python3 src/swarm_vehicle/test/test_port_denetimi.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle.ucus import port_denetimi as pd  # noqa: E402
from swarm_vehicle.ucus import rota  # noqa: E402


def aralik_dosyasi(metin):
    f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt")
    f.write(metin)
    f.close()
    return f.name


class AralikOkuma(unittest.TestCase):
    def test_dosyadan_okunur_ve_icinde_disinda(self):
        yol = aralik_dosyasi("32768\t60999\n")
        self.addCleanup(os.unlink, yol)
        self.assertEqual(pd.gecici_aralik(yol), (32768, 60999))
        for port in (20051, 27200, 32767):
            pd.denetle(port, "x", yol)                                    # aralık dışı: hata yok
        for port in (32768, 47200, 50052, 60999):
            with self.assertRaises(pd.PortAraligiHatasi) as k:
                pd.denetle(port, "gRPC", yol)
            self.assertIn(str(port), str(k.exception))

    def test_aralik_makine_ayarina_gore(self):
        yol = aralik_dosyasi("10000 20000\n")                             # aralık sabit değil: 20051 dışarıda, 15000 içeride
        self.addCleanup(os.unlink, yol)
        pd.denetle(20051, "gRPC", yol)
        with self.assertRaises(pd.PortAraligiHatasi):
            pd.denetle(15000, "gRPC", yol)

    def test_okunamayan_aralik_denetlenemez_gecer_ama_uyarir(self):
        self.assertIsNone(pd.gecici_aralik("/yok/yok/yok"))
        uyarilar = []
        pd.denetle(50052, "gRPC", "/yok/yok/yok", uyar=uyarilar.append)   # çalışma durmaz (hata yok)
        self.assertEqual(len(uyarilar), 1)                                  # ama sessiz de geçmez
        self.assertIn("okunamadı", uyarilar[0])
        self.assertIn("50052", uyarilar[0])

    def test_okunamayan_aralik_uyari_verilmediyse_stderr(self):
        import contextlib
        import io
        hata = io.StringIO()
        with contextlib.redirect_stderr(hata):
            pd.denetle(50052, "gRPC", "/yok/yok/yok")
        self.assertTrue(hata.getvalue().startswith("(!) "))
        self.assertIn("okunamadı", hata.getvalue())

    def test_okunabilen_aralikta_uyari_yok(self):
        yol = aralik_dosyasi("32768 60999\n")
        self.addCleanup(os.unlink, yol)
        uyarilar = []
        pd.denetle(20051, "gRPC", yol, uyar=uyarilar.append)
        self.assertEqual(uyarilar, [])

    def test_bozuk_icerik(self):
        yol = aralik_dosyasi("abc\n")
        self.addCleanup(os.unlink, yol)
        self.assertIsNone(pd.gecici_aralik(yol))


class YapilandirmaPortlari(unittest.TestCase):
    """Gerçek yapılandırmadaki sabit portlar bu makinenin geçici aralığının dışında olmalı."""

    def test_sabit_portlar_aralik_disinda(self):
        ham = rota.deney_env_oku()
        portlar = [("gRPC", int(p)) for p in ham["MAVSDK_GRPC_PORTS"].split()] + [("PX4 MAVLink", int(p)) for p in ham["PX4_MAVLINK_PORTS"].split()]
        portlar += [("merkezi mod", int(ham["MERKEZI_TCP_PORT_TABAN"]) + i) for i in range(3)] + [("sentetik yük", int(ham["SENTETIK_YUK_PORT_TABAN"]) + i) for i in range(3)]
        for ad, p in portlar:
            pd.denetle(p, ad)


class AdaptorBaslangic(unittest.TestCase):
    def test_aralik_ici_grpc_portu_acik_hata(self):
        aralik = pd.gecici_aralik()
        if aralik is None:
            self.skipTest("geçici port aralığı okunamıyor")
        from swarm_vehicle.ucus import px4_adapter
        ham = dict(rota.deney_env_oku(), MAVSDK_GRPC_PORTS=f"{aralik[0] + 5} {aralik[0] + 6} {aralik[0] + 7}")
        with tempfile.TemporaryDirectory() as gd:
            a = px4_adapter.Px4Adapter(1, deney_env=ham, gunluk_dizini=gd)
            with self.assertRaises(px4_adapter.Px4Hatasi) as k:
                a.baglan()
            self.assertIn("geçici port aralığının", str(k.exception))
            self.assertIsNone(a._thread)                                  # hiçbir şey başlatılmadı


if __name__ == "__main__":
    unittest.main()
