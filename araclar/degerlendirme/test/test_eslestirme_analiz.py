#!/usr/bin/env python3
"""Eşleştirme analiz betiği (E1a; FR-24, FR-28) birim testleri: elle hesaplanmış sentetik veri, sabit çıktı biçimi.
Çalıştırma: python3 -I araclar/degerlendirme/test/test_eslestirme_analiz.py

Sentetik veri: her sahnede aynı 4 hedef (N = 4): H1 insan (0, 0), H2 insan (50, 0), H3 enkaz (0, 50), H4 enkaz (50, 50).
  S-A uçta    4 rapor, hepsi hedefin üstünde                    → TP 4, FP 0, R 100, precision 1;     insan R 100, enkaz R 100
  S-A merkezi H1, H3 + 1 konumsuz insan                         → TP 2, FP 1, R 50,  precision 2/3;   insan R 50,  enkaz R 50
  S-B uçta    hiç rapor yok                                     → TP 0, FP 0, R 0,   precision tanımsız
  S-B merkezi H2 + H2'nin kopyası + uzak enkaz (100, 100)       → TP 1, FP 2, R 25,  precision 1/3;   insan R 50,  enkaz R 0
  S-C uçta    H1 (merkezi koşusu yok → çift kurulamaz, dışlanır)
  S-D uçta    H1                                                → TP 1, FP 0, R 25,  precision 1;     insan R 50,  enkaz R 0
  S-D merkezi hiç rapor yok                                     → TP 0, FP 0, R 0,   precision tanımsız
Üç tamamlanan çift (S-A, S-B, S-D): medyan ortalamadan ayrılır (iki değerde ikisi hep aynıdır).
"""
import copy
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

MODUL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # araclar/degerlendirme
BETIK = os.path.join(MODUL, "eslestirme_analiz.py")
sys.path.insert(0, MODUL)
import eslestirme_analiz as ea  # noqa: E402
import eslestirme as es  # noqa: E402

C, ESIK = es.yapilandirma_yukle()
OLCUM_ORNEK = os.path.join(es.KOK, "config", "ornek", "kosu_olcum_ornek.json")
HEDEFLER = [("H1", "insan", 0.0, 0.0), ("H2", "insan", 50.0, 0.0), ("H3", "enkaz", 0.0, 50.0), ("H4", "enkaz", 50.0, 50.0)]


def hedef_listesi(sahne):
    return {"surum": 1, "tur": "hedef_listesi", "sahne_kimligi": sahne, "bolum": "test",
            "hedefler": [{"kimlik": k, "sinif": s, "x": x, "y": y} for k, s, x, y in HEDEFLER]}


def rapor(kimlik, sinif, x=None, y=None):
    konum = None if x is None else {"x_m": x, "y_m": y}
    tespit = {"arac_kimligi": C.arac_kimlikleri[0], "n": 1, "sim_damga_ns": 1_000_000_000}
    return {"rapor_kimligi": kimlik, "sinif": sinif, "konum": konum, "ilk_konum": copy.deepcopy(konum), "guven": 0.5,
            "tespit_sayisi": 1, "ilk_tespit": tespit, "en_yuksek_guven_tespiti": dict(tespit)}


def nihai(sahne, mod, raporlar):
    return {"surum": 1, "tur": "nihai_rapor", "kosu_kimligi": f"kosu_{sahne}_{mod}", "sahne_kimligi": sahne, "mod": mod, "raporlar": raporlar}


def olcum(sahne, mod, tamamlandi=True, kosu_kimligi=None):
    with open(OLCUM_ORNEK, encoding="utf-8") as f:
        o = json.load(f)
    o.update({"kosu_kimligi": kosu_kimligi or f"kosu_{sahne}_{mod}", "sahne_kimligi": sahne, "mod": mod})
    if not tamamlandi:
        o.update({"tamamlandi": False, "tamamlanamadi": {"neden": "zaman_asimi", "gozlenen_sure_s": 600.0, "kismi_trafik_mb": 5.0},
                  "t1_mono_ns": None, "t_s": None, "d_mb": None, "complete_bayt": None, "b_mbit_s": None})
    return o


