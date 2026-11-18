#!/usr/bin/env python3
"""Çıkarım işçisinin tek başına denemesi (simülasyonsuz; YALNIZ test): gerçek bir alt süreç işçisini GPU ve ONNX Runtime CPU arka uçlarıyla sınar.

Kullanım:  python araclar/cikarim_isci_deneme.py [--tekrar 60] [--cpu-yolu]
Görüntüler: `ultralytics` paketinin assets/bus.jpg ve zidane.jpg dosyaları 640×480'e uyarlanmış RGB8; düz gri görüntü; bozuk boyutlu görüntü.
Denetimler (her biri "SONUC <gecti|kaldi> <ad> | <ayrıntı>"; kaldı varsa çıkış 1):
  - GPU arka ucu: person tespitleri → kare sonucu `tespit` (insan); düz gri → `tespit_yok`; bozuk boyut → `islem_hatasi` ("tespit yok" değil)
  - nms=False uçtan uca başlık kanıtı (başlık end2end, ham çıktı [1, 300, 6], kare başına NMS çağrısı 0), çevrimdışı mod
  - kanal IP kullanmıyor (işçi sürecinin soketleri yalnız AF_UNIX), işçide rclpy yüklü değil, CPU sabitlemesi uygulanmış (sched_getaffinity)
  - ısınma süresi, kare başına çıkarım süresi (ortanca, p99), GPU belleği (NVML süreç belleği ve torch), `cikarim_basi`/`cikarim_sonu` kayıtları (sonu ≥ basi)
  - ORT CPU arka ucu (--cpu-yolu): aynı görüntülerde aynı sonuç YAPISI (anahtarlar, türler, durumlar); sayılar farklı olabilir
Geçici klasör kullanır (koşu klasörü gerekmez); sonda siler.
"""
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(KOK, "src", "swarm_vehicle")
sys.path.insert(0, PKG)
os.environ["PYTHONPATH"] = PKG + os.pathsep + os.environ.get("PYTHONPATH", "")

KALDI = 0


def sonuc(gecti, ad, ayrinti):
    global KALDI
    if not gecti:
        KALDI += 1
    print(f"SONUC {'gecti' if gecti else 'kaldi'} {ad} | {ayrinti}", flush=True)


def olcum(ad, ayrinti):
    """Ölçüm/bilgi satırı: geçti/kaldı sayılmaz (test betikleri bilgi olarak yazar)."""
    print(f"OLCUM {ad} | {ayrinti}", flush=True)


def yuzde(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(math.ceil(p / 100 * len(v))) - 1)] if v else float("nan")


def soket_turleri(pid):
    inode = set()
    for ad in os.listdir(f"/proc/{pid}/fd"):
        try:
            m = re.fullmatch(r"socket:\[(\d+)\]", os.readlink(f"/proc/{pid}/fd/{ad}"))
        except OSError:
            continue
        if m:
            inode.add(m.group(1))
    turler = {}
    for tur in ("unix", "tcp", "udp", "tcp6", "udp6", "raw", "raw6", "packet", "netlink"):
        try:
            with open(f"/proc/net/{tur}", encoding="utf-8") as f:
                satirlar = f.read().splitlines()[1:]
        except OSError:
            continue
        for s in satirlar:
            p = s.split()
            ino = p[6] if tur == "unix" else (p[9] if len(p) > 9 else None)
            if ino in inode:
                turler[tur] = turler.get(tur, 0) + 1
    return len(inode), turler


def yapi(yanit):
    """Sonuç YAPISI: anahtar → tür adı (içiçe listeler için ilk öğe) — iki arka ucun aynı yapıyı döndürdüğünü karşılaştırmak için."""
    def tur(v):
        if isinstance(v, dict):
            return {k: tur(x) for k, x in sorted(v.items())}
        if isinstance(v, list):
            return [tur(v[0])] if v else []
        return type(v).__name__
    return tur(yanit)


