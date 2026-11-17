#!/usr/bin/env python3
"""DENEME 2 (depoya girmez): deprem sonrası şehir görünümü. sehir_uret.py'nin geliştirilmiş hali.

Kullanım: sehir_uret2.py <tohum> <cikti_klasoru>
Yenilikler: çatlak asfalt, parke kaldırımlar (kavşaklarda kesik), tozlu arsa zemini, binalardan caddelere taşan kırık taş
alanları ve toz lekeleri (yassı; görüş kapatmaz), daha çok moloz (hasarlı beton dahil), bazı arabaların üstünde beton parçaları,
kenar şeritlerinde küçük yıkık evler. Hedefler: eğitim sahnesi biçiminde 25 insan + 15 enkaz (toplam ≤ 40, merkezler ≥ 6 m),
engellerden en az 3 m uzakta. Çıktılar sehir_uret.py ile aynı (sahne.json, dunya.sdf, temel.sdf, parcalar/, sira.json).
"""
import json
import math
import os
import random
import sys

KOK = "/home/mikail/blm498-diploma-calismasi"
sys.path.insert(0, KOK + "/araclar")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sahne_uret as su  # noqa: E402
import sozlesme_dogrula as sd  # noqa: E402
from sehir_uret import ARABALAR, BINALAR, include  # noqa: E402

DENEME = KOK + "/.generated/deneme_sehir"
YOLLAR = [-120.0, -60.0, 0.0, 60.0, 120.0]
YOL_GEN, KALDIRIM = 12.0, 2.5
ADALAR = [-90.0, -30.0, 30.0, 90.0]
KENAR = [-138.0, 138.0]
MOLOZ_DOKU = [("sahne_dokulari", "Concrete034"), ("sahne_dokulari", "Bricks059"), ("sahne_dokulari", "WoodSiding008"),
              ("sehir_dokular", "Concrete044B")]
INSAN_SAYI, ENKAZ_SAYI, ARALIK, ENGEL_PAYI = 25, 15, 6.0, 3.0
BOLUM = "egitim"   # "test" ise belge kuralı: 15 + 15, merkezler ≥ 10 m, test'e özel varyantlar dahil


def doku(klasor, ad, ek="renk"):
    dosya = f"{ad}_sehir_renk.jpg" if klasor == "sehir_dokular" else f"{ad}_{ek}.jpg"
    return (f"<material><diffuse>1 1 1 1</diffuse><specular>0 0 0 1</specular><pbr><metal><albedo_map>model://{klasor}/{ad}/{dosya}"
            f"</albedo_map><roughness>1</roughness><metalness>0</metalness></metal></pbr></material>")


