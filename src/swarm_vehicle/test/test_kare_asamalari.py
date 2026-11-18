"""Kare aşama damgası doğrulayıcısı (`sozlesme_dogrula.dogrula_kare_asamalari`) birim testleri: sahte koşu klasörleri. Çalıştırma: python3 src/swarm_vehicle/test/test_kare_asamalari.py"""
import json
import os
import sys
import tempfile
import unittest

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(KOK, "araclar"))
import sozlesme_dogrula as sd  # noqa: E402

YARIM = 500_000_000


def ol(kaynak, n, olay, mono, arac=1, **ek):
    d = {"surum": 1, "tur": "kare_olay", "kaynak": kaynak, "arac_kimligi": arac, "n": n, "sim_damga_ns": n * YARIM, "olay": olay, "mono_ns": mono}
    d.update(ek)
    return d


class Kosu:
    """Geçici koşu klasörü: kosu.json (mimari) + kayit/ dosyaları."""

    def __init__(self, test, mimari, n_ilk=20, n_son=22, durumlar=None, gorev_bitis=True):
        self.t = tempfile.TemporaryDirectory()
        test.addCleanup(self.t.cleanup)
        self.kok = self.t.name
        os.makedirs(os.path.join(self.kok, "kayit"))
        with open(os.path.join(self.kok, "kosu.json"), "w", encoding="utf-8") as f:
            json.dump({"mimari_modu": mimari}, f)
        self.dosyalar = {}
        durumlar = durumlar or {n: "tespit_yok" for n in range(n_ilk, n_son + 1)}
        for n, durum in durumlar.items():
            tt = 1_000_000_000 * n
            if durum == "kare_alinamadi":
                self.ekle("kamera_alici_1", ol("kamera_alicisi", n, "kayip_tespit", tt, sonuc_durumu="kare_alinamadi"))
            else:
                self.ekle("gazebo_damga", ol("gazebo_damga", n, "uretim", tt))
                self.ekle("kamera_alici_1", ol("kamera_alicisi", n, "kuyruga_giris", tt + 10))
                self.ekle("kamera_alici_1" if mimari == "ucta" else "yer_istasyonu_kare", ol("kamera_alicisi" if mimari == "ucta" else "yer_istasyonu", n, "aktarim_tamam", "uygulanmaz" if mimari == "ucta" else tt + 20))
                self.ekle("cikarim_iscisi_1", ol("cikarim_iscisi", n, "cikarim_basi", tt + 30))
                self.ekle("cikarim_iscisi_1", ol("cikarim_iscisi", n, "cikarim_sonu", tt + 40))
            self.ekle("yer_istasyonu_kare", ol("yer_istasyonu", n, "kullanilabilir", tt + 50, sonuc_durumu=durum))
        if gorev_bitis:
            self.ekle("yer_istasyonu_gorev", {"surum": 1, "tur": "gorev_olay", "olay": "tarama_bitisi", "arac_kimligi": 1, "n_ilk": n_ilk, "n_son": n_son, "mono_ns": 1})

    def ekle(self, ad, d):
        with open(os.path.join(self.kok, "kayit", ad + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(d) + "\n")

    def dogrula(self):
        return sd.dogrula_kare_asamalari(self.kok, [1])


class AsamaDogrulama(unittest.TestCase):
    def test_gecerli_iki_mod(self):
        for mimari in ("ucta", "merkezi"):
            hatalar, ozet = Kosu(self, mimari).dogrula()
            self.assertEqual(hatalar, [], mimari)
            self.assertEqual(ozet, {1: {"tespit_yok": 3}})

    def test_gecerli_kare_alinamadi_icin_yalniz_kayip_ve_kullanilabilir_gerekir(self):
        hatalar, _ = Kosu(self, "ucta", durumlar={20: "tespit_yok", 21: "kare_alinamadi", 22: "tespit_yok"}).dogrula()
        self.assertEqual(hatalar, [])

    def test_aktarim_tamam_turu_moda_gore(self):
        k = Kosu(self, "merkezi")
        with open(os.path.join(k.kok, "kosu.json"), "w", encoding="utf-8") as f:
            json.dump({"mimari_modu": "ucta"}, f)                     # merkezi kayıtlar, uçta mod iddiası
        h, _ = k.dogrula()
        self.assertTrue(any("uçta modda aktarim_tamam 'uygulanmaz' olmalı" in x for x in h), h)
        k2 = Kosu(self, "ucta")
        with open(os.path.join(k2.kok, "kosu.json"), "w", encoding="utf-8") as f:
            json.dump({"mimari_modu": "merkezi"}, f)
        h, _ = k2.dogrula()
        self.assertTrue(any("merkezi modda aktarim_tamam sayısal olmalı" in x for x in h), h)

    def test_mimari_okunamazsa_hata(self):
        k = Kosu(self, "ucta")
        os.remove(os.path.join(k.kok, "kosu.json"))
        self.assertTrue(any("mimari_modu okunamadı" in x for x in k.dogrula()[0]))

    def test_ikinci_kayit_gizlenmez(self):
        k = Kosu(self, "ucta")
        k.ekle("cikarim_iscisi_1", ol("cikarim_iscisi", 21, "cikarim_sonu", 21_000_000_099))
        h, _ = k.dogrula()
        self.assertTrue(any("araç 1 n 21: 'cikarim_sonu' olayı ikinci kez yazılmış" in x for x in h), h)

    def test_sonucsuz_gorev_karesi(self):
        k = Kosu(self, "ucta", durumlar={20: "tespit_yok", 22: "tespit_yok"}, n_ilk=20, n_son=22)         # 21'in kullanilabilir kaydı yok
        h, _ = k.dogrula()
        self.assertTrue(any("[20, 22] aralığında 'kullanilabilir' kaydı olmayan 1 görev karesi (ilk: [21])" in x for x in h), h)

    def test_eksik_ve_sirasiz_asama(self):
        k = Kosu(self, "ucta", durumlar={20: "tespit_yok"}, n_ilk=20, n_son=20)
        k.ekle("cikarim_iscisi_1", ol("cikarim_iscisi", 99, "cikarim_basi", 5))       # kullanilabilir'i olmayan kayıt hata değildir
        self.assertEqual(k.dogrula()[0], [])
        p = os.path.join(k.kok, "kayit", "cikarim_iscisi_1.jsonl")
        satirlar = [json.loads(x) for x in open(p, encoding="utf-8")]
        satirlar = [d for d in satirlar if d["olay"] != "cikarim_sonu" and d["n"] == 20]
        open(p, "w", encoding="utf-8").write("".join(json.dumps(d) + "\n" for d in satirlar))
        self.assertTrue(any("eksik aşama damgası: cikarim_sonu" in x for x in k.dogrula()[0]))

    def test_alt_sureler_merkezi(self):
        k = Kosu(self, "merkezi", n_ilk=20, n_son=20)
        k.ekle("arac_sureci_1", ol("arac_sureci", 20, "gonderim_kuyrugu", 20_000_000_012))
        k.ekle("arac_sureci_1", ol("arac_sureci", 20, "gonderim", 20_000_000_015))
        s = sd.asama_sureleri(k.kok, [1])[1]
        # kuyruga_giris +10 ns, gonderim_kuyrugu +12, gonderim +15, aktarim_tamam +20 (ns) → ms cinsinden
        self.assertEqual([round(x * 1e6) for x in s["aktarim"]], [10])
        self.assertEqual(([round(x * 1e6) for x in s["aktarim_hazirlik"]], [round(x * 1e6) for x in s["aktarim_gonderim_kuyrugu"]], [round(x * 1e6) for x in s["aktarim_tel"]]), ([2], [3], [5]))


if __name__ == "__main__":
    unittest.main()
