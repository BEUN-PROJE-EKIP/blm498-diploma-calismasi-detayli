#!/usr/bin/env python3
"""Konum hesaplayıcı koşu analizi (YALNIZ okuma): işaretle geometri denetimi, tam rota izdüşüm tablosu, iki modda aynı sonuç ve odometri zaman kayması incelemesi.

Kullanım:  python3 -I araclar/konum_analiz.py <mod> <koşu_klasörü> --arac N [--kayma-ms X] [--sahte-bekleniyor]
Modlar:
  isaret   konum_isaret.py'nin eklediği bilinen ENU işaretleri: işaret başına yatay hata (PX4 enterpolasyonlu `kare_poz` ile ve Gazebo gerçek pozuyla); Bitti ölçütü: her ölçüm < 5 m, en az 20 görünüm
  rota     her görev karesi için görüntüde sabit piksellerin (merkez + dört köşeye yakın) Gazebo gerçek pozuyla izdüşümü ile PX4 pozuyla hesabı: evreye göre yatay hata (eşik yok; 5 m aşılırsa `kaldi`);
           ayrıca zemin ölçümü (dünya dosyası zemin düzlemi, araç yerdeyken model ve PX4 yüksekliği) ve kesişim mesafesi dağılımı; --kayma-ms verilirse PX4 pozu o kadar geri örneklenerek ikinci tablo
  iki_mod  kare sonuç kaydındaki her tespitin konumu, uçta modda `kare_poz` ile merkezi modda başlıktaki pozla (kayıttaki `poz`) ÇEVRİM DIŞI yeniden hesaplanır: birebir (< 1e-6 m); konumsuz sayıları ve nedenleri
  kayma    odometri zaman kayması: Gazebo poz kaynaklarının karşılaştırması, PX4 kaynak kodu satırları, evreye göre kayma tahmini (çapraz ilişki) ve hız–kayma ilişkisi, kaymanın konum hatasına etkisi
Girdi (koşu klasörü): kayit/kare_poz_<kimlik>.jsonl, kayit/kare_sonuc_<kimlik>.jsonl, kayit/telemetri_<kimlik>.jsonl, gz_gercek_poz.jsonl, konum_isaretleri.json, konum_isaret_kareler.jsonl, gz_poz_kaynaklari.jsonl.
Çıktı: `SONUC gecti|kaldi <ad> | <ayrıntı>`, `TABLO ...`, `BILGI ...` satırları. Çıkış: 0 (karar test betiğindedir), 2 kullanım/girdi hatası. Yalnız standart kitaplık + numpy.
"""
import bisect
import json
import math
import os
import re
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

import numpy as np  # noqa: E402
from swarm_vehicle import konum_hesap as kh  # noqa: E402
from swarm_vehicle import poz_tamponu as pt  # noqa: E402
from swarm_vehicle import rota as _rota  # noqa: E402

NS = 10 ** 9
ESIK_M = 5.0
ESIK_ESLESMEYEN = 0.05                          # işaret testinde eşleşmeyen blob oranı üst sınırı (gerekçe: mod_isaret)
PIKSELLER = {"merkez": (320.0, 240.0), "sol_ust": (64.0, 48.0), "sag_ust": (576.0, 48.0), "sol_alt": (64.0, 432.0), "sag_alt": (576.0, 432.0)}


def jsonl(yol):
    with open(yol, encoding="utf-8") as f:
        return [json.loads(s) for s in f if s.strip()]


def yuzdelik(v, p):
    s = sorted(v)
    return s[min(len(s) - 1, int(p / 100 * len(s)))] if s else float("nan")


def ozet(v):
    return f"n={len(v)} | ortanca {yuzdelik(v, 50):.3f} | p95 {yuzdelik(v, 95):.3f} | en çok {max(v):.3f}" if v else "n=0 | veri yok"


def sonuc(ok, ad, ayrinti):
    print(f"SONUC {'gecti' if ok else 'kaldi'} {ad} | {ayrinti}", flush=True)


class Poz:
    def __init__(self, konum, q, gecerli=True):
        self.gecerli, self.konum, self.q = gecerli, konum, q


