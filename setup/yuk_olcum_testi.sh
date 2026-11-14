#!/usr/bin/env bash
# yuk_olcum_testi.sh — üç araç + üç kamera + üç çıkarım işçisi + Gazebo yük ölçümü (K11) ve CPU/ONNX yolu hız ölçümü (K12).
# Kullanım: ./yuk_olcum_testi.sh [--dry-run | --verify | -h] [gpu] [cpu]
#   (argümansız)  gpu ve cpu ölçümlerini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (ikililer, model dosyaları, sahne üretimi, CPU eşlemesi); süreç başlatmaz
# gpu: 3 PX4 SITL (aşağı bakan kameralı x500) + gz + 3 GPU işçisi (yolo26l.pt, nms=False, FP32, batch=1, 640); önce YUK_SIM_SN sim sn gerçek
#      hızda sürekli koşu, sonra YUK_DOYGUNLUK_SN sn doygunluk testi (bellekteki karelerle, kare hızı sınırsız); iki koşu.
# cpu: aynı sahne; yolo26s.pt → ONNX (export(format='onnx', nms=False)) → ONNX Runtime CPU, işçi başına YUK_CPU_ISCI_CPU mantıksal CPU:
#      tek işçi doygunluk, üç eşzamanlı işçi doygunluk ve gerçek hızda (YUK_CPU_SIM_SN) koşu; ONNX şeması ve PyTorch–ONNX uyumu.
# Gizlilik: Ultralytics çağıran tüm süreçler YOLO_OFFLINE=1 ile çalışır (anonim olay gönderilmez); yalnız ağırlık indirme adımı hariçtir.
# CPU eşlemesi (yalnız ölçüm koşulu): işçi başına aynı fiziksel çekirdeğin iki mantıksal CPU'su (.generated/hardware.env HW_CPU_SIBLING_PAIRS,
# çalışma anında okunur, `taskset` ile uygulanır); gz/PX4/izleme bu CPU'ların dışında çalışır. sudo gerekmez.
# Her oturum kendi GZ_PARTITION değerini kullanır; başlatılan her süreç `setsid` ile ayrı süreç grubunda çalışır ve her çıkışta
# (hata, Ctrl-C dahil) öldürülür. Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz).
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        gpu|cpu) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(gpu cpu)
COMPONENT_NAME="Yük ve çıkarım hızı ölçümleri"
require_not_root
load_versions

export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
HW_ENV="$ROOT_DIR/.generated/hardware.env"
ENV_SH="$SETUP_DIR/env.sh"
VENV_PY="$ROOT_DIR/.venv/bin/python"
PY_TEST="$ROOT_DIR/araclar/yuk_olcum.py"
PX4_BUILD="$ROOT_DIR/third_party/PX4-Autopilot/build/px4_sitl_default"
PX4_BIN="$PX4_BUILD/bin/px4"
TMP_DIR=""
OUT_DIR=""
PGIDS=()
LAST_PG=""
WORKER_PGS=()
STAGE_TAG=""
MONITOR_PG=""
OTURUM_PART=""

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

