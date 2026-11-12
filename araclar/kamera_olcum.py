#!/usr/bin/env python3
"""Kamera damga/sıra ölçümü (K9) ve yatay görüş açısı ölçümü (K10).

Kullanım:
  kamera_olcum.py dunya <cikti.sdf> <kamera_sayisi>                    deneme sahnesini config değerlerinden üretir
  kamera_olcum.py kare  <konu1[,konu2..]> <sim_sn> <csv_dosyasi>       kare damgalarını kaydeder ve K9 istatistiklerini yazar
  kamera_olcum.py k10   <konu> <cikti_klasoru>                         bir kare alır, hedef piksel boyutlarından HFOV'yi hesaplar
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
    for t in e["CAM_TARGETS"].split():
        k, x, y = (float(v) for v in t.split(":"))
        hedefler.append((k, x, y))
    return {
        "w": int(e["CAM_WIDTH"]), "h": int(e["CAM_HEIGHT"]), "hz": float(e["CAM_RATE_HZ"]), "alt": float(e["CAM_ALT_M"]),
        "fov": float(e["CAM_SDF_HFOV_RAD"]), "dunya": e["CAM_WORLD"], "hedefler": hedefler, "aralik": float(e["CAM_SPACING_M"]),
    }


def konu_adi(i):
    return f"kamera_{i}/image"


def sdf_uret(cikti, n_kamera):
    c = cfg()
    p = []
    p.append('<?xml version="1.0" encoding="UTF-8"?>')
    p.append('<!-- Otomatik üretildi (araclar/kamera_olcum.py dunya); değerler config/deney.env içindeki CAM_* ayarlarından gelir. -->')
    p.append('<sdf version="1.9">')
    p.append(f'  <world name="{c["dunya"]}">')
    p.append('''    <physics type="ode">
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
      <direction>0.001 0.625 -0.78</direction><diffuse>0.904 0.904 0.904 1</diffuse><specular>0 0 0 1</specular></light>''')
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
        hedef = np.array([r, g, b]) * 255.0
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
    if mod == "k10" and len(sys.argv) == 4:
        return k10_modu(sys.argv[2], sys.argv[3])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
