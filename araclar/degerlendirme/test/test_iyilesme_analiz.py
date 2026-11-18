#!/usr/bin/env python3
"""İyileşme analiz betiği (E2a; FR-29) birim testleri: elle hesaplanmış sentetik veri, sabit çıktı biçimi.
Çalıştırma: python3 -I araclar/degerlendirme/test/test_iyilesme_analiz.py

Sentetik veri (T s, D MB, B = 8D/T Mbit/s; L ortanca/p95 s). I_X = 100 × (merkez − uç) / merkez; L farkı = merkez − uç.
  S-A uçta    T 200, D 10 (B 0,4),  L 0,10/0,30   merkezi T 250, D 40 (B 1,28), L 0,50/1,20  → I_D 75,  I_B 68,75, I_T 20,  L farkı 0,40/0,90
  S-B uçta    T 300, D 30 (B 0,8),  L 0,20/0,60   merkezi T 240, D 20 (B 2/3),  L 0,15/0,50  → I_D −50, I_B −20,   I_T −25, L farkı −0,05/−0,10
  S-C uçta    T 100, D 5  (B 0,4),  L 0,10/0,20   merkezi T 100, D 0  (B 0),    L örnek yok  → I_D, I_B tanımsız (payda 0), I_T 0, L farkı tanımsız
  S-D uçta    (merkezi özeti yok → çift kurulamaz, dışlanır)
  S-E uçta    tamamlanamadı, merkezi tamamlandı (→ çift dışlanır [FR-27])
Üç tamamlanan çift (S-A, S-B, S-C): I_T için ortalama −5/3, medyan 0 (ortalama ile medyan ayrılır).
"""
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

MODUL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # araclar/degerlendirme
BETIK = os.path.join(MODUL, "iyilesme_analiz.py")
sys.path.insert(0, MODUL)
import iyilesme_analiz as ia  # noqa: E402
import tablo  # noqa: E402

C = ia.yapilandirma_yukle()
OLCUM_ORNEK = os.path.join(ia.KOK, "config", "ornek", "kosu_olcum_ornek.json")
T0_NS = 1_000_000_000_000


def olcum(sahne, mod, t_s=100.0, d_mb=10.0, l=(0.1, 0.2), tamamlandi=True):
    """Sözleşmeye (§11.2) uyan sentetik koşu ölçüm özeti. `l` = (ortanca, p95) ya da None (örnek yok)."""
    with open(OLCUM_ORNEK, encoding="utf-8") as f:
        o = json.load(f)
    if l is None:
        kare = {"beklenen": 100, "pozitif": 0, "negatif": 0, "kare_alinamadi": 96, "islem_hatasi": 4, "gec_geldi": 0}
        o["l"] = {"ornek_sayisi": 0, "ortanca_s": None, "p95_s": None}
    else:
        kare = {"beklenen": 100, "pozitif": 30, "negatif": 60, "kare_alinamadi": 6, "islem_hatasi": 4, "gec_geldi": 2}
        o["l"] = {"ornek_sayisi": 90, "ortanca_s": l[0], "p95_s": l[1]}
    o.update({"kosu_kimligi": f"kosu_{sahne}_{mod}", "sahne_kimligi": sahne, "mod": mod, "kare_sayilari": kare,
              "sonuc_orani": (kare["pozitif"] + kare["negatif"]) / kare["beklenen"], "kare_alinamadi_orani": kare["kare_alinamadi"] / kare["beklenen"],
              "t0_mono_ns": T0_NS, "t1_mono_ns": T0_NS + round(t_s * 1e9), "t_s": t_s, "d_mb": d_mb, "b_mbit_s": 8 * d_mb / t_s})
    if not tamamlandi:
        o.update({"tamamlandi": False, "tamamlanamadi": {"neden": "zaman_asimi", "gozlenen_sure_s": 600.0, "kismi_trafik_mb": 5.0},
                  "t1_mono_ns": None, "t_s": None, "d_mb": None, "complete_bayt": None, "b_mbit_s": None})
    return o


