#!/usr/bin/env python3
"""Araç süreci koşusunun çözümlemesi (test yardımcısı): koordinatör kaydı, araç günlükleri, bağdaştırıcı günlükleri ve durum kayıt dosyaları.

Kullanım:  python araclar/analiz/arac_sureci_analiz.py <koşu_klasörü> --arac N [--erken-scan-start] [--erken-complete] [--yanlis-complete]
Her sonuç "SONUC <gecti|kaldi> <ad> | <ayrıntı>" satırıdır; kaldı varsa çıkış 1. Yalnız standart kitaplık.
"""
import json
import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KALDI = 0
NS = 10 ** 9
DIZI = ["HAZIR", "BARIYER_BEKLE", "TARAMA", "WAIT", "TAMAMLANDI"]


def sonuc(gecti, ad, ayrinti):
    global KALDI
    if not gecti:
        KALDI += 1
    print(f"SONUC {'gecti' if gecti else 'kaldi'} {ad} | {ayrinti}", flush=True)


def olcum(ad, ayrinti):
    """Ölçüm/bilgi satırı: geçti/kaldı sayılmaz (test betikleri bilgi olarak yazar)."""
    print(f"OLCUM {ad} | {ayrinti}", flush=True)


def jsonl(yol):
    with open(yol, encoding="utf-8") as f:
        return [json.loads(s) for s in f if s.strip()]


def env_oku():
    sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))
    from swarm_vehicle.ucus import rota
    return rota.deney_env_oku()


