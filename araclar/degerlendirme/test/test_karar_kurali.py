#!/usr/bin/env python3
"""Karar kuralı betiği (E4a; FR-30) birim testleri: kuralın bütün dalları ve sınırları, sentetik zincir, sabit çıktı biçimi.
Çalıştırma: python3 -I araclar/degerlendirme/test/test_karar_kurali.py

Kural [belge]: D/B/T/L için GA alt > 0 → uçta lehine, üst < 0 → merkezi lehine, aksi fark gösterilemedi. R farkı için eşik e = −100·2/N
(N = 30 → −6,67 puan): alt > e → geride değil, üst < e → geride, aksi gösterilemedi. Sınıra eşitlik aralığın içinde sayılır [varsayım].
Sentetik 30 çift (tam veri, koşulsuz): D iyileşmesi ≈ 40 (uçta lehine), T iyileşmesi ≈ −10 (merkezi lehine), B iyileşmesi 0 civarı (fark
gösterilemedi), L ortanca farkı ≈ 0,3 s (uçta lehine), L p95 farkı tek değerden ibaret (tanımsız), R farkı ≈ 0 (geride değil).
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
BETIK = os.path.join(MODUL, "karar_kurali.py")
sys.path.insert(0, MODUL)
sys.path.insert(0, TEST)
import bootstrap_ga as bg  # noqa: E402
import iyilesme_analiz as ia  # noqa: E402
import karar_kurali as kk  # noqa: E402
import tablo  # noqa: E402
import test_eslestirme_analiz as tea  # noqa: E402
import test_iyilesme_analiz as tia  # noqa: E402

KILIT = kk.yapilandirma_yukle()
E = KILIT["r_esik_puan"]


def ga_satiri(t, o, alt, ust, ortalama=None, tanimli=30, b=None, tohum=None):
    return {"tablo": t, "olcut": o, "cift_sayisi": tanimli, "tanimli_sayisi": tanimli, "tanimsiz_sayisi": 0,
            "ortalama": ortalama if ortalama is not None else (None if alt is None else (alt + ust) / 2), "ga_alt": alt, "ga_ust": ust,
            "yeniden_ornekleme": KILIT["yeniden_ornekleme"] if b is None else b, "tohum": KILIT["tohum"] if tohum is None else tohum}


def ga(*satirlar):
    return {(s["tablo"], s["olcut"]): s for s in satirlar}


def karar_bul(cikti, olcut):
    return next(s for s in cikti["karar"][1] if s["olcut"] == olcut)


class Kilit(unittest.TestCase):
    def test_belge_degerleri(self):
        self.assertEqual(KILIT["n_hedef"], 30)
        self.assertAlmostEqual(E, -20 / 3)          # ≈ −6,67 puan [belge]
        self.assertEqual(KILIT["planlanan_cift"], 30)
        self.assertEqual(KILIT["yeniden_ornekleme"], 10000)


class KararVer(unittest.TestCase):
    def test_iyilesme_dallari_ve_sinirlar(self):
        for alt, ust, beklenen in ((0.1, 5.0, "uc_lehine"), (-5.0, -0.1, "merkezi_lehine"), (-1.0, 1.0, "fark_gosterilemedi"),
                                   (0.0, 3.0, "fark_gosterilemedi"), (-3.0, 0.0, "fark_gosterilemedi"), (0.0, 0.0, "fark_gosterilemedi"),
                                   (1e-12, 1e-9, "uc_lehine"), (None, None, "tanimsiz"), (None, 1.0, "tanimsiz")):
            with self.subTest(alt=alt, ust=ust):
                self.assertEqual(kk.karar_ver("yuzde_iyilesme", alt, ust, 0.0), beklenen)
                self.assertEqual(kk.karar_ver("gecikme_farki", alt, ust, 0.0), beklenen)

    def test_r_dallari_ve_sinirlar(self):
        for alt, ust, beklenen in ((-6.0, 10.0, "geride_degil"), (-30.0, -7.0, "geride"), (-7.0, -6.0, "geride_olmadigi_gosterilemedi"),
                                   (E, 5.0, "geride_olmadigi_gosterilemedi"), (-20.0, E, "geride_olmadigi_gosterilemedi"),
                                   (-1.0, 1.0, "geride_degil"), (None, None, "tanimsiz")):
            with self.subTest(alt=alt, ust=ust):
                self.assertEqual(kk.karar_ver("r_farki", alt, ust, E), beklenen)

    def test_r_sifiri_iceren_aralik_geride_degil_olabilir(self):
        # R kuralı sıfıra değil eşiğe bakar: GA [−5, +5] sıfırı içerir ama alt sınır −6,67'den büyüktür → "geride değil" [belge]
        self.assertEqual(kk.karar_ver("r_farki", -5.0, 5.0, E), "geride_degil")


class Analiz(unittest.TestCase):
    def tam(self):
        return ga(ga_satiri("iyilesme_sahne", "d_iyilesme_yuzde", 30.0, 50.0), ga_satiri("iyilesme_sahne", "b_iyilesme_yuzde", -2.0, 3.0),
                  ga_satiri("iyilesme_sahne", "t_iyilesme_yuzde", -12.0, -8.0), ga_satiri("iyilesme_sahne", "l_ortanca_fark", 0.2, 0.4),
                  ga_satiri("iyilesme_sahne", "l_p95_fark", -0.3, 0.1), ga_satiri("eslestirme_sahne", "r_fark", -3.0, 4.0),
                  ga_satiri("eslestirme_sahne", "r_ucta", 60.0, 80.0))

    def test_olcut_olcut_karar_tek_ortak_karar_yok(self):
        c = kk.analiz(self.tam(), KILIT)
        self.assertEqual([(s["olcut"], s["karar"]) for s in c["karar"][1]], [
            ("d_iyilesme_yuzde", "uc_lehine"), ("b_iyilesme_yuzde", "fark_gosterilemedi"), ("t_iyilesme_yuzde", "merkezi_lehine"),
            ("l_ortanca_fark", "uc_lehine"), ("l_p95_fark", "fark_gosterilemedi"), ("r_fark", "geride_degil")])
        self.assertEqual(len(c["karar"][1]), 6)   # karar ölçütü olmayan r_ucta karar almaz; genel/ortak satır yoktur
        self.assertTrue(all(not s["kosullu"] for s in c["karar"][1]))

    def test_belge_cumleleri_ve_notlar(self):
        c = kk.analiz(self.tam(), KILIT)
        b, r, d = karar_bul(c, "b_iyilesme_yuzde"), karar_bul(c, "r_fark"), karar_bul(c, "d_iyilesme_yuzde")
        self.assertEqual(b["karar_metni"], "fark gösterilemedi")
        self.assertIn("eşdeğerlik anlamına gelmez", b["not"])
        self.assertEqual(r["karar_metni"], "uçta mod tespitte merkezi moddan belirgin biçimde geride değil")
        self.assertIn("operasyonel yeterlilik anlamına gelmez", r["not"])
        self.assertAlmostEqual(r["esik"], E)
        self.assertEqual((r["birim"], d["birim"], karar_bul(c, "l_p95_fark")["birim"]), ("puan", "%", "s"))
        self.assertEqual(d["not"], "")
        self.assertEqual(d["esik"], 0.0)

    def test_kosullu_sonuc(self):
        g = self.tam()
        g[("iyilesme_sahne", "d_iyilesme_yuzde")] = ga_satiri("iyilesme_sahne", "d_iyilesme_yuzde", 30.0, 50.0, tanimli=28)
        d = karar_bul(kk.analiz(g, KILIT), "d_iyilesme_yuzde")
        self.assertEqual((d["karar"], d["kalan_cift"], d["planlanan_cift"], d["kosullu"]), ("uc_lehine", 28, 30, True))
        self.assertIn("yalnız tamamlanan 28 çiftle sınırlı", d["not"])

    def test_eksik_olcut_tanimsiz(self):
        g = self.tam()
        del g[("eslestirme_sahne", "r_fark")]
        r = karar_bul(kk.analiz(g, KILIT), "r_fark")
        self.assertEqual((r["karar"], r["kalan_cift"], r["kosullu"]), ("tanimsiz", 0, True))
        self.assertIn("girdide ölçüt yok", r["not"])

    def test_kilitli_olmayan_tohum_ya_da_sayi_reddedilir(self):
        for kw in ({"tohum": KILIT["tohum"] + 1}, {"b": 999}):
            with self.subTest(**kw):
                g = self.tam()
                g[("iyilesme_sahne", "t_iyilesme_yuzde")] = ga_satiri("iyilesme_sahne", "t_iyilesme_yuzde", -1.0, 1.0, **kw)
                with self.assertRaisesRegex(kk.GirdiHatasi, "kilitli"):
                    kk.analiz(g, KILIT)


class Zincir(unittest.TestCase):
    """E1a/E2a sahne tablosu → E3a bootstrap_ga.csv → E4a karar (gerçek dosya biçimleriyle)."""

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def bootstrap_csv(self, girdiler):
        yol = os.path.join(self.d, "bootstrap_ga.csv")
        with open(yol, "w", encoding="utf-8", newline="") as f:
            f.write(tablo.csv_metni(*bg.analiz(girdiler, KILIT["yeniden_ornekleme"], KILIT["tohum"])["bootstrap_ga"]))
        return yol

    def test_otuz_cift_sentetik(self):
        rng = random.Random(5)
        sutun = bg.beklenen_sutunlar(*bg.yapilandirma_yukle()[:2])
        iy = []
        for i in range(30):
            s = {k: rng.uniform(-1, 1) for k in sutun["iyilesme_sahne"][1:]}
            s.update({"sahne_kimligi": f"S{i:02d}", "d_iyilesme_yuzde": 40 + rng.uniform(-5, 5), "t_iyilesme_yuzde": -10 + rng.uniform(-3, 3),
                      "b_iyilesme_yuzde": rng.uniform(-5, 5), "l_ortanca_fark": 0.3 + rng.uniform(-0.05, 0.05),
                      "l_p95_fark": 0.5 if i == 0 else None})
            iy.append(s)
        es_ = [{"sahne_kimligi": f"S{i:02d}", **{k: rng.uniform(-2, 2) for k in sutun["eslestirme_sahne"][1:]}} for i in range(30)]
        c = kk.analiz(kk.csv_oku(self.bootstrap_csv([("eslestirme_sahne", sutun["eslestirme_sahne"], es_),
                                                     ("iyilesme_sahne", sutun["iyilesme_sahne"], iy)])), KILIT)
        self.assertEqual({s["olcut"]: s["karar"] for s in c["karar"][1]}, {
            "d_iyilesme_yuzde": "uc_lehine", "b_iyilesme_yuzde": "fark_gosterilemedi", "t_iyilesme_yuzde": "merkezi_lehine",
            "l_ortanca_fark": "uc_lehine", "l_p95_fark": "tanimsiz", "r_fark": "geride_degil"})
        self.assertFalse(karar_bul(c, "d_iyilesme_yuzde")["kosullu"])
        self.assertTrue(karar_bul(c, "l_p95_fark")["kosullu"])   # tek tanımlı çift

    def test_test_senaryolari_kosullu(self):
        sutun = bg.beklenen_sutunlar(*bg.yapilandirma_yukle()[:2])
        e1 = bg.csv_oku(self._yaz("e1.csv", tablo.csv_metni(*tea.analiz(tea.tum_olcumler())["eslestirme_sahne"])), "eslestirme_sahne",
                        sutun["eslestirme_sahne"])
        e2 = bg.csv_oku(self._yaz("e2.csv", tablo.csv_metni(*ia.analiz(bg.yapilandirma_yukle()[0], tia.senaryo())["iyilesme_sahne"])),
                        "iyilesme_sahne", sutun["iyilesme_sahne"])
        c = kk.analiz(kk.csv_oku(self.bootstrap_csv([("eslestirme_sahne", sutun["eslestirme_sahne"], e1),
                                                     ("iyilesme_sahne", sutun["iyilesme_sahne"], e2)])), KILIT)
        d = karar_bul(c, "d_iyilesme_yuzde")   # E2a testindeki iki tanımlı değer {75, −50} → GA [−50, 75]
        self.assertEqual((d["ga_alt"], d["ga_ust"], d["karar"], d["kalan_cift"], d["kosullu"]), (-50.0, 75.0, "fark_gosterilemedi", 2, True))
        self.assertTrue(all(s["kosullu"] for s in c["karar"][1]))

    def _yaz(self, ad, metin):
        yol = os.path.join(self.d, ad)
        with open(yol, "w", encoding="utf-8", newline="") as f:
            f.write(metin)
        return yol

    def test_bozuk_girdi(self):
        bas = ",".join(bg.SUTUNLAR)
        satir = f"iyilesme_sahne,t_iyilesme_yuzde,2,2,0,5.0,0.0,10.0,{KILIT['yeniden_ornekleme']},{KILIT['tohum']}"
        for metin, ileti in (("a,b\n", "başlık"), (f"{bas}\n{satir}\n{satir}\n", "yinelenen"), (f"{bas}\niyilesme_sahne,x,2\n", "hücre"),
                             (f"{bas}\n{satir.replace(',2,2,', ',iki,2,')}\n", "sayı değil"),
                             (f"{bas}\n{satir.replace('0.0,10.0', '10.0,0.0')}\n", "ga_alt > ga_ust")):
            with self.subTest(ileti=ileti):
                with self.assertRaisesRegex(kk.GirdiHatasi, ileti):
                    kk.csv_oku(self._yaz("b.csv", metin))


class Bicim(unittest.TestCase):
    """Sütun adları ve sırası sabittir (sözleşmeler §11.4); değişirse M8b'ye bildirilir."""

    def test_sutunlar_sabit(self):
        self.assertEqual(kk.analiz({}, KILIT)["karar"][0], [
            "olcut", "kaynak_tablo", "tur", "birim", "ortalama", "ga_alt", "ga_ust", "esik", "karar", "karar_metni", "kalan_cift", "planlanan_cift",
            "kosullu", "not"])

    def test_csv_ve_md_satiri(self):
        c = kk.analiz(ga(ga_satiri("eslestirme_sahne", "r_fark", -3.0, 4.0, ortalama=0.5)), KILIT)
        r = tablo.csv_metni(*c["karar"]).splitlines()[6]
        self.assertEqual(r, "r_fark,eslestirme_sahne,r_farki,puan,0.500000,-3.000000,4.000000,-6.666667,geride_degil,"
                            "uçta mod tespitte merkezi moddan belirgin biçimde geride değil,30,30,0,"
                            "operasyonel yeterlilik anlamına gelmez; mutlak R ayrıca raporlanır")
        md = tablo.md_metni("karar", *c["karar"]).splitlines()
        self.assertEqual(md[0], "# karar")
        self.assertIn("| -6,67 | geride_degil |", md[-1])


