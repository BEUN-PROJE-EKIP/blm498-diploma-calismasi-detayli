#!/usr/bin/env python3
"""Üç araç + üç kamera + üç çıkarım işçisi yük ölçümü (K11) ve CPU/ONNX yolu hız ölçümü (K12).

Kullanım:
  yuk_olcum.py dunya <cikti.sdf>                                       3 araçlı (x500 + aşağı bakan kamera) sahneyi üretir
  yuk_olcum.py isci  <gpu|cpu> <konu> <mod> <cikti.json> [bayrak_dizini]
        mod = gercek    : kameradan gz-transport ile kare alır, YUK_SIM_SN sim saniyesi boyunca işler
        mod = doygunluk : kameradan birkaç kare alıp bellekte tutar, kare hızını sınırlamadan YUK_DOYGUNLUK_SN sn işler
  yuk_olcum.py izle  <sure_sn> <cikti.csv>                             GPU/CPU/bellek/RTF örnekleyici
  yuk_olcum.py onnx-aktar <pt_dosyasi>                                 ağırlığı (yoksa indirir) export(format='onnx', nms=False) ile aktarır
  yuk_olcum.py onnx-kontrol <pt_dosyasi> <onnx_dosyasi>                NMS'siz ONNX şeması ve PyTorch–ONNX uyumu
Değerler ortam değişkenlerinden okunur (setup/yuk_olcum_testi.sh, config/deney.env'den verir).
Yorum yoktur: ölçülen sayılar yazılır.
"""
import collections
import json
import math
import os
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore")
# Gizlilik: Ultralytics anonim olay göndermesin (settings sync=True olsa bile); ağırlıklar yerelde olmalı
os.environ.setdefault("YOLO_OFFLINE", "1")


def cfg():
    e = os.environ
    return {
        "w": int(e["CAM_WIDTH"]), "h": int(e["CAM_HEIGHT"]), "hz": float(e["CAM_RATE_HZ"]), "fov": float(e["CAM_SDF_HFOV_RAD"]),
        "dunya": e["CAM_WORLD"], "conf": float(e["INF_CONF"]), "max_det": int(e["INF_MAX_DET"]), "imgsz": int(e["INF_IMGSZ"]),
        "batch": int(e["INF_BATCH"]), "kuyruk": int(e["YUK_KUYRUK"]), "sim_sn": float(e["YUK_SIM_SN"]), "dsn": float(e["YUK_DOYGUNLUK_SN"]),
        "gpu_model": e["INF_GPU_MODEL"], "cpu_model": e["INF_CPU_MODEL"], "cpu_n": int(e.get("YUK_CPU_ISCI_CPU", "2")),
        "pozlar": [tuple(float(v) for v in p.split(",")) for p in e["UAV_START_POSES"].split()],
    }


