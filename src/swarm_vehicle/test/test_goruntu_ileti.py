"""Merkezi mod görüntü iletisi, gönderim kuyruğu ve göndericisi birim testleri (ROS 2, MAVSDK ve gz gerekmez). Çalıştırma: python3 src/swarm_vehicle/test/test_goruntu_ileti.py"""
import os
import socket
import struct
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle import goruntu_ileti as gi  # noqa: E402
from swarm_vehicle import goruntu_kanali as gk  # noqa: E402
from swarm_vehicle import poz_tamponu as pz  # noqa: E402

W, H = 640, 480
KAL = "KAL-65-640x480-v1"
POZ_GECERLI = gi.Poz(True, None, (1.5, -2.25, -30.0), (0.9, 0.1, 0.2, 0.3), 1_000_000_000, 1_040_000_000)
POZ_GECERSIZ = gi.Poz(False, "aralik_asildi", None, None, 1_000_000_000, 1_250_000_000)


def goruntu(n, poz=POZ_GECERLI, arac=1, dolgu=7):
    return gi.Ileti(gi.TUR_GORUNTU, arac, n, n * 500_000_000, KAL, poz, bytes([(n + dolgu) % 256]) * (W * H * 3))


def kayip(n, poz=POZ_GECERSIZ, arac=1):
    return gi.Ileti(gi.TUR_KARE_ALINAMADI, arac, n, n * 500_000_000, KAL, poz, b"")


class Kodlama(unittest.TestCase):
    def test_gidis_donus_iki_tur_ve_poz_durumlari(self):
        for il in (goruntu(5), goruntu(6, POZ_GECERSIZ), kayip(7), kayip(8, POZ_GECERLI), kayip(9, gi.Poz(False, "tampon_disi")), kayip(10, gi.Poz(False, "bekleme_asildi"))):
            b = gi.kodla(il)
            (c,) = gi.AkisCozucu(beklenen_arac=1).besle(b)
            self.assertEqual((c.tur, c.arac_kimligi, c.n, c.damga_ns, c.kalibrasyon_kimligi, c.kip), (il.tur, il.arac_kimligi, il.n, il.damga_ns, KAL, gi.KIP_IZGARA))
            self.assertEqual(c.yuk, il.yuk)
            self.assertEqual(c.poz, il.poz)
            self.assertEqual(len(b), gi.baslik_boyutu(KAL) + len(il.yuk))

    def test_baslik_boyutlari_ve_monotonik_zaman_yok(self):
        self.assertEqual((gi.B1_BOYUT, gi.B3_BOYUT), (33, 74))
        # iletide üretimin monotonik zamanı taşınmaz [belge]: iki ileti yalnız kodlama anına bağlı değildir (aynı girdi → aynı baytlar)
        a, b = gi.kodla(kayip(3)), gi.kodla(kayip(3))
        time.sleep(0.01)
        self.assertEqual(a, b)
        self.assertEqual(gi.kodla(kayip(3)), a)

    def test_kare_alinamadi_yuk_uzunlugu_sifir(self):
        b = gi.kodla(kayip(4))
        self.assertEqual(struct.unpack_from("<4sBBBIqqIH", b)[7], 0)
        with self.assertRaises(gi.IletiHatasi):
            gi.kodla(gi.Ileti(gi.TUR_KARE_ALINAMADI, 1, 1, 1, KAL, POZ_GECERSIZ, b"x"))

    def test_parcali_okuma_her_sinirdan(self):
        iletiler = [goruntu(20), kayip(21), goruntu(22, POZ_GECERSIZ), kayip(23)]
        akis = b"".join(gi.kodla(i) for i in iletiler)
        for parca in (1, 7, 33, 107, 4096, 100_000, len(akis)):          # bayt bayt ve başlık/yük sınırlarını bölen boyutlar
            c = gi.AkisCozucu(beklenen_arac=1)
            cikti = []
            for k in range(0, len(akis), parca):
                cikti += c.besle(akis[k:k + parca])
            self.assertEqual([(x.tur, x.n, x.yuk == i.yuk, x.poz == i.poz) for x, i in zip(cikti, iletiler)], [(i.tur, i.n, True, True) for i in iletiler], f"parça {parca}")
            self.assertEqual((len(cikti), c.bekleyen_bayt()), (4, 0))

    def test_yari_ileti_bekleyen_bayt(self):
        b = gi.kodla(goruntu(1))
        c = gi.AkisCozucu()
        self.assertEqual(c.besle(b[:1000]), [])
        self.assertEqual(c.bekleyen_bayt(), 1000)


