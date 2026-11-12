#!/usr/bin/env python3
"""Kamera damga/sıra ölçümü (K9) ve yatay görüş açısı ölçümü (K10).

Kullanım:
  kamera_olcum.py dunya <cikti.sdf> <kamera_sayisi>                    deneme sahnesini config değerlerinden üretir
  kamera_olcum.py kare  <konu1[,konu2..]> <sim_sn> <csv_dosyasi>       kare damgalarını kaydeder ve K9 istatistiklerini yazar
  kamera_olcum.py k10   <konu> <cikti_klasoru>                         bir kare alır, hedef piksel boyutlarından HFOV'yi hesaplar
  kamera_olcum.py dunya-insan <cikti.sdf>                              yatan insan (9 kombinasyon) ve enkaz yığınlı ölçüm sahnesi
  kamera_olcum.py hedef <konu> <cikti_klasoru>                         insan/enkaz piksel boyutu ölçümü
Değerler ortam değişkenlerinden okunur (setup/kamera_olcum_testi.sh, config/deney.env'den verir):
CAM_WIDTH, CAM_HEIGHT, CAM_RATE_HZ, CAM_ALT_M, CAM_SDF_HFOV_RAD, CAM_WORLD, CAM_TARGETS, CAM_SPACING_M.
Kameraya gz-transport ile doğrudan abone olunur (köprü yok). Yorum yoktur: ölçülen sayılar yazılır.
"""
import math
import os
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore")

RENKLER = [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.6, 0.0), (1.0, 0.0, 1.0)]
KALINLIK = 0.02   # hedef levhanın kalınlığı (m); üst yüzey z=KALINLIK


def cfg():
    e = os.environ
    hedefler = []
    if e.get("KALIB_ORANLI") == "1":
        # konumlar görüş alanının yarı genişlik/yüksekliğiyle ölçeklenir (x: dikey eksen, y: yatay eksen)
        yw = float(e["CAM_ALT_M"]) * math.tan(float(e["CAM_SDF_HFOV_RAD"]) / 2)
        yh = yw * int(e["CAM_HEIGHT"]) / int(e["CAM_WIDTH"])
        for t in e["KALIB_KARELER"].split():
            k, fx, fy = (float(v) for v in t.split(":"))
            hedefler.append((k, fx * yh, fy * yw))
    else:
        for t in e["CAM_TARGETS"].split():
            k, x, y = (float(v) for v in t.split(":"))
            hedefler.append((k, x, y))
    return {
        "w": int(e["CAM_WIDTH"]), "h": int(e["CAM_HEIGHT"]), "hz": float(e["CAM_RATE_HZ"]), "alt": float(e["CAM_ALT_M"]),
        "fov": float(e["CAM_SDF_HFOV_RAD"]), "dunya": e["CAM_WORLD"], "hedefler": hedefler, "aralik": float(e["CAM_SPACING_M"]),
    }


SAHNE_TEMEL = '''    <physics type="ode">
      <max_step_size>0.004</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>250</real_time_update_rate>
    </physics>
    <gravity>0 0 -9.8</gravity>
    <magnetic_field>6e-06 2.3e-05 -4.2e-05</magnetic_field>
    <atmosphere type="adiabatic"/>
    <scene><grid>false</grid><ambient>0.4 0.4 0.4 1</ambient><background>0.7 0.7 0.7 1</background><shadows>false</shadows></scene>
    <model name="ground_plane"><static>true</static><link name="link">
      <collision name="collision"><geometry><plane><normal>0 0 1</normal><size>1 1</size></plane></geometry></collision>
      <visual name="visual"><geometry><plane><normal>0 0 1</normal><size>500 500</size></plane></geometry>
        <material><ambient>0.8 0.8 0.8 1</ambient><diffuse>0.8 0.8 0.8 1</diffuse><specular>0 0 0 1</specular></material></visual>
    </link></model>
    <light name="sunUTC" type="directional"><pose>0 0 500 0 0 0</pose><cast_shadows>false</cast_shadows><intensity>1</intensity>
      <direction>0.001 0.625 -0.78</direction><diffuse>0.904 0.904 0.904 1</diffuse><specular>0 0 0 1</specular></light>'''


def konu_adi(i):
    return f"kamera_{i}/image"