def yuzde(v, p):
    s = sorted(v)
    if not s:
        return float("nan")
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def sdf_uret(cikti):
    c = cfg()
    p = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<!-- Otomatik üretildi (araclar/yuk_olcum.py dunya); değerler config/deney.env içindeki ayarlardan gelir. -->',
         '<sdf version="1.9">', f'  <world name="{c["dunya"]}">']
    p.append('''    <physics type="ode"><max_step_size>0.004</max_step_size><real_time_factor>1.0</real_time_factor><real_time_update_rate>250</real_time_update_rate></physics>
    <gravity>0 0 -9.8</gravity>
    <magnetic_field>6e-06 2.3e-05 -4.2e-05</magnetic_field>
    <atmosphere type="adiabatic"/>
    <scene><grid>false</grid><ambient>0.4 0.4 0.4 1</ambient><background>0.7 0.7 0.7 1</background><shadows>false</shadows></scene>
    <model name="ground_plane"><static>true</static><link name="link">
      <collision name="collision"><geometry><plane><normal>0 0 1</normal><size>1 1</size></plane></geometry></collision>
      <visual name="visual"><geometry><plane><normal>0 0 1</normal><size>500 500</size></plane></geometry>
        <material><ambient>0.8 0.8 0.8 1</ambient><diffuse>0.8 0.8 0.8 1</diffuse><specular>0 0 0 1</specular></material></visual>
    </link></model>
    <light name="sunUTC" type="directional"><pose>0 0 500 0 0 0</pose><cast_shadows>false</cast_shadows><intensity>1</intensity>
      <direction>0.001 0.625 -0.78</direction><diffuse>0.904 0.904 0.904 1</diffuse><specular>0 0 0 1</specular></light>''')
    for i, (x, y, z) in enumerate(c["pozlar"], start=1):
        # PX4'ün x500_mono_cam_down modeliyle aynı yapı (x500 + gövdeye sabit, aşağı bakan kamera); kamera ayarı CAM_* değerleri
        p.append(f'''    <model name="arac_{i}"><self_collide>false</self_collide><pose>{x:g} {y:g} {z:g} 0 0 0</pose>
      <include merge="true"><uri>model://x500</uri></include>
      <link name="camera_link"><pose>0 0 0.10 0 1.5707 0</pose>
        <inertial><pose>0.03 0.03 0.03 0 0 0</pose><mass>0.050</mass><inertia><ixx>0.00004</ixx><ixy>0</ixy><ixz>0</ixz><iyy>0.00004</iyy><iyz>0</iyz><izz>0.00004</izz></inertia></inertial>
        <visual name="kamera_govde"><geometry><box><size>0.02 0.04 0.04</size></box></geometry></visual>
        <sensor name="kamera" type="camera"><always_on>1</always_on><update_rate>{c["hz"]:g}</update_rate><visualize>false</visualize>
          <topic>kamera_{i}/image</topic>
          <camera><horizontal_fov>{c["fov"]:g}</horizontal_fov><image><width>{c["w"]}</width><height>{c["h"]}</height><format>R8G8B8</format></image>
            <clip><near>0.1</near><far>200</far></clip></camera></sensor></link>
      <joint name="CameraJoint" type="fixed"><parent>base_link</parent><child>camera_link</child><pose relative_to="base_link">0 0 0 0 1.5707 0</pose></joint>
    </model>''')
    p += ['  </world>', '</sdf>']
    with open(cikti, "w", encoding="utf-8") as f:
        f.write("\n".join(p) + "\n")


def cevrimdisi_kanit(etiket):
    """Ultralytics çağrılarından önce: ONLINE=False ve olay gönderimi kapalı olmalı; değilse süreç durur."""
    import ultralytics.utils as U
    from ultralytics.utils.events import events
    print(f"YOLO {etiket}: YOLO_OFFLINE={os.environ.get('YOLO_OFFLINE')} ONLINE={U.ONLINE} olay_gonderimi_aktif={events.enabled} sync={U.SETTINGS['sync']}", flush=True)
    if U.ONLINE or events.enabled:
        print(f"YOLO {etiket}: UYARI çevrimdışı mod etkin değil; durduruluyor", flush=True)
        sys.exit(3)


def uzak_baglanti_izle(kume, dur):
    """Süreç ve çocuklarının loopback dışı, bağlı (raddr'li) soketlerini 1 sn aralıkla `kume`ye ekler (tcpdump'sız ağ çıkışı kontrolü)."""
    import psutil
    proc = psutil.Process(os.getpid())
    while not dur.is_set():
        try:
            for pr in [proc] + proc.children(recursive=True):
                for c in pr.net_connections(kind="inet"):
                    if c.raddr and c.raddr.ip not in ("127.0.0.1", "::1") and c.status != "LISTEN":
                        kume.add(f"{c.raddr.ip}:{c.raddr.port}")
        except Exception:
            pass
        dur.wait(1.0)


def rss_mib():
    with open("/proc/self/status") as f:
        for ln in f:
            if ln.startswith("VmHWM:"):
                return int(ln.split()[1]) / 1024.0
    return float("nan")


