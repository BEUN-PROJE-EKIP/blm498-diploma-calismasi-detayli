#!/usr/bin/env python3
"""Doygun hatta DDS canlılığı denemesinin (M2 2.4; risk U21/U14) çözümlemesi (ölçüm yardımcısı).

Kullanım:  python araclar/dds_doygunluk_analiz.py --s0 <koşu> --s1 <koşu> --s2 <koşu> [--boyutlar <json>] [--cikti <md>]
Her senaryo klasörü: `kosu.json`, `kayit/yer_istasyonu_{gorev,durum,durum_ham,kare}.jsonl`, `arac_<k>.log`, `kayit/kare_sonuc_<k>.jsonl`, `kayit/gazebo_damga.jsonl`, `tc_ornek.jsonl` (araclar/tc_izle.py) ve
(S1/S2) `sentetik_yuk.jsonl` (araclar/sentetik_yuk.py). Çıktı: önce "SONUC <gecti|kaldi> ..." (YALNIZ deneyin önkoşulları: S1/S2'de hattın gerçekten doygun olması), sonra yan yana Markdown ölçüm tabloları.
Ölçüm "sorun var" gösterirse bu test hatası DEĞİLDİR: sayılar olduğu gibi yazılır, yorum/öneri yok. Yalnız standart kitaplık; çıkış 0 (önkoşullar sağlandı), 1 (kaldı), 2 (kullanım).
Yöntemler: durum gecikmesi = yer istasyonunun alım anındaki simülasyon saati − iletideki `sim_stamp` (aracın yayımladığı andaki sim saati; RTF≈1 ve aynı makine; çözünürlük gz saat konusunun yayım aralığıdır).
Kontrol iletisi gecikmeleri aynı makinedeki CLOCK_MONOTONIC günlük anlarıyla: ScanStart (yer istasyonu t0 → aracın `tarama_baslat_alindi`), COMPLETE (t1 → `complete_alindi`), ScanFinished (aracın `tarama_bitis_yayimlandi` →
yer istasyonunun `tarama_bitisi` olayı), Mission (aracın `basladi` → `mission_alindi`: keşif + teslim süresi)."""
import json
import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arac_sureci_analiz as asa  # noqa: E402

NS = 10 ** 9
KALDI = 0
HAT_MBIT = 25.0


def sonuc(gecti, ad, ayrinti):
    global KALDI
    if not gecti:
        KALDI += 1
    print(f"SONUC {'gecti' if gecti else 'kaldi'} {ad} | {ayrinti}", flush=True)


def jsonl(yol):
    if not os.path.isfile(yol):
        return []
    with open(yol, encoding="utf-8") as f:
        return [json.loads(s) for s in f if s.strip()]


def yuzdelik(x, q):
    x = sorted(x)
    if not x:
        return float("nan")
    k = (len(x) - 1) * q / 100
    a, b = math.floor(k), math.ceil(k)
    return x[a] + (x[b] - x[a]) * (k - a)


def ozet(x, birim="", n=1):
    if not x:
        return "-"
    return f"{yuzdelik(x, 50):.{n}f} / {yuzdelik(x, 95):.{n}f} / {max(x):.{n}f}{birim}"


def azalis_sayisi(ornekler, sinir_mono=None):
    """(mono_ns, sayı) dizisinde azalışlar (eşleşme kaybı) ve sonraki artışlar (yeniden eşleşme). `sinir_mono` (t1) verilirse: (t1'e kadar kayıp, t1'e kadar yeniden eşleşme, t1 sonrası azalış);
    t1 sonrası azalışlar kapanıştır (araçlar ve yer istasyonu COMPLETE'ten sonra çıkarken yayımcı/abone sayıları doğal olarak düşer)."""
    kayip = yeni = sonra = 0
    dustu = False
    for (m0, a), (m1, b) in zip(ornekler, ornekler[1:]):
        if b < a:
            if sinir_mono is None or m1 <= sinir_mono:
                kayip += 1
                dustu = True
            else:
                sonra += 1
        elif b > a and dustu and (sinir_mono is None or m1 <= sinir_mono):
            yeni += 1
    return kayip, yeni, sonra