stop_group() { # stop_group <pgid> : önce TERM, 3 sn sonra KILL
    local pg="$1" i
    kill -TERM -- "-$pg" 2>/dev/null || true
    for ((i = 0; i < 30; i++)); do
        kill -0 -- "-$pg" 2>/dev/null || break
        sleep 0.1
    done
    kill -KILL -- "-$pg" 2>/dev/null || true
}
stop_all() {
    local i
    for ((i = ${#PGIDS[@]} - 1; i >= 0; i--)); do stop_group "${PGIDS[$i]}"; done
    PGIDS=()
}
exit_hook() {
    [[ "${DRY_RUN:-0}" -eq 0 && "${MODE:-install}" != verify ]] || return 0   # --dry-run/--verify hiçbir süreç başlatmaz; yaşayan (başkasına ait) koşuya DOKUNMAZ
    stop_all
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
    TMP_DIR=""
}

start_group() { # start_group <günlük> <komut...> : LAST_PG = grup lideri
    local log="$1"; shift
    setsid "$@" > "$log" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
}

wait_for_log() { # wait_for_log <dosya> <ERE> <sn>
    local f="$1" re="$2" secs="$3" i out
    for ((i = 0; i < secs * 10; i++)); do
        out="$(cat "$f" 2>/dev/null || true)"   # grep -q + pipefail tuzağı olmasın
        if [[ "$out" =~ $re ]]; then return 0; fi
        sleep 0.1
    done
    return 1
}

dump_log() {
    local f="$1" line
    log_info "---- tam çıktı: ${f#"$TMP_DIR"/} ----"
    while IFS= read -r line; do log_info "  | $line"; done < "$f"
    log_info "---- çıktı sonu ----"
}

# --- Yapılandırma ------------------------------------------------------------
[[ -f "$DENEY_ENV" ]] || fail_stop "Yapılandırma yok: $DENEY_ENV"
# shellcheck source=/dev/null
source "$DENEY_ENV"
for v in CAM_WIDTH CAM_HEIGHT CAM_RATE_HZ CAM_SDF_HFOV_RAD CAM_WORLD UAV_START_POSES INF_CONF INF_NMS INF_MAX_DET INF_IMGSZ INF_BATCH INF_PRECISION \
         INF_GPU_MODEL INF_CPU_MODEL YUK_SIM_SN YUK_DOYGUNLUK_SN YUK_KUYRUK YUK_CPU_ISCI_CPU YUK_CPU_SIM_SN; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
export CAM_WIDTH CAM_HEIGHT CAM_RATE_HZ CAM_SDF_HFOV_RAD CAM_WORLD UAV_START_POSES INF_CONF INF_NMS INF_MAX_DET INF_IMGSZ INF_BATCH \
       INF_GPU_MODEL INF_CPU_MODEL YUK_SIM_SN YUK_DOYGUNLUK_SN YUK_KUYRUK YUK_CPU_ISCI_CPU YUK_CPU_SIM_SN
# Kilitli çıkarım ayarları: değiştirilmişse durur (sonuçlara bakılarak oynanmaz)
[[ "$INF_CONF" == "0.25" && "$INF_NMS" == "False" && "$INF_MAX_DET" == "300" && "$INF_IMGSZ" == "640" && "$INF_BATCH" == "1" && "$INF_PRECISION" == "fp32" ]] \
    || fail_stop "Kilitli çıkarım ayarları değiştirilmiş (conf 0.25, nms=False, max_det 300, imgsz 640, batch 1, FP32 olmalı)"
read -r -a POSES <<< "$UAV_START_POSES"
N_UAV="${#POSES[@]}"

# CPU eşlemesi: çalışma anında .generated/hardware.env'den (numaralar kodda sabit değil)
CPU_PAIRS=()      # işçi başına "a,b"
CPU_OTHER=""      # gz/PX4/izleme için, işçi CPU'ları dışındakiler
cpu_plan() {
    [[ -f "$HW_ENV" ]] || return 1
    # shellcheck source=/dev/null
    source "$HW_ENV"
    local -a pairs cl
    read -r -a pairs <<< "${HW_CPU_SIBLING_PAIRS:-}"
    [[ "${#pairs[@]}" -ge $((N_UAV + 1)) ]] || return 1
    local i p all="" used="," c other=""
    for ((i = 0; i < N_UAV; i++)); do CPU_PAIRS+=("${pairs[$i]}"); used+="${pairs[$i]},"; done
    for p in "${pairs[@]}"; do all+="$p,"; done
    IFS=',' read -r -a cl <<< "${all%,}"
    for c in "${cl[@]}"; do [[ "$used" == *",$c,"* ]] || other+="$c,"; done
    CPU_OTHER="${other%,}"
    [[ -n "$CPU_OTHER" ]]
}

check_prereqs() {
    local c d
    for c in gz ss pgrep setsid timeout taskset nvidia-smi; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "PX4 SITL ikilisi" test -x "$PX4_BIN"
    check "PX4 gz_env.sh (rootfs)" test -f "$PX4_BUILD/rootfs/gz_env.sh"
    check "Python ölçüm kodu" test -f "$PY_TEST"
    check "GPU modeli ($INF_GPU_MODEL)" test -f "$ROOT_DIR/$INF_GPU_MODEL"
    check "venv: torch CUDA, ultralytics, onnxruntime, psutil, gz.transport13" "$VENV_PY" -W ignore -c \
        'import torch, ultralytics, onnxruntime, psutil; assert torch.cuda.is_available(); from gz.transport13 import Node; from gz.msgs10.image_pb2 import Image'
    check_warn "CPU modeli ($INF_CPU_MODEL) var" test -f "$ROOT_DIR/$INF_CPU_MODEL"
    check_warn "venv: onnx (ONNX dışa aktarımı için)" "$VENV_PY" -c 'import onnx'
    check "CPU eşlemesi .generated/hardware.env'den çıkarıldı (işçi başına kardeş çift, diğerleri ayrı)" cpu_plan
    d="$(mktemp -d)"
    check "Sahne üretimi (araclar/yuk_olcum.py dunya)" "$VENV_PY" -W ignore "$PY_TEST" dunya "$d/dunya.sdf"
    # `gz sdf -k` birleştirmeli (merge) include'ları çözemez (PX4'ün kendi x500_mono_cam_down modeli de bu denetimden geçmez); gerçek doğrulama
    # gz sim'in sahneyi yüklemesidir. Burada yalnız XML iyi biçimli mi bakılır.
    check "Üretilen SDF iyi biçimli XML" python3 -I -c 'import sys, xml.etree.ElementTree as E; E.parse(sys.argv[1])' "$d/dunya.sdf"
    rm -rf "$d"
}

print_plan() {
    cpu_plan || true
    log_info "[dry-run] ölçümler: ${TESTS[*]}; $N_UAV araç (x500 + aşağı bakan kamera ${CAM_WIDTH}x${CAM_HEIGHT} ${CAM_RATE_HZ} Hz), dünya $CAM_WORLD"
    log_info "[dry-run] çıkarım (kilitli): conf=$INF_CONF nms=$INF_NMS max_det=$INF_MAX_DET imgsz=$INF_IMGSZ batch=$INF_BATCH $INF_PRECISION"
    log_info "[dry-run] CPU eşlemesi: işçiler ${CPU_PAIRS[*]:-?}, gz/PX4/izleme ${CPU_OTHER:-?} (taskset)"
    log_info "[dry-run] gpu: 2 koşu × (gerçek hız ${YUK_SIM_SN} sim sn + doygunluk ${YUK_DOYGUNLUK_SN} sn); işçi=$INF_GPU_MODEL"
    log_info "[dry-run] cpu: $INF_CPU_MODEL → ONNX (nms=False) → ONNX Runtime; tek işçi ve üç işçi doygunluk (${YUK_DOYGUNLUK_SN} sn), üç işçi gerçek hız ${YUK_CPU_SIM_SN} sim sn; 2 koşu"
    log_info "[dry-run] Süreç grupları (setsid) her çıkışta öldürülür; sonda px4/gz/mavsdk_server, port, /dev/shm, ros2 daemon, tc/ip, GPU süreci denetimi"
    log_info "[dry-run] Hiçbir süreç başlatılmadı"
}

if [[ "$MODE" == "verify" ]]; then
    check_prereqs
    component_finish "$COMPONENT_NAME"
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
    print_plan
    component_finish "$COMPONENT_NAME"
fi

check_prereqs
[[ "$COUNT_FAIL" -eq 0 ]] || fail_stop "Önkoşullar eksik"
TMP_DIR="$(mktemp -d)"
OUT_DIR="$ROOT_DIR/.generated/yuk/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"

# --- Ölçüm anlık görüntüleri -------------------------------------------------------
shm_list() { find /dev/shm -maxdepth 1 -printf '%f\n' 2>/dev/null | LC_ALL=C sort || true; }
gpu_pids() { nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | LC_ALL=C sort | tr '\n' ' ' || true; }
snapshot() { # snapshot <ad>
    local n="$1"
    {
        for c in px4 gz mavsdk_server ruby; do echo "proc $c $(pgrep -x -c "$c" || true)"; done
    } > "$TMP_DIR/$n.proc"
    port_snapshot "$TMP_DIR/$n.ports"
    shm_list > "$TMP_DIR/$n.shm"
    gpu_pids > "$TMP_DIR/$n.gpu"
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$TMP_DIR/$n.net"
}

# --- Oturum: gz (üretilen sahne) + N PX4 SITL (araca bağlı kamera) --------------------------
start_session() { # start_session <ad>
    local ad="$1" d="$TMP_DIR/$1" i out=""
    mkdir -p "$d"
    OTURUM_PART="yuk_${ad}_$$"
    "$VENV_PY" -W ignore "$PY_TEST" dunya "$d/dunya.sdf" || { log_fail "$ad: sahne üretilemedi"; return 1; }
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    start_group "$d/gz.log" taskset -c "$CPU_OTHER" env LC_NUMERIC=C GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 \
        bash -c '. "$1/rootfs/gz_env.sh"; exec gz sim -r -s -v 2 "$2"' _ "$PX4_BUILD" "$d/dunya.sdf"
    for ((i = 0; i < 600; i++)); do
        out="$(GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 gz topic -l 2>/dev/null || true)"
        [[ "$out" == *"/kamera_${N_UAV}/image"* ]] && break
        sleep 0.1
    done
    if [[ "$out" != *"/kamera_${N_UAV}/image"* ]]; then
        log_fail "$ad: kamera konuları 60 sn içinde görünmedi"; dump_log "$d/gz.log"; return 1
    fi
    for ((i = 0; i < N_UAV; i++)); do
        mkdir -p "$d/w$i"
        # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2/$3 alt kabukta açılır
        start_group "$d/px4_$i.log" taskset -c "$CPU_OTHER" env LC_NUMERIC=C GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 HEADLESS=1 \
            PX4_SYS_AUTOSTART=4001 PX4_GZ_WORLD="$CAM_WORLD" PX4_GZ_MODEL_NAME="arac_$((i + 1))" \
            bash -c '. "$1/rootfs/gz_env.sh"; cd "$2"; exec "$1/bin/px4" -i "$3" -d -s "$1/etc/init.d-posix/rcS" "$1/etc"' _ "$PX4_BUILD" "$d/w$i" "$i"
        if ! wait_for_log "$d/px4_$i.log" 'Startup script returned successfully' 90; then
            log_fail "$ad: PX4 örneği $i 90 sn içinde hazır olmadı"; dump_log "$d/px4_$i.log"; return 1
        fi
    done
    log_info "$ad: gz hazır (GZ_PARTITION=$OTURUM_PART), $N_UAV PX4 örneği çalışıyor (araca bağlı kameralar: kamera_1..$N_UAV)"
    return 0
}

# İşçi: start_worker <ad> <tur> <i> <mod> [bayrak_dizini]; çıktı JSON'u $TMP_DIR/<ad>/isci_<i>_<mod>.json
start_worker() {
    local ad="$1" tur="$2" i="$3" mod="$4" d="$TMP_DIR/$1"
    local -a extra=()
    [[ -z "${5:-}" ]] || extra=("$5")
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1.. alt kabukta açılır
    start_group "$d/isci_${i}_${STAGE_TAG}.log" taskset -c "${CPU_PAIRS[$i]}" env GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 \
        YOLO_OFFLINE=1 INF_CPU_ONNX="${INF_CPU_ONNX:-}" \
        bash -c 'source "$1"; shift; exec python -W ignore "$@"' _ "$ENV_SH" "$PY_TEST" isci "$tur" "kamera_$((i + 1))/image" "$mod" \
        "$d/isci_${i}_${STAGE_TAG}.json" "${extra[@]+"${extra[@]}"}"
    WORKER_PGS+=("$LAST_PG")
}
wait_workers() { # wait_workers <zaman_aşımı_sn> : işçi grupları bitene kadar bekler
    local tmo="$1" t0=$SECONDS pg alive
    while :; do
        alive=0
        for pg in "${WORKER_PGS[@]}"; do
            # Süreç kimliğine bakılır (grup kimliğine değil): setsid çağrısından önceki kısa pencerede "-$pg" henüz yoktur
            if kill -0 "$pg" 2>/dev/null; then alive=1; fi
        done
        [[ "$alive" -eq 1 ]] || return 0
        if ((SECONDS - t0 > tmo)); then
            log_fail "işçiler $tmo sn içinde bitmedi"
            for pg in "${WORKER_PGS[@]}"; do stop_group "$pg"; done
            return 1
        fi
        sleep 1
    done
}

start_monitor() { # start_monitor <ad> <üst_süre_sn> <csv>
    local ad="$1" sure="$2" csv="$3" d="$TMP_DIR/$1"
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1.. alt kabukta açılır
    start_group "$d/izle_$(basename "$csv").log" taskset -c "$CPU_OTHER" env GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 \
        bash -c 'source "$1"; shift; exec python -W ignore "$@"' _ "$ENV_SH" "$PY_TEST" izle "$sure" "$csv"
    MONITOR_PG="$LAST_PG"
}
stop_monitor() { # TERM: izleyici özetini yazıp çıkar (stop_group 3 sn bekler)
    stop_group "$MONITOR_PG"
}

# ISCI satırlarını bilgi olarak yazar; işçi çıktısı yoksa (-)
rapor_isci() { # rapor_isci <ad> <etiket> <mod>
    local ad="$1" etiket="$2" mod="$3" d="$TMP_DIR/$1" f line
    for f in "$d"/isci_*_"$mod".log; do
        [[ -f "$f" ]] || continue
        while IFS= read -r line; do
            case "$line" in ISCI*|YOLO*) log_info "$etiket: $line" ;; esac
        done < "$f"
        if ! grep -q '^ISCI' "$f"; then log_fail "$etiket: işçi çıktısı yok ($(basename "$f"))"; dump_log "$f"; fi
    done
}
rapor_izle() { # rapor_izle <ad> <etiket> <csv_dosya_adı>
    local d="$TMP_DIR/$1" etiket="$2" line
    while IFS= read -r line; do
        case "$line" in IZLE*) log_info "$etiket: $line" ;; esac
    done < "$d/izle_$3.log"
}
kaydet_json() { # kaydet_json <ad> : işçi JSON'larını ham kayda kopyalar
    local ad="$1" f
    for f in "$TMP_DIR/$ad"/isci_*.json; do
        [[ -f "$f" ]] && cp "$f" "$OUT_DIR/${ad}_$(basename "$f")"
    done
    return 0
}

# Bir ölçüm aşaması: gercek (sürekli) ya da doygunluk; tüm işçiler eşzamanlı
asama() { # asama <ad> <tur> <mod> <işçi_sayısı> <etiket> <üst_süre_sn>
    local ad="$1" tur="$2" mod="$3" n="$4" etiket="$5" ust="$6" d="$TMP_DIR/$1" i csv bayrak t0
    STAGE_TAG="${mod}_${n}isci"
    csv="$OUT_DIR/${ad}_${STAGE_TAG}_izleme.csv"
    WORKER_PGS=()
    start_monitor "$ad" "$ust" "$csv"
    if [[ "$mod" == "doygunluk" ]]; then
        bayrak="$d/bayrak_${n}"; mkdir -p "$bayrak"   # her aşamada yeni, boş klasör (silme gerekmez)
        for ((i = 0; i < n; i++)); do start_worker "$ad" "$tur" "$i" "$mod" "$bayrak"; done
        t0=$SECONDS
        while [[ "$(find "$bayrak" -name 'hazir_*' | wc -l)" -lt "$n" && $((SECONDS - t0)) -lt 150 ]]; do sleep 0.5; done
        : > "$bayrak/basla"
    else
        for ((i = 0; i < n; i++)); do start_worker "$ad" "$tur" "$i" "$mod"; done
    fi
    wait_workers "$ust" || true
    stop_monitor
    rapor_isci "$ad" "$etiket" "$STAGE_TAG"
    rapor_izle "$ad" "$etiket" "$(basename "$csv")"
    kaydet_json "$ad"
}

gpu_kosu() { # gpu_kosu <n>
    local n="$1" ad="gpu_$1"
    log_info "== GPU yolu, koşu $n: $N_UAV araç + $N_UAV kamera + $N_UAV GPU işçisi + Gazebo =="
    if start_session "$ad"; then
        asama "$ad" gpu gercek "$N_UAV" "$ad gerçek hız" $((YUK_SIM_SN * 4 + 300))
        # doygunluk: işçi JSON adları farklı (mod adı dosya adında) olduğundan üst üste yazılmaz
        asama "$ad" gpu doygunluk "$N_UAV" "$ad doygunluk" $((YUK_DOYGUNLUK_SN + 240))
    fi
    stop_all
}

cpu_hazirlik() { # ağırlığı indir/aktar, ONNX şemasını ve PyTorch–ONNX uyumunu kaydet
    local onnx_yolu="${ROOT_DIR}/${INF_CPU_MODEL%.pt}.onnx" line
    export INF_CPU_ONNX="$onnx_yolu"
    if [[ ! -f "$ROOT_DIR/$INF_CPU_MODEL" ]]; then
        # Ağırlık indirme (kurulum benzeri adım): YOLO_OFFLINE=1 indirmeyi kapatacağından bu adım çevrimdışı modsuz; yalnız indirir (predict/export yok, olay üretmez)
        log_info "CPU yolu: $INF_CPU_MODEL yok; yalnız ağırlık indiriliyor"
        # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
        env YOLO_AUTOINSTALL=False bash -c 'cd "$1" && exec "$2" -W ignore -c "from ultralytics import YOLO; YOLO(\"$3\")"' _ \
            "$(dirname "$ROOT_DIR/$INF_CPU_MODEL")" "$VENV_PY" "$(basename "$INF_CPU_MODEL")" > "$TMP_DIR/indir.log" 2>&1 \
            || { log_fail "Ağırlık indirilemedi"; dump_log "$TMP_DIR/indir.log"; return 1; }
    fi
    if [[ ! -f "$onnx_yolu" ]]; then
        log_info "CPU yolu: $INF_CPU_MODEL ONNX'e aktarılıyor (export(format='onnx', nms=False); YOLO_OFFLINE=1)"
        env YOLO_OFFLINE=1 YOLO_AUTOINSTALL=False "$VENV_PY" -W ignore "$PY_TEST" onnx-aktar "$ROOT_DIR/$INF_CPU_MODEL" > "$TMP_DIR/aktar.log" 2>&1 || { log_fail "ONNX dışa aktarımı başarısız"; dump_log "$TMP_DIR/aktar.log"; return 1; }
    fi
    log_info "CPU modeli SHA-256: $(sha256sum "$ROOT_DIR/$INF_CPU_MODEL" | cut -d' ' -f1) ($INF_CPU_MODEL); ONNX: $(sha256sum "$onnx_yolu" | cut -d' ' -f1)"
    local ornek
    ornek="$("$VENV_PY" -W ignore -c 'import os, ultralytics; print(os.path.join(os.path.dirname(ultralytics.__file__), "assets", "bus.jpg"))')"
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1.. alt kabukta açılır
    env ORNEK_KARE="$ornek" YOLO_OFFLINE=1 YOLO_AUTOINSTALL=False INF_CPU_ONNX="$onnx_yolu" taskset -c "${CPU_PAIRS[0]}" \
        bash -c 'source "$1"; shift; exec python -W ignore "$@"' _ "$ENV_SH" "$PY_TEST" onnx-kontrol "$ROOT_DIR/$INF_CPU_MODEL" "$onnx_yolu" > "$OUT_DIR/onnx_kontrol.txt" 2>&1 \
        || log_fail "ONNX kontrolü başarısız (NMS düğümü var ya da hata)"
    while IFS= read -r line; do
        case "$line" in ONNX*|YOLO*) log_info "$line" ;; esac
    done < "$OUT_DIR/onnx_kontrol.txt"
    return 0
}

