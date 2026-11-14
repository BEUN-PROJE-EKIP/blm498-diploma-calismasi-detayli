#!/usr/bin/env bash
# egitim_bellek_denemesi.sh — eğitim bellek denemesi (K13): batch=16 GPU belleğine sığıyor mu, eğitim içi doğrulama nms=False mı.
# Kullanım: ./egitim_bellek_denemesi.sh [--dry-run | --verify | -h]
#   (argümansız)  yapay deneme veri setini üretir ve kısa eğitim koşularını çalıştırır:
#                 (1) batch=TRAIN_BATCH, Ultralytics varsayılan amp, TRAIN_EPOCHS epoch, İKİ ardışık koşu
#                 (2) aynı batch, amp=False, bir koşu
#                 (3) sığma ölçütünü sağlayan en büyük batch (TRAIN_BATCH'ten başlayıp yarıya inerek; her amp kipi için, tek epoch)
#                 (4) bilgi: TRAIN_BATCH_EK batch değerleri (tek epoch; bellek yetmezse OOM yakalanır, GPU bozulmaz)
#                 (5) karşılaştırma: nms argümanı VERİLMEDEN (Ultralytics varsayılanı) bir kısa koşu: doğrulama başlığı farkını göstermek için
#   --dry-run     hiçbir süreç başlatmaz; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (GPU, model, venv, hardware.env, Ultralytics ayarları); süreç başlatmaz
# Gizlilik: eğitim süreçleri YOLO_OFFLINE=1 ile çalışır (Ultralytics anonim olay göndermez, indirme yapmaz); Python tarafı bunu doğrular ve
# süreç + çocukların loopback dışı bağlantılarını kaydeder. `ultralytics` ayar dosyasına dokunulmaz.
# Doğruluk üretilmez/yorumlanmaz; yalnız bellek, hız ve davranış. Gerçek eğitim (A8/A9) bu betiğin konusu değildir.
# Başlatılan her süreç `setsid` ile ayrı süreç grubunda çalışır ve her çıkışta (hata, Ctrl-C dahil) öldürülür. Bu betik
# install_all.sh/verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz). Hiçbir yerde `rm` kullanılmaz; çıktılar .generated/ altında kalır.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
parse_common_args "$@"
COMPONENT_NAME="Eğitim bellek denemesi"
require_not_root
load_versions

export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
VENV_PY="$ROOT_DIR/.venv/bin/python"
PY_VERI="$ROOT_DIR/araclar/egitim_deneme_veri.py"
PY_TRAIN="$ROOT_DIR/araclar/egitim_bellek_denemesi.py"
HW_ENV="$ROOT_DIR/.generated/hardware.env"
WORK_DIR="$ROOT_DIR/.generated/egitim_deneme"
OUT_DIR=""
PGIDS=()
LAST_PG=""

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

