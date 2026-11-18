#!/usr/bin/env python3
"""Poz tamponu koşu analizi (YALNIZ okuma): telemetri hızı, kare–poz kayıtlarının tamlığı ve tutarlılığı, enterpolasyonlu PX4 pozunun Gazebo gerçek pozuyla karşılaştırması,
PX4 zamanı − sim saati farkı, hata enjeksiyonu (isteğe bağlı).

Kullanım:  python3 -I araclar/analiz/poz_analiz.py <koşu_klasörü> --arac N [--enjeksiyon]
Girdi (koşu klasörü): kayit/telemetri_<kimlik>.jsonl, kayit/kare_poz_<kimlik>.jsonl, kayit/kare_sonuc_<kimlik>.jsonl, gz_gercek_poz.jsonl (araclar/olcum/poz_gercek_kayit.py), arac_<kimlik>.log.
Çıktı: `SONUC gecti|kaldi <ad> | <ayrıntı>` (test betiği bunları (+)/(-) yapar), `TABLO ...` ve `BILGI ...` satırları. Genel olarak eşik koymaz, sayıları raporlar; yalnız şu sınır denetimleri `kaldi` üretir:
yatay hata ortancası > 2 m, |PX4 − sim zaman farkı| > 10 ms, telemetri hızı (ortanca ≤ 50 ms ve p95 < POZ_ARALIK_SINIR_MS). Yalnız standart kitaplık.
Çıkış: 0 (SONUC kaldi olsa da analiz tamamlandıysa; karar betiktedir), 2 kullanım/girdi hatası.
"""
import bisect
import json
import math
import os
import re
import sys

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SATIR = re.compile(r'^([A-Z0-9_]+)=(?:"([^"]*)"|(\S*))\s*(?:#.*)?$')
NS = 10 ** 9


