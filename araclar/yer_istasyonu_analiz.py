#!/usr/bin/env python3
"""Yer istasyonu görev koordinatörü koşusunun çözümlemesi (test yardımcısı).

Kullanım:  python araclar/yer_istasyonu_analiz.py <koşu_klasörü> --arac N [--komut ARAC --komut-oncesi SAYI] [--mission-hata ARAC] [--bayat ARAC]
  (bayraksız)    olağan akış: Mission ulaştı ve yerel dosyayla eşit; t0 → tarama bitişleri → son sonuç → t1 → TAMAMLANDI sırası; ortak başlangıç/bitiş; T (monotonik ve sim) ve RTF; izleme geçişleri; bayat uyarı yok;
                 her araçta tam kare sonucu kümesi, araç ↔ yer istasyonu birebir, L
  --komut ARAC   komut iskeleti: koşu akışına ek olarak ARAC'a iki komut (sıra 1 ve tekrar 1) gönderildi → ACK_REJECTED ×2 (komut türü tanımsız, tekrar sıra), diğer araçlar tepkisiz, PX4 yazma (komut) olayı yeni yok
  --komut-oncesi komut gönderilmeden önce ARAC'ın px4_adapter günlüğündeki `komut` (yazma) olay sayısı
  --mission-hata ARAC  Mission uyuşmazlığı: ARAC yüklemedi (çıkış kodu 4), t0 yok, COMPLETE yok, zaman aşımı kaydı; diğer araçlar BARIYER_BEKLE'de bekledi
  --bayat ARAC   ARAC'ın durum yayımı susturuldu: izleme kaydında yalnız o araç için bir bayat uyarısı ve bitişi; akış değişmedi (t1 var)
Her sonuç "SONUC <gecti|kaldi> <ad> | <ayrıntı>" satırıdır; ardından ölçüm satırları ("OLCUM ..."). Kaldı varsa çıkış 1. Yalnız standart kitaplık."""
import json
import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arac_sureci_analiz as asa  # noqa: E402

NS = 10 ** 9
KALDI = 0
DIZI = ["HAZIR", "BARIYER_BEKLE", "TARAMA", "WAIT", "TAMAMLANDI"]
SONUC_DURUMU = {"tespit": "sonuc", "tespit_yok": "tespit_yok", "islem_hatasi": "islem_hatasi", "kare_alinamadi": "kare_alinamadi"}


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