cpu_kosu() { # cpu_kosu <n>: tek işçi doygunluk, üç işçi doygunluk, üç işçi gerçek hız
    local n="$1" ad="cpu_$1" onceki_sim="$YUK_SIM_SN"
    log_info "== CPU yolu (ONNX Runtime), koşu $n: $N_UAV araç + $N_UAV kamera + Gazebo; işçi başına $YUK_CPU_ISCI_CPU mantıksal CPU =="
    if start_session "$ad"; then
        asama "$ad" cpu doygunluk 1 "$ad tek işçi doygunluk" $((YUK_DOYGUNLUK_SN + 240))
        asama "$ad" cpu doygunluk "$N_UAV" "$ad üç işçi doygunluk" $((YUK_DOYGUNLUK_SN + 240))
        export YUK_SIM_SN="$YUK_CPU_SIM_SN"
        asama "$ad" cpu gercek "$N_UAV" "$ad üç işçi gerçek hız" $((YUK_CPU_SIM_SN * 4 + 300))
        export YUK_SIM_SN="$onceki_sim"
    fi
    stop_all
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), PX4 $PX4_TAG; ölçümler: ${TESTS[*]}; işçi CPU çiftleri: ${CPU_PAIRS[*]}; diğer: $CPU_OTHER; ham kayıt: ${OUT_DIR#"$ROOT_DIR"/}"
log_info "GPU: $(nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null | head -1 || true)"

for t in "${TESTS[@]}"; do
    case "$t" in
        gpu) gpu_kosu 1; gpu_kosu 2 ;;
        cpu) if cpu_hazirlik; then cpu_kosu 1; cpu_kosu 2; fi ;;
    esac
