#!/usr/bin/env python3
"""Alan pilotu koşusunun çözümlemesi (ölçüm yardımcısı): süre/uzunluk/RTF, yönelim (yaw, uçuş yönü), kapsama, bölge taşması, kare sonucu bütünlüğü.

Kullanım:  python araclar/alan_pilot_analiz.py <koşu_klasörü> --arac N [--cikti <md_yolu>]
Girdi: koşu klasöründeki araç günlükleri, kayit/*.jsonl (kare_sonuc, kamera_alici, gazebo_damga), koordinator kaydı (koordinator_deneme.jsonl ya da asıl koordinatörün yer_istasyonu_gorev.jsonl), alan_pilot_olcum.jsonl
(gözlemci: Gazebo model pozları + PX4 yönelim/konum/hız; araclar/alan_pilot_olcum.py), config/bolge_rota.json, config/kamera_kalibrasyon.json.
Çıktı: önce "SONUC <gecti|kaldi> <ad> | <ayrıntı>" satırları (M1 kapısı denetimleri; kaldı varsa çıkış 1), sonra ölçüm tabloları (Markdown). Ayrıca koşu klasörüne
`analiz/kare_yonelim_<araç>.csv` (her görev karesi için Gazebo/PX4 yönelimi) yazılır. Eşik konmaz: yönelim ve kapsama sayıları RAPORLANIR, geçti/kaldı ölçütü değildir.
Kurallar: numpy gerekir (venv). Gazebo pozu = gerçek değer (dünya çerçevesi ENU, gövde FLU); PX4 yönelimi FRD→NED kuaterniyonundan ENU/FLU'ya çevrilir.
Kamera: kalibrasyon dosyasındaki R (gövde FLU → kamera OpenCV), fx, fy, cx, cy, t_m (gövde çerçevesinde kamera konumu, m); zemin z = 0 düzlemi (dünya zemini).
Çıkış: 0 tamam, 1 SONUC kaldi, 2 kullanım/okuma hatası.
"""
import csv
import json
import math
import os
import sys

import numpy as np

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

import arac_sureci_analiz as asa  # noqa: E402
from swarm_vehicle.ucus import rota as rota_mod  # noqa: E402

NS = 10 ** 9
KALDI = 0
CIKTI = []


def sonuc(gecti, ad, ayrinti):
    global KALDI
    if not gecti:
        KALDI += 1
    print(f"SONUC {'gecti' if gecti else 'kaldi'} {ad} | {ayrinti}", flush=True)


def yaz(s=""):
    CIKTI.append(s)


def jsonl(yol):
    with open(yol, encoding="utf-8") as f:
        return [json.loads(s) for s in f if s.strip()]


# --- dönüşümler ---------------------------------------------------------------------------------------------------------------------------
def kuat_mat(q):
    """q: (N,4) [w,x,y,z] → (N,3,3) dönme matrisi."""
    q = np.asarray(q, float)
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    m = np.empty((len(q), 3, 3))
    m[:, 0, 0], m[:, 0, 1], m[:, 0, 2] = 1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)
    m[:, 1, 0], m[:, 1, 1], m[:, 1, 2] = 2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)
    m[:, 2, 0], m[:, 2, 1], m[:, 2, 2] = 2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)
    return m


_T_NED_ENU = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1.0]])
_F_FLU_FRD = np.diag([1.0, -1.0, -1.0])


def px4_mat_enu_flu(q):
    """PX4 kuaterniyonu (FRD→NED) → gövde FLU'dan dünya ENU'ya dönme matrisi."""
    return _T_NED_ENU @ kuat_mat(q) @ _F_FLU_FRD


def kuat_interp(t, tt, qq):
    """Zaman dizisi tt'deki kuaterniyonlar qq (N,4); t anlarında normalize doğrusal ara değer (işaret sürekliliği korunur)."""
    q = qq.copy()
    for i in range(1, len(q)):
        if np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    c = np.stack([np.interp(t, tt, q[:, k]) for k in range(4)], axis=1)
    return c / np.linalg.norm(c, axis=1, keepdims=True)


def derece(r):
    return np.degrees(r)


def sar(a):
    """Açıyı (derece) (-180, 180] aralığına sarar."""
    return (np.asarray(a, float) + 180.0) % 360.0 - 180.0


def dairesel_ort_std(a_derece):
    """Dairesel ortalama ve standart sapma (derece)."""
    a = np.radians(np.asarray(a_derece, float))
    if len(a) == 0:
        return float("nan"), float("nan")
    c, s = np.mean(np.cos(a)), np.mean(np.sin(a))
    r = math.hypot(c, s)
    return math.degrees(math.atan2(s, c)), math.degrees(math.sqrt(-2 * math.log(max(r, 1e-12))))


def yatay_az(v):
    """(N,3) vektörün yatay izdüşümünün azimutu (ENU, doğudan saat yönünün tersine, derece)."""
    return derece(np.arctan2(v[:, 1], v[:, 0]))