class Ag:
    """Tek OBJ'de çok yüzey; UV dünya koordinatından (doku_m'de bir tekrar)."""
    def __init__(self, doku_m):
        self.v, self.vt, self.f, self.d = [], [], [], doku_m

    def cokgen(self, noktalar, z):
        b = len(self.v)
        for x, y in noktalar:
            self.v.append(f"v {x:.3f} {y:.3f} {z:.3f}")
            self.vt.append(f"vt {x / self.d:.4f} {y / self.d:.4f}")
        for i in range(1, len(noktalar) - 1):
            self.f.append(f"f {b + 1}/{b + 1}/1 {b + i + 1}/{b + i + 1}/1 {b + i + 2}/{b + i + 2}/1")

    def dortgen(self, x0, y0, x1, y1, z):
        self.cokgen([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z)

    def yaz(self, yol):
        os.makedirs(os.path.dirname(yol), exist_ok=True)
        with open(yol, "w") as fh:
            fh.write("# deneme 2\n" + "\n".join(self.v + self.vt) + "\nvn 0 0 1\n" + "\n".join(self.f) + "\n")


def lekeli(rnd, x, y, r):
    n = rnd.randint(9, 14)
    return [(x + r * rnd.uniform(0.6, 1.15) * math.cos(2 * math.pi * k / n), y + r * rnd.uniform(0.6, 1.15) * math.sin(2 * math.pi * k / n))
            for k in range(n)]


def yuzey_modeli(ad, uri, malzeme):
    return (f'    <model name="{ad}"><static>true</static><link name="link"><visual name="v"><geometry><mesh><uri>{uri}</uri></mesh>'
            f'</geometry>{malzeme}</visual></link></model>')


def moloz_sdf(a, ad, x, y, yaw, rnd, olcek, z0=0.0):
    satir = [f'    <model name="{ad}"><static>true</static><pose>{su._poz(x, y, z0, 0, 0, yaw)}</pose><link name="link">']
    for k, (px, py, pz, r, p, yw, sx, sy, sz, ds) in enumerate(su.enkaz_parcalari(a, rnd, 0.45)):
        kl, dk = MOLOZ_DOKU[ds % len(MOLOZ_DOKU)]
        satir.append(f'      <visual name="p{k}"><pose>{su._poz(px * olcek, py * olcek, pz * olcek, r, p, yw)}</pose>'
                     f'<geometry><box><size>{su._f(sx * olcek)} {su._f(sy * olcek)} {su._f(sz * olcek)}</size></box></geometry>'
                     f'{doku(kl, dk)}</visual>')
    satir.append("    </link></model>")
    return "\n".join(satir)


def main(tohum, cikti):
    a = su.Ayar()
    rnd = random.Random(tohum)
    os.makedirs(os.path.join(cikti, "parcalar"), exist_ok=True)
    md = os.path.join(DENEME, "modeller", f"sehir_yuzey_{tohum}", "meshes")
    engeller, sira, parca = [], {k: [] for k in ("yuzeyler", "binalar", "moloz", "arabalar", "hedefler")}, {}

    # yüzeyler: arsa tozu, cadde, kaldırım, taşan kırık taş ve toz lekeleri (yassı, üst üste katmanlı)
    arsa, yol, kal, tas, toz = Ag(5.0), Ag(5.0), Ag(3.0), Ag(4.0), Ag(5.0)
    arsa.dortgen(-150, -150, 150, 150, 0.005)
    for c in YOLLAR:
        yol.dortgen(c - YOL_GEN / 2, -150, c + YOL_GEN / 2, 150, 0.02)
        yol.dortgen(-150, c - YOL_GEN / 2, 150, c + YOL_GEN / 2, 0.021)
    sinir = [-150.0] + YOLLAR + [150.0]
    for c in YOLLAR:
        for i in range(len(sinir) - 1):          # iki kavşak arası kaldırım parçaları
            s0 = sinir[i] + (YOL_GEN / 2 if sinir[i] in YOLLAR else 0)
            s1 = sinir[i + 1] - (YOL_GEN / 2 if sinir[i + 1] in YOLLAR else 0)
            for t in (-1, 1):
                k0, k1 = sorted((c + t * YOL_GEN / 2, c + t * (YOL_GEN / 2 + KALDIRIM)))
                kal.dortgen(k0, s0, k1, s1, 0.03)
                kal.dortgen(s0, k0, s1, k1, 0.03)
    parca["yuzey_arsa"] = yuzey_modeli("yuzey_arsa", f"model://sehir_yuzey_{tohum}/meshes/arsa.obj", doku("sehir_dokular", "Ground054"))
    parca["yuzey_yol"] = yuzey_modeli("yuzey_yol", f"model://sehir_yuzey_{tohum}/meshes/yol.obj", doku("sehir_dokular", "Asphalt026C"))
    parca["yuzey_kaldirim"] = yuzey_modeli("yuzey_kaldirim", f"model://sehir_yuzey_{tohum}/meshes/kaldirim.obj", doku("sehir_dokular", "PavingStones070"))

    def bina_koy(n, mdl, lx, ly, bx, by, yaw, tasma):
        ad = f"bina_{n}_{mdl}"
        parca[ad] = include(ad, f"model://{mdl}", bx, by, 0, math.radians(yaw))
        sira["binalar"].append(ad)
        r = math.hypot(lx, ly) / 2
        engeller.append((bx, by, r))
        # binanın altından caddeye doğru taşan kırık taş ve toz
        for _ in range(rnd.randint(2, 4)):
            aci = rnd.uniform(0, 2 * math.pi)
            d = r * rnd.uniform(0.5, 1.0)
            tas.cokgen(lekeli(rnd, bx + d * math.cos(aci), by + d * math.sin(aci), rnd.uniform(5, 9) * tasma), 0.045)
        for _ in range(rnd.randint(2, 5)):
            aci = rnd.uniform(0, 2 * math.pi)
            d = r + rnd.uniform(2, 14)
            toz.cokgen(lekeli(rnd, bx + d * math.cos(aci), by + d * math.sin(aci), rnd.uniform(3, 8)), 0.04)
        for m in range(rnd.randint(8, 16)):           # moloz yığınları; bir kısmı kaldırım ve caddeye taşar
            aci = rnd.uniform(0, 2 * math.pi)
            d = r + rnd.uniform(-2, 12)
            mx, my = bx + d * math.cos(aci), by + d * math.sin(aci)
            if abs(mx) > 147 or abs(my) > 147:
                continue
            ad = f"moloz_{n}_{m}"
            parca[ad] = moloz_sdf(a, ad, mx, my, rnd.uniform(0, 2 * math.pi), rnd, rnd.uniform(0.8, 2.2))
            sira["moloz"].append(ad)
            engeller.append((mx, my, 3.5))

    n = 0
    for ax in ADALAR:
        for ay in ADALAR:
            if rnd.random() < 0.12:
                for m in range(rnd.randint(6, 10)):
                    mx, my = ax + rnd.uniform(-20, 20), ay + rnd.uniform(-20, 20)
                    ad = f"moloz_{n}_b{m}"
                    parca[ad] = moloz_sdf(a, ad, mx, my, rnd.uniform(0, 2 * math.pi), rnd, rnd.uniform(1.0, 2.4))
                    sira["moloz"].append(ad)
                    engeller.append((mx, my, 4.0))
                tas.cokgen(lekeli(rnd, ax, ay, rnd.uniform(8, 14)), 0.045)
                n += 1
                continue
            mdl, (lx, ly), _h = rnd.choice(BINALAR)
            r = math.hypot(lx, ly) / 2
            pay = max(0.0, 24 - r) * 0.5
            bina_koy(n, mdl, lx, ly, ax + rnd.uniform(-pay, pay), ay + rnd.uniform(-pay, pay),
                     rnd.choice([0, 90, 180, 270]) + rnd.uniform(-8, 8), 1.0)
            n += 1
    # kenar şeritleri: küçük yıkık evler (uzun kenar şeride paralel)
    ev = BINALAR[0]
    for k in KENAR:
        for s in ADALAR:
            for yatay in (False, True):
                if rnd.random() < 0.35:
                    continue
                bx, by = (s, k) if yatay else (k, s)
                yaw = (0 if yatay else 90) + rnd.choice([0, 180]) + rnd.uniform(-6, 6)
                bina_koy(n, ev[0], ev[1][0], ev[1][1], bx + rnd.uniform(-8, 8) * (yatay), by + rnd.uniform(-8, 8) * (not yatay), yaw, 0.7)
                n += 1

    # arabalar: park edilmiş, bir kısmı savrulmuş, bir kısmının üstünde beton parçaları
    k = 0
    for c in YOLLAR:
        for yon in ("x", "y"):
            for serit in (-1, 1):
                s = -147.0
                while s < 147.0:
                    s += rnd.uniform(6, 14)
                    if any(abs(s - d) < 10 for d in YOLLAR) or rnd.random() > 0.33:
                        continue
                    mdl, ek, uz, gen = rnd.choice(ARABALAR)
                    ofs = serit * (YOL_GEN / 2 - gen / 2 - 0.4)
                    savrul = rnd.random() < 0.2
                    sap = rnd.uniform(-50, 50) if savrul else rnd.uniform(-4, 4)
                    if savrul:
                        ofs *= rnd.uniform(-0.2, 0.7)
                    x, y, yaw = (c + ofs, s, math.pi / 2) if yon == "x" else (s, c + ofs, 0.0)
                    yaw += ek + math.radians(sap) + (math.pi if rnd.random() < 0.5 else 0)
                    ad = f"araba_{k}_{mdl}"
                    parca[ad] = include(ad, f"model://{mdl}", x, y, 0, yaw)
                    sira["arabalar"].append(ad)
                    engeller.append((x, y, uz / 2 + 0.5))
                    if rnd.random() < 0.22:            # üstüne düşmüş beton parçaları
                        ad2 = f"moloz_araba_{k}"
                        parca[ad2] = moloz_sdf(a, ad2, x, y, rnd.uniform(0, 2 * math.pi), rnd, 0.45, z0=1.2)
                        sira["moloz"].append(ad2)
                    if rnd.random() < 0.3:
                        toz.cokgen(lekeli(rnd, x, y, rnd.uniform(2.5, 5)), 0.04)
                    k += 1

    for adi, ag in (("arsa", arsa), ("yol", yol), ("kaldirim", kal), ("tas", tas), ("toz", toz)):
        ag.yaz(os.path.join(md, f"{adi}.obj"))
    parca["yuzey_tas"] = yuzey_modeli("yuzey_tas", f"model://sehir_yuzey_{tohum}/meshes/tas.obj", doku("sehir_dokular", "Gravel040"))
    parca["yuzey_toz"] = yuzey_modeli("yuzey_toz", f"model://sehir_yuzey_{tohum}/meshes/toz.obj", doku("sehir_dokular", "Ground054"))
    sira["yuzeyler"] = ["yuzey_arsa", "yuzey_yol", "yuzey_kaldirim", "yuzey_tas", "yuzey_toz"]

    # hedefler (eğitim sahnesi biçimi)
    c = a.c
    siniflar = ["insan"] * INSAN_SAYI + ["enkaz"] * ENKAZ_SAYI
    rnd.shuffle(siniflar)
    hedefler, noktalar = [], []
    for i, s in enumerate(siniflar):
        for _ in range(80000):
            x, y = round(rnd.uniform(-145, 145), 2), round(rnd.uniform(-145, 145), 2)
            if all(math.hypot(x - px, y - py) >= ARALIK for px, py in noktalar) and \
               all(math.hypot(x - ex, y - ey) >= er + ENGEL_PAYI for ex, ey, er in engeller):
                break
        else:
            raise SystemExit(f"hedef {i + 1} yerleştirilemedi")
        noktalar.append((x, y))
        secenek = c.varyant[s] if BOLUM == "test" else [v for v in c.varyant[s] if v not in c.test_ozel[s]]
        hedefler.append({"kimlik": f"H{i + 1:02d}", "sinif": s, "x": x, "y": y, "yonelim_derece": su._aci(rnd),
                         "gorunum_varyanti": rnd.choice(secenek)})
    sahne = {"surum": 1, "tur": "sahne", "sahne_kimligi": f"S-SEHIR-{BOLUM.upper()}-DENEME-{tohum}", "bolum": BOLUM, "tohum": tohum,
             "alan": {"cerceve": "yerel_ENU", "merkez_m": [0, 0], "genislik_m": 300, "yukseklik_m": 300},
             "isik": {"gunes_azimut_derece": 230.0, "gunes_yukseklik_derece": 42.0}, "zemin": {"gorunum_varyanti": "zemin_c"},
             "hedefler": hedefler}
    hatalar = sd.dogrula_sahne(c, sahne)
    if hatalar:
        raise SystemExit("\n".join(hatalar))
    json.dump(sahne, open(os.path.join(cikti, "sahne.json"), "w"), ensure_ascii=False, indent=2)
    for t in hedefler:
        ad = f"hedef_{t['kimlik']}"
        parca[ad] = "\n".join(su.hedef_sdf(a, sahne, t))
        sira["hedefler"].append(ad)
    tam = su.dunya_uret(a, sahne)
    i = tam.index('    <model name="hedef_')
    sehir = "\n".join(parca[x] for g in ("yuzeyler", "binalar", "moloz", "arabalar") for x in sira[g]) + "\n"
    open(os.path.join(cikti, "dunya.sdf"), "w").write(tam[:i] + sehir + tam[i:])
    j = tam.index("    <spherical_coordinates>")
    open(os.path.join(cikti, "temel.sdf"), "w").write(tam[:i] + tam[j:])
    for ad, metin in parca.items():
        open(os.path.join(cikti, "parcalar", ad + ".sdf"), "w").write(f'<?xml version="1.0"?>\n<sdf version="1.9">\n{metin}\n</sdf>\n')
    json.dump(sira, open(os.path.join(cikti, "sira.json"), "w"), indent=1)
    print(f"yüzey {len(sira['yuzeyler'])}, bina {len(sira['binalar'])}, moloz {len(sira['moloz'])}, araba {len(sira['arabalar'])}, "
          f"hedef {len(hedefler)} ({INSAN_SAYI} insan + {ENKAZ_SAYI} enkaz)")


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
