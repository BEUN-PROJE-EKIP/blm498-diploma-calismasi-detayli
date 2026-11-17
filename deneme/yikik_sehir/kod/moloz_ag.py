#!/usr/bin/env python3
"""DENEME: programla doğal görünümlü moloz yığını ağları (OBJ). Belirlenimci: yalnız verilen random.Random kullanılır.

Bir yığın, malzeme başına bir OBJ'den oluşur (Gazebo'da görsel başına tek doku):
  tumsek  : düzensiz kenarlı alçak tümsek (kırık taş dokusu)
  beton   : kırık beton parçaları (bozulmuş ikosahedron, düz gölgeli) ve düzensiz kenarlı eğik levhalar
  tugla   : dağınık tuğlalar (küçük kutular)
  tahta   : kalaslar (uzun ince kutular)
UV: yüz normalinin baskın eksenine göre dünya koordinatından (üç yönlü izdüşüm), `doku_m` metrede bir tekrar.
"""
import math
import os

PHI = (1 + 5 ** 0.5) / 2
IKO_V = [(-1, PHI, 0), (1, PHI, 0), (-1, -PHI, 0), (1, -PHI, 0), (0, -1, PHI), (0, 1, PHI), (0, -1, -PHI), (0, 1, -PHI),
         (PHI, 0, -1), (PHI, 0, 1), (-PHI, 0, -1), (-PHI, 0, 1)]
IKO_F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
         (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]


def _norm(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / n for c in v)


def _alt_bol():
    """Bir kez alt bölünmüş birim ikosahedron (42 köşe, 80 yüz)."""
    v = [_norm(p) for p in IKO_V]
    orta, f = {}, []

    def m(a, b):
        k = (min(a, b), max(a, b))
        if k not in orta:
            v.append(_norm(tuple((v[a][i] + v[b][i]) / 2 for i in range(3))))
            orta[k] = len(v) - 1
        return orta[k]
    for a, b, c in IKO_F:
        ab, bc, ca = m(a, b), m(b, c), m(c, a)
        f += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
    return v, f


KURE_V, KURE_F = _alt_bol()


def _rot(rx, ry, rz):
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]]


def _uygula(R, p, t):
    return tuple(sum(R[i][k] * p[k] for k in range(3)) + t[i] for i in range(3))


class Obj:
    def __init__(self, doku_m):
        self.ucgenler, self.d = [], doku_m

    def ucgen(self, a, b, c):
        self.ucgenler.append((a, b, c))

    def kutu(self, merkez, boyut, R):
        hx, hy, hz = (s / 2 for s in boyut)
        k = [_uygula(R, (sx * hx, sy * hy, sz * hz), merkez) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        for a, b, c, d in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            self.ucgen(k[a], k[b], k[c])
            self.ucgen(k[a], k[c], k[d])

    def yaz(self, yol):
        v, vt, vn, f = [], [], [], []
        for i, (a, b, c) in enumerate(self.ucgenler):
            u = tuple(b[j] - a[j] for j in range(3))
            w = tuple(c[j] - a[j] for j in range(3))
            n = _norm((u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]))
            eks = max(range(3), key=lambda j: abs(n[j]))
            ui, vi = [(1, 2), (0, 2), (0, 1)][eks]
            vn.append(f"vn {n[0]:.4f} {n[1]:.4f} {n[2]:.4f}")
            for p in (a, b, c):
                v.append(f"v {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}")
                vt.append(f"vt {p[ui] / self.d:.4f} {p[vi] / self.d:.4f}")
            k = 3 * i
            f.append(f"f {k + 1}/{k + 1}/{i + 1} {k + 2}/{k + 2}/{i + 1} {k + 3}/{k + 3}/{i + 1}")
        with open(yol, "w") as fh:
            fh.write("# deneme moloz\n" + "\n".join(v + vt + vn + f) + "\n")


