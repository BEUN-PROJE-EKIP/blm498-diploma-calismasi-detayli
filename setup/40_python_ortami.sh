#!/usr/bin/env bash
# 40_python_ortami.sh — .venv oluşturur; PyTorch (CUDA), Ultralytics, MAVSDK, ONNX Runtime, ONNX (+onnxslim), NumPy, SciPy kurar.
# Kullanım: ./40_python_ortami.sh [--dry-run | --verify | --update-lock | -h]
#   (argümansız)  kurar (sudo gerekmez; yalnız proje içine yazar), sonda doğrular; kuruluysa atlar.
#                 Kilit dosyası VARSA tüm pip kurulumları kısıtlayıcıyla (-c kilit) yapılır; kilit üzerine yazılmaz,
#                 kurulum sonrası freeze .generated/python-freeze.txt dosyasına yazılıp kilitle karşılaştırılır.
#   --update-lock kilidi bilinçli güncellemek için: kısıtlayıcı KULLANILMAZ, kurulum sonrası freeze kilide yazılır
#   --dry-run     hiçbir şey kurmaz/değiştirmez; yapacağı komutları yazar
#   --verify      yalnız denetim (ağsız/sudosuz): sürümler, CUDA, sm_120, YOLO çıkarımı, mavsdk_server, onnxruntime, scipy
#                 (Ultralytics çağıran doğrulama süreci YOLO_OFFLINE=1 ile çalışır; anonim olay gönderilmez. Kurulumdaki ağırlık indirme hariçtir)
#   Ağırlıklar (kurulum ağ gerektirir; doğrulama gerektirmez): config/deney.env'deki INF_GPU_MODEL (GPU yolu), INF_CPU_MODEL (B planı, CPU arka ucu) ve CPU arka ucunun ONNX dosyası ISCI_CPU_ONNX temin edilir
#   (yoksa indirilir/aktarılır; YOLO_OFFLINE=1 ile: anonim olay gönderilmez). `.pt` dosyalarının SHA-256'sı setup/locks/agirlik-sha256.txt ile doğrulanır; uyuşmazlık açık (-). ONNX aktarımı bayt bayt
#   belirlenimci DEĞİLDİR (aynı .pt'den iki aktarım farklı özet verir): özet listesine girmez, türetilmiş dosya olarak kaynak .pt özeti ve aktarım ayarları listede KAYITLIDIR; --verify varlığını ve geçerli şemasını denetler.
#   --update-lock Python kilidiyle birlikte ağırlık özet listesini de MEVCUT dosyalardan yeniden yazar (bilinçli güncelleme).
# Sürümler yalnız setup/versions.env içindedir. Kilit dosyaları: setup/locks/python-requirements.lock.txt, setup/locks/agirlik-sha256.txt
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# --update-lock betiğe özgü bayrak; ortak ayrıştırıcıya geçmeden ayır.
UPDATE_LOCK=0
ARGS=()
for a in "$@"; do
    if [[ "$a" == "--update-lock" ]]; then UPDATE_LOCK=1; else ARGS+=("$a"); fi
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
if [[ "$UPDATE_LOCK" -eq 1 && "$MODE" == "verify" ]]; then echo "--update-lock ile --verify birlikte kullanılamaz" >&2; exit 2; fi
COMPONENT_NAME="Python ortamı"
require_not_root
load_versions

VENV="$ROOT_DIR/.venv"
PY="$VENV/bin/python"
LOCK_FILE="$SETUP_DIR/locks/python-requirements.lock.txt"
FREEZE_FILE="$GENERATED_DIR/python-freeze.txt"
# Ağırlıkların adı ve yeri YALNIZ config/deney.env'den okunur (INF_GPU_MODEL, INF_CPU_MODEL, ISCI_CPU_ONNX)
# (test amaçlı: DENEY_ENV ve AGIRLIK_LISTESI ortam değişkenleri yapılandırmayı/listeyi yalnız o çağrı için değiştirir; asıl dosyalara dokunmadan bozuk-kopya denemesi içindir)
DENEY_DOSYASI="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
# shellcheck source=/dev/null
source "$DENEY_DOSYASI"
GPU_PT="$ROOT_DIR/$INF_GPU_MODEL"
CPU_PT="$ROOT_DIR/$INF_CPU_MODEL"
CPU_ONNX="$ROOT_DIR/$ISCI_CPU_ONNX"
MODELS_DIR="$(dirname "$GPU_PT")"
MODEL_NAME="$(basename "$GPU_PT")"
WEIGHT_LOCK="${AGIRLIK_LISTESI:-$SETUP_DIR/locks/agirlik-sha256.txt}"
TORCH_FULL="${TORCH_VERSION}+${TORCH_CUDA_TAG}"
TV_FULL="${TORCHVISION_VERSION}+${TORCH_CUDA_TAG}"
TORCH_INDEX="https://download.pytorch.org/whl/${TORCH_CUDA_TAG}"
START=$SECONDS