done

# --- Temizlik denetimi ----------------------------------------------------------------
sleep 1
snapshot sonra
if diff -q "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" >/dev/null; then
    log_ok "Süreç denetimi: px4/gz/mavsdk_server/ruby sayıları başlangıçla aynı"
else
    log_fail "Artık süreç var: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" | tr '\n' ';' || true)"
fi
yeni_portlar="$(port_yeni "$TMP_DIR/once.ports" "$TMP_DIR/sonra.ports")"
kapanan_portlar="$(port_kapanan "$TMP_DIR/once.ports" "$TMP_DIR/sonra.ports")"
if [[ -z "$yeni_portlar" ]]; then
    log_ok "Yeni dinleyen TCP/UDP portu yok (başlangıçtakilere göre)"
else
    log_fail "Yeni dinleyen port(lar) kaldı: $yeni_portlar"
fi
if [[ -n "$kapanan_portlar" ]]; then log_info "Başlangıçta var olup kapanan dinleyiciler (testle ilgisiz, hata değil): $kapanan_portlar"; fi
shm_new="$(comm -13 "$TMP_DIR/once.shm" "$TMP_DIR/sonra.shm" | tr '\n' ' ')"
if [[ -z "$shm_new" ]]; then log_ok "/dev/shm altında yeni dosya yok"; else log_fail "/dev/shm altında artık dosya: $shm_new"; fi
if diff -q "$TMP_DIR/once.gpu" "$TMP_DIR/sonra.gpu" >/dev/null; then
    log_ok "GPU'da artık süreç yok (nvidia-smi compute-apps başlangıçla aynı)"
else
    log_fail "GPU süreç listesi değişti: önce='$(cat "$TMP_DIR/once.gpu")' sonra='$(cat "$TMP_DIR/sonra.gpu")'"
fi
if diff -q "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" >/dev/null; then
    log_ok "tc/ip durumu (lo) değişmedi"
else
    log_fail "lo üzerindeki tc/ip durumu değişti: $(diff "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" | tr '\n' ';' || true)"
fi
if [[ "$DAEMON_ONCE" -eq 0 ]]; then
    if pgrep -f '[r]os2-daemon' >/dev/null; then log_fail "Artık ros2 daemon süreci var"; else log_ok "ros2 daemon süreci yok"; fi
fi

component_finish "$COMPONENT_NAME" "tamamlandı (${TESTS[*]} ve süreç/port/shm/GPU/tc denetimi)"
