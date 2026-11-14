"""Çıkarım işçisi, kare sonucu ve araç süreci yardımcılarının birim testleri (GPU, ROS 2, gz, MAVSDK gerekmez; işçi kanalı testleri `sahte` arka uçla gerçek bir alt süreç başlatır).
Çalıştırma: python3 src/swarm_vehicle/test/test_cikarim.py      Beklenenler elle hesaplanmıştır."""
import os
import re
import socket
import sys
import tempfile
import unittest

PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, PKG)
os.environ["PYTHONPATH"] = os.path.abspath(PKG) + os.pathsep + os.environ.get("PYTHONPATH", "")   # alt süreç işçisi paketi bulsun
from swarm_vehicle import arac  # noqa: E402
from swarm_vehicle import cikarim_istemci as ci  # noqa: E402
from swarm_vehicle import cikarim_yardimci as Y  # noqa: E402
from swarm_vehicle import kare_isleyici as ki  # noqa: E402
from swarm_vehicle import kare_sonuc as ks  # noqa: E402
from swarm_vehicle import rota  # noqa: E402

KOK = rota.KOK
HAM = rota.deney_env_oku()
W, H = int(HAM["CAM_WIDTH"]), int(HAM["CAM_HEIGHT"])
NS = 10 ** 9


def goruntu(ilk_bayt=0):
    return bytes([ilk_bayt]) + bytes(W * H * 3 - 1)