class Hatalar(unittest.TestCase):
    def _bozuk(self, degistir, arac=1, **kw):
        b = bytearray(gi.kodla(goruntu(1)))
        degistir(b)
        with self.assertRaises(gi.IletiHatasi) as e:
            gi.AkisCozucu(beklenen_arac=arac, **kw).besle(bytes(b))
        return str(e.exception)

    def test_yanlis_sihir_surum_arac_tur_kip(self):
        self.assertIn("sihirli", self._bozuk(lambda b: b.__setitem__(slice(0, 4), b"XXXX")))
        self.assertIn("sürüm", self._bozuk(lambda b: b.__setitem__(4, 9)))
        self.assertIn("tür", self._bozuk(lambda b: b.__setitem__(5, 7)))
        self.assertIn("kip", self._bozuk(lambda b: b.__setitem__(6, 2)))
        self.assertIn("araç kimliği", self._bozuk(lambda b: None, arac=2))

    def test_uzunluk_hatalari(self):
        self.assertIn("yük uzunluğu", self._bozuk(lambda b: struct.pack_into("<I", b, 27, 10 ** 9)))
        self.assertIn("yük uzunluğu 0", self._bozuk(lambda b: struct.pack_into("<I", b, 27, 0)))                  # görüntü iletisi yük 0 olamaz
        self.assertIn("kalibrasyon", self._bozuk(lambda b: struct.pack_into("<H", b, 31, 5000)))
        k = bytearray(gi.kodla(kayip(2)))
        struct.pack_into("<I", k, 27, 10)
        with self.assertRaises(gi.IletiHatasi):
            gi.AkisCozucu().besle(bytes(k))

    def test_bozuk_poz_ve_bozuk_akis_sonrasi_kullanilamaz(self):
        self.assertIn("poz", self._bozuk(lambda b: b.__setitem__(33 + len(KAL) + 1, 9)))
        c = gi.AkisCozucu()
        with self.assertRaises(gi.IletiHatasi):
            c.besle(b"YYYY" + b"\0" * 40)
        with self.assertRaises(gi.IletiHatasi):
            c.besle(gi.kodla(kayip(1)))

    def test_gecerli_poz_sonlu_olmalı(self):
        with self.assertRaises(gi.IletiHatasi):
            gi.kodla(goruntu(1, gi.Poz(True, None, (float("nan"), 0, 0), (1, 0, 0, 0))))


class Kuyruk(unittest.TestCase):
    def test_fifo_sayaclar_ve_atma_yok(self):
        k = gk.GonderimKuyrugu()
        for n in range(100):
            k.koy((n, 1, b"x" * 10))
        self.assertEqual(k.derinlik(), (100, 1000))
        sirali = []
        while k.derinlik()[0]:
            sirali.append(k.bak(0.1)[0])
            k.cikar()
        self.assertEqual(sirali, list(range(100)))
        self.assertEqual((k.giren, k.cikan, k.maks_ileti, k.maks_bayt), (100, 100, 100, 1000))

    def test_bos_bekle(self):
        k = gk.GonderimKuyrugu()
        k.koy((1, 1, b"a"))
        self.assertFalse(k.bos_bekle(0.1))
        threading.Timer(0.1, k.cikar).start()
        self.assertTrue(k.bos_bekle(2))


class SahteSorgu:
    """poz_tamponu.PozTamponu yerine: her kareye geçerli ya da (n % 5 == 0 ise) geçersiz poz döner."""

    def sorgula(self, t_ns):
        n = t_ns // 500_000_000
        if n % 5 == 0:
            return pz.PozSonuc(False, pz.BEKLEME_ASILDI, None, None, None, 1.5, None, None)
        return pz.PozSonuc(True, None, t_ns - 10_000_000, t_ns + 10_000_000, 20.0, 0.1, (float(n), 0.0, -30.0), (1.0, 0.0, 0.0, 0.0))