pkg_version() { # pkg_version <paket> : venv içindeki sürüm (yoksa boş)
    [[ -x "$PY" ]] || return 0
    "$PY" -m pip show "$1" 2>/dev/null | sed -n 's/^Version: //p' || true
}

want_installed() { # want_installed <paket> <sürüm>
    [[ "$(pkg_version "$1")" == "$2" ]]
}

# Kısıtlayıcı: kilit varsa ve --update-lock verilmediyse tüm pip install komutlarına -c eklenir (geçişli bağımlılıklar kilitten gelir).
CONSTRAINT=()
if [[ -f "$LOCK_FILE" && "$UPDATE_LOCK" -eq 0 ]]; then CONSTRAINT=(-c "$LOCK_FILE"); fi

# --- Ağırlıklar ---------------------------------------------------------------
rel_yol() { printf '%s' "${1#"$ROOT_DIR"/}"; }

lock_sha() { # lock_sha <göreli_yol> : listedeki özet (yoksa boş); '#' ile başlayan satırlar açıklamadır
    [[ -f "$WEIGHT_LOCK" ]] || return 0
    awk -v p="$1" '$0 !~ /^#/ && $2 == p {print $1; exit}' "$WEIGHT_LOCK"
}

weight_check() { # weight_check <pt_yolu> : varlık + SHA-256 (listeyle); (+)/(-) yazar
    local f="$1" rel got want
    rel="$(rel_yol "$f")"
    if [[ ! -f "$f" ]]; then log_fail "Ağırlık yok: $rel (kurulum: ./setup/40_python_ortami.sh)"; return 0; fi
    got="$(sha256sum "$f" | cut -d' ' -f1)"
    want="$(lock_sha "$rel")"
    if [[ -z "$want" ]]; then
        log_fail "Ağırlık özet listesinde yok: $rel (${WEIGHT_LOCK#"$ROOT_DIR"/}; özet $got)"
    elif [[ "$got" == "$want" ]]; then
        log_ok "Ağırlık SHA-256 listeyle uyuşuyor: $rel (${got:0:16}…)"
    else
        log_fail "Ağırlık SHA-256 UYUŞMUYOR: $rel (bulunan ${got:0:16}…, listede ${want:0:16}…): dosya bozuk ya da kaynak değişmiş"
    fi
}

onnx_check() { # onnx_check <onnx_yolu> : varlık + geçerli ONNX şeması (NMS'siz uçtan uca baş: [1, 300, 6])
    local f="$1" rel out rc=0
    rel="$(rel_yol "$f")"
    if [[ ! -f "$f" ]]; then log_fail "ONNX yok: $rel (kurulum: ./setup/40_python_ortami.sh)"; return 0; fi
    out="$("$PY" -I -W ignore -c 'import sys, onnx; m = onnx.load(sys.argv[1]); onnx.checker.check_model(m); o = m.graph.output[0]; print([d.dim_value for d in o.type.tensor_type.shape.dim])' "$f" 2>&1)" || rc=$?
    if [[ "$rc" -eq 0 && "$out" == "[1, 300, 6]" ]]; then
        log_ok "ONNX geçerli ve NMS'siz uçtan uca çıktı biçimi $out: $rel (özet listede değil: aktarım belirlenimci değil)"
    else
        log_fail "ONNX geçersiz ya da beklenen çıktı biçimi değil ([1, 300, 6]; bulunan: $(tail -n 1 <<< "$out")): $rel"
    fi
}