def kare_araligi(ts, tb, hz):
    """Bağımsız hesap (aracın kendi işlevini ÇAĞIRMAZ: analiz sınadığı kodu kullanmasın): n_ilk = ceil(hz·t_s), n_son = floor(hz·t_b), tam sayı aritmetiğiyle; hz = CAM_RATE_HZ."""
    hz = int(float(hz))
    return -((-hz * ts) // NS), (hz * tb) // NS


def log_oku(yol):
    """Araç/bağdaştırıcı günlüğü: {olay: [ {anahtar: değer}... ]}; satır: <iso> <mono_ns> [sim_ns=X] <olay> k=v ..."""
    sonuc_ = {}
    with open(yol, encoding="utf-8") as f:
        for satir in f:
            p = satir.rstrip("\n").split(" ")
            if len(p) < 3:
                continue
            mono = int(p[1])
            i = 2
            kv = {"mono_ns": mono}
            if p[i].startswith("sim_ns="):
                v = p[i][7:]
                kv["sim_ns"] = None if v == "None" else int(v)
                i += 1
            olay = p[i]
            kv["ham"] = " ".join(p[i + 1:])
            for t in p[i + 1:]:
                if "=" in t:
                    k, v = t.split("=", 1)
                    kv[k] = v
            sonuc_.setdefault(olay, []).append(kv)
    return sonuc_


def yatay(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def ana(argv):
    a = list(argv)
    if not a:
        print(__doc__, file=sys.stderr)
        return 2
    klasor = a.pop(0)
    n_arac, bayrak = 0, set()
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k in ("--erken-scan-start", "--erken-complete", "--yanlis-complete"):
            bayrak.add(k)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    ham = env_oku()
    hz_kare = float(ham["CAM_RATE_HZ"])
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()][:n_arac]
    with open(os.path.join(KOK, "config", "bolge_rota.json"), encoding="utf-8") as f:
        rotalar = {r["arac_kimligi"]: r["noktalar"] for r in json.load(f)["rotalar"]}
    kayit = jsonl(os.path.join(klasor, "koordinator_deneme.jsonl"))
    olaylar = lambda ad: [x for x in kayit if x["olay"] == ad]  # noqa: E731
    t0 = (olaylar("t0") or [None])[0]
    t1 = (olaylar("t1") or [None])[0]
    sonuc(t0 is not None and t1 is not None and bool(olaylar("bitti")), "koordinator_tamam", "koordinatör t0, t1 ve bitti kayıtlarını yazdı" if t0 and t1 else "t0/t1/bitti eksik")
    if t0 is None or t1 is None:
        return 1
    durumlar = {k: [x for x in olaylar("durum") if x["arac"] == k] for k in kimlikler}
    bitisler = {x["arac"]: x for x in olaylar("tarama_bitis")}
    pozlar = olaylar("poz")
    min_ayrim_hazirlik, min_ayrim_tum = 1e9, 1e9
    for x in pozlar:
        liste = [v for v in x["pozlar"].values() if v]
        for i in range(len(liste)):
            for j in range(i + 1, len(liste)):
                d = math.dist(liste[i], liste[j])
                min_ayrim_tum = min(min_ayrim_tum, d)
                if x["mono_ns"] < t0["t0_mono_ns"]:
                    min_ayrim_hazirlik = min(min_ayrim_hazirlik, d)
    if len(kimlikler) > 1:
        sonuc(min_ayrim_hazirlik > 1.0, "hazirlik_carpisma_yok", f"hazırlık evresinde (t0 öncesi) araçlar arası en küçük 3B uzaklık {min_ayrim_hazirlik:.1f} m (> 1 m); tüm koşuda {min_ayrim_tum:.1f} m ({len(pozlar)} poz örneği)")
    en_gec_bariyer = 0
    for k in kimlikler:
        d = durumlar[k]
        dizi = []
        for x in d:
            if not dizi or dizi[-1] != x["durum"]:
                dizi.append(x["durum"])
        sonuc(dizi == DIZI, f"dizi_{k}", f"ortak durum konusundan kaydedilen dizi (bağımsız dinleyici): {' → '.join(dizi)}")
        bariyer = [x for x in d if x["durum"] == "BARIYER_BEKLE"]
        ilk_bariyer = bariyer[0]["mono_ns"] if bariyer else None
        en_gec_bariyer = max(en_gec_bariyer, ilk_bariyer or 0)
        sonuc(ilk_bariyer is not None and ilk_bariyer < t0["t0_mono_ns"], f"bariyer_once_{k}",
              f"koordinatör araç {k}'nın BARIYER_BEKLE iletisini aldıktan {(t0['t0_mono_ns'] - ilk_bariyer) / 1e6:.2f} ms sonra ScanStart yayımladı (sıra: BARIYER_BEKLE → ScanStart)" if ilk_bariyer else "BARIYER_BEKLE kaydı yok")
        # t0 anında Gazebo pozu
        rota = rotalar[k]
        p0 = t0["pozlar"].get(str(k))
        sonuc(p0 is not None and yatay(p0, rota[0]) <= 5.0 and abs(p0[2] - float(ham["ROTA_IRTIFA_M"])) <= 2.0, f"t0_poz_{k}",
              f"t0 anında Gazebo pozu: ilk noktaya yatay {yatay(p0, rota[0]):.2f} m (≤ 5), yükseklik {p0[2]:.2f} m (30 ± 2): kalkış ve ilk noktaya varış ScanStart'tan önce" if p0 else "poz yok")
        tarama = [x for x in d if x["durum"] == "TARAMA"]
        gecik = (tarama[0]["sim_damga_ns"] - t0["sim_ns"]) / NS if tarama else None
        alog_ = log_oku(os.path.join(klasor, f"arac_{k}.log"))
        iletim = (int(alog_["tarama_baslat_alindi"][0]["t_s_ns"]) - t0["sim_ns"]) / 1e6
        sonuc(tarama and tarama[0]["mono_ns"] > t0["t0_mono_ns"], f"tarama_gecis_{k}", f"TARAMA ilk yayımı t0'dan sonra; t0→t_s (aracın ScanStart'ı aldığı simülasyon anı) {iletim:.0f} sim ms; t0→ilk TARAMA yayımı (2 Hz yayım çözünürlüğü) {gecik:.2f} sim sn" if tarama else "TARAMA kaydı yok")
        # araç günlüğü
        alog = log_oku(os.path.join(klasor, f"arac_{k}.log"))
        ts = int(alog["tarama_baslat_alindi"][0]["t_s_ns"])
        tb = int(alog["tarama_bitis_yayimlandi"][0]["t_b_ns"])
        n_ilk, n_son = kare_araligi(ts, tb, ham["CAM_RATE_HZ"])
        b = bitisler.get(k)
        sonuc(b is not None and b["n_first"] == n_ilk and b["n_last"] == n_son and b["n_first"] <= b["n_last"], f"kare_araligi_{k}",
              f"ScanFinished n_first={b['n_first']}, n_last={b['n_last']}; araç günlüğü t_s={ts / NS:.3f} s, t_b={tb / NS:.3f} s → ceil(hz·t_s)={n_ilk}, floor(hz·t_b)={n_son}" if b else "ScanFinished yok")
        if b:
            pb = b["pozlar"].get(str(k))
            sonuc(pb is not None and yatay(pb, rota[-1]) <= 5.0 and abs(pb[2] - float(ham["ROTA_IRTIFA_M"])) <= 2.0, f"bitis_poz_{k}",
                  f"ScanFinished alındığında Gazebo pozu: son noktaya yatay {yatay(pb, rota[-1]):.2f} m (≤ 5), yükseklik {pb[2]:.2f} m" if pb else "poz yok")
        # yayım hızı (sim zamanına göre): kendi durum kayıtları
        if len(d) > 2:
            sim_aralik = (d[-1]["sim_damga_ns"] - d[0]["sim_damga_ns"]) / NS
            duvar_aralik = (d[-1]["mono_ns"] - d[0]["mono_ns"]) / NS
            hz_sim, hz_duvar = (len(d) - 1) / sim_aralik, (len(d) - 1) / duvar_aralik
            hedef = float(ham["DURUM_YAYIN_HZ"])
            sonuc(abs(hz_sim - hedef) <= 0.1 * hedef, f"yayim_hizi_{k}", f"durum yayım hızı {hz_sim:.3f} Hz (sim zamanı, {len(d)} ileti, {sim_aralik:.0f} sim sn); duvar saatine göre {hz_duvar:.3f} Hz (hedef {hedef:g} ± %10)")
        # süreler
        hz_ = alog["hazirlik_bitti"][0]
        olcum(f"sureler_{k}", f"hazırlık {hz_['sure_s']} sn (kalkış {hz_['kalkis_sure_s']}, gidiş {hz_['gidis_sure_s']}; gerçek, T'ye girmez); tarama süresi {(tb - ts) / NS:.1f} sim sn (t_s→t_b)"
              + (f"; t0→ScanFinished {(b['sim_ns'] - t0['sim_ns']) / NS:.1f} sim sn" if b else "; ScanFinished yok"))
        # bağdaştırıcı günlüğü: başlatma t0'dan sonra
        adlog = log_oku(os.path.join(klasor, f"px4_adapter_{k}.log"))
        baslat = [x for x in adlog.get("komut", []) if x.get("ad") == "mission.start"]
        sonuc(len(baslat) == 1 and baslat[0]["mono_ns"] > t0["t0_mono_ns"], f"gorev_baslatma_t0_sonrasi_{k}",
              f"mission.start komutu {len(baslat)} kez, t0'dan {(baslat[0]['mono_ns'] - t0['t0_mono_ns']) / 1e9:.2f} sn sonra (kalkış/arm komutları t0'dan önce)" if baslat else "mission.start yok")
        onceki = [x["ad"] for x in adlog.get("komut", []) if x["mono_ns"] < t0["t0_mono_ns"]]
        sonuc("action.arm" in onceki and "action.takeoff" in onceki and "mission.start" not in onceki, f"komutlar_t0_oncesi_{k}", f"t0 öncesi komutlar: {onceki}")
        if "--erken-scan-start" in bayrak:
            yok = [x for x in alog.get("durum_makinesi", []) if "yok_sayildi tarama_baslat" in x["ham"] and "'ERKEN'" in x["ham"]]
            ilk_baslat = baslat[0]["mono_ns"] if baslat else 0
            sonuc(bool(yok) and yok[0]["mono_ns"] < t0["t0_mono_ns"] and ilk_baslat > t0["t0_mono_ns"], f"erken_scan_start_{k}",
                  f"BARIYER_BEKLE öncesi ScanStart ('ERKEN') yok sayıldı ({yok[0]['ham'][:90] if yok else 'KAYIT YOK'}); görev yalnız gerçek t0'dan sonra başladı; t0 öncesi mission.start yok")
        if "--erken-complete" in bayrak:
            yok = [x for x in alog.get("durum_makinesi", []) if "yok_sayildi complete" in x["ham"]]
            sonuc(bool(yok), f"erken_complete_{k}", f"TARAMA sırasında gelen COMPLETE yok sayıldı: {yok[0]['ham'][:90] if yok else 'KAYIT YOK'}")
    sonuc(len(bitisler) == len(kimlikler), "tum_bitisler", f"{len(bitisler)}/{len(kimlikler)} ScanFinished alındı")
    if "--yanlis-complete" in bayrak:
        y = olaylar("yanlis_complete_yayimlandi")[0]
        arada = [x for x in olaylar("durum") if y["mono_ns"] <= x["mono_ns"] <= t1["t1_mono_ns"]]
        yalniz_wait = {x["durum"] for x in arada if x["arac"] in kimlikler} == {"WAIT"}
        sure = (t1["t1_mono_ns"] - y["mono_ns"]) / 1e9
        sonuc(yalniz_wait and sure >= 5.0 and len(arada) >= len(kimlikler) * 5, "yanlis_complete_wait", f"yanlış kimlikli COMPLETE'ten doğrusuna {sure:.1f} sn boyunca ({len(arada)} durum iletisi) bütün araçlar WAIT'te kaldı")
        sonra = [x for x in olaylar("durum") if x["mono_ns"] > t1["t1_mono_ns"]]
        sonuc(all(any(x["arac"] == k and x["durum"] == "TAMAMLANDI" for x in sonra) for k in kimlikler), "dogru_complete_tamamlandi", "doğru COMPLETE'ten sonra bütün araçlar TAMAMLANDI yayımladı")
    olcum("genel_sureler", f"t0→COMPLETE (t1) {(t1['sim_ns'] - t0['sim_ns']) / NS:.1f} sim sn ({(t1['t1_mono_ns'] - t0['t0_mono_ns']) / 1e9:.1f} gerçek sn)")
    # diğer araçların durum kayıtları
    if len(kimlikler) > 1:
        for yazar in kimlikler:
            kayit_yol = os.path.join(klasor, "kayit", f"arac_durum_{yazar}.jsonl")
            satirlar = jsonl(kayit_yol)
            digerleri = [k for k in kimlikler if k != yazar]
            ozet = []
            tamam = True
            for k in digerleri:
                r = [x for x in satirlar if x["kaynak_arac_kimligi"] == k]
                if len(r) < 2:
                    tamam = False
                    ozet.append(f"araç {k}: {len(r)} kayıt")
                    continue
                aralik = (r[-1]["sim_damga_ns"] - r[0]["sim_damga_ns"]) / NS
                beklenen = hz_kare * aralik + 1
                ozet.append(f"araç {k}: {len(r)} kayıt ({hz_kare:g} Hz × {aralik:.0f} sim sn + 1 = {beklenen:.0f} beklenir; eksik oranı %{max(0, 1 - len(r) / beklenen) * 100:.1f})")
            kendi = [x for x in satirlar if x["kaynak_arac_kimligi"] == yazar]
            sonuc(tamam and not kendi and {x["kaynak_arac_kimligi"] for x in satirlar} == set(digerleri), f"diger_arac_kayitlari_{yazar}", f"araç {yazar} kayıt dosyası yalnız diğer araçları içeriyor: " + "; ".join(ozet))
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
