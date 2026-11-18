#!/usr/bin/env python3
"""Bootstrap betiği (E3a; FR-29) birim testleri: elle hesaplanabilen sentetik örnekler, sabit çıktı biçimi.
Çalıştırma: python3 -I araclar/degerlendirme/test/test_bootstrap_ga.py

Beklenen değerler:
  {0, 10}               bootstrap ortalaması 0, 5, 10 olasılıkları 1/4, 1/2, 1/4 → 2,5. yüzdelik 0, 97,5. yüzdelik 10 (10.000 örnekte kesin)
  sabit sütun            GA = [c, c]
  eşleştirme             r_merkezi = r_ucta − 5 → r_fark her örnekte 5 → GA [5, 5] (çiftler ayrı çekilseydi aralık geniş olurdu)
  normal veri (n = 30)   GA ≈ ortalama ± 1,96·s/√n·√((n−1)/n) (göreli %10 içinde)
  ölçek                  ikinci sütun = 2 × birinci → GA da 2 katı (aynı tanımlı sayısı aynı sahne seçimlerini paylaşır)
Zincir: E1a ve E2a test senaryolarının sahne tabloları CSV'ye yazılıp okunur (biçim uyumu).
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

TEST = os.path.dirname(os.path.abspath(__file__))
MODUL = os.path.dirname(TEST)   # araclar/degerlendirme
BETIK = os.path.join(MODUL, "bootstrap_ga.py")
sys.path.insert(0, MODUL)
sys.path.insert(0, TEST)
import bootstrap_ga as bg  # noqa: E402
import tablo  # noqa: E402
import iyilesme_analiz as ia  # noqa: E402
import test_eslestirme_analiz as tea  # noqa: E402
import test_iyilesme_analiz as tia  # noqa: E402

C, ESIK, B, TOHUM = bg.yapilandirma_yukle()
BEKLENEN = bg.beklenen_sutunlar(C, ESIK)


def satirlar(**sutunlar):
    """Sütun adı → değer listesi; sahne kimlikleri S01, S02, …"""
    n = len(next(iter(sutunlar.values())))
    return [{"sahne_kimligi": f"S{i + 1:02d}", **{k: v[i] for k, v in sutunlar.items()}} for i in range(n)]


def satir_bul(cikti, olcut, tablo_adi=None):
    return next(s for s in cikti["bootstrap_ga"][1] if s["olcut"] == olcut and (tablo_adi is None or s["tablo"] == tablo_adi))


class Yapilandirma(unittest.TestCase):
    def test_belge_degeri(self):
        self.assertEqual(B, 10000)   # [belge, FR-29]
        self.assertIsInstance(TOHUM, int)


class OrtalamaGA(unittest.TestCase):
    def test_iki_deger_kesin(self):
        n, ort, alt, ust = bg.ortalama_ga([0.0, 10.0], B, TOHUM)
        self.assertEqual((n, ort, alt, ust), (2, 5.0, 0.0, 10.0))

    def test_sabit_sutun(self):
        n, ort, alt, ust = bg.ortalama_ga([3.25] * 12, B, TOHUM)
        self.assertEqual(n, 12)
        for v in (ort, alt, ust):
            self.assertAlmostEqual(v, 3.25, places=12)

    def test_normal_yaklasim(self):
        rng = random.Random(42)
        x = [rng.gauss(10.0, 4.0) for _ in range(30)]
        n, ort, alt, ust = bg.ortalama_ga(x, B, TOHUM)
        s = (sum((v - ort) ** 2 for v in x) / (n - 1)) ** 0.5
        yari = 1.96 * s / n ** 0.5 * ((n - 1) / n) ** 0.5
        self.assertLess(alt, ort)
        self.assertGreater(ust, ort)
        self.assertAlmostEqual((ust - alt) / 2, yari, delta=0.1 * yari)
        self.assertAlmostEqual((ust + alt) / 2, ort, delta=0.1 * yari)

    def test_tanimsiz_degerler(self):
        self.assertEqual(bg.ortalama_ga([], B, TOHUM), (0, None, None, None))
        self.assertEqual(bg.ortalama_ga([None, None], B, TOHUM), (0, None, None, None))
        self.assertEqual(bg.ortalama_ga([None, 7.0], B, TOHUM), (1, 7.0, None, None))   # tek değerden aralık kurulmaz [varsayım 2]
        n, ort, alt, ust = bg.ortalama_ga([None, 1.0, 2.0, 3.0], B, TOHUM)
        self.assertEqual((n, ort), (3, 2.0))
        self.assertEqual((alt, ust), bg.ortalama_ga([1.0, 2.0, 3.0], B, TOHUM)[2:])   # tanımsız çıkarılır [varsayım 1]

    def test_tohum_tekrarlanabilir(self):
        x = [1.0, 4.0, 9.0, 16.0, 25.0, 36.0]
        self.assertEqual(bg.ortalama_ga(x, B, TOHUM), bg.ortalama_ga(x, B, TOHUM))
        self.assertNotEqual(bg.ortalama_ga(x, B, TOHUM)[2:], bg.ortalama_ga(x, B, TOHUM + 1)[2:])


class Analiz(unittest.TestCase):
    def test_eslestirme_bozulmaz(self):
        uc = [10.0, 50.0, 90.0, 30.0, 70.0, 20.0]
        sutunlar = ["sahne_kimligi", "r_ucta", "r_merkezi", "r_fark"]
        s = satirlar(r_ucta=uc, r_merkezi=[v - 5 for v in uc], r_fark=[5.0] * 6)
        c = bg.analiz([("eslestirme_sahne", sutunlar, s)], B, TOHUM)
        fark = satir_bul(c, "r_fark")
        self.assertEqual((fark["ga_alt"], fark["ga_ust"]), (5.0, 5.0))
        ucta = satir_bul(c, "r_ucta")
        self.assertGreater(ucta["ga_ust"] - ucta["ga_alt"], 20.0)
        merkezi = satir_bul(c, "r_merkezi")   # aynı sahne seçimleri: merkezi aralık uçtanın tam 5 aşağısı
        self.assertAlmostEqual(merkezi["ga_alt"], ucta["ga_alt"] - 5)
        self.assertAlmostEqual(merkezi["ga_ust"], ucta["ga_ust"] - 5)

    def test_ayni_secimler_ve_sira_bagimsizligi(self):
        x = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
        s = satirlar(a=x, b=[2 * v for v in x])
        c1 = bg.analiz([("iyilesme_sahne", ["sahne_kimligi", "a", "b"], s)], B, TOHUM)
        c2 = bg.analiz([("iyilesme_sahne", ["sahne_kimligi", "b", "a"], s)], B, TOHUM)
        a, b = satir_bul(c1, "a"), satir_bul(c1, "b")
        self.assertAlmostEqual(b["ga_alt"], 2 * a["ga_alt"])
        self.assertAlmostEqual(b["ga_ust"], 2 * a["ga_ust"])
        self.assertEqual(satir_bul(c2, "a"), a)

    def test_satir_alanlari(self):
        s = satirlar(d_iyilesme_yuzde=[10.0, None, 30.0])
        r = bg.analiz([("iyilesme_sahne", ["sahne_kimligi", "d_iyilesme_yuzde"], s)], B, TOHUM)["bootstrap_ga"][1][0]
        self.assertEqual({k: r[k] for k in ("tablo", "olcut", "cift_sayisi", "tanimli_sayisi", "tanimsiz_sayisi", "ortalama", "yeniden_ornekleme",
                                            "tohum")},
                         {"tablo": "iyilesme_sahne", "olcut": "d_iyilesme_yuzde", "cift_sayisi": 3, "tanimli_sayisi": 2, "tanimsiz_sayisi": 1,
                          "ortalama": 20.0, "yeniden_ornekleme": B, "tohum": TOHUM})
        self.assertEqual((r["ga_alt"], r["ga_ust"]), (10.0, 30.0))   # iki değer: {10, 30} → 2,5. ve 97,5. yüzdelik uçlar

    def test_bos_tablo(self):
        c = bg.analiz([("iyilesme_sahne", BEKLENEN["iyilesme_sahne"], [])], B, TOHUM)["bootstrap_ga"][1]
        self.assertEqual(len(c), len(BEKLENEN["iyilesme_sahne"]) - 1)
        self.assertEqual((c[0]["cift_sayisi"], c[0]["ortalama"], c[0]["ga_alt"]), (0, None, None))


class CsvZinciri(unittest.TestCase):
    """E1a ve E2a'nın gerçek çıktı biçimi E3a'ya girer."""

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def yaz(self, ad, metin):
        yol = os.path.join(self.d, ad)
        with open(yol, "w", encoding="utf-8", newline="") as f:
            f.write(metin)
        return yol

    def e1a_csv(self):
        return self.yaz("eslestirme_sahne.csv", tablo.csv_metni(*tea.analiz(tea.tum_olcumler())["eslestirme_sahne"]))

    def e2a_csv(self):
        return self.yaz("iyilesme_sahne.csv", tablo.csv_metni(*ia.analiz(C, tia.senaryo())["iyilesme_sahne"]))

    def test_e1a_csv(self):
        s = bg.csv_oku(self.e1a_csv(), "eslestirme_sahne", BEKLENEN["eslestirme_sahne"])
        self.assertEqual([x["sahne_kimligi"] for x in s], ["S-A", "S-B", "S-D"])
        self.assertEqual(s[0]["r_fark"], 50.0)
        self.assertIsNone(s[1]["precision_ucta"])
        c = bg.analiz([("eslestirme_sahne", BEKLENEN["eslestirme_sahne"], s)], B, TOHUM)
        r = satir_bul(c, "r_fark")
        self.assertAlmostEqual(r["ortalama"], (50 - 25 + 25) / 3)
        self.assertLessEqual(r["ga_alt"], r["ortalama"])
        self.assertGreaterEqual(r["ga_ust"], r["ortalama"])
        self.assertEqual(satir_bul(c, "precision_ucta")["tanimsiz_sayisi"], 1)

    def test_e2a_csv(self):
        s = bg.csv_oku(self.e2a_csv(), "iyilesme_sahne", BEKLENEN["iyilesme_sahne"])
        c = bg.analiz([("iyilesme_sahne", BEKLENEN["iyilesme_sahne"], s)], B, TOHUM)
        d = satir_bul(c, "d_iyilesme_yuzde")
        self.assertEqual((d["cift_sayisi"], d["tanimli_sayisi"], d["ortalama"], d["ga_alt"], d["ga_ust"]), (3, 2, 12.5, -50.0, 75.0))

    def test_baslik_uyusmuyor(self):
        y = self.yaz("x.csv", "sahne_kimligi,r_ucta\nS-A,1\n")
        with self.assertRaisesRegex(bg.GirdiHatasi, "başlık"):
            bg.csv_oku(y, "eslestirme_sahne", BEKLENEN["eslestirme_sahne"])
        with self.assertRaisesRegex(bg.GirdiHatasi, "başlık"):   # yanlış tablo (E1a başlığı E2a yerine)
            bg.csv_oku(self.e1a_csv(), "iyilesme_sahne", BEKLENEN["iyilesme_sahne"])

    def test_bozuk_hucreler(self):
        bas = ",".join(BEKLENEN["iyilesme_sahne"])
        bos = "," * (len(BEKLENEN["iyilesme_sahne"]) - 2)
        for govde, ileti in ((f"S-A,abc{bos}", "sayı değil"), (f"S-A,inf{bos}", "sonlu"), (f"S-A,1{bos}\nS-A,2{bos}", "yinelenen"),
                             ("S-A,1", "hücre")):
            with self.subTest(ileti=ileti):
                y = self.yaz("b.csv", f"{bas}\n{govde}\n")
                with self.assertRaisesRegex(bg.GirdiHatasi, ileti):
                    bg.csv_oku(y, "iyilesme_sahne", BEKLENEN["iyilesme_sahne"])


class Bicim(unittest.TestCase):
    """Sütun adları ve sırası sabittir (sözleşmeler §11.4); değişirse E4a ve M8b'ye bildirilir."""

    def test_sutunlar_sabit(self):
        self.assertEqual(bg.analiz([], B, TOHUM)["bootstrap_ga"][0], [
            "tablo", "olcut", "cift_sayisi", "tanimli_sayisi", "tanimsiz_sayisi", "ortalama", "ga_alt", "ga_ust", "yeniden_ornekleme", "tohum"])

    def test_csv_satiri(self):
        c = bg.analiz([("iyilesme_sahne", ["sahne_kimligi", "t_iyilesme_yuzde"], satirlar(t_iyilesme_yuzde=[0.0, 10.0]))], B, TOHUM)
        self.assertEqual(tablo.csv_metni(*c["bootstrap_ga"]).splitlines()[1],
                         f"iyilesme_sahne,t_iyilesme_yuzde,2,2,0,5.000000,0.000000,10.000000,{B},{TOHUM}")
        self.assertIn("| 5,00 | 0,00 | 10,00 |", tablo.md_metni("bootstrap_ga", *c["bootstrap_ga"]))