def yigin(rnd, R, H, klasor, ad, tumsek=True, z0=0.0):
    """Merkezi (0, 0, z0) olan yığın; döndürür: [(dosya_adı, grup)] (boş gruplar yazılmaz)."""
    gruplar = {"tumsek": Obj(2.0), "beton": Obj(1.5), "tugla": Obj(1.0), "tahta": Obj(1.5)}
    n_halka, n_dilim = 6, 18
    kenar = [R * rnd.uniform(0.7, 1.15) for _ in range(n_dilim)]
    tepe = [(rnd.uniform(-0.2, 0.2) * R, rnd.uniform(-0.2, 0.2) * R)]

    def yukseklik(x, y):
        """Tümsek yüzeyi (kaba): merkezden uzaklığa göre kubbe."""
        r = math.hypot(x - tepe[0][0], y - tepe[0][1])
        aci = math.atan2(y, x) % (2 * math.pi)
        rk = kenar[int(aci / (2 * math.pi) * n_dilim) % n_dilim]
        return z0 + (H * max(0.0, 1 - (r / rk) ** 2) ** 0.8 if tumsek else 0.0)

    if tumsek:
        nokta = {}
        for i in range(n_halka + 1):
            for j in range(n_dilim):
                t = i / n_halka
                aci = 2 * math.pi * j / n_dilim
                r = kenar[j] * t
                x, y = tepe[0][0] * (1 - t) + r * math.cos(aci), tepe[0][1] * (1 - t) + r * math.sin(aci)
                z = H * max(0.0, 1 - t * t) ** 0.8 + (rnd.uniform(-0.12, 0.12) * H if 0 < i < n_halka else 0.0) - (0.03 if i == n_halka else 0)
                nokta[(i, j)] = (x, y, z)
        for i in range(n_halka):
            for j in range(n_dilim):
                a, b = nokta[(i, j)], nokta[(i, (j + 1) % n_dilim)]
                c, d = nokta[(i + 1, (j + 1) % n_dilim)], nokta[(i + 1, j)]
                if i == 0:
                    gruplar["tumsek"].ucgen(a, d, c)
                else:
                    gruplar["tumsek"].ucgen(a, d, c)
                    gruplar["tumsek"].ucgen(a, c, b)
    # kırık beton parçaları
    for _ in range(rnd.randint(5, 11) if tumsek else rnd.randint(2, 4)):
        s = rnd.uniform(0.25, 0.9) * (1 if tumsek else 0.6)
        olc = (s * rnd.uniform(0.8, 1.6), s * rnd.uniform(0.6, 1.2), s * rnd.uniform(0.35, 0.8))
        bozul = [rnd.uniform(0.65, 1.2) for _ in KURE_V]
        r_ = rnd.uniform(0, R * 0.85)
        aci = rnd.uniform(0, 2 * math.pi)
        x, y = r_ * math.cos(aci), r_ * math.sin(aci)
        m = (x, y, yukseklik(x, y) + olc[2] * 0.25)
        Rm = _rot(rnd.uniform(-0.5, 0.5), rnd.uniform(-0.5, 0.5), rnd.uniform(0, 2 * math.pi))
        k = [_uygula(Rm, tuple(KURE_V[i][j] * olc[j] * bozul[i] for j in range(3)), m) for i in range(len(KURE_V))]
        for a, b, c in KURE_F:
            gruplar["beton"].ucgen(k[a], k[b], k[c])
    # kırık levhalar
    for _ in range(rnd.randint(1, 3) if tumsek else rnd.randint(0, 1)):
        nk = rnd.randint(5, 8)
        rr = rnd.uniform(0.5, 1.3)
        ana = [(rr * rnd.uniform(0.6, 1.1) * math.cos(2 * math.pi * i / nk), rr * rnd.uniform(0.6, 1.1) * math.sin(2 * math.pi * i / nk))
               for i in range(nk)]
        kal = rnd.uniform(0.1, 0.18)
        r_ = rnd.uniform(0, R * 0.7)
        aci = rnd.uniform(0, 2 * math.pi)
        x, y = r_ * math.cos(aci), r_ * math.sin(aci)
        Rm = _rot(rnd.uniform(-0.6, 0.6), rnd.uniform(-0.6, 0.6), rnd.uniform(0, 2 * math.pi))
        m = (x, y, yukseklik(x, y) + 0.15)
        ust = [_uygula(Rm, (px, py, kal / 2), m) for px, py in ana]
        alt = [_uygula(Rm, (px, py, -kal / 2), m) for px, py in ana]
        for i in range(1, nk - 1):
            gruplar["beton"].ucgen(ust[0], ust[i], ust[i + 1])
            gruplar["beton"].ucgen(alt[0], alt[i + 1], alt[i])
        for i in range(nk):
            j = (i + 1) % nk
            gruplar["beton"].ucgen(alt[i], alt[j], ust[j])
            gruplar["beton"].ucgen(alt[i], ust[j], ust[i])
    # tuğlalar
    for _ in range(rnd.randint(12, 35) if tumsek else rnd.randint(0, 6)):
        r_ = rnd.uniform(0, R * 1.1)
        aci = rnd.uniform(0, 2 * math.pi)
        x, y = r_ * math.cos(aci), r_ * math.sin(aci)
        gruplar["tugla"].kutu((x, y, yukseklik(x, y) + 0.03), (0.22, 0.11, 0.07),
                               _rot(rnd.uniform(-0.6, 0.6), rnd.uniform(-0.6, 0.6), rnd.uniform(0, 2 * math.pi)))
    # kalaslar
    for _ in range(rnd.randint(0, 4) if tumsek else 0):
        r_ = rnd.uniform(0, R * 0.8)
        aci = rnd.uniform(0, 2 * math.pi)
        x, y = r_ * math.cos(aci), r_ * math.sin(aci)
        gruplar["tahta"].kutu((x, y, yukseklik(x, y) + 0.1), (rnd.uniform(1.2, 2.8), 0.16, 0.05),
                               _rot(rnd.uniform(-0.35, 0.35), rnd.uniform(-0.35, 0.35), rnd.uniform(0, 2 * math.pi)))
    os.makedirs(klasor, exist_ok=True)
    sonuc = []
    for g, o in gruplar.items():
        if o.ucgenler:
            dosya = f"{ad}_{g}.obj"
            o.yaz(os.path.join(klasor, dosya))
            sonuc.append((dosya, g))
    return sonuc