def senaryo():
    return [
        olcum("S-A", "ucta", 200.0, 10.0, (0.10, 0.30)), olcum("S-A", "merkezi", 250.0, 40.0, (0.50, 1.20)),
        olcum("S-B", "ucta", 300.0, 30.0, (0.20, 0.60)), olcum("S-B", "merkezi", 240.0, 20.0, (0.15, 0.50)),
        olcum("S-C", "ucta", 100.0, 5.0, (0.10, 0.20)), olcum("S-C", "merkezi", 100.0, 0.0, None),
        olcum("S-D", "ucta"),
        olcum("S-E", "ucta", tamamlandi=False), olcum("S-E", "merkezi"),
    ]


def satir_bul(satirlar, anahtar, deger):
    return next(s for s in satirlar if s[anahtar] == deger)


class SentetikVeri(unittest.TestCase):
    def test_sentetik_girdi_sozlesmeye_uyar(self):
        import sozlesme_dogrula as sd
        for o in senaryo():
            self.assertEqual(sd.dogrula_kosu_olcum(C, o), [], o["kosu_kimligi"])


class Hesap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = ia.analiz(C, senaryo())

    def test_yuzde_iyilesme_ve_isaret(self):
        s = satir_bul(self.t["iyilesme_sahne"][1], "sahne_kimligi", "S-A")
        self.assertAlmostEqual(s["d_iyilesme_yuzde"], 75.0)
        self.assertAlmostEqual(s["b_iyilesme_yuzde"], 68.75)
        self.assertAlmostEqual(s["t_iyilesme_yuzde"], 20.0)
        b = satir_bul(self.t["iyilesme_sahne"][1], "sahne_kimligi", "S-B")   # merkezi lehine → negatif
        self.assertAlmostEqual(b["d_iyilesme_yuzde"], -50.0)
        self.assertAlmostEqual(b["b_iyilesme_yuzde"], -20.0)
        self.assertAlmostEqual(b["t_iyilesme_yuzde"], -25.0)

    def test_l_farki_merkez_eksi_uc(self):
        a = satir_bul(self.t["iyilesme_sahne"][1], "sahne_kimligi", "S-A")
        self.assertAlmostEqual(a["l_ortanca_fark"], 0.40)
        self.assertAlmostEqual(a["l_p95_fark"], 0.90)
        b = satir_bul(self.t["iyilesme_sahne"][1], "sahne_kimligi", "S-B")
        self.assertAlmostEqual(b["l_ortanca_fark"], -0.05)
        self.assertAlmostEqual(b["l_p95_fark"], -0.10)
        self.assertNotIn("l_ortanca_iyilesme_yuzde", self.t["iyilesme_sahne"][0])   # L için yüzde iyileşme hesaplanmaz [belge]

    def test_sifir_payda_ve_ornek_yok_tanimsiz(self):
        c = satir_bul(self.t["iyilesme_sahne"][1], "sahne_kimligi", "S-C")
        self.assertIsNone(c["d_iyilesme_yuzde"])
        self.assertIsNone(c["b_iyilesme_yuzde"])
        self.assertEqual(c["t_iyilesme_yuzde"], 0.0)
        self.assertIsNone(c["l_ortanca_fark"])
        self.assertIsNone(c["l_p95_fark"])
        self.assertIsNone(c["l_ortanca_merkezi"])

    def test_ciftler_ve_dislanan(self):
        self.assertEqual([s["sahne_kimligi"] for s in self.t["iyilesme_sahne"][1]], ["S-A", "S-B", "S-C"])
        self.assertEqual(self.t["iyilesme_dislanan"][1], [{"sahne_kimligi": "S-D", "neden": "merkezi: kosu_olcum_yok"},
                                                         {"sahne_kimligi": "S-E", "neden": "ucta: tamamlanamadi"}])
        kosu = self.t["iyilesme_kosu"][1]
        self.assertEqual(len(kosu), 9)
        self.assertEqual([(s["sahne_kimligi"], s["mod"]) for s in kosu][:2], [("S-A", "ucta"), ("S-A", "merkezi")])
        e = satir_bul([s for s in kosu if s["mod"] == "ucta"], "sahne_kimligi", "S-E")
        self.assertFalse(e["tamamlandi"])
        self.assertFalse(e["ciftte"])
        self.assertIsNone(e["t_s"])
        self.assertTrue(satir_bul(kosu, "kosu_kimligi", "kosu_S-A_ucta")["ciftte"])

    def test_kosu_tablosu_kare_sayilari(self):
        k = satir_bul(self.t["iyilesme_kosu"][1], "kosu_kimligi", "kosu_S-C_merkezi")
        self.assertEqual((k["beklenen"], k["pozitif"], k["negatif"], k["kare_alinamadi"], k["islem_hatasi"]), (100, 0, 0, 96, 4))
        self.assertEqual(k["l_ornek_sayisi"], 0)
        self.assertAlmostEqual(k["sonuc_orani"], 0.0)
        self.assertAlmostEqual(k["kare_alinamadi_orani"], 0.96)

    def test_ozet(self):
        oz = {s["olcut"]: s for s in self.t["iyilesme_ozet"][1]}
        self.assertEqual([s["olcut"] for s in self.t["iyilesme_ozet"][1]], self.t["iyilesme_sahne"][0][1:])
        t = oz["t_iyilesme_yuzde"]
        self.assertEqual((t["cift_sayisi"], t["tanimli_sayisi"], t["tanimsiz_sayisi"]), (3, 3, 0))
        self.assertAlmostEqual(t["ortalama"], -5 / 3)
        self.assertAlmostEqual(t["medyan"], 0.0)
        self.assertAlmostEqual(t["en_kucuk"], -25.0)
        self.assertAlmostEqual(t["en_buyuk"], 20.0)
        d = oz["d_iyilesme_yuzde"]
        self.assertEqual((d["tanimli_sayisi"], d["tanimsiz_sayisi"]), (2, 1))
        self.assertAlmostEqual(d["ortalama"], 12.5)
        lo = oz["l_ortanca_fark"]
        self.assertEqual(lo["tanimli_sayisi"], 2)
        self.assertAlmostEqual(lo["ortalama"], 0.175)

    def test_dosya_sirasi_sonucu_degistirmez(self):
        karisik = senaryo()
        random.Random(7).shuffle(karisik)
        t2 = ia.analiz(C, karisik)
        for ad, (sutunlar, satirlar) in self.t.items():
            self.assertEqual(tablo.csv_metni(sutunlar, satirlar), tablo.csv_metni(*t2[ad]), ad)

    def test_bos_cift(self):
        t = ia.analiz(C, [olcum("S-D", "ucta")])
        self.assertEqual(t["iyilesme_sahne"][1], [])
        oz = t["iyilesme_ozet"][1][0]
        self.assertEqual((oz["cift_sayisi"], oz["ortalama"], oz["medyan"]), (0, None, None))