class KomutSatiri(unittest.TestCase):
    def calistir(self, *argumanlar):
        return subprocess.run([sys.executable, "-I", BETIK, *argumanlar], capture_output=True, text=True)

    def test_basarili(self):
        with tempfile.TemporaryDirectory() as d:
            e1 = os.path.join(d, "e1.csv")
            e2 = os.path.join(d, "e2.csv")
            with open(e1, "w", encoding="utf-8", newline="") as f:
                f.write(tablo.csv_metni(*tea.analiz(tea.tum_olcumler())["eslestirme_sahne"]))
            with open(e2, "w", encoding="utf-8", newline="") as f:
                f.write(tablo.csv_metni(*ia.analiz(C, tia.senaryo())["iyilesme_sahne"]))
            cikti = os.path.join(d, "c")
            r = self.calistir("--cikti", cikti, "--eslestirme-sahne", e1, "--iyilesme-sahne", e2)
            self.assertEqual(r.returncode, 0, r.stderr)
            olcut = len(BEKLENEN["eslestirme_sahne"]) + len(BEKLENEN["iyilesme_sahne"]) - 2
            self.assertIn(f"(+) {olcut} ölçüt, {B} yeniden örnekleme, tohum {TOHUM}", r.stdout)
            self.assertEqual(sorted(os.listdir(cikti)), ["bootstrap_ga.csv", "bootstrap_ga.md"])
            with open(os.path.join(cikti, "bootstrap_ga.csv"), encoding="utf-8") as f:
                self.assertEqual(len(f.read().splitlines()), olcut + 1)

    def test_girdi_hatasi_1(self):
        with tempfile.TemporaryDirectory() as d:
            y = os.path.join(d, "x.csv")
            with open(y, "w", encoding="utf-8") as f:
                f.write("a,b\n")
            r = self.calistir("--cikti", os.path.join(d, "c"), "--iyilesme-sahne", y)
            self.assertEqual(r.returncode, 1)
            self.assertIn("başlık", r.stderr)

    def test_kullanim_ve_yapilandirma_2(self):
        self.assertEqual(self.calistir().returncode, 2)
        self.assertEqual(self.calistir("--cikti", "x").returncode, 2)   # girdi tablosu yok
        self.assertEqual(self.calistir("--cikti", "x", "--iyilesme-sahne").returncode, 2)
        self.assertEqual(self.calistir("--bilinmeyen", "1").returncode, 2)
        with tempfile.TemporaryDirectory() as d:
            yap = os.path.join(d, "deney.env")
            with open(os.path.join(bg.es.KOK, "config", "deney.env"), encoding="utf-8") as f:
                metin = "".join(s for s in f if not s.startswith("BOOTSTRAP_TOHUM="))
            with open(yap, "w", encoding="utf-8") as f:
                f.write(metin)
            r = self.calistir("--cikti", os.path.join(d, "c"), "--iyilesme-sahne", os.path.join(d, "yok.csv"), "--yapilandirma", yap)
            self.assertEqual(r.returncode, 2)
            self.assertIn("BOOTSTRAP_TOHUM", r.stderr)


if __name__ == "__main__":
    unittest.main()