class Kamera:
    def __init__(self, yol):
        with open(yol, encoding="utf-8") as f:
            k = json.load(f)
        ic = k["ic_parametreler"]
        self.fx, self.fy, self.cx, self.cy = ic["fx"], ic["fy"], ic["cx"], ic["cy"]
        self.w, self.h = k["cozunurluk"]["genislik_px"], k["cozunurluk"]["yukseklik_px"]
        self.R = np.array(k["arac_kamera"]["R"], float)             # gövde → kamera
        self.t = np.array(k["arac_kamera"]["t_m"], float)           # gövde çerçevesinde kamera konumu
        u = np.array([[0, 0], [self.w, 0], [self.w, self.h], [0, self.h]], float)
        self.isinlar = np.stack([(u[:, 0] - self.cx) / self.fx, (u[:, 1] - self.cy) / self.fy, np.ones(4)], axis=1)   # (4,3) kamera çerçevesi

    def x_ekseni(self, Rwb):
        """Görüntü yatay ekseninin (kameranın x'i) dünya çerçevesindeki birim vektörü: (N,3)."""
        return Rwb @ self.R[0, :]

    def iz(self, p, Rwb):
        """Yer izi: dört köşe (N,4,2) dünya x,y; ışın zemini kesmiyorsa NaN."""
        yon = np.einsum("nij,jk,lk->nli", Rwb, self.R.T, self.isinlar)          # (N,4,3) dünya yönleri
        orig = p + np.einsum("nij,j->ni", Rwb, self.t)
        s = -orig[:, 2][:, None] / yon[:, :, 2]
        s = np.where(s > 0, s, np.nan)
        return orig[:, None, :2] + s[:, :, None] * yon[:, :, :2]


# --- kapsama --------------------------------------------------------------------------------------------------------------------------
class Izgara:
    def __init__(self, bolge, res):
        self.res = res
        self.x0, self.y0 = bolge["x_min"], bolge["y_min"]
        self.nx, self.ny = int(round((bolge["x_max"] - bolge["x_min"]) / res)), int(round((bolge["y_max"] - bolge["y_min"]) / res))
        self.gx = self.x0 + res * (np.arange(self.nx) + 0.5)
        self.gy = self.y0 + res * (np.arange(self.ny) + 0.5)

    def isle(self, kose, kapsa):
        """Dört köşeli dışbükey iz kapsa (ny,nx) bool dizisine işlenir."""
        if not np.all(np.isfinite(kose)):
            return
        i0 = max(int(math.floor((kose[:, 0].min() - self.x0) / self.res)), 0)
        i1 = min(int(math.ceil((kose[:, 0].max() - self.x0) / self.res)), self.nx)
        j0 = max(int(math.floor((kose[:, 1].min() - self.y0) / self.res)), 0)
        j1 = min(int(math.ceil((kose[:, 1].max() - self.y0) / self.res)), self.ny)
        if i1 <= i0 or j1 <= j0:
            return
        X, Y = np.meshgrid(self.gx[i0:i1], self.gy[j0:j1])
        isaret = None
        ic = np.ones(X.shape, bool)
        c = kose
        # yönlü alan: köşe sırası saat yönünde ya da tersi olabilir; kenar çarpımlarının hepsi aynı işarette olmalı
        alan = 0.0
        for k in range(4):
            a, b = c[k], c[(k + 1) % 4]
            alan += a[0] * b[1] - b[0] * a[1]
        isaret = 1.0 if alan > 0 else -1.0
        for k in range(4):
            a, b = c[k], c[(k + 1) % 4]
            cap = (b[0] - a[0]) * (Y - a[1]) - (b[1] - a[1]) * (X - a[0])
            ic &= (isaret * cap) >= -1e-9
        kapsa[j0:j1, i0:i1] |= ic


def kapsama_bolge(bolge, izler, kenar_pay, res=1.0):
    """izler: dört köşe dizileri (K,4,2). Dönen: (kapsa bool dizisi, Izgara)."""
    g = Izgara(bolge, res)
    kapsa = np.zeros((g.ny, g.nx), bool)
    for k in izler:
        g.isle(k, kapsa)
    return kapsa, g


def kapsama_ozeti(bolge, kapsa, g, kenar_pay, alan):
    """Boşluk oranları: bölge toplamı, iç bölge, alan dış sınırından ≤ kenar_pay bandı, bölgeler arası sınırdan ≤ kenar_pay bandı."""
    X, Y = np.meshgrid(g.gx, g.gy)
    ax0, ax1 = alan["merkez_m"][0] - alan["genislik_m"] / 2, alan["merkez_m"][0] + alan["genislik_m"] / 2
    ay0, ay1 = alan["merkez_m"][1] - alan["yukseklik_m"] / 2, alan["merkez_m"][1] + alan["yukseklik_m"] / 2
    dis = (X - bolge["x_min"] < kenar_pay) & (bolge["x_min"] <= ax0 + 1e-9) | (bolge["x_max"] - X < kenar_pay) & (bolge["x_max"] >= ax1 - 1e-9) \
        | (Y - bolge["y_min"] < kenar_pay) | (bolge["y_max"] - Y < kenar_pay)
    ic_sinir = (X - bolge["x_min"] < kenar_pay) & (bolge["x_min"] > ax0 + 1e-9) | (bolge["x_max"] - X < kenar_pay) & (bolge["x_max"] < ax1 - 1e-9)
    band = dis | ic_sinir
    bos = ~kapsa

    def oran(maske):
        n = int(maske.sum())
        return (100.0 * int((bos & maske).sum()) / n if n else float("nan")), int((bos & maske).sum()), n
    return {"bolge": oran(np.ones_like(bos)), "ic": oran(~band), "dis_band": oran(dis), "ic_band": oran(ic_sinir & ~dis), "dis_bos_konum": (X[bos & dis], Y[bos & dis])}