def veri():
    raporlar = [
        nihai("S-A", "ucta", [rapor("R1", "insan", 0, 0), rapor("R2", "insan", 50, 0), rapor("R3", "enkaz", 0, 50), rapor("R4", "enkaz", 50, 50)]),
        nihai("S-A", "merkezi", [rapor("R1", "insan", 1, 0), rapor("R2", "enkaz", 0, 51), rapor("R3", "insan")]),
        nihai("S-B", "ucta", []),
        nihai("S-B", "merkezi", [rapor("R1", "insan", 50, 1), rapor("R2", "insan", 51, 0), rapor("R3", "enkaz", 100, 100)]),
        nihai("S-C", "ucta", [rapor("R1", "insan", 0, 0)]),
        nihai("S-D", "ucta", [rapor("R1", "insan", 0.5, 0.5)]),
        nihai("S-D", "merkezi", []),
    ]
    return raporlar, [hedef_listesi(s) for s in ("S-A", "S-B", "S-C", "S-D")]


def analiz(olcumler=None, raporlar=None, listeler=None):
    r, hl = veri()
    return ea.analiz(C, ESIK, r if raporlar is None else raporlar, hl if listeler is None else listeler, olcumler)


def tum_olcumler():
    return [olcum(s, m) for s, m in (("S-A", "ucta"), ("S-A", "merkezi"), ("S-B", "ucta"), ("S-B", "merkezi"), ("S-C", "ucta"), ("S-D", "ucta"), ("S-D", "merkezi"))]


SAHNE_CSV = """\
sahne_kimligi,r_ucta,r_merkezi,r_fark,insan_r_ucta,insan_r_merkezi,insan_r_fark,enkaz_r_ucta,enkaz_r_merkezi,enkaz_r_fark,fp_ucta,fp_merkezi,precision_ucta,precision_merkezi
S-A,100.000000,50.000000,50.000000,100.000000,50.000000,50.000000,100.000000,50.000000,50.000000,0,1,1.000000,0.666667
S-B,0.000000,25.000000,-25.000000,0.000000,50.000000,-50.000000,0.000000,0.000000,0.000000,0,2,,0.333333
S-D,25.000000,0.000000,25.000000,50.000000,0.000000,50.000000,0.000000,0.000000,0.000000,0,0,1.000000,
"""

OZET_CSV = """\
olcut,cift_sayisi,tanimli_sayisi,tanimsiz_sayisi,ortalama,medyan,en_kucuk,en_buyuk
r_ucta,3,3,0,41.666667,25.000000,0.000000,100.000000
r_merkezi,3,3,0,25.000000,25.000000,0.000000,50.000000
r_fark,3,3,0,16.666667,25.000000,-25.000000,50.000000
insan_r_ucta,3,3,0,50.000000,50.000000,0.000000,100.000000
insan_r_merkezi,3,3,0,33.333333,50.000000,0.000000,50.000000
insan_r_fark,3,3,0,16.666667,50.000000,-50.000000,50.000000
enkaz_r_ucta,3,3,0,33.333333,0.000000,0.000000,100.000000
enkaz_r_merkezi,3,3,0,16.666667,0.000000,0.000000,50.000000
enkaz_r_fark,3,3,0,16.666667,0.000000,0.000000,50.000000
fp_ucta,3,3,0,0.000000,0.000000,0.000000,0.000000
fp_merkezi,3,3,0,1.000000,1.000000,0.000000,2.000000
precision_ucta,3,2,1,1.000000,1.000000,1.000000,1.000000
precision_merkezi,3,2,1,0.500000,0.500000,0.333333,0.666667
"""