def sdf_uret(cikti, n_kamera):
    c = cfg()
    p = []
    p.append('<?xml version="1.0" encoding="UTF-8"?>')
    p.append('<!-- Otomatik üretildi (araclar/kamera_olcum.py dunya); değerler config/deney.env içindeki CAM_* ayarlarından gelir. -->')
    p.append('<sdf version="1.9">')
    p.append(f'  <world name="{c["dunya"]}">')
    p.append(SAHNE_TEMEL)
    for i in range(1, n_kamera + 1):
        y = (i - 1) * c["aralik"]
        p.append(f'''    <model name="kamera_{i}"><static>true</static><pose>0 {y:g} {c["alt"]:g} 0 1.5707963 0</pose><link name="link">
      <sensor name="kamera" type="camera"><always_on>1</always_on><update_rate>{c["hz"]:g}</update_rate><visualize>false</visualize>
        <topic>{konu_adi(i)}</topic>
        <camera><horizontal_fov>{c["fov"]:g}</horizontal_fov><image><width>{c["w"]}</width><height>{c["h"]}</height><format>R8G8B8</format></image>
          <clip><near>0.1</near><far>200</far></clip></camera></sensor></link></model>''')
    for j, (k, x, y) in enumerate(c["hedefler"]):
        r, g, b = RENKLER[j % len(RENKLER)]
        p.append(f'''    <model name="hedef_{j + 1}"><static>true</static><pose>{x:g} {y:g} {KALINLIK / 2:g} 0 0 0</pose><link name="link">
      <visual name="visual"><geometry><box><size>{k:g} {k:g} {KALINLIK:g}</size></box></geometry>
        <material><ambient>0 0 0 1</ambient><diffuse>0 0 0 1</diffuse><specular>0 0 0 1</specular><emissive>{r} {g} {b} 1</emissive></material></visual>
    </link></model>''')
    p.append('  </world>')
    p.append('</sdf>')
    with open(cikti, "w", encoding="utf-8") as f:
        f.write("\n".join(p) + "\n")


class Alici:
    """Bir veya birden çok kamera konusuna abone olur; her kare için damga, alıcı monotonik zamanı ve kare verisini tutar."""

    def __init__(self, konular, veri_tut=False):
        from gz.transport13 import Node
        from gz.msgs10.image_pb2 import Image
        self.kayit = {k: [] for k in konular}
        self.kilit = threading.Lock()
        self.veri_tut = veri_tut
        self.son = None
        self.node = Node()
        for k in konular:
            if not self.node.subscribe(Image, "/" + k, self._cb(k)):
                raise RuntimeError(f"abonelik kurulamadı: /{k}")

    def _cb(self, konu):
        def cb(m):
            w = time.monotonic_ns()
            ns = m.header.stamp.sec * 1_000_000_000 + m.header.stamp.nsec
            with self.kilit:
                self.kayit[konu].append((ns, w, bytes(m.data) if self.veri_tut else None, m.width, m.height, m.step, m.pixel_format_type))
        return cb

    def sayi(self, k):
        with self.kilit:
            return len(self.kayit[k])


def kare_istatistik(konu, satirlar, yarim_ns):
    """K9 istatistikleri: damga katları, sıra, numara sürekliliği, sim/gerçek aralıklar, RTF."""
    ns = [s[0] for s in satirlar]
    wl = [s[1] for s in satirlar]
    n = len(ns)
    near = [round(t / yarim_ns) for t in ns]
    dev = [t - k * yarim_ns for t, k in zip(ns, near)]
    mutlak = [abs(d) for d in dev]
    farklar = [near[i] - near[i - 1] for i in range(1, n)]
    sirasiz = sum(1 for i in range(1, n) if ns[i] < ns[i - 1])
    esit = sum(1 for i in range(1, n) if ns[i] == ns[i - 1])
    atlanan = sum(f - 1 for f in farklar if f > 1)
    kopya_num = sum(1 for f in farklar if f == 0)
    geri_num = sum(1 for f in farklar if f < 0)
    sim_a = [(ns[i] - ns[i - 1]) * 1e-9 for i in range(1, n)]
    gercek_a = [(wl[i] - wl[i - 1]) * 1e-9 for i in range(1, n)]
    sim_sure = (ns[-1] - ns[0]) * 1e-9
    gercek_sure = (wl[-1] - wl[0]) * 1e-9
    rtf = sim_sure / gercek_sure if gercek_sure > 0 else float("nan")
    # 2·t_sim kuralı: n = 2·t_sim; "tam kat" = 2·t_sim tamsayı
    iki_t = [2 * t * 1e-9 for t in ns]
    iki_t_sapma = [abs(v - round(v)) for v in iki_t]
    return {
        "konu": konu, "kare": n, "ilk_damga_s": ns[0] * 1e-9, "son_damga_s": ns[-1] * 1e-9, "sim_sure_s": sim_sure, "gercek_sure_s": gercek_sure,
        "tam_kat_olmayan": sum(1 for d in dev if d != 0), "maks_sapma_ns": max(mutlak), "ort_sapma_ns": sum(mutlak) / n,
        "maks_2t_sapma": max(iki_t_sapma), "ort_2t_sapma": sum(iki_t_sapma) / n,
        "sirasiz": sirasiz, "esit_damga": esit, "atlanan_numara": atlanan, "kopya_numara": kopya_num, "geri_numara": geri_num,
        "numara_ilk": near[0], "numara_son": near[-1],
        "sim_aralik_min": min(sim_a), "sim_aralik_ort": sum(sim_a) / len(sim_a), "sim_aralik_maks": max(sim_a),
        "gercek_aralik_min": min(gercek_a), "gercek_aralik_ort": sum(gercek_a) / len(gercek_a), "gercek_aralik_maks": max(gercek_a),
        "rtf": rtf,
    }


