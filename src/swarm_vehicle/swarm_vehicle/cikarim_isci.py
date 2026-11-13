"""Çıkarım işçisi (B9, FR-12/FR-15): araç sürecinin başlattığı AYRI alt süreç. Kamera karesini alır, YOLO ile işler, sonucu döndürür.

Kullanım (araç süreci başlatır; elle de çalıştırılabilir):
  python -m swarm_vehicle.cikarim_isci --fd <soket-çifti-ucu> --arac-kimligi <id> --arac-sirasi <1..N> [--cpu 0,16] [--arka-uc gpu|cpu|sahte] [--kayit-klasoru <yol>]
Kanal: araç sürecinden devredilen AF_UNIX soket çifti ucu (cikarim_yardimci.py); IP, TCP/UDP ve DDS yoktur; bu süreçte rclpy ve gz içe aktarılmaz.
Çıkarım ayarları YALNIZ config/deney.env `INF_*` değerlerinden okunur (kilitli): güven INF_CONF, max_det INF_MAX_DET, imgsz INF_IMGSZ, batch INF_BATCH, FP32 (INF_PRECISION), nms=False (INF_NMS).
Ön işleme: kamera karesi RGB8 (CAM_WIDTH × CAM_HEIGHT × 3) → BGR (Ultralytics'in numpy girdi sözleşmesi) → Ultralytics letterbox (imgsz=640'a oranı koruyarak, 114 dolgu, [0,1] FP32); kutular özgün görüntü
piksel koordinatına geri çevrilir (xyxy). ORT (CPU) arka ucu aynı letterbox'ı kendi uygular.
nms=False kanıtı (GPU): başlık (Detect) uçtan uca (end2end) kipine alınır; her çıkarımda başlığın ham çıktısı [1, max_det, 6] olmalı (NMS'li yol [1, 4+nc, N] verir) ve `torchvision.ops.nms` ısınmadan
sonra hiç çağrılmamalıdır; aksi halde kare işlem hatası olur. Ultralytics'in kendi ısınma adımı sahte veriyle bir NMS çağrısı yapar; bu, ısınma sırasında ayrı sayılır.
Zaman damgaları (CLOCK_MONOTONIC ns): `cikarim_basi` = kare çerçevesi okunup işleme başlanan an; `cikarim_sonu` = sonucun işçide ana belleğe alındığı an (GPU senkronu ve `.cpu()` sonrası).
Kayıtlar: kayit/cikarim_iscisi_<araç>.jsonl (kare_olay, kaynak cikarim_iscisi), kayit/isci_kaynak_<araç>.jsonl (periyodik GPU kullanımı/belleği, ana bellek). Günlük satırları stderr'e yazılır.
Araç süreci kanalı kapatınca (ya da SIGTERM) işçi temiz çıkar. Çıkış kodları: 0 temiz, 1 hata, 2 kullanım, 3 yapılandırma/model hatası.
"""
import json
import os
import signal
import sys
import threading
import time

from . import cikarim_yardimci as Y
from . import rota as _rota

ISCI_KAYNAK = "cikarim_iscisi"


def g(*parcalar):
    print("ISCI " + " ".join(str(p) for p in parcalar), file=sys.stderr, flush=True)


# --- arka uçlar -----------------------------------------------------------------------------------------------------------------------------
class SahteArkaUc:
    """YALNIZ kanal/işçi mantığının birim testi için (GPU gerekmez): görüntünün ilk baytı 255 ise tek 'person' tespiti, 253 ise hata, 254 ise uzun bekleme; aksi halde tespit yok."""
    ad = "sahte"
    cihaz = "yok"
    model_adi = "sahte"
    sinif_adlari = ["person"]

    def __init__(self, ham, cpu_adet):
        self.uc_uca = {"sahte": True}

    def isin(self, w, h, adet):
        return []

    def cikar(self, yuk, w, h):
        b = yuk[0] if len(yuk) else 0
        if b == 253:
            raise RuntimeError("sahte arka uç hatası")
        if b == 254:
            time.sleep(600)
        return [{"sinif_adi": "person", "guven": 0.9, "kutu": [10.0, 20.0, 110.0, 220.0]}] if b == 255 else []

    def kapat(self):
        pass