def ana(argv):
    a = list(argv)
    if not a:
        print(__doc__, file=sys.stderr)
        return 2
    klasor = a.pop(0)
    n_arac, komut, komut_oncesi, mission_hata, bayat = 0, None, None, None, None
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k == "--komut" and a:
            komut = int(a.pop(0))
        elif k == "--komut-oncesi" and a:
            komut_oncesi = int(a.pop(0))
        elif k == "--mission-hata" and a:
            mission_hata = int(a.pop(0))
        elif k == "--bayat" and a:
            bayat = int(a.pop(0))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))
    from swarm_vehicle.ucus import rota
    ham = rota.deney_env_oku()
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()][:n_arac]
    gorev = jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_gorev.jsonl"))
    durum = jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_durum.jsonl"))
    ol = lambda ad: [x for x in gorev if x["olay"] == ad]  # noqa: E731
    t0 = (ol("t0") or [None])[0]
    t1 = (ol("t1") or [None])[0]
    logs = {k: asa.log_oku(os.path.join(klasor, f"arac_{k}.log")) for k in kimlikler}

    def cikis(k):
        yol = os.path.join(klasor, f"arac_{k}.cikis")
        return int(open(yol, encoding="utf-8").read()) if os.path.isfile(yol) else None

    # --- Mission uyuşmazlığı senaryosu ---------------------------------------------------------------------------------------------
    if mission_hata is not None:
        k = mission_hata
        sonuc("mission_uyusmuyor" in logs[k] and cikis(k) == 4, f"mission_hata_{k}",
              f"araç {k}: yerel dosyayla uyuşmayan Mission → açık hata ({logs[k].get('mission_uyusmuyor', [{}])[0].get('fark', '-')}), süreç çıkış kodu {cikis(k)} (beklenen 4)")
        yukleme = os.path.isfile(os.path.join(klasor, f"px4_adapter_{k}.log")) and " yukleme " in open(os.path.join(klasor, f"px4_adapter_{k}.log"), encoding="utf-8").read()
        sonuc(not yukleme and "rota_yuklendi" not in logs[k], f"mission_yukleme_yok_{k}", f"araç {k}: rota PX4'e yüklenmedi (px4_adapter günlüğünde `yukleme` olayı yok, araç günlüğünde rota_yuklendi yok)")
        sonuc(t0 is None and t1 is None, "mission_t0_yok", "koşu başlamadı: görev kaydında t0 ve t1 yok")
        e = [h for h in ol("hata") if h.get("neden") == "arac_erken_cikti" and h.get("arac_kimligi") == k]
        sonuc(bool(e) and e[0].get("ayrinti") == "cikis_kodu=4 evre=t0_oncesi", "mission_acik_hata",
              f"koordinatör açık hata kaydı yazdı: arac_erken_cikti araç {k} ({e[0].get('ayrinti') if e else '-'}; beklenen cikis_kodu=4 evre=t0_oncesi); zaman aşımı kabul edilmez")
        t_a, t_y = (os.path.getmtime(os.path.join(klasor, f)) if os.path.isfile(os.path.join(klasor, f)) else None for f in (f"arac_{k}.cikis", "yer_istasyonu.cikis"))
        if t_a is not None and t_y is not None:
            print(f"OLCUM mission: araç {k} çıkışından yer istasyonu bitişine {t_y - t_a:.2f} sn")
            sonuc(0 <= t_y - t_a <= 10, "mission_gecikmesiz", f"yer istasyonu araç çıkışından {t_y - t_a:.2f} sn sonra bitti (sınır 10 sn; GCS_UST_SN beklenmedi)")
        else:
            sonuc(False, "mission_gecikmesiz", "araç ya da yer istasyonu çıkış dosyası yok")
        return 1 if KALDI else 0

    # --- ortak: görev kaydı ---------------------------------------------------------------------------------------------------------
    sonuc(t0 is not None, "t0_var", "görev kaydında t0 var" if t0 else "t0 yok")
    if bayat is None and mission_hata is None:
        sonuc(t1 is not None and bool(ol("son_sonuc")), "t1_var", "görev kaydında son_sonuc ve t1 var" if t1 else "t1 yok")
    if t0 is None or t1 is None:
        return 1
    atanan = {x["arac_kimligi"]: x["mission_id"] for x in ol("gorev_atandi")}
    sonuc(set(atanan) == set(kimlikler) and len(set(atanan.values())) == 1, "gorev_atandi", f"her araca Mission atandı, ortak mission_id: {sorted(set(atanan.values()))}")
    for k in kimlikler:
        l = logs[k]
        ok = "mission_dogrulandi" in l and l["mission_alindi"][0]["mission_id"] == atanan[k] and "mission_uyusmuyor" not in l
        sonuc(ok, f"mission_ulasti_{k}", f"araç {k}: Mission alındı (bölge {l['mission_alindi'][0]['bolge']}, {l['mission_alindi'][0]['nokta']} nokta) ve yerel bolge_rota.json ile birebir eşit (yerel SHA-256 {l['mission_dogrulandi'][0]['yerel_sha256']}…)" if ok else "Mission doğrulanmadı")
    # sıra: t0 → bitişler → son_sonuc → t1 → tamamlandi
    bit = {x["arac_kimligi"]: x for x in ol("tarama_bitisi")}
    tam = {x["arac_kimligi"]: x for x in ol("tamamlandi")}
    son = ol("son_sonuc")[0]
    sira_ok = all(t0["mono_ns"] < bit[k]["mono_ns"] for k in kimlikler) and max(b["mono_ns"] for b in bit.values()) <= son["mono_ns"] <= t1["mono_ns"] and all(t1["mono_ns"] < tam[k]["mono_ns"] for k in kimlikler)
    sonuc(sira_ok and set(bit) == set(kimlikler) and set(tam) == set(kimlikler), "sira",
          "t0 → " + ", ".join(f"araç {k} bitişi +{(bit[k]['mono_ns'] - t0['mono_ns']) / 1e9:.1f} s" for k in kimlikler) + f" → son sonuç +{(son['mono_ns'] - t0['mono_ns']) / 1e9:.1f} s → t1 +{(t1['mono_ns'] - t0['mono_ns']) / 1e9:.1f} s → "
          + ", ".join(f"araç {k} TAMAMLANDI +{(tam[k]['mono_ns'] - t0['mono_ns']) / 1e9:.1f} s" for k in kimlikler))
    # ortak başlangıç ve bitiş (araçların kendi günlüklerinden alım anları; aynı makinede CLOCK_MONOTONIC)
    basl = {k: logs[k]["tarama_baslat_alindi"][0]["mono_ns"] for k in kimlikler}
    fark_b = {k: (basl[k] - t0["mono_ns"]) / 1e6 for k in kimlikler}
    sonuc(all(v > -5 for v in fark_b.values()) and max(fark_b.values()) < 2000, "ortak_baslangic",
          "ScanStart alım anları t0'a göre (ms): " + ", ".join(f"araç {k} {v:+.1f}" for k, v in fark_b.items()) + f"; en büyük fark {max(fark_b.values()):.1f} ms, araçlar arası yayılım {max(fark_b.values()) - min(fark_b.values()):.1f} ms")
    comp = {k: logs[k]["complete_alindi"][0]["mono_ns"] for k in kimlikler}
    fark_c = {k: (comp[k] - t1["mono_ns"]) / 1e6 for k in kimlikler}
    sonuc(all(v > -5 for v in fark_c.values()) and max(fark_c.values()) < 2000, "ortak_bitis",
          "COMPLETE alım anları t1'e göre (ms): " + ", ".join(f"araç {k} {v:+.1f}" for k, v in fark_c.items()) + f"; yayılım {max(fark_c.values()) - min(fark_c.values()):.1f} ms")
    T_mono = (t1["mono_ns"] - t0["mono_ns"]) / 1e9
    T_sim = (t1["sim_ns"] - t0["sim_ns"]) / 1e9 if t0["sim_ns"] is not None and t1["sim_ns"] is not None else None
    print(f"OLCUM T = t1 − t0: monotonik {T_mono:.2f} s" + (f", sim {T_sim:.2f} s, RTF {T_sim / T_mono:.3f}" if T_sim else "") + f"; t1 − son tarama bitişi {t1['t1_eksi_son_bitis_ns'] / 1e6:.1f} ms; mission_id {t1['mission_id']}")
    # izleme
    dizi = {k: [] for k in kimlikler}
    for x in durum:
        if x["olay"] == "durum_degisti" and x["arac_kimligi"] in dizi and (not dizi[x["arac_kimligi"]] or dizi[x["arac_kimligi"]][-1] != x["durum"]):
            dizi[x["arac_kimligi"]].append(x["durum"])
    sonuc(all(dizi[k] == DIZI for k in kimlikler), "izleme_gecisleri", "izleme kaydındaki durum dizisi (her araç): " + "; ".join(f"{k}: {' → '.join(dizi[k])}" for k in kimlikler))
    uyari = [x for x in durum if x["olay"] == "bayat_uyari"]
    ozet = [x for x in durum if x["olay"] == "ozet"]
    if bayat is None:
        sonuc(not uyari, "bayat_uyarisi_yok", f"izleme kaydında bayat durum uyarısı {len(uyari)}; periyodik özet satırı {len(ozet)} (IZLEME_OZET_SN={ham['IZLEME_OZET_SN']})")
    else:
        u = [x for x in uyari]
        sonuc(len(u) == 1 and u[0]["arac_kimligi"] == bayat and any(x["olay"] == "bayat_bitti" and x["arac_kimligi"] == bayat for x in durum), "bayat_uyarisi",
              f"yalnız araç {bayat} için bir bayat uyarısı ({[(x['arac_kimligi'], x['sessiz_sn']) for x in u]}) ve bayat_bitti kaydı; IZLEME_BAYAT_SN={ham['IZLEME_BAYAT_SN']}; akış değişmedi (t1 var)")
    # kare koşulu (uçta mod kare sonucu denetimleri, yer istasyonunun asıl koordinatör yolundan)
    damga = jsonl(os.path.join(klasor, "kayit", "gazebo_damga.jsonl"))
    yer = jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_kare.jsonl"))
    for k in kimlikler:
        b = logs[k]["tarama_bitis_yayimlandi"][0]
        n_ilk, n_son = int(b["n_first"]), int(b["n_last"])
        aralik = list(range(n_ilk, n_son + 1))
        y = [r for r in yer if r["arac_kimligi"] == k]
        say = {}
        for r in y:
            say[r["n"]] = say.get(r["n"], 0) + 1
        eksik = [n for n in aralik if say.get(n, 0) != 1]
        sonuc(not eksik and len(y) == len(aralik) and bit[k]["n_ilk"] == n_ilk and bit[k]["n_son"] == n_son, f"sonuc_kumesi_{k}",
              f"araç {k}: görev kaydındaki aralık [{n_ilk}, {n_son}] araç günlüğüyle aynı; {len(aralik)} numaranın her biri için yer istasyonunda tam bir sonuç (eksik/yinelenen {eksik[:5]})")
        sn = {r["n"]: r for r in jsonl(os.path.join(klasor, "kayit", f"kare_sonuc_{k}.jsonl"))}
        yd = {r["n"]: r["sonuc_durumu"] for r in y}
        farkli = [n for n in aralik if SONUC_DURUMU[sn[n]["durum"]] != yd.get(n)]
        sonuc(not farkli, f"arac_yer_birebir_{k}", f"araç ↔ yer istasyonu numara + durum birebir ({len(aralik)} numara, farklı {farkli[:5]})")
        uretim = {r["n"]: r["mono_ns"] for r in damga if r["arac_kimligi"] == k and r["olay"] == "uretim" and isinstance(r["n"], int)}
        L = [(r["mono_ns"] - uretim[r["n"]]) / 1e6 for r in y if r["sonuc_durumu"] in ("sonuc", "tespit_yok") and r["n"] in uretim]
        print(f"OLCUM araç {k}: L ortanca {yuzdelik(L, 50):.1f} ms, p95 {yuzdelik(L, 95):.1f} ms, en çok {max(L):.1f} ms ({len(L)} kare)")
        s_sim = (int(b["t_b_ns"]) - int(b["t_s_ns"])) / NS
        s_mono = (logs[k]["son_nokta_geri_cagrisi"][0]["mono_ns"] - logs[k]["tarama_baslat_alindi"][0]["mono_ns"]) / NS
        print(f"OLCUM araç {k}: tarama sim {s_sim:.1f} s, monotonik {s_mono:.1f} s, RTF {s_sim / s_mono:.3f}")
    for k in kimlikler:
        sonuc(cikis(k) == 0, f"arac_cikis_{k}", f"araç {k} süreci kendiliğinden kapandı (çıkış {cikis(k)})")
    # --- komut iskeleti ---------------------------------------------------------------------------------------------------------------
    if komut is not None:
        al = [x for x in logs[komut].get("komut_alindi", [])]
        sonuc(len(al) == 2 and all(x["ack"] == "ACK_REJECTED" for x in al) and [x["neden"] for x in al] == ["komut_turu_belgede_tanimli_degil", "tekrar_ya_da_geriye_sira"], f"komut_onay_{komut}",
              f"araç {komut}: {len(al)} komut alındı; ack {[x['ack'] for x in al]}, neden {[x['neden'] for x in al]}; sıra {[x['sequence'] for x in al]}")
        digerleri = [k for k in kimlikler if k != komut]
        sonuc(all("komut_alindi" not in logs[k] for k in digerleri), "komut_digerleri_tepkisiz", f"diğer araçlar {digerleri} komut almadı/tepki vermedi")
        kayit = jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_komut.jsonl"))
        g = [x for x in kayit if x["olay"] == "komut_gonderildi"]
        o = [x for x in kayit if x["olay"] == "onay_alindi"]
        sonuc(len(g) == 2 and len(o) == 2 and all(x["ack_state"] == "ACK_REJECTED" and x["arac_kimligi"] == komut and x["sequence"] == 1 for x in o), "komut_yer_istasyonu_kaydi",
              f"yer istasyonu komut kaydı: {len(g)} gönderim (ACK_PENDING), {len(o)} onay {[x['ack_state'] for x in o]}")
        ap = os.path.join(klasor, f"px4_adapter_{komut}.log")
        satirlar = open(ap, encoding="utf-8").read().splitlines()
        yazma = sum(1 for s_ in satirlar if len(s_.split(" ")) > 2 and s_.split(" ")[2] == "komut")
        red = sum(1 for s_ in satirlar if len(s_.split(" ")) > 2 and s_.split(" ")[2] == "komut_reddedildi")
        sonuc(komut_oncesi is not None and yazma == komut_oncesi and red == 2, "komut_px4_yazma_yok",
              f"px4_adapter günlüğünde PX4'e yazma (`komut`) olayı: komuttan önce {komut_oncesi}, sonra {yazma} (yeni yazma yok); `komut_reddedildi` {red}")
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