def yaz_istatistik(s):
    print(f"K9 {s['konu']}: kare={s['kare']} sim_sure={s['sim_sure_s']:.1f}s gercek_sure={s['gercek_sure_s']:.1f}s RTF={s['rtf']:.4f} "
          f"ilk_damga={s['ilk_damga_s']:.3f}s", flush=True)
    print(f"K9 {s['konu']}: damga_tam_kat_olmayan={s['tam_kat_olmayan']}/{s['kare']} maks_sapma={s['maks_sapma_ns']}ns ort_sapma={s['ort_sapma_ns']:.1f}ns "
          f"| 2t_tamsayidan_maks_fark={s['maks_2t_sapma']:.3e} ort={s['ort_2t_sapma']:.3e}", flush=True)
    print(f"K9 {s['konu']}: sirasiz_teslim={s['sirasiz']} esit_damga={s['esit_damga']} numara_ilk={s['numara_ilk']} numara_son={s['numara_son']} "
          f"atlanan_numara={s['atlanan_numara']} kopya_numara={s['kopya_numara']} geri_numara={s['geri_numara']}", flush=True)
    print(f"K9 {s['konu']}: sim_aralik[s] min={s['sim_aralik_min']:.6f} ort={s['sim_aralik_ort']:.6f} maks={s['sim_aralik_maks']:.6f} "
          f"| gercek_aralik[s] min={s['gercek_aralik_min']:.4f} ort={s['gercek_aralik_ort']:.4f} maks={s['gercek_aralik_maks']:.4f}", flush=True)


def kare_modu(konular, sim_sn, csv_yolu):
    c = cfg()
    yarim_ns = int(round(1e9 / c["hz"]))
    a = Alici(konular)
    t0 = time.monotonic()
    zaman_asimi = sim_sn * 4 + 90
    while True:
        time.sleep(0.5)
        with a.kilit:
            hazir = all(len(a.kayit[k]) >= 2 for k in konular)
            bitti = hazir and all((a.kayit[k][-1][0] - a.kayit[k][0][0]) * 1e-9 >= sim_sn for k in konular)
        if bitti:
            break
        if time.monotonic() - t0 > zaman_asimi:
            print(f"SONUC kaldi kare_toplama | zaman aşımı ({zaman_asimi:.0f} sn); kare sayıları: { {k: a.sayi(k) for k in konular} }", flush=True)
            return 1
    with a.kilit:
        kayit = {k: list(v) for k, v in a.kayit.items()}
    os.makedirs(os.path.dirname(csv_yolu) or ".", exist_ok=True)
    with open(csv_yolu, "w", encoding="utf-8") as f:
        f.write("konu,sira,damga_ns,alici_monotonik_ns\n")
        for k in konular:
            for i, (ns, w, _, _, _, _, _) in enumerate(kayit[k]):
                f.write(f"{k},{i},{ns},{w}\n")
    for k in konular:
        yaz_istatistik(kare_istatistik(k, kayit[k], yarim_ns))
        # Ayrıca ilk kare hariç (ilk kare, sensörün ilk planlı güncellemesinden önce üretilebiliyor; gözlem, yorum değil)
        s1 = kare_istatistik(k, kayit[k][1:], yarim_ns)
        print(f"K9 {k}: ILK_KARE_HARIC kare={s1['kare']} tam_kat_olmayan={s1['tam_kat_olmayan']} maks_sapma={s1['maks_sapma_ns']}ns sirasiz={s1['sirasiz']} "
              f"esit_damga={s1['esit_damga']} atlanan={s1['atlanan_numara']} kopya={s1['kopya_numara']} geri={s1['geri_numara']} "
              f"sim_aralik_min={s1['sim_aralik_min']:.6f} maks={s1['sim_aralik_maks']:.6f} | ilk_kare_damga={kayit[k][0][0] * 1e-9:.3f}s", flush=True)
    print(f"SONUC gecti kare_toplama | {len(konular)} konu, kare sayıları { {k: len(v) for k, v in kayit.items()} }, ham kayıt {csv_yolu}", flush=True)
    return 0