class SabitBicim(unittest.TestCase):
    """Elle hesaplanmış beklenen çıktı, hücre hücre (biçim sabit)."""

    def test_sahne_tablosu(self):
        self.assertEqual(ea.csv_metni(*analiz()["eslestirme_sahne"]), SAHNE_CSV)

    def test_ozet_tablosu(self):
        self.assertEqual(ea.csv_metni(*analiz()["eslestirme_ozet"]), OZET_CSV)

    def test_dislanan_tablosu(self):
        self.assertEqual(ea.csv_metni(*analiz()["eslestirme_dislanan"]), "sahne_kimligi,neden\nS-C,merkezi: nihai_rapor_yok\n")

    def test_kosu_tablosu(self):
        sutunlar, satirlar = analiz()["eslestirme_kosu"]
        self.assertEqual(sutunlar[:12], ["sahne_kimligi", "mod", "kosu_kimligi", "tamamlandi", "ciftte", "n", "tp", "fp", "fn", "r_yuzde", "precision",
                                         "konumsuz_rapor"])
        self.assertEqual(sutunlar[12:], [f"{s}_{m}" for s in ("insan", "enkaz") for m in ("n", "tp", "fp", "fn", "r_yuzde", "precision")])
        self.assertEqual([(s["sahne_kimligi"], s["mod"], s["ciftte"]) for s in satirlar],
                         [("S-A", "ucta", True), ("S-A", "merkezi", True), ("S-B", "ucta", True), ("S-B", "merkezi", True), ("S-C", "ucta", False),
                          ("S-D", "ucta", True), ("S-D", "merkezi", True)])
        am = satirlar[1]
        self.assertEqual((am["n"], am["tp"], am["fp"], am["fn"], am["konumsuz_rapor"]), (4, 2, 1, 2, 1))
        self.assertAlmostEqual(am["precision"], 2 / 3)
        self.assertEqual((am["insan_tp"], am["insan_fp"], am["insan_fn"], am["insan_r_yuzde"]), (1, 1, 1, 50.0))
        bu = satirlar[2]   # hiç rapor yok: R = 0, FP = 0, precision tanımsız [belge]
        self.assertEqual((bu["r_yuzde"], bu["fp"], bu["precision"]), (0.0, 0, None))
        bm = satirlar[3]
        self.assertEqual((bm["tp"], bm["fp"], bm["fn"], bm["r_yuzde"], bm["enkaz_fp"], bm["enkaz_r_yuzde"]), (1, 2, 3, 25.0, 1, 0.0))

    def test_markdown_ayni_veriden(self):
        sutunlar, satirlar = analiz()["eslestirme_sahne"]
        md = ea.md_metni("eslestirme_sahne", sutunlar, satirlar).splitlines()
        self.assertEqual(md[0], "# eslestirme_sahne")
        self.assertEqual(md[2], "| " + " | ".join(sutunlar) + " |")
        self.assertEqual(md[4], "| S-A | 100,00 | 50,00 | 50,00 | 100,00 | 50,00 | 50,00 | 100,00 | 50,00 | 50,00 | 0 | 1 | 1,00 | 0,67 |")
        self.assertEqual(md[5], "| S-B | 0,00 | 25,00 | -25,00 | 0,00 | 50,00 | -50,00 | 0,00 | 0,00 | 0,00 | 0 | 2 | tanımsız | 0,33 |")


class Degerler(unittest.TestCase):
    def test_bicimleyiciler(self):
        self.assertEqual([ea.csv_deger(v) for v in (None, True, False, 3, 2 / 3, -1e-9, "a")], ["", "1", "0", "3", "0.666667", "0.000000", "a"])
        self.assertEqual([ea.md_deger(v) for v in (None, True, False, 3, 2 / 3, -1e-9, "a|b")], ["tanımsız", "evet", "hayır", "3", "0,67", "0,00", "a\\|b"])

    def test_girdi_sirasi_sonucu_degistirmez(self):
        r, hl = veri()
        karisik_r, karisik_hl = r[:], hl[:]
        random.Random(7).shuffle(karisik_r)
        random.Random(7).shuffle(karisik_hl)
        self.assertEqual(analiz(), ea.analiz(C, ESIK, karisik_r, karisik_hl))

    def test_cift_yoksa_ozet_tanimsiz(self):
        r, hl = veri()
        t = ea.analiz(C, ESIK, [r[0]], hl)
        self.assertEqual(t["eslestirme_sahne"][1], [])
        for satir in t["eslestirme_ozet"][1]:
            self.assertEqual((satir["cift_sayisi"], satir["ortalama"], satir["medyan"]), (0, None, None))


