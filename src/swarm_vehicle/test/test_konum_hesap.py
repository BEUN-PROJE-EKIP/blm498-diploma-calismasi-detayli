"""Konum hesaplayıcı birim testleri (ROS 2, MAVSDK ve gz gerekmez). Çalıştırma: python3 src/swarm_vehicle/test/test_konum_hesap.py
Kapsam: düz uçuş, köşe pikselleri (yer izi genişliği), yaw 0/90/180/−90°, yalpa ve yunuslama ±10° (kapalı biçimli beklenen değer), başlangıç ofsetli araçlar, `kesisim_yok`, `poz_yok`,
BAĞIMSIZ ileri izdüşüm (kuaterniyon–vektör çarpımıyla ayrı yazılmış), bozuk kalibrasyon, iki modda kayda bağlama (konum alanı, kare_poz denkliği, kayıp karede bloke olmama)."""
import json
import math
import os
import random
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle.merkezi_mod import goruntu_ileti as gi  # noqa: E402
from swarm_vehicle.cikarim import kare_isleyici as ki  # noqa: E402
from swarm_vehicle.cikarim import kare_sonuc as ks  # noqa: E402
from swarm_vehicle.cikarim import konum_hesap as kh  # noqa: E402
from swarm_vehicle.ucus import poz_tamponu as pt  # noqa: E402
from swarm_vehicle.ucus import rota  # noqa: E402

HAM = rota.deney_env_oku()
KAL = kh.kalibrasyon_oku()
FX = KAL.fx
CAM_Z = KAL.t[2]                    # kameranın gövde üstündeki yüksekliği (kalibrasyon dosyasından)
MS = 10 ** 6


