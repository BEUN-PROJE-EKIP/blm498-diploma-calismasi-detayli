#!/usr/bin/env python3
"""Çıkarım işçisi ve kare sonucu koşusunun çözümlemesi (test yardımcısı): damga, alıcı, işçi ve kare sonucu kayıtları araç + n üzerinden birleştirilir.

Kullanım:  python araclar/analiz/cikarim_analiz.py <koşu_klasörü> --arac N [--enjeksiyon] [--gz-ip-yok]
  --enjeksiyon  hata enjeksiyonlu koşu (KAMERA_ENJEKSIYON='dusur=+20'; ISCI_ENJEKSIYON='hata=+40;olum=+80'): beklenen durum kümeleri denetlenir; yoksa hata/kayıpsız koşu beklenir
  --gz-ip-yok   araç süreçleri GZ_IP verilmeden başlatıldı: soket kanıtı (canli_<araç>.json) denetlenir
Her sonuç "SONUC <gecti|kaldi> <ad> | <ayrıntı>" satırıdır; kaldı varsa çıkış 1. Yalnız standart kitaplık.
"""
import json
import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KALDI = 0
NS = 10 ** 9
DURUMLAR = ("tespit", "tespit_yok", "islem_hatasi", "kare_alinamadi")


def sonuc(gecti, ad, ayrinti):
    global KALDI
    if not gecti:
        KALDI += 1
    print(f"SONUC {'gecti' if gecti else 'kaldi'} {ad} | {ayrinti}", flush=True)


def jsonl(yol):
    with open(yol, encoding="utf-8") as f:
        return [json.loads(s) for s in f if s.strip()]


def log_oku(yol):
    """Araç günlüğü: olay → [anahtar-değer sözlükleri]; her kayıtta `mono_ns` ve `sira` (dosya sırası)."""
    s = {}
    sira = 0
    with open(yol, encoding="utf-8") as f:
        for satir in f:
            p = satir.rstrip("\n").split(" ")
            if len(p) < 3:
                continue
            i = 2
            kv = {"mono_ns": int(p[1]), "sira": sira}
            sira += 1
            if p[i].startswith("sim_ns="):
                kv["sim_ns"] = p[i][7:]
                i += 1
            olay = p[i]
            for t in p[i + 1:]:
                if "=" in t:
                    k, v = t.split("=", 1)
                    kv[k] = v
            s.setdefault(olay, []).append(kv)
    return s


def yuzde(liste, p):
    liste = sorted(liste)
    return liste[min(len(liste) - 1, int(math.ceil(p / 100 * len(liste))) - 1)] if liste else float("nan")