class KosuOlcumu(unittest.TestCase):
    def test_tum_kosular_tamamlandiysa_olcumsuzle_ayni(self):
        self.assertEqual(analiz(tum_olcumler()), analiz())

    def test_tamamlanamayan_kosunun_cifti_dislanir(self):
        o = tum_olcumler()
        o[1] = olcum("S-A", "merkezi", tamamlandi=False)
        t = analiz(o)
        self.assertEqual([s["sahne_kimligi"] for s in t["eslestirme_sahne"][1]], ["S-B", "S-D"])
        self.assertIn({"sahne_kimligi": "S-A", "neden": "merkezi: tamamlanamadi"}, t["eslestirme_dislanan"][1])
        kosu = {(s["sahne_kimligi"], s["mod"]): s for s in t["eslestirme_kosu"][1]}
        self.assertEqual((kosu[("S-A", "merkezi")]["tamamlandi"], kosu[("S-A", "merkezi")]["ciftte"], kosu[("S-A", "ucta")]["ciftte"]), (False, False, False))
        self.assertEqual(t["eslestirme_ozet"][1][0]["cift_sayisi"], 2)

    def test_rapor_yok_ama_olcum_tamamlanamadi(self):
        o = tum_olcumler() + [olcum("S-C", "merkezi", tamamlandi=False)]
        self.assertIn({"sahne_kimligi": "S-C", "neden": "merkezi: tamamlanamadi"}, analiz(o)["eslestirme_dislanan"][1])

    def test_olcum_eksik(self):
        with self.assertRaisesRegex(ea.GirdiHatasi, "koşu ölçüm özeti yok"):
            analiz(tum_olcumler()[:-1])

    def test_kosu_kimligi_uyusmuyor(self):
        o = tum_olcumler()
        o[0] = olcum("S-A", "ucta", kosu_kimligi="kosu_baska")
        with self.assertRaisesRegex(ea.GirdiHatasi, "koşu kimliği uyuşmuyor"):
            analiz(o)


class GirdiDenetimi(unittest.TestCase):
    def test_hedef_listesi_yok(self):
        r, hl = veri()
        with self.assertRaisesRegex(ea.GirdiHatasi, "hedef listesi yok: sahne 'S-C'"):
            ea.analiz(C, ESIK, r, hl[:2])

    def test_yinelenen_kosu(self):
        r, hl = veri()
        with self.assertRaisesRegex(ea.GirdiHatasi, "yinelenen koşu"):
            ea.analiz(C, ESIK, r + [r[0]], hl)

    def test_yinelenen_hedef_listesi(self):
        r, hl = veri()
        with self.assertRaisesRegex(ea.GirdiHatasi, "yinelenen hedef listesi"):
            ea.analiz(C, ESIK, r, hl + [hl[0]])

    def test_sozlesme_disi_rapor(self):
        r, hl = veri()
        r[0]["mod"] = "bilinmeyen"
        with self.assertRaisesRegex(ea.GirdiHatasi, "nihai_rapor: mod"):
            ea.analiz(C, ESIK, r, hl)


class KomutSatiri(unittest.TestCase):
    def test_dosyalar_yazilir(self):
        r, hl = veri()
        with tempfile.TemporaryDirectory() as d:
            hl_kl, cikti = os.path.join(d, "hedefler"), os.path.join(d, "cikti")
            os.makedirs(hl_kl)
            for liste in hl:
                with open(os.path.join(hl_kl, f"{liste['sahne_kimligi']}.json"), "w", encoding="utf-8") as f:
                    json.dump(liste, f)
            yollar = []
            for i, x in enumerate(r):
                yollar.append(os.path.join(d, f"rapor_{i}.json"))
                with open(yollar[-1], "w", encoding="utf-8") as f:
                    json.dump(x, f)
            p = subprocess.run([sys.executable, "-I", BETIK, "--hedef-listeleri", hl_kl, "--cikti", cikti, *yollar], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(sorted(os.listdir(cikti)), sorted(f"{ad}.{u}" for ad in ("eslestirme_kosu", "eslestirme_sahne", "eslestirme_ozet", "eslestirme_dislanan")
                                                                for u in ("csv", "md")))
            with open(os.path.join(cikti, "eslestirme_sahne.csv"), encoding="utf-8") as f:
                self.assertEqual(f.read(), SAHNE_CSV)
            with open(os.path.join(cikti, "eslestirme_ozet.csv"), encoding="utf-8") as f:
                self.assertEqual(f.read(), OZET_CSV)

            p = subprocess.run([sys.executable, "-I", BETIK, "--hedef-listeleri", hl_kl, "--cikti", cikti, *yollar, yollar[0]], capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertIn("yinelenen koşu", p.stderr)

    def test_kullanim_hatasi(self):
        p = subprocess.run([sys.executable, "-I", BETIK, "--cikti"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
