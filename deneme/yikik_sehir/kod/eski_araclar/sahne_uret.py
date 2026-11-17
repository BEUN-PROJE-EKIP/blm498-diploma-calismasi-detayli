#!/usr/bin/env python3
"""Gazebo sahne üreticisi (A1): tohumdan sahne dosyası, sahne dosyasından dünya dosyası.

Kullanım:
  sahne_uret.py sahne --bolum <egitim|dogrulama|test> --tohum <N> --kimlik <SAHNE_KIMLIGI> [-o sahne.json]
      Sahne dosyasını (planlama/sozlesmeler.md §2) tohumdan üretir; çıktı doğrulayıcıdan (araclar/sozlesme_dogrula.py) geçmeden yazılmaz.
  sahne_uret.py dunya <sahne.json> [-o dunya.sdf]
      Sahne dosyasından dünya dosyasını üretir (kararlar.md 2026-11-14 "Sahne başına dünya dosyası"): dünya adı SIM_WORLD ve fizik
      ayarları PX4'ün varsayılan dünyasıyla aynı; `<plugin>` yok; ışık, zemin ve hedefler sahne dosyasından. Model ve dokular
      `model://` adresiyle yazılır: Gazebo'yu başlatan, `$SAHNE_VARLIK_KOK/modeller` klasörünü GZ_SIM_RESOURCE_PATH'e ekler.
Çıktı dosyası verilmezse standart çıktıya yazılır. Aynı girdi aynı baytı verir (belirlenimci; yalnız `random.Random(tohum)` ve
`random.Random("<tohum>:<hedef kimliği>")` kullanılır; sayılar sabit biçimle yazılır).

Sahne dosyasında olmayan ayrıntılar (insanın sırtüstü/yüzüstü yatışı, enkaz yığınının parça dizilimi ve dokusu) hedef başına
`Random("<tohum>:<kimlik>")` ile türetilir; sahne dosyası tek doğru kaynak kalır.
Yönelim (sozlesmeler §1): insanda ayaktan başa eksenin yönü; enkazda yığın diziliminin döndürülme açısı.
Çıkış: 0 başarılı, 1 geçersiz girdi/çıktı, 2 kullanım hatası.
"""
import hashlib
import json
import math
import os
import random
import sys

BURASI = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(BURASI)
sys.path.insert(0, BURASI)

import sozlesme_dogrula as sd  # noqa: E402
import varlik_kur as vk  # noqa: E402

DENEME_SAYISI = 20000          # hedef başına konum deneme sınırı (reddetmeli örnekleme)
PARCA_MERKEZ_PAYI_M = 0.4      # enkaz parça merkezi yığın yarıçapından bu kadar içeride (K10 temsiliyle aynı kural)

# PX4 v1.16.0 Tools/simulation/gz/worlds/default.sdf ile aynı (dünya adı, fizik, ortam, coğrafi orijin).
# setup/sahne_uretici_testi.sh `birim` bu değerleri PX4 dosyasıyla karşılaştırır.
PX4_TEMEL = """    <physics type="ode">
      <max_step_size>0.004</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>250</real_time_update_rate>
    </physics>
    <gravity>0 0 -9.8</gravity>
    <magnetic_field>6e-06 2.3e-05 -4.2e-05</magnetic_field>
    <atmosphere type="adiabatic"/>
    <scene>
      <grid>false</grid>
      <ambient>0.4 0.4 0.4 1</ambient>
      <background>0.7 0.7 0.7 1</background>
      <shadows>true</shadows>
    </scene>"""
PX4_KOORDINAT = """    <spherical_coordinates>
      <surface_model>EARTH_WGS84</surface_model>
      <world_frame_orientation>ENU</world_frame_orientation>
      <latitude_deg>47.397971057728974</latitude_deg>
      <longitude_deg> 8.546163739800146</longitude_deg>
      <elevation>0</elevation>
    </spherical_coordinates>"""


