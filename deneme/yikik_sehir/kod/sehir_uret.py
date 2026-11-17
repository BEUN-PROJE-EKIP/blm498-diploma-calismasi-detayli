#!/usr/bin/env python3
"""DENEME (depoya girmez): yıkılmış şehir görünümlü sahne. Kullanıcının görmesi için; Ömer'e sorulacak kararlardan önce.

Kullanım: sehir_uret.py <tohum> <cikti_klasoru>
Çıktı: sahne.json (sözleşme biçiminde, 15 insan + 15 enkaz hedef), dunya.sdf (tam dünya), parcalar/*.sdf (canlı ekleme için
tek tek modeller) ve sira.json (ekleme sırası: yollar, binalar, moloz, arabalar, hedefler).
Varlıklar: .generated/varliklar/modeller (A1) + .generated/deneme_sehir/modeller (Fuel CC0: yıkık binalar, arabalar, asfalt).
"""
import json
import math
import os
import random
import sys

KOK = "/home/mikail/blm498-diploma-calismasi"
sys.path.insert(0, KOK + "/araclar")
import sahne_uret as su  # noqa: E402
import sozlesme_dogrula as sd  # noqa: E402

DENEME = KOK + "/.generated/deneme_sehir"
YOLLAR = [-120.0, -60.0, 0.0, 60.0, 120.0]      # cadde orta çizgileri (x = sabit ve y = sabit)
YOL_GEN = 12.0
DOKU_M = 5.0
ADALAR = [-90.0, -30.0, 30.0, 90.0]
# yıkık binalar: (model, xy boyut m (ölçekli), yükseklik m)
BINALAR = [("collapsed_house", (16.2, 12.9), 5.8), ("collapsed_fire_station", (28.0, 18.3), 11.5),
           ("collapsed_police_station", (19.6, 22.1), 8.6), ("collapsed_industrial", (23.1, 19.7), 24.0)]
# arabalar: (model, uzunluk ekseni ek dönüşü (rad), uzunluk, genişlik)
ARABALAR = [("hatchback", 0.0, 4.0, 2.1), ("hatchback_blue", 0.0, 4.0, 2.1), ("hatchback_red", 0.0, 4.0, 2.1),
            ("suv", 0.0, 5.0, 2.6), ("pickup", 0.0, 5.7, 2.5), ("prius_hybrid", math.pi / 2, 4.6, 2.0)]
MOLOZ_DOKU = ["Concrete034", "Bricks059", "WoodSiding008"]


def model(ad, poz, ic):
    return f'<?xml version="1.0"?>\n<sdf version="1.9">\n{ic(ad, poz)}\n</sdf>\n'


def include(ad, uri, x, y, z, yaw, roll=0.0, pitch=0.0):
    # dış model sarmalı: hem dünya dosyasında hem tek başına (EntityFactory) geçerli; iç model statik
    return (f'    <model name="{ad}"><static>true</static><pose>{su._poz(x, y, z, roll, pitch, yaw)}</pose>'
            f'<include><uri>{uri}</uri><static>true</static></include></model>')


def yol_agi(cikti):
    """Caddeler: her şerit için UV'si DOKU_M'de tekrarlayan dörtgenler (tek OBJ)."""
    v, vt, f = [], [], []
    h = 150.0
    for c in YOLLAR:
        for yon in ("x", "y"):
            if yon == "x":      # x = c sabit, y boyunca uzanan cadde
                k = [(c - YOL_GEN / 2, -h), (c + YOL_GEN / 2, -h), (c + YOL_GEN / 2, h), (c - YOL_GEN / 2, h)]
            else:
                k = [(-h, c - YOL_GEN / 2), (h, c - YOL_GEN / 2), (h, c + YOL_GEN / 2), (-h, c + YOL_GEN / 2)]
            b = len(v)
            for x, y in k:
                v.append(f"v {x:.3f} {y:.3f} 0.02")
                vt.append(f"vt {x / DOKU_M:.4f} {y / DOKU_M:.4f}")
            f.append(f"f {b + 1}/{b + 1}/1 {b + 2}/{b + 2}/1 {b + 3}/{b + 3}/1")
            f.append(f"f {b + 1}/{b + 1}/1 {b + 3}/{b + 3}/1 {b + 4}/{b + 4}/1")
    os.makedirs(os.path.dirname(cikti), exist_ok=True)
    with open(cikti, "w") as fh:
        fh.write("# deneme: caddeler\n" + "\n".join(v + vt) + "\nvn 0 0 1\n" + "\n".join(f) + "\n")


