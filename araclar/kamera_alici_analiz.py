#!/usr/bin/env python3
"""Kamera alıcısı koşusunun çözümlemesi (test yardımcısı): damga kaydı, alıcı kayıtları, araç günlükleri, koordinatör ve görüş denemesi.

Kullanım:  python araclar/kamera_alici_analiz.py <koşu_klasörü> --arac N [--enjeksiyon] [--gorus]
  --enjeksiyon  hata enjeksiyonlu koşu (dusur=+20,+60,+61,son;gecik=+100): beklenen kayıp/geç gelme kümeleri denetlenir; yoksa kayıpsız koşu beklenir
  --gorus       gorus_deneme.jsonl (aşağı bakış ve eksen yönelimi) denetlenir
Her sonuç "SONUC <gecti|kaldi> <ad> | <ayrıntı>" satırıdır; kaldı varsa çıkış 1. Yalnız standart kitaplık.
"""
import json
import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KALDI = 0
NS = 10 ** 9


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
                i += 1
            olay = p[i]
            kv["ham"] = " ".join(p[i + 1:])
            for t in p[i + 1:]:
                if "=" in t:
                    k, v = t.split("=", 1)
                    kv[k] = v
            s.setdefault(olay, []).append(kv)
    return s


def yuzde(liste, p):
    liste = sorted(liste)
    return liste[min(len(liste) - 1, int(math.ceil(p / 100 * len(liste))) - 1)] if liste else None