class Gonderici(unittest.TestCase):
    def _sunucu(self, rcvbuf=4096):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s, s.getsockname()[1]

    def test_okuma_durunca_bloke_kuyruk_buyur_sonra_hepsi_sirayla(self):
        sunucu, port = self._sunucu()
        olaylar, loglar = [], []
        kuyruk = gk.GonderimKuyrugu()
        g = gk.Gonderici(1, 2, "127.0.0.1", ("127.0.0.1", port), kuyruk, lambda o, **kv: loglar.append((o, kv)), olay_yaz=olaylar.append, kuyruk_kayit_sn=0.1)
        g.baslat(5)
        istemci, _ = sunucu.accept()
        istemci.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        self.assertTrue(g.bagli_bekle(5))
        u = gk.IletiHazirlayici(1, 2, SahteSorgu(), KAL, kuyruk, lambda *a, **k: None, olay_yaz=olaylar.append)
        # okuma durmuş: 30 ileti (görüntüler ve kare alınamadı karışık, sıralı) üretilir; gönderici bloke olur, kuyruk büyür, hiçbiri atılmaz
        for n in range(30):
            if n % 7 == 3:
                u.kayip(n, 1)
            else:
                u.goruntu(n, n * 500_000_000, 1, bytes([n % 256]) * (W * H * 3), W, H)
        time.sleep(0.6)
        it, by = kuyruk.derinlik()
        self.assertGreater(it, 20)                                             # gönderici soket doluyken bekliyor: kuyruk boşalmadı
        self.assertLess(g.gonderilen, 30)
        # okuma başlar: hepsi sırayla gelir
        cozucu = gi.AkisCozucu(beklenen_arac=1)
        alinan = []
        istemci.settimeout(10)
        sinir = time.monotonic() + 30
        while len(alinan) < 30 and time.monotonic() < sinir:
            alinan += cozucu.besle(istemci.recv(1 << 20))
        self.assertEqual([i.n for i in alinan], list(range(30)))                                              # sıra korunur (kare alınamadı görüntüler arasında yerinde)
        self.assertEqual([i.tur for i in alinan], [gi.TUR_KARE_ALINAMADI if n % 7 == 3 else gi.TUR_GORUNTU for n in range(30)])
        self.assertTrue(all(len(i.yuk) == (0 if i.tur == gi.TUR_KARE_ALINAMADI else W * H * 3) for i in alinan))
        self.assertTrue(g.bosalt_ve_kapat(10))
        c = kuyruk.sayaclar()
        self.assertEqual((c["giren"], c["cikan"], c["bekleyen"]), (30, 30, 0))                                # atılan 0
        self.assertEqual(sum(1 for o in olaylar if o["olay"] == "gonderim"), 30)
        self.assertEqual(sum(1 for o in olaylar if o["olay"] == "gonderim_kuyrugu"), 30)
        istemci.close()
        sunucu.close()

    def test_poz_gecersizse_ileti_geciksiz_bayrakla_gider(self):
        sunucu, port = self._sunucu(65536)
        kuyruk = gk.GonderimKuyrugu()
        g = gk.Gonderici(1, 2, "127.0.0.1", ("127.0.0.1", port), kuyruk, lambda *a, **k: None)
        g.baslat(5)
        istemci, _ = sunucu.accept()
        u = gk.IletiHazirlayici(1, 2, SahteSorgu(), KAL, kuyruk, lambda *a, **k: None)
        u.kayip(5, 1)
        u.goruntu(6, 3_000_000_000, 1, b"\1" * (W * H * 3), W, H)
        cozucu = gi.AkisCozucu()
        istemci.settimeout(5)
        alinan = []
        while len(alinan) < 2:
            alinan += cozucu.besle(istemci.recv(1 << 20))
        self.assertEqual((alinan[0].poz.gecerli, alinan[0].poz.neden), (False, "bekleme_asildi"))
        self.assertEqual((alinan[1].poz.gecerli, alinan[1].poz.konum), (True, (6.0, 0.0, -30.0)))
        self.assertEqual(u.poz_gecersiz, {"bekleme_asildi": 1})
        g.bosalt_ve_kapat(5)
        istemci.close()
        sunucu.close()

    def test_kapanis_idempotent_ikinci_cagri_gunluk_ve_kayit_uretmez_kuyruk_kaydi_sirali(self):
        sunucu, port = self._sunucu(65536)
        kuyruk, loglar, kayitlar = gk.GonderimKuyrugu(), [], []
        g = gk.Gonderici(1, 2, "127.0.0.1", ("127.0.0.1", port), kuyruk, lambda o, **kv: loglar.append(o), kuyruk_yaz=kayitlar.append, kuyruk_kayit_sn=0.01)
        g.baslat(5)
        istemci, _ = sunucu.accept()
        u = gk.IletiHazirlayici(1, 2, SahteSorgu(), KAL, kuyruk, lambda *a, **k: None)
        for n in range(1, 4):
            u.goruntu(n, n * 500_000_000, 1, b"\1" * (W * H * 3), W, H)
        threading.Thread(target=lambda: [None for _ in iter(lambda: istemci.recv(1 << 20), b"")], daemon=True).start()   # alıcı: gelen baytları boşaltır
        time.sleep(0.3)                                                        # periyodik kayıt iş parçacığı çalışsın
        ilk = g.bosalt_ve_kapat(3)
        kayit_sayisi, kapandi = len(kayitlar), loglar.count("goruntu_kanali_kapandi")
        ikinci = g.bosalt_ve_kapat(3)
        self.assertEqual((ilk, ikinci), (True, True))
        self.assertEqual(kapandi, 1)
        self.assertEqual(loglar.count("goruntu_kanali_kapandi"), 1)            # ikinci çağrı günlük üretmez
        self.assertEqual(len(kayitlar), kayit_sayisi)                          # ... ve fazladan kuyruk kaydı yazmaz
        mono = [k["mono_ns"] for k in kayitlar]
        self.assertEqual(mono, sorted(mono))                                   # zaman geriye gitmez (kapanış kaydı sonuncu)
        for alan in ("giren_ileti", "gonderilen_ileti", "gonderilen_bayt"):
            v = [k[alan] for k in kayitlar]
            self.assertEqual(v, sorted(v), alan)
        istemci.close()
        sunucu.close()

    def test_baglanti_kopunca_acik_hata_ve_kalan_sayilir(self):
        sunucu, port = self._sunucu(65536)
        kuyruk = gk.GonderimKuyrugu()
        loglar = []
        g = gk.Gonderici(1, 2, "127.0.0.1", ("127.0.0.1", port), kuyruk, lambda o, **kv: loglar.append(o))
        g.baslat(5)
        istemci, _ = sunucu.accept()
        istemci.close()
        sunucu.close()
        u = gk.IletiHazirlayici(1, 2, SahteSorgu(), KAL, kuyruk, lambda *a, **k: None)
        for n in range(1, 8):
            u.goruntu(n, n * 500_000_000, 1, b"\2" * (W * H * 3), W, H)
            time.sleep(0.05)
        sinir = time.monotonic() + 5
        while g.hata is None and time.monotonic() < sinir:
            time.sleep(0.05)
        self.assertIsNotNone(g.hata)                                           # yeniden bağlanma yok: açık hata
        self.assertIn("goruntu_kanali_hata", loglar)
        self.assertFalse(g.bosalt_ve_kapat(0.2))
        self.assertGreater(kuyruk.derinlik()[0], 0)                            # kalan iletiler sayılıdır, sessizce silinmez

    def test_hazirlayici_istisnasi_acik_hata_bos_ileti_kuyruga_girmez(self):
        class Bozuk:
            def sorgula(self, t_ns):
                raise RuntimeError("poz sorgusu patladı")
        kuyruk = gk.GonderimKuyrugu()
        loglar, bildirimler = [], []
        u = gk.IletiHazirlayici(1, 2, Bozuk(), KAL, kuyruk, lambda o, **kv: loglar.append(o), hata_bildir=bildirimler.append)
        u.goruntu(1, 500_000_000, 1, b"\3" * (W * H * 3), W, H)
        u.goruntu(2, 1_000_000_000, 1, b"\3" * (W * H * 3), W, H)
        u.kayip(3, 1)
        self.assertEqual(kuyruk.derinlik(), (0, 0))                            # hiçbir ileti kuyruğa girmedi
        self.assertIn("poz sorgusu patladı", u.hata)
        self.assertEqual(len(bildirimler), 1)                                  # kanal bir kez açık hatayla durdurulur
        self.assertEqual(loglar.count("hata"), 1)
        self.assertEqual(u.dusen, 2)                                           # hata sonrası gelen kareler sayılır, sessiz değil

    def test_bos_goruntu_yuku_asla_gonderilmez(self):
        kuyruk = gk.GonderimKuyrugu()
        bildirimler = []
        u = gk.IletiHazirlayici(1, 2, SahteSorgu(), KAL, kuyruk, lambda *a, **k: None, hata_bildir=bildirimler.append)
        u.goruntu(1, 500_000_000, 1, b"", W, H)                               # önbellekte bulunamayan görüntü: boş yük
        self.assertEqual(kuyruk.derinlik(), (0, 0))
        self.assertIn("boş yük", u.hata)
        self.assertEqual(len(bildirimler), 1)
        # kare alınamadı iletisinin yükü zaten boştur: hata değildir
        kuyruk2 = gk.GonderimKuyrugu()
        u2 = gk.IletiHazirlayici(1, 2, SahteSorgu(), KAL, kuyruk2, lambda *a, **k: None)
        u2.kayip(1, 1)
        self.assertEqual(kuyruk2.derinlik()[0], 1)
        self.assertIsNone(u2.hata)

    def test_hata_ver_baglantiyi_kapatir_ve_gonderici_durur(self):
        sunucu, port = self._sunucu(65536)
        kuyruk = gk.GonderimKuyrugu()
        loglar = []
        g = gk.Gonderici(1, 2, "127.0.0.1", ("127.0.0.1", port), kuyruk, lambda o, **kv: loglar.append(o))
        g.baslat(5)
        istemci, _ = sunucu.accept()
        istemci.settimeout(5)
        self.assertTrue(g.bagli_bekle(5))
        g.hata_ver("deneme hatası")
        g.hata_ver("ikinci hata")                                              # ilk hata korunur
        self.assertEqual(g.hata, "deneme hatası")
        self.assertEqual(istemci.recv(10), b"")                                # alıcı kapanışı görür
        sinir = time.monotonic() + 5
        while not g.durdu_mu() and time.monotonic() < sinir:
            time.sleep(0.05)
        self.assertTrue(g.durdu_mu())
        self.assertEqual(loglar.count("goruntu_kanali_hata"), 1)
        istemci.close()
        sunucu.close()

    def test_temiz_kapatma_enjeksiyonu_hata_isaretlemez_ama_kanal_kapanir(self):
        sunucu, port = self._sunucu(65536)
        kuyruk = gk.GonderimKuyrugu()
        g = gk.Gonderici(1, 2, "127.0.0.1", ("127.0.0.1", port), kuyruk, lambda *a, **k: None, temiz_kapat_n=2)
        g.baslat(5)
        istemci, _ = sunucu.accept()
        istemci.settimeout(5)
        u = gk.IletiHazirlayici(1, 2, SahteSorgu(), KAL, kuyruk, lambda *a, **k: None)
        for n in (1, 2, 3, 4):
            u.kayip(n, 1)
        alinan = bytearray()
        while True:
            parca = istemci.recv(65536)
            if not parca:
                break
            alinan += parca
        c = gi.AkisCozucu(beklenen_arac=1)
        self.assertEqual([il.n for il in c.besle(bytes(alinan))], [1, 2])      # n=2'den sonra temiz kapanış, yarım ileti yok
        self.assertEqual(c.bekleyen_bayt(), 0)
        self.assertIsNone(g.hata)
        self.assertTrue(g.durdu_mu())
        istemci.close()
        sunucu.close()

    def test_bagli_degilse_zaman_asimi_acik_hata(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                                              # kimse dinlemiyor
        g = gk.Gonderici(1, 2, "127.0.0.1", ("127.0.0.1", port), gk.GonderimKuyrugu(), lambda *a, **k: None)
        g.baslat(1)
        self.assertFalse(g.bagli_bekle(5))
        self.assertIn("bağlanılamadı", g.hata)


if __name__ == "__main__":
    unittest.main()