weight_fetch() { # weight_fetch <pt_yolu> : yoksa indirir (YOLO_OFFLINE=1: anonim olay yok); sonra özeti listeyle karşılaştırır
    local f="$1" rel
    rel="$(rel_yol "$f")"
    if [[ -f "$f" ]]; then
        log_ok "Ağırlık zaten var: $rel"
    elif [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] (cd $(rel_yol "$(dirname "$f")") && YOLO_OFFLINE=1 $PY -c \"from ultralytics import YOLO; YOLO('$(basename "$f")')\")"
        return 0
    else
        mkdir -p "$(dirname "$f")"
        run "Ağırlık indiriliyor ($(basename "$f"))" bash -c 'cd "$1" && YOLO_OFFLINE=1 "$2" -c "from ultralytics import YOLO; YOLO(\"$3\")"' _ "$(dirname "$f")" "$PY" "$(basename "$f")"
    fi
    if [[ "$DRY_RUN" -eq 0 ]]; then weight_check "$f"; fi
}

onnx_fetch() { # onnx_fetch : CPU arka ucunun ONNX dosyası yoksa CPU .pt'den NMS'siz aktarır (araclar/olcum/yuk_olcum.py onnx-aktar; YOLO_OFFLINE=1)
    local rel
    rel="$(rel_yol "$CPU_ONNX")"
    if [[ -f "$CPU_ONNX" ]]; then
        log_ok "ONNX zaten var: $rel"
    elif [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] YOLO_OFFLINE=1 $PY araclar/olcum/yuk_olcum.py onnx-aktar $(rel_yol "$CPU_PT")  (export(format='onnx', nms=False); çıktı $rel)"
        return 0
    else
        [[ -f "$CPU_PT" ]] || { log_fail "ONNX aktarımı için kaynak ağırlık yok: $(rel_yol "$CPU_PT")"; return 0; }
        # shellcheck disable=SC2016  # tek tırnak bilerek: $1.. alt kabukta açılır
        run "ONNX aktarılıyor ($(basename "$CPU_PT") → $(basename "$CPU_ONNX"), nms=False)" bash -c 'set -a; source "$1"; set +a; cd "$2" && YOLO_OFFLINE=1 YOLO_AUTOINSTALL=False "$3" -W ignore araclar/olcum/yuk_olcum.py onnx-aktar "$4"' _ "$DENEY_DOSYASI" "$ROOT_DIR" "$PY" "$CPU_PT"
    fi
    if [[ "$DRY_RUN" -eq 0 ]]; then onnx_check "$CPU_ONNX"; fi
}

weights_install() {
    weight_fetch "$GPU_PT"
    weight_fetch "$CPU_PT"
    onnx_fetch
    if [[ "$DRY_RUN" -eq 0 && ( ! -f "$WEIGHT_LOCK" || "$UPDATE_LOCK" -eq 1 ) ]]; then weights_write_lock; fi
}

weights_write_lock() { # özet listesini MEVCUT dosyalardan yazar (yalnız liste yoksa ya da --update-lock ile)
    local f tmp="$WEIGHT_LOCK.tmp"
    [[ -f "$GPU_PT" && -f "$CPU_PT" ]] || { log_warn "Ağırlıklardan biri yok: özet listesi yazılmadı"; return 0; }
    {
        echo "# Model ağırlıkları SHA-256 listesi (kaynak: Ultralytics indirme; takım kuralı: ağırlıklar depoya girmez, özetle izlenir). Biçim: sha256sum (özet, iki boşluk, proje köküne göre yol)."
        echo "# Yalnız bilinçli güncellenir: ./setup/40_python_ortami.sh --update-lock"
        (cd "$ROOT_DIR" && sha256sum -- "$(rel_yol "$GPU_PT")" "$(rel_yol "$CPU_PT")")
        echo "# ONNX (türetilmiş, özet listede YOK): $(rel_yol "$CPU_ONNX") — kaynak $(rel_yol "$CPU_PT") (SHA-256 yukarıda); ayarlar: Ultralytics export(format='onnx', imgsz=INF_IMGSZ, nms=False, batch=1, device='cpu'), FP32, simplify/opset/dynamic varsayılan;"
        echo "# aynı .pt'den iki aktarım FARKLI SHA-256 verir (aktarım bayt bayt belirlenimci değil), bu yüzden özet listesine girmez; --verify varlığını ve geçerli şemasını ([1, 300, 6]) denetler."
    } > "$tmp"
    mv "$tmp" "$WEIGHT_LOCK"
    log_ok "Ağırlık özet listesi yazıldı: ${WEIGHT_LOCK#"$ROOT_DIR"/}"
}

# --- Kurulum -----------------------------------------------------------------
install_component() {
    # 1) venv
    if [[ -x "$PY" ]]; then
        log_ok "venv zaten var: $VENV"
    elif python3 -c "import ensurepip" >/dev/null 2>&1; then
        run "venv oluşturuluyor" python3 -m venv --system-site-packages "$VENV"
    elif [[ "$DRY_RUN" -eq 1 ]]; then
        log_warn "python3-venv (ensurepip) yok: gerçek modda durulur; önce 05_temel_paketler.sh çalıştırılmalı"
        log_info "[dry-run] python3 -m venv --system-site-packages $VENV"
    else
        log_fail "python3-venv (ensurepip) yok: önce 05_temel_paketler.sh (python3-venv) çalıştırılmalı"
        component_failed "$COMPONENT_NAME"
        exit 1
    fi

    # 2) PyTorch + torchvision (CUDA tekerlekleri)
    if want_installed torch "$TORCH_FULL" && want_installed torchvision "$TV_FULL"; then
        log_ok "torch $TORCH_FULL ve torchvision $TV_FULL zaten kurulu"
    else
        run "PyTorch kuruluyor ($TORCH_FULL)" "$PY" -m pip install --disable-pip-version-check --no-input \
            "${CONSTRAINT[@]}" --index-url "$TORCH_INDEX" "torch==$TORCH_FULL" "torchvision==$TV_FULL"
    fi

    # 3) PyPI paketleri (sabit sürümler): yalnız sürümü uyuşmayan/eksik olanlar kurulur (aşağı sürüme geçiş dahil);
    #    torch/ultralytics gibi doğru sürümdekiler yeniden kurulmaz.
    local spec pkg want
    local -a todo=()
    for spec in "ultralytics==$ULTRALYTICS_VERSION" "mavsdk==$MAVSDK_VERSION" "onnxruntime==$ONNXRUNTIME_VERSION" \
                "onnx==$ONNX_VERSION" "onnxslim==$ONNXSLIM_VERSION" "numpy==$NUMPY_VERSION" "scipy==$SCIPY_VERSION"; do
        pkg="${spec%%==*}"; want="${spec#*==}"
        if want_installed "$pkg" "$want"; then
            log_ok "$pkg $want zaten kurulu"
        else
            log_info "$pkg: kurulu '$(pkg_version "$pkg")', istenen '$want'"
            todo+=("$spec")
        fi
    done
    if [[ "${#todo[@]}" -gt 0 ]]; then
        run "PyPI paketleri kuruluyor: ${todo[*]}" "$PY" -m pip install --disable-pip-version-check --no-input "${CONSTRAINT[@]}" "${todo[@]}"
    fi

    # 4) Kilit dosyası: depodaki kilit ÜZERİNE YAZILMAZ (yalnız ilk üretimde veya --update-lock ile).
    #    Kurulum sonrası freeze .generated/ altına yazılır ve kilitle karşılaştırılır.
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] $PY -m pip freeze --local > ${FREEZE_FILE#"$ROOT_DIR"/}; kilitle karşılaştırılır"
        if [[ ! -f "$LOCK_FILE" || "$UPDATE_LOCK" -eq 1 ]]; then log_info "[dry-run] freeze → ${LOCK_FILE#"$ROOT_DIR"/} (kilit yok veya --update-lock)"; fi
    else
        freeze_pkgs "$PY" "$FREEZE_FILE"
        if [[ ! -f "$LOCK_FILE" || "$UPDATE_LOCK" -eq 1 ]]; then
            mkdir -p "$(dirname "$LOCK_FILE")"
            cp "$FREEZE_FILE" "$LOCK_FILE.tmp"; mv "$LOCK_FILE.tmp" "$LOCK_FILE"
            log_ok "Kilit dosyası yazıldı: ${LOCK_FILE#"$ROOT_DIR"/} ($(wc -l < "$LOCK_FILE") paket)"
        else
            lock_report "venv" "$LOCK_FILE" "$FREEZE_FILE"
        fi
    fi

    # 5) Ön eğitimli ağırlıklar (bir kez): GPU yolu (.pt), CPU arka ucu (.pt) ve CPU arka ucunun NMS'siz ONNX dosyası; .pt özetleri listeyle doğrulanır
    weights_install
}

# --- Doğrulama ---------------------------------------------------------------
read -r -d '' PY_VERIFY <<'PYCODE' || true
import os, sys, time, subprocess
import importlib.metadata as md

def out(kind, msg):
    print(f"{kind} {msg}", flush=True)

def section(fn):
    try:
        fn()
    except Exception as e:  # her bölüm bağımsız; biri düşse de diğerleri çalışır
        out("FAIL", f"{fn.__name__}: {type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}")

E = os.environ
expected = [
    ("torch", f"{E['TORCH_VERSION']}+{E['TORCH_CUDA_TAG']}"),
    ("torchvision", f"{E['TORCHVISION_VERSION']}+{E['TORCH_CUDA_TAG']}"),
    ("ultralytics", E["ULTRALYTICS_VERSION"]),
    ("mavsdk", E["MAVSDK_VERSION"]),
    ("onnxruntime", E["ONNXRUNTIME_VERSION"]),
    ("onnx", E["ONNX_VERSION"]),
    ("onnxslim", E["ONNXSLIM_VERSION"]),
    ("numpy", E["NUMPY_VERSION"]),
    ("scipy", E["SCIPY_VERSION"]),
]

def versions():
    for name, want in expected:
        try:
            got = md.version(name)
        except md.PackageNotFoundError:
            got = None
        if got == want:
            out("OK", f"{name} {got} (beklenen)")
        else:
            out("FAIL", f"{name} sürümü {want} olmalı; bulunan: {got}")

def info_versions():
    for name in ("grpcio", "protobuf", "aiogrpc"):
        try:
            out("INFO", f"{name} {md.version(name)}")
        except md.PackageNotFoundError:
            out("INFO", f"{name} kurulu değil")

def cuda():
    import torch
    out("INFO", f"torch {torch.__version__}, torch CUDA {torch.version.cuda}")
    if not torch.cuda.is_available():
        out("FAIL", "torch.cuda.is_available() yanlış")
        return
    out("OK", "torch.cuda.is_available() doğru")
    name = torch.cuda.get_device_name(0)
    smi = E.get("NVSMI_GPU", "")
    if smi and name == smi:
        out("OK", f"GPU adı nvidia-smi ile aynı: {name}")
    else:
        out("FAIL", f"GPU adı uyuşmuyor: torch='{name}' nvidia-smi='{smi}'")
    cap = torch.cuda.get_device_capability(0)
    if cap == (12, 0):
        out("OK", f"get_device_capability() = {cap}")
    else:
        out("WARN", f"get_device_capability() = {cap} (RTX 50 serisi için (12, 0) beklenir)")
    arch = torch.cuda.get_arch_list()
    out("INFO", f"get_arch_list() = {arch}")
    if "sm_120" in arch or "compute_120" in arch:
        out("OK", "arch listesinde sm_120/compute_120 var")
    else:
        out("FAIL", "arch listesinde sm_120/compute_120 yok")
    g = torch.Generator().manual_seed(0)
    a = torch.randn(512, 512, generator=g)
    b = torch.randn(512, 512, generator=g)
    gpu = (a.cuda() @ b.cuda()).cpu()
    cpu = a @ b
    if torch.allclose(gpu, cpu, rtol=1e-3, atol=1e-3):
        out("OK", f"GPU matris çarpımı CPU ile uyuşuyor (en büyük fark {float((gpu - cpu).abs().max()):.2e})")
    else:
        out("FAIL", f"GPU matris çarpımı CPU ile uyuşmuyor (en büyük fark {float((gpu - cpu).abs().max()):.2e})")

def yolo():
    import numpy as np
    from ultralytics import YOLO
    out("OK", "from ultralytics import YOLO")
    # Gizlilik: bu süreç YOLO_OFFLINE=1 ile çalışır; Ultralytics anonim olay göndermemeli (settings sync=True olsa bile)
    import ultralytics.utils as U
    from ultralytics.utils.events import events
    if not U.ONLINE and not events.enabled:
        out("OK", f"Ultralytics çevrimdışı: YOLO_OFFLINE={os.environ.get('YOLO_OFFLINE')} ONLINE={U.ONLINE} olay gönderimi aktif={events.enabled} (settings sync={U.SETTINGS['sync']})")
    else:
        out("FAIL", f"Ultralytics çevrimdışı DEĞİL: ONLINE={U.ONLINE} olay gönderimi aktif={events.enabled}")
        return
    path = os.path.join(E["MODELS_DIR"], E["MODEL_NAME"])
    if not os.path.isfile(path):
        out("WARN", f"ağırlık dosyası yok ({path}); çıkarım denetimi atlandı (kur modunda indirilir)")
        return
    model = YOLO(path)
    out("OK", f"{E['MODEL_NAME']} yüklendi")
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)  # 640x480 RGB (yükseklik 480, genişlik 640)
    kw = dict(imgsz=640, conf=0.25, nms=False, device=0, batch=1, half=False, verbose=False)
    res = model.predict(img, **kw)
    ok = isinstance(res, list) and len(res) == 1 and hasattr(res[0], "boxes") and res[0].boxes.xyxy.shape[-1] == 4
    if not ok:
        out("FAIL", "predict çıktı biçimi beklenen değil")
        return
    out("OK", f"predict çalıştı; çıktı biçimi uygun ({len(res[0].boxes)} kutu)")
    import torch
    for _ in range(30):  # ısınma
        model.predict(img, **kw)
    torch.cuda.synchronize()
    n = 30
    t0 = time.perf_counter()
    for _ in range(n):
        model.predict(img, **kw)
    torch.cuda.synchronize()
    ms = (time.perf_counter() - t0) / n * 1000.0
    fps = 1000.0 / ms
    with open(os.path.join(E["GENERATED_DIR"], "gpu_hizi.txt"), "w") as f:
        f.write(f"model={E['MODEL_NAME']} imgsz=640 batch=1 half=False nms=False\n")
        f.write(f"gpu={torch.cuda.get_device_name(0)} torch={torch.__version__}\n")
        f.write(f"isinma=30 olcum={n}\n")
        f.write(f"ortalama_cikarim_ms={ms:.2f}\nfps={fps:.1f}\n")
        f.write("not=Tek süreç, boşta GPU; gerçek koşul (3 işçi + Gazebo) ayrı bir ölçümde belirlenecek.\n")
    out("INFO", f"çıkarım (30 ısınma + {n} ölçüm): ortalama {ms:.2f} ms/kare, {fps:.1f} FPS (yalnız bilgi)")