class CPUModel:
    """ONNX Runtime CPU çıkarımı: NMS'siz (end2end) çıktı; ön işleme Ultralytics letterbox ile aynı."""

    def __init__(self, onnx_yolu, n_thread):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = n_thread
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.s = ort.InferenceSession(onnx_yolu, so, providers=["CPUExecutionProvider"])
        self.girdi = self.s.get_inputs()[0].name

    def __call__(self, bgr, conf, max_det, imgsz):
        import cv2
        import numpy as np
        h, w = bgr.shape[:2]
        r = min(imgsz / h, imgsz / w)
        nh, nw = int(round(h * r)), int(round(w * r))
        im = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        top, left = (imgsz - nh) // 2, (imgsz - nw) // 2
        can = np.full((imgsz, imgsz, 3), 114, np.uint8)
        can[top:top + nh, left:left + nw] = im
        x = can[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        y = self.s.run(None, {self.girdi: np.ascontiguousarray(x)})[0]
        d = y[0]
        d = d[d[:, 4] > conf][:max_det].copy()
        # kutular letterbox koordinatındadır: orijinal görüntü koordinatına geri eşle
        d[:, [0, 2]] = ((d[:, [0, 2]] - left) / r).clip(0, w)
        d[:, [1, 3]] = ((d[:, [1, 3]] - top) / r).clip(0, h)
        return d


class Isci:
    def __init__(self, tur, konu, mod, cikti, bayrak):
        import numpy as np
        self.np = np
        self.c = cfg()
        self.tur, self.konu, self.mod, self.cikti, self.bayrak = tur, konu, mod, cikti, bayrak
        self.kuyruk = collections.deque()
        self.kilit = threading.Lock()
        self.olay = threading.Event()
        self.alinan = 0
        self.tasan = 0
        self.kuyruk_maks = 0
        self.ilk_damga = None
        self.son_damga = None
        self.ilk_gercek = None
        self.dur = False
        self.saklanan = []     # doygunluk için bellekteki kareler
        if tur == "gpu":
            cevrimdisi_kanit(f"işçi {konu}")
            import torch
            from ultralytics import YOLO
            self.torch = torch
            torch.set_num_threads(self.c["cpu_n"])
            self.model = YOLO(self.c["gpu_model"])
            self.model.to("cuda:0")
        else:
            self.model = CPUModel(os.environ["INF_CPU_ONNX"], self.c["cpu_n"])

    def cb(self, m):
        a = time.monotonic_ns()
        np = self.np
        if m.pixel_format_type != 3 or m.step != m.width * 3:
            return
        rgb = np.frombuffer(m.data, dtype=np.uint8).reshape(m.height, m.width, 3)
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        ns = m.header.stamp.sec * 1_000_000_000 + m.header.stamp.nsec
        with self.kilit:
            self.alinan += 1
            if self.ilk_damga is None:
                self.ilk_damga, self.ilk_gercek = ns, a
            self.son_damga = ns
            if len(self.saklanan) < 8:
                self.saklanan.append(bgr)
            self.kuyruk.append((ns, a, bgr))
            if len(self.kuyruk) > self.c["kuyruk"]:
                self.kuyruk.popleft()
                self.tasan += 1
            self.kuyruk_maks = max(self.kuyruk_maks, len(self.kuyruk))
        self.olay.set()

    def cikar(self, bgr):
        c = self.c
        if self.tur == "gpu":
            t0 = time.perf_counter()
            r = self.model.predict(bgr, imgsz=c["imgsz"], conf=c["conf"], max_det=c["max_det"], batch=c["batch"], nms=False,
                                   device=0, verbose=False)
            self.torch.cuda.synchronize()
            dt = (time.perf_counter() - t0) * 1000.0
            sp = r[0].speed
            return dt, len(r[0].boxes), sp
        t0 = time.perf_counter()
        d = self.model(bgr, c["conf"], c["max_det"], c["imgsz"])
        dt = (time.perf_counter() - t0) * 1000.0
        return dt, len(d), {}

    def isin(self):
        for _ in range(5):
            self.cikar(self.np.random.randint(0, 255, (self.c["h"], self.c["w"], 3), dtype=self.np.uint8))
        if self.tur == "gpu":
            self.torch.cuda.reset_peak_memory_stats()

    def calis(self):
        from gz.transport13 import Node
        from gz.msgs10.image_pb2 import Image
        c = self.c
        node = Node()
        if not node.subscribe(Image, "/" + self.konu, self.cb):
            raise RuntimeError(f"abonelik kurulamadı: /{self.konu}")
        self.isin()
        self.uzak = set()
        self.uzak_dur = threading.Event()
        threading.Thread(target=uzak_baglanti_izle, args=(self.uzak, self.uzak_dur), daemon=True).start()
        sureler, hizlar, tespit = [], collections.defaultdict(list), 0
        gecikme = []
        islenen = 0
        t_bas = time.monotonic()
        if self.mod == "gercek":
            ilk_islem = None
            while not self.dur:
                if not self.olay.wait(timeout=1.0):
                    if time.monotonic() - t_bas > c["sim_sn"] * 4 + 120:
                        break
                    continue
                with self.kilit:
                    if not self.kuyruk:
                        self.olay.clear()
                        continue
                    ns, a, bgr = self.kuyruk.popleft()
                    if not self.kuyruk:
                        self.olay.clear()
                dt, n, sp = self.cikar(bgr)
                bitis = time.monotonic_ns()
                islenen += 1
                if ilk_islem is None:
                    ilk_islem = time.monotonic()
                sureler.append(dt)
                gecikme.append((bitis - a) / 1e6)
                tespit += n
                for k, v in sp.items():
                    hizlar[k].append(v)
                with self.kilit:
                    span = (self.son_damga - self.ilk_damga) * 1e-9
                if span >= c["sim_sn"]:
                    break
            with self.kilit:
                kalan = len(self.kuyruk)
                sim_sure = (self.son_damga - self.ilk_damga) * 1e-9 if self.ilk_damga is not None else float("nan")
                alinan, tasan, qmax = self.alinan, self.tasan, self.kuyruk_maks
            gercek_sure = time.monotonic() - (self.ilk_gercek / 1e9 if False else t_bas)
        else:   # doygunluk
            t0 = time.monotonic()
            while len(self.saklanan) < 8 and time.monotonic() - t0 < 60:
                time.sleep(0.2)
            kareler = list(self.saklanan)
            node.unsubscribe("/" + self.konu)
            if not kareler:
                raise RuntimeError("doygunluk için kare alınamadı")
            if self.bayrak:
                open(os.path.join(self.bayrak, f"hazir_{os.getpid()}"), "w").close()
                t0 = time.monotonic()
                while not os.path.exists(os.path.join(self.bayrak, "basla")) and time.monotonic() - t0 < 120:
                    time.sleep(0.05)
            t_bas = time.monotonic()
            i = 0
            while time.monotonic() - t_bas < c["dsn"]:
                dt, n, sp = self.cikar(kareler[i % len(kareler)])
                i += 1
                islenen += 1
                sureler.append(dt)
                tespit += n
                for k, v in sp.items():
                    hizlar[k].append(v)
            alinan = tasan = qmax = kalan = 0
            sim_sure = float("nan")
            gercek_sure = time.monotonic() - t_bas
        bellek = {}
        if self.tur == "gpu":
            bellek = {"torch_maks_ayrilan_mib": self.torch.cuda.max_memory_allocated() / 2**20,
                      "torch_maks_ayrilmis_mib": self.torch.cuda.max_memory_reserved() / 2**20}
        self.uzak_dur.set()
        sonuc = {
            "uzak_baglantilar": sorted(self.uzak), "tur": self.tur, "konu": self.konu, "mod": self.mod, "pid": os.getpid(), "alinan": alinan, "islenen": islenen,
            "tasan_atlanan": tasan, "kuyrukta_kalan": kalan, "kuyruk_maks": qmax, "sim_sure_s": sim_sure, "gercek_sure_s": gercek_sure,
            "kare_s_sim": (islenen / sim_sure) if sim_sure == sim_sure and sim_sure > 0 else None,
            "kare_s_gercek": islenen / gercek_sure if gercek_sure > 0 else None,
            "cikarim_ms": {"medyan": yuzde(sureler, 50), "p95": yuzde(sureler, 95), "maks": max(sureler) if sureler else None,
                           "ort": sum(sureler) / len(sureler) if sureler else None, "min": min(sureler) if sureler else None},
            "asama_ms_medyan": {k: yuzde(v, 50) for k, v in hizlar.items()},
            "gecikme_ms": {"medyan": yuzde(gecikme, 50), "p95": yuzde(gecikme, 95), "maks": max(gecikme) if gecikme else None} if gecikme else None,
            "tespit_toplam": tespit, "rss_maks_mib": rss_mib(), "cpu_zamani_s": time.process_time(), "bellek": bellek,
            "cpu_afinite": sorted(os.sched_getaffinity(0)),
        }
        with open(self.cikti, "w", encoding="utf-8") as f:
            json.dump(sonuc, f, indent=1)
        print(f"YOLO işçi {self.konu}: loopback dışı bağlantılar (süreç+çocuklar): {sonuc['uzak_baglantilar']}", flush=True)
        print(f"ISCI {self.konu} {self.mod}: islenen={islenen} alinan={alinan} tasan={tasan} kare/s(gercek)={sonuc['kare_s_gercek']:.3f} "
              f"kare/s(sim)={sonuc['kare_s_sim'] if sonuc['kare_s_sim'] is None else round(sonuc['kare_s_sim'], 3)} sim_sure={sonuc['sim_sure_s']:.1f}s "
              f"kuyruk_maks={sonuc['kuyruk_maks']} kalan={sonuc['kuyrukta_kalan']} "
              f"cikarim_ms medyan={sonuc['cikarim_ms']['medyan']:.2f} p95={sonuc['cikarim_ms']['p95']:.2f} maks={sonuc['cikarim_ms']['maks']:.2f} "
              f"| asama_ms_medyan={ {k: round(v, 2) for k, v in sonuc['asama_ms_medyan'].items()} } "
              f"| torch_maks_ayrilan={sonuc['bellek'].get('torch_maks_ayrilan_mib', float('nan')):.0f}MiB torch_maks_ayrilmis={sonuc['bellek'].get('torch_maks_ayrilmis_mib', float('nan')):.0f}MiB "
              f"rss_maks={sonuc['rss_maks_mib']:.0f}MiB tespit={sonuc['tespit_toplam']} afinite={sonuc['cpu_afinite']}", flush=True)
        return 0


def isci_modu(tur, konu, mod, cikti, bayrak):
    w = Isci(tur, konu, mod, cikti, bayrak)
    return w.calis()


def izle_modu(sure, csv_yolu):
    import psutil
    import subprocess
    from gz.transport13 import Node
    from gz.msgs10.clock_pb2 import Clock
    c = cfg()
    clk = {"sim": None, "t": None}

    def cb(m):
        clk["sim"] = m.sim.sec + m.sim.nsec * 1e-9
        clk["t"] = time.monotonic()
    node = Node()
    node.subscribe(Clock, f"/world/{c['dunya']}/clock", cb)
    import signal
    dur = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: dur.update(v=True))   # orkestratör işçiler bitince TERM gönderir: özet yine yazılır
    satirlar = []
    onceki = (None, None)
    t0 = time.monotonic()
    psutil.cpu_percent(None)
    prok = {}
    while time.monotonic() - t0 < sure and not dur["v"]:
        time.sleep(2.0)
        zaman = time.monotonic() - t0
        # GPU
        try:
            g = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=10).stdout.strip().split(",")
            gpu_u, gpu_m = float(g[0]), float(g[1])
            ap = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
            apm = {int(a.split(",")[0]): float(a.split(",")[1]) for a in ap if "," in a}
        except Exception:
            gpu_u = gpu_m = float("nan")
            apm = {}
        # RTF
        rtf = float("nan")
        if clk["sim"] is not None:
            if onceki[0] is not None and clk["t"] - onceki[1] > 0:
                rtf = (clk["sim"] - onceki[0]) / (clk["t"] - onceki[1])
            onceki = (clk["sim"], clk["t"])
        # işçi ve diğer süreçler
        isc = {}
        for p in psutil.process_iter(["pid", "cmdline", "name"]):
            try:
                cl = " ".join(p.info["cmdline"] or [])
                if "yuk_olcum.py" in cl and " isci " in cl:
                    ad = "isci:" + cl.split(" isci ")[1].split()[1]
                elif p.info["name"] in ("px4", "gz", "ruby"):
                    ad = p.info["name"]
                else:
                    continue
                pr = prok.setdefault(p.info["pid"], p)
                isc.setdefault(ad, []).append((p.info["pid"], pr.cpu_percent(None), pr.memory_info().rss / 2**20))
            except Exception:
                continue
        vm = psutil.virtual_memory()
        satir = {"t": zaman, "gpu_kullanim": gpu_u, "gpu_bellek_mib": gpu_m, "rtf": rtf, "sistem_cpu": psutil.cpu_percent(None),
                 "ana_bellek_kullanilan_mib": (vm.total - vm.available) / 2**20, "surecler": isc, "gpu_surec_mib": apm}
        satirlar.append(satir)
    with open(csv_yolu, "w", encoding="utf-8") as f:
        f.write("t_s,gpu_kullanim,gpu_bellek_mib,rtf,sistem_cpu,ana_bellek_mib\n")
        for s in satirlar:
            f.write(f"{s['t']:.1f},{s['gpu_kullanim']},{s['gpu_bellek_mib']},{s['rtf']},{s['sistem_cpu']},{s['ana_bellek_kullanilan_mib']:.0f}\n")
    with open(csv_yolu + ".json", "w", encoding="utf-8") as f:
        json.dump(satirlar, f)
    ozet_izle(satirlar)
    return 0


