"""Merkezi mod alıcısı birim testleri (ROS 2 gerekmez; gerçek TCP, yerel döngü). Çalıştırma: python3 src/swarm_gcs/test/test_merkezi_alici.py"""
import os
import socket
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "swarm_vehicle"))
from swarm_gcs.merkezi_alici import MerkeziAlici, okuma_dur_ayristir  # noqa: E402
from swarm_gcs.sonuc_defteri import SonucDefteri  # noqa: E402
from swarm_vehicle import goruntu_ileti as gi  # noqa: E402
from swarm_vehicle import kare_isleyici as ki  # noqa: E402
from swarm_vehicle import rota  # noqa: E402

KAL = "KAL-65-640x480-v1"
W, H = 640, 480
POZ = gi.Poz(True, None, (1.0, 2.0, -30.0), (1.0, 0.0, 0.0, 0.0), 10, 20)
POZ_YOK = gi.Poz(False, "aralik_asildi", None, None, 10, 20_000_000_000)


def goruntu(n, arac=1, dolgu=1):
    return gi.Ileti(gi.TUR_GORUNTU, arac, n, n * 500_000_000, KAL, POZ, bytes([dolgu]) * (W * H * 3))


def kayip(n, arac=1):
    return gi.Ileti(gi.TUR_KARE_ALINAMADI, arac, n, n * 500_000_000, KAL, POZ_YOK, b"")


def bos_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Sahte:
    def __init__(self):
        self.cagrilar = []
        self.n_ilk = None

    def goruntu(self, n, damga, mono, veri, w, h, merkez_poz=None, kalibrasyon_uyumsuz=False):
        self.cagrilar.append(("goruntu", n, damga, len(veri), merkez_poz))
        self.uyumsuz = getattr(self, "uyumsuz", []) + [(n, kalibrasyon_uyumsuz)]

    def kayip(self, n, mono, merkez_poz=None, kalibrasyon_uyumsuz=False):
        self.cagrilar.append(("kayip", n, merkez_poz))
        self.uyumsuz = getattr(self, "uyumsuz", []) + [(n, kalibrasyon_uyumsuz)]


def kur(beklenen_kaynak="127.0.0.1", enj="", islemci=None, **ek):
    ham = dict(rota.deney_env_oku(), GCS_ADDR="127.0.0.1", UAV1_ADDR=beklenen_kaynak, MERKEZI_TCP_PORT_TABAN=str(bos_port()))
    sahte, olaylar, loglar = islemci or Sahte(), [], []
    a = MerkeziAlici(ham, [1], lambda o, **kv: loglar.append((o, kv)), {1: sahte}, olay_yaz=olaylar.append, enjeksiyon_metni=enj, kalibrasyon_kimligi=KAL, port_denetimi=False, **ek)
    a.baslat()
    return a, sahte, olaylar, loglar, int(ham["MERKEZI_TCP_PORT_TABAN"])


def baglan(port):
    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    return c


def bekle(kosul, sn=10):
    sinir = time.monotonic() + sn
    while time.monotonic() < sinir:
        if kosul():
            return True
        time.sleep(0.02)
    return False