def moloz_sdf(a, ad, x, y, yaw, rnd, olcek):
    """Arka plan moloz yığını (hedef değil): A1 enkaz parçalarıyla aynı üretici, ölçekli."""
    satir = [f'    <model name="{ad}"><static>true</static><pose>{su._poz(x, y, 0, 0, 0, yaw)}</pose><link name="link">']
    for k, (px, py, pz, r, p, yw, sx, sy, sz, ds) in enumerate(su.enkaz_parcalari(a, rnd, 0.4)):
        doku = MOLOZ_DOKU[ds % len(MOLOZ_DOKU)]
        satir.append(f'      <visual name="p{k}"><pose>{su._poz(px * olcek, py * olcek, pz * olcek, r, p, yw)}</pose>'
                     f'<geometry><box><size>{su._f(sx * olcek)} {su._f(sy * olcek)} {su._f(sz * olcek)}</size></box></geometry>'
                     f'{su._doku_malzeme(doku)}</visual>')
    satir.append("    </link></model>")
    return "\n".join(satir)


def yol_ici(x, y):
    return any(abs(x - c) < YOL_GEN / 2 or abs(y - c) < YOL_GEN / 2 for c in YOLLAR)


def main(tohum, cikti):
    a = su.Ayar()
    rnd = random.Random(tohum)
    os.makedirs(os.path.join(cikti, "parcalar"), exist_ok=True)
    yol_agi(os.path.join(DENEME, "modeller", "sehir_yol", "meshes", "yollar.obj"))
    engeller = []       # (x, y, yarıçap) hedef yerleşiminde kaçınılacak
    sira = {"yollar": [], "binalar": [], "moloz": [], "arabalar": [], "hedefler": []}
    parca = {}

    # caddeler
    parca["sehir_yollar"] = ('    <model name="sehir_yollar"><static>true</static><link name="link"><visual name="v"><geometry><mesh>'
                             '<uri>model://sehir_yol/meshes/yollar.obj</uri></mesh></geometry><material><diffuse>1 1 1 1</diffuse>'
                             '<specular>0 0 0 1</specular><pbr><metal><albedo_map>model://asphalt_plane/materials/textures/tarmac.png</albedo_map>'
                             '<roughness>1</roughness><metalness>0</metalness></metal></pbr></material></visual></link></model>')
    sira["yollar"].append("sehir_yollar")

    # yıkık binalar ve çevrelerindeki moloz
    n = 0
    for ax in ADALAR:
        for ay in ADALAR:
            if rnd.random() < 0.15:      # boş arsa
                bx, by = ax, ay
                for m in range(rnd.randint(4, 8)):
                    mx, my = bx + rnd.uniform(-18, 18), by + rnd.uniform(-18, 18)
                    ad = f"moloz_{n}_{m}"
                    parca[ad] = moloz_sdf(a, ad, mx, my, rnd.uniform(0, 2 * math.pi), rnd, rnd.uniform(1.0, 2.2))
                    sira["moloz"].append(ad)
                    engeller.append((mx, my, 4.0))
                n += 1
                continue
            mdl, (lx, ly), _h = rnd.choice(BINALAR)
            yaw = rnd.choice([0, 90, 180, 270]) + rnd.uniform(-8, 8)
            r = math.hypot(lx, ly) / 2
            pay = max(0.0, 24 - r)
            bx, by = ax + rnd.uniform(-pay, pay) * 0.5, ay + rnd.uniform(-pay, pay) * 0.5
            ad = f"bina_{n}_{mdl}"
            parca[ad] = include(ad, f"model://{mdl}", bx, by, 0, math.radians(yaw))
            sira["binalar"].append(ad)
            engeller.append((bx, by, r))
            for m in range(rnd.randint(5, 10)):          # binadan dökülen moloz
                aci = rnd.uniform(0, 2 * math.pi)
                d = r + rnd.uniform(0, 5)
                mx, my = bx + d * math.cos(aci), by + d * math.sin(aci)
                if abs(mx - ax) > 23 or abs(my - ay) > 23:
                    continue
                ad = f"moloz_{n}_{m}"
                parca[ad] = moloz_sdf(a, ad, mx, my, rnd.uniform(0, 2 * math.pi), rnd, rnd.uniform(1.0, 2.0))
                sira["moloz"].append(ad)
                engeller.append((mx, my, 4.0))
            n += 1

    # park edilmiş ve savrulmuş arabalar
    k = 0
    for c in YOLLAR:
        for yon in ("x", "y"):
            for serit in (-1, 1):
                s = -147.0
                while s < 147.0:
                    s += rnd.uniform(6, 14)
                    if any(abs(s - d) < 10 for d in YOLLAR) or rnd.random() > 0.35:
                        continue
                    mdl, ek, uz, gen = rnd.choice(ARABALAR)
                    ofs = serit * (YOL_GEN / 2 - gen / 2 - 0.4)
                    savrul = rnd.random() < 0.15
                    sap = rnd.uniform(-45, 45) if savrul else rnd.uniform(-4, 4)
                    if savrul:
                        ofs *= rnd.uniform(0.0, 0.7)
                    if yon == "x":       # cadde y boyunca: araba uzunluğu y ekseninde
                        x, y, yaw = c + ofs, s, math.pi / 2
                    else:
                        x, y, yaw = s, c + ofs, 0.0
                    yaw += ek + math.radians(sap) + (math.pi if rnd.random() < 0.5 else 0)
                    ad = f"araba_{k}_{mdl}"
                    parca[ad] = include(ad, f"model://{mdl}", x, y, 0, yaw)
                    sira["arabalar"].append(ad)
                    engeller.append((x, y, uz / 2 + 0.5))
                    k += 1

    # hedefler: açık alanda, engellerden ve birbirinden uzak (sözleşme kuralları + örtülmeme payı)
    c = a.c
    siniflar = ["insan"] * c.test_sayi["insan"] + ["enkaz"] * c.test_sayi["enkaz"]
    rnd.shuffle(siniflar)
    hedefler, noktalar = [], []
    for i, s in enumerate(siniflar):
        for _ in range(50000):
            x, y = round(rnd.uniform(-145, 145), 2), round(rnd.uniform(-145, 145), 2)
            if all(math.hypot(x - px, y - py) >= c.mesafe_test for px, py in noktalar) and \
               all(math.hypot(x - ex, y - ey) >= er + 3.5 for ex, ey, er in engeller):
                break
        else:
            raise SystemExit(f"hedef {i + 1} yerleştirilemedi")
        noktalar.append((x, y))
        hedefler.append({"kimlik": f"H{i + 1:02d}", "sinif": s, "x": x, "y": y, "yonelim_derece": su._aci(rnd),
                         "gorunum_varyanti": rnd.choice(c.varyant[s])})
    sahne = {"surum": 1, "tur": "sahne", "sahne_kimligi": f"S-SEHIR-DENEME-{tohum}", "bolum": "test", "tohum": tohum,
             "alan": {"cerceve": "yerel_ENU", "merkez_m": [0, 0], "genislik_m": 300, "yukseklik_m": 300},
             "isik": {"gunes_azimut_derece": 230.0, "gunes_yukseklik_derece": 45.0}, "zemin": {"gorunum_varyanti": "zemin_c"},
             "hedefler": hedefler}
    hatalar = sd.dogrula_sahne(c, sahne)
    if hatalar:
        raise SystemExit("\n".join(hatalar))
    json.dump(sahne, open(os.path.join(cikti, "sahne.json"), "w"), ensure_ascii=False, indent=2)
    for t in hedefler:
        ad = f"hedef_{t['kimlik']}"
        parca[ad] = "\n".join(su.hedef_sdf(a, sahne, t))
        sira["hedefler"].append(ad)
    # tam dünya ve temel (boş) dünya
    tam = su.dunya_uret(a, sahne)
    i = tam.index('    <model name="hedef_')
    sehir = "\n".join(parca[x] for g in ("yollar", "binalar", "moloz", "arabalar") for x in sira[g]) + "\n"
    open(os.path.join(cikti, "dunya.sdf"), "w").write(tam[:i] + sehir + tam[i:])
    j = tam.index("    <spherical_coordinates>")
    open(os.path.join(cikti, "temel.sdf"), "w").write(tam[:i] + tam[j:])
    for ad, metin in parca.items():
        open(os.path.join(cikti, "parcalar", ad + ".sdf"), "w").write(f'<?xml version="1.0"?>\n<sdf version="1.9">\n{metin}\n</sdf>\n')
    json.dump(sira, open(os.path.join(cikti, "sira.json"), "w"), indent=1)
    print(f"yollar 1, bina {len(sira['binalar'])}, moloz {len(sira['moloz'])}, araba {len(sira['arabalar'])}, hedef {len(hedefler)}")


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