def ozet_izle(satirlar):
    import statistics
    gu = [s["gpu_kullanim"] for s in satirlar if s["gpu_kullanim"] == s["gpu_kullanim"]]
    gm = [s["gpu_bellek_mib"] for s in satirlar if s["gpu_bellek_mib"] == s["gpu_bellek_mib"]]
    rt = [s["rtf"] for s in satirlar if s["rtf"] == s["rtf"]]
    cp = [s["sistem_cpu"] for s in satirlar]
    mem = [s["ana_bellek_kullanilan_mib"] for s in satirlar]
    if gu:
        print(f"IZLE gpu_kullanim% ort={statistics.mean(gu):.1f} maks={max(gu):.0f} | gpu_bellek_toplam_mib maks={max(gm):.0f} min={min(gm):.0f}", flush=True)
    if rt:
        print(f"IZLE rtf (2 sn pencere) ort={statistics.mean(rt):.4f} min={min(rt):.4f} maks={max(rt):.4f} n={len(rt)}", flush=True)
    print(f"IZLE sistem_cpu% ort={statistics.mean(cp):.1f} maks={max(cp):.0f} | ana_bellek_kullanilan_mib maks={max(mem):.0f}", flush=True)
    adlar = sorted({a for s in satirlar for a in s["surecler"]})
    for a in adlar:
        cpu = [sum(x[1] for x in s["surecler"][a]) for s in satirlar if a in s["surecler"]]
        rss = [sum(x[2] for x in s["surecler"][a]) for s in satirlar if a in s["surecler"]]
        print(f"IZLE {a}: cpu% ort={statistics.mean(cpu):.1f} maks={max(cpu):.0f} | rss_mib maks={max(rss):.0f}", flush=True)
    pids = sorted({p for s in satirlar for p in s["gpu_surec_mib"]})
    for p in pids:
        v = [s["gpu_surec_mib"][p] for s in satirlar if p in s["gpu_surec_mib"]]
        print(f"IZLE gpu_surec pid={p}: nvidia-smi bellek maks={max(v):.0f} MiB", flush=True)