class DortDurum(unittest.TestCase):
    ES = Y.SinifEsleme(["insan", "enkaz"], "person=insan")

    def test_durum_kodlari_mesaj_tanimindan(self):
        """kare_sonuc.DURUM_KODU, FrameResult.msg'deki STATUS_* değerleriyle aynı (mesaj tanımı değişmez; kodlar buradan doğrulanır)."""
        with open(os.path.join(KOK, "src", "swarm_msgs", "msg", "FrameResult.msg"), encoding="utf-8") as f:
            sabitler = {m.group(1): int(m.group(2)) for m in re.finditer(r"^uint8 (STATUS_\w+)=(\d+)", f.read(), re.M)}
        self.assertEqual(ks.DURUM_KODU[ks.TESPIT], sabitler["STATUS_DETECTIONS"])
        self.assertEqual(ks.DURUM_KODU[ks.TESPIT_YOK], sabitler["STATUS_NO_DETECTION"])
        self.assertEqual(ks.DURUM_KODU[ks.ISLEM_HATASI], sabitler["STATUS_PROCESSING_ERROR"])
        self.assertEqual(ks.DURUM_KODU[ks.KARE_ALINAMADI], sabitler["STATUS_FRAME_NOT_RECEIVED"])
        self.assertEqual(len(set(ks.DURUM_KODU.values())), 4)

    def test_tespit_var(self):
        y = {"durum": "tamam", "tespitler": [{"sinif_adi": "person", "guven": 0.9, "kutu": [1, 2, 30, 40]}]}
        d, t, atilan, hata = ks.durum_belirle(y, self.ES)
        self.assertEqual((d, len(t), atilan, hata), (ks.TESPIT, 1, 0, None))
        self.assertEqual((t[0]["sinif"], t[0]["sinif_no"], t[0]["konum"], t[0]["aday"]), ("insan", 0, None, False))

    def test_acik_tespit_yok(self):
        self.assertEqual(ks.durum_belirle({"durum": "tamam", "tespitler": []}, self.ES), (ks.TESPIT_YOK, [], 0, None))

    def test_proje_disi_sinif_atilir_ve_tespit_yok_olur(self):
        y = {"durum": "tamam", "tespitler": [{"sinif_adi": "bus", "guven": 0.9, "kutu": [0, 0, 5, 5]}]}
        self.assertEqual(ks.durum_belirle(y, self.ES), (ks.TESPIT_YOK, [], 1, None))

    def test_islem_hatasi_tespit_yok_degildir(self):
        d, t, _, hata = ks.durum_belirle({"durum": "hata", "hata": "x", "tespitler": []}, self.ES)
        self.assertEqual((d, t, hata), (ks.ISLEM_HATASI, [], "x"))
        self.assertNotEqual(d, ks.TESPIT_YOK)
        for bozuk in (None, {}, {"durum": "belki"}, "x"):
            self.assertEqual(ks.durum_belirle(bozuk, self.ES)[0], ks.ISLEM_HATASI)
        # tespit alanı bozuksa işlem hatası (sessizce "tespit yok" olmaz)
        self.assertEqual(ks.durum_belirle({"durum": "tamam", "tespitler": [{"sinif_adi": "person"}]}, self.ES)[0], ks.ISLEM_HATASI)

    def test_kayit_tutarliligi(self):
        k = ks.kayit_olustur(1, 5, 5 * NS // 2, ks.KARE_ALINAMADI)
        self.assertEqual((k["durum"], k["tespit_sayisi"], k["tespitler"], k["hata"]), ("kare_alinamadi", 0, [], None))     # kare alınamadı tespit taşımaz
        with self.assertRaises(ValueError):
            ks.kayit_olustur(1, 5, 0, ks.ISLEM_HATASI)                     # hata metni zorunlu
        with self.assertRaises(ValueError):
            ks.kayit_olustur(1, 5, 0, ks.TESPIT_YOK, hata="x")             # hata metni yasak
        with self.assertRaises(ValueError):
            ks.kayit_olustur(1, 5, 0, ks.TESPIT)                           # tespit durumu boş listeyle olmaz
        with self.assertRaises(ValueError):
            ks.kayit_olustur(1, 5, 0, ks.TESPIT_YOK, [{"sinif": "insan"}])  # tespit_yok tespit taşımaz
        with self.assertRaises(ValueError):
            ks.kayit_olustur(1, 5, 0, "belki")

    def test_mesaj_olusturma(self):
        class Zaman:
            sec = nanosec = 0

        class Tespit:
            pass

        class FR:
            STATUS_DETECTIONS, STATUS_NO_DETECTION, STATUS_PROCESSING_ERROR, STATUS_FRAME_NOT_RECEIVED = 1, 2, 3, 4
            NUMBERING_GRID = 1

            def __init__(self):
                self.detections = []
        t = [{"sinif": "insan", "sinif_no": 0, "guven": 0.5, "kutu": [1.0, 2.0, 3.0, 4.0], "konum": None, "aday": False}]
        k = ks.kayit_olustur(2, 7, 3_500_000_000, ks.TESPIT, t)
        m = ks.mesaj_olustur(k, FR, Tespit, lambda ns: ns)
        self.assertEqual((m.vehicle_id, m.numbering_mode, m.frame_number, m.sim_stamp, m.status), (2, 1, 7, 3_500_000_000, 1))
        d = m.detections[0]
        self.assertEqual((d.class_id, d.confidence, d.box_x_min, d.box_y_max, d.has_position, d.candidate), (0, 0.5, 1.0, 4.0, False, False))
        m2 = ks.mesaj_olustur(ks.kayit_olustur(2, 8, 4 * NS, ks.ISLEM_HATASI, hata="x"), FR, Tespit, lambda ns: ns)
        self.assertEqual((m2.status, m2.detections), (3, []))


class SinifEslemesi(unittest.TestCase):
    def test_coco_tablosu_ve_proje_modeli(self):
        e = Y.SinifEsleme.yapilandirmadan(HAM)
        self.assertEqual(e.esle("person"), ("insan", 0))
        self.assertIsNone(e.esle("bus"))
        self.assertEqual(e.esle("enkaz"), ("enkaz", 1))        # proje modeli: sınıf adları birebir
        self.assertEqual(e.esle("insan"), ("insan", 0))

    def test_gecersiz_tablo(self):
        with self.assertRaises(ValueError):
            Y.SinifEsleme(["insan", "enkaz"], "person=hayvan")
        self.assertIsNone(Y.SinifEsleme(["insan", "enkaz"], "").esle("person"))


class SonucDefteri(unittest.TestCase):
    def test_her_numara_tam_bir_sonuc(self):
        d = ks.SonucDefteri()
        self.assertTrue(d.ekle(ks.kayit_olustur(1, 20, 0, ks.TESPIT_YOK)))
        self.assertFalse(d.ekle(ks.kayit_olustur(1, 20, 0, ks.KARE_ALINAMADI)))     # ikinci sonuç reddedilir
        self.assertEqual(d.kayitlar[20]["durum"], "tespit_yok")
        self.assertEqual(d.cift_sayisi, 1)
        self.assertEqual(d.eksikler(20, 23), [21, 22, 23])
        for n in (21, 22, 23):
            d.ekle(ks.kayit_olustur(1, n, 0, ks.TESPIT_YOK))
        self.assertEqual(d.eksikler(20, 23), [])
        self.assertTrue(d.bekle_tamam(20, 23, 0.1))
        self.assertFalse(d.bekle_tamam(20, 24, 0.1))
        self.assertEqual(d.durum_sayilari()["tespit_yok"], 4)


class Enjeksiyon(unittest.TestCase):
    def test_belirtecler_bir_kez_tetiklenir(self):
        e = Y.IsciEnjeksiyon("hata=+3;olum=+7,50")
        self.assertTrue(e.acik)
        self.assertEqual([e.karar(n, 20) for n in (22, 23, 23, 27, 27, 50, 50)], [None, "hata", None, "olum", None, "olum", None])
        self.assertFalse(Y.IsciEnjeksiyon("").acik)
        self.assertEqual(Y.IsciEnjeksiyon("").ozet(), "kapali")
        with self.assertRaises(ValueError):
            Y.IsciEnjeksiyon("x=1")


class CpuTopolojisi(unittest.TestCase):
    def _sahte_sysfs(self, eslesmeler):
        d = tempfile.mkdtemp()
        for cpu, sib in eslesmeler.items():
            os.makedirs(os.path.join(d, f"cpu{cpu}", "topology"))
            with open(os.path.join(d, f"cpu{cpu}", "topology", "thread_siblings_list"), "w", encoding="utf-8") as f:
                f.write(sib + "\n")
        os.makedirs(os.path.join(d, "cpufreq"))           # cpu<sayı> olmayan girişler yok sayılır
        return d

    def test_kumeler_ve_atama(self):
        d = self._sahte_sysfs({0: "0,4", 4: "0,4", 1: "1,5", 5: "1,5", 2: "2-3", 3: "2-3"})
        k = Y.cpu_cekirdek_kumeleri(d)
        self.assertEqual(k, [(0, 4), (1, 5), (2, 3)])
        self.assertEqual(Y.cpu_ata(1, k, 2)[0], [0, 4])
        self.assertEqual(Y.cpu_ata(2, k, 2)[0], [1, 5])
        self.assertEqual(Y.cpu_ata(3, k, 2)[0], [2, 3])
        self.assertEqual(Y.cpu_ata(4, k, 2)[0], [])                         # küme kalmadı: sabitleme yok, neden yazılı
        self.assertIn("uygun çekirdek kümesi yok", Y.cpu_ata(4, k, 2)[1])
        # üç araç için çiftler çakışmaz
        ciftler = [set(Y.cpu_ata(i, k, 2)[0]) for i in (1, 2, 3)]
        self.assertFalse(ciftler[0] & ciftler[1] or ciftler[0] & ciftler[2] or ciftler[1] & ciftler[2])
        # izin verilen CPU kümesi dışındaki küme atlanır
        self.assertEqual(Y.cpu_ata(1, k, 2, izinli={1, 5, 2, 3})[0], [1, 5])

    def test_smt_yoksa_ata_yapilamaz(self):
        d = self._sahte_sysfs({0: "0", 1: "1"})
        self.assertEqual(Y.cpu_ata(1, Y.cpu_cekirdek_kumeleri(d), 2)[0], [])

    def test_gercek_topoloji_okunur(self):
        k = Y.cpu_cekirdek_kumeleri()
        self.assertTrue(k and all(len(set(c)) == len(c) for c in k))
        self.assertEqual(len({x for c in k for x in c}), sum(len(c) for c in k))   # bir CPU tek kümede


class Kanal(unittest.TestCase):
    def test_cerceve_gidis_donus(self):
        a, b = socket.socketpair()
        self.addCleanup(b.close)
        veri = bytes(range(256)) * 100
        Y.cerceve_yaz(a, {"tur": "kare", "n": 7, "ş": "ç"}, veri)
        bas, yuk = Y.cerceve_oku(b)
        self.assertEqual((bas, bytes(yuk)), ({"tur": "kare", "n": 7, "ş": "ç"}, veri))
        Y.cerceve_yaz(a, {"tur": "dur"})
        bas, yuk = Y.cerceve_oku(b)
        self.assertEqual((bas["tur"], len(yuk)), ("dur", 0))
        a.close()
        with self.assertRaises(Y.KanalKapandi):
            Y.cerceve_oku(b)

    def test_bozuk_cerceve_reddedilir(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        a.sendall(b"\xff\xff\xff\xff\x00\x00\x00\x00")
        with self.assertRaises(ValueError):
            Y.cerceve_oku(b)


class GzIp(unittest.TestCase):
    def test_tanimsizsa_yerel_yapilir(self):
        e = {}
        arac.gz_ip_ayarla(e)
        self.assertEqual(e["GZ_IP"], "127.0.0.1")

    def test_ayni_deger_kabul(self):
        e = {"GZ_IP": "127.0.0.1"}
        arac.gz_ip_ayarla(e)
        self.assertEqual(e["GZ_IP"], "127.0.0.1")

    def test_baska_deger_acik_hata(self):
        e = {"GZ_IP": HAM["UAV1_ADDR"]}
        with self.assertRaises(ValueError) as c:
            arac.gz_ip_ayarla(e)
        self.assertIn("127.0.0.1", str(c.exception))
        self.assertEqual(e["GZ_IP"], HAM["UAV1_ADDR"])       # değiştirilmedi

    def test_main_baska_degerle_cikis_2(self):
        eski = os.environ.get("GZ_IP")
        os.environ["GZ_IP"] = HAM["UAV1_ADDR"]
        try:
            self.assertEqual(arac.main(["1"]), 2)               # hiçbir şey başlatılmadan
        finally:
            if eski is None:
                os.environ.pop("GZ_IP", None)
            else:
                os.environ["GZ_IP"] = eski


def soket_turleri(pid):
    """İşçinin açık soketlerinin türü: /proc/<pid>/fd'deki socket:[inode] → /proc/net/{unix,tcp,udp,tcp6,udp6,raw} tablosuyla eşleştirme."""
    inode = set()
    for ad in os.listdir(f"/proc/{pid}/fd"):
        try:
            hedef = os.readlink(f"/proc/{pid}/fd/{ad}")
        except OSError:
            continue
        m = re.fullmatch(r"socket:\[(\d+)\]", hedef)
        if m:
            inode.add(m.group(1))
    turler = {}
    for tur in ("unix", "tcp", "udp", "tcp6", "udp6", "raw", "raw6"):
        with open(f"/proc/net/{tur}", encoding="utf-8") as f:
            satirlar = f.read().splitlines()[1:]
        for s in satirlar:
            p = s.split()
            ino = p[6] if tur == "unix" else p[9]
            if ino in inode:
                turler.setdefault(tur, []).append(ino)
    return inode, turler


class IsciIstemcisi(unittest.TestCase):
    """Gerçek alt süreç (sahte arka uç; GPU yok): kanal, durumlar, ölüm, zaman aşımı, yeniden başlatma."""

    def yap(self, **kw):
        ham = dict(HAM, ISCI_CPU_SABITLE="0", ISCI_HAZIR_SN="60")
        ham.update(kw.pop("ham", {}))
        gunluk = []
        i = ci.IsciIstemcisi(ham, 1, int(HAM["UAV_SYS_IDS"].split()[0]), None, lambda o, **v: gunluk.append((o, v)), arka_uc="sahte", **kw)
        i.gunluk = gunluk
        self.addCleanup(i.kapat)
        return i

    def test_hazir_ve_kanal_ip_kullanmaz(self):
        i = self.yap(enjeksiyon_metni="")
        i.baslat()
        b = i.hazir_bekle()
        self.assertIsNotNone(b)
        self.assertEqual((b["arka_uc"], b["rclpy_yuklu"]), ("sahte", False))      # işçide rclpy içe aktarılmadı
        inode, turler = soket_turleri(b["pid"])
        self.assertTrue(inode)                                                     # kanal soketi var
        self.assertEqual(sorted(turler), ["unix"], f"işçide unix dışı soket: {turler}")      # TCP/UDP yok
        self.assertNotEqual(b["pid"], os.getpid())

    def test_uc_sonuc_turu(self):
        i = self.yap(enjeksiyon_metni="")
        i.baslat()
        y = i.isle(20, 10 * NS, goruntu(255), W, H)                                # tespit
        self.assertEqual((y["durum"], len(y["tespitler"]), y["n"]), ("tamam", 1, 20))
        self.assertGreaterEqual(y["sonu_ns"], y["basi_ns"])
        y = i.isle(21, 11 * NS, goruntu(0), W, H)                                  # açık tespit yok
        self.assertEqual((y["durum"], y["tespitler"]), ("tamam", []))
        y = i.isle(22, 12 * NS, goruntu(253), W, H)                                # işçi hatası (işçi yaşar)
        self.assertEqual(y["durum"], "hata")
        self.assertIn("sahte arka uç hatası", y["hata"])
        self.assertEqual(i.yeniden, 0)
        y = i.isle(23, 13 * NS, goruntu(0), W, H)                                  # işçi hata sonrası çalışıyor
        self.assertEqual(y["durum"], "tamam")

    def test_bozuk_goruntu_islem_hatasi(self):
        i = self.yap(enjeksiyon_metni="")
        i.baslat()
        y = i.isle(20, 10 * NS, bytes(1000), W, H)                                 # yük uzunluğu başlıkla uyumsuz
        self.assertEqual(y["durum"], "hata")
        self.assertIn("bozuk", y["hata"])
        y = i.isle(21, 11 * NS, bytes(100 * 100 * 3), 100, 100)                    # beklenmeyen boyut
        self.assertEqual(y["durum"], "hata")
        es = Y.SinifEsleme.yapilandirmadan(HAM)
        self.assertEqual(ks.durum_belirle(y, es)[0], ks.ISLEM_HATASI)              # "tespit yok" DEĞİL
        self.assertEqual(i.isle(22, 12 * NS, goruntu(0), W, H)["durum"], "tamam")

    def test_hata_enjeksiyonu(self):
        i = self.yap(enjeksiyon_metni="hata=+2")
        i.n_ilk = 20
        i.baslat()
        self.assertEqual([i.isle(n, n * NS // 2, goruntu(0), W, H)["durum"] for n in (20, 21, 22, 23)], ["tamam", "tamam", "hata", "tamam"])
        self.assertEqual(i.yeniden, 0)

    def test_olum_enjeksiyonu_sonra_yeniden_baslatma(self):
        i = self.yap(enjeksiyon_metni="olum=+1")
        i.n_ilk = 20
        i.baslat()
        pid1 = i.hazir_bekle()["pid"]
        self.assertEqual(i.isle(20, 10 * NS, goruntu(0), W, H)["durum"], "tamam")
        y = i.isle(21, 21 * NS // 2, goruntu(255), W, H)            # işçi bu kareyi alınca ölür
        self.assertEqual(y["durum"], "hata")
        self.assertIn("öldü", y["hata"])
        self.assertEqual(i.yeniden, 1)
        y = i.isle(22, 12 * NS, goruntu(255), W, H)                                # yeni işçi hazır olunca sıradaki kare işlenir (atılmaz)
        self.assertEqual((y["durum"], len(y["tespitler"])), ("tamam", 1))
        self.assertNotEqual(i.bilgi["pid"], pid1)
        self.assertEqual(i.baslatma, 2)
        self.assertTrue(any(o == "isci_yeniden_baslatiliyor" for o, _ in i.gunluk))

    def test_zaman_asimi(self):
        i = self.yap(enjeksiyon_metni="", kare_zaman_asimi_sn=1.0)
        i.baslat()
        y = i.isle(20, 10 * NS, goruntu(254), W, H)                                # arka uç 600 sn uyur
        self.assertEqual(y["durum"], "hata")
        self.assertIn("zaman aşımı", y["hata"])
        self.assertEqual(i.isle(21, 11 * NS, goruntu(0), W, H)["durum"], "tamam")  # yeniden başlatılan işçi
        self.assertEqual(i.yeniden, 1)

    def test_yeniden_baslatma_siniri(self):
        i = self.yap(enjeksiyon_metni="olum=20,21,22", ham={"ISCI_YENIDEN_BASLAT_MAKS": "1"})
        i.baslat()
        d = [i.isle(n, n * NS // 2, goruntu(0), W, H) for n in (20, 21, 22, 23)]
        self.assertEqual([x["durum"] for x in d], ["hata", "hata", "hata", "hata"])        # 20: öldü (yeniden 1), 21: öldü (sınır), 22/23: kalıcı hata
        self.assertIn("sınırı aşıldı", d[3]["hata"])
        self.assertEqual(i.baslatma, 2)

    def test_model_yuklenemezse_kalici_hata(self):
        """İşçi yapılandırmayı kendisi okur (DENEY_ENV): ağırlık dosyası yoksa indirme DENENMEZ, işçi `hazir_degil` bildirir ve araç HAZIR'a geçemez."""
        with open(os.path.join(KOK, "config", "deney.env"), encoding="utf-8") as f:
            metin = f.read()
        gecici = tempfile.mkdtemp()
        yol = os.path.join(gecici, "deney.env")
        with open(yol, "w", encoding="utf-8") as f:
            f.write(re.sub(r'^INF_GPU_MODEL=.*$', 'INF_GPU_MODEL=".generated/models/yok.pt"', metin, flags=re.M))
        eski = os.environ.get("DENEY_ENV")
        os.environ["DENEY_ENV"] = yol
        self.addCleanup(lambda: os.environ.pop("DENEY_ENV", None) if eski is None else os.environ.__setitem__("DENEY_ENV", eski))
        i = self.yap(enjeksiyon_metni="")
        i.arka_uc = "gpu"
        i.baslat()
        self.assertIsNone(i.hazir_bekle(60))
        self.assertIn("model ağırlığı yok", i.kalici_hata)
        y = i.isle(20, 10 * NS, goruntu(0), W, H)                                  # kalıcı hata: kare işlem hatası, "tespit yok" değil
        self.assertEqual(y["durum"], "hata")


class KareIsleyiciTesti(unittest.TestCase):
    def test_her_numara_tam_bir_sonuc_ve_dort_durum(self):
        i = ci.IsciIstemcisi(dict(HAM, ISCI_CPU_SABITLE="0"), 1, 1, None, lambda *a, **k: None, arka_uc="sahte", enjeksiyon_metni="hata=+2")
        i.n_ilk = 20
        self.addCleanup(i.kapat)
        i.baslat()
        kancadan = []
        k = ki.KareIsleyici(HAM, 1, i, None, lambda *a, **kw: None, kancadan.append)
        k.goruntu(20, 10 * NS, 1, goruntu(255), W, H)        # tespit
        k.goruntu(21, 21 * NS // 2, 1, goruntu(0), W, H)   # açık tespit yok
        k.goruntu(22, 11 * NS, 1, goruntu(0), W, H)          # enjeksiyonla işçi hatası
        k.kayip(23, 1)                                       # alıcı kaybı
        d = k.defter
        self.assertEqual([d.kayitlar[n]["durum"] for n in (20, 21, 22, 23)], ["tespit", "tespit_yok", "islem_hatasi", "kare_alinamadi"])
        self.assertEqual([r["n"] for r in kancadan], [20, 21, 22, 23])           # kanca her sonuç için bir kez
        self.assertEqual(d.kayitlar[23]["sim_damga_ns"], 23 * NS // 2)
        self.assertEqual((d.kayitlar[23]["tespitler"], d.kayitlar[22]["tespitler"]), ([], []))
        self.assertEqual(d.eksikler(20, 23), [])
        k.kayip(22, 2)                                       # aynı numaraya ikinci sonuç yazılamaz
        self.assertEqual(d.cift_sayisi, 1)
        self.assertEqual(d.kayitlar[22]["durum"], "islem_hatasi")

    def test_kapanista_kalan_numaralar_islem_hatasi(self):
        i = ci.IsciIstemcisi(dict(HAM, ISCI_CPU_SABITLE="0"), 1, 1, None, lambda *a, **k: None, arka_uc="sahte")
        k = ki.KareIsleyici(HAM, 1, i, None, lambda *a, **kw: None)
        k.kayip(20, 1)
        zorlandi = []
        zamaninda, zorla, hatali = k.kapanis_tamamla(20, 22, 0.2, lambda: zorlandi.append(1) or [])
        self.assertFalse(zamaninda)
        self.assertEqual((zorla, hatali, len(zorlandi)), ([], [21, 22], 1))
        self.assertEqual([k.defter.kayitlar[n]["durum"] for n in (20, 21, 22)], ["kare_alinamadi", "islem_hatasi", "islem_hatasi"])    # asla "tespit yok" değil
        self.assertEqual(k.defter.eksikler(20, 22), [])

    def test_kapanis_son_kancayi_bekler(self):
        """Son sonucun kancası yavaşken kapanış dönmeden önce kanca tamamlanmış olmalı (kapanışta ileti sayacı tam)."""
        import threading
        import time
        i = ci.IsciIstemcisi(dict(HAM, ISCI_CPU_SABITLE="0"), 1, 1, None, lambda *a, **k: None, arka_uc="sahte")
        sayac = []

        def yavas_kanca(kayit):
            time.sleep(0.5)                       # defter.ekle'den SONRA, kanca bitmeden bekleyici uyanabilir
            sayac.append(kayit["n"])
        k = ki.KareIsleyici(HAM, 1, i, None, lambda *a, **kw: None, yavas_kanca)
        k.kayip(20, 1)
        k.kayip(21, 1)
        t = threading.Thread(target=k.kayip, args=(22, 1))
        t.start()
        zamaninda, zorla, hatali = k.kapanis_tamamla(20, 22, 5.0, lambda: [])
        self.assertTrue(zamaninda)
        self.assertEqual(sorted(sayac), [20, 21, 22])          # dönüşte üç kanca da bitmiş
        t.join()


class DosyaKurallari(unittest.TestCase):
    def test_isci_modulu_rclpy_ice_aktarmaz(self):
        for ad in ("cikarim_isci.py", "cikarim_istemci.py", "cikarim_yardimci.py", "kare_sonuc.py", "kare_isleyici.py"):
            with open(os.path.join(PKG, "swarm_vehicle", ad), encoding="utf-8") as f:
                kod = f.read()
            self.assertIsNone(re.search(r"^\s*(import|from)\s+(rclpy|rcl_interfaces|swarm_msgs|gz|mavsdk)\b", kod, re.M), ad)

    def test_saf_moduller_agir_kitaplik_olmadan_yuklenir(self):
        import subprocess
        kod = ("import sys; sys.path.insert(0, sys.argv[1]); "
               "from swarm_vehicle import cikarim_yardimci, cikarim_istemci, cikarim_isci, kare_sonuc, kare_isleyici; "
               "agir = {'rclpy', 'gz', 'mavsdk', 'torch', 'numpy', 'ultralytics', 'onnxruntime', 'cv2'} & set(sys.modules); "
               "sys.exit(1 if agir else 0)")
        r = subprocess.run([sys.executable, "-I", "-c", kod, os.path.abspath(PKG)], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