class GpuArkaUc:
    """PyTorch + CUDA, Ultralytics YOLO (kilitli deney yolu): FP32, batch=1, nms=False (uçtan uca başlık), güven INF_CONF."""
    ad = "gpu"

    def __init__(self, ham, cpu_adet):
        os.environ.setdefault("YOLO_OFFLINE", "1")        # ağırlık/olay için ağa çıkılmaz
        if ham["INF_NMS"] != "False" or ham["INF_PRECISION"] != "fp32" or int(ham["INF_BATCH"]) != 1:
            raise ValueError(f"INF_* kilitli değerlerden farklı (nms={ham['INF_NMS']}, hassasiyet={ham['INF_PRECISION']}, batch={ham['INF_BATCH']}): işçi başlamaz")
        yol = os.path.join(_rota.KOK, ham["INF_GPU_MODEL"])
        if not os.path.isfile(yol):
            raise FileNotFoundError(f"model ağırlığı yok: {ham['INF_GPU_MODEL']} (indirme yapılmaz; .generated/models içinde olmalı)")
        import numpy as np
        import torch
        import torchvision
        import ultralytics.utils as U
        from ultralytics import YOLO
        from ultralytics.utils.events import events
        self.np, self.torch = np, torch
        self.cevrimdisi = (not U.ONLINE) and (not events.enabled)
        if not self.cevrimdisi:
            raise RuntimeError(f"Ultralytics çevrimdışı değil (ONLINE={U.ONLINE}, olay gönderimi={events.enabled}): işçi başlamaz")
        torch.set_num_threads(cpu_adet)
        self.conf, self.max_det, self.imgsz = float(ham["INF_CONF"]), int(ham["INF_MAX_DET"]), int(ham["INF_IMGSZ"])
        self.model_adi = ham["INF_GPU_MODEL"]
        self.model = YOLO(yol)
        self.model.to("cuda:0")
        self.cihaz = torch.cuda.get_device_name(0)
        self.sinif_adlari = [self.model.names[i] for i in sorted(self.model.names)]
        self._kutu = {"sekil": None}                         # kanca yalnız bu sözlüğe yazar (Ultralytics modeli deepcopy eder; kancanın `self`'e bağlı olmaması gerekir)
        self.nms_cagri = 0
        asil_nms = torchvision.ops.nms

        def sayan_nms(*a, **k):
            self.nms_cagri += 1
            return asil_nms(*a, **k)
        torchvision.ops.nms = sayan_nms
        kutu = self._kutu

        def kanca(_modul, _girdi, cikti):
            y = cikti[0] if isinstance(cikti, (tuple, list)) else cikti
            kutu["sekil"] = tuple(y.shape) if hasattr(y, "shape") else None
        self.model.model.model[-1].register_forward_hook(kanca)
        self.uc_uca = {}

    def _tahmin(self, bgr):
        r = self.model.predict(bgr, imgsz=self.imgsz, conf=self.conf, max_det=self.max_det, batch=1, nms=False, half=False, device=0, verbose=False)
        self.torch.cuda.synchronize()
        return r[0]

    def isin(self, w, h, adet):
        """Isınma çıkarımları (rastgele görüntü); uçtan uca başlığı ve NMS'siz yolu kanıtlar. Dönen: her çıkarımın ms süresi."""
        sureler = []
        rng = self.np.random.default_rng(1)
        for _ in range(max(1, adet)):
            bgr = rng.integers(0, 255, (h, w, 3), dtype=self.np.uint8)
            t = time.perf_counter()
            self._tahmin(bgr)
            sureler.append((time.perf_counter() - t) * 1000)
        bas = self.model.predictor.model.model.model[-1]
        self.uc_uca = {"baslik_end2end": bool(bas.end2end), "ham_cikti_sekli": list(self._kutu["sekil"] or ()), "isinmada_nms_cagrisi": self.nms_cagri}
        self.nms_cagri = 0                                  # ısınma sonrası: kare başına NMS çağrısı sıfır olmalı
        self.torch.cuda.reset_peak_memory_stats()
        self._uc_uca_denetle()
        return sureler

    def _uc_uca_denetle(self):
        bas = self.model.predictor.model.model.model[-1]
        beklenen = (1, self.max_det, 6)
        if not bas.end2end or self._kutu["sekil"] != beklenen:
            raise RuntimeError(f"nms=False uçtan uca başlık kanıtlanamadı: end2end={bas.end2end}, ham çıktı {self._kutu["sekil"]} (beklenen {beklenen})")

    def cikar(self, yuk, w, h):
        np = self.np
        rgb = np.frombuffer(yuk, dtype=np.uint8).reshape(h, w, 3)
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        nms0 = self.nms_cagri
        r = self._tahmin(bgr)
        d = r.boxes.data.cpu().numpy()                      # sonuç ana belleğe alındı (GPU senkronu + .cpu())
        if self.nms_cagri != nms0:
            raise RuntimeError("çıkarım sırasında NMS çağrıldı (nms=False ihlali)")
        self._uc_uca_denetle()
        adlar = r.names
        return [{"sinif_adi": adlar[int(s)], "guven": float(c), "kutu": [float(a), float(b), float(e), float(f)]} for a, b, e, f, c, s in d.tolist()]

    def gpu_bellek(self):
        return {"torch_maks_ayrilan_mib": self.torch.cuda.max_memory_allocated() / 2 ** 20, "torch_maks_ayrilmis_mib": self.torch.cuda.max_memory_reserved() / 2 ** 20}

    def kapat(self):
        pass