def onnx_aktar(pt_yolu):
    """Ağırlık yoksa Ultralytics ile indirir (cwd = ağırlık klasörü); export(format='onnx', nms=False) ile ONNX'e aktarır."""
    import hashlib
    cevrimdisi_kanit("onnx-aktar")
    from ultralytics import YOLO
    klasor, ad = os.path.split(os.path.abspath(pt_yolu))
    os.makedirs(klasor, exist_ok=True)
    os.chdir(klasor)
    m = YOLO(ad)
    sha = hashlib.sha256(open(ad, "rb").read()).hexdigest()
    print(f"AKTAR ağırlık={ad} boyut={os.path.getsize(ad)} sha256={sha}", flush=True)
    c = cfg()
    cikti = m.export(format="onnx", imgsz=c["imgsz"], nms=False, batch=1, device="cpu", verbose=False)
    print(f"AKTAR onnx={cikti} boyut={os.path.getsize(cikti)} sha256={hashlib.sha256(open(cikti, 'rb').read()).hexdigest()} "
          f"ayarlar: format=onnx imgsz={c['imgsz']} nms=False batch=1 FP32 simplify=varsayılan opset=varsayılan dynamic=varsayılan", flush=True)
    return 0


def onnx_kontrol(pt_yolu, onnx_yolu):
    import numpy as np
    import onnx
    import onnxruntime as ort
    cevrimdisi_kanit("onnx-kontrol")
    from ultralytics import YOLO
    m = onnx.load(onnx_yolu)
    ops = [n.op_type for n in m.graph.node]
    nms_var = any("NonMaxSuppression" in o or "NMS" in o for o in ops)
    girdi = [(i.name, [d.dim_value or d.dim_param for d in i.type.tensor_type.shape.dim]) for i in m.graph.input]
    cikti = [(o.name, [d.dim_value or d.dim_param for d in o.type.tensor_type.shape.dim]) for o in m.graph.output]
    print(f"ONNX girdi={girdi} cikti={cikti} dugum_sayisi={len(ops)} NMS_dugumu_var={nms_var} opset={[(o.domain, o.version) for o in m.opset_import]}", flush=True)
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    # gerçek bir sahne karesi daha anlamlı: varsa K10 karesi
    k10 = os.environ.get("ORNEK_KARE")
    if k10 and os.path.exists(k10):
        from PIL import Image
        img = np.array(Image.open(k10).convert("RGB"))[:, :, ::-1].copy()
    pt = YOLO(pt_yolu)
    r = pt.predict(img, imgsz=int(os.environ["INF_IMGSZ"]), conf=float(os.environ["INF_CONF"]), max_det=int(os.environ["INF_MAX_DET"]), nms=False,
                   device="cpu", verbose=False)[0]
    cm = CPUModel(onnx_yolu, int(os.environ.get("YUK_CPU_ISCI_CPU", "2")))
    d = cm(img, float(os.environ["INF_CONF"]), int(os.environ["INF_MAX_DET"]), int(os.environ["INF_IMGSZ"]))
    ham = cm.s.run(None, {cm.girdi: np.zeros((1, 3, int(os.environ["INF_IMGSZ"]), int(os.environ["INF_IMGSZ"])), np.float32)})[0]
    print(f"ONNX ham_cikti_sekli={tuple(ham.shape)} dtype={ham.dtype} | PyTorch tespit={len(r.boxes)} ONNX tespit={len(d)}", flush=True)
    if len(r.boxes) and len(d):
        a = r.boxes.data.cpu().numpy()

        def iou(p, q):
            x1, y1, x2, y2 = max(p[0], q[0]), max(p[1], q[1]), min(p[2], q[2]), min(p[3], q[3])
            i = max(0.0, x2 - x1) * max(0.0, y2 - y1)
            return i / ((p[2] - p[0]) * (p[3] - p[1]) + (q[2] - q[0]) * (q[3] - q[1]) - i + 1e-9)
        eslesen, ayrintilar = 0, []
        for q in d:                      # ONNX tespiti → aynı sınıftan en yüksek IoU'lu PyTorch tespiti
            adaylar = [(iou(q[:4], p[:4]), p) for p in a if int(p[5]) == int(q[5])]
            if adaylar:
                best, p = max(adaylar, key=lambda t: t[0])
                if best > 0.5:
                    eslesen += 1
                ayrintilar.append(f"sınıf {int(q[5])}: IoU={best:.3f} güven PyTorch={p[4]:.3f} ONNX={q[4]:.3f}")
            else:
                ayrintilar.append(f"sınıf {int(q[5])}: PyTorch'ta aynı sınıfta tespit yok (ONNX güven {q[4]:.3f})")
        print(f"ONNX uyum: ONNX {len(d)} tespitin {eslesen}'i PyTorch ile IoU>0.5 eşleşti (PyTorch {len(a)} tespit)", flush=True)
        for t in ayrintilar:
            print(f"ONNX uyum ayrıntı: {t}", flush=True)
    return 0 if not nms_var else 1


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    mod = sys.argv[1]
    if mod == "dunya" and len(sys.argv) == 3:
        sdf_uret(sys.argv[2])
        return 0
    if mod == "isci" and len(sys.argv) in (6, 7):
        return isci_modu(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6] if len(sys.argv) == 7 else None)
    if mod == "izle" and len(sys.argv) == 4:
        return izle_modu(float(sys.argv[2]), sys.argv[3])
    if mod == "onnx-aktar" and len(sys.argv) == 3:
        return onnx_aktar(sys.argv[2])
    if mod == "onnx-kontrol" and len(sys.argv) == 4:
        return onnx_kontrol(sys.argv[2], sys.argv[3])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