class Alici(unittest.TestCase):
    def test_iletiler_islemciye_sirayla_ve_poz_ile_gider(self):
        a, sahte, olaylar, loglar, port = kur()
        self.addCleanup(a.kapat)
        c = baglan(port)
        for il in (goruntu(10), goruntu(11), kayip(12), goruntu(13)):
            c.sendall(gi.kodla(il))
        self.assertTrue(bekle(lambda: len(sahte.cagrilar) == 4))
        self.assertEqual([x[:2] for x in sahte.cagrilar], [("goruntu", 10), ("goruntu", 11), ("kayip", 12), ("goruntu", 13)])
        self.assertEqual(sahte.cagrilar[0][4], POZ)
        self.assertEqual(sahte.cagrilar[2][2], POZ_YOK)
        self.assertEqual([(o["olay"], o["n"], o["kaynak"]) for o in olaylar], [("aktarim_tamam", n, "yer_istasyonu") for n in (10, 11, 12, 13)])
        o = a.ozet()[1]
        self.assertEqual((o["alinan_ileti"], o["goruntu"], o["kare_alinamadi"], o["tekrar"], o["geriye"], o["atlanan"], o["islenen"]), (4, 3, 1, 0, 0, 0, 4))
        self.assertTrue(a.bagli_mi(1))
        c.close()

    def test_isleme_kuyrugu_disk_destekli_ve_tasma_acik_hata(self):
        """B13: işleme kuyruğu diske yazar; taşma (yapay ENOSPC, 3. yazma) kareyi ATMAZ: açık kanal hatası, `kuyruk_tasmasi` günlüğü; önceki kareler işlenir; kalan iletiler okunmaz."""
        with mock.patch.dict(os.environ, {"KUYRUK_TEST_TASMA": "isleme_1:3"}):
            a, sahte, olaylar, loglar, port = kur()
        self.addCleanup(a.kapat)
        self.assertTrue(os.path.isdir(a._kuyruk[1].dizin))
        c = baglan(port)
        for n in (10, 11, 12, 13, 14):
            c.sendall(gi.kodla(goruntu(n)))
        self.assertTrue(bekle(lambda: a.hata_var()))
        self.assertIn("işleme kuyruğu taştı", a.hata_var()[1])
        self.assertTrue(bekle(lambda: len(sahte.cagrilar) == 2))
        time.sleep(0.2)
        self.assertEqual([x[1] for x in sahte.cagrilar], [10, 11], "taşmadan önce kuyruğa alınanlar işlenir; taşan ve sonrası işlenmez")
        o = a.ozet()[1]
        self.assertEqual((o["islem_kuyrugu_tasan"], o["islenen"]), (1, 2))
        # taşma sonrası denklik: çözülen = kuyruğa giren (2) + taşan (1) + bırakılan; bırakılan = aynı okumadan çözülmüş ama kuyruğa alınmamış (okuma sınırına göre 0..2; soketteki okunmamış sayılmaz)
        self.assertEqual(o["alinan_ileti"], 3, "taşan ileti alınmış sayılır")
        self.assertIn(o["birakilan"], (0, 1, 2))
        self.assertLessEqual(o["alinan_ileti"] + o["birakilan"], 5)
        g = [kv for ad, kv in loglar if ad == "kuyruk_tasmasi"]
        self.assertEqual((len(g), g[0]["seviye"], g[0]["kuyruk"], g[0]["n"]), (1, "(-)", "isleme_1", 12))
        self.assertIn("merkezi_kanal_hatasi", [ad for ad, _ in loglar])
        c.close()

    def test_ayni_okumadan_cozulen_iletiler_birakilan_olarak_sayilir(self):
        with mock.patch.dict(os.environ, {"KUYRUK_TEST_TASMA": "isleme_1:2"}):
            a, sahte, olaylar, loglar, port = kur()
        self.addCleanup(a.kapat)
        c = baglan(port)
        c.sendall(b"".join(gi.kodla(kayip(n)) for n in (10, 11, 12, 13, 14)))      # küçük iletiler tek sendall: beşi de aynı okumada çözülür
        self.assertTrue(bekle(lambda: a.hata_var()))
        time.sleep(0.2)
        o = a.ozet()[1]
        self.assertEqual(o["islem_kuyrugu_tasan"], 1)
        self.assertEqual((o["alinan_ileti"], o["birakilan"]), (2, 3), "2. yazma taştı: 1 kuyrukta + 1 taşan; kalan 3 ileti bırakıldı ve sayıldı")
        b = [kv for ad, kv in loglar if ad == "merkezi_kuyruk_tasti_birakilan"]
        self.assertEqual((len(b), int(b[0]["birakilan"])), (1, o["birakilan"]))
        c.close()

    def test_kapanista_kuyruk_bosken_dizin_silinir(self):
        a, sahte, olaylar, loglar, port = kur()
        c = baglan(port)
        c.sendall(gi.kodla(goruntu(10)))
        self.assertTrue(bekle(lambda: len(sahte.cagrilar) == 1))
        dizin = a._kuyruk[1].dizin
        c.close()
        a.kapat()
        self.assertFalse(os.path.exists(dizin), "işleme tamamlandı: kuyruk dizini silinmeli")
        self.assertNotIn("merkezi_kapanis_zaman_asimi", [ad for ad, _ in loglar])

    def test_tekrar_geriye_ve_atlanan_sayilir_islenmez(self):
        a, sahte, olaylar, loglar, port = kur()
        self.addCleanup(a.kapat)
        c = baglan(port)
        for il in (goruntu(20), goruntu(21), goruntu(21), goruntu(19), goruntu(25)):
            c.sendall(gi.kodla(il))
        self.assertTrue(bekle(lambda: a.ozet()[1]["alinan_ileti"] == 5))
        time.sleep(0.2)
        o = a.ozet()[1]
        self.assertEqual((o["tekrar"], o["geriye"], o["atlanan"]), (1, 1, 3))
        self.assertEqual([x[1] for x in sahte.cagrilar], [20, 21, 25])         # tekrar ve geriye giden işlenmez
        adlar = [l[0] for l in loglar]
        self.assertIn("merkezi_tekrar_numara", adlar)
        self.assertIn("merkezi_geriye_giden_numara", adlar)
        self.assertIn("merkezi_atlanan_numara", adlar)                          # sessiz değil
        c.close()

    def test_yanlis_kaynak_adresi_reddedilir(self):
        a, sahte, olaylar, loglar, port = kur(beklenen_kaynak="127.0.0.2")
        self.addCleanup(a.kapat)
        c = baglan(port)
        self.assertTrue(bekle(lambda: a.ozet()[1]["reddedilen_baglanti"] == 1))
        self.assertFalse(a.bagli_mi(1))
        self.assertIn("merkezi_baglanti_reddedildi", [l[0] for l in loglar])
        c.close()

    def test_bozuk_ileti_acik_hata_baglanti_kapanir(self):
        a, sahte, olaylar, loglar, port = kur()
        self.addCleanup(a.kapat)
        c = baglan(port)
        c.sendall(b"XXXX" * 20)                                              # sihirli değeri bozuk akış
        self.assertTrue(bekle(lambda: a.durum[1].hata is not None))
        self.assertIn("sihirli", a.durum[1].hata)
        self.assertFalse(a.bagli_mi(1))
        self.assertEqual(sahte.cagrilar, [])
        self.assertIn("merkezi_kanal_hatasi", [l[0] for l in loglar])
        c.close()

    def test_yanlis_arac_kimligi_acik_hata(self):
        a, sahte, olaylar, loglar, port = kur()
        self.addCleanup(a.kapat)
        c = baglan(port)
        c.sendall(gi.kodla(goruntu(1, arac=2)))
        self.assertTrue(bekle(lambda: a.durum[1].hata is not None))
        self.assertIn("araç kimliği", a.durum[1].hata)
        self.assertFalse(a.bagli_mi(1))
        self.assertEqual(sahte.cagrilar, [])
        c.close()

    def test_yari_ileti_ile_kapanis_acik_hata(self):
        a, sahte, olaylar, loglar, port = kur()
        self.addCleanup(a.kapat)
        c = baglan(port)
        c.sendall(gi.kodla(goruntu(1))[:5000])
        c.close()
        self.assertTrue(bekle(lambda: a.durum[1].hata is not None))
        self.assertIn("yarım", a.durum[1].hata)

    def test_temiz_kapanis_defter_tamam_degilse_acik_hata(self):
        tamam = {"v": False}
        a, sahte, olaylar, loglar, port = kur(defter_tamam=lambda arac: tamam["v"])
        self.addCleanup(a.kapat)
        c = baglan(port)
        for n in (1, 2, 3):
            c.sendall(gi.kodla(goruntu(n)))
        c.close()                                                              # yarım ileti yok: temiz kapanış
        self.assertTrue(bekle(lambda: len(sahte.cagrilar) == 3))
        self.assertTrue(bekle(lambda: a.durum[1].temiz_kapandi))
        self.assertIsNone(a.durum[1].hata)                                     # hata_var çağrılana dek denetim yok
        hatalar = a.hata_var()
        self.assertIn(1, hatalar)
        self.assertIn("tamamlanmadan kapandı", hatalar[1])
        self.assertIn("merkezi_kanal_hatasi", [o for o, _ in loglar])
        self.assertEqual(a.hata_var(), hatalar)                                # ikinci çağrı aynı hata, yeni günlük yok
        self.assertEqual([o for o, _ in loglar].count("merkezi_kanal_hatasi"), 1)

    def test_temiz_kapanis_defter_tamamsa_hata_yok(self):
        a, sahte, olaylar, loglar, port = kur(defter_tamam=lambda arac: True)
        self.addCleanup(a.kapat)
        c = baglan(port)
        c.sendall(gi.kodla(goruntu(1)))
        c.close()
        self.assertTrue(bekle(lambda: a.durum[1].temiz_kapandi and len(sahte.cagrilar) == 1))
        time.sleep(0.3)
        self.assertEqual(a.hata_var(), {})
        self.assertIsNone(a.durum[1].hata)

    def test_temiz_kapanis_islenmemis_iletiler_varken_hata_verilmez(self):
        """Kapanış anında işleme kuyruğunda bekleyen ileti varsa defter henüz tamam olamaz; denetim işleme bitince yapılır."""
        tamam = {"v": False}
        yavas = Sahte()
        orijinal = yavas.goruntu

        def goruntu_yavas(*arg, **kw):
            time.sleep(0.4)
            orijinal(*arg, **kw)
            tamam["v"] = True
        yavas.goruntu = goruntu_yavas
        a, _, olaylar, loglar, port = kur(defter_tamam=lambda arac: tamam["v"], islemci=yavas)
        self.addCleanup(a.kapat)
        c = baglan(port)
        c.sendall(gi.kodla(goruntu(1)))
        c.close()
        self.assertTrue(bekle(lambda: a.durum[1].temiz_kapandi))
        self.assertEqual(a.hata_var(), {})                                     # işlenmekte olan ileti var
        self.assertTrue(bekle(lambda: tamam["v"]))
        time.sleep(0.3)
        self.assertEqual(a.hata_var(), {})                                     # işleme bitti ve defter tamam: normal kapanış

    def test_isleme_kuyrugu_kaydi_tutarli_ve_kapanista_son_kayit(self):
        kayitlar = []
        a, sahte, olaylar, loglar, port = kur(isleme_yaz=lambda arac, d: kayitlar.append(d))
        c = baglan(port)
        for n in (1, 2, 3, 4):
            c.sendall(gi.kodla(goruntu(n)))
        self.assertTrue(bekle(lambda: len(sahte.cagrilar) == 4))
        time.sleep(0.2)
        c.close()
        a.kapat()
        self.assertGreaterEqual(len(kayitlar), 1)
        son = kayitlar[-1]
        self.assertEqual((son["tur"], son["arac_kimligi"], son["giren_ileti"], son["islenen_ileti"], son["ileti"]), ("isleme_kuyrugu", 1, 4, 4, 0))
        for k in kayitlar:
            self.assertEqual(k["ileti"], k["giren_ileti"] - k["islenen_ileti"])
            self.assertEqual(k["surum"], 1)
        self.assertEqual([k["mono_ns"] for k in kayitlar], sorted(k["mono_ns"] for k in kayitlar))

    def test_kalibrasyon_uyusmazligi_sayilir(self):
        a, sahte, olaylar, loglar, port = kur()
        self.addCleanup(a.kapat)
        c = baglan(port)
        il = goruntu(1)
        il.kalibrasyon_kimligi = "BASKA"
        c.sendall(gi.kodla(il))
        self.assertTrue(bekle(lambda: len(sahte.cagrilar) == 1))
        self.assertEqual(a.ozet()[1]["kalibrasyon_uyumsuz"], 1)
        self.assertEqual(sahte.uyumsuz, [(1, True)])                 # işleyiciye bildirilir: o karenin tespitleri konumsuz kalır
        c.close()

    def test_okuma_dur_enjeksiyonu_ayristirma(self):
        self.assertEqual(okuma_dur_ayristir("okuma_dur=5:20"), (5.0, 20.0))
        self.assertIsNone(okuma_dur_ayristir(""))
        with self.assertRaises(ValueError):
            okuma_dur_ayristir("baska=1")