def k10_modu(konu, cikti_dizini):
    import numpy as np
    from PIL import Image as PImage
    c = cfg()
    a = Alici([konu], veri_tut=True)
    t0 = time.monotonic()
    while a.sayi(konu) < 4 and time.monotonic() - t0 < 120:
        time.sleep(0.5)
    if a.sayi(konu) < 4:
        print("SONUC kaldi k10_kare | kare alınamadı", flush=True)
        return 1
    with a.kilit:
        ns, _, veri, w, h, step, pf = a.kayit[konu][3]
    os.makedirs(cikti_dizini, exist_ok=True)
    if pf != 3 or step != w * 3:
        print(f"SONUC kaldi k10_kare | beklenmeyen piksel biçimi (pixel_format_type={pf}, step={step}, genişlik={w})", flush=True)
        return 1
    img = np.frombuffer(veri, dtype=np.uint8).reshape(h, w, 3).astype(np.float64)
    PImage.fromarray(img.astype(np.uint8)).save(os.path.join(cikti_dizini, "k10_kare.png"))
    print(f"K10 kare: {w}x{h} RGB8 sıkıştırmasız, damga={ns * 1e-9:.3f}s", flush=True)
    z = c["alt"] - KALINLIK                      # kameradan hedef üst yüzeyine dik uzaklık (m)
    sonuclar = []
    for j, (k, x, y) in enumerate(c["hedefler"]):
        r, g, b = RENKLER[j % len(RENKLER)]
        hedef = srgb255((r, g, b))
        # Konum tahmini: renge en yakın pikseller (eşik: arka plandan uzak, hedef rengine yakın)
        uzak = np.linalg.norm(img - hedef, axis=2)
        maske = uzak < 60.0
        if maske.sum() < 4:
            print(f"K10 hedef_{j + 1}: bulunamadı (renk {hedef.astype(int).tolist()})", flush=True)
            continue
        ys, xs = np.nonzero(maske)
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        # Arka plan rengi: kutunun dışındaki halkanın medyanı
        pad = 6
        halka = img[max(0, y0 - pad):y1 + pad + 1, max(0, x0 - pad):x1 + pad + 1].copy()
        halka_maske = np.ones(halka.shape[:2], bool)
        halka_maske[(y0 - max(0, y0 - pad)):(y1 - max(0, y0 - pad) + 1), (x0 - max(0, x0 - pad)):(x1 - max(0, x0 - pad) + 1)] = False
        bg = np.median(halka[halka_maske], axis=0)
        d = hedef - bg
        # Kısmi kaplama (alfa): arka plan→hedef doğrusuna iz düşüm; alt piksel genişlik/yükseklik = orta satır/sütun alfa toplamı
        alfa = np.clip(((img - bg) @ d) / (d @ d), 0.0, 1.0)
        alt = alfa[max(0, y0 - pad):y1 + pad + 1, max(0, x0 - pad):x1 + pad + 1]
        cy, cx = (y0 + y1) // 2 - max(0, y0 - pad), (x0 + x1) // 2 - max(0, x0 - pad)
        gen_alt = float(alt[cy, :].sum())            # yatay (u) boyut, alt piksel
        yuk_alt = float(alt[:, cx].sum())            # dikey (v) boyut, alt piksel
        gen_kutu = int(x1 - x0 + 1)
        yuk_kutu = int(y1 - y0 + 1)
        # Piksel/m ve HFOV (u ekseni dünya y; v ekseni dünya x). Kenar k m olduğundan her iki eksen aynı ölçeği vermeli.
        ppm_u = gen_alt / k
        ppm_v = yuk_alt / k
        fx = ppm_u * z
        fy = ppm_v * z
        hfov = 2 * math.atan(c["w"] / (2 * fx))
        vfov = 2 * math.atan(c["h"] / (2 * fy))
        # Belirsizlik: ±1 piksel (kenar iki ucunda ±0,5) => göreli ±1/gen; HFOV'ye türev
        d_hfov = abs(2 * (1 / (1 + (c["w"] / (2 * fx)) ** 2)) * (c["w"] / (2 * fx ** 2)) * fx * (1.0 / gen_alt))
        sonuclar.append((j + 1, k, x, y, gen_kutu, yuk_kutu, gen_alt, yuk_alt, ppm_u, ppm_v, hfov, vfov, d_hfov))
        print(f"K10 hedef_{j + 1}: kenar={k:g}m konum=({x:g},{y:g})m kutu={gen_kutu}x{yuk_kutu}px alt_piksel={gen_alt:.2f}x{yuk_alt:.2f}px "
              f"piksel/m u={ppm_u:.3f} v={ppm_v:.3f} HFOV={hfov:.4f}rad ({math.degrees(hfov):.2f}°) ±{d_hfov:.4f} VFOV={vfov:.4f}rad", flush=True)
    if len(sonuclar) < 3:
        print(f"SONUC kaldi k10_hedef | yalnız {len(sonuclar)} hedef ölçüldü (≥ 3 gerekli)", flush=True)
        return 1
    # Kenar yanlılığı (karşıtlık/anti-alias) sabit bir piksel kaymasıysa, piksel-boyut ~ kenar_m doğrusunun EĞİMİ onu eler:
    # alt_piksel = ppm * kenar + sabit  (en küçük kareler; u ekseni).
    ks = [s[1] for s in sonuclar]
    gs = [s[6] for s in sonuclar]
    mk, mg = sum(ks) / len(ks), sum(gs) / len(gs)
    sxx = sum((k_ - mk) ** 2 for k_ in ks)
    egim = sum((k_ - mk) * (g_ - mg) for k_, g_ in zip(ks, gs)) / sxx if sxx else float("nan")
    sabit = mg - egim * mk
    hfov_fit = 2 * math.atan(c["w"] / (2 * egim * z)) if egim == egim and egim > 0 else float("nan")
    print(f"K10 dogru_uydurma: alt_piksel = {egim:.4f} piksel/m x kenar + {sabit:+.3f} piksel => HFOV(egim)={hfov_fit:.4f}rad ({math.degrees(hfov_fit):.2f}°)", flush=True)
    hf = [s[10] for s in sonuclar]
    ort = sum(hf) / len(hf)
    gsd = 1.0 / (sum(s[8] for s in sonuclar) / len(sonuclar))
    iz = 2 * c["alt"] * math.tan(ort / 2)
    iz_sdf = 2 * c["alt"] * math.tan(c["fov"] / 2)
    print(f"K10 ozet: olculen_HFOV_ort={ort:.4f}rad ({math.degrees(ort):.2f}°) min={min(hf):.4f} maks={max(hf):.4f} | SDF horizontal_fov={c['fov']:.4f}rad "
          f"({math.degrees(c['fov']):.2f}°) fark={ort - c['fov']:+.4f}rad ({math.degrees(ort - c['fov']):+.2f}°)", flush=True)
    print(f"K10 ozet: yer_ornekleme={gsd:.4f} m/piksel (alt={c['alt']:g}m) iz_genisligi_olculen={iz:.2f}m iz_genisligi_SDF={iz_sdf:.2f}m", flush=True)
    print(f"SONUC gecti k10_olcum | {len(sonuclar)} hedef; HFOV ölçülen {ort:.4f} rad, SDF {c['fov']:.4f} rad", flush=True)
    return 0


