#!/usr/bin/env python3
"""Uçta mod (kare sonuçlarının yer istasyonuna gönderimi, B11) koşusunun çözümlemesi (test yardımcısı).

Kullanım:  python araclar/uc_mod_analiz.py <koşu_klasörü> --arac N [--hata] [--gecikme-sn S] [--hic] [--tc-once BAYT --tc-sonra BAYT]
  --hata         hata senaryosu: araç 1'de `KAMERA_ENJEKSIYON=dusur=+20` (kare alınamadı) ve `ISCI_ENJEKSIYON=hata=+40` (işlem hatası) beklenir
  --gecikme-sn S araç 1'in sondan üçüncü görev karesinin (n_ilk+379) sonucu yayımda S sn geciktirildi (`KARE_SONUC_ENJEKSIYON=gecik=+379:S`): t1 − son tarama bitişi ≥ S − 3 beklenir
  --hic          bir sonuç hiç gelmez (çok büyük gecikme): COMPLETE yayımlanmamış (t1 kaydı yok), `sonuclar_eksik` kaydı var, eksik tam bir numara
  --tc-once/--tc-sonra  tc htb 1:10 'Sent' sayaçları (bayt): koşu boyunca sürü ağından geçen toplam bayt raporlanır
Her sonuç "SONUC <gecti|kaldi> <ad> | <ayrıntı>" satırıdır; kaldı varsa çıkış 1. Ardından ölçüm satırları (`OLCUM ...`). Yalnız standart kitaplık.
"""
import json
import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NS = 10 ** 9
KALDI = 0
SONUC_DURUMU = {"tespit": "sonuc", "tespit_yok": "tespit_yok", "islem_hatasi": "islem_hatasi", "kare_alinamadi": "kare_alinamadi"}


def sonuc(gecti, ad, ayrinti):
    global KALDI
    if not gecti:
        KALDI += 1
    print(f"SONUC {'gecti' if gecti else 'kaldi'} {ad} | {ayrinti}", flush=True)


def jsonl(yol):
    with open(yol, encoding="utf-8") as f:
        return [json.loads(s) for s in f if s.strip()]


def log_oku(yol):
    s = {}
    with open(yol, encoding="utf-8") as f:
        for satir in f:
            p = satir.rstrip("\n").split(" ")
            if len(p) < 3:
                continue
            i = 2
            kv = {"mono_ns": int(p[1])}
            if p[i].startswith("sim_ns="):
                v = p[i][7:]
                kv["sim_ns"] = None if v == "None" else int(v)
                i += 1
            olay = p[i]
            for t in p[i + 1:]:
                if "=" in t:
                    k, v = t.split("=", 1)
                    kv[k] = v
            s.setdefault(olay, []).append(kv)
    return s


def yuzdelik(x, q):
    x = sorted(x)
    if not x:
        return float("nan")
    k = (len(x) - 1) * q / 100
    a, b = math.floor(k), math.ceil(k)
    return x[a] + (x[b] - x[a]) * (k - a)


