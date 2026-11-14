"""Görev koordinatörü saf mantığı, izleme ve görev kaydı birim testleri (ROS 2 gerekmez). Çalıştırma: python3 src/swarm_gcs/test/test_gorev_mantik.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_gcs"))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))
from swarm_gcs import gorev_mantik as gm  # noqa: E402
from swarm_gcs.gorev_kayit import GorevKaydi  # noqa: E402
from swarm_gcs.izleme import DurumIzleyici  # noqa: E402

A = [1, 2, 3]
BARIYER, TAMAM = 2, 5


def hazir_et(k, araclar=A, t=100):
    for a in araclar:
        k.durum_geldi(a, BARIYER, t + a)


class Koordinasyon(unittest.TestCase):
    def test_bariyer_yalniz_uc_hazir_ve_eslesme(self):
        k = gm.Koordinasyon(A, "G1")
        hazir_et(k, [1, 2])
        k.eslesme_guncelle(3)
        self.assertIsNone(k.sonraki())                        # üçüncü araç hazır değil
        k.durum_geldi(3, BARIYER, 200)
        self.assertEqual(k.sonraki(), "scan_start")
        k2 = gm.Koordinasyon(A, "G1")
        hazir_et(k2)
        k2.eslesme_guncelle(2)
        self.assertIsNone(k2.sonraki())                       # hazır ama eşleşme eksik: bariyer açılmaz
        k2.eslesme_guncelle(3)
        self.assertEqual(k2.sonraki(), "scan_start")

    def test_hazir_olayi_bir_kez_ve_bilinmeyen_arac(self):
        k = gm.Koordinasyon(A, "G1")
        self.assertEqual(k.durum_geldi(1, BARIYER, 5), [{"olay": "hazir", "arac_kimligi": 1}])
        self.assertEqual(k.durum_geldi(1, BARIYER, 6), [])    # yinelenen hazır bildirimi sayılmaz
        o = k.durum_geldi(9, BARIYER, 7)
        self.assertEqual((o[0]["olay"], o[0]["neden"]), ("yok_sayildi", "bilinmeyen_arac"))
        self.assertNotIn(9, k.hazir)

    def _taramaya_gec(self):
        k = gm.Koordinasyon(A, "G1")
        hazir_et(k)
        k.eslesme_guncelle(3)
        k.scan_start_yapildi(1000, 5)
        return k

    def test_t1_iki_kosul(self):
        k = self._taramaya_gec()
        for a in (1, 2):
            k.bitis_geldi(a, "G1", True, 10, 400, 2000)
        k.sonuclar_guncelle(True)
        self.assertIsNone(k.sonraki())                        # üçüncü bitiş yok
        k.bitis_geldi(3, "G1", True, 10, 400, 2100)
        k.sonuclar_guncelle(False)
        self.assertIsNone(k.sonraki())                        # bütün bitişler var ama sonuçlar tamam değil
        k.sonuclar_guncelle(True)
        self.assertEqual(k.sonraki(), "complete")
        k.complete_yapildi(3000, 9)
        self.assertEqual(k.faz, gm.FAZ_COMPLETE_VERILDI)

    def test_erken_yinelenen_yanlis_kimlikli_olaylar_akisi_degistirmez(self):
        k = gm.Koordinasyon(A, "G1")
        o = k.bitis_geldi(1, "G1", True, 10, 20, 1)           # bariyer açılmadan gelen bitiş
        self.assertEqual(o[0]["neden"], "tarama_fazinda_degil")
        hazir_et(k)
        k.eslesme_guncelle(3)
        k.scan_start_yapildi(1000, 5)
        self.assertEqual(k.bitis_geldi(1, "YANLIS", True, 10, 20, 2)[0]["neden"], "mission_id_uyusmuyor")
        self.assertEqual(k.bitis_geldi(1, "G1", True, 10, 20, 3)[0]["olay"], "tarama_bitisi")
        self.assertEqual(k.bitis_geldi(1, "G1", True, 10, 20, 4)[0]["neden"], "tekrar_bitis")
        self.assertEqual(k.bitis[1], (10, 20, 3))             # ilk bildirim kalır
        self.assertEqual(k.bitis_geldi(7, "G1", True, 10, 20, 5)[0]["neden"], "bilinmeyen_arac")
        self.assertEqual(k.faz, gm.FAZ_TARAMA)
        # TAMAMLANDI COMPLETE'ten önce sayılmaz
        self.assertEqual(k.durum_geldi(1, TAMAM, 6), [])

    def test_yedek_yol_acik_hata(self):
        k = self._taramaya_gec()
        o = k.bitis_geldi(2, "G1", False, 0, 0, 1)
        self.assertEqual((o[0]["olay"], o[0]["neden"]), ("hata", "yedek_yol_desteklenmiyor"))
        self.assertEqual(k.faz, gm.FAZ_HATA)
        k.sonuclar_guncelle(True)
        self.assertIsNone(k.sonraki())                        # hata fazında COMPLETE yok

    def test_kapat_uc_tamamlandi(self):
        k = self._taramaya_gec()
        for a in A:
            k.bitis_geldi(a, "G1", True, 10, 400, 2000)
        k.sonuclar_guncelle(True)
        k.complete_yapildi(3000, 9)
        for a in (1, 2):
            self.assertEqual(k.durum_geldi(a, TAMAM, 3100)[0]["olay"], "tamamlandi")
        self.assertIsNone(k.sonraki())
        k.durum_geldi(3, TAMAM, 3200)
        self.assertEqual(k.sonraki(), "kapat")

    def test_zaman_asimi_complete_yok(self):
        k = self._taramaya_gec()
        k.bitis_geldi(1, "G1", True, 10, 400, 2000)
        k.sonuclar_guncelle(False)
        neden = k.zaman_asimi()
        self.assertIn("tarama bitişi [2, 3]", neden)
        self.assertEqual(k.faz, gm.FAZ_HATA)
        k.sonuclar_guncelle(True)
        self.assertIsNone(k.sonraki())

    def test_zaman_asimi_hazir_fazinda(self):
        k = gm.Koordinasyon(A, "G1")
        hazir_et(k, [1])
        self.assertIn("hazır bildirimi [2, 3]", k.zaman_asimi())


class Izleme(unittest.TestCase):
    def test_degisim_ve_ozet(self):
        z = DurumIzleyici(A, 5, 10)
        o = z.durum_geldi(1, 1, (0, 0), -1, 10 ** 9)
        self.assertEqual(o[0]["olay"], "durum_degisti")
        self.assertEqual(z.durum_geldi(1, 1, (0, 0), -1, 2 * 10 ** 9), [])     # aynı durum: yazılmaz
        self.assertEqual(z.durum_geldi(1, 3, (1, 4), 7, 3 * 10 ** 9)[0]["durum"], "TARAMA")
        self.assertEqual(z.durum_geldi(1, 3, (2, 4), 9, 4 * 10 ** 9)[0]["ilerleme"], [2, 4])
        self.assertIn("özet", DurumIzleyici.satir(z.kontrol(4 * 10 ** 9)[-1]))

    def test_kapanis_ozeti_bayat_uyarisi_uretmez(self):
        z = DurumIzleyici(A, 5, 1)
        z.durum_geldi(1, 5, (4, 4), 9, 1)
        o = z.kontrol(100 * 10 ** 9, yalniz_ozet=True)
        self.assertEqual([x["olay"] for x in o], ["ozet"])        # çok eski son durum olsa da yalnız özet: kapanış bayat uyarısı doğurmaz
        self.assertEqual(z.bayat_sayisi[1], 0)

    def test_bayat_uyarisi_bir_kez_ve_bitisi(self):
        z = DurumIzleyici(A, 5, 100)
        z.durum_geldi(1, 3, (1, 4), 7, 0 + 1)
        z.durum_geldi(2, 3, (1, 4), 7, 0 + 1)
        self.assertEqual([o for o in z.kontrol(4 * 10 ** 9) if o["olay"] == "bayat_uyari"], [])
        u = [o for o in z.kontrol(7 * 10 ** 9) if o["olay"] == "bayat_uyari"]
        self.assertEqual(sorted(o["arac_kimligi"] for o in u), [1, 2])           # araç 3'ten hiç durum gelmedi: ilk durum gelmeden uyarı yok
        self.assertEqual([o for o in z.kontrol(9 * 10 ** 9) if o["olay"] == "bayat_uyari"], [])    # aynı dönem için ikinci uyarı yok
        o = z.durum_geldi(1, 3, (2, 4), 8, 10 * 10 ** 9)
        self.assertEqual(o[0]["olay"], "bayat_bitti")
        self.assertEqual(z.bayat_sayisi[1], 1)


class Kayit(unittest.TestCase):
    def test_gecerli_satirlar_dogrulayicidan_gecer(self):
        klasor = tempfile.mkdtemp()
        yol = os.path.join(klasor, "yer_istasyonu_gorev.jsonl")
        g = GorevKaydi(yol)
        g.yaz("gorev_atandi", arac_kimligi=1, mission_id="G1")
        g.yaz("hazir", sim_ns=5, arac_kimligi=1)
        g.yaz("birlestirme_yok", ayrinti="M3")
        g.yaz("t0", sim_ns=6, mission_id="G1")
        g.yaz("tarama_bitisi", arac_kimligi=1, n_ilk=10, n_son=20, t_s_ns=None, t_b_ns=None)
        g.yaz("son_sonuc")
        g.yaz("t1", sim_ns=9, mission_id="G1", t1_eksi_son_bitis_ns=1000)
        monos = [d["mono_ns"] for d in g.satirlar]
        self.assertEqual(monos, sorted(monos))
        r = subprocess.run([sys.executable, "-I", os.path.join(KOK, "araclar", "sozlesme_dogrula.py"), yol], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_gecersiz_olay_ve_alan(self):
        g = GorevKaydi(None)
        with self.assertRaises(ValueError):
            g.yaz("bariyer_acildi")
        with self.assertRaises(ValueError):
            g.yaz("hazir", arac_kimligi=1, rastgele=1)

    def test_mono_geriye_gitmez(self):
        g = GorevKaydi(None)
        a = g.yaz("hazir", arac_kimligi=1, mono_ns=500)
        b = g.yaz("hazir", arac_kimligi=2, mono_ns=100)
        self.assertGreaterEqual(b["mono_ns"], a["mono_ns"])

    def test_json_satiri_okunur(self):
        yol = os.path.join(tempfile.mkdtemp(), "x.jsonl")
        g = GorevKaydi(yol)
        g.yaz("zaman_asimi", neden="x")
        with open(yol, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read())["olay"], "zaman_asimi")


if __name__ == "__main__":
    unittest.main()