def jsonl_oku(yol):
    with open(yol, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


class Poz:
    def __init__(self, konum, q, gecerli=True):
        self.gecerli, self.konum, self.q = gecerli, konum, q


def q_euler(roll, pitch, yaw):
    """Gövde FRD → NED kuaterniyonu (wxyz), ZYX sırası, derece (pozitif yaw saat yönü, pozitif yunuslama burun yukarı, pozitif yalpa sağ kanat aşağı)."""
    r, p, y = (math.radians(v) / 2 for v in (roll, pitch, yaw))
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return (cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy)


def hesaplayici(baslangic=(0.0, 0.0, 0.0), zemin=0.0):
    return kh.KonumHesaplayici(KAL, baslangic, zemin)


def merkez_kutu(u, v):
    return [u, v, u, v]


class DuzUcus(unittest.TestCase):
    def test_merkez_aracin_tam_alti(self):
        s = hesaplayici().hesapla(merkez_kutu(320, 240), Poz((0.0, 0.0, -30.0), (1.0, 0.0, 0.0, 0.0)))
        self.assertIsNone(s.neden)
        self.assertAlmostEqual(s.konum[0], 0.0, places=9)
        self.assertAlmostEqual(s.konum[1], 0.0, places=9)
        self.assertAlmostEqual(s.mesafe_m, 30.0 + CAM_Z, places=9)

    def test_kutu_merkezi_kullanilir(self):
        h, p = hesaplayici(), Poz((12.0, -7.0, -30.0), (1.0, 0.0, 0.0, 0.0))
        a, b = h.hesapla([100, 50, 300, 150], p), h.hesapla(merkez_kutu(200, 100), p)
        self.assertEqual(a.konum, b.konum)

    def test_kose_pikselleri_yer_izi(self):
        """30 m irtifa, kamera gövdenin CAM_Z üstünde: yarım genişlik = (30 + CAM_Z) · tan(HFOV/2); yükseklik yarısı 240/320 oranında. Kuzeye bakan araç: görüntüde yukarı = kuzey, sağ = doğu."""
        h, p = hesaplayici(), Poz((0.0, 0.0, -30.0), (1.0, 0.0, 0.0, 0.0))
        yari = (30.0 + CAM_Z) * math.tan(math.radians(float(HAM["CAM_HFOV_DEG"])) / 2)
        self.assertAlmostEqual(yari, (30.0 + CAM_Z) * 320 / FX, places=3)
        for (u, v), (e, n) in {(0, 0): (-yari, yari * 0.75), (640, 0): (yari, yari * 0.75), (0, 480): (-yari, -yari * 0.75), (640, 480): (yari, -yari * 0.75),
                               (320, 0): (0, yari * 0.75), (640, 240): (yari, 0)}.items():
            s = h.hesapla(merkez_kutu(u, v), p)
            self.assertAlmostEqual(s.konum[0], e, places=2, msg=(u, v))
            self.assertAlmostEqual(s.konum[1], n, places=2, msg=(u, v))
        self.assertAlmostEqual(2 * yari, 2 * (30.0 + CAM_Z) * math.tan(math.radians(32.5)), places=6)

    def test_yaw_dort_yon(self):
        """Görüntü üstü (v=0) = uçuş yönü, sağ (u=640) = gövdenin sağı. ENU: x = doğu, y = kuzey."""
        yari = (30.0 + CAM_Z) * 320 / FX
        ileri, sag = yari * 0.75, yari
        for yaw in (0, 90, 180, -90, 37.5):
            psi = math.radians(yaw)
            f, r = (math.sin(psi), math.cos(psi)), (math.cos(psi), -math.sin(psi))      # ENU (x, y): ileri ve sağ birim vektörleri
            h, p = hesaplayici(), Poz((0.0, 0.0, -30.0), q_euler(0, 0, yaw))
            for (u, v), (a_ileri, a_sag) in {(320, 0): (ileri, 0), (640, 240): (0, sag), (640, 0): (ileri, sag), (0, 480): (-ileri, -sag)}.items():
                s = h.hesapla(merkez_kutu(u, v), p)
                self.assertAlmostEqual(s.konum[0], a_ileri * f[0] + a_sag * r[0], places=2, msg=(yaw, u, v))
                self.assertAlmostEqual(s.konum[1], a_ileri * f[1] + a_sag * r[1], places=2, msg=(yaw, u, v))

    def test_yunuslama_kapali_bicim(self):
        for pitch in (-10.0, 10.0):
            th = math.radians(pitch)
            H = 30.0 + CAM_Z * math.cos(th)
            beklenen_ileri = -CAM_Z * math.sin(th) + H * math.tan(th)       # kamera ofseti (gövde üstü) ve merkez ışının eğimi
            s = hesaplayici().hesapla(merkez_kutu(320, 240), Poz((0.0, 0.0, -30.0), q_euler(0, pitch, 0)))
            self.assertAlmostEqual(s.konum[1], beklenen_ileri, places=6, msg=pitch)       # kuzeye bakıyor: ileri = kuzey (y)
            self.assertAlmostEqual(s.konum[0], 0.0, places=9)

    def test_yalpa_kapali_bicim(self):
        for roll in (-10.0, 10.0):
            ph = math.radians(roll)
            H = 30.0 + CAM_Z * math.cos(ph)
            # sağ kanat aşağı (pozitif yalpa) → karınlık sola bakar: merkez ışın sola düşer; kamera ofseti: gövde yukarı (FLU z) = FRD −z, yalpada (0, 0, −CAM_Z) → sağ bileşen +CAM_Z·sin(yalpa)
            beklenen_sag = CAM_Z * math.sin(ph) - H * math.tan(ph)
            s = hesaplayici().hesapla(merkez_kutu(320, 240), Poz((0.0, 0.0, -30.0), q_euler(roll, 0, 0)))
            self.assertAlmostEqual(s.konum[0], beklenen_sag, places=6, msg=roll)          # kuzeye bakıyor: sağ = doğu (x)
            self.assertAlmostEqual(s.konum[1], 0.0, places=9)

    def test_baslangic_ofsetli_araclar(self):
        """2. ve 3. araç: NED konumu ev konumuna göredir; ENU konumu başlangıç konumu eklenerek bulunur (x = x0 + doğu, y = y0 + kuzey)."""
        for sira in (1, 2, 3):
            h = kh.KonumHesaplayici.yapilandirmadan(HAM, int(HAM["UAV_SYS_IDS"].split()[sira - 1]))
            x0, y0, z0 = (float(v) for v in HAM["UAV_START_POSES"].split()[sira - 1].split(","))
            s = h.hesapla(merkez_kutu(320, 240), Poz((20.0, 5.0, -30.0), (1.0, 0.0, 0.0, 0.0)))     # kuzey 20, doğu 5, 30 m yukarıda
            self.assertAlmostEqual(s.konum[0], x0 + 5.0, places=6, msg=sira)
            self.assertAlmostEqual(s.konum[1], y0 + 20.0, places=6, msg=sira)
        self.assertEqual(kh.ned_den_enu(20.0, 5.0, -30.0, 3.0, 0.0, 0.0), (8.0, 20.0, 30.0))


class KonumsuzDurumlar(unittest.TestCase):
    def test_isin_yukari_ya_da_paralel(self):
        h = hesaplayici()
        # yalpa 90°: merkez ışın yatay (zemine paralel); 120°: yukarı
        self.assertEqual(h.hesapla(merkez_kutu(320, 240), Poz((0, 0, -30.0), q_euler(90, 0, 0))).neden, kh.NEDEN_KESISIM_YOK)
        self.assertEqual(h.hesapla(merkez_kutu(320, 240), Poz((0, 0, -30.0), q_euler(120, 0, 0))).neden, kh.NEDEN_KESISIM_YOK)
        # ufka yakın piksel: yunuslama 80° iken görüntü üst kenarı ufku geçer
        s = h.hesapla(merkez_kutu(320, 0), Poz((0, 0, -30.0), q_euler(0, 80, 0)))
        self.assertEqual((s.konum, s.neden), (None, kh.NEDEN_KESISIM_YOK))

    def test_kamera_zeminin_altinda(self):
        s = hesaplayici(zemin=50.0).hesapla(merkez_kutu(320, 240), Poz((0, 0, -30.0), (1.0, 0.0, 0.0, 0.0)))
        self.assertEqual(s.neden, kh.NEDEN_KESISIM_YOK)

    def test_poz_yok(self):
        h = hesaplayici()
        for p in (None, Poz(None, None, gecerli=False), Poz((0, 0, -30.0), (1.0, 0, 0, 0), gecerli=False), Poz((0, 0, -30.0), (0.0, 0.0, 0.0, 0.0))):
            s = h.hesapla(merkez_kutu(320, 240), p)
            self.assertEqual((s.konum, s.neden), (None, kh.NEDEN_POZ_YOK), msg=p)

    def test_sonlu_olmayan_kutu(self):
        p = Poz((0, 0, -30.0), (1.0, 0.0, 0.0, 0.0))
        for kutu in ([float("nan"), 0, 1, 1], [0, 0, float("inf"), 1], [1, 2, 3], None):
            self.assertEqual(hesaplayici().hesapla(kutu, p).neden, kh.NEDEN_KESISIM_YOK, msg=kutu)


# --- bağımsız ileri izdüşüm: ayrı yazılmış (kuaterniyon–vektör çarpımı, ters zincir) ----------------------------------------------------------------
def kq_carp(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def kq_dondur(q, v):
    n = math.sqrt(sum(a * a for a in q))
    q = tuple(a / n for a in q)
    s = kq_carp(kq_carp(q, (0.0, *v)), (q[0], -q[1], -q[2], -q[3]))
    return s[1:]


def kq_ters_dondur(q, v):
    return kq_dondur((q[0], -q[1], -q[2], -q[3]), v)


def ileri_izdusum(nokta_enu, konum_ned, q, baslangic):
    """ENU zemin noktası → görüntü pikseli (u, v). Zincir tersine: ENU → NED → gövde FRD → FLU → kamera (R^T) → piksel; kamera gövde konumu t ile ötelenmiştir."""
    x0, y0, z0 = baslangic
    p_ned = (nokta_enu[1] - y0, nokta_enu[0] - x0, -(nokta_enu[2] - z0))
    fark = tuple(a - b for a, b in zip(p_ned, konum_ned))
    p_frd = kq_ters_dondur(q, fark)
    p_flu = (p_frd[0], -p_frd[1], -p_frd[2])
    g = tuple(a - b for a, b in zip(p_flu, KAL.t))
    p_kam = tuple(sum(KAL.R[j][i] * g[j] for j in range(3)) for i in range(3))     # R^T · g
    if p_kam[2] <= 0:
        return None
    return FX * p_kam[0] / p_kam[2] + KAL.cx, KAL.fy * p_kam[1] / p_kam[2] + KAL.cy


class BagimsizIleriIzdusum(unittest.TestCase):
    def test_rastgele_poz_ve_zemin_noktasi(self):
        rng = random.Random(20261117)
        sinanan = 0
        while sinanan < 400:
            sira = rng.choice((1, 2, 3))
            x0, y0, z0 = (float(v) for v in HAM["UAV_START_POSES"].split()[sira - 1].split(","))
            konum = (rng.uniform(-80, 80), rng.uniform(-80, 80), -rng.uniform(5, 60))
            q = q_euler(rng.uniform(-25, 25), rng.uniform(-25, 25), rng.uniform(-180, 180))
            hedef = (x0 + konum[1] + rng.uniform(-15, 15), y0 + konum[0] + rng.uniform(-15, 15), 0.0)
            piksel = ileri_izdusum(hedef, konum, q, (x0, y0, z0))
            if piksel is None or not (0 <= piksel[0] <= 640 and 0 <= piksel[1] <= 480):
                continue
            h = kh.KonumHesaplayici(KAL, (x0, y0, z0), 0.0)
            s = h.hesapla(merkez_kutu(*piksel), Poz(konum, q))
            self.assertIsNone(s.neden)
            self.assertLess(math.hypot(s.konum[0] - hedef[0], s.konum[1] - hedef[1]), 1e-6)
            sinanan += 1

    def test_gazebo_gercek_poz_donusumu(self):
        """FLU/ENU gerçek poz → NED/FRD girdisi: doğuya bakan araç (ENU'da gövde x = doğu) için görüntü üstü doğu yönündedir."""
        konum_ned, q = kh.enu_flu_den_ned_frd((10.0, 20.0, 30.0), (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        self.assertEqual(konum_ned, (20.0, 10.0, -30.0))
        s = hesaplayici().hesapla(merkez_kutu(320, 0), Poz(konum_ned, q))
        yari_ileri = (30.0 + CAM_Z) * 240 / FX
        self.assertAlmostEqual(s.konum[0], 10.0 + yari_ileri, places=6)
        self.assertAlmostEqual(s.konum[1], 20.0, places=6)


class KalibrasyonHatalari(unittest.TestCase):
    def yaz(self, d, icerik):
        yol = os.path.join(d, "kal.json")
        with open(yol, "w", encoding="utf-8") as f:
            f.write(icerik)
        return yol

    def test_okunamaz_ve_bozuk(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(kh.KalibrasyonHatasi):
                kh.kalibrasyon_oku(os.path.join(d, "yok.json"))
            with self.assertRaises(kh.KalibrasyonHatasi):
                kh.kalibrasyon_oku(self.yaz(d, "{bozuk"))
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "config", "kamera_kalibrasyon.json"), encoding="utf-8") as f:
                tam = json.load(f)
            for degistir in (lambda x: x.pop("ic_parametreler"), lambda x: x["ic_parametreler"].update(fx=0), lambda x: x["arac_kamera"].update(R=[[1, 0, 0]]),
                             lambda x: x["arac_kamera"].update(arac_cercevesi="FRD"), lambda x: x.update(tur="baska"), lambda x: x["arac_kamera"].update(t_m=[0, 0, float("nan")])):
                x = json.loads(json.dumps(tam))
                degistir(x)
                with self.assertRaises(kh.KalibrasyonHatasi):
                    kh.kalibrasyon_oku(self.yaz(d, json.dumps(x)))
            self.assertEqual(kh.kalibrasyon_oku(self.yaz(d, json.dumps(tam))).kimlik, tam["kalibrasyon_kimligi"])

    def test_yapilandirma_eksik_anahtar(self):
        ham = dict(HAM)
        del ham["ZEMIN_Z_M"]
        with self.assertRaises(KeyError):
            kh.KonumHesaplayici.yapilandirmadan(ham, 1)


# --- kayda bağlama (KareIsleyici) --------------------------------------------------------------------------------------------------------------
class SahteIstemci:
    def __init__(self, tespitler):
        self.tespitler = tespitler

    def isle(self, n, damga_ns, veri, w, h):
        return {"durum": "tamam", "tespitler": self.tespitler, "basi_ns": 1, "sonu_ns": 2}


def kutu_tespiti(kutu):
    return {"sinif_adi": "insan", "guven": 0.9, "kutu": kutu}


def tampon_dolu(ns_ilk=0, ns_son=20 * 10 ** 9, adim_ms=20, konum_f=None, bekle_sn=0.0):
    b = pt.PozTamponu(100 * MS, bekle_sn, 600)
    t = ns_ilk
    while t <= ns_son:
        b.ekle(t, (0.0, 0.0, -30.0) if konum_f is None else konum_f(t), (1.0, 0.0, 0.0, 0.0))
        t += adim_ms * MS
    return b


class KayitaBaglama(unittest.TestCase):
    def isleyici(self, d, istemci, poz_tamponu=None, **ek):
        yol = os.path.join(d, "kare_poz.jsonl") if poz_tamponu is not None else None
        sonuclar = []
        k = ki.KareIsleyici(HAM, 1, istemci, os.path.join(d, "kare_sonuc.jsonl"), lambda *a, **kv: None, sonuclar.append, poz_tamponu=poz_tamponu, poz_yol=yol,
                            konum_hesaplayici=kh.KonumHesaplayici.yapilandirmadan(HAM, 1), **ek)
        return k, sonuclar

    def test_ucta_konum_kare_pozdan(self):
        with tempfile.TemporaryDirectory() as d:
            k, sonuclar = self.isleyici(d, SahteIstemci([kutu_tespiti([300, 220, 340, 260]), kutu_tespiti([0, 0, 40, 40])]), tampon_dolu())
            k.goruntu(10, 5 * 10 ** 9, 1, b"x", 640, 480)
            t = sonuclar[0]["tespitler"]
            self.assertEqual(len(t), 2)
            self.assertAlmostEqual(t[0]["konum"][0], 0.0, places=6)
            self.assertAlmostEqual(t[0]["konum"][1], 0.0, places=6)
            self.assertIsNone(t[0]["konum_neden"])
            self.assertLess(t[1]["konum"][0], -15.0)
            self.assertFalse(t[0]["aday"])
            self.assertEqual(k.konum_sayac["konumlu"], 2)

    def test_ucta_poz_yok(self):
        with tempfile.TemporaryDirectory() as d:
            b = tampon_dolu(ns_ilk=0, ns_son=2 * 10 ** 9)                  # 5. saniye tampon dışında beklemeden geçersiz: son örnekten sonra, bekle_sn = 0
            k, sonuclar = self.isleyici(d, SahteIstemci([kutu_tespiti([300, 220, 340, 260])]), b)
            k.goruntu(10, 5 * 10 ** 9, 1, b"x", 640, 480)
            t = sonuclar[0]["tespitler"][0]
            self.assertEqual((t["konum"], t["konum_neden"]), (None, "poz_yok"))
            self.assertEqual(k.konum_sayac["poz_yok"], 1)

    def test_kesisim_yok_kaydi(self):
        with tempfile.TemporaryDirectory() as d:
            b = pt.PozTamponu(100 * MS, 0.0, 600)
            for t in range(0, 20 * 10 ** 9, 20 * MS):
                b.ekle(t, (0.0, 0.0, -30.0), q_euler(120, 0, 0))             # kamera yukarı bakıyor
            k, sonuclar = self.isleyici(d, SahteIstemci([kutu_tespiti([300, 220, 340, 260])]), b)
            k.goruntu(10, 5 * 10 ** 9, 1, b"x", 640, 480)
            t = sonuclar[0]["tespitler"][0]
            self.assertEqual((t["konum"], t["konum_neden"]), (None, "kesisim_yok"))

    def test_merkezi_baslik_pozu_ve_kalibrasyon_uyumsuzlugu(self):
        with tempfile.TemporaryDirectory() as d:
            k, sonuclar = self.isleyici(d, SahteIstemci([kutu_tespiti([300, 220, 340, 260])]))
            poz = gi.Poz(True, None, (10.0, 4.0, -30.0), (1.0, 0.0, 0.0, 0.0), 1, 2)
            k.goruntu(10, 5 * 10 ** 9, 1, b"x", 640, 480, merkez_poz=poz)
            k.goruntu(11, 5_500_000_000, 1, b"x", 640, 480, merkez_poz=poz, kalibrasyon_uyumsuz=True)
            k.goruntu(12, 6 * 10 ** 9, 1, b"x", 640, 480, merkez_poz=gi.Poz(False, "bekleme_asildi"))
            a, b, c = (s["tespitler"][0] for s in sonuclar)
            self.assertAlmostEqual(a["konum"][0], 4.0, places=6)
            self.assertAlmostEqual(a["konum"][1], 10.0, places=6)
            self.assertEqual((b["konum"], b["konum_neden"]), (None, "poz_yok"))
            self.assertEqual((c["konum"], c["konum_neden"]), (None, "poz_yok"))
            self.assertEqual(sonuclar[0]["poz"]["konum_ned_m"], [10.0, 4.0, -30.0])

    def test_iki_mod_ayni_pozda_ayni_konum(self):
        with tempfile.TemporaryDirectory() as d:
            b = tampon_dolu(konum_f=lambda t: (t / 1e9, 3.0, -30.0))
            ucta, s1 = self.isleyici(d, SahteIstemci([kutu_tespiti([500, 100, 560, 160])]), b)
            ucta.goruntu(10, 5 * 10 ** 9, 1, b"x", 640, 480)
            kare = pt.kare_poz_kaydi(1, 10, 5 * 10 ** 9, b.sorgula(5 * 10 ** 9))
            with tempfile.TemporaryDirectory() as d2:
                merkezi, s2 = self.isleyici(d2, SahteIstemci([kutu_tespiti([500, 100, 560, 160])]))
                merkezi.goruntu(10, 5 * 10 ** 9, 1, b"x", 640, 480, merkez_poz=gi.Poz(kare["gecerli"], kare["neden"], tuple(kare["konum_ned_m"]), tuple(kare["q_wxyz"]), kare["t1_ns"], kare["t2_ns"]))
            self.assertEqual(s1[0]["tespitler"][0]["konum"], s2[0]["tespitler"][0]["konum"])

    def test_sahte_tespit_anahtari(self):
        with tempfile.TemporaryDirectory() as d:
            k, sonuclar = self.isleyici(d, SahteIstemci([]), tampon_dolu(), sahte_tespit_metni="100,100,140,140;500,300,540,340")
            k.goruntu(10, 5 * 10 ** 9, 1, b"x", 640, 480)
            self.assertEqual([t["kutu"] for t in sonuclar[0]["tespitler"]], [[100.0, 100.0, 140.0, 140.0], [500.0, 300.0, 540.0, 340.0]])
            self.assertEqual(sonuclar[0]["durum"], ks.TESPIT)
        with self.assertRaises(ValueError):
            ki.sahte_tespitleri_ayristir("1,2,3")

    def test_mesaj_has_position(self):
        class Det:
            pass

        kayit = ks.kayit_olustur(1, 10, 5 * 10 ** 9, ks.TESPIT, [{"sinif": "insan", "sinif_no": 0, "guven": 0.9, "kutu": [1.0, 2.0, 3.0, 4.0], "konum": [7.5, -2.5], "konum_neden": None, "aday": False},
                                                                  {"sinif": "insan", "sinif_no": 0, "guven": 0.9, "kutu": [1.0, 2.0, 3.0, 4.0], "konum": None, "konum_neden": "poz_yok", "aday": False}])

        class FR:
            NUMBERING_GRID, STATUS_DETECTIONS, STATUS_NO_DETECTION, STATUS_PROCESSING_ERROR, STATUS_FRAME_NOT_RECEIVED = 1, 1, 2, 3, 4

            def __init__(self):
                self.detections = []

        m = ks.mesaj_olustur(kayit, FR, Det, lambda ns: ns)
        d0, d1 = m.detections
        self.assertEqual((d0.has_position, d0.east, d0.north), (True, 7.5, -2.5))
        self.assertEqual((d1.has_position, d1.east, d1.north), (False, 0.0, 0.0))
        self.assertFalse(d0.candidate)


class KarePozDenkligi(unittest.TestCase):
    def test_poz_istisnasinda_da_kare_poz_yazilir(self):
        class Bozuk:
            bekle_sn = 0.0

            def sorgula(self, t):
                raise RuntimeError("deneme")

        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "kare_poz.jsonl")
            olaylar = []
            k = ki.KareIsleyici(HAM, 1, SahteIstemci([kutu_tespiti([300, 220, 340, 260])]), os.path.join(d, "sonuc.jsonl"), lambda o, **kv: olaylar.append(o), None, poz_tamponu=Bozuk(), poz_yol=yol,
                                konum_hesaplayici=kh.KonumHesaplayici.yapilandirmadan(HAM, 1))
            k.goruntu(10, 5 * 10 ** 9, 1, b"x", 640, 480)
            k.kayip(11, 1)
            k.kayip_bekle(5)
            k.poz_yazici.kapat()
            kayitlar = jsonl_oku(yol)
            sonuclar = jsonl_oku(os.path.join(d, "sonuc.jsonl"))
            self.assertEqual(sorted(r["n"] for r in kayitlar), sorted(r["n"] for r in sonuclar))
            self.assertEqual({(r["gecerli"], r["neden"]) for r in kayitlar}, {(False, "hata")})
            self.assertEqual(sonuclar[0]["tespitler"][0]["konum_neden"], "poz_yok")
            self.assertEqual(sum(1 for o in olaylar if o == "kare_poz_hatasi"), 2)
            self.assertEqual(k.poz_gecersiz, {"hata": 2})


class KayipKareBlokeEtmez(unittest.TestCase):
    def kur(self, d, bekle_sn):
        b = pt.PozTamponu(100 * MS, bekle_sn, 60)
        b.ekle(14 * 10 ** 9, (0, 0, -30.0), (1.0, 0, 0, 0))                    # yalnız bir örnek: sonraki kareler için poz beklenir
        yol = os.path.join(d, "kare_poz.jsonl")
        return b, yol, ki.KareIsleyici(HAM, 1, None, None, lambda *a, **kw: None, None, poz_tamponu=b, poz_yol=yol)

    def test_kayip_poz_beklemesiyle_bloke_olmaz(self):
        with tempfile.TemporaryDirectory() as d:
            b, yol, k = self.kur(d, 0.5)
            t0 = time.monotonic()
            for n in range(40, 44):                                             # ardışık kayıp kareler: her biri kendi bekleme sınırında poz bekler (telemetri durmuş)
                k.kayip(n, 1)
            cagri = time.monotonic() - t0
            self.assertLess(cagri, 0.1, "kayip() poz beklemesiyle bloke oldu")
            self.assertLess(k.kayip_cagri_maks_ms, 50.0)
            self.assertFalse(k.defter.var_mi(43))                                # sonuçlar henüz hazır değil (poz bekleniyor)
            self.assertTrue(k.kayip_bekle(10.0))
            k.poz_yazici.kapat()
            kayitlar = jsonl_oku(yol)
            self.assertEqual([r["n"] for r in kayitlar], [40, 41, 42, 43])      # sıra korunur, her numara bir kez
            self.assertEqual({r["neden"] for r in kayitlar}, {pt.BEKLEME_ASILDI})
            self.assertTrue(all(r["bekleme_ms"] >= 400 for r in kayitlar))      # bekleme ölçüme dahildir ve yazılır
            self.assertEqual(sorted(k.defter.kayitlar), [40, 41, 42, 43])

    def test_ikinci_kayip_ayni_numara_reddedilir(self):
        with tempfile.TemporaryDirectory() as d:
            b, yol, k = self.kur(d, 0.0)
            k.kayip(28, 1)
            k.kayip(28, 2)
            self.assertTrue(k.kayip_bekle(5.0))
            k.poz_yazici.kapat()
            self.assertEqual(len(jsonl_oku(yol)), 1)
            self.assertEqual(k.defter.cift_sayisi, 1)

    def test_kapanis_kayip_kuyrugunu_bekler(self):
        with tempfile.TemporaryDirectory() as d:
            b, yol, k = self.kur(d, 0.3)
            zorla_cagrildi = []

            def zorla():
                for n in (50, 51):
                    k.kayip(n, 1)
                zorla_cagrildi.append(True)
                return [50, 51]
            zamaninda, z, hatali = k.kapanis_tamamla(50, 51, 0.05, zorla)
            self.assertFalse(zamaninda)
            self.assertEqual((z, hatali), ([50, 51], []))                       # kayıp sonuçları beklendi: işlem hatası yazılmadı
            self.assertEqual({r["durum"] for r in k.defter.kayitlar.values()}, {ks.KARE_ALINAMADI})
            self.assertEqual(k.defter.cift_sayisi, 0)

    def test_kapanis_birikmis_kayip_isleri_islem_hatasina_donmez(self):
        """Telemetri durmuşken kapanıştan ÖNCE birikmiş kayıp işler (her biri POZ_BEKLE_SN bekler) kapanışta beklenir: süre bekleyen + zorla + 1 ile hesaplanır."""
        with tempfile.TemporaryDirectory() as d:
            b, yol, k = self.kur(d, 0.5)
            for n in range(60, 68):
                k.kayip(n, 1)                                                   # 8 iş birikti (toplam ≈ 4 sn): eski süre (2 + 1 × 0,6 sn) yetmezdi
            zamaninda, z, hatali = k.kapanis_tamamla(60, 67, 0.05, lambda: [])
            self.assertFalse(zamaninda)
            self.assertEqual((z, hatali), ([], []))
            self.assertEqual({r["durum"] for r in k.defter.kayitlar.values()}, {ks.KARE_ALINAMADI})
            self.assertEqual(len(k.defter.kayitlar), 8)


class SahteTespitIzi(unittest.TestCase):
    """KONUM_TEST_SAHTE açıkken açık günlük satırı ve konum_ozeti sayacı; kapalıyken hiçbiri."""

    def kur(self, d, sahte):
        satirlar = []
        k = ki.KareIsleyici(HAM, 1, SahteIstemci([]), os.path.join(d, "ks.jsonl"), lambda olay, **kv: satirlar.append((olay, kv)), lambda r: None,
                            konum_hesaplayici=kh.KonumHesaplayici.yapilandirmadan(HAM, 1), sahte_tespit_metni=sahte)
        return k, satirlar

    def test_acikken_uyari_ve_sayac(self):
        with tempfile.TemporaryDirectory() as d:
            k, satirlar = self.kur(d, "300,220,340,260;40,40,80,80")
            uyarilar = [kv for olay, kv in satirlar if olay == "test_anahtari_acik"]
            self.assertEqual(len(uyarilar), 1)
            self.assertEqual((uyarilar[0]["seviye"], uyarilar[0]["anahtar"], uyarilar[0]["kutu_sayisi"]), ("(!)", "KONUM_TEST_SAHTE", 2))
            for n in (1, 2, 3):
                k.goruntu(n, n * 5 * 10 ** 8, 1, b"x", 640, 480)
            self.assertEqual(k.konum_ozeti()["sahte_tespit"], 6)

    def test_kapaliyken_iz_yok(self):
        with tempfile.TemporaryDirectory() as d:
            k, satirlar = self.kur(d, "")
            self.assertEqual([olay for olay, kv in satirlar if olay == "test_anahtari_acik"], [])
            k.goruntu(1, 5 * 10 ** 8, 1, b"x", 640, 480)
            self.assertEqual(k.konum_ozeti()["sahte_tespit"], 0)


if __name__ == "__main__":
    unittest.main()