class GirdiHatalari(unittest.TestCase):
    def test_yinelenen_kosu(self):
        with self.assertRaisesRegex(ia.GirdiHatasi, "yinelenen"):
            ia.analiz(C, [olcum("S-A", "ucta"), olcum("S-A", "ucta")])

    def test_sozlesmeye_uymayan_ozet(self):
        o = olcum("S-A", "ucta")
        o["b_mbit_s"] = 99.0   # B = 8D/T ile tutarsız
        with self.assertRaises(ia.GirdiHatasi):
            ia.analiz(C, [o])

    def test_dogrudan_islevler(self):
        self.assertIsNone(ia.yuzde_iyilesme(0.0, 1.0))
        self.assertIsNone(ia.yuzde_iyilesme(None, 1.0))
        self.assertAlmostEqual(ia.yuzde_iyilesme(4.0, 1.0), 75.0)
        self.assertIsNone(ia.fark(None, 0.1))
        self.assertAlmostEqual(ia.fark(0.5, 0.1), 0.4)


class Bicim(unittest.TestCase):
    """Sütun adları ve sırası sabittir (sözleşmeler §11.4); değişirse E3a, E4a ve M8b'ye bildirilir."""

    def test_sutunlar_sabit(self):
        t = ia.analiz(C, senaryo())
        self.assertEqual(t["iyilesme_kosu"][0], [
            "sahne_kimligi", "mod", "kosu_kimligi", "tamamlandi", "ciftte", "t_s", "d_mb", "b_mbit_s", "l_ornek_sayisi", "l_ortanca_s",
            "l_p95_s", "beklenen", "pozitif", "negatif", "kare_alinamadi", "islem_hatasi", "gec_geldi", "sonuc_orani", "kare_alinamadi_orani"])
        self.assertEqual(t["iyilesme_sahne"][0], [
            "sahne_kimligi", "d_ucta", "d_merkezi", "d_iyilesme_yuzde", "b_ucta", "b_merkezi", "b_iyilesme_yuzde", "t_ucta", "t_merkezi",
            "t_iyilesme_yuzde", "l_ortanca_ucta", "l_ortanca_merkezi", "l_ortanca_fark", "l_p95_ucta", "l_p95_merkezi", "l_p95_fark"])
        self.assertEqual(t["iyilesme_ozet"][0], ["olcut", "cift_sayisi", "tanimli_sayisi", "tanimsiz_sayisi", "ortalama", "medyan", "en_kucuk",
                                                 "en_buyuk"])
        self.assertEqual(t["iyilesme_dislanan"][0], ["sahne_kimligi", "neden"])

    def test_csv_ve_md_satiri(self):
        t = ia.analiz(C, senaryo())
        sutunlar, satirlar = t["iyilesme_sahne"]
        csv_satirlari = tablo.csv_metni(sutunlar, satirlar).splitlines()
        self.assertEqual(csv_satirlari[3], "S-C,5.000000,0.000000,,0.400000,0.000000,,100.000000,100.000000,0.000000,0.100000,,,0.200000,,")
        md = tablo.md_metni("iyilesme_sahne", sutunlar, satirlar).splitlines()
        self.assertEqual(md[0], "# iyilesme_sahne")
        self.assertEqual(md[4], "| S-A | 10,00 | 40,00 | 75,00 | 0,40 | 1,28 | 68,75 | 200,00 | 250,00 | 20,00 | 0,10 | 0,50 | 0,40 | 0,30 | 1,20 | 0,90 |")
        self.assertIn("| tanımsız |", md[6])
        kosu = tablo.csv_metni(*t["iyilesme_kosu"]).splitlines()
        self.assertTrue(kosu[1].startswith("S-A,ucta,kosu_S-A_ucta,1,1,200.000000,10.000000,0.400000,90,"))