# --- bağımsız ileri izdüşüm (hesaplayıcıdan ayrı yazılmış: kuaterniyon–vektör çarpımı) ---------------------------------------------------------------
def _kq_carp(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def _kq_ters_dondur(q, v):
    n = math.sqrt(sum(a * a for a in q))
    c = (q[0] / n, -q[1] / n, -q[2] / n, -q[3] / n)
    return _kq_carp(_kq_carp(c, (0.0, *v)), (c[0], -c[1], -c[2], -c[3]))[1:]


def ileri_izdusum(kal, nokta_enu, konum_ned, q, baslangic):
    """ENU zemin noktası → piksel (u, v) ya da None (kameranın arkası). Yalnız gerçek poz ile eşleştirme (ilişkilendirme) için."""
    x0, y0, z0 = baslangic
    p_ned = (nokta_enu[1] - y0, nokta_enu[0] - x0, -(nokta_enu[2] - z0))
    fark = tuple(a - b for a, b in zip(p_ned, konum_ned))
    p_frd = _kq_ters_dondur(q, fark)
    g = (p_frd[0] - kal.t[0], -p_frd[1] - kal.t[1], -p_frd[2] - kal.t[2])
    p_kam = tuple(sum(kal.R[j][i] * g[j] for j in range(3)) for i in range(3))
    if p_kam[2] <= 0:
        return None
    return kal.fx * p_kam[0] / p_kam[2] + kal.cx, kal.fy * p_kam[1] / p_kam[2] + kal.cy


# --- poz kaynakları -------------------------------------------------------------------------------------------------------------------------------------
class GercekPoz:
    """Gazebo gerçek pozu (poz_gercek_kayit.py): sim zamanına göre doğrusal konum, normalize doğrusal yönelim. ENU konum, gövde FLU → ENU kuaterniyonu."""

    def __init__(self, kayitlar):
        p = sorted((g for g in kayitlar if g["k"] == "poz"), key=lambda g: g["sim_ns"])
        self.t = np.array([g["sim_ns"] for g in p], dtype=np.int64)
        self.p = np.array([g["p"] for g in p], dtype=float)
        self.q = np.array([g["q"] for g in p], dtype=float)
        self.tf = self.t.astype(float)

    def var(self):
        return len(self.t) > 10

    def at(self, t_ns, sinir_ns=50 * 10 ** 6):
        i = int(np.searchsorted(self.t, t_ns))
        if i <= 0 or i >= len(self.t) or self.t[i] - self.t[i - 1] > sinir_ns:
            return None
        f = (t_ns - self.t[i - 1]) / (self.t[i] - self.t[i - 1])
        q = self.q[i - 1] + f * (self.q[i] - self.q[i - 1])
        return tuple(self.p[i - 1] + f * (self.p[i] - self.p[i - 1])), tuple(q / np.linalg.norm(q))

    def girdi(self, t_ns, baslangic):
        """Hesaplayıcı girdisi (NED konum, FRD → NED kuaterniyonu) ya da None."""
        g = self.at(t_ns)
        if g is None:
            return None
        konum_ned, q = kh.enu_flu_den_ned_frd(g[0], g[1], baslangic)
        return Poz(konum_ned, q)

    def hiz(self, t_ns, yari_pencere_ns=250 * 10 ** 6):
        a, b = self.at(t_ns - yari_pencere_ns), self.at(t_ns + yari_pencere_ns)
        if a is None or b is None:
            return None
        return ((b[0][0] - a[0][0]) / (2 * yari_pencere_ns / 1e9), (b[0][1] - a[0][1]) / (2 * yari_pencere_ns / 1e9))


class Px4Poz:
    """PX4 telemetrisi (kabul edilen örnekler): kaynak zamanına göre doğrusal konum, küresel yönelim (tampon kuralıyla aynı)."""

    def __init__(self, telemetri):
        k = [t for t in telemetri if t["kabul"]]
        self.t = [t["kaynak_ns"] for t in k]
        self.konum = [t["konum_ned_m"] for t in k]
        self.q = [t["q_wxyz"] for t in k]

    def at(self, t_ns, sinir_ns=100 * 10 ** 6):
        i = bisect.bisect_left(self.t, t_ns)
        if i <= 0 or i >= len(self.t):
            return None
        if self.t[i] == t_ns:
            return Poz(tuple(self.konum[i]), tuple(self.q[i]))
        if self.t[i] - self.t[i - 1] > sinir_ns:
            return None
        f = (t_ns - self.t[i - 1]) / (self.t[i] - self.t[i - 1])
        return Poz(tuple(a + f * (b - a) for a, b in zip(self.konum[i - 1], self.konum[i])), pt.slerp(self.q[i - 1], self.q[i], f))


def poz_nesnesi(r):
    """`kare_poz` kaydı (ya da kare sonucundaki `poz`) → Poz."""
    if not r["gecerli"]:
        return Poz(None, None, False)
    return Poz(tuple(r["konum_ned_m"]), tuple(r["q_wxyz"]))


def girdi_yukle(klasor, arac):
    ham = _rota.deney_env_oku()
    kimlik = int(ham["UAV_SYS_IDS"].split()[arac - 1])
    baslangic = tuple(float(v) for v in ham["UAV_START_POSES"].split()[arac - 1].split(","))
    return ham, kimlik, baslangic


def hesaplayici_olustur(ham, kimlik):
    return kh.KonumHesaplayici.yapilandirmadan(ham, kimlik)


# --- isaret -----------------------------------------------------------------------------------------------------------------------------------------------
def mod_isaret(klasor, arac, ham, kimlik, baslangic):
    kal = kh.kalibrasyon_oku()
    hes = hesaplayici_olustur(ham, kimlik)
    gercek = GercekPoz(jsonl(os.path.join(klasor, "gz_gercek_poz.jsonl")))
    kp = {r["n"]: r for r in jsonl(os.path.join(klasor, "kayit", f"kare_poz_{kimlik}.jsonl"))}
    with open(os.path.join(klasor, "konum_isaretleri.json"), encoding="utf-8") as f:
        isr = json.load(f)["isaretler"]
    kareler = jsonl(os.path.join(klasor, "konum_isaret_kareler.jsonl"))
    W, H = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
    gozlem, konumsuz, sinirda, eslesmeyen = [], [], 0, 0
    for fr in kareler:
        n, t = fr["n"], fr["damga_ns"]
        if not fr["bloklar"] or n not in kp:
            continue
        g = gercek.girdi(t, baslangic)
        if g is None:
            continue
        for b in fr["bloklar"]:
            if b["x"] <= 0 or b["y"] <= 0 or b["x"] + b["w"] >= W or b["y"] + b["h"] >= H:
                sinirda += 1                                    # görüntü kenarına değen blok: merkezi kırpılmış, ölçüme alınmaz (sayılır)
                continue
            # ilişkilendirme: gerçek pozla her işaretin izdüşümü; en yakın piksel (bağımsız ileri izdüşüm)
            aday = []
            for k, i in enumerate(isr):
                pk = ileri_izdusum(kal, (i["x"], i["y"], 0.0), g.konum, g.q, baslangic)
                if pk is not None:
                    aday.append((math.hypot(pk[0] - b["cx"], pk[1] - b["cy"]), k))
            if not aday or min(aday)[0] > 60:
                eslesmeyen += 1
                continue
            k = min(aday)[1]
            kutu = [b["cx"], b["cy"], b["cx"], b["cy"]]
            dogru = (isr[k]["x"], isr[k]["y"])
            sg = hes.hesapla(kutu, g)
            sp = hes.hesapla(kutu, poz_nesnesi(kp[n]))
            if sp.konum is None:
                konumsuz.append((n, k, sp.neden))
                continue
            e_px4 = math.hypot(sp.konum[0] - dogru[0], sp.konum[1] - dogru[1])
            e_gz = math.hypot(sg.konum[0] - dogru[0], sg.konum[1] - dogru[1]) if sg.konum else float("nan")
            gozlem.append({"n": n, "isaret": k, "u": b["cx"], "v": b["cy"], "e_px4": e_px4, "e_gz": e_gz, "poz_etkisi": math.hypot(sp.konum[0] - sg.konum[0], sp.konum[1] - sg.konum[1]) if sg.konum else float("nan"),
                          "mesafe": sp.mesafe_m})
    e1, e2 = [o["e_px4"] for o in gozlem], [o["e_gz"] for o in gozlem if math.isfinite(o["e_gz"])]
    pe = [o["poz_etkisi"] for o in gozlem if math.isfinite(o["poz_etkisi"])]
    print(f"BILGI isaret_gozlem: işaret {len(isr)}, kare {len(kareler)}, görünüm {len(gozlem)} (kenara değen blok {sinirda}, eşleşmeyen {eslesmeyen}, konumsuz {len(konumsuz)} {sorted({x[2] for x in konumsuz})})")
    print(f"TABLO isaret_hata_px4_m (PX4 enterpolasyonlu kare_poz; hesaplayıcı + poz hatası) {ozet(e1)}")
    print(f"TABLO isaret_hata_gercek_poz_m (Gazebo gerçek poz; yalnız hesaplayıcı + görüntü merkezi hatası) {ozet(e2)}")
    print(f"TABLO isaret_poz_etkisi_m (iki hesap arası fark) {ozet(pe)}")
    if gozlem:
        us, vs = [o["u"] for o in gozlem], [o["v"] for o in gozlem]
        print(f"BILGI isaret_piksel_kapsami u [{min(us):.0f}, {max(us):.0f}] v [{min(vs):.0f}, {max(vs):.0f}] (görüntü {W}×{H}); kesişim mesafesi {ozet([o['mesafe'] for o in gozlem])}")
    for k in range(len(isr)):
        v = [o["e_px4"] for o in gozlem if o["isaret"] == k]
        if v:
            print(f"TABLO isaret_{k} (yanal {isr[k]['yanal_m']:+.0f} m) {ozet(v)}")
    sonuc(len(gozlem) >= 20, "isaret_gorunum_sayisi", f"{len(gozlem)} işaret görünümü (≥ 20), {len({o['isaret'] for o in gozlem})}/{len(isr)} işaret")
    gorulen = {o["isaret"] for o in gozlem}
    sonuc(len(gorulen) == len(isr), "isaret_hepsi_gorundu", f"her işaret en az bir görünümde bulundu: {len(gorulen)}/{len(isr)} (görünmeyen {sorted(set(range(len(isr))) - gorulen)})")
    toplam_blok = len(gozlem) + len(konumsuz) + eslesmeyen
    oran = eslesmeyen / toplam_blok if toplam_blok else 1.0
    # eşik gerekçesi: eşleşmeyen blob = gerçek pozun izdüşümünün 60 px içinde olmayan kırmızı bölge (sahne artefaktı ya da yanlış ilişkilendirme/izdüşüm hatası); önceki koşularda 0/155. %5, birkaç geçici artefakta izin verir ama
    # izdüşüm ya da ilişkilendirme bozulduğunda (blokların çoğu eşleşmez) kesin başarısız olur
    sonuc(oran <= ESIK_ESLESMEYEN, "isaret_eslesmeyen_orani", f"eşleşmeyen blob oranı {oran:.3f} ({eslesmeyen}/{toplam_blok}) ≤ {ESIK_ESLESMEYEN:g}")
    sonuc(bool(gozlem) and max(e1) < ESIK_M, "isaret_hata_5m", f"her ölçüm < {ESIK_M:g} m: en çok {max(e1) if e1 else float('nan'):.3f} m (PX4 pozu), gerçek pozla {max(e2) if e2 else float('nan'):.3f} m")
    if e2:
        sonuc(max(e2) < ESIK_M, "isaret_hata_gercek_poz_5m", f"gerçek pozla her ölçüm < {ESIK_M:g} m: en çok {max(e2):.3f} m")


# --- rota -------------------------------------------------------------------------------------------------------------------------------------------------
def evre_siniflandir(gercek, t_ns, hiz_ms):
    """Gerçek poz hızından: askıda (hız < 0,3 m/s), düz (hız ≥ 0,9·ROTA_HIZ_MS ve ±1 sn içinde yön değişimi < 10°), aksi dönüş (hızlanma, yavaşlama, dönüş)."""
    v = gercek.hiz(t_ns)
    if v is None:
        return None
    sp = math.hypot(*v)
    if sp < 0.3:
        return "askida"
    a, b = gercek.hiz(t_ns - NS), gercek.hiz(t_ns + NS)
    if a is None or b is None or math.hypot(*a) < 0.3 or math.hypot(*b) < 0.3:
        return "donus"
    d = abs((math.degrees(math.atan2(a[0], a[1])) - math.degrees(math.atan2(b[0], b[1])) + 180) % 360 - 180)
    return "duz" if sp >= 0.9 * hiz_ms and d < 10.0 else "donus"


def zemin_olc(klasor, ham, baslangic, gercek, tel):
    x0, y0, z0 = baslangic
    sdf = os.path.join(KOK, "third_party", "PX4-Autopilot", "Tools", "simulation", "gz", "worlds", f"{ham['SIM_WORLD']}.sdf")
    metin = open(sdf, encoding="utf-8").read() if os.path.exists(sdf) else ""
    m = re.search(r'<model name="ground_plane">.*?<pose>([^<]*)</pose>', metin, re.S)
    print(f"BILGI zemin_dunya_dosyasi {os.path.relpath(sdf, KOK)}: ground_plane model pozu '{m.group(1).strip() if m else '?'}', çarpışma düzlemi normal 0 0 1 (düzlem, kalınlık yok), görsel düzlem 500×500")
    ilk = gercek.t[0] + 3 * NS
    yerde = [g for g, t in zip(gercek.p, gercek.t) if t <= ilk]
    zg = [p[2] for p in yerde]
    pk = Px4Poz(tel)
    zp = [z0 - k[2] for t, k in zip(pk.t, pk.konum) if t <= ilk]
    if zg and zp:
        print(f"TABLO zemin_arac_yerde (ilk 3 sim sn) model orijini z (Gazebo, ENU): ortanca {yuzdelik(zg, 50):+.4f} m [{min(zg):+.4f}, {max(zg):+.4f}] | PX4 z = z0 − d: ortanca {yuzdelik(zp, 50):+.4f} m "
              f"| fark (PX4 − Gazebo) {yuzdelik(zp, 50) - yuzdelik(zg, 50):+.4f} m | zemin düzlemine göre model orijini {yuzdelik(zg, 50) - float(ham['ZEMIN_Z_M']):+.4f} m (ZEMIN_Z_M = {ham['ZEMIN_Z_M']})")


def rota_tablosu(klasor, ham, kimlik, baslangic, gercek, px4, kp, kayma_ns, etiket, yontem="tam"):
    """`kayma_ns` ≠ 0 ise PX4 pozu o kadar GERİ örneklenir (Δ > 0: PX4 öndedir; PX4'ün t anındaki pozu gerçek pozun t + Δ anındakine karşılık gelir). yontem: "tam" = konum ve
    yönelim birlikte geri örneklenir; "konum" = yalnız konum geri örneklenir, yönelim kare üretim anındaki (kare_poz) kalır. Yalnız analiz; kodda düzeltme yok.
    Dönen: (tüm izdüşüm hataları, {evre: [hatalar]})."""
    hes = hesaplayici_olustur(ham, kimlik)
    hiz_ms = float(ham["ROTA_HIZ_MS"])
    hata = {}                       # (evre, piksel adı) → [m]
    mesafe, toplam, atlanan = [], 0, 0
    for r in kp.values():
        t = r["kare_ns"]
        g = gercek.girdi(t, baslangic)
        evre = evre_siniflandir(gercek, t, hiz_ms)
        if kayma_ns == 0:
            p = poz_nesnesi(r)
        else:
            p = px4.at(t - kayma_ns)
            if yontem == "konum" and p is not None and r["gecerli"]:
                p = Poz(p.konum, tuple(r["q_wxyz"]))                  # yalnız konum kaydırılır; yönelim kare anındaki (kare_poz) değerdir
        if g is None or evre is None or p is None or not getattr(p, "gecerli", True):
            atlanan += 1
            continue
        toplam += 1
        for ad, (u, v) in PIKSELLER.items():
            kutu = [u, v, u, v]
            sg, sp = hes.hesapla(kutu, g), hes.hesapla(kutu, p)
            if sg.konum is None or sp.konum is None:
                atlanan += 1
                continue
            e = math.hypot(sg.konum[0] - sp.konum[0], sg.konum[1] - sp.konum[1])
            for anahtar in ((evre, ad), (evre, "hepsi"), ("tum", ad), ("tum", "hepsi")):
                hata.setdefault(anahtar, []).append(e)
            mesafe.append(sp.mesafe_m)
    print(f"BILGI rota_kare ({etiket}): {toplam} görev karesi, atlanan (poz/gerçek poz yok ya da konumsuz) {atlanan}; kesişim mesafesi {ozet(mesafe)} m")
    for evre in ("duz", "donus", "askida", "tum"):
        for ad in ("hepsi", *PIKSELLER):
            v = hata.get((evre, ad))
            if v:
                print(f"TABLO rota_hata_m ({etiket}) evre={evre:6s} piksel={ad:8s} {ozet(v)}")
    tum = hata.get(("tum", "hepsi"), [])
    return tum, {e: hata.get((e, "hepsi"), []) for e in ("duz", "donus", "askida")}


def kayma_etkisi_yaz(klasor, ham, kimlik, baslangic, gercek, px4, kp, kayma_ms):
    """U26 için: Δ = 0, "tam poz geri örnekleme" ve "yalnız konum geri örnekleme" sayıları (ortanca / p95 / en çok; tümü ve evre bazında en çok)."""
    t0, e0 = rota_tablosu(klasor, ham, kimlik, baslangic, gercek, px4, kp, 0, "kayma=0")
    sonuc_ = {}
    for yontem, ad in (("tam", "tam poz (konum + yönelim)"), ("konum", "yalnız konum")):
        t1, e1 = rota_tablosu(klasor, ham, kimlik, baslangic, gercek, px4, kp, int(kayma_ms * 1e6), f"kayma={kayma_ms:g} ms yontem={yontem}", yontem)
        if not (t0 and t1):
            continue
        evre = " | ".join(f"{e} en çok {max(e0[e]):.3f} → {max(e1[e]):.3f} m" for e in ("duz", "donus") if e0[e] and e1[e])
        print(f"BILGI kayma_duzeltme_analizi yontem={yontem} [{ad}] Δ = {kayma_ms:g} ms geri örnekleme (yalnız analiz; kodda düzeltme yok): ortanca {yuzdelik(t0, 50):.3f} → {yuzdelik(t1, 50):.3f} m | "
              f"p95 {yuzdelik(t0, 95):.3f} → {yuzdelik(t1, 95):.3f} m | en çok {max(t0):.3f} → {max(t1):.3f} m | {evre}")
        sonuc_[yontem] = (t0, t1)
    return sonuc_


def mod_rota(klasor, arac, ham, kimlik, baslangic, kayma_ms):
    gercek = GercekPoz(jsonl(os.path.join(klasor, "gz_gercek_poz.jsonl")))
    tel = jsonl(os.path.join(klasor, "kayit", f"telemetri_{kimlik}.jsonl"))
    kp = {r["n"]: r for r in jsonl(os.path.join(klasor, "kayit", f"kare_poz_{kimlik}.jsonl"))}
    sonuc(gercek.var() and len(kp) > 0, "rota_girdi", f"gerçek poz örneği {len(gercek.t)}, kare_poz {len(kp)}")
    zemin_olc(klasor, ham, baslangic, gercek, tel)
    px4 = Px4Poz(tel)
    tum0, _ = rota_tablosu(klasor, ham, kimlik, baslangic, gercek, px4, kp, 0, "kayma=0")
    sonuc(bool(tum0) and max(tum0) < ESIK_M, "rota_hata_5m", f"her izdüşüm hatası < {ESIK_M:g} m (kayma düzeltmesi yok): en çok {max(tum0) if tum0 else float('nan'):.3f} m ({len(tum0)} izdüşüm)")
    if kayma_ms is not None:
        kayma_etkisi_yaz(klasor, ham, kimlik, baslangic, gercek, px4, kp, kayma_ms)


# --- iki_mod ----------------------------------------------------------------------------------------------------------------------------------------------
def mod_iki_mod(klasor, arac, ham, kimlik, baslangic, mod):
    hes = hesaplayici_olustur(ham, kimlik)
    sonuclar = jsonl(os.path.join(klasor, "kayit", f"kare_sonuc_{kimlik}.jsonl"))
    kp = {r["n"]: r for r in jsonl(os.path.join(klasor, "kayit", f"kare_poz_{kimlik}.jsonl"))}
    sayac = {"tespit": 0, "konumlu": 0, "poz_yok": 0, "kesisim_yok": 0}
    farkli, eksik_poz, yanlis_neden = [], 0, []
    sapma_maks = 0.0
    yanlis_ofset = []
    ofset_hes = kh.KonumHesaplayici.yapilandirmadan(ham, int(ham["UAV_SYS_IDS"].split()[0])) if arac != 1 else None
    for r in sonuclar:
        for t in r["tespitler"]:
            sayac["tespit"] += 1
            if mod == "merkezi":
                pr = r.get("poz")
            else:
                pr = kp.get(r["n"])
            if pr is None:
                eksik_poz += 1
                continue
            p = poz_nesnesi(pr)
            s = hes.hesapla(t["kutu"], p)
            if t["konum"] is None:
                sayac[t["konum_neden"]] += 1
                if s.konum is not None or s.neden != t["konum_neden"]:
                    yanlis_neden.append((r["n"], t["konum_neden"], s.neden))
                continue
            sayac["konumlu"] += 1
            if s.konum is None:
                yanlis_neden.append((r["n"], "konumlu", s.neden))
                continue
            d = math.hypot(s.konum[0] - t["konum"][0], s.konum[1] - t["konum"][1])
            sapma_maks = max(sapma_maks, d)
            if d >= 1e-6:
                farkli.append((r["n"], d))
            if ofset_hes is not None:
                so = ofset_hes.hesapla(t["kutu"], p)
                if so.konum is not None:
                    yanlis_ofset.append(math.hypot(so.konum[0] - t["konum"][0], so.konum[1] - t["konum"][1]))
    print(f"TABLO iki_mod_{mod}_arac{kimlik} tespit={sayac['tespit']} konumlu={sayac['konumlu']} poz_yok={sayac['poz_yok']} kesisim_yok={sayac['kesisim_yok']} | kare sonucu {len(sonuclar)} | en büyük çevrim dışı sapma {sapma_maks:.3e} m")
    if yanlis_ofset:
        print(f"BILGI iki_mod_{mod}_arac{kimlik} başlangıç ofseti denetimi: 1. aracın başlangıç konumuyla hesaplansaydı sapma ortanca {yuzdelik(yanlis_ofset, 50):.3f} m (beklenen: iki araç başlangıcı arası fark)")
    sonuc(sayac["tespit"] > 0 and not eksik_poz and not farkli and not yanlis_neden, f"iki_mod_{mod}_arac{kimlik}",
          f"{sayac['tespit']} tespit çevrim dışı yeniden hesaplandı ({'başlıktaki poz' if mod == 'merkezi' else 'kare_poz'}): sapma ≥ 1e-6 m olan {len(farkli)}, neden uyuşmayan {len(yanlis_neden)}, pozu bulunamayan {eksik_poz}")
    if ofset_hes is not None:
        b1 = tuple(float(v) for v in ham["UAV_START_POSES"].split()[0].split(","))
        beklenen = math.hypot(baslangic[0] - b1[0], baslangic[1] - b1[1])          # yanlış (1. araç) ofsetle sapma = ‖başlangıç_k − başlangıç_1‖ (yatay)
        olculen = yuzdelik(yanlis_ofset, 50) if yanlis_ofset else float("nan")
        sonuc(bool(yanlis_ofset) and abs(olculen - beklenen) <= 0.01, f"iki_mod_{mod}_arac{kimlik}_ofset",
              f"araç başlangıç ofseti kayıtta uygulanmış: yanlış ofsetle ortanca sapma {olculen:.3f} m, beklenen ‖başlangıç_{arac} − başlangıç_1‖ = {beklenen:.3f} m (±0,01 m)")


# --- kayma ------------------------------------------------------------------------------------------------------------------------------------------------
def px4_kaynak_satirlari():
    kok = os.path.join(KOK, "third_party", "PX4-Autopilot")
    istekler = [("src/modules/mavlink/streams/ODOMETRY.hpp", "msg.time_usec = odom.timestamp_sample"),
                ("src/modules/ekf2/EKF2.cpp", "odom.timestamp_sample = imu_sample.time_us"),
                ("src/modules/ekf2/params_gnss.yaml", "EKF2_GPS_DELAY:")]
    for yol, desen in istekler:
        p = os.path.join(kok, yol)
        try:
            for i, s in enumerate(open(p, encoding="utf-8"), 1):
                if desen in s:
                    ek = ""
                    if yol.endswith("params_gnss.yaml"):
                        ek = " | " + " ".join(x.strip() for x in open(p, encoding="utf-8").read().splitlines()[i:i + 9] if "default" in x or "unit" in x or "short" in x)
                    print(f"BILGI px4_kaynak {yol}:{i}: {s.strip()}{ek}")
                    break
            else:
                print(f"BILGI px4_kaynak {yol}: '{desen}' bulunamadı")
        except OSError as e:
            print(f"BILGI px4_kaynak {yol}: okunamadı ({e})")


def gz_kaynaklari_karsilastir(klasor):
    yol = os.path.join(klasor, "gz_poz_kaynaklari.jsonl")
    if not os.path.exists(yol):
        print("BILGI gz_poz_kaynaklari.jsonl yok: Gazebo poz kaynakları karşılaştırması atlandı")
        return None
    r = jsonl(yol)
    liste = next((x["liste"] for x in reversed(r) if x["k"] == "konular"), [])
    print(f"BILGI gz_poz_konulari {liste}")
    seri = {}
    for x in r:
        if x["k"] == "poz" and x["ad"] != "base_link":
            seri.setdefault(x["konu"], []).append(x)
    adlar = sorted(seri)
    if len(adlar) < 2:
        print("BILGI iki poz konusu gerekli; karşılaştırma atlandı")
        return None
    a, b = adlar[0], adlar[1]
    A = {k: (np.array([x["damga_ns"] for x in v]), np.array([x["p"] for x in v]), np.array([x["mono_ns"] for x in v])) for k, v in seri.items()}
    ta, pa, ma = A[a]
    tb, pb, mb = A[b]
    # damga farkı: her b iletisi için en yakın a damgası
    idx = np.clip(np.searchsorted(ta, tb), 1, len(ta) - 1)
    yakin = np.where(np.abs(ta[idx] - tb) < np.abs(ta[idx - 1] - tb), idx, idx - 1)
    d = (ta[yakin] - tb) / 1e6
    print(f"TABLO gz_damga_farki_ms ({a} − {b}, en yakın iletiler): ortanca {np.median(d):+.3f} | min {d.min():+.3f} | maks {d.max():+.3f} | ileti {len(ta)} / {len(tb)}")
    # değer farkı: aynı damga için (doğrusal örnekleme); gerçek hız ile 'damga farkı kadar kayma' karşılaştırması
    t0, t1 = max(ta[0], tb[0]) + 10 ** 8, min(ta[-1], tb[-1]) - 10 ** 8
    tt = np.arange(t0, t1, 20 * 10 ** 6)
    pa_i = np.stack([np.interp(tt, ta, pa[:, k]) for k in range(3)], 1)
    pb_i = np.stack([np.interp(tt, tb, pb[:, k]) for k in range(3)], 1)
    fark = np.linalg.norm(pa_i - pb_i, axis=1)
    print(f"TABLO gz_deger_farki_m (aynı damgada iki kaynağın konumu) ortanca {np.median(fark):.5f} | p95 {np.percentile(fark, 95):.5f} | en çok {fark.max():.5f}")
    # çapraz ilişki: a'yı Δ kadar kaydır, b'ye en iyi uyan Δ
    en = (None, 1e18)
    for dms in np.arange(-20, 20.5, 0.5):
        hata = np.linalg.norm(np.stack([np.interp(tt + dms * 1e6, ta, pa[:, k]) for k in range(3)], 1) - pb_i, axis=1)
        if np.sqrt(np.mean(hata ** 2)) < en[1]:
            en = (dms, float(np.sqrt(np.mean(hata ** 2))))
    print(f"TABLO gz_kaynak_kaymasi_ms ({a} değeri {b} ile en iyi eşleşmesi için damga ötelemesi) {en[0]:+.1f} ms (RMS {en[1]:.5f} m)")
    return d


def mod_kayma(klasor, arac, ham, kimlik, baslangic):
    x0, y0, z0 = baslangic
    px4_kaynak_satirlari()
    gz_kaynaklari_karsilastir(klasor)
    gercek = GercekPoz(jsonl(os.path.join(klasor, "gz_gercek_poz.jsonl")))
    tel = jsonl(os.path.join(klasor, "kayit", f"telemetri_{kimlik}.jsonl"))
    kabul = [t for t in tel if t["kabul"]]
    hiz_ms = float(ham["ROTA_HIZ_MS"])
    tk = np.array([t["kaynak_ns"] for t in kabul], dtype=np.int64)
    est = np.array([[x0 + t["konum_ned_m"][1], y0 + t["konum_ned_m"][0], z0 - t["konum_ned_m"][2]] for t in kabul])

    def gercek_xy(t_arr):
        return np.stack([np.interp(t_arr.astype(float), gercek.tf, gercek.p[:, k]) for k in range(3)], 1)

    # gerçek hız (±0,25 sn merkezi fark) ve evre
    v = (gercek_xy(tk + 250 * 10 ** 6) - gercek_xy(tk - 250 * 10 ** 6)) / 0.5
    hiz = np.hypot(v[:, 0], v[:, 1])
    gecerli = (tk > gercek.t[0] + NS) & (tk < gercek.t[-1] - NS)
    evre = np.array([("askida" if h < 0.3 else ("duz" if h >= 0.9 * hiz_ms else "donus")) for h in hiz])
    # düz evre: yalnız yönü sabit olanlar (±1 sn)
    vm, vp = (gercek_xy(tk - NS) - gercek_xy(tk)) , (gercek_xy(tk + NS) - gercek_xy(tk))
    yon_fark = np.abs((np.degrees(np.arctan2(vm[:, 0], vm[:, 1])) - np.degrees(np.arctan2(vp[:, 0], vp[:, 1])) + 180) % 360 - 180)
    evre = np.where((evre == "duz") & (np.abs(yon_fark - 180) > 10), "donus", evre)   # geri farkın tersi (−vm) ile ileri fark aynı yönde değilse dönüş
    print("BILGI kayma_evre_sayilari " + " ".join(f"{e}={int(np.sum((evre == e) & gecerli))}" for e in ("duz", "donus", "askida")))
    deltalar = np.arange(-50, 300.5, 2.0)

    def rms_egri(maske):
        s = []
        for dms in deltalar:
            g = gercek_xy(tk[maske] + int(dms * 1e6))
            s.append(float(np.sqrt(np.mean((est[maske, 0] - g[:, 0]) ** 2 + (est[maske, 1] - g[:, 1]) ** 2))))
        return np.array(s)

    sonuclar = {}
    for e in ("duz", "donus", "askida", "tum"):
        maske = gecerli & ((evre == e) if e != "tum" else (hiz >= 0.0))
        if np.sum(maske) < 20:
            print(f"BILGI kayma_{e}: örnek {int(np.sum(maske))} (yetersiz)")
            continue
        egri = rms_egri(maske)
        i = int(np.argmin(egri))
        i0 = int(np.argmin(np.abs(deltalar)))
        ort_hiz = float(np.mean(hiz[maske]))
        sonuclar[e] = deltalar[i]
        print(f"TABLO kayma_capraz_iliski evre={e:6s} n={int(np.sum(maske)):5d} ortalama gerçek hız {ort_hiz:5.2f} m/s | en iyi Δ {deltalar[i]:+6.1f} ms (RMS {egri[i]:.3f} m) | Δ=0'da RMS {egri[i0]:.3f} m")
    # hız–kayma ilişkisi: iz boyunca işaretli hata = Δ·hız + sabit (hareket yönünde; gerçek hız ve gerçek konum aynı anda)
    h_mask = gecerli & (hiz >= 0.5)
    g0 = gercek_xy(tk)
    u = v[:, :2] / np.maximum(hiz, 1e-9)[:, None]
    e_iz = (est[:, 0] - g0[:, 0]) * u[:, 0] + (est[:, 1] - g0[:, 1]) * u[:, 1]
    e_yan = (est[:, 0] - g0[:, 0]) * (-u[:, 1]) + (est[:, 1] - g0[:, 1]) * u[:, 0]
    if np.sum(h_mask) > 50:
        egim, kesim = np.polyfit(hiz[h_mask], e_iz[h_mask], 1)
        r = float(np.corrcoef(hiz[h_mask], e_iz[h_mask])[0, 1])
        print(f"TABLO kayma_hiz_iliskisi iz boyunca hata = {egim * 1000:+.1f} ms · hız {kesim:+.3f} m (n={int(np.sum(h_mask))}, korelasyon {r:+.3f}); yanal hata ortanca {np.median(e_yan[h_mask]):+.3f} m")
        for lo, hi in ((0.5, 2.0), (2.0, 4.0), (4.0, 4.6), (4.6, 99.0)):
            m = h_mask & (hiz >= lo) & (hiz < hi)
            if np.sum(m) >= 10:
                print(f"TABLO kayma_hiz_araligi [{lo:g}, {hi:g}) m/s n={int(np.sum(m)):5d} iz boyunca hata ortanca {np.median(e_iz[m]):+.3f} m | ortanca hız {np.median(hiz[m]):.2f} m/s | ima edilen Δ {1000 * np.median(e_iz[m]) / np.median(hiz[m]):+.1f} ms")
    askida = gecerli & (hiz < 0.3)
    if np.sum(askida) > 20:
        print(f"TABLO kayma_askida (hız < 0,3 m/s; yerde ve havada) yatay ofset ortanca {np.median(np.hypot(est[askida, 0] - g0[askida, 0], est[askida, 1] - g0[askida, 1])):.3f} m | n={int(np.sum(askida))}")
    sonuc(bool(sonuclar), "kayma_olculdu", "evre bazında çapraz ilişki tahmini yapıldı: " + ", ".join(f"{k}: {v:+.1f} ms" for k, v in sonuclar.items()) + " (eşik yok; düzeltme kodda yapılmaz)")
    # kaymanın konum hatasına etkisi: rota izdüşüm tablosu Δ = 0 ve Δ = ölçülen (düz evre; yoksa tümü) için; iki yöntemle (tam poz / yalnız konum); kodda düzeltme YOKTUR
    # İŞARET KURALI (tek): Δ > 0 = PX4 gerçek pozun ÖNÜNDEDİR (PX4'ün t anındaki pozu gerçek pozun t + Δ anındakine karşılık gelir); iz boyunca hata = + Δ · hız
    secilen = sonuclar.get("duz", sonuclar.get("tum"))
    if secilen is not None:
        px4 = Px4Poz(tel)
        kp = {r["n"]: r for r in jsonl(os.path.join(klasor, "kayit", f"kare_poz_{kimlik}.jsonl"))}
        kayma_etkisi_yaz(klasor, ham, kimlik, baslangic, gercek, px4, kp, secilen)


def ana(argv):
    a = list(argv)
    if len(a) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    mod, klasor = a.pop(0), a.pop(0)
    arac, kayma_ms, imod = None, None, None
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            arac = int(a.pop(0))
        elif k == "--kayma-ms" and a:
            kayma_ms = float(a.pop(0))
        elif k == "--mod" and a:
            imod = a.pop(0)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if arac is None or mod not in ("isaret", "rota", "iki_mod", "kayma") or (mod == "iki_mod" and imod not in ("ucta", "merkezi")):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        ham, kimlik, baslangic = girdi_yukle(klasor, arac)
        if mod == "isaret":
            mod_isaret(klasor, arac, ham, kimlik, baslangic)
        elif mod == "rota":
            mod_rota(klasor, arac, ham, kimlik, baslangic, kayma_ms)
        elif mod == "iki_mod":
            mod_iki_mod(klasor, arac, ham, kimlik, baslangic, imod)
        else:
            mod_kayma(klasor, arac, ham, kimlik, baslangic)
    except OSError as e:
        print(f"(-) girdi okunamadı: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