# --- Yatan insan ve enkaz temsilleri (aday görüş açısı ölçümü; kalıcı model değil) ------------------------------------------
INSAN_RENKLERI = [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.6, 0.0), (1.0, 0.0, 1.0), (0.0, 0.8, 0.8),
                  (1.0, 0.5, 0.0), (0.5, 0.0, 1.0), (1.0, 1.0, 0.0), (0.6, 0.3, 0.0)]
ENKAZ_TONLARI = [(0.12, 0.12, 0.12), (0.18, 0.16, 0.14), (0.25, 0.10, 0.03), (0.10, 0.06, 0.03), (0.30, 0.30, 0.30), (0.15, 0.15, 0.17)]   # doğrusal; beton/ahşap tonları
KONUMLAR = ["merkez", "kenar", "köşe"]


def srgb255(rgb):
    """Emisif (doğrusal) renk → görüntüde beklenen sRGB piksel değeri (0-255). Gazebo çıktısı sRGB kodlu (ör. 0,6 → 203)."""
    import numpy as np
    v = np.array(rgb, dtype=float)
    return 255.0 * np.where(v <= 0.0031308, 12.92 * v, 1.055 * np.power(v, 1 / 2.4) - 0.055)


def insan_cfg():
    e = os.environ
    uz, dar, kal = (float(v) for v in e["INSAN_BOYUT"].split(":"))
    return {"uz": uz, "dar": dar, "kal": kal, "yonelim": [float(v) for v in e["INSAN_YONELIM"].split()],
            "enkaz_n": int(e["ENKAZ_KUTU_SAYISI"]), "enkaz_cap": float(e["ENKAZ_CAP_M"]), "enkaz_yuk": float(e["ENKAZ_YUKSEKLIK_M"])}


