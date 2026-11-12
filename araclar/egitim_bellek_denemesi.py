#!/usr/bin/env python3
"""Eğitim bellek denemesi (K13): kısa eğitim koşusu; GPU belleği, hız ve eğitim içi doğrulamanın NMS durumu ölçülür.

Kullanım: egitim_bellek_denemesi.py <veri_yaml> <cikti_klasoru> <ad> <batch> <amp:true|false> <epoch> <cikti.json>
Ortam: TRAIN_MODEL, TRAIN_IMGSZ, TRAIN_SAVE_PERIOD, TRAIN_NMS, TRAIN_PAY_YUZDE, TRAIN_WORKERS_MAX, ROOT_DIR/.generated/hardware.env.
Doğruluk sonucu üretilmez/yorumlanmaz; yalnız bellek, hız ve davranış kaydedilir.
Gizlilik: süreç YOLO_OFFLINE=1 ile çalıştırılır (Ultralytics anonim olay göndermez); bu betik bunu doğrular ve ağ bağlantılarını kaydeder.
"""
import json
import os
import subprocess
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("YOLO_OFFLINE", "1")


def nvsmi(sorgu, uygulama=False):
    ana = "--query-compute-apps=" if uygulama else "--query-gpu="
    return subprocess.run(["nvidia-smi", ana + sorgu, "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout.strip()


def calisma_isci(maks):
    """DataLoader işçi sayısı: üst sınır ile fiziksel çekirdek sayısının küçüğü (çalışma anında .generated/hardware.env'den)."""
    kok = os.environ.get("ROOT_DIR", os.getcwd())
    cek = None
    try:
        for ln in open(os.path.join(kok, ".generated", "hardware.env"), encoding="utf-8"):
            if ln.startswith("HW_CPU_PHYSICAL_CORES="):
                cek = int(ln.split("=", 1)[1].strip().strip('"'))
    except OSError:
        pass
    return min(maks, cek) if cek else min(maks, os.cpu_count() or 1)


def main():
    if len(sys.argv) != 8:
        print(__doc__, file=sys.stderr)
        return 2
    veri, proje, ad, batch, amp, epoch, cikti = sys.argv[1:]
    batch, epoch = int(batch), int(epoch)
    amp = amp.lower() == "true"
    e = os.environ
    import psutil
    import torch
    import ultralytics.utils as U
    from ultralytics import YOLO
    from ultralytics.utils.events import events

    sonuc = {"ad": ad, "batch": batch, "amp": amp, "epoch": epoch, "yolo_offline": e.get("YOLO_OFFLINE"), "ONLINE": bool(U.ONLINE),
             "olay_gonderimi_aktif": bool(events.enabled), "ultralytics_sync_ayari": bool(U.SETTINGS["sync"]),
             "toplam_vram_mib": float(nvsmi("memory.total")), "baslangic_bellek_mib": float(nvsmi("memory.used")), "epochlar": [],
             "dogrulama": {}, "uzak_baglantilar": [], "oom": False, "hata": None}
    print(f"EGITIM {ad}: YOLO_OFFLINE={e.get('YOLO_OFFLINE')} ONLINE={U.ONLINE} olay_gonderimi_aktif={events.enabled} sync={U.SETTINGS['sync']}", flush=True)
    if events.enabled or U.ONLINE:
        print(f"EGITIM {ad}: UYARI olay gönderimi aktif görünüyor; durduruluyor", flush=True)
        json.dump(sonuc | {"hata": "olay gönderimi aktif"}, open(cikti, "w"), indent=1)
        return 3

    pid = os.getpid()
    dur = threading.Event()
    uzak = set()

    def izle():
        proc = psutil.Process(pid)
        tepe_surec = 0.0
        while not dur.is_set():
            try:
                for ln in nvsmi("pid,used_memory", uygulama=True).splitlines():
                    p, m = ln.split(",")
                    if int(p) == pid:
                        tepe_surec = max(tepe_surec, float(m))
                sonuc["nvidia_smi_surec_tepe_mib"] = tepe_surec
                for pr in [proc] + proc.children(recursive=True):
                    for c in pr.net_connections(kind="inet"):
                        if c.raddr and c.raddr.ip not in ("127.0.0.1", "::1") and c.status not in ("LISTEN",):
                            uzak.add(f"{c.raddr.ip}:{c.raddr.port}")
            except Exception:
                pass
            time.sleep(0.5)
    th = threading.Thread(target=izle, daemon=True)
    th.start()

    durum = {"t0": 0.0, "isleme": []}

    def ep_basla(tr):
        torch.cuda.reset_peak_memory_stats()
        durum["t0"] = time.monotonic()

    def ep_son(tr):
        durum.setdefault("e", {})
        durum["e"] = {"epoch": tr.epoch + 1, "egitim_suresi_s": time.monotonic() - durum["t0"], "nb": len(tr.train_loader),
                      "egitim_tepe_ayrilan_mib": torch.cuda.max_memory_allocated() / 2**20,
                      "egitim_tepe_ayrilmis_mib": torch.cuda.max_memory_reserved() / 2**20}
        durum["e"]["iter_s"] = durum["e"]["nb"] / durum["e"]["egitim_suresi_s"]

    def fit_son(tr):
        d = durum.get("e", {})
        d["epoch_toplam_s"] = time.monotonic() - durum["t0"]
        d["epoch_sonu_tepe_ayrilan_mib"] = torch.cuda.max_memory_allocated() / 2**20
        d["epoch_sonu_tepe_ayrilmis_mib"] = torch.cuda.max_memory_reserved() / 2**20
        d = dict(d)
        for i, x in enumerate(sonuc["epochlar"]):
            if x["epoch"] == d["epoch"]:      # nihai doğrulamada aynı epoch için ikinci çağrı: tepe değerleri büyüğüyle birleştir
                for k in ("epoch_sonu_tepe_ayrilan_mib", "epoch_sonu_tepe_ayrilmis_mib"):
                    d[k] = max(d[k], x[k])
                sonuc["epochlar"][i] = d
                return
        sonuc["epochlar"].append(d)

    def val_basla(v):
        if sonuc["dogrulama"]:
            return
        m = getattr(v, "model", None)
        sonuc["dogrulama"] = {"validator_args_nms": v.args.nms, "validator_end2end": bool(getattr(v, "end2end", False)),
                              "model_end2end": getattr(m, "end2end", None), "sinif": type(v).__name__, "postprocess_girdi_sekilleri": []}
        orijinal = v.postprocess

        def sekil(x):
            if hasattr(x, "shape"):
                return tuple(x.shape)
            if isinstance(x, dict):
                return {k: sekil(v) for k, v in x.items()}
            if isinstance(x, (list, tuple)):
                return [sekil(v) for v in x]
            return type(x).__name__

        def sar(preds):
            if len(sonuc["dogrulama"]["postprocess_girdi_sekilleri"]) < 2:
                sonuc["dogrulama"]["postprocess_girdi_sekilleri"].append(sekil(preds))
                sonuc["dogrulama"]["postprocess_sirasinda_validator_end2end"] = bool(getattr(v, "end2end", False))
            return orijinal(preds)
        v.postprocess = sar        # ölçüm sarmalayıcısı (Ultralytics kodu değişmez)

    model = YOLO(os.path.join(os.environ.get("ROOT_DIR", "."), e["TRAIN_MODEL"]) if not os.path.isabs(e["TRAIN_MODEL"]) else e["TRAIN_MODEL"])
    model.add_callback("on_train_epoch_start", ep_basla)
    model.add_callback("on_train_epoch_end", ep_son)
    model.add_callback("on_fit_epoch_end", fit_son)
    model.add_callback("on_val_start", val_basla)
    isci = calisma_isci(int(e["TRAIN_WORKERS_MAX"]))
    sonuc["workers"] = isci
    kw = dict(data=veri, epochs=epoch, imgsz=int(e["TRAIN_IMGSZ"]), batch=batch, save=True, save_period=int(e["TRAIN_SAVE_PERIOD"]),
              workers=isci, device=0, project=proje, name=ad, exist_ok=True, plots=False, val=True)
    if e["TRAIN_NMS"] in ("True", "False"):
        kw["nms"] = e["TRAIN_NMS"] == "True"        # "None": argüman verilmez (Ultralytics varsayılanı; karşılaştırma için)
    if not amp:
        kw["amp"] = False
    sonuc["egitim_argumanlari"] = {k: v for k, v in kw.items() if k not in ("data", "project", "name")} | {"amp": kw.get("amp", "varsayılan (True)")}
    t0 = time.monotonic()
    try:
        model.train(**kw)
    except torch.cuda.OutOfMemoryError as ex:
        sonuc["oom"] = True
        sonuc["hata"] = f"CUDA OOM: {str(ex)[:200]}"
    except RuntimeError as ex:
        sonuc["oom"] = "out of memory" in str(ex).lower()
        sonuc["hata"] = f"{type(ex).__name__}: {str(ex)[:300]}"
    sonuc["toplam_sure_s"] = time.monotonic() - t0
    time.sleep(1.0)
    dur.set()
    th.join(3)
    sonuc["uzak_baglantilar"] = sorted(uzak)
    if sonuc["epochlar"]:
        sonuc["tepe_ayrilan_mib"] = max(x["epoch_sonu_tepe_ayrilan_mib"] for x in sonuc["epochlar"])
        sonuc["tepe_ayrilmis_mib"] = max(x["epoch_sonu_tepe_ayrilmis_mib"] for x in sonuc["epochlar"])
        kalan = sonuc["toplam_vram_mib"] - sonuc["baslangic_bellek_mib"]
        pay = float(e["TRAIN_PAY_YUZDE"])
        sonuc["kalan_vram_mib"] = kalan
        sonuc["sigma_reserved"] = sonuc["tepe_ayrilmis_mib"] <= kalan * (1 - pay / 100)
        sonuc["sigma_nvidia_smi"] = sonuc.get("nvidia_smi_surec_tepe_mib", 1e18) <= kalan * (1 - pay / 100)
    json.dump(sonuc, open(cikti, "w"), indent=1, default=str)
    s = sonuc
    print(f"EGITIM {ad}: batch={batch} amp={amp} epoch={len(s['epochlar'])}/{epoch} oom={s['oom']} hata={s['hata']}", flush=True)
    if s["epochlar"]:
        print(f"EGITIM {ad}: tepe torch ayrılan={s['tepe_ayrilan_mib']:.0f}MiB ayrılmış={s['tepe_ayrilmis_mib']:.0f}MiB nvidia-smi süreç tepe={s.get('nvidia_smi_surec_tepe_mib', float('nan')):.0f}MiB "
              f"toplam VRAM={s['toplam_vram_mib']:.0f}MiB başlangıç={s['baslangic_bellek_mib']:.0f}MiB kalan={s['kalan_vram_mib']:.0f}MiB "
              f"sığma(reserved, ≥%{e['TRAIN_PAY_YUZDE']} pay)={s['sigma_reserved']} sığma(nvidia-smi)={s['sigma_nvidia_smi']}", flush=True)
        for x in s["epochlar"]:
            print(f"EGITIM {ad}: epoch {x['epoch']}: eğitim {x['egitim_suresi_s']:.1f}s nb={x['nb']} {x['iter_s']:.2f} it/s tepe_ayrılan(eğitim)={x['egitim_tepe_ayrilan_mib']:.0f} "
                  f"(epoch sonu {x['epoch_sonu_tepe_ayrilan_mib']:.0f}) ayrılmış={x['epoch_sonu_tepe_ayrilmis_mib']:.0f}MiB epoch toplam {x['epoch_toplam_s']:.1f}s", flush=True)
    print(f"EGITIM {ad}: doğrulama {s['dogrulama']}", flush=True)
    print(f"EGITIM {ad}: uzak bağlantılar (loopback dışı, süreç+çocuklar): {s['uzak_baglantilar']}", flush=True)
    return 0 if not s["hata"] else 1


if __name__ == "__main__":
    sys.exit(main())
