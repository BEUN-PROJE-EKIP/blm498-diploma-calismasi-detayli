#!/usr/bin/env python3
"""Merkezi mod (araç başına TCP görüntü kanalı + yer istasyonu çıkarımı, B12) koşusunun çözümlemesi (YALNIZ okuma; test yardımcısı).

Kullanım:  python3 -I araclar/merkezi_analiz.py <koşu_klasörü> --arac N [--hata] [--basinc <başlangıç_sn>:<süre_sn>] [--sha] [--tc-once BAYT --tc-sonra BAYT] [--uc-klasoru <uçta mod koşu klasörü>] [--tek-klasoru <tek araç merkezi koşu klasörü>]
  --hata      hata senaryosu: araçta `KAMERA_ENJEKSIYON=dusur=+20` (kare alınamadı), yer istasyonunda `ISCI_ENJEKSIYON=hata=+40` (işlem hatası) beklenir
  --basinc    yer istasyonu alıcısı `MERKEZI_ENJEKSIYON=okuma_dur=<başlangıç>:<süre>` ile okumayı durdurdu: kuyruk büyümeli, kare atılmamalı, hepsi gelmeli
  --sha       `MERKEZI_SHA=1` kayıtları (gönderilen / alınan görüntü SHA-256'sı) numara bazında karşılaştırılır
  --tc-once/--tc-sonra  tc htb 1:10 'Sent' sayaçları (bayt): araç→yer istasyonu bayt sayısı hesabıyla karşılaştırılır
  --uc-klasoru  aynı rota için uçta mod koşusu: L ve CPU eşlemesi yan yana raporlanır (yalnız rapor)
  --tek-klasoru aynı makinede tek araç merkezi koşusu: ortak her araç için L (ortanca/p95/en çok) farkı raporlanır (yalnız rapor; değer kilitlenmez)
--arac N (N = 1, 2 ya da 3): her ölçüt HER ARAÇ İÇİN ayrı sınanır (`_<araç kimliği>` son ekli SONUC satırları); üç araçta ayrıca kontrol iletilerinin (ScanStart/COMPLETE) alım gecikmesi raporlanır.
Her sonuç "SONUC <gecti|kaldi> <ad> | <ayrıntı>" satırıdır; ardından ölçüm satırları (`OLCUM ...`). Yalnız standart kitaplık (+ swarm_vehicle saf mantık modülleri).
"""
import json
import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uc_mod_analiz import jsonl, log_oku, yuzdelik  # noqa: E402

NS = 10 ** 9
KALDI = 0
TCP_MSS = 65483            # lo MTU 65536 − IP 20 − TCP 32 (zaman damgalı)
IP_TCP_BASLIK = 52


def sonuc(gecti, ad, ayrinti):
    global KALDI
    if not gecti:
        KALDI += 1
    print(f"SONUC {'gecti' if gecti else 'kaldi'} {ad} | {ayrinti}", flush=True)