class SahteIstemci:
    """IsciIstemcisi yerine: numaraya göre çıkarım yanıtı."""

    def __init__(self):
        self.n_ilk = None
        self.ham = {}

    def isle(self, n, damga_ns, veri, w, h):
        if n % 4 == 1:
            return {"tur": "sonuc", "n": n, "durum": "hata", "hata": "işçi hatası (enjeksiyon)", "tespitler": [], "basi_ns": None, "sonu_ns": None}
        t = [{"sinif_adi": "person", "guven": 0.9, "kutu": [10, 10, 50, 50]}] if n % 4 == 0 else []
        return {"tur": "sonuc", "n": n, "durum": "tamam", "tespitler": t, "basi_ns": 1, "sonu_ns": 2}


class SonucZinciri(unittest.TestCase):
    def test_dort_durum_defter_ve_poz_kaydi(self):
        """Merkezde sonuç → aynı KareIsleyici/kanca → sonuç defteri: dört durum ayrı ve her numara tam bir sonuç; alınan poz sonuç kaydında."""
        ham = dict(rota.deney_env_oku(), GCS_ADDR="127.0.0.1", UAV1_ADDR="127.0.0.1", MERKEZI_TCP_PORT_TABAN=str(bos_port()))
        defter = SonucDefteri([1])
        defter.aralik_ayarla(1, 20, 23)
        kayitlar = []

        def kanca(k):
            kayitlar.append(k)
            defter.ekle(k["arac_kimligi"], k["n"], k["durum"], time.monotonic_ns())
        isl = ki.KareIsleyici(ham, 1, SahteIstemci(), None, lambda *a, **k: None, kanca)
        a = MerkeziAlici(ham, [1], lambda *x, **k: None, {1: isl}, kalibrasyon_kimligi=KAL, port_denetimi=False)
        a.baslat()
        self.addCleanup(a.kapat)
        c = baglan(a.durum[1].port)
        for il in (goruntu(20), goruntu(21), goruntu(22), kayip(23)):
            c.sendall(gi.kodla(il))
        self.assertTrue(defter.bekle_hepsi_tamam(10))
        durum = {k["n"]: k["durum"] for k in kayitlar}
        self.assertEqual(durum, {20: "tespit", 21: "islem_hatasi", 22: "tespit_yok", 23: "kare_alinamadi"})
        self.assertEqual(defter.sayilar()[1]["durumlar"], {"tespit": 1, "tespit_yok": 1, "islem_hatasi": 1, "kare_alinamadi": 1})
        poz = {k["n"]: k.get("poz") for k in kayitlar}
        self.assertEqual(poz[20], POZ.sozluk())
        self.assertEqual(poz[23]["neden"], "aralik_asildi")
        self.assertIsNone(poz[23]["konum_ned_m"])                                # geçersiz pozda konum yok; yedek kullanılmaz
        self.assertTrue(all(k["tespitler"] == [] for k in kayitlar if k["durum"] != "tespit"))
        self.assertTrue(all(t["konum"] is None and t["konum_neden"] == "poz_yok" and t["aday"] is False for k in kayitlar for t in k["tespitler"]))   # konum hesaplayıcı verilmedi: konumsuz
        self.assertEqual(isl.istemci.n_ilk, 20)                                  # işçi enjeksiyonu için n_ilk = ilk ileti
        c.close()