def ana(argv):
    a = list(argv)
    if not a:
        print(__doc__, file=sys.stderr)
        return 2
    klasor = a.pop(0)
    n_arac, enj, gorus = 0, False, False
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k == "--enjeksiyon":
            enj = True
        elif k == "--gorus":
            gorus = True
        else:
            print(__doc__, file=sys.stderr)
            return 2
    sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))
    from swarm_vehicle import rota
    ham = rota.deney_env_oku()
    hz = int(float(ham["CAM_RATE_HZ"]))
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()][:n_arac]
    damga_hepsi = jsonl(os.path.join(klasor, "kayit", "gazebo_damga.jsonl"))
    koord = jsonl(os.path.join(klasor, "koordinator_deneme.jsonl"))
    for k in kimlikler:
        alog = log_oku(os.path.join(klasor, f"arac_{k}.log"))
        al = jsonl(os.path.join(klasor, "kayit", f"kamera_alici_{k}.jsonl"))
        dm = [r for r in damga_hepsi if r["arac_kimligi"] == k]
        ozet = alog["kamera_alici_ozet"][0]
        ts, tb = int(alog["tarama_baslat_alindi"][0]["t_s_ns"]), int(alog["tarama_bitis_yayimlandi"][0]["t_b_ns"])
        n_ilk, n_son = -((-hz * ts) // NS), (hz * tb) // NS
        bitis = alog["tarama_bitis_yayimlandi"][0]
        # --- görev aralığı: her numara tam bir sınıfta -------------------------------------------------------------------------------------
        gorev = [r["n"] for r in al if r["olay"] == "kuyruga_giris"]
        kayip = [r["n"] for r in al if r["olay"] == "kullanilabilir" and r.get("sonuc_durumu") == "kare_alinamadi"]
        gec = [r["n"] for r in al if r["olay"] == "gec_geldi"]
        aralik = set(range(n_ilk, n_son + 1))
        sinif_hatasi = [n for n in aralik if (n in gorev) + (n in kayip) != 1]
        sonuc(int(bitis["n_first"]) == n_ilk and int(bitis["n_last"]) == n_son and ozet["n_ilk"] == str(n_ilk) and ozet["n_son"] == str(n_son), f"aralik_{k}",
              f"ScanFinished n_first={bitis['n_first']}, n_last={bitis['n_last']} = alıcı n_ilk={ozet['n_ilk']}, n_son={ozet['n_son']} = ceil/floor(t_s={ts / NS:.3f} s, t_b={tb / NS:.3f} s) → {n_ilk}..{n_son} ({len(aralik)} numara)")
        sonuc(not sinif_hatasi and set(gorev) | set(kayip) == aralik and len(gorev) == len(set(gorev)) and len(kayip) == len(set(kayip)) and not (set(gorev) & set(kayip)),
              f"tam_bir_sinif_{k}", f"[{n_ilk}, {n_son}] aralığındaki {len(aralik)} numaranın her biri tam bir sınıfta: görev karesi {len(gorev)}, kare alınamadı {len(kayip)}; hem görev hem kayıp: {sorted(set(gorev) & set(kayip))}; sınıfsız: {sinif_hatasi[:5]}")
        kapanis = [r for r in al if r["olay"] == "yok_sayildi" and r.get("neden") == "kapanis_sonrasi"]
        sonuc(bool(kapanis) and kapanis[0]["n"] == n_son + 1 and (n_son + 1) not in gorev, f"kapanis_karesi_{k}",
              f"n_son'dan büyük ilk kare ({kapanis[0]['n'] if kapanis else '-'}) görev girdisi sayılmadı (yok_sayildi/kapanis_sonrasi); kuyruga_giris yok")
        sonuc(int(ozet["kuyruktan_tuketilen"]) == len(gorev) and int(ozet["boyut_hatasi"]) == 0, f"kuyruk_{k}",
              f"iç kuyruğa verilen {len(gorev)} görev karesi, tüketicinin saydığı {ozet['kuyruktan_tuketilen']} (son {ozet['son_tuketilen']}); kare boyutu hatası {ozet['boyut_hatasi']}")
        ilk = alog["kamera_ilk_kare"][0]
        sonuc(ilk["genislik"] == ham["CAM_WIDTH"] and ilk["yukseklik"] == ham["CAM_HEIGHT"] and int(ilk["bayt"]) == int(ham["CAM_WIDTH"]) * int(ham["CAM_HEIGHT"]) * 3, f"kare_biçimi_{k}",
              f"{ilk['genislik']}×{ilk['yukseklik']}, {ilk['bayt']} bayt (= 640·480·3, sıkıştırmasız RGB8), piksel_bicimi={ilk['piksel_bicimi']}")
        # --- kayıp / geç gelme -----------------------------------------------------------------------------------------------------------
        if not enj:
            sonuc(not kayip and not gec and int(ozet["gorev"]) == len(aralik), f"kayipsiz_{k}", f"kare_alinamadi {len(kayip)}, gec_geldi {len(gec)}, görev karesi {ozet['gorev']}/{len(aralik)}")
        else:
            beklenen_dusen = {n_ilk + 20, n_ilk + 60, n_ilk + 61, n_son}
            beklenen_gecik = {n_ilk + 100}
            sonuc(set(kayip) == beklenen_dusen | beklenen_gecik and set(gec) == beklenen_gecik and not (set(gorev) & set(kayip)), f"enjeksiyon_kumeler_{k}",
                  f"kare_alinamadi={sorted(kayip)} (düşürülen {sorted(beklenen_dusen)} + geciken {sorted(beklenen_gecik)}), gec_geldi={sorted(gec)}; görev karesi {len(gorev)} = {len(aralik)} − {len(kayip)}")
            sonuc(len(gorev) == len(aralik) - len(kayip), f"enjeksiyon_gorev_sayisi_{k}", f"görev karesi {len(gorev)}")
            # zaman sırası: her kayıp, kendisinden sonraki ilk kareyle AYNI anda üretildi ve dosyada o karenin kaydından ÖNCE yazıldı
            sira_hatasi = []
            for m in kayip:
                kay = next(i for i, r in enumerate(al) if r["olay"] == "kullanilabilir" and r["n"] == m and r.get("sonuc_durumu") == "kare_alinamadi")
                sonraki = next((i for i, r in enumerate(al) if i > kay and r["olay"] in ("kuyruga_giris", "yok_sayildi") and isinstance(r["n"], int) and r["n"] > m), None)
                if sonraki is None or al[sonraki]["mono_ns"] != al[kay]["mono_ns"]:
                    sira_hatasi.append(m)
                # kayıp kaydı, kendisinden önceki hiçbir kareden önce yazılmamış olmalı
            sonuc(not sira_hatasi, f"kayip_zaman_sirasi_{k}", f"{len(kayip)} kayıp kaydının her biri, kendisinden sonra gelen ilk kareyle aynı alım anında (kayıt kesinleşti) ve onun kaydından önce yazıldı; ihlal: {sira_hatasi}")
            son_kayit = next(r for r in al if r["olay"] == "kullanilabilir" and r["n"] == n_son)
            sonuc(son_kayit["mono_ns"] == kapanis[0]["mono_ns"], f"sondaki_kayip_{k}", f"n_son={n_son} kaydı, n_son+1={n_son + 1} (kapanış) karesinin alım anında yazıldı (sondaki kayıp ilk büyük kareyle kapandı)")
            for m in gec:
                gk = next(r for r in al if r["olay"] == "gec_geldi" and r["n"] == m)
                kk = next(r for r in al if r["olay"] == "kullanilabilir" and r["n"] == m)
                sonuc(gk["mono_ns"] > kk["mono_ns"] and m not in gorev, f"gec_geldi_{k}", f"n={m}: kare alınamadı kaydından {(gk['mono_ns'] - kk['mono_ns']) / 1e6:.0f} ms sonra teslim edildi; iç kuyruğa VERİLMEDİ (kuyruga_giris yok); yalnız yerel kayıt")
        # --- damga birleşmesi (B7) ---------------------------------------------------------------------------------------------------------
        dmn = {(r["sim_damga_ns"]): r for r in dm}
        alici_goruldu = {r["sim_damga_ns"]: r for r in al if r["olay"] in ("kuyruga_giris", "yok_sayildi", "gec_geldi")}
        esles = sorted(set(dmn) & set(alici_goruldu))
        yalniz_damga = sorted(set(dmn) - set(alici_goruldu))
        yalniz_alici = sorted(set(alici_goruldu) - set(dmn))
        ilk_alici = min(alici_goruldu) if alici_goruldu else None
        onceki = [d for d in yalniz_damga if ilk_alici is not None and d < ilk_alici]
        son_alici = max(alici_goruldu) if alici_goruldu else None
        sonrasi = [d for d in yalniz_damga if son_alici is not None and d > son_alici]
        gorev_icinde = [dmn[d]["n"] for d in yalniz_damga if isinstance(dmn[d]["n"], int) and n_ilk <= dmn[d]["n"] <= n_son]
        beklenen_yalniz = {n_ilk + 20, n_ilk + 60, n_ilk + 61, n_son} if enj else set()      # enjeksiyonla alıcıya hiç verilmeyen kareler yalnız damgada kalır (beklenen)
        sonuc(not yalniz_alici and set(gorev_icinde) == beklenen_yalniz, f"damga_birlesme_{k}",
              f"damga {len(dm)} kare = eşleşen {len(esles)} + yalnız damgada {len(yalniz_damga)} (alıcı abonelik öncesi {len(onceki)}, alıcı kapandıktan sonra {len(sonrasi)}, diğer {len(yalniz_damga) - len(onceki) - len(sonrasi)}) ; yalnız alıcıda {len(yalniz_alici)}; görev aralığında yalnız damgada {len(gorev_icinde)}{' (enjeksiyonla düşürülenler: ' + str(sorted(gorev_icinde)) + ')' if enj else ''}; "
              f"kayıp kaydı yazılan {len(kayip)} numara damgada {'var' if all(any(r['n'] == m for r in dm) for m in kayip) else 'YOK'}")
        gecikme = [(alici_goruldu[d]["mono_ns"] - dmn[d]["mono_ns"]) / 1e6 for d in esles]
        if gecikme and not enj:
            sonuc(min(gecikme) > -50, f"uretim_alim_gecikmesi_{k}", f"üretim → alım gecikmesi (ms, {len(gecikme)} kare): ortanca {yuzde(gecikme, 50):.2f}, p99 {yuzde(gecikme, 99):.2f}, en çok {max(gecikme):.2f}, en az {min(gecikme):.2f}")
        ilk_d = dm[0]
        sonuc(True, f"ilk_kare_{k}", f"oturumun (damga bileşeninin gördüğü) ilk karesi: n={ilk_d['n']}, damga {ilk_d['sim_damga_ns'] / NS:.3f} sim sn ({'ızgarada' if isinstance(ilk_d['n'], int) else 'ızgara dışı'}); ızgara dışı kare sayısı {sum(1 for r in dm if not isinstance(r['n'], int))}")
        # --- kare üretim hızı (sim zamanı ve duvar saati) ------------------------------------------------------------------------------------
        iz = [r for r in dm if isinstance(r["n"], int)]
        if len(iz) > 2:
            sim = (iz[-1]["sim_damga_ns"] - iz[0]["sim_damga_ns"]) / NS
            duvar = (iz[-1]["mono_ns"] - iz[0]["mono_ns"]) / NS
            farklar = [(b["sim_damga_ns"] - a_["sim_damga_ns"]) / NS for a_, b in zip(iz, iz[1:])]
            sonuc(abs((len(iz) - 1) / sim - hz) < 0.01 and set(round(f, 6) for f in farklar) <= {0.5, 1.0}, f"uretim_hizi_{k}",
                  f"üretim hızı {(len(iz) - 1) / sim:.3f} kare/sim sn ({len(iz)} ızgara karesi, {sim:.0f} sim sn); duvar saatine göre {(len(iz) - 1) / duvar:.3f} kare/s; damga farkları {sorted(set(round(f, 6) for f in farklar))}")
        # --- last_frame_number ---------------------------------------------------------------------------------------------------------------
        durum = [r for r in koord if r["olay"] == "durum" and r["arac"] == k]
        degerler = [r["son_kare"] for r in durum]
        tarama = [r["son_kare"] for r in durum if r["durum"] in ("TARAMA", "WAIT", "TAMAMLANDI")]
        sonuc(all(b >= a_ for a_, b in zip(degerler, degerler[1:])) and (tarama and max(tarama) <= n_son) and (min(degerler) == -1) and any(x >= n_ilk for x in tarama), f"last_frame_number_{k}",
              f"VehicleState.last_frame_number: tarama öncesi -1, sonra {n_ilk}…{max(tarama) if tarama else '-'} aralığında artıyor (azalmıyor), n_son={n_son}'i aşmıyor; son değer {degerler[-1]}")
    if gorus:
        g = jsonl(os.path.join(klasor, "gorus_deneme.jsonl"))
        o = next(r for r in g if r.get("ozet"))
        w, h = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
        pay = 40          # işaretin (3 m) yarı boyu ≈ 25 px; kenara 40 px'ten yakın öngörülen merkezli kareler kısmen kadraj dışıdır, ağırlık merkezi sapar: ölçüte girmez
        tespit = [r for r in g if "olculen_uv" in r]
        tam = [r for r in tespit if pay <= r["oncul_uv"][0] <= w - pay and pay <= r["oncul_uv"][1] <= h - pay]
        hatalar = [r["hata_px"] for r in tam]
        sonuc(len(tam) >= 5 and max(hatalar) <= 15.0, "gorus_eksen",
              f"yer işareti {len(tespit)} karede görüldü, {len(tam)}'inde tamamen kadrajda (kenar payı {pay} px); ölçülen piksel konumu Gazebo pozundan öngörülenle ortalama {sum(hatalar) / len(hatalar):.2f} px, en çok {max(hatalar):.2f} px farklı (≤ 15); "
              f"u aralığı {min(r['olculen_uv'][0] for r in tam):.0f}…{max(r['olculen_uv'][0] for r in tam):.0f} (yaklaşık beklenen {o['yaklasik_beklenen_u']}), v aralığı {min(r['olculen_uv'][1] for r in tam):.0f}…{max(r['olculen_uv'][1] for r in tam):.0f}" if tam else "tamamen kadrajdaki tespit yok")
        if len(tam) >= 2:
            v0, v1 = tam[0]["olculen_uv"][1], tam[-1]["olculen_uv"][1]
            sonuc(v1 > v0 and tam[0]["poz"][1] < tam[-1]["poz"][1] and all(r["olculen_uv"][0] > w / 2 for r in tam), "gorus_yon",
                  f"araç +y (kuzey, uçuş) yönünde ilerlerken işaret görüntüde aşağı kayıyor (v {v0:.0f} → {v1:.0f}): görüntüde yukarı = uçuş yönü; işaret (rotanın doğusunda) görüntünün sağında (u > {w // 2}): sağ = gövdenin sağı; yatay eksen uçuş yönüne dik")
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
