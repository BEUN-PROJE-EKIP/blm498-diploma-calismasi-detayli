#!/usr/bin/env python3
"""Aday alan boyutları için simülasyonsuz hesap tablosu (config/ dosyalarını DEĞİŞTİRMEZ; bellekte `rota.uret` çağrılır, hiçbir dosya yazılmaz).

Kullanım:  python araclar/alan_aday_tablo.py [--boyutlar 240,270,300,330,360] [--hedef-sayisi 30] [--env <yol>]
Her aday için kare alan (genişlik = yükseklik = S m) `config/deney.env` değerleriyle (3 bölge, 30 m, HFOV 65°, 2 m en az örtüşme, ROTA_HIZ_MS, CAM_RATE_HZ) üretilir.
Sütunlar: bölge boyutu, şerit sayısı, araç başına rota uzunluğu (yatay çokgen uzunluğu), nominal tarama süresi (uzunluk / hız), araç başına ve toplam görev karesi
(= 1 + ⌊süre · CAM_RATE_HZ⌋: ilk noktadaki kare dahil; koşuda gerçek sayı ±1), merkezi modda ham görüntü yükü (kare · CAM_WIDTH·CAM_HEIGHT·3 bayt) ve 25 Mbit/s'de
tek yönlü aktarım süresi (GŞÖA 6.5 hesabı: bit/ağ hızı; ağ hızı NET_RATE_MBIT değil ölçülen profil değeridir: --ag-mbit, öntanımlı 25),
şerit yerleşimi (ardışık şerit aralığı, gerçek komşu örtüşme, "israf" = örtüşmenin 2 m en azdan fazlası ve ilk-son şerit aralığına oranı, ile şerit sayısı tam sayıya
yuvarlanmasaydı son şeridin bölge kenarından taşacağı miktar), hedef yoğunluğu (hedef sayısı, ALAN_KENAR_PAYI_M kenar payı, merkezler en az 10 m).
Yalnız standart kitaplık. Çıkış 0 tamam, 2 kullanım/okuma hatası.
"""
import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

from swarm_vehicle import rota  # noqa: E402

HEDEF_AYRIM_M = 10.0   # [belge] hedef merkezleri arası en az uzaklık (deney.env SAHNE_*)


def hesapla(ham, boyut, hedef_sayisi, ag_mbit):
    h = dict(ham)
    h["ALAN_GENISLIK_M"], h["ALAN_YUKSEKLIK_M"] = str(boyut), str(boyut)
    d = rota.uret(h)
    hiz, hz = float(ham["ROTA_HIZ_MS"]), float(ham["CAM_RATE_HZ"])
    kare_bayt = int(ham["CAM_WIDTH"]) * int(ham["CAM_HEIGHT"]) * 3
    w = d["serit"]["iz_genisligi_m"]
    ort = d["serit"]["ortusme_min_m"]
    r0 = d["rotalar"][0]["noktalar"]
    uzunluk = []
    for r in d["rotalar"]:
        n = r["noktalar"]
        uzunluk.append(sum(math.dist(n[i], n[i + 1]) for i in range(len(n) - 1)))
    b = d["bolgeler"][0]
    bolge_gen = b["x_max"] - b["x_min"]
    bolge_yuk = b["y_max"] - b["y_min"]
    m = len(r0) // 2
    xs = [r0[2 * i][0] for i in range(m)]
    adim = (xs[-1] - xs[0]) / (m - 1) if m > 1 else 0.0
    gercek_ort = w - adim if m > 1 else float("nan")
    fazla_toplam = (m - 1) * (gercek_ort - ort) if m > 1 else 0.0
    # yuvarlanmasaydı: ilk şerit sol kenarda, her şerit (w - ort) ilerler; son şeridin sağ kenarı bölge kenarını ne kadar aşar
    saf = (m - 1) * (w - ort) + w - bolge_gen if m > 1 else w - bolge_gen
    sure = [u / hiz for u in uzunluk]
    kare = [1 + int(s * hz) for s in sure]
    toplam_kare = sum(kare)
    bayt = toplam_kare * kare_bayt
    aktarim_s = bayt * 8 / (ag_mbit * 1e6)
    kullanilabilir = (boyut - 2 * float(ham["ALAN_KENAR_PAYI_M"])) ** 2
    return {
        "boyut": boyut, "bolge": f"{bolge_gen:g} × {bolge_yuk:g}", "serit": m, "uzunluk": max(uzunluk), "uzunluk_min": min(uzunluk), "sure": max(sure), "kare_arac": kare[0],
        "kare_toplam": toplam_kare, "yuk_mb": bayt / 1e6, "aktarim_s": aktarim_s, "adim": adim, "gercek_ort": gercek_ort, "fazla": fazla_toplam,
        "fazla_oran": 100 * fazla_toplam / bolge_gen, "saf_tasma": saf, "hedef_ha": hedef_sayisi / (boyut * boyut / 1e4), "hedef_m2": boyut * boyut / hedef_sayisi,
        "kullanilabilir": kullanilabilir, "disk_dolu": 100 * hedef_sayisi * math.pi * (HEDEF_AYRIM_M / 2) ** 2 / kullanilabilir,
    }