class KomutSatiri(unittest.TestCase):
    def calistir(self, *argumanlar):
        return subprocess.run([sys.executable, "-I", BETIK, *argumanlar], capture_output=True, text=True)

    def test_basarili_ve_dosyalar(self):
        with tempfile.TemporaryDirectory() as d:
            yollar = []
            for i, o in enumerate(senaryo()):
                yollar.append(os.path.join(d, f"o{i}.json"))
                with open(yollar[-1], "w", encoding="utf-8") as f:
                    json.dump(o, f)
            cikti = os.path.join(d, "cikti")
            r = self.calistir("--cikti", cikti, *yollar)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("3 tamamlanan sahne çifti, 2 dışlanan sahne", r.stdout)
            self.assertEqual(sorted(os.listdir(cikti)), sorted(f"{ad}.{u}" for ad in ("iyilesme_kosu", "iyilesme_sahne", "iyilesme_ozet",
                                                                                      "iyilesme_dislanan") for u in ("csv", "md")))

    def test_girdi_hatasi_1(self):
        with tempfile.TemporaryDirectory() as d:
            y = os.path.join(d, "o.json")
            with open(y, "w", encoding="utf-8") as f:
                json.dump(olcum("S-A", "ucta"), f)
            r = self.calistir("--cikti", os.path.join(d, "c"), y, y)
            self.assertEqual(r.returncode, 1)
            self.assertIn("yinelenen", r.stderr)

    def test_kullanim_hatasi_2(self):
        self.assertEqual(self.calistir().returncode, 2)
        self.assertEqual(self.calistir("--cikti", "x", "--bilinmeyen").returncode, 2)
        self.assertEqual(self.calistir("--cikti", tempfile.gettempdir(), "/yok/dosya.json").returncode, 2)


if __name__ == "__main__":
    unittest.main()
