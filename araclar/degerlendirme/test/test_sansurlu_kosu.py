#!/usr/bin/env python3
"""Sansürlü koşu betiği (E5a; FR-27) birim testleri: elle hesaplanmış sentetik veri, sabit çıktı biçimi.
Çalıştırma: python3 -I araclar/degerlendirme/test/test_sansurlu_kosu.py

Sentetik veri (planlanan çift 30, yapılandırmadan):
  S-A  uçta tamamlandı                               merkezi tamamlandı                              → çiftte
  S-B  uçta zaman_asimi, gözlenen 1200 s, kısmi 30,5 MB   merkezi tamamlandı                          → çift dışı
  S-C  uçta tamamlandı                               merkezi kuyruk_tasmasi, 400 s, kısmi bilinmiyor  → çift dışı
  S-D  uçta surec_olumu, 100 s, kısmi 1 MB           merkezi diger, 50 s, kısmi 0 MB                  → çift dışı
  S-E  uçta tamamlandı                               merkezi özeti yok                                → çift dışı
H boş: alt sınır = gözlenen süre. H = 1200: bütün alt sınırlar 1200 (süreç ölümü ve taşma da COMPLETE yayımlamaz). H = 1500: S-B tutarsız.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import json
import unittest

TEST = os.path.dirname(os.path.abspath(__file__))
MODUL = os.path.dirname(TEST)   # araclar/degerlendirme
BETIK = os.path.join(MODUL, "sansurlu_kosu.py")
sys.path.insert(0, MODUL)
sys.path.insert(0, TEST)
import sansurlu_kosu as sk  # noqa: E402
import tablo  # noqa: E402
import test_iyilesme_analiz as tia  # noqa: E402

C, H_YAP, PLAN = sk.yapilandirma_yukle()
YAP = os.path.join(sk.ia.KOK, "config", "deney.env")


def eksik(sahne, mod, neden, gozlenen, kismi):
    o = tia.olcum(sahne, mod, tamamlandi=False)
    o["tamamlanamadi"] = {"neden": neden, "gozlenen_sure_s": gozlenen, "kismi_trafik_mb": kismi}
    return o


def senaryo():
    return [tia.olcum("S-A", "ucta"), tia.olcum("S-A", "merkezi"),
            eksik("S-B", "ucta", "zaman_asimi", 1200.0, 30.5), tia.olcum("S-B", "merkezi"),
            tia.olcum("S-C", "ucta"), eksik("S-C", "merkezi", "kuyruk_tasmasi", 400.0, None),
            eksik("S-D", "ucta", "surec_olumu", 100.0, 1.0), eksik("S-D", "merkezi", "diger", 50.0, 0.0),
            tia.olcum("S-E", "ucta")]


def ozet(t, kapsam):
    return next(s for s in t["sansurlu_ozet"][1] if s["kapsam"] == kapsam)


class Yapilandirma(unittest.TestCase):
    def test_depodaki_degerler(self):
        self.assertEqual(PLAN, 30)
        self.assertIsNone(H_YAP)   # H, C12'de (M7) kilitlenene kadar boş

    def yaz(self, d, h):
        with open(YAP, encoding="utf-8") as f:
            satirlar = [s for s in f if not s.startswith(f"{sk.H_ANAHTARI}=")]
        if h is not None:
            satirlar.append(f'{sk.H_ANAHTARI}="{h}"\n')
        yol = os.path.join(d, "deney.env")
        with open(yol, "w", encoding="utf-8") as f:
            f.writelines(satirlar)
        return yol

    def test_h_degerleri(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(sk.yapilandirma_yukle(self.yaz(d, "1200"))[1], 1200.0)
            for kotu in ("abc", "0", "-5", "inf", "nan"):
                with self.subTest(h=kotu), self.assertRaises(ValueError):
                    sk.yapilandirma_yukle(self.yaz(d, kotu))
            with self.assertRaisesRegex(ValueError, "eksik anahtar"):
                sk.yapilandirma_yukle(self.yaz(d, None))


class Hesap(unittest.TestCase):
    def test_tamamlanamayanlarin_hepsi_listelenir(self):
        t = sk.analiz(C, None, PLAN, senaryo())
        self.assertEqual([(s["sahne_kimligi"], s["mod"], s["neden"], s["gozlenen_sure_s"], s["t_alt_sinir_s"], s["kismi_trafik_mb"], s["h_s"])
                          for s in t["sansurlu_kosu"][1]], [
            ("S-B", "ucta", "zaman_asimi", 1200.0, 1200.0, 30.5, None),
            ("S-C", "merkezi", "kuyruk_tasmasi", 400.0, 400.0, None, None),
            ("S-D", "ucta", "surec_olumu", 100.0, 100.0, 1.0, None),
            ("S-D", "merkezi", "diger", 50.0, 50.0, 0.0, None)])

    def test_h_ile_alt_sinir(self):
        t = sk.analiz(C, 1200.0, PLAN, senaryo())
        self.assertEqual([s["t_alt_sinir_s"] for s in t["sansurlu_kosu"][1]], [1200.0] * 4)
        self.assertEqual({s["h_s"] for s in t["sansurlu_kosu"][1]}, {1200.0})
        self.assertEqual(sk.sansur_alt_siniri(1300.0, 1200.0), 1300.0)

    def test_h_den_kisa_zaman_asimi_tutarsiz(self):
        with self.assertRaisesRegex(sk.GirdiHatasi, "H'den"):
            sk.analiz(C, 1500.0, PLAN, senaryo())
        sk.analiz(C, 1200.0005, PLAN, senaryo())   # 1 ms pay

    def test_cift_durumlari(self):
        t = sk.analiz(C, None, PLAN, senaryo())
        self.assertEqual([(s["sahne_kimligi"], s["ucta"], s["merkezi"], s["ciftte"]) for s in t["sansurlu_cift"][1]], [
            ("S-A", "tamamlandi", "tamamlandi", True), ("S-B", "tamamlanamadi", "tamamlandi", False),
            ("S-C", "tamamlandi", "tamamlanamadi", False), ("S-D", "tamamlanamadi", "tamamlanamadi", False),
            ("S-E", "tamamlandi", "kosu_olcum_yok", False)])

    def test_ozet(self):
        t = sk.analiz(C, None, PLAN, senaryo())
        alanlar = ("planlanan", "kayitli", "tamamlanan", "tamamlanamayan", "zaman_asimi", "kuyruk_tasmasi", "surec_olumu", "diger", "kayit_yok",
                   "kosullu")
        self.assertEqual(tuple(ozet(t, "ucta")[a] for a in alanlar), (30, 5, 3, 2, 1, 0, 1, 0, 25, True))
        self.assertEqual(tuple(ozet(t, "merkezi")[a] for a in alanlar), (30, 4, 2, 2, 0, 1, 0, 1, 26, True))
        self.assertEqual(tuple(ozet(t, "cift")[a] for a in alanlar), (30, 5, 1, 3, 1, 1, 1, 1, 25, True))
        self.assertEqual([s["kapsam"] for s in t["sansurlu_ozet"][1]], ["ucta", "merkezi", "cift"])

    def test_tam_veri_kosulsuz(self):
        t = sk.analiz(C, 1200.0, PLAN, [tia.olcum(f"S{i:02d}", m) for i in range(PLAN) for m in ("ucta", "merkezi")])
        self.assertEqual(t["sansurlu_kosu"][1], [])
        self.assertTrue(all(not s["kosullu"] and s["tamamlanan"] == PLAN and s["kayit_yok"] == 0 for s in t["sansurlu_ozet"][1]))

    def test_tek_tamamlanamayan_kosu_bile_kosullu_yapar(self):
        olcumler = [tia.olcum(f"S{i:02d}", m) for i in range(PLAN) for m in ("ucta", "merkezi")]
        olcumler[-1] = eksik(f"S{PLAN - 1:02d}", "merkezi", "zaman_asimi", 1200.0, 3.0)
        c = ozet(sk.analiz(C, 1200.0, PLAN, olcumler), "cift")
        self.assertEqual((c["tamamlanan"], c["tamamlanamayan"], c["kosullu"]), (PLAN - 1, 1, True))

    def test_girdi_hatalari(self):
        with self.assertRaisesRegex(sk.GirdiHatasi, "yinelenen"):
            sk.analiz(C, None, PLAN, [tia.olcum("S-A", "ucta"), tia.olcum("S-A", "ucta")])
        with self.assertRaisesRegex(sk.GirdiHatasi, "planlanandan"):
            sk.analiz(C, None, 2, [tia.olcum(s, "ucta") for s in ("S1", "S2", "S3")])
        bozuk = eksik("S-A", "ucta", "bilinmeyen_neden", 10.0, 0.0)
        with self.assertRaisesRegex(sk.GirdiHatasi, "kosu_olcum"):
            sk.analiz(C, None, PLAN, [bozuk])

    def test_dosya_sirasi_sonucu_degistirmez(self):
        t1 = sk.analiz(C, None, PLAN, senaryo())
        t2 = sk.analiz(C, None, PLAN, list(reversed(senaryo())))
        for ad, (sutunlar, satirlar) in t1.items():
            self.assertEqual(tablo.csv_metni(sutunlar, satirlar), tablo.csv_metni(*t2[ad]), ad)


class Bicim(unittest.TestCase):
    """Sütun adları ve sırası sabittir (sözleşmeler §11.4); değişirse M8b'ye bildirilir."""

    def test_sutunlar_sabit(self):
        t = sk.analiz(C, None, PLAN, [])
        self.assertEqual(t["sansurlu_kosu"][0], ["sahne_kimligi", "mod", "kosu_kimligi", "neden", "gozlenen_sure_s", "h_s", "t_alt_sinir_s",
                                                 "kismi_trafik_mb"])
        self.assertEqual(t["sansurlu_cift"][0], ["sahne_kimligi", "ucta", "merkezi", "ciftte"])
        self.assertEqual(t["sansurlu_ozet"][0], ["kapsam", "planlanan", "kayitli", "tamamlanan", "tamamlanamayan", "zaman_asimi", "kuyruk_tasmasi",
                                                 "surec_olumu", "diger", "kayit_yok", "kosullu"])

    def test_csv_ve_md_satiri(self):
        t = sk.analiz(C, None, PLAN, senaryo())
        k = tablo.csv_metni(*t["sansurlu_kosu"]).splitlines()
        self.assertEqual(k[1], "S-B,ucta,kosu_S-B_ucta,zaman_asimi,1200.000000,,1200.000000,30.500000")
        self.assertEqual(k[2], "S-C,merkezi,kosu_S-C_merkezi,kuyruk_tasmasi,400.000000,,400.000000,")
        self.assertEqual(tablo.csv_metni(*t["sansurlu_ozet"]).splitlines()[3], "cift,30,5,1,3,1,1,1,1,25,1")
        md = tablo.md_metni("sansurlu_kosu", *t["sansurlu_kosu"]).splitlines()
        self.assertEqual(md[4], "| S-B | ucta | kosu_S-B_ucta | zaman_asimi | 1200,00 | tanımsız | 1200,00 | 30,50 |")


