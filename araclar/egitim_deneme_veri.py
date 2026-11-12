#!/usr/bin/env python3
"""Eğitim bellek denemesi için küçük, yapay, tohumla tekrarlanabilir YOLO biçimli veri seti üretir.

Kullanım: egitim_deneme_veri.py <cikti_klasoru>
Ortam: TRAIN_VERI_TOHUM, TRAIN_VERI_EGITIM, TRAIN_VERI_DOGRULAMA, CAM_WIDTH, CAM_HEIGHT.
Görüntü: 640 × 480 RGB, rastgele gürültü + yumuşak renk geçişli arka plan; 1-6 rastgele dikdörtgen hedef; iki sınıf: 0 insan, 1 enkaz.
Bu veri gerçek hedef görünümünü temsil etmez; yalnız bellek/akış ölçümü içindir (doğruluk üretilmez).
"""
import os
import sys

import numpy as np
from PIL import Image


def uret(klasor, tohum, n_egitim, n_dogrulama, w, h):
    rng = np.random.default_rng(tohum)
    for bolum, n in (("train", n_egitim), ("val", n_dogrulama)):
        os.makedirs(os.path.join(klasor, "images", bolum), exist_ok=True)
        os.makedirs(os.path.join(klasor, "labels", bolum), exist_ok=True)
        for i in range(n):
            # arka plan: iki rastgele renk arasında doğrusal geçiş + gürültü
            c0, c1 = rng.integers(40, 220, 3), rng.integers(40, 220, 3)
            t = np.linspace(0, 1, w)[None, :, None]
            img = (c0[None, None, :] * (1 - t) + c1[None, None, :] * t).repeat(h, axis=0)
            img = img + rng.normal(0, 12, (h, w, 3))
            etiketler = []
            for _ in range(int(rng.integers(1, 7))):
                sinif = int(rng.integers(0, 2))
                bw, bh = int(rng.integers(20, 120)), int(rng.integers(20, 120))
                x0, y0 = int(rng.integers(0, w - bw)), int(rng.integers(0, h - bh))
                renk = rng.integers(0, 255, 3)
                img[y0:y0 + bh, x0:x0 + bw] = renk
                etiketler.append(f"{sinif} {(x0 + bw / 2) / w:.6f} {(y0 + bh / 2) / h:.6f} {bw / w:.6f} {bh / h:.6f}")
            ad = f"{bolum}_{i:04d}"
            Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(os.path.join(klasor, "images", bolum, ad + ".jpg"), quality=95)
            with open(os.path.join(klasor, "labels", bolum, ad + ".txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(etiketler) + "\n")
    with open(os.path.join(klasor, "data.yaml"), "w", encoding="utf-8") as f:
        f.write(f"path: {os.path.abspath(klasor)}\ntrain: images/train\nval: images/val\nnames:\n  0: insan\n  1: enkaz\n")


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    e = os.environ
    uret(sys.argv[1], int(e["TRAIN_VERI_TOHUM"]), int(e["TRAIN_VERI_EGITIM"]), int(e["TRAIN_VERI_DOGRULAMA"]), int(e["CAM_WIDTH"]), int(e["CAM_HEIGHT"]))
    print(f"VERI {sys.argv[1]}: {e['TRAIN_VERI_EGITIM']} eğitim + {e['TRAIN_VERI_DOGRULAMA']} doğrulama görüntüsü (tohum {e['TRAIN_VERI_TOHUM']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