# ---------------------------------------------------------------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------------------------------------------------------------
class Ayar:
    def __init__(self, env_yolu=None):
        env_yolu = env_yolu or vk.DENEY_ENV
        self.ham = sd.yapilandirma_yukle(env_yolu)
        self.c = sd.Yapilandirma(self.ham)
        h = self.ham
        eksik = [k for k in ("SAHNE_DIGER_SINIF_MIN", "SAHNE_DIGER_SINIF_MAKS", "SIM_WORLD", "ENKAZ_KUTU_SAYISI", "ENKAZ_CAP_M",
                             "ENKAZ_YUKSEKLIK_M") if k not in h]
        if eksik:
            raise ValueError("yapılandırmada eksik anahtar: " + ", ".join(eksik))
        self.sinif_min, self.sinif_maks = int(h["SAHNE_DIGER_SINIF_MIN"]), int(h["SAHNE_DIGER_SINIF_MAKS"])
        if not 1 <= self.sinif_min <= self.sinif_maks or self.sinif_maks * len(self.c.siniflar) > self.c.diger_maks:
            raise ValueError("SAHNE_DIGER_SINIF_MIN/MAKS: 1 ≤ MIN ≤ MAKS ve MAKS × sınıf sayısı ≤ SAHNE_DIGER_HEDEF_MAKS olmalı")
        self.dunya_adi = h["SIM_WORLD"]
        self.enkaz_n, self.enkaz_cap, self.enkaz_yuk = int(h["ENKAZ_KUTU_SAYISI"]), float(h["ENKAZ_CAP_M"]), float(h["ENKAZ_YUKSEKLIK_M"])
        self.varlik_yolu = vk.yollar(h)[0]
        self.varlik = vk.liste_yukle(self.varlik_yolu, h)
        with open(self.varlik_yolu, "rb") as f:
            self.varlik_sha = hashlib.sha256(f.read()).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------------------
# Sahne dosyası
# ---------------------------------------------------------------------------------------------------------------------------------
def _aci(rnd):
    """[0, 360) aralığında, 0,1° çözünürlüklü açı (yuvarlama 360,0 verirse 0,0)."""
    v = round(rnd.uniform(0.0, 360.0), 1)
    return 0.0 if v >= 360.0 else v


def sahne_uret(a, bolum, tohum, kimlik):
    c = a.c
    if bolum not in c.bolumler:
        raise ValueError(f"bölüm {c.bolumler} değerlerinden biri olmalı (bulunan: {bolum!r})")
    if not isinstance(tohum, int) or tohum < 0:
        raise ValueError("tohum sıfır veya pozitif tam sayı olmalı")
    rnd = random.Random(tohum)
    # Çağrı sırası sabittir; değiştirmek aynı tohumdan farklı sahne üretir (A2 listeleri SHA-256 ile bunu yakalar).
    isik = {"gunes_azimut_derece": _aci(rnd),
            "gunes_yukseklik_derece": round(rnd.uniform(c.gunes_min, c.gunes_maks), 1)}
    zemin = {"gorunum_varyanti": rnd.choice(c.zemin)}
    if bolum == "test":
        sayi = dict(c.test_sayi)
        esik = c.mesafe_test
    else:
        sayi = {s: rnd.randint(a.sinif_min, a.sinif_maks) for s in c.siniflar}
        esik = c.mesafe_diger
    siniflar = [s for s in c.siniflar for _ in range(sayi[s])]
    rnd.shuffle(siniflar)
    (x0, x1), (y0, y1) = c.x_aralik, c.y_aralik
    x0, x1, y0, y1 = x0 + c.kenar_payi, x1 - c.kenar_payi, y0 + c.kenar_payi, y1 - c.kenar_payi
    hedefler, noktalar = [], []
    for i, s in enumerate(siniflar):
        for _ in range(DENEME_SAYISI):
            x, y = round(rnd.uniform(x0, x1), 2), round(rnd.uniform(y0, y1), 2)
            if all(math.hypot(x - px, y - py) >= esik for px, py in noktalar):
                break
        else:
            raise ValueError(f"{i + 1}. hedef {DENEME_SAYISI} denemede yerleştirilemedi (merkezler arası ≥ {esik:g} m)")
        noktalar.append((x, y))
        secenek = c.varyant[s] if bolum == "test" else [v for v in c.varyant[s] if v not in c.test_ozel[s]]
        hedefler.append({"kimlik": f"H{i + 1:02d}", "sinif": s, "x": x, "y": y,
                         "yonelim_derece": _aci(rnd), "gorunum_varyanti": rnd.choice(secenek)})
    d = {"surum": sd.SURUM, "tur": "sahne", "sahne_kimligi": kimlik, "bolum": bolum, "tohum": tohum,
         "alan": {"cerceve": "yerel_ENU", "merkez_m": [_sayi(c.merkez[0]), _sayi(c.merkez[1])],
                  "genislik_m": _sayi(c.genislik), "yukseklik_m": _sayi(c.yukseklik)},
         "isik": isik, "zemin": zemin, "hedefler": hedefler}
    hatalar = sd.dogrula_sahne(c, d)
    if hatalar:
        raise ValueError("üretilen sahne doğrulayıcıdan geçmedi:\n  " + "\n  ".join(hatalar))
    return d