class KomutSatiri(unittest.TestCase):
    def calistir(self, *argumanlar):
        return subprocess.run([sys.executable, "-I", BETIK, *argumanlar], capture_output=True, text=True)

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def dosyalar(self, olcumler):
        yollar = []
        for i, o in enumerate(olcumler):
            yollar.append(os.path.join(self.d, f"o{i}.json"))
            with open(yollar[-1], "w", encoding="utf-8") as f:
                json.dump(o, f)
        return yollar

    def test_basarili(self):
        cikti = os.path.join(self.d, "c")
        r = self.calistir("--cikti", cikti, *self.dosyalar(senaryo()))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("9 koşu, 4 tamamlanamayan; tamamlanan çift 1/30 (koşullu sonuç)", r.stdout)
        self.assertIn("(!) ZAMAN_ASIMI_H_SN boş", r.stdout)
        self.assertEqual(sorted(os.listdir(cikti)), sorted(f"{a}.{u}" for a in ("sansurlu_kosu", "sansurlu_cift", "sansurlu_ozet")
                                                           for u in ("csv", "md")))

    def test_hatalar(self):
        y = self.dosyalar([tia.olcum("S-A", "ucta")])[0]
        r = self.calistir("--cikti", os.path.join(self.d, "c"), y, y)
        self.assertEqual(r.returncode, 1)
        self.assertIn("yinelenen", r.stderr)
        self.assertEqual(self.calistir().returncode, 2)
        self.assertEqual(self.calistir("--cikti", "x").returncode, 2)
        self.assertEqual(self.calistir("--cikti", "x", "--yapilandirma").returncode, 2)
        self.assertEqual(self.calistir("--cikti", "x", "/yok/o.json").returncode, 2)


if __name__ == "__main__":
    unittest.main()