def ortusme_satirlari(bolge, rota_noktalari, serit_izleri, res, y_alt, y_ust):
    """Komşu tarama doğrularının gerçekleşen örtüşmesi (m): y satırı başına iki iz kümesinin ortak kapsadığı hücre sayısı × res.
    serit_izleri: tarama doğrusu sırasıyla [iz köşeleri (K,4,2)] listeleri. Dönen: [(çift, satır_örtüşmeleri dizisi)]."""
    g = Izgara(bolge, res)
    kapsalar = []
    for izler in serit_izleri:
        k = np.zeros((g.ny, g.nx), bool)
        for iz in izler:
            g.isle(iz, k)
        kapsalar.append(k)
    sat = (g.gy >= y_alt) & (g.gy <= y_ust)
    cikti = []
    for i in range(len(kapsalar) - 1):
        ort = (kapsalar[i] & kapsalar[i + 1])[sat].sum(axis=1) * res
        cikti.append((i, ort))
    return cikti


# --- yükleme -----------------------------------------------------------------------------------------------------------------------
def dizi_gz(satirlar, a):
    r = sorted((s for s in satirlar if s["k"] == "gz" and s["a"] == a), key=lambda s: s["sim_ns"])
    t = np.array([s["sim_ns"] for s in r], float) / NS
    return t, np.array([s["p"] for s in r], float), np.array([s["q"] for s in r], float)


def dizi_px4(satirlar, a):
    att = sorted((s for s in satirlar if s["k"] == "att" and s["a"] == a and s["sim_ns"] is not None), key=lambda s: s["mono_ns"])
    pv = sorted((s for s in satirlar if s["k"] == "pv" and s["a"] == a and s["sim_ns"] is not None), key=lambda s: s["mono_ns"])
    return ((np.array([s["sim_ns"] for s in att], float) / NS, np.array([s["q"] for s in att], float)),
            (np.array([s["sim_ns"] for s in pv], float) / NS, np.array([s["n"] for s in pv], float), np.array([s["v"] for s in pv], float)))


def en_yakin(tt, t):
    i = np.clip(np.searchsorted(tt, t), 1, len(tt) - 1)
    sol, sag = tt[i - 1], tt[i]
    return np.where(np.abs(t - sol) <= np.abs(sag - t), i - 1, i)


def bacak_zamanlari(t, p, noktalar, kabul):
    """Gazebo konum örneklerinden (zaman t, konum p) her bacağın başlangıç zamanı: bacak k, WP[k] → WP[k+1]; k+1. noktaya `kabul` m yaklaşınca sonraki bacağa geçilir.
    Dönen: başlangıç zamanları (nbacak+1: sonuncusu rotanın bitiş zamanı; erişilemeyen None)."""
    nb = len(noktalar) - 1
    bas = [None] * (nb + 1)
    bas[0] = t[0]
    k = 0
    for i in range(len(t)):
        if k >= nb:
            break
        if math.dist(p[i, :2], noktalar[k + 1]) < kabul:
            k += 1
            bas[k] = t[i]
    return bas


def yuzde(x, q):
    return float(np.percentile(np.asarray(x, float), q)) if len(x) else float("nan")