def hedef_konumlari(c):
    """Görüş alanına göre ölçeklenmiş konumlar: (x, y) m. x görüntü dikey, y görüntü yatay eksenidir.
    İnsan grubu: her konumda üç yönelim 2,5 m aralıkla; enkaz yığınları ters tarafta."""
    yw = c["alt"] * math.tan(c["fov"] / 2)         # görüntü yatay yarı genişliği (yerde, m)
    yh = yw * c["h"] / c["w"]
    insan = []
    # (merkez, kenar, köşe) grup merkezleri; yönelimler grup içinde 2,5 m aralıkla dizilir (merkez/kenar: x ekseninde, köşe: y ekseninde)
    gruplar = [((0.0, 0.0), (1, 0)), ((0.0, 0.75 * yw), (1, 0)), ((0.7 * yh, 0.75 * yw), (0, 1))]
    return yw, yh, gruplar


def sdf_uret_insan(cikti):
    import random
    c = cfg()
    ic = insan_cfg()
    yw, yh, gruplar = hedef_konumlari(c)
    p = []
    p.append('<?xml version="1.0" encoding="UTF-8"?>')
    p.append('<!-- Otomatik üretildi (araclar/kamera_olcum.py dunya-insan); yatan insan ve enkaz yalnız ölçüm temsilidir. -->')
    p.append('<sdf version="1.9">')
    p.append(f'  <world name="{c["dunya"]}">')
    p.append(SAHNE_TEMEL)
    p.append(f'''    <model name="kamera_1"><static>true</static><pose>0 0 {c["alt"]:g} 0 1.5707963 0</pose><link name="link">
      <sensor name="kamera" type="camera"><always_on>1</always_on><update_rate>{c["hz"]:g}</update_rate><visualize>false</visualize>
        <topic>{konu_adi(1)}</topic>
        <camera><horizontal_fov>{c["fov"]:g}</horizontal_fov><image><width>{c["w"]}</width><height>{c["h"]}</height><format>R8G8B8</format></image>
          <clip><near>0.1</near><far>200</far></clip></camera></sensor></link></model>''')
    ad = 0
    for gi, ((gx, gy), (dx, dy)) in enumerate(gruplar):
        for yi, ang in enumerate(ic["yonelim"]):
            ofs = (yi - 1) * 2.5
            x, y = gx + ofs * dx, gy + ofs * dy
            # uzun kenar kutuda x ekseni boyunca; "yönelim 0°" = uzun kenar görüntü yatay (dünya y) eksenine paralel => yaw = 90° - yönelim
            yaw = math.radians(90.0 - ang)
            r, g, b = INSAN_RENKLERI[ad % len(INSAN_RENKLERI)]
            ad += 1
            p.append(f'''    <model name="insan_{KONUMLAR[gi]}_{int(ang)}"><static>true</static><pose>{x:.4f} {y:.4f} {ic["kal"] / 2:g} 0 0 {yaw:.6f}</pose><link name="link">
      <visual name="visual"><geometry><box><size>{ic["uz"]:g} {ic["dar"]:g} {ic["kal"]:g}</size></box></geometry>
        <material><ambient>0 0 0 1</ambient><diffuse>0 0 0 1</diffuse><specular>0 0 0 1</specular><emissive>{r} {g} {b} 1</emissive></material></visual>
    </link></model>''')
    # enkaz yığınları ters tarafta (negatif x ve y): merkeze yakın, kenar, köşe
    yigin_konum = [(0.0, -0.45 * yw), (0.0, -0.75 * yw), (-0.7 * yh, -0.75 * yw)]
    for yi, (px, py) in enumerate(yigin_konum):
        rnd = random.Random(100 + yi)
        for k in range(ic["enkaz_n"]):
            a = rnd.uniform(0, 2 * math.pi)
            rr = rnd.uniform(0, ic["enkaz_cap"] / 2 - 0.4)
            sx, sy, sz = rnd.uniform(0.5, 1.4), rnd.uniform(0.3, 1.0), rnd.uniform(0.2, ic["enkaz_yuk"])
            yaw = rnd.uniform(0, math.pi)
            r, g, b = ENKAZ_TONLARI[rnd.randrange(len(ENKAZ_TONLARI))]
            p.append(f'''    <model name="enkaz_{KONUMLAR[yi]}_{k}"><static>true</static><pose>{px + rr * math.cos(a):.4f} {py + rr * math.sin(a):.4f} {sz / 2:.4f} 0 0 {yaw:.6f}</pose><link name="link">
      <visual name="visual"><geometry><box><size>{sx:.3f} {sy:.3f} {sz:.3f}</size></box></geometry>
        <material><ambient>0 0 0 1</ambient><diffuse>0 0 0 1</diffuse><specular>0 0 0 1</specular><emissive>{r} {g} {b} 1</emissive></material></visual>
    </link></model>''')
    p.append('  </world>')
    p.append('</sdf>')
    with open(cikti, "w", encoding="utf-8") as f:
        f.write("\n".join(p) + "\n")