def goruntuler():
    import numpy as np
    import ultralytics
    from PIL import Image
    varlik = os.path.join(os.path.dirname(ultralytics.__file__), "assets")
    w, h = int(HAM["CAM_WIDTH"]), int(HAM["CAM_HEIGHT"])
    d = {}
    for ad in ("bus", "zidane"):
        d[ad] = np.array(Image.open(os.path.join(varlik, f"{ad}.jpg")).convert("RGB").resize((w, h))).tobytes()
    d["gri"] = bytes([114]) * (w * h * 3)
    return d


def bir_arka_uc(arka, klasor, goruntu, tekrar, cpu_sabitle):
    from swarm_vehicle.cikarim import cikarim_istemci as ci
    from swarm_vehicle.cikarim import cikarim_yardimci as Y
    from swarm_vehicle.cikarim import kare_sonuc as ks
    w, h = int(HAM["CAM_WIDTH"]), int(HAM["CAM_HEIGHT"])
    ham = dict(HAM, ISCI_CPU_SABITLE="1" if cpu_sabitle else "0", ISCI_KAYNAK_SN="0.5")
    gunluk = []
    ist = ci.IsciIstemcisi(ham, 1, int(HAM["UAV_SYS_IDS"].split()[0]), klasor, lambda o, **v: gunluk.append((o, v)), arka_uc=arka, enjeksiyon_metni="")
    es = Y.SinifEsleme.yapilandirmadan(HAM)
    t0 = time.monotonic()
    ist.baslat()
    b = ist.hazir_bekle()
    if b is None:
        sonuc(False, f"{arka}_hazir", f"işçi hazır olmadı: {ist.kalici_hata}")
        ist.kapat()
        return None
    olcum(f"{arka}_hazir", f"işçi hazır: pid {b['pid']}, model {b['model']}, cihaz {b['cihaz']}, yükleme {b['yukleme_s']} sn, ısınma {b['isinma_s']} sn ({len(b['isinma_ms'])} çıkarım: "
          f"{', '.join(str(x) for x in b['isinma_ms'])} ms), toplam {time.monotonic() - t0:.1f} sn; çevrimdışı={b['cevrimdisi']}")
    sonuc(b["rclpy_yuklu"] is False, f"{arka}_rclpy_yok", f"işçide rclpy yüklü değil (rclpy_yuklu={b['rclpy_yuklu']})")
    sonuc(b["uc_uca"] != {}, f"{arka}_uc_uca", f"nms=False uçtan uca kanıtı: {json.dumps(b['uc_uca'])}")
    pid = b["pid"]
    n_soket, turler = soket_turleri(pid)
    sonuc(n_soket > 0 and set(turler) == {"unix"}, f"{arka}_kanal_ip_yok", f"işçi sürecinin {n_soket} soketi var, türleri: {turler} (yalnız AF_UNIX beklenir; TCP/UDP yok)")
    if cpu_sabitle:
        gercek = sorted(os.sched_getaffinity(pid))
        sonuc(gercek == sorted(b["cpu"]) and len(gercek) == int(HAM["ISCI_MANTIKSAL_CPU"]), f"{arka}_cpu_sabit", f"işçi CPU kümesi (sched_getaffinity) {gercek} = bildirilen {b['cpu']}; eşleme günlüğü: {dict(gunluk[0][1])['cpu_eslemesi']}")
    kayitlar = {}
    sureler = {}
    sira = 0
    for ad, veri in goruntu.items():
        sureler[ad] = []
        for i in range(tekrar):
            n = 20 + sira
            sira += 1
            y = ist.isle(n, n * 10 ** 9 // 2, veri, w, h)
            if i == 0:
                kayitlar[ad] = y
            if y.get("durum") == "tamam":
                sureler[ad].append((y["sonu_ns"] - y["basi_ns"]) / 1e6)
    # --- üç sonuç türü ---------------------------------------------------------------------------------------------------------------
    durumlar = {}
    for ad in ("bus", "zidane", "gri"):
        d, t, atilan, hata = ks.durum_belirle(kayitlar[ad], es)
        durumlar[ad] = (d, t, atilan, hata)
    for ad in ("bus", "zidane"):
        d, t, atilan, _ = durumlar[ad]
        ham_person = [x for x in kayitlar[ad]["tespitler"] if x["sinif_adi"] == "person"]
        if arka == "gpu":
            sonuc(d == ks.TESPIT and all(x["sinif"] == "insan" for x in t) and len(t) == len(ham_person) >= 1, f"{arka}_{ad}_insan",
                  f"{ad}.jpg: durum {d}, insan tespiti {len(t)} (güven {[round(x['guven'], 2) for x in t]}); proje dışı sınıf atılan {atilan}; kutu örneği {[round(v, 1) for v in t[0]['kutu']] if t else None}")
        else:
            sonuc(d in (ks.TESPIT, ks.TESPIT_YOK), f"{arka}_{ad}_durum", f"{ad}.jpg: durum {d}, insan tespiti {len(t)}")
    d, t, atilan, hata = durumlar["gri"]
    sonuc(d == ks.TESPIT_YOK and not t and hata is None, f"{arka}_gri_tespit_yok", f"düz gri görüntü: durum {d} (açık 'tespit yok', işçi hatası yok), ham tespit sayısı {len(kayitlar['gri']['tespitler'])}")
    yb = ist.isle(900, 900 * 10 ** 9 // 2, bytes(1234), w, h)
    db = ks.durum_belirle(yb, es)
    sonuc(db[0] == ks.ISLEM_HATASI and db[1] == [] and db[0] != ks.TESPIT_YOK and db[3], f"{arka}_bozuk_islem_hatasi", f"bozuk boyutlu görüntü (1234 bayt): durum {db[0]}, boş tespit listesine rağmen 'tespit yok' DEĞİL; hata: {db[3]}")
    yb2 = ist.isle(901, 901 * 10 ** 9 // 2, bytes(64 * 48 * 3), 64, 48)
    sonuc(ks.durum_belirle(yb2, es)[0] == ks.ISLEM_HATASI, f"{arka}_bozuk_boyut2", f"yanlış çözünürlük (64×48): durum {ks.durum_belirle(yb2, es)[0]}")
    sonuc(ist.isle(902, 902 * 10 ** 9 // 2, goruntu["gri"], w, h)["durum"] == "tamam", f"{arka}_hata_sonrasi_calisir", "bozuk görüntüden sonra işçi yaşıyor ve sonraki kareyi işliyor")
    # --- süreler -----------------------------------------------------------------------------------------------------------------------
    tum = [x for v in sureler.values() for x in v]
    sonuc(len(tum) == tekrar * len(goruntu) and all(x > 0 for x in tum), f"{arka}_cikarim_suresi",
          f"kare başına çıkarım süresi (cikarim_basi→cikarim_sonu, ms; {len(tum)} kare): ortanca {yuzde(tum, 50):.2f}, p99 {yuzde(tum, 99):.2f}, en çok {max(tum):.2f}, en az {min(tum):.2f}; "
          + "; ".join(f"{ad}: ortanca {yuzde(v, 50):.2f}" for ad, v in sureler.items()))
    if arka == "gpu":
        ist.kapat()
        kayit = os.path.join(klasor, "kayit", f"isci_kaynak_{int(HAM['UAV_SYS_IDS'].split()[0])}.jsonl")
        with open(kayit, encoding="utf-8") as f:
            k = [json.loads(s) for s in f if s.strip()]
        bel = [x["gpu_bellek_mib"] for x in k if x["gpu_bellek_mib"] is not None]
        kul = [x["gpu_kullanim_yuzde"] for x in k if x["gpu_kullanim_yuzde"] is not None]
        with open(os.path.join(klasor, f"cikarim_isci_{int(HAM['UAV_SYS_IDS'].split()[0])}.log"), encoding="utf-8") as f:
            kap = [s for s in f.read().splitlines() if s.startswith("ISCI kapanis")]
        sonuc(bool(bel) and bool(kul) and len(k) >= 2, "gpu_kaynak_kaydi",
              f"{len(k)} periyodik kaynak kaydı: GPU belleği (NVML süreç) en çok {max(bel):.0f} MiB, GPU kullanımı (SM %) en çok {max(kul)}, ana bellek RSS en çok {max(x['ana_bellek_rss_mib'] for x in k):.0f} MiB; işçi kapanışı: {kap[-1] if kap else '-'}")
    else:
        ist.kapat()
    # --- kare olayları ------------------------------------------------------------------------------------------------------------------
    yol = os.path.join(klasor, "kayit", f"cikarim_iscisi_{int(HAM['UAV_SYS_IDS'].split()[0])}.jsonl")
    with open(yol, encoding="utf-8") as f:
        olaylar = [json.loads(s) for s in f if s.strip()]
    basi = {r["n"]: r["mono_ns"] for r in olaylar if r["olay"] == "cikarim_basi"}
    sonu = {r["n"]: r["mono_ns"] for r in olaylar if r["olay"] == "cikarim_sonu"}
    sonuc(basi.keys() == sonu.keys() and all(sonu[n] >= basi[n] for n in basi) and len(basi) >= tekrar * len(goruntu), f"{arka}_kare_olaylari",
          f"{len(basi)} karede cikarim_basi ve cikarim_sonu var, hepsinde sonu ≥ basi (en küçük fark {min(sonu[n] - basi[n] for n in basi) / 1e6:.2f} ms)")
    return {"yapi": {ad: yapi(kayitlar[ad]) for ad in ("bus", "gri")}, "yapi_bozuk": yapi(yb), "durumlar": {ad: durumlar[ad][0] for ad in durumlar}, "durum_bozuk": db[0]}


def ana(argv):
    global HAM
    tekrar, cpu_yolu = 60, False
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--tekrar" and a:
            tekrar = int(a.pop(0))
        elif k == "--cpu-yolu":
            cpu_yolu = True
        else:
            print(__doc__, file=sys.stderr)
            return 2
    from swarm_vehicle.ucus import rota
    HAM = rota.deney_env_oku()
    tmp = tempfile.mkdtemp(prefix="cikarim_isci_deneme_")
    try:
        gr = goruntuler()
        os.makedirs(os.path.join(tmp, "kayit"))
        gpu = bir_arka_uc("gpu", tmp, gr, tekrar, True)
        if cpu_yolu:
            tmp2 = tempfile.mkdtemp(prefix="cikarim_isci_deneme_cpu_")
            try:
                os.makedirs(os.path.join(tmp2, "kayit"))
                cpu = bir_arka_uc("cpu", tmp2, gr, max(5, tekrar // 6), True)
            finally:
                shutil.rmtree(tmp2, ignore_errors=True)
            if gpu and cpu:
                sonuc(gpu["yapi"] == cpu["yapi"] and gpu["yapi_bozuk"] == cpu["yapi_bozuk"], "iki_yol_ayni_yapi",
                      f"GPU ve ORT CPU arka uçları aynı sonuç yapısını döndürüyor (alanlar/türler): {json.dumps(gpu['yapi']['bus'], ensure_ascii=False)}")
                sonuc(gpu["durumlar"]["gri"] == cpu["durumlar"]["gri"] == "tespit_yok" and gpu["durum_bozuk"] == cpu["durum_bozuk"] == "islem_hatasi", "iki_yol_ayni_durumlar",
                      f"düz gri: GPU {gpu['durumlar']['gri']} / CPU {cpu['durumlar']['gri']}; bozuk görüntü: GPU {gpu['durum_bozuk']} / CPU {cpu['durum_bozuk']}; bus: GPU {gpu['durumlar']['bus']} / CPU {cpu['durumlar']['bus']}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"ISCI_DENEME bitti: {'tamam' if KALDI == 0 else str(KALDI) + ' denetim kaldı'}", flush=True)
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