stop_group() { # stop_group <pgid> : önce TERM, 5 sn sonra KILL
    local pg="$1" i
    kill -TERM -- "-$pg" 2>/dev/null || true
    for ((i = 0; i < 50; i++)); do
        kill -0 "$pg" 2>/dev/null || break
        sleep 0.1
    done
    kill -KILL -- "-$pg" 2>/dev/null || true
}
exit_hook() {
    local i
    for ((i = ${#PGIDS[@]} - 1; i >= 0; i--)); do stop_group "${PGIDS[$i]}"; done
    PGIDS=()
}

# --- Yapılandırma ------------------------------------------------------------
[[ -f "$DENEY_ENV" ]] || fail_stop "Yapılandırma yok: $DENEY_ENV"
# shellcheck source=/dev/null
source "$DENEY_ENV"
for v in CAM_WIDTH CAM_HEIGHT TRAIN_MODEL TRAIN_IMGSZ TRAIN_BATCH TRAIN_EPOCHS TRAIN_SAVE_PERIOD TRAIN_NMS TRAIN_VERI_TOHUM TRAIN_VERI_EGITIM \
         TRAIN_VERI_DOGRULAMA TRAIN_BATCH_EK TRAIN_PAY_YUZDE TRAIN_WORKERS_MAX; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
export CAM_WIDTH CAM_HEIGHT TRAIN_MODEL TRAIN_IMGSZ TRAIN_BATCH TRAIN_EPOCHS TRAIN_SAVE_PERIOD TRAIN_NMS TRAIN_VERI_TOHUM TRAIN_VERI_EGITIM \
       TRAIN_VERI_DOGRULAMA TRAIN_BATCH_EK TRAIN_PAY_YUZDE TRAIN_WORKERS_MAX
# Belgeye göre eğitim ayarları: değiştirilmişse durur (sonuçlara bakılarak oynanmaz)
[[ "$TRAIN_IMGSZ" == "640" && "$TRAIN_BATCH" == "16" && "$TRAIN_SAVE_PERIOD" == "1" && "$TRAIN_NMS" == "False" ]] \
    || fail_stop "Belge ayarları değiştirilmiş (imgsz 640, batch 16, save_period 1, nms=False olmalı)"
[[ "$TRAIN_EPOCHS" =~ ^[23]$ ]] || fail_stop "TRAIN_EPOCHS 2 veya 3 olmalı (kısa deneme)"

check_prereqs() {
    local c sync
    for c in nvidia-smi pgrep setsid timeout ss; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "Python kodları" test -f "$PY_VERI" -a -f "$PY_TRAIN"
    check "Eğitim modeli ($TRAIN_MODEL)" test -f "$ROOT_DIR/$TRAIN_MODEL"
    check "venv: torch CUDA, ultralytics, psutil" "$VENV_PY" -W ignore -c 'import torch, ultralytics, psutil; assert torch.cuda.is_available()'
    check ".generated/hardware.env (DataLoader işçi sayısı için)" test -f "$HW_ENV"
    sync="$("$VENV_PY" -W ignore -c 'from ultralytics import settings; print(settings["sync"])' 2>/dev/null || echo '?')"
    if [[ "$sync" == "True" ]]; then
        log_warn "Ultralytics ayarında sync=True (anonim olay gönderimi); bu betik süreçlere YOLO_OFFLINE=1 verir, ayar dosyasına dokunmaz"
    else
        log_info "Ultralytics ayarında sync=$sync"
    fi
}

print_plan() {
    log_info "[dry-run] veri: $TRAIN_VERI_EGITIM eğitim + $TRAIN_VERI_DOGRULAMA doğrulama (tohum $TRAIN_VERI_TOHUM) → ${WORK_DIR#"$ROOT_DIR"/}/veri"
    log_info "[dry-run] (1) batch=$TRAIN_BATCH amp=varsayılan ${TRAIN_EPOCHS} epoch × 2 koşu; (2) amp=False 1 koşu"
    log_info "[dry-run] (3) en büyük sığan batch (yarıya inerek, her amp kipi, 1 epoch); (4) bilgi batch'leri: $TRAIN_BATCH_EK (1 epoch); (5) nms argümansız karşılaştırma"
    log_info "[dry-run] ortam: YOLO_OFFLINE=1 YOLO_AUTOINSTALL=False; sığma ölçütü: tepe reserved ≤ (toplam VRAM − başlangıç) × (1 − %$TRAIN_PAY_YUZDE)"
    log_info "[dry-run] Süreç grupları (setsid) her çıkışta öldürülür; sonda GPU süreci, port, /dev/shm, tc/ip, ros2 daemon denetimi"
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
OUT_DIR="$WORK_DIR/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"

# --- Ölçüm anlık görüntüleri -------------------------------------------------------
snapshot() { # snapshot <ad>
    local n="$1"
    port_snapshot "$OUT_DIR/$n.ports"
    find /dev/shm -maxdepth 1 -printf '%f\n' 2>/dev/null | LC_ALL=C sort > "$OUT_DIR/$n.shm" || true
    { nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | LC_ALL=C sort | tr '\n' ' ' || true; } > "$OUT_DIR/$n.gpu"
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$OUT_DIR/$n.net"
}

# json_alan <dosya> <alan> : JSON alanı (yoksa boş)
json_alan() { "$VENV_PY" -c 'import json, sys; d = json.load(open(sys.argv[1])); v = d.get(sys.argv[2]); print("" if v is None else v)' "$1" "$2" 2>/dev/null || true; }

# egitim <ad> <batch> <amp:true|false> <epoch> [nms:False|None] : bir koşu; SIGAR (True|False|boş) ayarlanır
SIGAR=""
egitim() {
    local ad="$1" batch="$2" amp="$3" epoch="$4" nms="${5:-$TRAIN_NMS}" log json rc=0 line
    log="$OUT_DIR/$ad.log"; json="$OUT_DIR/$ad.json"
    SIGAR=""
    setsid timeout -k 10 1500 env LC_NUMERIC=C YOLO_OFFLINE=1 YOLO_AUTOINSTALL=False ROOT_DIR="$ROOT_DIR" TRAIN_NMS="$nms" \
        "$VENV_PY" -W ignore "$PY_TRAIN" "$WORK_DIR/veri/data.yaml" "$OUT_DIR/runs" "$ad" "$batch" "$amp" "$epoch" "$json" > "$log" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
    wait "$LAST_PG" || rc=$?
    stop_group "$LAST_PG"
    while IFS= read -r line; do
        case "$line" in EGITIM*) log_info "$line" ;; esac
    done < "$log"
    if [[ ! -f "$json" ]]; then
        log_fail "$ad: sonuç dosyası yok (çıkış $rc); günlük sonu: $(tail -n 5 "$log" | tr '\n' '|')"
        return 0
    fi
    SIGAR="$(json_alan "$json" sigma_reserved)"
    if [[ "$(json_alan "$json" oom)" == "True" ]]; then log_info "$ad: CUDA OOM yakalandı (batch=$batch amp=$amp)"; fi
    if [[ -n "$(json_alan "$json" uzak_baglantilar | tr -d '[]')" ]]; then
        log_fail "$ad: loopback dışı ağ bağlantısı görüldü: $(json_alan "$json" uzak_baglantilar)"
    else
        log_ok "$ad: loopback dışı ağ bağlantısı yok (YOLO_OFFLINE=1; olay gönderimi aktif=$(json_alan "$json" olay_gonderimi_aktif))"
    fi
    if [[ -n "$(json_alan "$json" hata)" && "$(json_alan "$json" oom)" != "True" ]]; then
        log_fail "$ad: eğitim hatası: $(json_alan "$json" hata)"
    fi
    return 0
}

# en_buyuk_batch <amp:true|false> : TRAIN_BATCH'ten yarıya inerek sığma ölçütünü sağlayan en büyük batch; BULUNAN değişkeni
BULUNAN=""
en_buyuk_batch() {
    local amp="$1" b="$TRAIN_BATCH"
    BULUNAN=""
    while [[ "$b" -ge 1 ]]; do
        egitim "ara_b${b}_amp${amp}" "$b" "$amp" 1
        if [[ "$SIGAR" == "True" ]]; then BULUNAN="$b"; return 0; fi
        b=$((b / 2))
    done
    return 0
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor; önce durdurun"
log_info "GPU: $(nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null | head -1 || true); çıktı: ${OUT_DIR#"$ROOT_DIR"/}"
mkdir -p "$WORK_DIR/veri"
env ROOT_DIR="$ROOT_DIR" "$VENV_PY" "$PY_VERI" "$WORK_DIR/veri" > "$OUT_DIR/veri.log" 2>&1 || fail_stop "Deneme veri seti üretilemedi: $(tail -n 3 "$OUT_DIR/veri.log" | tr '\n' '|')"
log_ok "$(cat "$OUT_DIR/veri.log")"

log_info "== (1) batch=$TRAIN_BATCH, varsayılan amp, $TRAIN_EPOCHS epoch, iki ardışık koşu =="
egitim "b${TRAIN_BATCH}_amp_varsayilan_1" "$TRAIN_BATCH" true "$TRAIN_EPOCHS"
egitim "b${TRAIN_BATCH}_amp_varsayilan_2" "$TRAIN_BATCH" true "$TRAIN_EPOCHS"
log_info "== (2) batch=$TRAIN_BATCH, amp=False =="
egitim "b${TRAIN_BATCH}_amp_kapali" "$TRAIN_BATCH" false "$TRAIN_EPOCHS"
log_info "== (3) sığma ölçütünü sağlayan en büyük batch =="
en_buyuk_batch true;  log_info "En büyük sığan batch (varsayılan amp): ${BULUNAN:-bulunamadı}"
en_buyuk_batch false; log_info "En büyük sığan batch (amp=False): ${BULUNAN:-bulunamadı}"
log_info "== (4) bilgi: ek batch değerleri (tek epoch, varsayılan amp) =="
for b in $TRAIN_BATCH_EK; do egitim "ek_b${b}_amp_varsayilan" "$b" true 1; done
log_info "== (5) karşılaştırma: nms argümanı verilmeden (Ultralytics varsayılanı), batch 8, tek epoch =="
egitim "karsilastirma_nms_varsayilan_b8" 8 true 1 None

# --- Temizlik denetimi ----------------------------------------------------------------
sleep 1
snapshot sonra
if [[ "$(cat "$OUT_DIR/once.gpu")" == "$(cat "$OUT_DIR/sonra.gpu")" ]]; then
    log_ok "GPU'da artık süreç yok (nvidia-smi compute-apps başlangıçla aynı)"
else
    log_fail "GPU süreç listesi değişti: önce='$(cat "$OUT_DIR/once.gpu")' sonra='$(cat "$OUT_DIR/sonra.gpu")'"
fi
yeni_portlar="$(port_yeni "$OUT_DIR/once.ports" "$OUT_DIR/sonra.ports")"
kapanan_portlar="$(port_kapanan "$OUT_DIR/once.ports" "$OUT_DIR/sonra.ports")"
if [[ -z "$yeni_portlar" ]]; then log_ok "Yeni dinleyen TCP/UDP portu yok (başlangıçtakilere göre)"; else log_fail "Yeni dinleyen port(lar) kaldı: $yeni_portlar"; fi
if [[ -n "$kapanan_portlar" ]]; then log_info "Başlangıçta var olup kapanan dinleyiciler (testle ilgisiz, hata değil): $kapanan_portlar"; fi
shm_new="$(comm -13 "$OUT_DIR/once.shm" "$OUT_DIR/sonra.shm" | tr '\n' ' ')"
if [[ -z "$shm_new" ]]; then log_ok "/dev/shm altında yeni dosya yok"; else log_fail "/dev/shm altında artık dosya: $shm_new"; fi
if diff -q "$OUT_DIR/once.net" "$OUT_DIR/sonra.net" >/dev/null; then
    log_ok "tc/ip durumu (lo) değişmedi"
else
    log_fail "lo üzerindeki tc/ip durumu değişti: $(diff "$OUT_DIR/once.net" "$OUT_DIR/sonra.net" | tr '\n' ';' || true)"
fi
if [[ "$DAEMON_ONCE" -eq 0 ]]; then
    if pgrep -f '[r]os2-daemon' >/dev/null; then log_fail "Artık ros2 daemon süreci var"; else log_ok "ros2 daemon süreci yok"; fi
fi
if pgrep -f '[e]gitim_bellek_denemesi.py' >/dev/null; then log_fail "Artık eğitim süreci var"; else log_ok "Artık eğitim süreci yok"; fi

component_finish "$COMPONENT_NAME" "tamamlandı (eğitim bellek denemesi ve GPU/port/shm/tc denetimi)"