def olc(klasor, kimlikler):
    r = {"klasor": os.path.basename(klasor.rstrip("/"))}
    gorev = jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_gorev.jsonl"))
    ol = lambda ad: [x for x in gorev if x["olay"] == ad]  # noqa: E731
    t0 = (ol("t0") or [None])[0]
    t1 = (ol("t1") or [None])[0]
    r["t0"], r["t1"] = t0, t1
    r["zaman_asimi"] = (ol("zaman_asimi") or [{}])[0].get("neden")
    r["hata"] = [x.get("neden") for x in ol("hata")]
    logs = {}
    for k in kimlikler:
        yol = os.path.join(klasor, f"arac_{k}.log")
        logs[k] = asa.log_oku(yol) if os.path.isfile(yol) else {}
    r["logs"] = logs
    # --- hat (tc) -----------------------------------------------------------------------------------------------------------------
    tc = [x for x in jsonl(os.path.join(klasor, "tc_ornek.jsonl")) if x.get("sinif") and x.get("yaprak")]
    r["tc"] = tc
    if len(tc) >= 2:
        def pencere(a_ns, b_ns):
            s = [x for x in tc if a_ns <= x["mono_ns"] <= b_ns] or tc
            ilk, son = s[0], s[-1]
            dt = (son["mono_ns"] - ilk["mono_ns"]) / NS or 1.0
            hizlar = [(b["sinif"]["bayt"] - a["sinif"]["bayt"]) * 8 / ((b["mono_ns"] - a["mono_ns"]) / NS) / 1e6 for a, b in zip(s, s[1:]) if b["mono_ns"] > a["mono_ns"]]
            return {"sure": dt, "mbit": (son["sinif"]["bayt"] - ilk["sinif"]["bayt"]) * 8 / dt / 1e6, "mbit_max": max(hizlar) if hizlar else 0.0, "bayt": son["sinif"]["bayt"] - ilk["sinif"]["bayt"],
                    "paket": son["sinif"]["paket"] - ilk["sinif"]["paket"], "dusen_sinif": son["sinif"]["dusen"] - ilk["sinif"]["dusen"], "dusen_yaprak": son["yaprak"]["dusen"] - ilk["yaprak"]["dusen"],
                    "overlimits": son["sinif"]["overlimits"] - ilk["sinif"]["overlimits"], "backlog_max": max(x["yaprak"]["backlog_bayt"] for x in s), "backlog_ort": yuzdelik([x["yaprak"]["backlog_bayt"] for x in s], 50),
                    "backlog_paket_max": max(x["yaprak"]["backlog_paket"] for x in s)}
        r["hat_tum"] = pencere(tc[0]["mono_ns"], tc[-1]["mono_ns"])
        if t0 and t1:
            r["hat_gorev"] = pencere(t0["mono_ns"], t1["mono_ns"])
    # --- durum iletileri ---------------------------------------------------------------------------------------------------------
    ham = jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_durum_ham.jsonl"))
    bosluk, gecikme = {}, {}
    for k in kimlikler:
        m = sorted(x["mono_ns"] for x in ham if x["arac"] == k)
        bosluk[k] = [(b - a) / 1e6 for a, b in zip(m, m[1:])]
        gecikme[k] = [(x["sim_ns"] - x["yayim_sim_ns"]) / 1e6 for x in ham if x["arac"] == k and x["sim_ns"] is not None]
    r["durum_bosluk"], r["durum_gecikme"], r["durum_adet"] = bosluk, gecikme, {k: sum(1 for x in ham if x["arac"] == k) for k in kimlikler}
    r["bayat"] = sum(1 for x in jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_durum.jsonl")) if x["olay"] == "bayat_uyari")
    # araçlar arası durum alımı (araç günlüklerindeki arac_durum kayıtları): kaynak başına boşluk
    ab = {}
    for k in kimlikler:
        d = jsonl(os.path.join(klasor, "kayit", f"arac_durum_{k}.jsonl"))
        for kaynak in kimlikler:
            m = sorted(x["alinma_mono_ns"] for x in d if x["kaynak_arac_kimligi"] == kaynak)
            if len(m) > 1:
                ab.setdefault(k, []).extend((b - a) / 1e6 for a, b in zip(m, m[1:]))
    r["araclar_arasi_bosluk"] = ab
    # --- kontrol iletileri -----------------------------------------------------------------------------------------------------
    k_ = {"ScanStart": [], "COMPLETE": [], "ScanFinished": [], "Mission": []}
    eksik = []
    for k in kimlikler:
        l = logs[k]
        try:
            k_["ScanStart"].append((l["tarama_baslat_alindi"][0]["mono_ns"] - t0["mono_ns"]) / 1e6)
        except (KeyError, TypeError):
            eksik.append(f"ScanStart→araç {k}")
        try:
            k_["COMPLETE"].append((l["complete_alindi"][0]["mono_ns"] - t1["mono_ns"]) / 1e6)
        except (KeyError, TypeError):
            eksik.append(f"COMPLETE→araç {k}")
        try:
            yayim = l["tarama_bitis_yayimlandi"][0]["mono_ns"]
            alim = next(x for x in ol("tarama_bitisi") if x["arac_kimligi"] == k)["mono_ns"]
            k_["ScanFinished"].append((alim - yayim) / 1e6)
        except (KeyError, StopIteration):
            eksik.append(f"ScanFinished araç {k}→yer istasyonu")
        try:
            k_["Mission"].append((l["mission_alindi"][0]["mono_ns"] - l["basladi"][0]["mono_ns"]) / 1e6)
        except (KeyError, IndexError):
            eksik.append(f"Mission→araç {k}")
    r["kontrol"], r["kontrol_eksik"] = k_, eksik
    # --- kare sonuçları ------------------------------------------------------------------------------------------------------------
    yer = jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_kare.jsonl"))
    damga = jsonl(os.path.join(klasor, "kayit", "gazebo_damga.jsonl"))
    kare = {}
    for k in kimlikler:
        b = (logs[k].get("tarama_bitis_yayimlandi") or [None])[0]
        if b is None:
            kare[k] = {"aralik": None, "beklenen": 0, "gelen": 0, "eksik": None, "yinelenen": 0, "L": []}
            continue
        n_ilk, n_son = int(b["n_first"]), int(b["n_last"])
        y = [x for x in yer if x["arac_kimligi"] == k]
        say = {}
        for x in y:
            say[x["n"]] = say.get(x["n"], 0) + 1
        uretim = {x["n"]: x["mono_ns"] for x in damga if x["arac_kimligi"] == k and x["olay"] == "uretim" and isinstance(x["n"], int)}
        kare[k] = {"aralik": (n_ilk, n_son), "beklenen": n_son - n_ilk + 1, "gelen": sum(1 for n in range(n_ilk, n_son + 1) if n in say), "eksik": sum(1 for n in range(n_ilk, n_son + 1) if n not in say),
                   "yinelenen": sum(v - 1 for v in say.values()), "L": [(x["mono_ns"] - uretim[x["n"]]) / 1e6 for x in y if x["sonuc_durumu"] in ("sonuc", "tespit_yok") and x["n"] in uretim]}
    r["kare"] = kare
    if t1:
        r["t1_eksi_bitis_ms"] = t1.get("t1_eksi_son_bitis_ns", 0) / 1e6
    # --- eşleşme / canlılık ---------------------------------------------------------------------------------------------------
    sinir = t1["mono_ns"] if t1 else None
    esl = [(x["mono_ns"], x["yayimci"]) for x in ol("eslesme")]
    r["eslesme_kare_sonuc"] = ([n for _, n in esl], *azalis_sayisi(esl, sinir))
    arac_es = {}
    for k in kimlikler:
        arac_es[k] = {}
        for x in logs[k].get("eslesme_degisti", []):
            arac_es[k].setdefault(x["kaynak"], []).append((x["mono_ns"], int(x["sayi"])))
    r["eslesme_arac"] = {k: {ad: ([n for _, n in s], *azalis_sayisi(s, sinir)) for ad, s in d.items()} for k, d in arac_es.items()}
    yog = os.path.join(klasor, "yer_istasyonu.log")
    dy = []
    if os.path.isfile(yog):
        for s in open(yog, encoding="utf-8"):
            if " durum_eslesme_degisti " in s:
                dy.append((int(s.split(" ")[1]), int(s.rsplit("yayimci=", 1)[1])))
    r["eslesme_durum_gcs"] = ([n for _, n in dy], *azalis_sayisi(dy, sinir))
    # --- sentetik yük -------------------------------------------------------------------------------------------------------------
    yuk = jsonl(os.path.join(klasor, "sentetik_yuk.jsonl"))
    r["yuk"] = None
    if yuk:
        y = {}
        for a in kimlikler:
            kr = [x for x in yuk if x["k"] == "kare" and x["a"] == a]
            kq = [x for x in yuk if x["k"] == "kuyruk" and x["a"] == a]
            oz = next((x for x in yuk if x["k"] == "ozet" and x["a"] == a), None)
            bekle = [(x["gonderim_bitis_ns"] - x["enq_ns"]) / 1e6 for x in kr if x["gonderim_bitis_ns"]]
            u2u = [(x["alim_bitis_ns"] - x["enq_ns"]) / 1e6 for x in kr if x["alim_bitis_ns"]]
            y[a] = {"ozet": oz, "bekle": bekle, "uctan_uca": u2u, "derinlik_max": max((x["derinlik"] for x in kq), default=0), "kuyruk": kq}
        r["yuk"] = y
    return r


def tablo(basliklar, satirlar):
    s = "| " + " | ".join(basliklar) + " |\n|" + "---|" * len(basliklar) + "\n"
    for x in satirlar:
        s += "| " + " | ".join(str(v) for v in x) + " |\n"
    return s


def ana(argv):
    a = list(argv)
    yollar, boyutlar, cikti = {}, None, None
    while a:
        k = a.pop(0)
        if k in ("--s0", "--s1", "--s2") and a:
            yollar[k[2:]] = a.pop(0)
        elif k == "--boyutlar" and a:
            boyutlar = a.pop(0)
        elif k == "--cikti" and a:
            cikti = a.pop(0)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if not yollar:
        print(__doc__, file=sys.stderr)
        return 2
    sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))
    from swarm_vehicle import rota
    ham = rota.deney_env_oku()
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()]
    sn = sorted(yollar)
    R = {s: olc(yollar[s], kimlikler) for s in sn}
    ad = {"s0": "S0 taban", "s1": "S1 sürekli doygunluk", "s2": "S2 başlangıçta doygunluk"}
    # --- önkoşullar ------------------------------------------------------------------------------------------------------------
    for s in sn:
        if s == "s0":
            continue
        r = R[s]
        if not r.get("tc") or not r["yuk"]:
            sonuc(False, f"{s}_yuk_kaydi", "tc örnekleri ya da sentetik yük kaydı yok")
            continue
        oz = [r["yuk"][k]["ozet"] for k in kimlikler if r["yuk"][k]["ozet"]]
        bas = min(o["baslangic_ns"] for o in oz)
        dur = max(o["durdurma_ns"] for o in oz)
        yuk_pencere = [x for x in r["tc"] if bas <= x["mono_ns"] <= dur]
        if len(yuk_pencere) >= 2:
            ilk, son = yuk_pencere[0], yuk_pencere[-1]
            dt = (son["mono_ns"] - ilk["mono_ns"]) / NS
            mbit = (son["sinif"]["bayt"] - ilk["sinif"]["bayt"]) * 8 / dt / 1e6
            backlog = max(x["yaprak"]["backlog_bayt"] for x in yuk_pencere)
            ovl = son["sinif"]["overlimits"] - ilk["sinif"]["overlimits"]
            r["yuk_penceresi"] = {"mbit": mbit, "backlog_max": backlog, "overlimits": ovl, "sure": dt}
            sonuc(mbit >= 0.88 * HAT_MBIT and (backlog > 0 or ovl > 0), f"{s}_hat_doygun",
                  f"yük penceresinde ({dt:.0f} sn) 1:10 ortalama kullanım {mbit:.2f} Mbit/s (≥ {0.88 * HAT_MBIT:.1f}), bfifo backlog en çok {backlog} bayt, overlimits artışı {ovl}")
        else:
            sonuc(False, f"{s}_hat_doygun", "yük penceresinde tc örneği yok")
    # --- tablolar ------------------------------------------------------------------------------------------------------------------
    o = []
    w = o.append
    w("#### Görev sonucu\n")
    satir = []
    for s in sn:
        r = R[s]
        t0, t1 = r["t0"], r["t1"]
        T = (t1["mono_ns"] - t0["mono_ns"]) / NS if t0 and t1 else None
        Ts = (t1["sim_ns"] - t0["sim_ns"]) / NS if t0 and t1 and t0["sim_ns"] is not None and t1["sim_ns"] is not None else None
        satir.append([ad[s], r["klasor"], "evet" if t1 else "HAYIR", "var" if t0 else "yok", f"{T:.2f}" if T else "-", f"{Ts:.2f}" if Ts else "-", f"{Ts / T:.3f}" if T and Ts else "-",
                      f"{r['t1_eksi_bitis_ms']:.1f} ms" if t1 else "-", r["zaman_asimi"] or (r["hata"][0] if r["hata"] else "-")])
    w(tablo(["Senaryo", "Koşu", "Tamamlandı (t1)", "t0", "T mono (s)", "T sim (s)", "RTF", "t1 − son tarama bitişi", "Tamamlanmadıysa (eksik koşul / hata)"], satir))
    w("\n#### Hat (tc 1:10 ve bfifo yaprağı; yalnız okuma)\n")
    satir = []
    for s in sn:
        r = R[s]
        for ad_, p in (("tüm koşu", r.get("hat_tum")), ("t0–t1", r.get("hat_gorev")), ("yük penceresi", r.get("yuk_penceresi"))):
            if not p:
                continue
            if ad_ == "yük penceresi":
                satir.append([ad[s], ad_, f"{p['sure']:.0f}", f"{p['mbit']:.2f}", "-", "-", "-", p["overlimits"], p["backlog_max"], "-"])
            else:
                satir.append([ad[s], ad_, f"{p['sure']:.0f}", f"{p['mbit']:.2f}", f"{p['mbit_max']:.2f}", p["dusen_sinif"], p["dusen_yaprak"], p["overlimits"], p["backlog_max"], f"{p['backlog_ort']:.0f}"])
    w(tablo(["Senaryo", "Pencere", "Süre (s)", "Ortalama kullanım (Mbit/s)", "En çok 1 sn (Mbit/s)", "Düşen paket (sınıf)", "Düşen paket (bfifo)", "overlimits Δ", "bfifo backlog en çok (bayt)", "backlog ortanca (bayt)"], satir))
    w("\n#### Durum iletileri (2 Hz; ortanca / p95 / en çok)\n")
    satir = []
    for s in sn:
        r = R[s]
        for k in kimlikler:
            satir.append([ad[s], k, r["durum_adet"][k], ozet(r["durum_bosluk"][k], " ms", 0), ozet(r["durum_gecikme"][k], " ms", 1), ozet(r["araclar_arasi_bosluk"].get(k, []), " ms", 0)])
        satir.append([ad[s], "bayat durum uyarısı", r["bayat"], "", "", ""])
    w(tablo(["Senaryo", "Araç", "Yer istasyonunda alınan ileti", "İleti arası boşluk", "Yayım → alım gecikmesi (sim saati)", "Araçlar arası alım boşluğu (aracın aldığı)"], satir))
    w("\n#### Kontrol iletileri (yayım → alım gecikmesi, ms; araç başına ölçümlerin ortanca / p95 / en çok)\n")
    satir = []
    for s in sn:
        r = R[s]
        for ad_, v in r["kontrol"].items():
            satir.append([ad[s], ad_, len(v), ozet(v, " ms", 1)])
        satir.append([ad[s], "alınamayan (kayıp)", len(r["kontrol_eksik"]), ", ".join(r["kontrol_eksik"]) or "yok"])
    w(tablo(["Senaryo", "İleti", "Ölçüm", "ortanca / p95 / en çok"], satir))
    w("\n#### Kare sonuçları (yer istasyonu; L = kullanılabilir − üretim)\n")
    satir = []
    for s in sn:
        r = R[s]
        for k in kimlikler:
            c = r["kare"][k]
            satir.append([ad[s], k, c["aralik"] or "-", f"{c['gelen']}/{c['beklenen']}", c["eksik"] if c["eksik"] is not None else "-", c["yinelenen"], ozet(c["L"], " ms", 1)])
    w(tablo(["Senaryo", "Araç", "Aralık", "Gelen / beklenen", "Eksik", "Yinelenen", "L ortanca / p95 / en çok"], satir))
    w("\n#### DDS eşleşme ve canlılık\n")
    satir = []
    for s in sn:
        r = R[s]
        e, kay, yen, son = r["eslesme_kare_sonuc"]
        satir.append([ad[s], "yer istasyonu: kare sonucu abonesi (eşleşmiş yayımcı sayısı)", " → ".join(map(str, e)) or "-", kay, yen, son])
        e, kay, yen, son = r["eslesme_durum_gcs"]
        satir.append([ad[s], "yer istasyonu: durum abonesi (eşleşmiş yayımcı sayısı)", " → ".join(map(str, e)) or "-", kay, yen, son])
        for k in kimlikler:
            for ad_, (seri, kay, yen, son) in r["eslesme_arac"].get(k, {}).items():
                satir.append([ad[s], f"araç {k}: {ad_} yayımcısı (eşleşmiş abone sayısı)", " → ".join(map(str, seri)), kay, yen, son])
    w(tablo(["Senaryo", "Gözlem noktası", "Sayı dizisi (zaman sırasıyla)", "Eşleşme kaybı (t1'e kadar azalış)", "Yeniden eşleşme (t1'e kadar)", "t1 sonrası azalış (kapanış)"], satir))
    w("\nYöntem: yayımcı/abone eşleşme sayıları `get_subscription_count` / `get_publisher_count` ile 0,05–0,5 sn aralıkla örneklenir; azalış = eşleşme kaybı, ardından artış = yeniden eşleşme. "
      "COMPLETE'ten (t1) sonraki azalışlar kapanıştır (araçlar ve yer istasyonu çıkarken sayılar düşer) ve ayrı sütundadır. Katılımcı canlılık kaybı ayrıca ölçülmedi: kayıp, eşleşme sayılarında görünür.\n")
    if any(R[s]["yuk"] for s in sn):
        w("\n#### Sentetik yük (merkezi modun ağ yükünü taklit eder; B12 sonucu DEĞİLDİR)\n")
        satir = []
        for s in sn:
            r = R[s]
            if not r["yuk"]:
                continue
            for k in kimlikler:
                y = r["yuk"][k]
                oz = y["ozet"]
                if not oz:
                    continue
                satir.append([ad[s], k, f"{oz['uretilen_kare']} / {oz['gonderilen_kare']} / {oz['alinan_kare']}", f"{oz['gonderilen_bayt'] / 1e6:.1f}", ozet(y["bekle"], " ms", 0), ozet(y["uctan_uca"], " ms", 0), y["derinlik_max"],
                              oz["kuyrukta_kalan"], f"{(oz['bosalma_ns'] - oz['durdurma_ns']) / NS:.1f}", oz["bosaldi"]])
        w(tablo(["Senaryo", "Araç", "Üretilen / gönderilen / alınan kare", "Gönderilen (MB)", "Kuyrukta bekleme (ortanca/p95/en çok)", "Kuyruğa giriş → alım (ortanca/p95/en çok)", "Uygulama kuyruğu en çok (kare)", "Sonda kalan", "Boşalma süresi (s)", "Boşaldı"], satir))
    # araç başına bayt (sudo'suz tahmin)
    if boyutlar and os.path.isfile(boyutlar):
        b = json.load(open(boyutlar, encoding="utf-8"))
        w("\n#### Araç başına bayt (sudo'suz tahmin)\n")
        satir = []
        for s in sn:
            r = R[s]
            if not r.get("hat_tum"):
                continue
            toplam = r["hat_tum"]["bayt"]
            yuk_b = sum(r["yuk"][k]["ozet"]["gonderilen_bayt"] for k in kimlikler if r["yuk"] and r["yuk"][k]["ozet"]) if r["yuk"] else 0
            for k in kimlikler:
                kare_n = r["kare"][k]["gelen"]
                durum_n = r["durum_adet"][k]
                tahmin = kare_n * b["FrameResult"] + durum_n * b["VehicleState"] + b["ScanFinished"] + b["Mission"]
                satir.append([ad[s], k, f"{kare_n} × {b['FrameResult']} B + {durum_n} × {b['VehicleState']} B + ...", f"{tahmin / 1e3:.1f}"])
            satir.append([ad[s], "tc 1:10 toplam (3 araç + yer istasyonu)", f"{toplam / 1e6:.2f} MB (tüm örnek penceresi)", f"sentetik yük uygulama baytı (gönderilen) {yuk_b / 1e6:.2f} MB; tc toplamı − yük baytı = {(toplam - yuk_b) / 1e6:.2f} MB (DDS, keşif, kalp atışı, TCP başlık/onayları; bileşenleri bu yöntemle ayrıştırılamaz)"])
        w(tablo(["Senaryo", "Araç / kaynak", "Uygulama ileti sayısı × serileştirilmiş boyut (DDS yükü tahmini)", "Tahmin (kB) / açıklama"], satir))
        w("\nKesin araç başına sayaç sudo gerektirir (araç başına tc sınıfı/süzgeci); burada yalnız uygulama sayaçlarından tahmin verilir. Sürü ağı tek htb sınıfıdır (1:10).\n")
    metin = "".join(o)
    print(metin)
    if cikti:
        with open(cikti, "w", encoding="utf-8") as f:
            f.write(metin)
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