def ana(argv):
    a = list(argv)
    if not a:
        print(__doc__, file=sys.stderr)
        return 2
    klasor = a.pop(0)
    n_arac, hata, gecikme, hic, tc0, tc1 = 0, False, None, False, None, None
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k == "--hata":
            hata = True
        elif k == "--gecikme-sn" and a:
            gecikme = float(a.pop(0))
        elif k == "--hic":
            hic = True
        elif k == "--tc-once" and a:
            tc0 = int(a.pop(0))
        elif k == "--tc-sonra" and a:
            tc1 = int(a.pop(0))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))
    from swarm_vehicle import rota
    ham = rota.deney_env_oku()
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()][:n_arac]
    koord = jsonl(os.path.join(klasor, "koordinator_deneme.jsonl"))
    ol = lambda ad: [x for x in koord if x["olay"] == ad]  # noqa: E731
    t0 = (ol("t0") or [None])[0]
    t1 = (ol("t1") or [None])[0]
    tamam = (ol("sonuclar_tamam") or [None])[0]
    eksik = (ol("sonuclar_eksik") or [None])[0]
    bitisler = ol("tarama_bitis")
    eslesme = (ol("eslesme_tamam") or [None])[0]
    if hic:
        sonuc(t0 is not None and len(bitisler) == n_arac, "hic_bitisler_geldi", f"t0 var, {len(bitisler)}/{n_arac} tarama bitişi alındı; sonuçlar eksikken koordinatör bekledi")
        sonuc(t1 is None and tamam is None and eksik is not None and bool(ol("zaman_asimi")), "hic_complete_yok",
              f"COMPLETE yayımlanmadı (t1 kaydı yok), `sonuclar_eksik` kaydı var, açık zaman aşımı kaydı: {[x['beklenen'] for x in ol('zaman_asimi')]}")
        if eksik is not None:
            toplam_eksik = sum(v["eksik"] or 0 for v in eksik["sayilar"].values())
            sonuc(toplam_eksik == 1, "hic_tek_eksik", f"eksik numara sayısı {toplam_eksik} (beklenen 1): " + str({k: v["eksik"] for k, v in eksik["sayilar"].items()}))
        return 1 if KALDI else 0
    sonuc(t0 is not None and t1 is not None and tamam is not None and bool(ol("bitti")), "koordinator_tamam", "koordinatör t0, sonuclar_tamam, t1 ve bitti kayıtlarını yazdı" if t1 else "t0/t1/sonuclar_tamam/bitti eksik")
    if t0 is None or t1 is None or tamam is None:
        return 1
    sonuc(bool(ol("birlestirme_yok")), "birlestirme_yok_kaydi", "koordinatör günlüğünde 'birleştirme yok (M3)' kaydı var")
    sonuc(eslesme is not None and eslesme["yayimci"] >= n_arac and eslesme["mono_ns"] < t0["mono_ns"], "bariyer_eslesmeden_sonra",
          f"kare sonucu konusunda {eslesme['yayimci'] if eslesme else '-'} yayımcıyla eşleşme t0'dan {(t0['mono_ns'] - eslesme['mono_ns']) / 1e6:.0f} ms önce tamamlandı; eşleşme anları t0'a göre (s): "
          + ", ".join(f"{(m - t0['mono_ns']) / 1e9:+.1f}→{n}" for m, n in eslesme["anlar"]) if eslesme else "eşleşme kaydı yok")
    damga = jsonl(os.path.join(klasor, "kayit", "gazebo_damga.jsonl"))
    yer = jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_kare.jsonl"))
    son_sonuc_mono, tum_L = 0, {}
    for k in kimlikler:
        alog = log_oku(os.path.join(klasor, f"arac_{k}.log"))
        bit = alog["tarama_bitis_yayimlandi"][0]
        n_ilk, n_son = int(bit["n_first"]), int(bit["n_last"])
        aralik = list(range(n_ilk, n_son + 1))
        y = [r for r in yer if r["arac_kimligi"] == k]
        sayim = {}
        for r in y:
            sayim[r["n"]] = sayim.get(r["n"], 0) + 1
        eksik_n = [n for n in aralik if sayim.get(n, 0) != 1]
        disi = [n for n in sayim if not n_ilk <= n <= n_son]
        sonuc(not eksik_n and not disi and len(y) == len(aralik), f"yer_tam_{k}",
              f"[{n_ilk}, {n_son}] aralığındaki {len(aralik)} numaranın her biri için yer istasyonunda tam bir `kullanilabilir` kaydı; yinelenen/eksik {eksik_n[:5]}, aralık dışı {sorted(disi)[:5]}")
        sn = {r["n"]: r for r in jsonl(os.path.join(klasor, "kayit", f"kare_sonuc_{k}.jsonl"))}
        farkli = [n for n in aralik if SONUC_DURUMU[sn[n]["durum"]] != next((r["sonuc_durumu"] for r in y if r["n"] == n), None)]
        say = {}
        for r in y:
            say[r["sonuc_durumu"]] = say.get(r["sonuc_durumu"], 0) + 1
        sonuc(not farkli and len(sn) == len(aralik), f"arac_yer_birebir_{k}", f"araçtaki kare_sonuc kaydı ile yer istasyonu kaydı numara + durum düzeyinde birebir ({len(aralik)} numara; farklı: {farkli[:5]}); yer istasyonu durumları {say}")
        gon = [r for r in jsonl(os.path.join(klasor, "kayit", f"arac_sureci_{k}.jsonl")) if r["olay"] == "gonderim"]
        sonuc(sorted(r["n"] for r in gon) == aralik, f"gonderim_kaydi_{k}", f"araç gönderim kaydı: {len(gon)} (beklenen {len(aralik)}), her numara bir kez")
        ozet = alog["sonuc_yayin_ozet"][0]
        sonuc(int(ozet["verilen"]) == len(aralik) and int(ozet["yayimlanan"]) == len(aralik) and int(ozet["hata"]) == 0 and ozet["onaylandi"] == "True" and "sonuc_yayin_uyari" not in alog,
              f"yayim_ozeti_{k}", f"verilen {ozet['verilen']}, yayımlanan {ozet['yayimlanan']}, yayım hatası {ozet['hata']}, tüm iletiler onaylandı={ozet['onaylandi']}, yayım kuyruğu en çok {ozet['kuyruk_maks']}")
        son_sonuc_mono = max(son_sonuc_mono, max(r["mono_ns"] for r in y))
        # L: yalnız sonuc / tespit_yok (işlem hatası ve kare alınamadı L'ye girmez)
        uretim = {r["n"]: r["mono_ns"] for r in damga if r["arac_kimligi"] == k and r["olay"] == "uretim" and isinstance(r["n"], int)}
        L = [(r["mono_ns"] - uretim[r["n"]]) / 1e6 for r in y if r["sonuc_durumu"] in ("sonuc", "tespit_yok") and r["n"] in uretim]
        tum_L[k] = L
        sonuc(len(L) == sum(v for d, v in say.items() if d in ("sonuc", "tespit_yok")) and L and min(L) > 0, f"L_{k}",
              f"L = kullanilabilir − uretim (Gazebo üretim ↔ yer istasyonu, araç+n): {len(L)} kare, ortanca {yuzdelik(L, 50):.1f} ms, p95 {yuzdelik(L, 95):.1f} ms, en çok {max(L):.1f} ms, en az {min(L):.1f} ms")
        if hata and k == kimlikler[0]:
            beklenen = {n_ilk + 20: "kare_alinamadi", n_ilk + 40: "islem_hatasi"}
            gercek = {n: r["sonuc_durumu"] for n, r in ((r["n"], r) for r in y) if r["sonuc_durumu"] in ("kare_alinamadi", "islem_hatasi")}
            sonuc(gercek == beklenen, "hata_durumlari", f"yer istasyonunda yalnız {beklenen} (STATUS_FRAME_NOT_RECEIVED / STATUS_PROCESSING_ERROR) beklenir; bulunan {gercek}; ikisi de 'tespit_yok' sayılmadı")
    # --- sıra ve süreler ---------------------------------------------------------------------------------------------------------------
    for k in kimlikler:
        b = next(x for x in bitisler if x["arac"] == k)
        sonuc(t0["mono_ns"] < b["mono_ns"] < tamam["mono_ns"] <= t1["t1_mono_ns"], f"sira_{k}", f"t0 → araç {k} tarama bitişi ({(b['mono_ns'] - t0['mono_ns']) / 1e9:.1f} s) → sonuçlar tamam → t1 ({(t1['t1_mono_ns'] - t0['mono_ns']) / 1e9:.1f} s)")
    sonuc(son_sonuc_mono <= t1["t1_mono_ns"] and tamam["gecersiz"] == 0 and tamam["tekrar"] == 0 and tamam["bilinmeyen_arac"] == 0, "complete_son_sonuctan_sonra",
          f"COMPLETE son sonuçtan {(t1['t1_mono_ns'] - son_sonuc_mono) / 1e6:.1f} ms sonra; geçersiz {tamam['gecersiz']}, tekrar {tamam['tekrar']}, bilinmeyen araç {tamam['bilinmeyen_arac']}; son sonuç, son tarama bitişinden {(son_sonuc_mono - t1['son_tarama_bitis_mono_ns']) / 1e6:.0f} ms sonra")
    for k, v in tamam["sayilar"].items():
        sonuc(v["aralik_disi"] == 0 and v["tekrar"] == 0 and v["eksik"] == 0, f"defter_{k}", f"araç {k}: beklenen {v['beklenen']}, gelen {v['gelen']}, eksik {v['eksik']}, tekrar {v['tekrar']}, aralık dışı {v['aralik_disi']}, durumlar {v['durumlar']}")
    fark_bitis = t1["t1_eksi_son_bitis_s"]
    print(f"OLCUM t1 - son_tarama_bitisi = {fark_bitis * 1000:.1f} ms; t1 - son_sonuc = {t1['t1_eksi_son_sonuc_s'] * 1000:.1f} ms")
    if gecikme is not None:
        sonuc(fark_bitis >= gecikme - 3.0, "gecikme_beklendi", f"sondan üçüncü karenin sonucunun yayımı {gecikme:g} sn geciktirildi (normalde bitişten ~1,5 sn önce gelir); COMPLETE son tarama bitişinden {fark_bitis:.1f} s sonra (≥ {gecikme - 3.0:g}): koordinatör bekledi")
    for k in kimlikler:
        alog = log_oku(os.path.join(klasor, f"arac_{k}.log"))
        bit = alog["tarama_bitis_yayimlandi"][0]
        s_sim = (int(bit["t_b_ns"]) - int(bit["t_s_ns"])) / NS
        s_mono = (alog["son_nokta_geri_cagrisi"][0]["mono_ns"] - alog["tarama_baslat_alindi"][0]["mono_ns"]) / NS
        print(f"OLCUM araç {k}: tarama sim {s_sim:.1f} s, monotonik {s_mono:.1f} s, RTF {s_sim / s_mono:.3f}; kare {int(bit['n_first'])}..{int(bit['n_last'])}")
    if tc0 is not None and tc1 is not None:
        print(f"OLCUM tc htb 1:10 (sürü ağı, bütün katılımcılar: {n_arac} araç + yer istasyonu): {tc1 - tc0} bayt ({(tc1 - tc0) / 1e6:.2f} MB) koşu boyunca")
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