def _sayi(v):
    return int(v) if float(v).is_integer() else v


def sahne_metni(d):
    return json.dumps(d, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------------------------------------------------------------
# Hedef geometrisi (dünya dosyası ve K10 ölçüm sahnesi ortak kullanır)
# ---------------------------------------------------------------------------------------------------------------------------------
def _f(v, n=4):
    s = f"{v:.{n}f}"
    return "0" if float(s) == 0 else s.rstrip("0").rstrip(".") if "." in s else s


YATIS_ADI = {1: "roll+90", -1: "roll-90"}


def _rpy(R):
    """Dönüş matrisi → SDF roll/pitch/yaw (R = Rz(yaw)·Ry(pitch)·Rx(roll))."""
    pitch = math.asin(max(-1.0, min(1.0, -R[2][0])))
    return math.atan2(R[2][1], R[2][2]), pitch, math.atan2(R[1][0], R[0][0])


def _carp(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]


def insan_yerlesimi(varyant, yatis):
    """Yatırılmış insan ağının hedef çerçevesindeki pozu (x, y, z, roll, pitch, yaw). varyant: listedeki insan varyantı.
    Hedef çerçevesi: orijin hedef merkezi (yerde), +x = yönelim (ayaktan başa). Ağ çerçevesi: +z ayaktan başa (Fuel modelleri);
    önce ağın z ekseni çevresinde `on_donus_derece` (göğüs–sırt ekseni y'ye gelir), sonra yatis +1: roll +90° (ağ +z → −y),
    yatis −1: roll −90° (ağ +z → +y; iki yatış yüzüstü/sırtüstü), ardından baş +x'e döner. `sinir_kutusu_m` ve `yatis_kalkma_m`
    ön dönüşlü ağ çerçevesindedir. Sınır kutusunun yatay merkezi hedef merkezine gelir; dikey kaydırma `yatis_kalkma_m` (alt yüzeyin
    `insan.temas.gomulme_yuzdesi` kadarı zemin altında: ayakta modellenmiş ağın çıkıntıları gövdeyi havada bırakmasın)."""
    (mnx, mny, mnz), (mxx, mxy, mxz) = varyant["sinir_kutusu_m"]
    kalk = varyant["yatis_kalkma_m"][YATIS_ADI[yatis]]
    cx = (mnx + mxx) / 2
    if yatis > 0:      # Rx(+90): (x, y, z) -> (x, -z, y)
        cy, yaw = -(mnz + mxz) / 2, math.pi / 2
    else:              # Rx(-90): (x, y, z) -> (x, z, -y)
        cy, yaw = (mnz + mxz) / 2, -math.pi / 2
    # konum = Rz(yaw)·(−cx, −cy) ; z = kalk ; dönüş = Rz(yaw)·Rx(±90°)·Rz(ön dönüş)
    cs, sn = math.cos(yaw), math.sin(yaw)
    r, p, y = _rpy(_carp(_carp(_rz(yaw), _rx(yatis * math.pi / 2)), _rz(math.radians(varyant["on_donus_derece"]))))
    return (-cx * cs + cy * sn, -cx * sn - cy * cs, kalk, r, p, y)


def enkaz_parcalari(a, rnd, levha_orani):
    """Yığın parçaları (hedef çerçevesinde): [(x, y, z, roll, pitch, yaw, sx, sy, sz, doku_sirasi)].
    Kutu boyutları ve yerleşim K10 temsiliyle aynı dağılımdan (araclar/kamera_olcum.py sdf_uret_insan); levhalar ince ve hafif eğik."""
    p = []
    for _ in range(a.enkaz_n):
        aci = rnd.uniform(0, 2 * math.pi)
        rr = rnd.uniform(0, a.enkaz_cap / 2 - PARCA_MERKEZ_PAYI_M)
        if rnd.random() < levha_orani:
            sx, sy, sz = rnd.uniform(0.6, 1.4), rnd.uniform(0.4, 1.0), rnd.uniform(0.04, 0.10)
            roll, pitch = rnd.uniform(-0.25, 0.25), rnd.uniform(-0.25, 0.25)
        else:
            sx, sy, sz = rnd.uniform(0.5, 1.4), rnd.uniform(0.3, 1.0), rnd.uniform(0.2, a.enkaz_yuk)
            roll = pitch = 0.0
        yaw = rnd.uniform(0, math.pi)
        z = sz / 2 + 0.5 * (sx * abs(math.sin(pitch)) + sy * abs(math.sin(roll)))   # eğik levhanın alt köşesi yere değer
        p.append((rr * math.cos(aci), rr * math.sin(aci), z, roll, pitch, yaw, sx, sy, sz, rnd.randrange(1 << 30)))
    return p


def _poz(x, y, z, r, p, yw):
    return f"{_f(x)} {_f(y)} {_f(z)} {_f(r, 6)} {_f(p, 6)} {_f(yw, 6)}"


def _doku_malzeme(klasor):
    ad = vk.doku_dosya_adi(klasor, "renk")
    return (f"<material><diffuse>1 1 1 1</diffuse><specular>0 0 0 1</specular><pbr><metal>"
            f"<albedo_map>model://{vk.DOKU_MODELI}/{klasor}/{ad}</albedo_map><roughness>1</roughness><metalness>0</metalness>"
            f"</metal></pbr></material>")


def _insan_malzeme(m):
    if not m:
        return ""
    return ("<material><diffuse>1 1 1 1</diffuse><specular>1 1 1 1</specular><pbr><metal>"
            + "".join(f"<{k}>{m[k]}</{k}>" for k in ("albedo_map", "normal_map", "metalness_map", "roughness_map") if k in m)
            + "</metal></pbr></material>")


def hedef_sdf(a, sahne, t, malzeme_ezme=None):
    """Bir hedefin <model> öğesi. malzeme_ezme verilirse (K10 ölçümü) bütün görsellere bu malzeme yazılır."""
    rnd = random.Random(f"{sahne['tohum']}:{t['kimlik']}")
    satir = [f'    <model name="hedef_{t["kimlik"]}">',
             "      <static>true</static>",
             f"      <pose>{_poz(t['x'], t['y'], 0, 0, 0, math.radians(t['yonelim_derece']))}</pose>",
             '      <link name="link">']
    if t["sinif"] == "insan":
        v = a.varlik["insan"]["varyantlar"][t["gorunum_varyanti"]]
        yatis = rnd.choice((1, -1))
        satir.append(f'        <visual name="govde"><pose>{_poz(*insan_yerlesimi(v, yatis))}</pose>'
                     f'<geometry><mesh><uri>{v["ag"]}</uri></mesh></geometry>{malzeme_ezme or _insan_malzeme(v["malzeme"])}</visual>')
    else:
        dokular = a.varlik["enkaz"]["varyantlar"][t["gorunum_varyanti"]]
        for k, (x, y, z, r, p, yw, sx, sy, sz, ds) in enumerate(enkaz_parcalari(a, rnd, a.varlik["enkaz"]["levha_orani"])):
            mz = malzeme_ezme(k) if callable(malzeme_ezme) else (malzeme_ezme or _doku_malzeme(dokular[ds % len(dokular)]))
            satir.append(f'        <visual name="parca_{k}"><pose>{_poz(x, y, z, r, p, yw)}</pose>'
                         f'<geometry><box><size>{_f(sx)} {_f(sy)} {_f(sz)}</size></box></geometry>{mz}</visual>')
    satir += ["      </link>", "    </model>"]
    return satir


def gunes_yonu(azimut_derece, yukseklik_derece):
    """Işık yönü (güneşten yere): güneşin bulunduğu yönün tersi; yerel ENU."""
    az, el = math.radians(azimut_derece), math.radians(yukseklik_derece)
    return (-math.cos(el) * math.cos(az), -math.cos(el) * math.sin(az), -math.sin(el))


# ---------------------------------------------------------------------------------------------------------------------------------
# Dünya dosyası
# ---------------------------------------------------------------------------------------------------------------------------------
def dunya_uret(a, sahne):
    hatalar = sd.dogrula_sahne(a.c, sahne)
    if hatalar:
        raise ValueError("sahne dosyası geçersiz:\n  " + "\n  ".join(hatalar))
    z = a.varlik["zemin"]
    zemin_doku = z["varyantlar"][sahne["zemin"]["gorunum_varyanti"]]
    zemin_ag = f"model://{vk.ZEMIN_MODELI}/meshes/{vk.zemin_ag_adi(z['ag_boyu_m'], z['doku_boyu_m'])}"
    dx, dy, dz = gunes_yonu(sahne["isik"]["gunes_azimut_derece"], sahne["isik"]["gunes_yukseklik_derece"])
    sahne_sha = hashlib.sha256(json.dumps(sahne, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    p = ['<?xml version="1.0" encoding="UTF-8"?>',
         f"<!-- Otomatik üretildi (araclar/sahne_uret.py dunya); elle değiştirmeyin. Sahne {sahne['sahne_kimligi']} "
         f"(bölüm {sahne['bolum']}, tohum {sahne['tohum']}), sahne SHA-256 (sıralı JSON) {sahne_sha}, "
         f"varlık listesi SHA-256 {a.varlik_sha}. Model ve dokular model:// ile: GZ_SIM_RESOURCE_PATH += $SAHNE_VARLIK_KOK/modeller -->",
         '<sdf version="1.9">',
         f'  <world name="{a.dunya_adi}">',
         PX4_TEMEL,
         '    <model name="ground_plane">',
         "      <static>true</static>",
         '      <link name="link">',
         '        <collision name="collision"><geometry><plane><normal>0 0 1</normal><size>1 1</size></plane></geometry>'
         "<surface><friction><ode/></friction><bounce/><contact/></surface></collision>",
         f'        <visual name="visual"><geometry><mesh><uri>{zemin_ag}</uri></mesh></geometry>{_doku_malzeme(zemin_doku)}</visual>',
         "      </link>",
         "    </model>",
         '    <light name="sunUTC" type="directional">',
         "      <pose>0 0 500 0 0 0</pose>",
         "      <cast_shadows>true</cast_shadows>",
         "      <intensity>1</intensity>",
         f"      <direction>{_f(dx, 6)} {_f(dy, 6)} {_f(dz, 6)}</direction>",
         "      <diffuse>0.904 0.904 0.904 1</diffuse>",
         "      <specular>0.271 0.271 0.271 1</specular>",
         "      <attenuation><range>2000</range><linear>0</linear><constant>1</constant><quadratic>0</quadratic></attenuation>",
         "    </light>"]
    for t in sahne["hedefler"]:
        p += hedef_sdf(a, sahne, t)
    p += [PX4_KOORDINAT, "  </world>", "</sdf>"]
    metin = "\n".join(p) + "\n"
    if "<plugin" in metin:
        raise AssertionError("dünya dosyası <plugin> içeremez (kararlar.md)")
    return metin


# ---------------------------------------------------------------------------------------------------------------------------------
# Komut satırı
# ---------------------------------------------------------------------------------------------------------------------------------
def _yaz(metin, cikti):
    if cikti is None:
        sys.stdout.write(metin)
        return
    gecici = cikti + ".yaziliyor"
    with open(gecici, "w", encoding="utf-8") as f:
        f.write(metin)
    os.replace(gecici, cikti)


def ana(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    komut, a_ = argv[0], list(argv[1:])
    sec = {}
    konum = []
    while a_:
        k = a_.pop(0)
        if k in ("--bolum", "--tohum", "--kimlik", "-o") and a_:
            sec[k] = a_.pop(0)
        elif not k.startswith("-"):
            konum.append(k)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    try:
        if komut == "sahne" and not konum and {"--bolum", "--tohum", "--kimlik"} <= set(sec):
            if not sec["--tohum"].isdigit():
                raise ValueError("--tohum sıfır veya pozitif tam sayı olmalı")
            d = sahne_uret(Ayar(), sec["--bolum"], int(sec["--tohum"]), sec["--kimlik"])
            _yaz(sahne_metni(d), sec.get("-o"))
            return 0
        if komut == "dunya" and len(konum) == 1 and set(sec) <= {"-o"}:
            with open(konum[0], encoding="utf-8") as f:
                sahne = json.load(f)
            _yaz(dunya_uret(Ayar(), sahne), sec.get("-o"))
            return 0
    except (ValueError, OSError, KeyError) as e:
        print(f"(-) {e}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