class OrtArkaUc:
    """B planı yapı uyumu: ONNX Runtime CPU, NMS'siz (end2end) çıktı. Deneylerde kullanılmaz (kararlar: çıkarım yolu GPU)."""
    ad = "cpu"

    def __init__(self, ham, cpu_adet):
        os.environ.setdefault("YOLO_OFFLINE", "1")
        yol = os.path.join(_rota.KOK, ham["ISCI_CPU_ONNX"])
        if not os.path.isfile(yol):
            raise FileNotFoundError(f"ONNX modeli yok: {ham['ISCI_CPU_ONNX']} (indirme yapılmaz)")
        import ast

        import cv2
        import numpy as np
        import onnxruntime as ort
        self.np, self.cv2 = np, cv2
        so = ort.SessionOptions()
        so.intra_op_num_threads = cpu_adet
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.s = ort.InferenceSession(yol, so, providers=["CPUExecutionProvider"])
        self.girdi = self.s.get_inputs()[0].name
        self.conf, self.max_det, self.imgsz = float(ham["INF_CONF"]), int(ham["INF_MAX_DET"]), int(ham["INF_IMGSZ"])
        self.model_adi, self.cihaz = ham["ISCI_CPU_ONNX"], "cpu"
        adlar = ast.literal_eval(self.s.get_modelmeta().custom_metadata_map["names"])
        self.sinif_adlari = [adlar[i] for i in sorted(adlar)]
        self._adlar = adlar
        self.uc_uca = {}

    def _ham(self, bgr):
        np, cv2 = self.np, self.cv2
        h, w = bgr.shape[:2]
        r = min(self.imgsz / h, self.imgsz / w)
        nh, nw = int(round(h * r)), int(round(w * r))
        im = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        ust, sol = (self.imgsz - nh) // 2, (self.imgsz - nw) // 2
        can = np.full((self.imgsz, self.imgsz, 3), 114, np.uint8)
        can[ust:ust + nh, sol:sol + nw] = im
        x = can[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        y = self.s.run(None, {self.girdi: np.ascontiguousarray(x)})[0]
        return y, r, ust, sol

    def isin(self, w, h, adet):
        sureler = []
        rng = self.np.random.default_rng(1)
        y = None
        for _ in range(max(1, adet)):
            bgr = rng.integers(0, 255, (h, w, 3), dtype=self.np.uint8)
            t = time.perf_counter()
            y, _r, _u, _s = self._ham(bgr)
            sureler.append((time.perf_counter() - t) * 1000)
        self.uc_uca = {"ham_cikti_sekli": list(y.shape), "cikti_adi": self.s.get_outputs()[0].name}
        try:
            import onnx
            ops = [n.op_type for n in onnx.load(os.path.join(_rota.KOK, self.model_adi)).graph.node]
            self.uc_uca["nms_dugumu_var"] = any("NonMaxSuppression" in o or "NMS" in o for o in ops)
        except ImportError:
            self.uc_uca["nms_dugumu_var"] = None
        if tuple(y.shape) != (1, self.max_det, 6) or self.uc_uca["nms_dugumu_var"]:
            raise RuntimeError(f"ONNX çıktısı NMS'siz uçtan uca değil: {self.uc_uca}")
        return sureler

    def cikar(self, yuk, w, h):
        np = self.np
        bgr = np.ascontiguousarray(np.frombuffer(yuk, dtype=np.uint8).reshape(h, w, 3)[:, :, ::-1])
        y, r, ust, sol = self._ham(bgr)
        d = y[0]
        d = d[d[:, 4] > self.conf][:self.max_det].copy()
        d[:, [0, 2]] = ((d[:, [0, 2]] - sol) / r).clip(0, w)       # letterbox koordinatından özgün görüntü koordinatına
        d[:, [1, 3]] = ((d[:, [1, 3]] - ust) / r).clip(0, h)
        return [{"sinif_adi": self._adlar[int(s)], "guven": float(c), "kutu": [float(a), float(b), float(e), float(f)]} for a, b, e, f, c, s in d.tolist()]

    def kapat(self):
        pass


ARKA_UCLAR = {"gpu": GpuArkaUc, "cpu": OrtArkaUc, "sahte": SahteArkaUc}


# --- kaynak örnekleyici ---------------------------------------------------------------------------------------------------------------------
class KaynakOrnekleyici(threading.Thread):
    """Periyodik: işçi sürecinin GPU kullanımı (NVML süreç kullanımı, SM %), GPU belleği (NVML süreç belleği, MiB), ana bellek (RSS) ve CPU yüzdesi (tek mantıksal CPU = %100).
    Yöntem: pynvml (nvidia-ml-py; sudo yok): nvmlDeviceGetProcessUtilization (son örneklemeden beri süreç SM kullanımı) ve nvmlDeviceGetComputeRunningProcesses (süreç GPU belleği).
    NVML yoksa/başarısızsa GPU alanları null yazılır ve bir kez günlüğe uyarı düşer. Üst sınır konmaz."""

    def __init__(self, yol, arac_kimligi, aralik_sn, gpu_kullan):
        super().__init__(name="isci_kaynak", daemon=True)
        self.yol, self.arac, self.aralik = yol, int(arac_kimligi), float(aralik_sn)
        self.dur = threading.Event()
        self.pid = os.getpid()
        self.nvml = None
        self.uyari = False
        self.son_zaman = 0
        self.son_cpu = None
        self.olcumler = []
        if gpu_kullan:
            try:
                import pynvml
                pynvml.nvmlInit()
                self.nvml = pynvml
                self.el = pynvml.nvmlDeviceGetHandleByIndex(0)
            except Exception as e:  # noqa: BLE001
                g("kaynak_uyari", f"NVML başlatılamadı: {e!r}")

    @staticmethod
    def _rss_mib():
        with open("/proc/self/statm", encoding="ascii") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2 ** 20

    @staticmethod
    def _cpu_s():
        with open("/proc/self/stat", encoding="ascii") as f:
            p = f.read().rsplit(")", 1)[1].split()
        return (int(p[11]) + int(p[12])) / os.sysconf("SC_CLK_TCK")

    def _gpu(self):
        if self.nvml is None:
            return None, None
        p = self.nvml
        kul = bel = None
        try:
            for pr in p.nvmlDeviceGetComputeRunningProcesses(self.el):
                if pr.pid == self.pid and pr.usedGpuMemory is not None:
                    bel = pr.usedGpuMemory / 2 ** 20
        except p.NVMLError as e:
            if not self.uyari:
                self.uyari = True
                g("kaynak_uyari", f"GPU süreç belleği okunamadı: {e}")
        try:
            kul = 0
            for s in p.nvmlDeviceGetProcessUtilization(self.el, self.son_zaman):
                if s.pid == self.pid:
                    kul = max(kul, int(s.smUtil))
                self.son_zaman = max(self.son_zaman, s.timeStamp)
        except p.NVMLError as e:
            if "Not Found" in str(e):
                kul = 0                                 # örnekleme aralığında süreç hiç çalışmadı
            else:
                kul = None
                if not self.uyari:
                    self.uyari = True
                    g("kaynak_uyari", f"GPU süreç kullanımı okunamadı: {e}")
        return kul, bel

    def ornek(self):
        simdi_mono = time.monotonic_ns()
        cpu = self._cpu_s()
        cpu_yuzde = None if self.son_cpu is None else round(100.0 * (cpu - self.son_cpu[0]) / max((simdi_mono - self.son_cpu[1]) / 1e9, 1e-6), 1)
        self.son_cpu = (cpu, simdi_mono)
        kul, bel = self._gpu()
        d = {"surum": 1, "tur": "isci_kaynak", "arac_kimligi": self.arac, "isci_pid": self.pid, "mono_ns": simdi_mono, "gpu_kullanim_yuzde": kul,
             "gpu_bellek_mib": None if bel is None else round(bel, 1), "ana_bellek_rss_mib": round(self._rss_mib(), 1), "cpu_yuzde": cpu_yuzde}
        self.olcumler.append(d)
        with open(self.yol, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def run(self):
        self.ornek()
        while not self.dur.wait(self.aralik):
            self.ornek()


# --- ana döngü ------------------------------------------------------------------------------------------------------------------------------
def calistir(argv):
    import socket
    a = list(argv)
    fd = kimlik = sira = None
    cpu = []
    arka = None
    klasor = None
    while a:
        k = a.pop(0)
        if k == "--fd" and a:
            fd = int(a.pop(0))
        elif k == "--arac-kimligi" and a:
            kimlik = int(a.pop(0))
        elif k == "--arac-sirasi" and a:
            sira = int(a.pop(0))
        elif k == "--cpu" and a:
            cpu = Y.cpu_listesi_coz(a.pop(0))
        elif k == "--arka-uc" and a:
            arka = a.pop(0)
        elif k == "--kayit-klasoru" and a:
            klasor = a.pop(0)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if fd is None or kimlik is None or sira is None:
        print(__doc__, file=sys.stderr)
        return 2
    sock = socket.socket(fileno=fd)
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    signal.signal(signal.SIGINT, lambda *_: os._exit(0))
    if cpu:
        os.sched_setaffinity(0, cpu)                          # torch/ORT iş parçacıkları bu kümeyi miras alır
    ham = _rota.deney_env_oku()
    arka = arka or ham["ISCI_ARKA_UC"]
    cpu_adet = len(cpu) if cpu else int(ham["ISCI_MANTIKSAL_CPU"])
    w, h = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
    olay_yol = ksn_yol = None
    if klasor:
        olay_yol = os.path.join(klasor, "kayit", f"cikarim_iscisi_{kimlik}.jsonl")
        ksn_yol = os.path.join(klasor, "kayit", f"isci_kaynak_{kimlik}.jsonl")
    olay_dosya = open(olay_yol, "a", encoding="utf-8") if olay_yol else None

    def olay(n, damga_ns, ad, mono):
        if olay_dosya:
            olay_dosya.write(json.dumps({"surum": 1, "tur": "kare_olay", "kaynak": ISCI_KAYNAK, "arac_kimligi": kimlik, "n": n, "sim_damga_ns": damga_ns, "olay": ad, "mono_ns": mono}) + "\n")
            olay_dosya.flush()

    t_yukle = time.monotonic()
    try:
        arka_uc = ARKA_UCLAR[arka](ham, cpu_adet)
    except KeyError:
        print(f"(-) bilinmeyen arka uç: {arka}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        g("baslatma_hatasi", repr(e))
        try:
            Y.cerceve_yaz(sock, {"tur": "hazir_degil", "hata": repr(e)})
        except OSError:
            pass
        return 3
    yukleme_s = time.monotonic() - t_yukle
    t_isin = time.monotonic()
    try:
        isinma_ms = arka_uc.isin(w, h, int(ham["ISCI_ISINMA_KARE"]))
    except Exception as e:  # noqa: BLE001
        g("isinma_hatasi", repr(e))
        try:
            Y.cerceve_yaz(sock, {"tur": "hazir_degil", "hata": repr(e)})
        except OSError:
            pass
        return 3
    isinma_s = time.monotonic() - t_isin
    ornekleyici = None
    if ksn_yol:
        ornekleyici = KaynakOrnekleyici(ksn_yol, kimlik, float(ham["ISCI_KAYNAK_SN"]), arka == "gpu")
        ornekleyici.start()
    bilgi = {"tur": "hazir", "pid": os.getpid(), "arka_uc": arka_uc.ad, "model": arka_uc.model_adi, "cihaz": arka_uc.cihaz, "yukleme_s": round(yukleme_s, 3),
             "isinma_s": round(isinma_s, 3), "isinma_ms": [round(x, 2) for x in isinma_ms], "cpu": sorted(os.sched_getaffinity(0)), "rclpy_yuklu": "rclpy" in sys.modules,
             "uc_uca": arka_uc.uc_uca, "sinif_adlari": arka_uc.sinif_adlari, "cevrimdisi": getattr(arka_uc, "cevrimdisi", None)}
    g("hazir", json.dumps(bilgi, ensure_ascii=False))
    Y.cerceve_yaz(sock, bilgi)
    tampon = bytearray(w * h * 3)
    islenen = 0
    try:
        while True:
            try:
                baslik, yuk = Y.cerceve_oku(sock, tampon)
            except Y.KanalKapandi:
                break
            if baslik.get("tur") == "dur":
                break
            if baslik.get("tur") != "kare":
                continue
            basi = time.monotonic_ns()
            n, damga = int(baslik["n"]), int(baslik["damga_ns"])
            olay(n, damga, "cikarim_basi", basi)
            enj = baslik.get("enj")
            if enj == "olum":
                g("enjeksiyon_olum", n)
                if olay_dosya:
                    olay_dosya.flush()
                os._exit(137)                                 # işçi ölümü (yalnız test enjeksiyonu)
            yanit = {"tur": "sonuc", "n": n, "damga_ns": damga}
            try:
                if enj == "hata":
                    raise RuntimeError("enjekte edilen işçi hatası")
                kw, kh = int(baslik["w"]), int(baslik["h"])
                if (kw, kh) != (w, h) or len(yuk) != kw * kh * 3 or baslik.get("bicim") != "rgb8":
                    raise ValueError(f"görüntü boyutu/biçimi bozuk: {kw}x{kh} {baslik.get('bicim')} {len(yuk)} bayt (beklenen {w}x{h} rgb8 {w * h * 3} bayt)")
                tespitler = arka_uc.cikar(yuk, kw, kh)
                sonu = time.monotonic_ns()
                yanit.update(durum="tamam", tespitler=tespitler)
            except Exception as e:  # noqa: BLE001
                sonu = time.monotonic_ns()
                g("kare_hatasi", n, repr(e))
                yanit.update(durum="hata", hata=f"{type(e).__name__}: {e}", tespitler=[])
            olay(n, damga, "cikarim_sonu", sonu)
            yanit.update(basi_ns=basi, sonu_ns=sonu)
            islenen += 1
            try:
                Y.cerceve_yaz(sock, yanit)
            except OSError:
                break
    finally:
        if ornekleyici:
            ornekleyici.dur.set()
        ozet = {"islenen": islenen}
        if hasattr(arka_uc, "gpu_bellek"):
            ozet.update(arka_uc.gpu_bellek())
        g("kapanis", json.dumps(ozet))
        if olay_dosya:
            olay_dosya.close()
    return 0


def main():
    return calistir(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