def _alt_piksel_olcu(img, hedef_renk, pad=8):
    """Renkli levha/kutu: kısmi kaplama (alfa) ağırlıklı ikinci momentlerden uzun/dar kenar (piksel), alan, yön, merkez."""
    import numpy as np
    uzak = np.linalg.norm(img - hedef_renk, axis=2)
    maske = uzak < 60.0
    if maske.sum() < 4:
        return None
    ys, xs = np.nonzero(maske)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    ya, yb = max(0, y0 - pad), min(img.shape[0], y1 + pad + 1)
    xa, xb = max(0, x0 - pad), min(img.shape[1], x1 + pad + 1)
    pen = img[ya:yb, xa:xb]
    halka = np.ones(pen.shape[:2], bool)
    halka[(y0 - ya):(y1 - ya + 1), (x0 - xa):(x1 - xa + 1)] = False
    bg = np.median(pen[halka], axis=0)
    d = hedef_renk - bg
    alfa = np.clip(((pen - bg) @ d) / (d @ d), 0.0, 1.0)
    alan = float(alfa.sum())
    yy, xx = np.mgrid[0:pen.shape[0], 0:pen.shape[1]]
    cx, cy = float((alfa * xx).sum() / alan), float((alfa * yy).sum() / alan)
    cxx = float((alfa * (xx - cx) ** 2).sum() / alan)
    cyy = float((alfa * (yy - cy) ** 2).sum() / alan)
    cxy = float((alfa * (xx - cx) * (yy - cy)).sum() / alan)
    ev, evec = np.linalg.eigh(np.array([[cxx, cxy], [cxy, cyy]]))
    uzun = math.sqrt(12.0 * max(ev[1], 0.0))
    dar = math.sqrt(12.0 * max(ev[0], 0.0))
    aci = math.degrees(math.atan2(evec[1, 1], evec[0, 1])) % 180.0      # uzun eksenin görüntü yatay eksenine göre açısı
    return {"uzun_px": uzun, "dar_px": dar, "alan_px": alan, "aci": aci, "merkez": (cx + xa, cy + ya), "kutu": (int(x1 - x0 + 1), int(y1 - y0 + 1))}