def durum_gecikmeleri(klasor, kimlikler, t0, t1, gorev):
    """OLCUM (yaklaşık): 2 Hz VehicleState alım gecikmesi, hat boşken (t0 öncesi) ve hat doygunken (t0–t1) ayrı; ScanFinished alım gecikmesi.
    Yöntem: iletinin `yayim_sim_ns` (aracın yayım anındaki sim saati) → Gazebo üretim kayıtlarındaki (`gazebo_damga.jsonl`, sim_damga_ns ↔ mono_ns) doğrusal en küçük kareler eşlemesiyle yayım anı (mono) tahmin edilir;
    gecikme = yer istasyonu alım anı (mono) − tahmini yayım anı. Eşleme yaklaşıktır (üretim kaydının kendi gecikmesi ve doğrusal varsayım dahil); mutlak sapma birkaç ms olabilir. Eşik/iddia yok."""
    ham_yol = os.path.join(klasor, "kayit", "yer_istasyonu_durum_ham.jsonl")
    damga_yol = os.path.join(klasor, "kayit", "gazebo_damga.jsonl")
    if not (os.path.isfile(ham_yol) and os.path.isfile(damga_yol)):
        print("OLCUM durum iletisi gecikmesi: yer_istasyonu_durum_ham.jsonl ya da gazebo_damga.jsonl yok")
        return
    xs, ys = [], []
    for d in isteye_bagli(damga_yol):
        if d.get("olay") == "uretim" and isinstance(d.get("n"), int) and d.get("sim_damga_ns") is not None:
            xs.append(float(d["sim_damga_ns"])); ys.append(float(d["mono_ns"]))
    if len(xs) < 10:
        print(f"OLCUM durum iletisi gecikmesi: sim→mono eşlemesi için yetersiz üretim kaydı ({len(xs)})")
        return
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    egim = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    artik = [abs(my + egim * (x - mx) - y) / 1e6 for x, y in zip(xs, ys)]
    ham = [d for d in isteye_bagli(ham_yol) if d.get("yayim_sim_ns") is not None]
    t0m, t1m = t0["mono_ns"], t1["mono_ns"]
    for k in kimlikler:
        bos, doygun = [], []
        for d in ham:
            if d.get("arac") != k:
                continue
            gec = (d["mono_ns"] - (my + egim * (d["yayim_sim_ns"] - mx))) / 1e6
            if d["mono_ns"] < t0m:
                bos.append(gec)
            elif d["mono_ns"] <= t1m:
                doygun.append(gec)
        for ad, v in (("t0 öncesi (hat boş)", bos), ("t0–t1 (hat doygun)", doygun)):
            print(f"OLCUM araç {k}: durum iletisi (2 Hz) alım gecikmesi, {ad}: {len(v)} ileti" + (f" ortanca {yuzdelik(v, 50):.1f} / p95 {yuzdelik(v, 95):.1f} / en çok {max(v):.1f} ms" if v else "")
                  + " [yaklaşık: yayim_sim_ns → gazebo_damga doğrusal sim→mono eşlemesi]")
    print(f"OLCUM sim→mono eşlemesi: {len(xs)} üretim kaydı, eğim {egim:.6f}, eşleme artığı ortanca {yuzdelik(artik, 50):.2f} / en çok {max(artik):.2f} ms")
    for k in kimlikler:
        alog = log_oku(os.path.join(klasor, f"arac_{k}.log"))
        yay = [x["mono_ns"] for x in alog.get("tarama_bitis_yayimlandi", [])]
        alim = [x["mono_ns"] for x in gorev if x["olay"] == "tarama_bitisi" and x.get("arac_kimligi") == k]
        if len(yay) == 1 and len(alim) == 1:
            print(f"OLCUM araç {k}: ScanFinished alım gecikmesi {(alim[0] - yay[0]) / 1e6:.1f} ms (yayım: araç günlüğü tarama_bitis_yayimlandi; alım: yer istasyonu görev kaydı tarama_bitisi; hat doygunken yayımlanır)")
        else:
            print(f"OLCUM araç {k}: ScanFinished alım gecikmesi hesaplanamadı (yayım kaydı {len(yay)}, alım kaydı {len(alim)})")


def isteye_bagli(yol):
    return jsonl(yol) if os.path.isfile(yol) else []


