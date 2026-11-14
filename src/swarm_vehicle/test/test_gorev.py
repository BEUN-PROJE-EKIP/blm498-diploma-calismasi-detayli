"""Mission ↔ bolge_rota.json karşılaştırması ve komut yolu iskeleti birim testleri (ROS 2 gerekmez). Çalıştırma: python3 src/swarm_vehicle/test/test_gorev.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle import gorev, komut_yolu, rota  # noqa: E402

DOSYA = os.path.join(rota.KOK, "config", "bolge_rota.json")


class MissionKarsilastirma(unittest.TestCase):
    def setUp(self):
        self.br = gorev.bolge_rota_oku(DOSYA)

    def test_uretilen_mission_yerel_dosyayla_esit(self):
        for a in (1, 2, 3):
            m = gorev.mission_sozlugu(self.br, a, "G1")
            self.assertEqual(gorev.mission_karsilastir(m, self.br, a), [])
            self.assertEqual(len(gorev.mission_noktalari(m)), len(next(r for r in self.br["rotalar"] if r["arac_kimligi"] == a)["noktalar"]))

    def test_float32_yuvarlama_payi(self):
        m = gorev.mission_sozlugu(self.br, 1, "G1")
        m["altitude_m"] = float(__import__("struct").unpack("f", __import__("struct").pack("f", 30.0))[0])
        m["speed_ms"] = float(__import__("struct").unpack("f", __import__("struct").pack("f", 5.0))[0])
        self.assertEqual(gorev.mission_karsilastir(m, self.br, 1), [])

    def test_nokta_farki(self):
        m = gorev.enjeksiyon_sapma(gorev.mission_sozlugu(self.br, 2, "G1"), 1.0)
        fark = gorev.mission_karsilastir(m, self.br, 2)
        self.assertTrue(fark and fark[0].startswith("nokta 0"), fark)

    def test_irtifa_hiz_bolge_arac_farki(self):
        m = gorev.mission_sozlugu(self.br, 1, "G1")
        self.assertTrue(any("altitude_m" in f for f in gorev.mission_karsilastir(dict(m, altitude_m=31.0), self.br, 1)))
        self.assertTrue(any("speed_ms" in f for f in gorev.mission_karsilastir(dict(m, speed_ms=6.0), self.br, 1)))
        self.assertTrue(any("region_x_min" in f for f in gorev.mission_karsilastir(dict(m, region_x_min=-149.0), self.br, 1)))
        self.assertTrue(any("region_id" in f for f in gorev.mission_karsilastir(dict(m, region_id="B2"), self.br, 1)))
        self.assertTrue(any("vehicle_id" in f for f in gorev.mission_karsilastir(dict(m, vehicle_id=2), self.br, 1)))

    def test_nokta_sayisi_ve_yanlis_arac_dosyasi(self):
        m = gorev.mission_sozlugu(self.br, 1, "G1")
        m["waypoints"] = m["waypoints"][:-1]
        self.assertTrue(any("nokta sayısı" in f for f in gorev.mission_karsilastir(m, self.br, 1)))
        self.assertTrue(gorev.mission_karsilastir(gorev.mission_sozlugu(self.br, 1, "G1"), self.br, 9))           # araç 9 için rota yok

    def test_mesaj_gidis_donus(self):
        class Nokta:
            x = y = z = 0.0

        class Mesaj:
            def __init__(self):
                self.waypoints = []
        m = gorev.mission_sozlugu(self.br, 3, "G7")
        ileti = gorev.mesaj_doldur(Mesaj, Nokta, m)
        self.assertEqual(gorev.mesajdan_sozluk(ileti)["waypoints"], m["waypoints"])
        self.assertEqual(gorev.mission_karsilastir(gorev.mesajdan_sozluk(ileti), self.br, 3), [])

    def test_sha256_kararli(self):
        self.assertEqual(gorev.dosya_sha256(DOSYA), gorev.dosya_sha256(DOSYA))
        self.assertEqual(len(gorev.dosya_sha256(DOSYA)), 64)


class KomutYolu(unittest.TestCase):
    def test_dogru_arac_ve_sira_yine_de_reddedilir(self):
        ack, neden, son = komut_yolu.denetle(2, 2, 1, None)
        self.assertEqual((ack, neden, son), (komut_yolu.ACK_REJECTED, komut_yolu.NEDEN_TUR_TANIMSIZ, 1))

    def test_yanlis_arac(self):
        ack, neden, son = komut_yolu.denetle(2, 1, 5, None)
        self.assertEqual((ack, neden, son), (komut_yolu.ACK_REJECTED, komut_yolu.NEDEN_YANLIS_ARAC, None))

    def test_tekrar_ve_geriye_sira(self):
        _, _, son = komut_yolu.denetle(2, 2, 3, None)
        self.assertEqual(komut_yolu.denetle(2, 2, 3, son)[1], komut_yolu.NEDEN_TEKRAR_SIRA)
        self.assertEqual(komut_yolu.denetle(2, 2, 2, son)[1], komut_yolu.NEDEN_TEKRAR_SIRA)
        ack, neden, son2 = komut_yolu.denetle(2, 2, 4, son)
        self.assertEqual((neden, son2), (komut_yolu.NEDEN_TUR_TANIMSIZ, 4))


class AdaptorKomutIsle(unittest.TestCase):
    """px4_adapter.komut_isle PX4'e YAZMAZ: `_yaz` çağrılırsa test düşer; komut sayacı artmaz; günlükte `komut_reddedildi` olayı."""

    def test_yaz_cagrilmaz(self):
        from swarm_vehicle import px4_adapter
        klasor = tempfile.mkdtemp()
        a = px4_adapter.Px4Adapter(2, deney_env=rota.deney_env_oku(), gunluk_dizini=klasor)

        async def yasak(*_a, **_k):
            raise AssertionError("komut_isle _yaz çağırdı")
        a._yaz = yasak
        self.assertEqual(a.komut_isle(a.arac_kimligi, 1), (komut_yolu.ACK_REJECTED, komut_yolu.NEDEN_TUR_TANIMSIZ))
        self.assertEqual(a.komut_isle(a.arac_kimligi, 1)[1], komut_yolu.NEDEN_TEKRAR_SIRA)
        self.assertEqual(a.komut_isle(3, 9)[1], komut_yolu.NEDEN_YANLIS_ARAC)
        self.assertEqual(a.komut_sayaci, 0)
        with open(os.path.join(klasor, f"px4_adapter_{a.arac_kimligi}.log"), encoding="utf-8") as f:
            satirlar = f.read().splitlines()
        self.assertEqual(len(satirlar), 3)
        self.assertTrue(all(" komut_reddedildi " in s for s in satirlar))
        self.assertTrue(all(" komut " not in s.replace("komut_reddedildi", "") for s in satirlar))     # `_yaz`'ın `komut` olayı yok


if __name__ == "__main__":
    unittest.main()
