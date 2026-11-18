#!/usr/bin/env python3
"""Değerlendirme yazılımı (B18, FR-28) birim testleri: sentetik örnekler. ROS 2 gerekmez; numpy ve scipy (kilitli ortam) gerekir.
Çalıştırma: python3 -I araclar/degerlendirme/test/test_eslestirme.py
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

MODUL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # araclar/degerlendirme
BETIK = os.path.join(MODUL, "eslestirme.py")
sys.path.insert(0, MODUL)
import eslestirme as dg  # noqa: E402

C, ESIK = dg.yapilandirma_yukle()
SAHNE = "S-TEST-0001"


def rapor(kimlik, sinif, x=None, y=None):
    """Sözleşmeye uygun tek nihai rapor; x None ise konumsuz rapor."""
    konum = None if x is None else {"x_m": x, "y_m": y}
    tespit = {"arac_kimligi": C.arac_kimlikleri[0], "n": 1, "sim_damga_ns": 1_000_000_000}
    return {"rapor_kimligi": kimlik, "sinif": sinif, "konum": konum, "ilk_konum": copy.deepcopy(konum), "guven": 0.5,
            "tespit_sayisi": 1, "ilk_tespit": tespit, "en_yuksek_guven_tespiti": dict(tespit)}


def nihai(raporlar, sahne=SAHNE):
    return {"surum": 1, "tur": "nihai_rapor", "kosu_kimligi": "kosu_sentetik", "sahne_kimligi": sahne, "mod": C.mimariler[0], "raporlar": raporlar}


def hedef(kimlik, sinif, x, y):
    return {"kimlik": kimlik, "sinif": sinif, "x": x, "y": y}


def liste(hedefler, sahne=SAHNE):
    return {"surum": 1, "tur": "hedef_listesi", "sahne_kimligi": sahne, "bolum": "test", "hedefler": hedefler}


def degerlendir(raporlar, hedefler):
    return dg.degerlendir(C, ESIK, nihai(raporlar), liste(hedefler))


def ciftler(sonuc):
    return {(e["rapor_kimligi"], e["hedef_kimligi"]) for e in sonuc["eslesmeler"]}


class Yapilandirma(unittest.TestCase):
    def test_esik_belgedeki_deger(self):
        self.assertEqual(ESIK, 5.0)   # [belge] FR-28: en fazla 5 m


class AtamaMaliyeti(unittest.TestCase):
    def test_uygun_olmayan_maliyet_belgedeki_sinirdan_buyuk(self):
        # [belge] uygun olmayan çiftin maliyeti 5 × (N + 1)'den büyük sabit
        for n in (0, 1, 30):
            self.assertGreater(dg.uygun_olmayan_maliyet(ESIK, n), 5 * (n + 1))

    def test_sabit_maliyetli_atama_eslesme_sayilmaz(self):
        # tek rapor, tek hedef, uzaklık eşiğin dışında: algoritma sabit maliyetle atar ama eşleşme dönmez
        self.assertEqual(dg.sinif_icinde_ata([(10.0, 0.0)], [(0.0, 0.0)], ESIK, 1), [])

    def test_hedef_sayisi_n_yi_asamaz(self):
        with self.assertRaises(ValueError):
            dg.sinif_icinde_ata([(0.0, 0.0)], [(0.0, 0.0), (20.0, 0.0)], ESIK, 1)


class Eslestirme(unittest.TestCase):
    def test_tam_eslesme(self):
        s = degerlendir([rapor("R1", "insan", 0.5, 0), rapor("R2", "enkaz", 20, 1), rapor("R3", "insan", 40, -2)],
                        [hedef("H1", "insan", 0, 0), hedef("H2", "enkaz", 20, 0), hedef("H3", "insan", 40, 0)])
        self.assertEqual((s["n"], s["tp"], s["fp"], s["fn"]), (3, 3, 0, 0))
        self.assertEqual(s["r_yuzde"], 100.0)
        self.assertEqual(s["precision"], 1.0)
        self.assertEqual(ciftler(s), {("R1", "H1"), ("R2", "H2"), ("R3", "H3")})
        self.assertAlmostEqual({e["rapor_kimligi"]: e["uzaklik_m"] for e in s["eslesmeler"]}["R3"], 2.0)

    def test_fazladan_kopya_fp(self):
        s = degerlendir([rapor("R1", "insan", 0, 1), rapor("R2", "insan", 0, -3)], [hedef("H1", "insan", 0, 0)])
        self.assertEqual((s["tp"], s["fp"], s["fn"]), (1, 1, 0))
        self.assertEqual(ciftler(s), {("R1", "H1")})   # daha yakın olan atanır
        self.assertEqual(s["eslesmeyen_raporlar"], [{"rapor_kimligi": "R2", "sinif": "insan", "neden": "eslesmedi"}])
        self.assertEqual(s["precision"], 0.5)

    def test_konumsuz_rapor_fp(self):
        s = degerlendir([rapor("R1", "insan"), rapor("R2", "insan", 1, 0)], [hedef("H1", "insan", 0, 0)])
        self.assertEqual((s["tp"], s["fp"], s["fn"], s["konumsuz_rapor"]), (1, 1, 0, 1))
        self.assertIn({"rapor_kimligi": "R1", "sinif": "insan", "neden": "konumsuz"}, s["eslesmeyen_raporlar"])

    def test_yalniz_konumsuz_rapor_hedefle_eslesmez(self):
        s = degerlendir([rapor("R1", "insan")], [hedef("H1", "insan", 0, 0)])
        self.assertEqual((s["tp"], s["fp"], s["fn"]), (0, 1, 1))
        self.assertEqual(s["precision"], 0.0)

    def test_yanlis_sinif_eslesmez(self):
        s = degerlendir([rapor("R1", "enkaz", 0, 0)], [hedef("H1", "insan", 0, 0)])
        self.assertEqual((s["tp"], s["fp"], s["fn"]), (0, 1, 1))
        self.assertEqual(s["r_yuzde"], 0.0)

    def test_esik_siniri(self):
        tam = degerlendir([rapor("R1", "insan", 3, 4)], [hedef("H1", "insan", 0, 0)])   # tam 5,0 m: dahil
        self.assertEqual(tam["tp"], 1)
        self.assertEqual(tam["eslesmeler"][0]["uzaklik_m"], 5.0)
        disari = degerlendir([rapor("R1", "insan", 5.01, 0)], [hedef("H1", "insan", 0, 0)])
        self.assertEqual((disari["tp"], disari["fp"], disari["fn"]), (0, 1, 1))

    def test_acgozlu_secim_yanilir_macar_yanilmaz(self):
        # En yakın çifti önce alan seçim R1–H1 (1 m) alır, R2 boşta kalır (H2'ye 7,5 m) → TP 1.
        # En çok TP'li atama: R2–H1 (2 m), R1–H2 (4,5 m) → TP 2.
        s = degerlendir([rapor("R1", "insan", 1, 0), rapor("R2", "insan", -2, 0)], [hedef("H1", "insan", 0, 0), hedef("H2", "insan", 5.5, 0)])
        self.assertEqual((s["tp"], s["fp"], s["fn"]), (2, 0, 0))
        self.assertEqual(ciftler(s), {("R2", "H1"), ("R1", "H2")})

    def test_esit_tp_icinde_toplam_uzaklik_en_kucuk(self):
        # İki atama da TP 2: R1–H1 + R2–H2 (1 + 1 m) ile R1–H2 + R2–H1 (3 + 3 m); ilki seçilir.
        s = degerlendir([rapor("R1", "insan", 1, 0), rapor("R2", "insan", 3, 0)], [hedef("H1", "insan", 0, 0), hedef("H2", "insan", 4, 0)])
        self.assertEqual(ciftler(s), {("R1", "H1"), ("R2", "H2")})

    def test_bos_rapor_listesi_precision_tanimsiz(self):
        s = degerlendir([], [hedef("H1", "insan", 0, 0), hedef("H2", "enkaz", 20, 0)])
        self.assertEqual((s["tp"], s["fp"], s["fn"]), (0, 0, 2))
        self.assertIsNone(s["precision"])
        self.assertEqual(s["r_yuzde"], 0.0)
        self.assertEqual(s["eslesmeyen_hedefler"], [{"hedef_kimligi": "H1", "sinif": "insan"}, {"hedef_kimligi": "H2", "sinif": "enkaz"}])

    def test_bos_hedef_listesi_r_tanimsiz(self):
        s = degerlendir([rapor("R1", "insan", 0, 0)], [])
        self.assertEqual((s["n"], s["tp"], s["fp"]), (0, 0, 1))
        self.assertIsNone(s["r_yuzde"])

    def test_sinif_bazli_sayilar(self):
        s = degerlendir([rapor("R1", "insan", 0, 0), rapor("R2", "insan", 50, 50), rapor("R3", "enkaz", 20, 0), rapor("R4", "enkaz")],
                        [hedef("H1", "insan", 0, 0), hedef("H2", "insan", 30, 0), hedef("H3", "enkaz", 20, 0)])
        self.assertEqual((s["tp"], s["fp"], s["fn"]), (2, 2, 1))
        i, e = s["sinif_bazli"]["insan"], s["sinif_bazli"]["enkaz"]
        self.assertEqual((i["n"], i["tp"], i["fp"], i["fn"]), (2, 1, 1, 1))
        self.assertEqual(i["r_yuzde"], 50.0)
        self.assertEqual((e["n"], e["tp"], e["fp"], e["fn"]), (1, 1, 1, 0))
        self.assertEqual(e["precision"], 0.5)
        for k in ("n", "tp", "fp", "fn"):   # sınıf toplamı = genel
            self.assertEqual(i[k] + e[k], s[k])

    def test_girdi_sirasi_sonucu_degistirmez(self):
        r = [rapor("R1", "insan", 1, 0), rapor("R2", "insan", 3, 0), rapor("R3", "enkaz", 2, 2), rapor("R4", "insan")]
        h = [hedef("H1", "insan", 0, 0), hedef("H2", "insan", 4, 0), hedef("H3", "enkaz", 0, 0)]
        self.assertEqual(degerlendir(r, h), degerlendir(list(reversed(r)), list(reversed(h))))

    def test_hedef_kimligi_atamayi_etkilemez(self):
        # Kimlikler yer değiştirince eşleşen konumlar aynı kalır (kimlik ölçüt değil, yalnız etiket).
        r = [rapor("R1", "insan", 1, 0), rapor("R2", "insan", -2, 0)]
        a = degerlendir(r, [hedef("H1", "insan", 0, 0), hedef("H2", "insan", 5.5, 0)])
        b = degerlendir(r, [hedef("H2", "insan", 0, 0), hedef("H1", "insan", 5.5, 0)])
        konum = {"H1": (0, 0), "H2": (5.5, 0)}
        ters = {"H1": (5.5, 0), "H2": (0, 0)}
        self.assertEqual({(e["rapor_kimligi"], konum[e["hedef_kimligi"]]) for e in a["eslesmeler"]},
                         {(e["rapor_kimligi"], ters[e["hedef_kimligi"]]) for e in b["eslesmeler"]})

    def test_tam_test_sahnesi(self):
        # 15 insan + 15 enkaz, merkezler arası ≥ 10 m; 12 insan + 13 enkaz eşik içinde, 1 kopya, 2 konumsuz, 1 eşik dışı.
        hed = [hedef(f"H{i:02d}", "insan" if i < 15 else "enkaz", -140 + 10 * i, 0) for i in range(30)]
        rap = [rapor(f"R{i:02d}", t["sinif"], t["x"] + 1.5, t["y"] - 2) for i, t in enumerate(hed) if i not in (12, 13, 14, 28, 29)]
        rap += [rapor("K01", "insan", -140.5, 0.5), rapor("K02", "enkaz"), rapor("K03", "insan"), rapor("K04", "enkaz", 150 - 10 - 7, 0)]
        s = degerlendir(rap, hed)
        self.assertEqual((s["n"], s["tp"], s["fp"], s["fn"]), (30, 25, 4, 5))
        self.assertAlmostEqual(s["r_yuzde"], 100 * 25 / 30)
        self.assertAlmostEqual(s["precision"], 25 / 29)
        self.assertEqual(s["konumsuz_rapor"], 2)


class GirdiDenetimi(unittest.TestCase):
    def test_sahne_uyusmazligi(self):
        with self.assertRaisesRegex(dg.GirdiHatasi, "sahne uyuşmuyor"):
            dg.degerlendir(C, ESIK, nihai([], sahne="S-TEST-0002"), liste([]))

    def test_sozlesme_disi_rapor(self):
        bozuk = rapor("R1", "kedi", 0, 0)
        with self.assertRaisesRegex(dg.GirdiHatasi, "nihai_rapor: raporlar\\[0\\].sinif"):
            dg.degerlendir(C, ESIK, nihai([bozuk]), liste([]))

    def test_sozlesme_disi_hedef_listesi(self):
        with self.assertRaisesRegex(dg.GirdiHatasi, "hedef_listesi: "):
            dg.degerlendir(C, ESIK, nihai([]), liste([hedef("H1", "insan", "sifir", 0)]))

    def test_esik_anahtari_eksik(self):
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "deney.env")
            with open(os.path.join(dg.KOK, "config", "deney.env"), encoding="utf-8") as f:
                satirlar = [s for s in f if not s.startswith(dg.ESIK_ANAHTARI + "=")]
            with open(yol, "w", encoding="utf-8") as f:
                f.writelines(satirlar)
            with self.assertRaisesRegex(ValueError, dg.ESIK_ANAHTARI):
                dg.yapilandirma_yukle(yol)


class KomutSatiri(unittest.TestCase):
    def calistir(self, rapor_d, liste_d):
        with tempfile.TemporaryDirectory() as d:
            yollar = []
            for ad, v in (("rapor.json", rapor_d), ("liste.json", liste_d)):
                yollar.append(os.path.join(d, ad))
                with open(yollar[-1], "w", encoding="utf-8") as f:
                    json.dump(v, f)
            return subprocess.run([sys.executable, "-I", BETIK, *yollar], capture_output=True, text=True)

    def test_basarili(self):
        p = self.calistir(nihai([rapor("R1", "insan", 0, 0)]), liste([hedef("H1", "insan", 0, 0)]))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["tp"], 1)

    def test_girdi_gecersiz_cikis_1(self):
        p = self.calistir(nihai([], sahne="S-BASKA"), liste([]))
        self.assertEqual(p.returncode, 1)
        self.assertIn("sahne uyuşmuyor", p.stderr)

    def test_kullanim_hatasi_cikis_2(self):
        p = subprocess.run([sys.executable, "-I", BETIK], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