def ana(argv):
    boyutlar, hedef, env, ag = [240, 270, 300, 330, 360], 30, None, 25.0
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--boyutlar" and a:
            boyutlar = [int(x) for x in a.pop(0).split(",")]
        elif k == "--hedef-sayisi" and a:
            hedef = int(a.pop(0))
        elif k == "--env" and a:
            env = a.pop(0)
        elif k == "--ag-mbit" and a:
            ag = float(a.pop(0))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    try:
        ham = rota.deney_env_oku(env)
        sat = [hesapla(ham, b, hedef, ag) for b in boyutlar]
    except (OSError, ValueError, KeyError) as e:
        print(f"(-) hesap yapılamadı: {e}", file=sys.stderr)
        return 2
    hiz, hz = ham["ROTA_HIZ_MS"], ham["CAM_RATE_HZ"]
    print(f"Aday alan tablosu (yapılandırma: 3 bölge, irtifa {ham['ROTA_IRTIFA_M']} m, HFOV {ham['CAM_HFOV_DEG']}°, hız {hiz} m/s [geçici], {hz} Hz, ağ {ag:g} Mbit/s, kare {int(ham['CAM_WIDTH']) * int(ham['CAM_HEIGHT']) * 3} bayt)")
    print()
    print("| Alan S (m) | Bölge (m) | Şerit | Rota uzunluğu (m) | Nominal tarama (s) | Kare/araç | Kare toplam | Merkezi ham yük (MB) | Aktarım 25 Mbit/s (s) | Aktarım / tarama |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for s in sat:
        print(f"| {s['boyut']} | {s['bolge']} | {s['serit']} | {s['uzunluk']:.1f} | {s['sure']:.1f} | {s['kare_arac']} | {s['kare_toplam']} | {s['yuk_mb']:.0f} | {s['aktarim_s']:.0f} | {s['aktarim_s'] / s['sure']:.2f} |")
    print()
    print("| Alan S (m) | Şerit aralığı (m) | Gerçek komşu örtüşme (m) | Şerit sayısı yuvarlanmasaydı son şerit taşması = toplam fazla örtüşme (m) | Bölge genişliğine oranı (%) | Hedef/ha | Hedef başına alan (m²) | Kenar payı sonrası alan (m²) | 10 m ayrım diskinin doluluğu (%) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for s in sat:
        print(f"| {s['boyut']} | {s['adim']:.2f} | {s['gercek_ort']:.2f} | {s['saf_tasma']:.2f} | {s['fazla_oran']:.1f} | {s['hedef_ha']:.2f} | {s['hedef_m2']:.0f} | {s['kullanilabilir']:.0f} | {s['disk_dolu']:.1f} |")
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
