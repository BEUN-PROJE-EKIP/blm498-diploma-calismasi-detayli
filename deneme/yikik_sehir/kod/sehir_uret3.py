#!/usr/bin/env python3
"""DENEME 3 (depoya girmez): sehir_uret2 + kutu molozlar yerine programla üretilen doğal moloz yığınları (moloz_ag.py).
Kullanım: sehir_uret3.py <tohum> <cikti_klasoru>"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import moloz_ag  # noqa: E402
import sehir_uret2 as s2  # noqa: E402

GRUP_DOKU = {"tumsek": ("sehir_dokular", "Gravel040"), "tugla": ("sahne_dokulari", "Bricks059"), "tahta": ("sahne_dokulari", "WoodSiding008")}
BETON = [("sehir_dokular", "Concrete044B"), ("sahne_dokulari", "Concrete034")]
TOHUM = [0]


def moloz_sdf(a, ad, x, y, yaw, rnd, olcek, z0=0.0):
    tumsek = z0 == 0.0
    R = 1.4 * olcek if tumsek else 1.0
    H = min(1.6, 0.55 * olcek)
    klasor = os.path.join(s2.DENEME, "modeller", f"sehir_moloz_{TOHUM[0]}", "meshes")
    dosyalar = moloz_ag.yigin(rnd, R, H, klasor, ad, tumsek=tumsek)
    beton = BETON[rnd.randrange(len(BETON))]
    satir = [f'    <model name="{ad}"><static>true</static><pose>{s2.su._poz(x, y, z0, 0, 0, yaw)}</pose><link name="link">']
    for dosya, g in dosyalar:
        kl, dk = beton if g == "beton" else GRUP_DOKU[g]
        malz = s2.doku(kl, dk)
        if dk == "Concrete034":      # açık beton dokusu güneşte bembeyaz görünüyordu: koyulaştır
            malz = malz.replace("<diffuse>1 1 1 1</diffuse>", "<diffuse>0.55 0.54 0.52 1</diffuse>")
        satir.append(f'      <visual name="{g}"><geometry><mesh><uri>model://sehir_moloz_{TOHUM[0]}/meshes/{dosya}</uri></mesh></geometry>'
                     f'{malz}</visual>')
    satir.append("    </link></model>")
    return "\n".join(satir)


if __name__ == "__main__":
    TOHUM[0] = int(sys.argv[1])
    s2.moloz_sdf = moloz_sdf
    if len(sys.argv) > 3 and sys.argv[3] == "test":      # belge: test sahnesinde 15 insan + 15 enkaz, merkezler ≥ 10 m
        c = s2.su.Ayar().c
        s2.BOLUM, s2.INSAN_SAYI, s2.ENKAZ_SAYI, s2.ARALIK = "test", c.test_sayi["insan"], c.test_sayi["enkaz"], c.mesafe_test
    s2.main(int(sys.argv[1]), sys.argv[2])