class PortAraligi(unittest.TestCase):
    def test_aralik_ici_dinleme_portu_acik_hata_soket_acilmaz(self):
        from swarm_vehicle import port_denetimi
        aralik = port_denetimi.gecici_aralik()
        if aralik is None:
            self.skipTest("geçici port aralığı okunamıyor")
        ham = dict(rota.deney_env_oku(), GCS_ADDR="127.0.0.1", UAV1_ADDR="127.0.0.1", MERKEZI_TCP_PORT_TABAN=str(aralik[0] + 10))
        a = MerkeziAlici(ham, [1], lambda *x, **k: None, {1: Sahte()}, kalibrasyon_kimligi=KAL)       # port_denetimi öntanımlı açık
        with self.assertRaises(port_denetimi.PortAraligiHatasi):
            a.baslat()
        self.assertEqual(a._dinle, {})                                  # hiçbir dinleme soketi açılmadı

    def test_aralik_okunamazsa_uyari_gunluge_yazilir_calisma_durmaz(self):
        from unittest import mock

        from swarm_vehicle import port_denetimi
        loglar = []
        ham = dict(rota.deney_env_oku(), GCS_ADDR="127.0.0.1", UAV1_ADDR="127.0.0.1")
        a = MerkeziAlici(ham, [1], lambda o, **kv: loglar.append((o, kv)), {1: Sahte()}, kalibrasyon_kimligi=KAL)
        with mock.patch.object(port_denetimi, "ARALIK_DOSYASI", "/yok/yok/yok"), mock.patch.object(port_denetimi.denetle, "__defaults__", ("/yok/yok/yok", None)):
            a.portlari_denetle()                                         # hata fırlatmaz
        uyarilar = [kv for o, kv in loglar if o == "uyari"]
        self.assertEqual(len(uyarilar), 1)
        self.assertIn("okunamadı", uyarilar[0]["neden"])

    def test_yapilandirmadaki_taban_aralik_disinda_ve_denetim_gecer(self):
        ham = dict(rota.deney_env_oku(), GCS_ADDR="127.0.0.1", UAV1_ADDR="127.0.0.1")
        a = MerkeziAlici(ham, [1], lambda *x, **k: None, {1: Sahte()}, kalibrasyon_kimligi=KAL)
        from swarm_vehicle import port_denetimi
        port_denetimi.denetle(a.durum[1].port, "merkezi mod")


if __name__ == "__main__":
    unittest.main()