def hedef_modu(konu, cikti_dizini):
    """Aday görüş açısı ölçümü: yatan insan (9 kombinasyon) ve enkaz yığınları; bir kare alınır."""
    import cv2
    import numpy as np
    from PIL import Image as PImage
    c = cfg()
    ic = insan_cfg()
    a = Alici([konu], veri_tut=True)
    t0 = time.monotonic()
    while a.sayi(konu) < 4 and time.monotonic() - t0 < 120:
        time.sleep(0.5)
    if a.sayi(konu) < 4:
        print("SONUC kaldi hedef_kare | kare alınamadı", flush=True)
        return 1
    with a.kilit:
        ns, _, veri, w, h, step, pf = a.kayit[konu][3]
    os.makedirs(cikti_dizini, exist_ok=True)
    img = np.frombuffer(veri, dtype=np.uint8).reshape(h, w, 3).astype(np.float64)
    PImage.fromarray(img.astype(np.uint8)).save(os.path.join(cikti_dizini, f"hedef_{int(round(math.degrees(c['fov']) * 10)):04d}.png"))
    yw, yh, _ = hedef_konumlari(c)
    print(f"HEDEF sahne: SDF HFOV={c['fov']:.4f}rad ({math.degrees(c['fov']):.2f}°) beklenen iz genişliği={2 * yw:.2f}m x {2 * yh:.2f}m; kare {w}x{h}", flush=True)
    satirlar = []
    ad = 0
    for gi in range(3):
        for ang in ic["yonelim"]:
            renk = srgb255(INSAN_RENKLERI[ad % len(INSAN_RENKLERI)])
            ad += 1
            o = _alt_piksel_olcu(img, renk)
            if o is None:
                print(f"HEDEF insan {KONUMLAR[gi]} {int(ang)}°: bulunamadı", flush=True)
                continue
            satirlar.append((KONUMLAR[gi], int(ang), o))
            print(f"HEDEF insan {KONUMLAR[gi]:6s} yönelim={int(ang):2d}°: uzun={o['uzun_px']:.2f}px dar={o['dar_px']:.2f}px alan={o['alan_px']:.1f}px² ölçülen_açı={o['aci']:.1f}° "
                  f"merkez=({o['merkez'][0]:.0f},{o['merkez'][1]:.0f}) kutu={o['kutu'][0]}x{o['kutu'][1]}", flush=True)
    if not satirlar:
        print("SONUC kaldi hedef_insan | hiçbir insan hedefi bulunamadı", flush=True)
        return 1
    dar = [o["dar_px"] for _, _, o in satirlar]
    uzun = [o["uzun_px"] for _, _, o in satirlar]
    print(f"HEDEF insan ozet: n={len(satirlar)}/9 dar_kenar min={min(dar):.2f}px ort={sum(dar) / len(dar):.2f}px maks={max(dar):.2f}px | uzun_kenar min={min(uzun):.2f} ort={sum(uzun) / len(uzun):.2f} maks={max(uzun):.2f}px", flush=True)
    for kn in KONUMLAR:
        v = [o["dar_px"] for k_, _, o in satirlar if k_ == kn]
        if v:
            print(f"HEDEF insan konum {kn}: dar_kenar ort={sum(v) / len(v):.2f}px min={min(v):.2f}px", flush=True)
    # Enkaz: yer renklerinden farklı ve insan renklerine uymayan pikseller; yığınlar bağlı bileşenlerle
    bg = np.median(img.reshape(-1, 3), axis=0)
    fark = np.linalg.norm(img - bg, axis=2) > 30.0
    insan_maske = np.zeros(fark.shape, np.uint8)
    for r_ in INSAN_RENKLERI:
        insan_maske |= (np.linalg.norm(img - srgb255(r_), axis=2) < 60.0).astype(np.uint8)
    fark &= ~(cv2.dilate(insan_maske, np.ones((9, 9), np.uint8)) > 0)    # insan hedeflerinin kenar piksellerini enkaz sayma
    kapali = cv2.dilate(fark.astype(np.uint8), np.ones((5, 5), np.uint8))
    n, etiket, ist, cent = cv2.connectedComponentsWithStats(kapali, connectivity=8)
    yiginlar = [(i, ist[i, cv2.CC_STAT_AREA]) for i in range(1, n) if ist[i, cv2.CC_STAT_AREA] > 200]
    # merkeze uzaklığa göre sırala: en yakın = merkeze yakın, orta = kenar, en uzak = köşe
    yiginlar.sort(key=lambda t: float(np.hypot(cent[t[0]][0] - w / 2, cent[t[0]][1] - h / 2)))
    adlar = ["merkeze yakın", "kenar", "köşe"]
    capl = []
    for sira, (i, alan) in enumerate(yiginlar[:3]):
        pts = np.column_stack(np.nonzero((etiket == i) & fark))[:, ::-1].astype(np.float32)
        (rcx, rcy), (rw, rh), _ = cv2.minAreaRect(pts)
        uzun_k, kisa_k = max(rw, rh), min(rw, rh)
        cap = float(max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1])))
        capl.append((adlar[sira], uzun_k, kisa_k, cap))
        print(f"HEDEF enkaz {adlar[sira]}: en_boy_oranı={uzun_k / max(kisa_k, 1e-9):.2f} (minAreaRect {uzun_k:.1f}x{kisa_k:.1f}px) çap(bbox maks)={cap:.1f}px alan={alan}px² merkez=({cent[i][0]:.0f},{cent[i][1]:.0f})", flush=True)
    if len(capl) < 3:
        print(f"SONUC kaldi hedef_enkaz | yalnız {len(capl)} yığın bulundu (3 bekleniyor)", flush=True)
        return 1
    print(f"HEDEF enkaz ozet: çap min={min(x[3] for x in capl):.1f}px ort={sum(x[3] for x in capl) / 3:.1f}px maks={max(x[3] for x in capl):.1f}px; "
          f"yatan insan en_boy_oranı (model) = {ic['uz'] / ic['dar']:.2f}", flush=True)
    print(f"SONUC gecti hedef_olcum | {len(satirlar)} insan, {len(capl)} enkaz yığını, dar kenar min {min(dar):.2f}px", flush=True)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    mod = sys.argv[1]
    if mod == "dunya" and len(sys.argv) == 4:
        sdf_uret(sys.argv[2], int(sys.argv[3]))
        return 0
    if mod == "kare" and len(sys.argv) == 5:
        return kare_modu(sys.argv[2].split(","), float(sys.argv[3]), sys.argv[4])
    if mod == "dunya-insan" and len(sys.argv) == 3:
        sdf_uret_insan(sys.argv[2])
        return 0
    if mod == "hedef" and len(sys.argv) == 4:
        return hedef_modu(sys.argv[2], sys.argv[3])
    if mod == "k10" and len(sys.argv) == 4:
        return k10_modu(sys.argv[2], sys.argv[3])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
