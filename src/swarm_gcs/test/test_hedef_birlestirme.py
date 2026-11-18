"""Hedef birleştirme birim testleri (ROS 2 gerekmez). Çalıştırma: python3 src/swarm_gcs/test/test_hedef_birlestirme.py"""
import json
import os
import random
import sys
import tempfile
import unittest

KOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
sys.path.insert(0, os.path.join(KOK, "src", "swarm_gcs"))
sys.path.insert(0, os.path.join(KOK, "araclar"))
from swarm_gcs.birlestirme import hedef_birlestirme as hb  # noqa: E402
from swarm_gcs.birlestirme.hedef_birlestirme import BirlestirmeHatasi, Tespit, birlestir  # noqa: E402
from sozlesme_dogrula import Yapilandirma, dogrula_nihai_rapor, yapilandirma_yukle  # noqa: E402

ARALIK = 2.5
C = Yapilandirma(yapilandirma_yukle(os.path.join(KOK, "config", "deney.env")))


def t(arac, n, sim, sinif="insan", guven=0.5, konum=(0.0, 0.0)):
    return Tespit(arac, n, sim, sinif, guven, konum)


class Birlestirme(unittest.TestCase):
    def test_bos_girdi(self):
        self.assertEqual(birlestir([], ARALIK), [])

    def test_tek_tespit(self):
        r = birlestir([t(1, 10, 100, guven=0.7, konum=(3.0, 4.0))], ARALIK)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["rapor_kimligi"], "R001")
        self.assertEqual(r[0]["konum"], {"x_m": 3.0, "y_m": 4.0})
        self.assertEqual(r[0]["ilk_konum"], {"x_m": 3.0, "y_m": 4.0})
        self.assertEqual(r[0]["tespit_sayisi"], 1)
        self.assertEqual(r[0]["ilk_tespit"], r[0]["en_yuksek_guven_tespiti"])
        self.assertEqual(r[0]["ilk_tespit"], {"arac_kimligi": 1, "n": 10, "sim_damga_ns": 100})

    def test_sinir_dahil_ve_epsilon_disi(self):
        r = birlestir([t(1, 1, 1, konum=(0, 0)), t(1, 2, 2, konum=(2.5, 0))], ARALIK)
        self.assertEqual(len(r), 1, "tam 2,5 m eklenir (≤)")
        self.assertEqual(r[0]["tespit_sayisi"], 2)
        r = birlestir([t(1, 1, 1, konum=(0, 0)), t(1, 2, 2, konum=(2.5 + 1e-9, 0))], ARALIK)
        self.assertEqual(len(r), 2, "2,5 m + ε yeni aday")

    def test_ilk_konum_sabit_surunme_yok(self):
        # A→B 2 m, B→C 2 m, A→C 4 m: adayın konumu ilk tespitte KİLİTLİ; C yeni aday
        r = birlestir([t(1, 1, 1, konum=(0, 0), guven=0.3), t(1, 2, 2, konum=(2, 0), guven=0.9), t(1, 3, 3, konum=(4, 0), guven=0.4)], ARALIK)
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0]["ilk_konum"], {"x_m": 0.0, "y_m": 0.0})
        self.assertEqual(r[0]["konum"], {"x_m": 2.0, "y_m": 0.0}, "nihai konum en yüksek güvenli tespitin konumu; ilk konum değişmez")
        self.assertEqual(r[1]["ilk_konum"], {"x_m": 4.0, "y_m": 0.0})

    def test_farkli_sinif_ayni_yer(self):
        r = birlestir([t(1, 1, 1, "insan"), t(1, 2, 2, "enkaz")], ARALIK)
        self.assertEqual([x["sinif"] for x in r], ["insan", "enkaz"])

    def test_iki_uygun_aday_en_yakin(self):
        # A (0,0) ve B (4,0) iki aday. (2.2,0): A'ya 2,2, B'ye 1,8 → ikisi de ≤ 2,5 uygun; en yakın B
        r = birlestir([t(1, 1, 1, konum=(0, 0)), t(1, 2, 2, konum=(4, 0)), t(1, 3, 3, konum=(2.2, 0))], ARALIK)
        self.assertEqual([x["tespit_sayisi"] for x in r], [1, 2])
        # (1.8,0): A'ya 1,8, B'ye 2,2 → en yakın A
        r = birlestir([t(1, 1, 1, konum=(0, 0)), t(1, 2, 2, konum=(4, 0)), t(1, 3, 3, konum=(1.8, 0))], ARALIK)
        self.assertEqual([x["tespit_sayisi"] for x in r], [2, 1])

    def test_esit_uzaklik_en_eski_aday(self):
        r = birlestir([t(1, 1, 1, konum=(0, 0)), t(1, 2, 2, konum=(4, 0)), t(1, 3, 3, konum=(2, 0))], ARALIK)
        self.assertEqual([x["tespit_sayisi"] for x in r], [2, 1], "eşit uzaklıkta ilk açılan (en eski) aday")

    def test_nihai_konum_en_yuksek_guven_ve_esitlikte_en_eski(self):
        r = birlestir([t(1, 1, 1, guven=0.4, konum=(0, 0)), t(2, 1, 2, guven=0.9, konum=(1, 0)), t(3, 1, 3, guven=0.9, konum=(2, 0)), t(1, 2, 4, guven=0.6, konum=(0.5, 0))], ARALIK)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["guven"], 0.9)
        self.assertEqual(r[0]["konum"], {"x_m": 1.0, "y_m": 0.0}, "güven eşitliğinde en eski tespit")
        self.assertEqual(r[0]["en_yuksek_guven_tespiti"], {"arac_kimligi": 2, "n": 1, "sim_damga_ns": 2})
        self.assertEqual(r[0]["ilk_tespit"], {"arac_kimligi": 1, "n": 1, "sim_damga_ns": 1})
        self.assertEqual(r[0]["tespit_sayisi"], 4)

    def test_konumsuz_ayri_rapor_birlestirmeye_girmez(self):
        r = birlestir([t(1, 1, 1, konum=(0, 0), guven=0.4), t(2, 1, 2, konum=None, guven=0.8), t(3, 1, 3, konum=None, guven=0.6), t(1, 2, 4, konum=(0.5, 0), guven=0.5)], ARALIK)
        self.assertEqual(len(r), 3)
        konumlu = [x for x in r if x["konum"] is not None]
        konumsuz = [x for x in r if x["konum"] is None]
        self.assertEqual(len(konumsuz), 2, "her konumsuz tespit ayrı rapor")
        for x in konumsuz:
            self.assertIsNone(x["ilk_konum"])
            self.assertEqual(x["tespit_sayisi"], 1)
        self.assertEqual(konumlu[0]["tespit_sayisi"], 2, "konumsuz tespit aynı yerdeki konumlu tespiti etkilemez")
        self.assertEqual(len({x["rapor_kimligi"] for x in r}), 3)

    def test_siralama_girdi_sirasindan_bagimsiz(self):
        d = [t(a, n, 1000 + 10 * n + a, konum=(random.Random(a * 31 + n).uniform(0, 6), 0), guven=0.25 + 0.01 * ((a + n) % 70)) for a in (1, 2, 3) for n in range(1, 9)]
        beklenen = birlestir(d, ARALIK)
        for tohum in range(20):
            karisik = list(d)
            random.Random(tohum).shuffle(karisik)
            self.assertEqual(birlestir(karisik, ARALIK), beklenen)

    def test_siralama_anahtari_sim_damga_arac_n(self):
        # aynı sim damgası: araç numarası eşitlik bozucu (sonra n); ilk tespit anahtara göre en küçük
        r = birlestir([t(3, 5, 100, konum=(0, 0)), t(2, 5, 100, konum=(0, 0)), t(1, 5, 100, konum=(0, 0))], ARALIK)
        self.assertEqual(r[0]["ilk_tespit"], {"arac_kimligi": 1, "n": 5, "sim_damga_ns": 100})
        r = birlestir([t(2, 5, 100, konum=(0, 0)), t(1, 9, 100, konum=(0, 0)), t(1, 3, 100, konum=(0, 0))], ARALIK)
        self.assertEqual(r[0]["ilk_tespit"], {"arac_kimligi": 1, "n": 3, "sim_damga_ns": 100})
        r = birlestir([t(1, 1, 200, konum=(0, 0)), t(2, 1, 100, konum=(0, 0))], ARALIK)
        self.assertEqual(r[0]["ilk_tespit"]["arac_kimligi"], 2, "sim damgası (üretim zamanı) önce")

    def test_gecersiz_girdi_acik_hata(self):
        with self.assertRaises(hb.BirlestirmeHatasi):
            birlestir([t(1, 1, 1, guven=float("nan"))], ARALIK)
        with self.assertRaises(hb.BirlestirmeHatasi):
            birlestir([t(1, 1, 1, konum=(float("inf"), 0))], ARALIK)

    def test_sim_damgasi_eksik_veya_gecersiz_hata(self):
        tes = [{"sinif": "insan", "guven": 0.5, "konum": [0, 0]}]
        for kotu in (None, -1, 1.5, True, "5"):
            with self.assertRaises(BirlestirmeHatasi, msg=repr(kotu)):
                hb.tespitleri_hazirla([{"arac": 1, "n": 7, "sim_damga_ns": kotu, "tespitler": tes}])
        with self.assertRaises(BirlestirmeHatasi):
            hb.tespitleri_hazirla([{"arac": 1, "n": 7, "tespitler": tes}])           # alan hiç yok
        self.assertEqual(hb.tespitleri_hazirla([{"arac": 1, "n": 7, "sim_damga_ns": 0, "tespitler": tes}])[0].sim_damga_ns, 0)
        self.assertEqual(hb.tespitleri_hazirla([{"arac": 1, "n": 7, "tespitler": []}]), [], "tespitsiz kareye sim damgası gerekmez")

    def test_rapor_dogrulayicidan_gecer(self):
        d = [t(1, 1, 10, konum=(0, 0), guven=0.4), t(2, 1, 11, konum=(1, 1), guven=0.9), t(3, 4, 12, "enkaz", 0.3, (30, 30)), t(1, 5, 13, konum=None, guven=0.8)]
        r = birlestir(d, ARALIK)
        rapor = hb.nihai_rapor("kosu_x", "sahne_x", "ucta", r)
        self.assertEqual(dogrula_nihai_rapor(C, rapor), [])
        self.assertEqual(dogrula_nihai_rapor(C, hb.nihai_rapor("kosu_x", "sahne_x", "ucta", [])), [], "boş rapor listesi geçerli")

    def test_iki_mod_ayni_rapor(self):
        """Uçta modda DDS ileti biçiminden, merkezi modda kare sonucu kaydından gelen aynı tespitler: iki giriş yolu AYNI raporu üretir."""
        kareler = {(1, 1): [("insan", 0.8, (0.0, 0.0)), ("enkaz", 0.4, None)], (2, 1): [("insan", 0.9, (1.0, 1.0))], (3, 2): []}
        sim = {(1, 1): 500, (2, 1): 500, (3, 2): 1000}
        ucta = [{"arac": a, "n": n, "sim_damga_ns": sim[(a, n)], "tespitler": [{"sinif": s_, "guven": g, "konum": None if k is None else [k[0], k[1]]} for s_, g, k in v]} for (a, n), v in kareler.items()]
        merkezi = [{"arac": a, "n": n, "sim_damga_ns": sim[(a, n)], "tespitler": [{"sinif": s_, "guven": g, "konum": k} for s_, g, k in v]} for (a, n), v in reversed(list(kareler.items()))]
        r1 = birlestir(hb.tespitleri_hazirla(ucta), ARALIK)
        r2 = birlestir(hb.tespitleri_hazirla(merkezi), ARALIK)
        self.assertEqual(r1, r2)
        self.assertEqual(len(r1), 2, "insan (2 tespit, iki araç) + konumsuz enkaz")

    def test_dosya_yazimi(self):
        with tempfile.TemporaryDirectory() as k:
            yol = os.path.join(k, "nihai_rapor.json")
            kayit = [{"arac": 1, "n": 4, "sim_damga_ns": 2000000000, "tespitler": [{"sinif": "insan", "guven": 0.6, "konum": [1.0, 2.0]}]}]
            raporlar, girdi, konumsuz = hb.birlestir_ve_yaz(kayit, ARALIK, yol, "kosu_x", None, "merkezi")
            self.assertEqual((len(raporlar), girdi, konumsuz), (1, 1, 0))
            with open(yol, encoding="utf-8") as f:
                d = json.load(f)
            self.assertIsNone(d["sahne_kimligi"], "sahne tanımsızsa null olduğu gibi taşınır")
            self.assertEqual(dogrula_nihai_rapor(C, d), [])
            self.assertFalse(os.path.exists(yol + ".tmp"))
            self.assertEqual(hb.birlestir_ve_yaz([], ARALIK, None, "k", "s", "ucta"), ([], 0, 0))

    def test_modul_damga_dosyasini_beklemez(self):
        with open(hb.__file__, encoding="utf-8") as f:
            kaynak = f.read()
        for yasak in ("import time", "time.sleep", "uretim_anlari_oku", "UretimBulunamadi", "URETIM_BEKLE_SN"):
            self.assertNotIn(yasak, kaynak, yasak)


if __name__ == "__main__":
    unittest.main()