def env_oku():
    d = {}
    with open(os.path.join(KOK, "config", "deney.env"), encoding="utf-8") as f:
        for s in f:
            m = _SATIR.match(s.strip())
            if m:
                d[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return d


def jsonl(yol):
    with open(yol, encoding="utf-8") as f:
        return [json.loads(s) for s in f if s.strip()]


def yuzdelik(v, p):
    s = sorted(v)
    return s[min(len(s) - 1, int(p / 100 * len(s)))] if s else float("nan")


def ozet(v):
    return f"ortanca {yuzdelik(v, 50):.2f} | p95 {yuzdelik(v, 95):.2f} | en çok {max(v):.2f}" if v else "veri yok"


def yaw_deg(q):
    w, x, y, z = q
    return math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


def acifarki(a, b):
    return (a - b + 180) % 360 - 180


def sonuc(ok, ad, ayrinti):
    print(f"SONUC {'gecti' if ok else 'kaldi'} {ad} | {ayrinti}", flush=True)


def ana(argv):
    a = list(argv)
    klasor = arac = None
    enj = False
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            arac = int(a.pop(0))
        elif k == "--enjeksiyon":
            enj = True
        elif klasor is None and not k.startswith("--"):
            klasor = k
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if klasor is None or arac is None:
        print(__doc__, file=sys.stderr)
        return 2
    ham = env_oku()
    kimlik = int(ham["UAV_SYS_IDS"].split()[arac - 1])
    x0, y0, z0 = (float(v) for v in ham["UAV_START_POSES"].split()[arac - 1].split(","))
    sinir_ns = float(ham["POZ_ARALIK_SINIR_MS"]) * 1e6
    hz = int(float(ham["CAM_RATE_HZ"]))
    try:
        tel = jsonl(os.path.join(klasor, "kayit", f"telemetri_{kimlik}.jsonl"))
        kp = jsonl(os.path.join(klasor, "kayit", f"kare_poz_{kimlik}.jsonl"))
        ks = jsonl(os.path.join(klasor, "kayit", f"kare_sonuc_{kimlik}.jsonl"))
    except OSError as e:
        print(f"(-) girdi okunamadı: {e}", file=sys.stderr)
        return 2
    gz_yol = os.path.join(klasor, "gz_gercek_poz.jsonl")
    gz = jsonl(gz_yol) if os.path.exists(gz_yol) else []

    # --- (a) telemetri hızı -------------------------------------------------------------------------------------------------------------
    kabul = [t for t in tel if t["kabul"]]
    red = [t for t in tel if not t["kabul"]]
    tk = [t["kaynak_ns"] for t in kabul]
    araliklar = {"hepsi": [], "yerde": [], "havada": []}
    for i in range(1, len(kabul)):
        ms = (tk[i] - tk[i - 1]) / 1e6
        araliklar["hepsi"].append(ms)
        havada = -kabul[i]["konum_ned_m"][2] > 1.0
        araliklar["havada" if havada else "yerde"].append(ms)
    tsure = (tk[-1] - tk[0]) / 1e9 if len(tk) > 1 else 0
    print(f"BILGI telemetri örnek={len(tel)} kabul={len(kabul)} reddedilen={len(red)} ({sorted({t['red_neden'] for t in red})}) süre={tsure:.1f} sn (kaynak) hız≈{len(kabul) / tsure if tsure else 0:.1f} Hz")
    for ad, v in araliklar.items():
        print(f"TABLO telemetri_aralik_ms {ad:7s} n={len(v):6d} | {ozet(v)}")
    ort, p95 = yuzdelik(araliklar["hepsi"], 50), yuzdelik(araliklar["hepsi"], 95)
    sonuc(len(araliklar["hepsi"]) > 100 and ort <= 50 and p95 < sinir_ns / 1e6, "telemetri_hizi",
          f"ortanca {ort:.2f} ms (≤ 50), p95 {p95:.2f} ms (< {sinir_ns / 1e6:g}); hız komutu gönderilmedi (PX4'e yazma yok)")
    if not enj:
        sonuc(len(red) == 0, "telemetri_ret_yok", f"reddedilen örnek {len(red)}")

    # --- (b) kare–poz kümesi ve tutarlılık ------------------------------------------------------------------------------------------------
    ns_ks, ns_kp = [r["n"] for r in ks], [r["n"] for r in kp]
    sonuc(len(ns_kp) == len(set(ns_kp)) and set(ns_kp) == set(ns_ks) and len(ks) > 0, "kare_poz_kumesi",
          f"kare_sonuc {len(ks)} numara, kare_poz {len(kp)} kayıt, küme birebir={set(ns_kp) == set(ns_ks)}, yinelenen={len(ns_kp) - len(set(ns_kp))}")
    gecerli = [r for r in kp if r["gecerli"]]
    nedenler = {}
    for r in kp:
        if not r["gecerli"]:
            nedenler[r["neden"]] = nedenler.get(r["neden"], 0) + 1
    print(f"BILGI kare_poz toplam={len(kp)} geçerli={len(gecerli)} (%{100 * len(gecerli) / max(1, len(kp)):.2f}) geçersiz nedenleri={nedenler or 'yok'}")
    bek = [r["bekleme_ms"] for r in kp]
    print(f"TABLO bekleme_ms n={len(bek)} | {ozet(bek)}")
    # bağımsız yeniden hesap (aynı telemetri kaydından): geçerlilik ve konum
    yanlis = []
    for r in kp:
        t = r["kare_ns"]
        if not tk or t < tk[0]:
            bekle_gec = False
        else:
            i = bisect.bisect_left(tk, t)
            if i >= len(tk):
                bekle_gec = False
            elif tk[i] == t:
                bekle_gec = True
            else:
                bekle_gec = (tk[i] - tk[i - 1]) <= sinir_ns
        if bekle_gec != r["gecerli"]:
            yanlis.append((r["n"], "gecerlilik", r["gecerli"], bekle_gec))
            continue
        if r["gecerli"]:
            i = bisect.bisect_left(tk, t)
            p1, p2 = kabul[i - 1 if tk[i] != t else i]["konum_ned_m"], kabul[i]["konum_ned_m"]
            f = 0.0 if tk[i] == t else (t - tk[i - 1]) / (tk[i] - tk[i - 1])
            bek_k = [u + f * (v - u) for u, v in zip(p1, p2)]
            if max(abs(u - v) for u, v in zip(bek_k, r["konum_ned_m"])) > 1e-6:
                yanlis.append((r["n"], "konum", r["konum_ned_m"], bek_k))
    sonuc(not yanlis, "kare_poz_tutarlilik", f"{len(kp)} kayıt telemetri dosyasından bağımsız yeniden hesaplandı (geçerlilik + doğrusal konum, 1e-6 m); uyuşmayan {len(yanlis)}" + (f" ilk: {yanlis[:3]}" if yanlis else ""))
    if not enj:
        sonuc(len(gecerli) == len(kp), "kare_poz_gecerli_oran", f"geçerli {len(gecerli)}/{len(kp)}; geçersiz nedenleri {nedenler or 'yok'}")
    else:
        enjekte = [t for t in red if t["red_neden"] == "enjeksiyon"]
        if enjekte:
            k0, k1 = enjekte[0]["kaynak_ns"], enjekte[-1]["kaynak_ns"]
            ic = [r for r in kp if k0 <= r["kare_ns"] <= k1]
            dis = [r for r in kp if r["kare_ns"] < k0 - sinir_ns or r["kare_ns"] > k1 + 1 * NS]
            ic_gec = [r for r in ic if not r["gecerli"]]
            dis_gec = [r for r in dis if r["gecerli"]]
            sonuc(len(enjekte) > 0 and len(ic) > 0 and len(ic_gec) == len(ic) and {r["neden"] for r in ic_gec} <= {"aralik_asildi", "bekleme_asildi"},
                  "enjeksiyon_penceresi", f"enjekte edilen örnek {len(enjekte)} ({(k1 - k0) / 1e9:.2f} sn kaynak); penceredeki kare {len(ic)}, hepsi geçersiz={len(ic_gec) == len(ic)}, nedenler {sorted({r['neden'] for r in ic_gec})}")
            sonuc(len(dis) > 0 and len(dis_gec) == len(dis), "enjeksiyon_disi_gecerli", f"pencere dışındaki kare {len(dis)}, geçerli {len(dis_gec)}")
        else:
            sonuc(False, "enjeksiyon_penceresi", "enjeksiyon örneği yok (POZ_TEST_DURDUR etkisiz)")

    # --- (c) gerçek poz karşılaştırması --------------------------------------------------------------------------------------------------
    if gz:
        gp = [g for g in gz if g["k"] == "poz"]
        gs = [g["sim_ns"] for g in gp]
        sonuc(len(gp) > 1000, "gz_gercek_poz_kaydi", f"gerçek poz örneği {len(gp)} (sim {(gs[-1] - gs[0]) / 1e9:.1f} sn)" if gp else "gerçek poz kaydı yok")
        yatay, irtifa, yaw = [], [], []
        ornek_ilk = None
        for r in gecerli:
            t = r["kare_ns"]
            i = bisect.bisect_left(gs, t)
            if i <= 0 or i >= len(gs) or gs[i] - gs[i - 1] > 50 * 10 ** 6:
                continue
            f = (t - gs[i - 1]) / (gs[i] - gs[i - 1])
            g = [u + f * (v - u) for u, v in zip(gp[i - 1]["p"], gp[i]["p"])]
            n_, e_, d_ = r["konum_ned_m"]
            est = (x0 + e_, y0 + n_, z0 - d_)
            yatay.append(math.hypot(est[0] - g[0], est[1] - g[1]))
            irtifa.append(est[2] - g[2])
            y_est = 90.0 - yaw_deg(r["q_wxyz"])                      # NED yaw (kuzeyden saat yönü) → ENU yaw (doğudan saat yönü tersi)
            y_gz = acifarki(yaw_deg(gp[i - 1]["q"]), 0) if f < 0.5 else yaw_deg(gp[i]["q"])
            yaw.append(acifarki(y_est, y_gz))
            if ornek_ilk is None:
                ornek_ilk = (r["n"], est, g, y_est, y_gz)
        mutlak = lambda v: [abs(x) for x in v]  # noqa: E731
        print(f"BILGI gerçek poz karşılaştırması: {len(yatay)}/{len(gecerli)} geçerli kare (ilk: {ornek_ilk})")
        print(f"TABLO yatay_hata_m  n={len(yatay)} | {ozet(yatay)}")
        print(f"TABLO irtifa_hata_m n={len(irtifa)} (işaretli: tahmin − gerçek) | ortanca {yuzdelik(irtifa, 50):+.3f} | mutlak {ozet(mutlak(irtifa))}")
        print(f"TABLO yaw_hata_der  n={len(yaw)} (işaretli: tahmin − gerçek) | ortanca {yuzdelik(yaw, 50):+.3f} | mutlak {ozet(mutlak(yaw))}")
        om = yuzdelik(yatay, 50)
        sonuc(len(yatay) > 0 and om <= 2.0, "yatay_hata_ortanca", f"yatay hata ortancası {om:.3f} m (DUR eşiği 2 m)")
        # --- (d) zaman farkı --------------------------------------------------------------------------------------------------------------
        # Ölçülen, yalnız (PX4 kaynak zamanı − sim saati) DEĞİL; buna iki taşıma yolunun (gz saat konusu ile MAVLink → mavsdk_server → gRPC) en küçük gecikmeleri arasındaki fark da eklenir:
        # her iki zaman da alım anındaki CLOCK_MONOTONIC ile eşlenir ve 10 sn'lik pencerelerde alt zarfların (min(mono − zaman)) farkı alınır (RTF ≠ 1 olduğundan pencere başına).
        # K8'in yaş düzeltmeli yöntemiyle birebir karşılaştırılabilir değildir (orada her okuma kendi yaşı kadar örnekleme anına taşınmıştı); yalnız büyüklük bakımından kıyaslanır.
        saat = [g for g in gz if g["k"] == "saat"]
        pen = 10 * NS
        ofs = []
        if saat and kabul:
            m0 = min(kabul[0]["alinma_mono_ns"], saat[0]["mono_ns"])
            ta, ts = {}, {}
            for t in kabul:
                w = (t["alinma_mono_ns"] - m0) // pen
                ta[w] = min(ta.get(w, 10 ** 30), t["alinma_mono_ns"] - t["kaynak_ns"])
            for s in saat:
                w = (s["mono_ns"] - m0) // pen
                ts[w] = min(ts.get(w, 10 ** 30), s["mono_ns"] - s["sim_ns"])
            for w in sorted(set(ta) & set(ts)):
                ofs.append((w, (ts[w] - ta[w]) / 1e6))             # kaynak − sim = (mono−sim)_alt − (mono−kaynak)_alt
        if ofs:
            v = [o for _, o in ofs]
            egim = (v[-1] - v[0]) / max(1, (ofs[-1][0] - ofs[0][0]) * 10) * 1000 if len(v) > 1 else 0.0
            print(f"TABLO zaman_farki_ms (PX4 − sim; {len(v)} pencere × 10 sn) | ilk {v[0]:+.2f} | son {v[-1]:+.2f} | ortanca {yuzdelik(v, 50):+.2f} | min {min(v):+.2f} | maks {max(v):+.2f} | eğim {egim:+.1f} µs/s")
            sonuc(max(abs(x) for x in v) <= 10.0, "zaman_farki", f"PX4 zamanı − sim saati ortancası {yuzdelik(v, 50):+.2f} ms (K8: −4,1 ms); en büyük |fark| {max(abs(x) for x in v):.2f} ms (DUR eşiği ±10 ms); yöntem: alım monotoniğine göre pencere başına alt zarf farkı")
        else:
            sonuc(False, "zaman_farki", "ölçülemedi (saat/telemetri örneği yok)")
    else:
        print("BILGI gz_gercek_poz.jsonl yok: gerçek poz karşılaştırması ve zaman farkı atlandı")
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