class KomutSatiri(unittest.TestCase):
    def calistir(self, *argumanlar):
        return subprocess.run([sys.executable, "-I", BETIK, *argumanlar], capture_output=True, text=True)

    def test_basarili_ve_hatalar(self):
        with tempfile.TemporaryDirectory() as d:
            y = os.path.join(d, "bootstrap_ga.csv")
            satir = f"iyilesme_sahne,d_iyilesme_yuzde,30,30,0,40.0,35.0,45.0,{KILIT['yeniden_ornekleme']},{KILIT['tohum']}"
            with open(y, "w", encoding="utf-8") as f:
                f.write(",".join(bg.SUTUNLAR) + "\n" + satir + "\n")
            cikti = os.path.join(d, "c")
            r = self.calistir("--cikti", cikti, y)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("(i) d_iyilesme_yuzde: uçta mod lehine fark gösterildi\n", r.stdout)
            self.assertIn("(i) r_fark: karar verilemedi (güven aralığı tanımsız) (koşullu)", r.stdout)
            self.assertEqual(sorted(os.listdir(cikti)), ["karar.csv", "karar.md"])
            with open(y, "w", encoding="utf-8") as f:
                f.write(",".join(bg.SUTUNLAR) + "\n" + satir.replace(f",{KILIT['tohum']}", ",1") + "\n")
            r = self.calistir("--cikti", cikti, y)
            self.assertEqual(r.returncode, 1)
            self.assertIn("kilitli", r.stderr)
        self.assertEqual(self.calistir().returncode, 2)
        self.assertEqual(self.calistir("--cikti", "x").returncode, 2)
        self.assertEqual(self.calistir("--cikti", "x", "a.csv", "b.csv").returncode, 2)
        self.assertEqual(self.calistir("--cikti", "x", "/yok/bootstrap_ga.csv").returncode, 2)


if __name__ == "__main__":
    unittest.main()