def _free_port(kind):
    import socket
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def _heartbeat(seq):
    # Asgari MAVLink v2 HEARTBEAT (sysid 1, compid 1); crc_extra = 50
    import struct
    payload = struct.pack("<IBBBBB", 0, 2, 3, 0, 4, 3)
    body = bytes([9, 0, 0, seq & 0xFF, 1, 1, 0, 0, 0]) + payload
    c = 0xFFFF
    for b in body + bytes([50]):
        t = b ^ (c & 0xFF)
        t = (t ^ (t << 4)) & 0xFF
        c = ((c >> 8) ^ (t << 8) ^ (t << 3) ^ (t >> 4)) & 0xFFFF
    return b"\xfd" + body + struct.pack("<H", c)

def mavsdk_server():
    import mavsdk, socket
    exe = os.path.join(os.path.dirname(mavsdk.__file__), "bin", "mavsdk_server")
    if not os.access(exe, os.X_OK):
        out("FAIL", f"mavsdk_server yok veya çalıştırılabilir değil: {exe}")
        return
    out("OK", "mavsdk_server ikilisi var ve çalıştırılabilir")
    r = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=30)
    if r.returncode == 0 and "-p" in r.stdout:
        out("OK", "mavsdk_server --help çalışıyor")
    else:
        out("FAIL", f"mavsdk_server --help beklenmeyen sonuç (çıkış kodu {r.returncode})")
        return
    # Duman testi (PX4 yok): `-p <gRPC portu> udpin://127.0.0.1:<udp>`; gRPC portu, bir MAVLink
    # sistemi keşfedilince açılır, bu yüzden sahte HEARTBEAT gönderilir.
    gport = _free_port(socket.SOCK_STREAM)
    uport = _free_port(socket.SOCK_DGRAM)
    p = subprocess.Popen([exe, "-p", str(gport), "udpin://127.0.0.1:%d" % uport],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        t0 = time.time()
        up = False
        seq = 0
        while time.time() - t0 < 4 and not up:
            if p.poll() is not None:
                break
            udp.sendto(_heartbeat(seq), ("127.0.0.1", uport)); seq += 1
            time.sleep(0.25)
            c = socket.socket()
            c.settimeout(0.2)
            try:
                c.connect(("127.0.0.1", gport)); up = True
            except OSError:
                pass
            c.close()
        udp.close()
        if up:
            out("OK", f"mavsdk_server duman testi: gRPC portu 127.0.0.1:{gport} dinliyor ({time.time() - t0:.1f} sn)")
        else:
            out("FAIL", f"mavsdk_server duman testi: gRPC portu {gport} açılmadı (süreç çıkış kodu: {p.poll()})")
    finally:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill(); p.wait()
    out("OK" if p.poll() is not None else "FAIL", "mavsdk_server süreci temizlendi")

def numerics():
    import numpy as np
    import onnx
    import onnxruntime as ort
    from scipy.optimize import linear_sum_assignment
    out("OK", f"import onnx {onnx.__version__} (ONNX dışa aktarımı için)")
    prov = ort.get_available_providers()
    if "CPUExecutionProvider" in prov:
        out("OK", f"onnxruntime sağlayıcıları: {prov}")
    else:
        out("FAIL", f"onnxruntime CPUExecutionProvider yok: {prov}")
    cost = np.array([[4, 1, 3], [2, 0, 5], [3, 2, 2]])
    r, c = linear_sum_assignment(cost)
    if list(c) == [1, 0, 2] and int(cost[r, c].sum()) == 5:
        out("OK", "scipy linear_sum_assignment beklenen atamayı verdi")
    else:
        out("FAIL", f"scipy linear_sum_assignment beklenmeyen sonuç: {list(c)}")

for fn in (versions, info_versions, cuda, yolo, mavsdk_server, numerics):
    section(fn)
PYCODE

verify_component() {
    if [[ ! -x "$PY" ]]; then
        log_fail "venv yok: $VENV"
        return 0
    fi
    log_ok "venv var: $VENV"
    local pyver
    pyver="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if [[ "$pyver" == "$PYTHON_REQUIRED" ]]; then log_ok "venv Python sürümü: $pyver"; else log_fail "venv Python sürümü $PYTHON_REQUIRED olmalı; bulunan: $pyver"; fi
    check "pip check temiz" "$PY" -m pip check
    if [[ ! -f "$WEIGHT_LOCK" ]]; then log_fail "Ağırlık özet listesi yok: ${WEIGHT_LOCK#"$ROOT_DIR"/}"; fi
    weight_check "$GPU_PT"
    weight_check "$CPU_PT"
    onnx_check "$CPU_ONNX"
    freeze_pkgs "$PY" "$FREEZE_FILE"
    lock_report "venv" "$LOCK_FILE" "$FREEZE_FILE"

    local smi_name="" line
    if have_cmd nvidia-smi; then smi_name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | sed -n 1p || true)"; fi
    mkdir -p "$MODELS_DIR"
    local prev=""
    while IFS= read -r line; do
        if [[ "$line" == "$prev" ]]; then continue; fi   # yinelenen (ör. Ultralytics) uyarılarını bir kez yaz
        prev="$line"
        case "$line" in
            "OK "*)   log_ok "${line#OK }" ;;
            "FAIL "*) log_fail "${line#FAIL }" ;;
            "WARN "*) log_warn "${line#WARN }" ;;
            "INFO "*) log_info "${line#INFO }" ;;
            *)        log_info "  $line" ;;
        esac
    done < <(YOLO_OFFLINE=1 TORCH_VERSION="$TORCH_VERSION" TORCH_CUDA_TAG="$TORCH_CUDA_TAG" TORCHVISION_VERSION="$TORCHVISION_VERSION" \
             ULTRALYTICS_VERSION="$ULTRALYTICS_VERSION" MAVSDK_VERSION="$MAVSDK_VERSION" \
             ONNXRUNTIME_VERSION="$ONNXRUNTIME_VERSION" ONNX_VERSION="$ONNX_VERSION" ONNXSLIM_VERSION="$ONNXSLIM_VERSION" NUMPY_VERSION="$NUMPY_VERSION" SCIPY_VERSION="$SCIPY_VERSION" \
             NVSMI_GPU="$smi_name" MODELS_DIR="$MODELS_DIR" MODEL_NAME="$MODEL_NAME" GENERATED_DIR="$GENERATED_DIR" \
             "$PY" -c "$PY_VERIFY" 2>>"$LOG_FILE")
}

if [[ "$MODE" == "install" ]]; then
    install_component
fi
if [[ "$MODE" == "verify" || "$DRY_RUN" -eq 0 ]]; then
    verify_component
fi
log_info "Geçen süre: $((SECONDS - START)) sn"
component_finish "$COMPONENT_NAME"