def ana(argv):
    a = list(argv)
    if not a:
        print(__doc__, file=sys.stderr)
        return 2
    klasor = a.pop(0)
    n_arac, cikti_md = 0, None
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k == "--cikti" and a:
            cikti_md = a.pop(0)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    ham = rota_mod.deney_env_oku()
    hz = int(float(ham["CAM_RATE_HZ"]))
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()][:n_arac]
    irtifa, hiz = float(ham["ROTA_IRTIFA_M"]), float(ham["ROTA_HIZ_MS"])
    kabul = float(ham["PX4A_KABUL_YARICAPI_M"])
    kenar_pay = float(ham["ALAN_KENAR_PAYI_M"])
    with open(os.path.join(KOK, "config", "bolge_rota.json"), encoding="utf-8") as f:
        br = json.load(f)
    alan = br["alan"]
    bolgeler = {b["arac_kimligi"]: b for b in br["bolgeler"]}
    rotalar = {r["arac_kimligi"]: [tuple(n) for n in r["noktalar"]] for r in br["rotalar"]}
    kam = Kamera(os.path.join(KOK, "config", "kamera_kalibrasyon.json"))
    baslangic = {k: tuple(float(v) for v in p.split(",")) for k, p in zip(kimlikler, ham["UAV_START_POSES"].split())}
    olcum = jsonl(os.path.join(klasor, "alan_pilot_olcum.jsonl"))
    from koordinator_kayit import koordinator_olaylari
    koord = koordinator_olaylari(klasor)      # deneme koordinatörünün ya da asıl yer istasyonu koordinatörünün kaydı (aynı olay sözlüğü biçimi)
    damga_hepsi = jsonl(os.path.join(klasor, "kayit", "gazebo_damga.jsonl"))
    os.makedirs(os.path.join(klasor, "analiz"), exist_ok=True)

    ozet = {}
    for ai, k in enumerate(kimlikler, start=1):
        alog = asa.log_oku(os.path.join(klasor, f"arac_{k}.log"))
        s = {"k": k, "ai": ai}
        s["t_s"] = int(alog["tarama_baslat_alindi"][0]["t_s_ns"]) / NS
        bit = alog["tarama_bitis_yayimlandi"][0]
        s["t_b"] = int(bit["t_b_ns"]) / NS
        s["n_ilk"], s["n_son"] = int(bit["n_first"]), int(bit["n_last"])
        s["mono_s"] = alog["tarama_baslat_alindi"][0]["mono_ns"]
        s["mono_b"] = alog["son_nokta_geri_cagrisi"][0]["mono_ns"]
        s["hazirlik"] = float(alog["hazirlik_bitti"][0]["sure_s"])
        s["basladi_mono"] = alog["basladi"][0]["mono_ns"]
        td = [x for x in alog["durum"] if x.get("durum") == "TAMAMLANDI"]
        s["tamam_mono"] = td[0]["mono_ns"] if td else None
        s["ozet_alici"] = alog["kamera_alici_ozet"][0]
        s["kare_ozet"] = alog["kare_sonuclari_tamam"][0]
        t, p, q = dizi_gz(olcum, ai)
        if len(t) < 10:
            print(f"(-) araç {k}: Gazebo poz örneği yok ({len(t)})", file=sys.stderr)
            return 2
        s["gz"] = (t, p, q)
        s["att"], s["pv"] = dizi_px4(olcum, ai)
        s["rota"] = rotalar[k]
        s["bolge"] = bolgeler[k]
        ozet[k] = s

    # --- M1 kapısı denetimleri (kare sonucu bütünlüğü, sınır, çakışma) ----------------------------------------------------------------------
    for k, s in ozet.items():
        sn = jsonl(os.path.join(klasor, "kayit", f"kare_sonuc_{k}.jsonl"))
        al = jsonl(os.path.join(klasor, "kayit", f"kamera_alici_{k}.jsonl"))
        aralik = set(range(s["n_ilk"], s["n_son"] + 1))
        numaralar = [r["n"] for r in sn]
        durumlar = {}
        for r in sn:
            durumlar[r["durum"]] = durumlar.get(r["durum"], 0) + 1
        s["sonuc_durumlari"] = durumlar
        sonuc(sorted(numaralar) == sorted(aralik), f"kare_sonucu_tam_{k}",
              f"[{s['n_ilk']}, {s['n_son']}] aralığındaki {len(aralik)} görev numarası için {len(numaralar)} kare sonucu, tekrar {len(numaralar) - len(set(numaralar))}, eksik {len(aralik - set(numaralar))}; durumlar {durumlar}")
        sonuc(int(s["ozet_alici"]["gorev_siniri_asildi"]) == 0, f"gorev_siniri_asildi_{k}", f"gorev_siniri_asildi = {s['ozet_alici']['gorev_siniri_asildi']}")
        dm = {r["n"] for r in damga_hepsi if r["arac_kimligi"] == k and isinstance(r["n"], int)}
        oncesi = {r["n"] for r in al if r["olay"] == "yok_sayildi" and r.get("neden") == "gorev_oncesi" and isinstance(r["n"], int)}
        kayip = {r["n"] for r in al if r["olay"] == "kayip_tespit" and isinstance(r["n"], int)}
        cakisma = sorted(n for n in (dm & oncesi & kayip))
        sonuc(not cakisma, f"gorev_oncesi_kayip_cakismasi_{k}", f"damgada var + alıcıda gorev_oncesi + kayip_tespit çakışan numara sayısı {len(cakisma)} {cakisma[:5]}; kare_alinamadi {len(kayip)}")
        sonuc(s["kare_ozet"]["zamaninda"] == "True" and s["kare_ozet"]["islem_hatasi"] == "0" and s["kare_ozet"]["kare_alinamadi"] == "0",
              f"kare_sonuclari_zamaninda_{k}", f"kapanış zamanında={s['kare_ozet']['zamaninda']}, islem_hatasi={s['kare_ozet']['islem_hatasi']}, kare_alinamadi={s['kare_ozet']['kare_alinamadi']}, tespit={s['kare_ozet']['tespit']}, tespit_yok={s['kare_ozet']['tespit_yok']}")

    # --- süre, uzunluk, RTF -------------------------------------------------------------------------------------------------------------
    yaz("### Süre, uzunluk, RTF (araç başına)")
    yaz()
    yaz("| Araç | Planlanan rota (m) | Gerçek yol, PX4 (m) | Gerçek yol, Gazebo (m) | Hazırlık (gerçek s) | Tarama sim (s) | Tarama monotonik (s) | RTF | Başlangıç→TAMAMLANDI (gerçek s) | Kare n_ilk…n_son (adet) |")
    yaz("|---|---|---|---|---|---|---|---|---|---|")
    son_bitis = 0.0
    for k, s in ozet.items():
        nok = s["rota"]
        plan = sum(math.dist(nok[i], nok[i + 1]) for i in range(len(nok) - 1))
        (ta, qa), (tp, npos, vel) = s["att"], s["pv"]
        pencere = (tp >= s["t_s"]) & (tp <= s["t_b"])
        pp = npos[pencere]
        gercek_px4 = float(np.sum(np.linalg.norm(np.diff(pp, axis=0), axis=1))) if len(pp) > 1 else float("nan")
        tg, pg, _ = s["gz"]
        pg_ = pg[(tg >= s["t_s"]) & (tg <= s["t_b"])]
        gercek_gz = float(np.sum(np.linalg.norm(np.diff(pg_, axis=0), axis=1))) if len(pg_) > 1 else float("nan")
        sim_s = s["t_b"] - s["t_s"]
        mono_sn = (s["mono_b"] - s["mono_s"]) / NS
        s["sure"] = {"plan": plan, "px4": gercek_px4, "gz": gercek_gz, "sim": sim_s, "mono": mono_sn, "rtf": sim_s / mono_sn}
        top = (s["tamam_mono"] - s["basladi_mono"]) / NS if s["tamam_mono"] else float("nan")
        son_bitis = max(son_bitis, s["t_b"])
        yaz(f"| {k} | {plan:.1f} | {gercek_px4:.1f} | {gercek_gz:.1f} | {s['hazirlik']:.1f} | {sim_s:.1f} | {mono_sn:.1f} | {sim_s / mono_sn:.3f} | {top:.1f} | {s['n_ilk']}…{s['n_son']} ({s['n_son'] - s['n_ilk'] + 1}) |")
    t0 = next((x for x in koord if x["olay"] == "t0"), None)
    t1 = next((x for x in koord if x["olay"] == "t1"), None)
    yaz()
    if t0 and t1:
        yaz(f"Son aracın tarama bitişi: sim {son_bitis:.2f} s; koordinatör t0 sim {t0['sim_ns'] / NS:.2f} s, t1 sim {t1['sim_ns'] / NS:.2f} s; en uzun tarama (t_s→son t_b) {son_bitis - min(s['t_s'] for s in ozet.values()):.1f} s. "
           f"Tarama bitişi yayımları t0'dan sonra: " + ", ".join(f"araç {x['arac']}: {x['sim_ns'] / NS - t0['sim_ns'] / NS:.1f} s" for x in koord if x["olay"] == "tarama_bitis") + ".")
        yaz()
    yaz("Tanımlar: planlanan rota = bolge_rota.json çokgen uzunluğu (yatay); gerçek yol = t_s…t_b penceresindeki PX4 yerel konum (NED, 3B) ve Gazebo model konumu (3B) örneklerinin ardışık farklarının toplamı; "
        "tarama sim = t_b − t_s (simülasyon saati); tarama monotonik = `tarama_baslat_alindi` ile `son_nokta_geri_cagrisi` günlük anları arası; RTF = sim / monotonik; "
        "hazırlık = `hazirlik_bitti` süresi (kalkış + ilk noktaya gidiş, t0 öncesi); Başlangıç→TAMAMLANDI = araç günlüğünde `basladi` ile `durum TAMAMLANDI` arası.")
    yaz()

    # --- görev karesi başına yönelim ----------------------------------------------------------------------------------------------------
    yaz("### Yönelim: görüntünün yatay ekseni ile uçuş yönü (kare üretim anında)")
    yaz()
    yaz("Açı = görüntü yatay ekseninin (kamera x) yatay izdüşümü ile uçuş yönü (hız vektörünün yatay izdüşümü) arasındaki işaretsiz açı; ideal değer 90°. "
        "Sapma d = (kamera x azimutu − uçuş yönü azimutu + 90°) sarılmış, işaretli (derece; + = gövde uçuş yönünden saat yönünün tersine dönük). Bacak: bolge_rota noktaları arası; "
        "çift numaralı (0,2,…) bacaklar tarama doğrusu (y boyunca), tek numaralılar kısa geçiş (x boyunca).")
    yaz()
    yonelim = {}
    for k, s in ozet.items():
        t_g, p_g, q_g = s["gz"]
        bas = bacak_zamanlari(t_g[(t_g >= s["t_s"] - 5)], p_g[(t_g >= s["t_s"] - 5)], s["rota"], kabul + 0.5)
        s["bacak_bas"] = bas
        nb = len(s["rota"]) - 1
        n_k = np.arange(s["n_ilk"], s["n_son"] + 1)
        t_k = n_k / hz
        bacak = np.full(len(t_k), -1)
        for b in range(nb):
            if bas[b] is None:
                continue
            bitis = bas[b + 1] if bas[b + 1] is not None else np.inf
            bacak[(t_k >= bas[b]) & (t_k < bitis)] = b
        bacak[(t_k >= (bas[nb] if bas[nb] is not None else np.inf))] = nb      # rota bitti, son nokta kabulünden sonra
        # Gazebo pozu (kare anında) ve uçuş yönü (±0,5 s merkezî fark)
        p_k = np.stack([np.interp(t_k, t_g, p_g[:, c]) for c in range(3)], axis=1)
        R_g = kuat_mat(kuat_interp(t_k, t_g, q_g))
        v_g = np.stack([(np.interp(t_k + 0.5, t_g, p_g[:, c]) - np.interp(t_k - 0.5, t_g, p_g[:, c])) / 1.0 for c in range(3)], axis=1)
        (t_a, q_a), (t_p, n_p, v_p) = s["att"], s["pv"]
        ia, ip = en_yakin(t_a, t_k), en_yakin(t_p, t_k)
        R_p = px4_mat_enu_flu(q_a[ia])
        v_px4 = np.stack([v_p[ip][:, 1], v_p[ip][:, 0], -v_p[ip][:, 2]], axis=1)       # NED → ENU
        s["fark_att_s"] = float(np.max(np.abs(t_a[ia] - t_k)))
        sat = {}
        for ad, R, v in (("gz", R_g, v_g), ("px4", R_p, v_px4)):
            cx = kam.x_ekseni(R)
            az_x, az_v = yatay_az(cx), yatay_az(v)
            hv = np.linalg.norm(v[:, :2], axis=1)
            d = sar(az_x - az_v + 90.0)
            yaw = derece(np.arctan2(R[:, 1, 0], R[:, 0, 0]))
            roll = derece(np.arctan2(R[:, 2, 1], R[:, 2, 2]))
            pitch = derece(np.arcsin(-np.clip(R[:, 2, 0], -1, 1)))
            sat[ad] = {"d": d, "yaw": yaw, "roll": roll, "pitch": pitch, "uyon": az_v, "hv": hv, "aci": np.abs(sar(az_x - az_v))}
        z_px4 = -n_p[ip][:, 2]
        yonelim[k] = {"n": n_k, "t": t_k, "bacak": bacak, "p": p_k, "R_g": R_g, "z_px4": z_px4, **{"g_" + x: v for x, v in sat["gz"].items()}, **{"p_" + x: v for x, v in sat["px4"].items()}}
        with open(os.path.join(klasor, "analiz", f"kare_yonelim_{k}.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["n", "sim_s", "bacak", "x", "y", "z", "gz_yaw", "gz_roll", "gz_pitch", "gz_uyon", "gz_sapma", "px4_yaw", "px4_roll", "px4_pitch", "px4_uyon", "px4_sapma", "px4_z"])
            for i in range(len(n_k)):
                w.writerow([int(n_k[i]), f"{t_k[i]:.1f}", int(bacak[i])] + [f"{v:.3f}" for v in p_k[i]] + [f"{sat['gz'][c][i]:.2f}" for c in ("yaw", "roll", "pitch", "uyon", "d")]
                           + [f"{sat['px4'][c][i]:.2f}" for c in ("yaw", "roll", "pitch", "uyon", "d")] + [f"{z_px4[i]:.2f}"])

    for k, s in ozet.items():
        y = yonelim[k]
        nb = len(s["rota"]) - 1
        yaz(f"**Araç {k}** (kare üretim anı → Gazebo pozu kareye doğrusal/nlerp ara değerle; PX4 yönelimi en yakın örnek, en büyük zaman farkı {s['fark_att_s'] * 1000:.0f} ms)")
        yaz()
        yaz("| Bacak | Tür | Kare | Uçuş yönü (°) | Yaw Gazebo ort ± std (°) | Yaw PX4 ort ± std (°) | Açı Gazebo ort ± std (°) | Sapma Gazebo ort / en çok (°) | Açı PX4 ort ± std (°) | Sapma PX4 ort / en çok (°)  |d| > 10° kare (Gazebo / PX4) |")
        yaz("|---|---|---|---|---|---|---|---|---|---|---|")
        toplam = {"tarama": {"g": [], "p": []}, "gecis": {"g": [], "p": []}}
        for b in range(nb):
            m = (y["bacak"] == b) & (y["g_hv"] > 1.0)
            if m.sum() == 0:
                yaz(f"| {b} | {'tarama' if b % 2 == 0 else 'geçiş'} | 0 | | | | | | | | |")
                continue
            tur = "tarama" if b % 2 == 0 else "gecis"
            uy_o, _ = dairesel_ort_std(y["g_uyon"][m])
            yo_g, ys_g = dairesel_ort_std(y["g_yaw"][m])
            yo_p, ys_p = dairesel_ort_std(y["p_yaw"][m])
            toplam[tur]["g"].append(y["g_d"][m])
            toplam[tur]["p"].append(y["p_d"][m])
            dg, dp = y["g_d"][m], y["p_d"][m]
            yaz(f"| {b} | {'tarama' if tur == 'tarama' else 'geçiş'} | {int(m.sum())} | {uy_o:.1f} | {yo_g:.1f} ± {ys_g:.2f} | {yo_p:.1f} ± {ys_p:.2f} | "
                f"{np.mean(y['g_aci'][m]):.2f} ± {np.std(y['g_aci'][m]):.2f} | {np.mean(dg):+.2f} / {np.max(np.abs(dg)):.2f} | {np.mean(y['p_aci'][m]):.2f} ± {np.std(y['p_aci'][m]):.2f} | {np.mean(dp):+.2f} / {np.max(np.abs(dp)):.2f} | {int((np.abs(dg) > 10).sum())} / {int((np.abs(dp) > 10).sum())} |")
        yaz()
        s["yon_toplam"] = {tur: {kaynak: (np.concatenate(v) if v else np.array([])) for kaynak, v in d.items()} for tur, d in toplam.items()}

    yaz("**Özet (tarama doğruları ve geçişler, tüm kareler; |sapma| = |d|, derece):**")
    yaz()
    yaz("| Araç | Tür | Kare | Gazebo ortanca / p95 / en çok | PX4 ortanca / p95 / en çok |")
    yaz("|---|---|---|---|---|")
    for k, s in ozet.items():
        for tur, ad in (("tarama", "tarama"), ("gecis", "geçiş")):
            g, p = np.abs(s["yon_toplam"][tur]["g"]), np.abs(s["yon_toplam"][tur]["p"])
            if len(g) == 0:
                continue
            yaz(f"| {k} | {ad} | {len(g)} | {np.median(g):.2f} / {yuzde(g, 95):.2f} / {np.max(g):.2f} | {np.median(p):.2f} / {yuzde(p, 95):.2f} / {np.max(p):.2f} |")
    yaz()

    # --- yalpa, yunuslama, irtifa (tarama doğruları) -------------------------------------------------------------------------------------
    yaz("### Düz bacaklarda (tarama doğruları) yalpa, yunuslama, irtifa")
    yaz()
    yaz(f"İrtifa = Gazebo modelinin dünya z'si (zemin z = 0); sapma = z − {irtifa:g} m. PX4 göreli irtifası (−aşağı konum) çapraz denetim.")
    yaz()
    yaz("| Araç | Bacak | Yalpa ort ± std / en çok (°) | Yunuslama ort ± std / en çok (°) | Gazebo z ort ± std (m) | z en az…en çok (m) | PX4 z ort (m) |")
    yaz("|---|---|---|---|---|---|---|")
    for k, s in ozet.items():
        y = yonelim[k]
        for b in range(0, len(s["rota"]) - 1, 2):
            m = (y["bacak"] == b)
            if m.sum() < 3:
                continue
            r, pt, z = y["g_roll"][m], y["g_pitch"][m], y["p"][m][:, 2]
            yaz(f"| {k} | {b} | {np.mean(r):+.2f} ± {np.std(r):.2f} / {np.max(np.abs(r)):.2f} | {np.mean(pt):+.2f} ± {np.std(pt):.2f} / {np.max(np.abs(pt)):.2f} | {np.mean(z):.2f} ± {np.std(z):.2f} | {z.min():.2f}…{z.max():.2f} | {np.mean(y['z_px4'][m]):.2f} |")
    yaz()

    # --- kapsama ------------------------------------------------------------------------------------------------------------------------
    def izler_gercek(k, maske=None):
        y = yonelim[k]
        m = np.ones(len(y["n"]), bool) if maske is None else maske
        return kam.iz(y["p"][m], y["R_g"][m]), y["bacak"][m]

    def izler_ideal(k):
        nok = ozet[k]["rota"]
        adim = hiz / hz
        pts, Rs, bac = [], [], []
        for b in range(len(nok) - 1):
            a_, c_ = np.array(nok[b]), np.array(nok[b + 1])
            uz = float(np.linalg.norm(c_ - a_))
            yon = (c_ - a_) / uz
            yaw = math.atan2(yon[1], yon[0])
            Rz = np.array([[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]])
            for sd in list(np.arange(0.0, uz + 1e-9, adim)) + [uz]:      # bacağın son noktası da örneklenir (kare fazı ideal geometriyi etkilemesin)
                q_ = a_ + yon * sd
                pts.append([q_[0], q_[1], irtifa])
                Rs.append(Rz)
                bac.append(b)
        return kam.iz(np.array(pts), np.array(Rs)), np.array(bac)

    yaz("### Kapsama (her bölgede, bölgenin 1 m'lik ızgarası; en az bir kare izine girmeyen nokta oranı)")
    yaz()
    yaz(f"Gerçek: görev karelerinin Gazebo pozundan hesaplanan yer izi (eğim dahil, zemin z = 0 düzlemi). İdeal: planlanan rota 2,5 m aralıklı örneklenir (hız/kare hızı), seviye uçuş, yön = bacak yönü, z = {irtifa:g} m. "
        f"Bant tanımı: bölge kenarından ≤ {kenar_pay:g} m (ALAN_KENAR_PAYI_M); 'dış bant' alanın dış sınırındaki kenarlar (ve bölgenin y uçları), 'iç bant' bölgeler arası sınırdaki kenarlar. "
        "'Başka araçla' sütunu: bölgenin kendi aracı + diğer araçların kareleri birlikte.")
    yaz()
    yaz("| Bölge (araç) | Kaynak | Boş oran, bölge (%) | Boş hücre / toplam | İç (%) | Dış bant (%) | İç bant (%) | Başka araçlarla birlikte (%) |")
    yaz("|---|---|---|---|---|---|---|---|")
    bos_konumlar = {}
    for k, s in ozet.items():
        bo = s["bolge"]
        tum_gercek = np.concatenate([izler_gercek(kk)[0] for kk in kimlikler])
        for ad, (iz, _) in (("gerçek", izler_gercek(k)), ("ideal", izler_ideal(k))):
            kapsa, g = kapsama_bolge(bo, iz, kenar_pay)
            o = kapsama_ozeti(bo, kapsa, g, kenar_pay, alan)
            if ad == "gerçek":
                kapsa2, _ = kapsama_bolge(bo, tum_gercek, kenar_pay)
                digeri = f"{100.0 * (~kapsa2).sum() / kapsa2.size:.3f}"
                bos_konumlar[k] = o["dis_bos_konum"]
            else:
                digeri = "-"
            yaz(f"| {bo['bolge_kimligi']} ({k}) | {ad} | {o['bolge'][0]:.3f} | {o['bolge'][1]} / {o['bolge'][2]} | {o['ic'][0]:.3f} | {o['dis_band'][0]:.3f} | {o['ic_band'][0]:.3f} | {digeri} |")
            s.setdefault("kapsama", {})[ad] = o
    yaz()

    # --- komşu şerit örtüşmesi ----------------------------------------------------------------------------------------------------------
    yaz("### Komşu şeritlerin örtüşmesi (m)")
    yaz()
    yaz(f"Tarama doğrusu başına (çift numaralı bacak) kareler 0,25 m ızgarada birleştirilir; komşu iki doğrunun, rota y aralığındaki her satırda ortak kapsadığı genişlik. Planlanan en az örtüşme {ham['ROTA_ORTUSME_MIN_M']} m.")
    yaz()
    yaz("| Araç | Kaynak | Çift (bacak) | En kötü satır (m) | Ortanca (m) | En iyi (m) |")
    yaz("|---|---|---|---|---|---|")
    for k, s in ozet.items():
        nok = s["rota"]
        y_alt, y_ust = min(p[1] for p in nok), max(p[1] for p in nok)
        for ad, (iz, bac) in (("gerçek", izler_gercek(k)), ("ideal", izler_ideal(k))):
            serit = [iz[bac == b] for b in range(0, len(nok) - 1, 2)]
            for (i, ort) in ortusme_satirlari(s["bolge"], nok, serit, 0.25, y_alt, y_ust):
                yaz(f"| {k} | {ad} | {2 * i}–{2 * i + 2} | {ort.min():.2f} | {np.median(ort):.2f} | {ort.max():.2f} |")
                s.setdefault("ortusme", {}).setdefault(ad, []).append((float(ort.min()), float(np.median(ort))))
    yaz()

    # --- bölge taşması ve ayrım ---------------------------------------------------------------------------------------------------------
    yaz("### Bölge sınırları ve araçlar arası ayrım (tarama penceresi t_s…t_b)")
    yaz()
    yaz("Taşma = aracın yatay konumunun kendi bölgesinin dikdörtgeninden dışa uzaklığı (m; 0 = içeride). İz taşması = görev karesi yer izi köşelerinin kendi bölgesi dışına uzaklığı. "
        "Konumlar: Gazebo gerçek konumu ve PX4 yerel konumu (başlangıç pozuna eklenerek ENU).")
    yaz()
    yaz("| Araç | Bölge x aralığı (m) | En kötü taşma, Gazebo (m) | En kötü taşma, PX4 (m) | En kötü iz taşması: tarama doğruları / geçişler (m) | Gazebo konum x aralığı (m) |")
    yaz("|---|---|---|---|---|---|")
    pencere_poz = {}
    for k, s in ozet.items():
        t_g, p_g, _ = s["gz"]
        m = (t_g >= s["t_s"]) & (t_g <= s["t_b"])
        pencere_poz[k] = (t_g[m], p_g[m])
        bo = s["bolge"]

        def tasma(x, y_):
            return np.maximum.reduce([bo["x_min"] - x, x - bo["x_max"], bo["y_min"] - y_, y_ - bo["y_max"], np.zeros_like(x)])
        tg = tasma(p_g[m][:, 0], p_g[m][:, 1])
        (t_a, _), (t_p, n_p, _) = s["att"], s["pv"]
        mp = (t_p >= s["t_s"]) & (t_p <= s["t_b"])
        x0, y0, _z0 = baslangic[k]
        tp_ = tasma(x0 + n_p[mp][:, 1], y0 + n_p[mp][:, 0])
        iz, bac = izler_gercek(k)
        ix, iy = iz[:, :, 0], iz[:, :, 1]
        tum = np.where(np.isfinite(ix) & np.isfinite(iy), tasma(np.nan_to_num(ix), np.nan_to_num(iy)), 0.0)
        ti_t = tum[bac % 2 == 0].max() if np.any(bac % 2 == 0) else float("nan")
        ti_g = tum[bac % 2 == 1].max() if np.any(bac % 2 == 1) else float("nan")
        s["tasma"] = (float(tg.max()), float(tp_.max()), float(ti_t), float(ti_g))
        yaz(f"| {k} | {bo['x_min']:g}…{bo['x_max']:g} | {tg.max():.2f} | {tp_.max():.2f} | {ti_t:.2f} / {ti_g:.2f} | {p_g[m][:, 0].min():.2f}…{p_g[m][:, 0].max():.2f} |")
    yaz()
    if len(kimlikler) > 1:
        yaz("| Araç çifti | Aynı anda en yakın yatay uzaklık (m) | Aynı anda en yakın 3B uzaklık (m) | İz noktaları arası en kısa yatay uzaklık (m) | Gazebo konum x aralıkları arasındaki boşluk (m) |")
        yaz("|---|---|---|---|---|")
        for i in range(len(kimlikler)):
            for j in range(i + 1, len(kimlikler)):
                ki, kj = kimlikler[i], kimlikler[j]
                ti_, pi_ = pencere_poz[ki]
                tj_, pj_ = pencere_poz[kj]
                t_ort = np.arange(max(ti_[0], tj_[0]), min(ti_[-1], tj_[-1]), 0.1)
                a1 = np.stack([np.interp(t_ort, ti_, pi_[:, c]) for c in range(3)], axis=1)
                b1 = np.stack([np.interp(t_ort, tj_, pj_[:, c]) for c in range(3)], axis=1)
                yat = np.linalg.norm(a1[:, :2] - b1[:, :2], axis=1)
                uc = np.linalg.norm(a1 - b1, axis=1)
                d2 = np.min(np.linalg.norm(pi_[:, None, :2] - pj_[None, :, :2], axis=2))
                bosluk = max(pj_[:, 0].min() - pi_[:, 0].max(), pi_[:, 0].min() - pj_[:, 0].max())
                yaz(f"| {ki}–{kj} | {yat.min():.2f} | {uc.min():.2f} | {d2:.2f} | {bosluk:.2f} |")
        yaz()

    # --- çıktı --------------------------------------------------------------------------------------------------------------------------
    metin = "\n".join(CIKTI) + "\n"
    print(metin)
    if cikti_md:
        with open(cikti_md, "w", encoding="utf-8") as f:
            f.write(metin)
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