def ozet_L(klasor, k):
    """L = kullanilabilir − uretim (yalnız `sonuc`/`tespit_yok`): ms listesi."""
    damga = jsonl(os.path.join(klasor, "kayit", "gazebo_damga.jsonl"))
    uretim = {r["n"]: r["mono_ns"] for r in damga if r["arac_kimligi"] == k and r["olay"] == "uretim" and isinstance(r["n"], int)}
    yer = [r for r in jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_kare.jsonl")) if r["arac_kimligi"] == k and r["olay"] == "kullanilabilir"]
    return [(r["mono_ns"] - uretim[r["n"]]) / 1e6 for r in yer if r["sonuc_durumu"] in ("sonuc", "tespit_yok") and r["n"] in uretim]


def cpu_beklenen(ham, k_sira):
    """Uçta modda araç k_sira'nın işçisinin alacağı CPU kümesi (aynı işlev: cikarim_yardimci.cpu_ata)."""
    if ham.get("ISCI_CPU_SABITLE", "0") != "1":
        return [], "sabitleme kapalı"
    from swarm_vehicle import cikarim_yardimci as Y
    kumeler = Y.cpu_cekirdek_kumeleri()
    return Y.cpu_ata(k_sira, kumeler, int(ham["ISCI_MANTIKSAL_CPU"]), izinli=os.sched_getaffinity(0))


def ana(argv):
    a = list(argv)
    if not a:
        print(__doc__, file=sys.stderr)
        return 2
    klasor = a.pop(0)
    n_arac, hata, basinc, sha, tc0, tc1, uc, tek = 0, False, None, False, None, None, None, None
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k == "--hata":
            hata = True
        elif k == "--basinc" and a:
            b, _, s = a.pop(0).partition(":")
            basinc = (float(b), float(s))
        elif k == "--sha":
            sha = True
        elif k == "--tc-once" and a:
            tc0 = int(a.pop(0))
        elif k == "--tc-sonra" and a:
            tc1 = int(a.pop(0))
        elif k == "--uc-klasoru" and a:
            uc = a.pop(0)
        elif k == "--tek-klasoru" and a:
            tek = a.pop(0)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    from swarm_vehicle import goruntu_ileti as gi
    from swarm_vehicle import rota
    ham = rota.deney_env_oku()
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()][:n_arac]
    hz = int(float(ham["CAM_RATE_HZ"]))
    kos = json.load(open(os.path.join(klasor, "kosu.json"), encoding="utf-8"))
    sonuc(kos.get("mimari_modu") == "merkezi", "mimari_modu", f"kosu.json mimari_modu = {kos.get('mimari_modu')!r}")
    glog = log_oku(os.path.join(klasor, "yer_istasyonu.log"))
    kal = rota.kalibrasyon_kimligi_oku()
    kar = isteye_bagli(os.path.join(klasor, "kayit", "yer_istasyonu_kare.jsonl"))
    gorev = isteye_bagli(os.path.join(klasor, "kayit", "yer_istasyonu_gorev.jsonl"))
    olay = lambda ad: [x for x in gorev if x["olay"] == ad]  # noqa: E731
    t0, t1, son_sonuc = (olay("t0") or [None])[0], (olay("t1") or [None])[0], (olay("son_sonuc") or [None])[0]
    sonuc(t0 is not None and t1 is not None and son_sonuc is not None and bool(olay("tamamlandi")), "koordinator_tamam", "t0, son_sonuc, t1 ve tamamlandı kayıtları var" if t1 else "t0/son_sonuc/t1/tamamlandı eksik")
    if t0 is None or t1 is None:
        return 1
    # --- bağlantı ve bariyer ---------------------------------------------------------------------------------------------------------------
    bag = glog.get("merkezi_baglandi", [])
    hazir = glog.get("merkezi_isci_hazir", [])
    sonuc(len(bag) == n_arac and len(hazir) == n_arac, "kanal_ve_isci_hazir", f"yer istasyonu günlüğünde {len(bag)} kanal bağlantısı ve {len(hazir)} hazır işçi (beklenen {n_arac} + {n_arac})")
    sonuc(all(b["mono_ns"] < t0["mono_ns"] for b in bag + hazir) and bool(bag), "bariyer_kanal_isci_sonrasi", "t0, bütün kanallar bağlandıktan ve bütün işçiler hazır olduktan sonra yayımlandı"
          + (f" (son bağlantı t0'dan {(t0['mono_ns'] - max(b['mono_ns'] for b in bag)) / 1e9:.1f} s, son hazır işçi {(t0['mono_ns'] - max(b['mono_ns'] for b in hazir)) / 1e9:.1f} s önce)" if bag and hazir else ""))
    sonuc(len(glog.get("isci_baslatildi", [])) == n_arac and "eslesme_degisti" not in glog, "yer_isci_sayisi", f"yer istasyonunda {len(glog.get('isci_baslatildi', []))} işçi başlatıldı (beklenen {n_arac}); DDS kare sonucu eşleşme günlüğü yok")
    for k in kimlikler:                        # kontrol iletileri (ScanStart, Complete): yayım anından (yer istasyonu t0/t1 kaydı) araç günlüğündeki alım anına; aynı makine, aynı CLOCK_MONOTONIC
        a_ = log_oku(os.path.join(klasor, f"arac_{k}.log"))
        bas = [(x["mono_ns"] - t0["mono_ns"]) / 1e6 for x in a_.get("tarama_baslat_alindi", [])]
        com = [(x["mono_ns"] - t1["mono_ns"]) / 1e6 for x in a_.get("complete_alindi", [])]
        sonuc(len(bas) == 1 and len(com) == 1, f"kontrol_iletileri_{k}", f"araç {k}: ScanStart alımı t0'dan {bas[0]:.1f} ms sonra, COMPLETE alımı t1'den {com[0]:.1f} ms sonra (hat boşken ölçüldü; doygun hat gecikmesi aşağıdaki durum iletisi OLCUM satırlarında)" if len(bas) == 1 and len(com) == 1 else f"araç {k}: ScanStart alım kaydı {len(bas)}, COMPLETE alım kaydı {len(com)} (beklenen 1 + 1)")
    durum_gecikmeleri(klasor, kimlikler, t0, t1, gorev)
    ozet_g = {}
    for kv in glog.get("merkezi_ozet", []):
        for ad, v in kv.items():
            if ad.startswith("arac"):
                ozet_g[int(ad[4:])] = json.loads(v)
    son_sonuc_mono = 0
    tum = {}
    for sira, k in enumerate(kimlikler, 1):
        alog = log_oku(os.path.join(klasor, f"arac_{k}.log"))
        sonuc("merkezi_mod" in alog and "isci_baslatildi" not in alog and "isci_hazir" not in alog and "kare_sonuc" not in alog and "sonuc_yayin_ozet" not in alog
              and not any(x.get("kaynak") == "kare_sonuc" for x in alog.get("eslesme_degisti", [])),
              f"arac_isci_yok_{k}", "araç günlüğünde merkezi_mod var; çıkarım işçisi başlatılmadı, FrameResult yayımı/eşleşmesi yok")
        bit = alog["tarama_bitis_yayimlandi"][0]
        n_ilk, n_son = int(bit["n_first"]), int(bit["n_last"])
        aralik = list(range(n_ilk, n_son + 1))
        oz = alog["merkezi_ozet"][0]
        # gönderilen = alınan = işlenen = sonuç
        gon = [r for r in isteye_bagli(os.path.join(klasor, "kayit", f"arac_sureci_{k}.jsonl")) if r["olay"] == "gonderim"]
        kuy = [r for r in isteye_bagli(os.path.join(klasor, "kayit", f"arac_sureci_{k}.jsonl")) if r["olay"] == "gonderim_kuyrugu"]
        alim = [r for r in kar if r["arac_kimligi"] == k and r["olay"] == "alim"]
        kul = [r for r in kar if r["arac_kimligi"] == k and r["olay"] == "kullanilabilir"]
        sn = {r["n"]: r for r in isteye_bagli(os.path.join(klasor, "kayit", f"kare_sonuc_{k}.jsonl"))}
        sonuc(sorted(r["n"] for r in gon) == aralik and sorted(r["n"] for r in kuy) == aralik and sorted(r["n"] for r in alim) == aralik and sorted(sn) == aralik and sorted(r["n"] for r in kul) == aralik,
              f"sayilar_{k}", f"[{n_ilk}, {n_son}] {len(aralik)} numara: araçta kuyruğa giren {len(kuy)}, gönderilen {len(gon)}; yer istasyonunda alınan {len(alim)}, sonuç {len(sn)}, kullanılabilir {len(kul)}; her numara bir kez")
        durumlar = {}
        for r in kul:
            durumlar[r["sonuc_durumu"]] = durumlar.get(r["sonuc_durumu"], 0) + 1
        uretilen = durumlar.get("sonuc", 0) + durumlar.get("tespit_yok", 0)
        sonuc(uretilen > 0 and sum(durumlar.values()) == len(aralik), f"isci_sonuc_uretti_{k}", f"araç {k}'nin yer istasyonundaki işçisi {uretilen}/{len(aralik)} karede çıkarım sonucu üretti (durumlar {durumlar})")
        o = ozet_g.get(k, {})
        sonuc(o.get("tekrar") == 0 and o.get("geriye") == 0 and o.get("atlanan") == 0 and o.get("kalibrasyon_uyumsuz") == 0 and o.get("hata") is None and o.get("islenen") == len(aralik) and o.get("alinan_ileti") == len(aralik),
              f"alici_dogrulama_{k}", f"tekrar {o.get('tekrar')}, geriye giden {o.get('geriye')}, atlanan {o.get('atlanan')} (aralık dışı alım: 0), kalibrasyon uyuşmazlığı {o.get('kalibrasyon_uyumsuz')}, kanal hatası {o.get('hata')}, işlenen {o.get('islenen')}/{len(aralik)}")
        sonuc(oz["kuyruk_bosaldi"] == "True" and int(oz["gonderilen"]) == len(aralik) and int(oz["uretilen"]) == len(aralik), f"kuyruk_atilan_yok_{k}",
              f"üretilen {oz['uretilen']} (görüntü {oz['goruntu']}, kare alınamadı {oz['kare_alinamadi']}), gönderilen {oz['gonderilen']}, kuyruk boşaldı {oz['kuyruk_bosaldi']}; atılan 0")
        # poz birebir
        kp = {r["n"]: r for r in isteye_bagli(os.path.join(klasor, "kayit", f"kare_poz_{k}.jsonl"))}
        farkli = []
        for n in aralik:
            p, r = sn[n].get("poz"), kp.get(n)
            if p is None or r is None:
                farkli.append((n, "eksik"))
                continue
            for alan in ("gecerli", "neden", "t1_ns", "t2_ns", "konum_ned_m", "q_wxyz"):
                if p[alan] != r[alan]:
                    farkli.append((n, alan))
        sonuc(sorted(kp) == aralik and not farkli, f"poz_birebir_{k}", f"başlıktaki poz (yer istasyonu kare sonucu) ile araçtaki kare_poz kaydı numara bazında birebir ({len(aralik)} numara; farklı {farkli[:4]}); geçerli {sum(1 for r in kp.values() if r['gecerli'])}/{len(kp)}")
        # şema: konum ya [doğu, kuzey] (neden null) ya da null (neden poz_yok | kesisim_yok); birleştirme adayı false (B15)
        tespitler = [(r, t) for r in sn.values() for t in r["tespitler"]]
        tutarli = all(((t["konum"] is None) == (t["konum_neden"] is not None)) and t["aday"] is False for r, t in tespitler)
        sonuc(tutarli, f"konum_alani_{k}", f"tespitlerde konum/konum_neden tutarlı, aday false ({len(tespitler)} tespit; konumlu {sum(1 for r, t in tespitler if t['konum'] is not None)})")
        # kalibrasyon kimliği başlıkta (sayıldı)
        uyusmayan = [x for x in glog.get("merkezi_kalibrasyon_uyusmuyor", []) if str(x.get("arac")) == str(k)]
        sonuc(not uyusmayan and o.get("kalibrasyon_uyumsuz") == 0, f"kalibrasyon_{k}",
              f"yer istasyonu alıcısı her başlıktaki kalibrasyon kimliğini beklenen {kal!r} ile karşılaştırdı: uyuşmazlık günlük satırı {len(uyusmayan)}, özet sayacı {o.get('kalibrasyon_uyumsuz')}")
        # sıra: COMPLETE son sonuçtan sonra
        son_sonuc_mono = max(son_sonuc_mono, max(r["mono_ns"] for r in kul))
        # SHA
        if sha:
            g = {r["n"]: r for r in isteye_bagli(os.path.join(klasor, "kayit", f"merkezi_sha_{k}.jsonl"))}
            al = {r["n"]: r for r in isteye_bagli(os.path.join(klasor, "kayit", f"merkezi_sha_alim_{k}.jsonl"))}
            uyusmayan = [n for n in g if n not in al or al[n]["sha256"] != g[n]["sha256"] or al[n]["bayt"] != g[n]["bayt"]]
            sonuc(len(g) > 0 and not uyusmayan and sorted(g) == sorted(al), f"sha_{k}", f"gönderilen {len(g)} ve alınan {len(al)} görüntü baytının SHA-256'sı numara bazında aynı (hepsi karşılaştırıldı; uyuşmayan {uyusmayan[:4]}; bayt {next(iter(g.values()))['bayt'] if g else '-'})")
        # durumlar
        say = {}
        for r in kul:
            say[r["sonuc_durumu"]] = say.get(r["sonuc_durumu"], 0) + 1
        print(f"OLCUM araç {k}: yer istasyonu durumları {say}")
        # L
        L = ozet_L(klasor, k)
        tum[k] = L
        sonuc(bool(L) and min(L) > 0, f"L_{k}", f"L = kullanilabilir − uretim (merkezi): {len(L)} kare, ortanca {yuzdelik(L, 50):.1f} ms, p95 {yuzdelik(L, 95):.1f} ms, en çok {max(L):.1f} ms, en az {min(L):.1f} ms")
        if tek:
            Lt = ozet_L(tek, k)
            print(f"OLCUM L tek araç merkezi koşuyla (araç {k}): bu koşu {len(L)} kare ortanca {yuzdelik(L, 50):.1f} / p95 {yuzdelik(L, 95):.1f} / en çok {max(L):.1f} ms; tek araç koşusu {len(Lt)} kare ortanca {yuzdelik(Lt, 50):.1f} / p95 {yuzdelik(Lt, 95):.1f} / en çok {max(Lt):.1f} ms; fark ortanca {yuzdelik(L, 50) - yuzdelik(Lt, 50):+.1f} / p95 {yuzdelik(L, 95) - yuzdelik(Lt, 95):+.1f} ms" if Lt else f"OLCUM tek araç merkezi koşusunda araç {k} için L yok")
        if uc:
            Lu = ozet_L(uc, k)
            print(f"OLCUM L yan yana (araç {k}): merkezi {len(L)} kare ortanca {yuzdelik(L, 50):.1f} / p95 {yuzdelik(L, 95):.1f} / en çok {max(L):.1f} ms; uçta {len(Lu)} kare ortanca {yuzdelik(Lu, 50):.1f} / p95 {yuzdelik(Lu, 95):.1f} / en çok {max(Lu):.1f} ms" if Lu else "OLCUM uçta mod L yok")
        # CPU eşlemesi
        beklenen, aciklama = cpu_beklenen(ham, sira)
        h = next((x for x in hazir if int(x.get("arac", -1)) == k), None)
        cpu_g = [int(c) for c in h["cpu"].split(",")] if h and h.get("cpu") else []
        sonuc(cpu_g == beklenen, f"cpu_kumesi_{k}", f"yer istasyonundaki işçi {k} CPU {cpu_g}; uçta modda araç {k} işçisinin alacağı (cpu_ata({sira}, …)) {beklenen} ({aciklama})")
        if uc:
            ualog = log_oku(os.path.join(uc, f"arac_{k}.log"))
            ucpu = ualog.get("isci_hazir", [{}])[0].get("cpu", "-")
            print(f"OLCUM CPU: uçta modda araç {k} işçisi {ucpu}; merkezi modda yer istasyonu işçisi {','.join(map(str, cpu_g))}")
        # üretim hızı, kuyruk
        print(f"OLCUM üretim: gerçek üretim hızı {oz['gercek_uretim_hz']} kare/sn (gz geri çağrıları, duvar saati); kare sayısı {oz['uretilen']}; kamera iç kuyruğu en çok {oz['kamera_kuyruk_maks']}; gönderim kuyruğu en çok {oz['kuyruk_maks_ileti']} ileti / {oz['kuyruk_maks_bayt']} bayt")
        kd = isteye_bagli(os.path.join(klasor, "kayit", f"gonderim_kuyrugu_{k}.jsonl"))
        if kd:
            m = max(r["ileti"] for r in kd)
            zaman = ", ".join(f"{(r['mono_ns'] - kd[0]['mono_ns']) / 1e9:.0f}s:{r['ileti']}" for r in kd[::max(1, len(kd) // 12)])
            print(f"OLCUM kuyruk_durumu {len(kd)} kayıt; en çok {m} ileti ({max(r['bayt'] for r in kd)} bayt); çizelge (sn:ileti) {zaman}")
        ik_ = isteye_bagli(os.path.join(klasor, "kayit", f"isleme_kuyrugu_{k}.jsonl"))
        if ik_:
            zaman_ = ", ".join(f"{(r['mono_ns'] - ik_[0]['mono_ns']) / 1e9:.0f}s:{r['ileti']}" for r in ik_[::max(1, len(ik_) // 12)])
            print(f"OLCUM isleme_kuyrugu {len(ik_)} kayıt (yer istasyonu); en çok {max(r['ileti'] for r in ik_)} ileti; çizelge (sn:ileti) {zaman_}")
            sonuc(ik_[-1]["giren_ileti"] == ik_[-1]["islenen_ileti"] == int(oz["uretilen"]) and ik_[-1]["ileti"] == 0, f"isleme_kuyrugu_son_{k}",
                  f"işleme kuyruğu son kaydı: giren {ik_[-1]['giren_ileti']} = işlenen {ik_[-1]['islenen_ileti']} = üretilen {oz['uretilen']}, bekleyen {ik_[-1]['ileti']}")
        else:
            sonuc(False, f"isleme_kuyrugu_var_{k}", "yer istasyonunda işleme kuyruğu kaydı (kayit/isleme_kuyrugu_<araç>.jsonl) yok")
        if hata and k == kimlikler[0]:
            beklenen_h = {n_ilk + 20: "kare_alinamadi", n_ilk + 40: "islem_hatasi"}
            gercek = {r["n"]: r["sonuc_durumu"] for r in kul if r["sonuc_durumu"] in ("kare_alinamadi", "islem_hatasi")}
            sonuc(gercek == beklenen_h, "hata_durumlari", f"yer istasyonunda yalnız {beklenen_h} (STATUS_FRAME_NOT_RECEIVED / STATUS_PROCESSING_ERROR) beklenir; bulunan {gercek}; ikisi de 'tespit_yok' sayılmadı")
            # kare alınamadı iletisi: yük 0, aynı kuyrukta sıra korunmuş (alım sırası numara sırası, gönderim sırası numara sırası)
            n_k = n_ilk + 20
            sonuc([r["n"] for r in sorted(alim, key=lambda r: r["mono_ns"])] == aralik and [r["n"] for r in sorted(gon, key=lambda r: r["mono_ns"])] == aralik,
                  "kare_alinamadi_sirasi", f"kare alınamadı iletisi (n={n_k}) görüntü iletileriyle aynı kuyrukta: gönderim ve alım sırası numara sırasıyla aynı")
            sonuc(sn[n_k]["tespitler"] == [] and sn[n_k]["durum"] == "kare_alinamadi" and sn[n_k]["poz"] is not None, "kare_alinamadi_poz", f"n={n_k}: sonuç kare_alinamadi, tespit yok, başlıkta poz alanı var (geçerli={sn[n_k]['poz']['gecerli']})")
            ik = sn[n_ilk + 40]
            sonuc(ik["durum"] == "islem_hatasi" and ik["tespitler"] == [] and bool(ik["hata"]), "isci_hatasi_sonuc", f"n={n_ilk + 40}: işçi hatası islem_hatasi olarak sonuçlandı ('tespit yok' değil): {ik['hata']}")
        if basinc:
            bas, sure = basinc
            dur = glog.get("merkezi_okuma_durdu", [])
            sur = glog.get("merkezi_okuma_surdu", [])
            sonuc(bool(dur) and bool(sur), f"okuma_durdu_{k}", f"alıcı okumayı durdurdu ({len(dur)} kez) ve sürdürdü ({len(sur)} kez); pencere {bas:g}+{sure:g} sn")
            if kd:
                m = max(r["ileti"] for r in kd)
                sonuc(m >= 3, f"kuyruk_buyudu_{k}", f"gönderim kuyruğu geri basınçla büyüdü: en çok {m} ileti ({max(r['bayt'] for r in kd) / 1e6:.1f} MB); gönderici bekledi, atılan 0")
    # --- sıra ---------------------------------------------------------------------------------------------------------------------------
    sonuc(son_sonuc_mono <= t1["mono_ns"] and bool(son_sonuc) and son_sonuc["mono_ns"] <= t1["mono_ns"], "complete_son_sonuctan_sonra", f"COMPLETE son sonuçtan {(t1['mono_ns'] - son_sonuc_mono) / 1e6:.1f} ms sonra (t0 → t1 {(t1['mono_ns'] - t0['mono_ns']) / 1e9:.1f} s)")
    for k in kimlikler:
        r = [x for x in olay("tarama_bitisi") if x["arac_kimligi"] == k]
        sonuc(bool(r) and t0["mono_ns"] < r[0]["mono_ns"] < t1["mono_ns"], f"sira_{k}", "t0 → tarama bitişi → t1")
    # --- tc -----------------------------------------------------------------------------------------------------------------------------
    if tc0 is not None and tc1 is not None:
        toplam_uyg = 0
        goruntu_sayi = kare_sayi = 0
        for k in kimlikler:
            kd = isteye_bagli(os.path.join(klasor, "kayit", f"gonderim_kuyrugu_{k}.jsonl"))
            toplam_uyg += kd[-1]["gonderilen_bayt"] if kd else 0
            alog = log_oku(os.path.join(klasor, f"arac_{k}.log"))["merkezi_ozet"][0]
            goruntu_sayi += int(alog["goruntu"])
            kare_sayi += int(alog["kare_alinamadi"])
        baslik = gi.baslik_boyutu(kal)
        beklenen_uyg = goruntu_sayi * (baslik + int(ham["CAM_WIDTH"]) * int(ham["CAM_HEIGHT"]) * 3) + kare_sayi * baslik
        segment = math.ceil(toplam_uyg / TCP_MSS)
        beklenen_tc = toplam_uyg + 2 * IP_TCP_BASLIK * segment            # veri + (en çok) her segment için bir onay
        olculen = tc1 - tc0
        print(f"OLCUM tc htb 1:10: ölçülen {olculen} bayt; uygulama baytı {toplam_uyg} = {goruntu_sayi} görüntü × ({baslik} başlık + 921600) + {kare_sayi} kare alınamadı × {baslik}; TCP/IP ek yükü ≈ {IP_TCP_BASLIK} bayt × {segment} segment (+ onaylar) → beklenen ≈ {beklenen_tc}")
        sonuc(toplam_uyg == beklenen_uyg, "tc_uygulama_baytlari", f"araç kuyruğundan gönderilen bayt {toplam_uyg} = ileti sayısı × (başlık + 921 600) (+ kare alınamadı başlıkları) = {beklenen_uyg}")
        sonuc(toplam_uyg <= olculen <= 1.05 * beklenen_tc, "tc_sinif_sayaci", f"tc sınıf sayacı {olculen} bayt: uygulama baytından fazla ({olculen / toplam_uyg:.4f} ×) ve TCP/IP ek yükü + onaylar payıyla (≤ 1,05 × {beklenen_tc}) uyumlu; ROS 2 DDS kontrol trafiği dahil")
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