def ana(argv):
    a = list(argv)
    if not a:
        print(__doc__, file=sys.stderr)
        return 2
    klasor = a.pop(0)
    n_arac, enj, gz_ip_yok = 0, False, False
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k == "--enjeksiyon":
            enj = True
        elif k == "--gz-ip-yok":
            gz_ip_yok = True
        else:
            print(__doc__, file=sys.stderr)
            return 2
    sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))
    from swarm_vehicle.ucus import rota
    ham = rota.deney_env_oku()
    hz = int(float(ham["CAM_RATE_HZ"]))
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()][:n_arac]
    damga_hepsi = jsonl(os.path.join(klasor, "kayit", "gazebo_damga.jsonl"))
    ozetler = []
    for sira_no, k in enumerate(kimlikler, start=1):
        alog = log_oku(os.path.join(klasor, f"arac_{k}.log"))
        al = jsonl(os.path.join(klasor, "kayit", f"kamera_alici_{k}.jsonl"))
        isci = jsonl(os.path.join(klasor, "kayit", f"cikarim_iscisi_{k}.jsonl"))
        kayitlar = jsonl(os.path.join(klasor, "kayit", f"kare_sonuc_{k}.jsonl"))
        kaynak = jsonl(os.path.join(klasor, "kayit", f"isci_kaynak_{k}.jsonl"))
        dm = {r["sim_damga_ns"]: r for r in damga_hepsi if r["arac_kimligi"] == k}
        ts, tb = int(alog["tarama_baslat_alindi"][0]["t_s_ns"]), int(alog["tarama_bitis_yayimlandi"][0]["t_b_ns"])
        n_ilk, n_son = -((-hz * ts) // NS), (hz * tb) // NS
        aralik = list(range(n_ilk, n_son + 1))
        # --- tam bir sonuç -----------------------------------------------------------------------------------------------------------------
        sayim = {}
        for r in kayitlar:
            sayim[r["n"]] = sayim.get(r["n"], 0) + 1
        eksik = [n for n in aralik if n not in sayim]
        fazla = [n for n in sayim if n not in set(aralik)]
        cift = [n for n, c in sayim.items() if c != 1]
        sonuc(not eksik and not fazla and not cift, f"tam_bir_sonuc_{k}",
              f"[{n_ilk}, {n_son}] aralığındaki {len(aralik)} numaranın her biri için tam bir kare sonucu ({len(kayitlar)} kayıt); eksik {eksik[:5]}, aralık dışı {fazla[:5]}, birden çok {cift[:5]}")
        by = {r["n"]: r for r in kayitlar}
        say = {d: sum(1 for r in kayitlar if r["durum"] == d) for d in DURUMLAR}
        bozuk = [r["n"] for r in kayitlar if r["durum"] not in DURUMLAR or (r["durum"] == "tespit") != bool(r["tespitler"]) or (r["durum"] != "tespit" and r["tespitler"])]
        sonuc(not bozuk and all((r["durum"] == "islem_hatasi") == bool(r["hata"]) for r in kayitlar), f"dort_durum_{k}",
              f"dört durum ayrı kodlanmış: tespit {say['tespit']}, tespit_yok {say['tespit_yok']}, islem_hatasi {say['islem_hatasi']}, kare_alinamadi {say['kare_alinamadi']} (toplam {sum(say.values())}); tutarsız kayıt {bozuk[:5]}")
        # --- alıcı ile uyum ------------------------------------------------------------------------------------------------------------------
        gorev = sorted(r["n"] for r in al if r["olay"] == "kuyruga_giris")
        kayip = sorted(r["n"] for r in al if r["olay"] == "kayip_tespit" and r.get("sonuc_durumu") == "kare_alinamadi")
        islendi = sorted(n for n, r in by.items() if r["durum"] in ("tespit", "tespit_yok", "islem_hatasi"))
        sonuc(islendi == gorev and sorted(n for n, r in by.items() if r["durum"] == "kare_alinamadi") == kayip, f"alici_uyumu_{k}",
              f"alıcının görev karesi ({len(gorev)}) ve kayıp ({len(kayip)}) kümeleri kare sonuçlarıyla birebir aynı (işlenen {len(islendi)}, kare_alinamadi {say['kare_alinamadi']})")
        # --- işçi olayları ---------------------------------------------------------------------------------------------------------------------
        basi = {r["n"]: r for r in isci if r["olay"] == "cikarim_basi"}
        sonu = {r["n"]: r for r in isci if r["olay"] == "cikarim_sonu"}
        giris = {r["n"]: r for r in al if r["olay"] == "kuyruga_giris"}
        olumlu = [n for n in islendi if n in basi and n not in sonu]                  # işçi ölümü: yalnız basi var
        eksik_basi = [n for n in islendi if n not in basi]
        eksik_sonu = [n for n in islendi if n not in sonu and n not in olumlu]
        sira_ihlali = [n for n in islendi if n in sonu and n in basi and not (sonu[n]["mono_ns"] >= basi[n]["mono_ns"])]
        kuyruk_ihlali = [n for n in islendi if n in basi and giris[n]["mono_ns"] > basi[n]["mono_ns"]]
        olu_beklenen = {n_ilk + 80} if enj else set()
        sonuc(not [n for n in eksik_basi if n not in olu_beklenen] and not eksik_sonu and set(olumlu) == olu_beklenen and not sira_ihlali and not kuyruk_ihlali, f"isci_olaylari_{k}",
              f"{len(islendi)} işlenen karenin hepsinde cikarim_basi; {len(sonu)} karede cikarim_sonu ≥ cikarim_basi (ihlal {sira_ihlali[:3]}); kuyruga_giris ≤ cikarim_basi (ihlal {kuyruk_ihlali[:3]}); "
              f"yalnız basi olan (işçi ölümü) {olumlu}; eksik basi {eksik_basi[:3]}; eksik sonu {eksik_sonu[:3]}")
        # --- damga ↔ alıcı ↔ işçi ↔ kare sonucu birleşmesi ---------------------------------------------------------------------------------
        zincir_hata = []
        uretim_alim = []
        for n in islendi:
            d = dm.get(n * NS // hz)
            if d is None or n not in giris or n not in basi:
                zincir_hata.append((n, "kayıt eksik"))
                continue
            uretim_alim.append((giris[n]["mono_ns"] - d["mono_ns"]) / 1e6)
            adimlar = [giris[n]["mono_ns"], basi[n]["mono_ns"]] + ([sonu[n]["mono_ns"]] if n in sonu else []) + [by[n]["mono_ns"]]
            if any(y < x for x, y in zip(adimlar, adimlar[1:])) or (giris[n]["mono_ns"] - d["mono_ns"]) / 1e6 < -50:
                zincir_hata.append((n, "zaman sırası bozuk"))
        sonuc(not zincir_hata, f"damga_birlesme_{k}",
              f"{len(islendi)} işlenen karede damga(uretim) → kuyruga_giris → cikarim_basi → cikarim_sonu → kare sonucu zinciri araç+n üzerinden eksiksiz birleşti ve zaman sırası doğru (damga→alıcı farkı ortanca {yuzde(uretim_alim, 50):.2f} ms, en az {min(uretim_alim):.2f} ms; ≥ −50 ms kabul); ihlal {zincir_hata[:3]}")
        kayip_damgada = [n for n in kayip if (n * NS // hz) in dm]
        sonuc(len(kayip_damgada) == len(kayip), f"kayip_damgada_{k}", f"'kare_alinamadi' sonuçlu {len(kayip)} numaranın {len(kayip_damgada)}'i damga kaydında var (Gazebo üretti, alıcıya ulaşmadı)")
        # --- beklenen durum kümeleri ---------------------------------------------------------------------------------------------------------
        if not enj:
            diger = [r for r in kayitlar if r["durum"] in ("islem_hatasi", "kare_alinamadi")]
            sinif_say = {}
            for r in kayitlar:
                for t in r["tespitler"]:
                    sinif_say[t["sinif"]] = sinif_say.get(t["sinif"], 0) + 1
            sonuc(not diger, f"kayipsiz_hatasiz_{k}",
                  f"enjeksiyonsuz koşuda işlem hatası ve kare alınamadı yok (bulunan {len(diger)}); boş sahnede beklenen tespit_yok {say['tespit_yok']}/{len(kayitlar)}; tespit çıkan kare {say['tespit']} (sınıflar {sinif_say or 'yok'}); "
                  f"proje sınıfı dışında atılan tespit {sum(r['atilan_sinif_disi'] for r in kayitlar)}")
        else:
            hata_n, olum_n, kayip_n = n_ilk + 40, n_ilk + 80, n_ilk + 20
            durum_of = {n: by[n]["durum"] for n in aralik if n in by}
            beklenen_diger = {n: "tespit_yok" for n in aralik if n not in (hata_n, olum_n, kayip_n)}
            gercek_diger = {n: d for n, d in durum_of.items() if n not in (hata_n, olum_n, kayip_n)}
            sonuc(durum_of.get(kayip_n) == "kare_alinamadi" and not by[kayip_n]["tespitler"] and kayip_n in kayip, f"enj_kayip_{k}", f"alıcı enjeksiyonu: n={kayip_n} → kare_alinamadi (tespit taşımıyor)")
            sonuc(durum_of.get(hata_n) == "islem_hatasi" and "enjekte" in (by[hata_n]["hata"] or ""), f"enj_isci_hatasi_{k}", f"işçi hata enjeksiyonu: n={hata_n} → islem_hatasi ('{by[hata_n]['hata']}'), tespit_yok DEĞİL")
            sonuc(durum_of.get(olum_n) == "islem_hatasi" and "öldü" in (by[olum_n]["hata"] or ""), f"enj_isci_olumu_{k}", f"işçi ölümü: n={olum_n} → islem_hatasi ('{by[olum_n]['hata']}'); cikarim_basi var, cikarim_sonu yok: {olum_n in basi and olum_n not in sonu}")
            sonuc(gercek_diger == beklenen_diger, f"enj_diger_kareler_{k}",
                  f"üç enjeksiyon dışında {len(beklenen_diger)} numaranın hepsi tespit_yok (işçi yeniden başlatıldıktan sonra bekleyen kareler atılmadan işlendi); farklı olan: {[(n, d) for n, d in gercek_diger.items() if d != 'tespit_yok'][:5]}")
            tamam = alog["kare_sonuclari_tamam"][0]
            sonuc(tamam["isci_baslatma"] == "2" and tamam["isci_yeniden"] == "1" and "isci_yeniden_baslatiliyor" in alog, f"enj_yeniden_baslatma_{k}",
                  f"işçi {tamam['isci_baslatma']} kez başlatıldı, {tamam['isci_yeniden']} yeniden başlatma; işçi pid'leri günlükte: {[x['pid'] for x in alog['isci_baslatildi']]}; kuyruk en çok {tamam['kuyruk_maks']} kare bekledi")
            sonuc(not alog.get("kare_sonuc_cift"), f"enj_cift_yok_{k}", f"ikinci sonuç denemesi yok (cift_sonuc={tamam['cift_sonuc']})")
        # --- hazırlık ve sıra ---------------------------------------------------------------------------------------------------------------------
        hz_k = alog["isci_hazir"][0]
        bariyer = [r for r in alog["durum"] if r.get("durum") == "BARIYER_BEKLE"][0]
        hazir_bekle = alog["isci_hazir_bekleme_bitti"][0]
        sonuc(hz_k["sira"] < hazir_bekle["sira"] < bariyer["sira"] and hz_k["rclpy_yuklu"] == "False", f"bariyer_sirasi_{k}",
              f"günlük sırası: isci_hazir (satır {hz_k['sira']}) < isci_hazir_bekleme_bitti ({hazir_bekle['sira']}) < BARIYER_BEKLE ({bariyer['sira']}); işçi hazır olmadan BARIYER_BEKLE yok; "
              f"model yükleme {hz_k['yukleme_s']} sn, ısınma {hz_k['isinma_s']} sn ({hz_k['isinma_kare']} çıkarım), hazırlıkta ek bekleme {hazir_bekle['ek_bekleme_s']} sn; işçide rclpy yok; uçtan uca: {hz_k['uc_uca']}")
        # --- kuyruk, süre, kaynak ---------------------------------------------------------------------------------------------------------------
        tamam = alog["kare_sonuclari_tamam"][0]
        sonuc(tamam["zamaninda"] == "True" and tamam["zorla_kayip"] == "yok" and tamam["kapanista_islem_hatasi"] == "yok" and int(tamam["mesaj"]) == len(kayitlar), f"kapanis_{k}",
              f"kare sonuçları kapanış süresinden önce tamamlandı (bekleme {tamam['bekleme_s']} sn); zorla kayıp {tamam['zorla_kayip']}; kapanışta işlem hatası {tamam['kapanista_islem_hatasi']}; "
              f"FrameResult iletisi oluşturuldu {tamam['mesaj']}/{len(kayitlar)} (ağa gönderilmedi)")
        sure = [(sonu[n]["mono_ns"] - basi[n]["mono_ns"]) / 1e6 for n in islendi if n in sonu and n in basi]
        sonuc(bool(sure) and min(sure) >= 0, f"cikarim_suresi_{k}",
              f"kare başına çıkarım süresi (cikarim_basi→cikarim_sonu, {len(sure)} kare, ms): ortanca {yuzde(sure, 50):.2f}, p99 {yuzde(sure, 99):.2f}, en çok {max(sure):.2f}; "
              f"uçtan uca (kuyruga_giris→kare sonucu) ortanca {yuzde([(by[n]['mono_ns'] - giris[n]['mono_ns']) / 1e6 for n in islendi], 50):.1f} ms, en çok {max((by[n]['mono_ns'] - giris[n]['mono_ns']) / 1e6 for n in islendi):.1f} ms; kuyruk en çok {tamam['kuyruk_maks']} kare")
        bel = [r["gpu_bellek_mib"] for r in kaynak if r["gpu_bellek_mib"] is not None]
        kul = [r["gpu_kullanim_yuzde"] for r in kaynak if r["gpu_kullanim_yuzde"] is not None]
        sonuc(len(kaynak) >= 5 and bool(bel) and bool(kul), f"isci_kaynak_{k}",
              f"{len(kaynak)} periyodik kaynak kaydı: GPU belleği (NVML süreç) en çok {max(bel) if bel else '-'} MiB; GPU kullanımı (SM %) ortalama {sum(kul) / len(kul) if kul else float('nan'):.1f}, en çok {max(kul) if kul else '-'}; "
              f"ana bellek RSS en çok {max(r['ana_bellek_rss_mib'] for r in kaynak):.0f} MiB; işçi pid'leri {sorted({r['isci_pid'] for r in kaynak})}")
        t0, t1 = alog["tarama_baslat_alindi"][0], alog["tarama_bitis_yayimlandi"][0]
        rtf = (int(t1["t_b_ns"]) - int(t0["t_s_ns"])) / max(t1["mono_ns"] - t0["mono_ns"], 1)
        ozetler.append((k, rtf))
        sonuc(0.9 < rtf < 1.1, f"rtf_{k}", f"gerçek zaman faktörü (tarama: sim {(int(t1['t_b_ns']) - int(t0['t_s_ns'])) / NS:.1f} sn / gerçek {(t1['mono_ns'] - t0['mono_ns']) / NS:.1f} sn) = {rtf:.4f}")
        # --- CPU sabitlemesi (canlı denetim) -----------------------------------------------------------------------------------------------
        cd = os.path.join(klasor, f"canli_{k}.json")
        if os.path.exists(cd) and ham.get("ISCI_CPU_SABITLE") == "1":
            c = json.load(open(cd, encoding="utf-8"))
            bas = alog["isci_baslatildi"]
            iscler = list(c["isciler"].values())
            hazir_cpu = sorted(int(x) for x in alog["isci_hazir"][0]["cpu"].split(","))
            sonuc(bool(iscler) and all(i["cpu"] == hazir_cpu and len(i["cpu"]) == int(ham["ISCI_MANTIKSAL_CPU"]) for i in iscler), f"cpu_sabit_{k}",
                  f"çalışan işçinin gerçek CPU kümesi (sched_getaffinity = taskset -p) {[i['cpu'] for i in iscler]}; günlükteki eşleme: {bas[0]['cpu_eslemesi'] if bas else '-'}")
            sonuc(all(set(i["soket_turleri"]) == {"unix"} for i in iscler), f"kanal_ip_yok_{k}", f"işçi sürecinin soket türleri {[i['soket_turleri'] for i in iscler]} (yalnız unix; TCP/UDP yok)")
        if gz_ip_yok and os.path.exists(cd):
            c = json.load(open(cd, encoding="utf-8"))
            gozlem = sorted(c["arac_inet"])
            tcp = [g for g in gozlem if g.startswith(("tcp ", "tcp6 "))]
            yerel_tcp = [g for g in tcp if g.split()[1].startswith(("127.0.0.1:", "::1:", "::ffff:7f00:1:"))]
            dinleyen = [g for g in tcp if g.endswith("LISTEN")]
            ddsli = sorted({g.split()[1].rsplit(":", 1)[0] for g in gozlem if g.startswith("udp ") and g.split()[1].startswith("10.10.")})
            sonuc(bool(dinleyen) and len(yerel_tcp) == len(tcp), f"gz_ip_{k}",
                  f"araç süreci GZ_IP verilmeden başlatıldı; gz-transport'un (ZeroMQ) bütün TCP soketleri ({len(tcp)}; {len(dinleyen)} dinleyen) yalnız loopback'te: {tcp}; sürü ağı adreslerinde ({ddsli}) yalnız UDP (DDS) soketi var, TCP yok; "
                  f"gz keşif soketleri UDP 10317/10318 (0.0.0.0, çok noktaya yayın): {[g for g in gozlem if ':10317 ' in g or ':10318 ' in g]}")
            sonuc("gz_ip=127.0.0.1" in " ".join(f"{a}={b}" for a, b in alog["basladi"][0].items()), f"gz_ip_gunluk_{k}", f"araç günlüğü: gz_ip={alog['basladi'][0].get('gz_ip')}")
    for k, r in ozetler:
        print(f"OZET arac {k}: rtf {r:.4f}", flush=True)
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
