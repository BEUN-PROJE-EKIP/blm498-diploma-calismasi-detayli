#!/usr/bin/env bash
# kamera_olcum_testi.sh — kamera kare damgaları ve kare sırası (K9) ile yatay görüş açısı (K10) ölçümü; başsız Gazebo, köprüsüz gz-transport.
# Kullanım: ./kamera_olcum_testi.sh [--dry-run | --verify | -h] [k9] [yuk] [k10] [hedef]
#   (argümansız)  k9, yuk ve k10'u çalıştırır; adlar verilirse yalnız onlar (hedef yalnız adı verilirse çalışır).
#   --dry-run     hiçbir süreç başlatmaz; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (ikililer, yapılandırma, sahne üretimi, SDF doğrulaması); süreç başlatmaz
# Ölçümler (Python tarafı: araclar/olcum/kamera_olcum.py; sahne config/deney.env CAM_* değerlerinden üretilir, depoya yeni SDF girmez):
#   k9    tek sabit kamera (30 m, aşağı bakan), CAM_K9_SIM_SN sim saniyesi (≥ 600 kare); iki kez, her seferinde farklı GZ_PARTITION
#   yuk   (1) tek kamera + PX4 SITL (x500) açıkken, (2) üç kamera, CAM_YUK_SIM_SN sim saniyesi (≥ 120 sn); damga katı/sıra bozuluyor mu
#   k10   yerdeki bilinen boyutlu hedeflerin piksel boyutundan yatay görüş açısı; SDF horizontal_fov ile karşılaştırma
#   hedef aday görüş açılarında (HFOV_ADAY_DERECE + CAM_SDF_HFOV_RAD karşılaştırma) önce gerçek HFOV (kalibrasyon levhaları), sonra yatan insan
#         (INSAN_YONELIM × 3 konum) ve enkaz yığınlarının piksel boyutu; kabul ölçütü OLC_DAR_KENAR_PX (yalnız ölçüm, kilit değil)
# Ham kare kaydı (damga CSV) ve K10 örnek karesi .generated/kamera/<zaman>/ altına yazılır (depoya girmez). sudo gerekmez.
# Her oturum kendi GZ_PARTITION değerini kullanır; başlatılan her süreç `setsid` ile ayrı süreç grubunda çalışır ve her çıkışta
# (hata, Ctrl-C dahil) öldürülür. Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz).
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        k9|yuk|k10|hedef) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(k9 yuk k10)
COMPONENT_NAME="Kamera damga/sıra ve görüş açısı ölçümleri"
require_not_root
load_versions

export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
ENV_SH="$SETUP_DIR/env.sh"
VENV_PY="$ROOT_DIR/.venv/bin/python"
PY_TEST="$ROOT_DIR/araclar/olcum/kamera_olcum.py"
PX4_BUILD="$ROOT_DIR/third_party/PX4-Autopilot/build/px4_sitl_default"
PX4_BIN="$PX4_BUILD/bin/px4"
TMP_DIR=""
OUT_DIR=""
PGIDS=()
LAST_PG=""

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
for v in CAM_WIDTH CAM_HEIGHT CAM_RATE_HZ CAM_ALT_M CAM_SDF_HFOV_RAD CAM_WORLD CAM_TARGETS CAM_SPACING_M CAM_K9_SIM_SN CAM_YUK_SIM_SN SIM_MODEL_TEMEL; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
for v in HFOV_ADAY_DERECE OLC_DAR_KENAR_PX INSAN_BOYUT INSAN_YONELIM ENKAZ_KUTU_SAYISI ENKAZ_CAP_M ENKAZ_YUKSEKLIK_M KALIB_KARELER; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
export CAM_WIDTH CAM_HEIGHT CAM_RATE_HZ CAM_ALT_M CAM_SDF_HFOV_RAD CAM_WORLD CAM_TARGETS CAM_SPACING_M HFOV_ADAY_DERECE OLC_DAR_KENAR_PX \
       INSAN_BOYUT INSAN_YONELIM ENKAZ_KUTU_SAYISI ENKAZ_CAP_M ENKAZ_YUKSEKLIK_M KALIB_KARELER

check_prereqs() {
    local c d
    for c in gz ss pgrep setsid timeout; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "PX4 SITL ikilisi" test -x "$PX4_BIN"
    check "PX4 gz_env.sh (rootfs)" test -f "$PX4_BUILD/rootfs/gz_env.sh"
    check "Python ölçüm kodu" test -f "$PY_TEST"
    check "gz.transport13, gz.msgs10, numpy, PIL (venv)" "$VENV_PY" -c 'from gz.transport13 import Node; from gz.msgs10.image_pb2 import Image; import numpy, PIL'
    d="$(mktemp -d)"
    check "Sahne üretimi (araclar/olcum/kamera_olcum.py dunya)" "$VENV_PY" -W ignore "$PY_TEST" dunya "$d/dunya.sdf" 3
    check "Üretilen SDF geçerli (gz sdf -k)" gz sdf -k "$d/dunya.sdf"
    rm -rf "$d"
}

print_plan() {
    log_info "[dry-run] ölçümler: ${TESTS[*]}; kamera ${CAM_WIDTH}x${CAM_HEIGHT} R8G8B8 ${CAM_RATE_HZ} Hz, ${CAM_ALT_M} m, SDF HFOV ${CAM_SDF_HFOV_RAD} rad; dünya $CAM_WORLD; hedefler $CAM_TARGETS"
    log_info "[dry-run] k9: 2 oturum (farklı GZ_PARTITION), 1 kamera, ${CAM_K9_SIM_SN} sim sn; damga katı (2·t), sıra, numara sürekliliği, sim/gerçek aralıklar, RTF"
    log_info "[dry-run] yuk: 1 kamera + PX4 SITL ($SIM_MODEL_TEMEL), sonra 3 kamera; ${CAM_YUK_SIM_SN} sim sn"
    log_info "[dry-run] k10: hedef piksel boyutu → HFOV; SDF ile karşılaştırma; örnek kare .generated/kamera/ altına"
    log_info "[dry-run] hedef: adaylar ${HFOV_ADAY_DERECE}° + karşılaştırma ${CAM_SDF_HFOV_RAD} rad; her aday için kalibrasyon levhaları (${KALIB_KARELER}) ve yatan insan (${INSAN_BOYUT} m, yönelim ${INSAN_YONELIM}° × merkez/kenar/köşe) + ${ENKAZ_KUTU_SAYISI} kutulu 3 enkaz yığını; ölçüt dar kenar ≥ ${OLC_DAR_KENAR_PX} piksel"
    log_info "[dry-run] Süreç grupları (setsid) her çıkışta öldürülür; sonda px4/gz/mavsdk_server, port, /dev/shm, ros2 daemon, tc/ip denetimi"
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
OUT_DIR="$ROOT_DIR/.generated/kamera/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"

# --- Ölçüm anlık görüntüleri -------------------------------------------------------
shm_list() { find /dev/shm -maxdepth 1 -printf '%f\n' 2>/dev/null | LC_ALL=C sort || true; }
snapshot() { # snapshot <ad>
    local n="$1"
    {
        for c in px4 gz mavsdk_server ruby; do echo "proc $c $(pgrep -x -c "$c" || true)"; done
    } > "$TMP_DIR/$n.proc"
    port_snapshot "$TMP_DIR/$n.ports"
    shm_list > "$TMP_DIR/$n.shm"
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$TMP_DIR/$n.net"
}

# --- Oturum: gz (üretilen sahne) [+ PX4 SITL] -------------------------------------------
OTURUM_PART=""
# start_session <ad> <kamera_sayısı> <px4:0|1> [dünya: kare|insan] : OTURUM_PART ayarlanır; başarısızlıkta 1
start_session() {
    local ad="$1" n="$2" px="$3" tur="${4:-kare}" d="$TMP_DIR/$1" i out
    mkdir -p "$d"
    OTURUM_PART="kam_${ad}_$$"
    if [[ "$tur" == "insan" ]]; then
        "$VENV_PY" -W ignore "$PY_TEST" dunya-insan "$d/dunya.sdf" || { log_fail "$ad: sahne üretilemedi"; return 1; }
    else
        "$VENV_PY" -W ignore "$PY_TEST" dunya "$d/dunya.sdf" "$n" || { log_fail "$ad: sahne üretilemedi"; return 1; }
    fi
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    start_group "$d/gz.log" env LC_NUMERIC=C GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 \
        bash -c '. "$1/rootfs/gz_env.sh"; exec gz sim -r -s -v 2 "$2"' _ "$PX4_BUILD" "$d/dunya.sdf"
    for ((i = 0; i < 600; i++)); do
        out="$(GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 gz topic -l 2>/dev/null || true)"
        [[ "$out" == *"/kamera_${n}/image"* ]] && break
        sleep 0.1
    done
    if [[ "$out" != *"/kamera_${n}/image"* ]]; then
        log_fail "$ad: /kamera_${n}/image konusu 60 sn içinde görünmedi"; dump_log "$d/gz.log"; return 1
    fi
    log_info "$ad: gz hazır (GZ_PARTITION=$OTURUM_PART, $n kamera)"
    if [[ "$px" -eq 1 ]]; then
        mkdir -p "$d/w0"
        # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
        start_group "$d/px4.log" env LC_NUMERIC=C GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 HEADLESS=1 \
            PX4_SIM_MODEL="$SIM_MODEL_TEMEL" PX4_GZ_WORLD="$CAM_WORLD" PX4_GZ_MODEL_POSE="40,0,0" \
            bash -c '. "$1/rootfs/gz_env.sh"; cd "$2"; exec "$1/bin/px4" -i 0 -d -s "$1/etc/init.d-posix/rcS" "$1/etc"' _ "$PX4_BUILD" "$d/w0"
        if ! wait_for_log "$d/px4.log" 'Startup script returned successfully' 90; then
            log_fail "$ad: PX4 SITL 90 sn içinde hazır olmadı"; dump_log "$d/px4.log"; return 1
        fi
        log_info "$ad: PX4 SITL ($SIM_MODEL_TEMEL) hazır ve çalışıyor (yük)"
    fi
    return 0
}

# run_py <ad> <komut-argümanları...> : Python ölçümünü çalıştırır; K9/K10 satırlarını bilgi, SONUC satırlarını (+)/(-) yapar
run_py() {
    local ad="$1" tmo="$2" line rc=0 t0=$SECONDS; shift 2
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    env GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 \
        timeout -k 3 "$tmo" bash -c 'source "$1"; shift; exec python -W ignore "$@"' _ "$ENV_SH" "$PY_TEST" "$@" > "$TMP_DIR/$ad/py.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            K9\ *|K10\ *|HEDEF\ *) log_info "$ad: $line" ;;
        esac
    done < "$TMP_DIR/$ad/py.log"
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: Python ölçümü çıkış kodu $rc ($((SECONDS - t0)) sn)"
        dump_log "$TMP_DIR/$ad/py.log"
    fi
}

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

oturum_k9() { # iki tekrar; farklı GZ_PARTITION
    local r
    for r in 1 2; do
        log_info "== K9 tekrar $r: 1 kamera, ${CAM_K9_SIM_SN} sim sn =="
        if start_session "k9_$r" 1 0; then
            run_py "k9_$r" $((CAM_K9_SIM_SN * 4 + 150)) kare "kamera_1/image" "$CAM_K9_SIM_SN" "$OUT_DIR/k9_$r.csv"
        fi
        stop_all
    done
}
oturum_yuk() {
    log_info "== Yük (1): 1 kamera + PX4 SITL, ${CAM_YUK_SIM_SN} sim sn =="
    if start_session yuk_px4 1 1; then
        run_py yuk_px4 $((CAM_YUK_SIM_SN * 4 + 150)) kare "kamera_1/image" "$CAM_YUK_SIM_SN" "$OUT_DIR/yuk_px4.csv"
    fi
    stop_all
    log_info "== Yük (2): 3 kamera, ${CAM_YUK_SIM_SN} sim sn =="
    if start_session yuk_3kamera 3 0; then
        run_py yuk_3kamera $((CAM_YUK_SIM_SN * 4 + 150)) kare "kamera_1/image,kamera_2/image,kamera_3/image" "$CAM_YUK_SIM_SN" "$OUT_DIR/yuk_3kamera.csv"
    fi
    stop_all
}
oturum_k10() {
    log_info "== K10: hedef piksel boyutu → HFOV =="
    if start_session k10 1 0; then
        run_py k10 200 k10 "kamera_1/image" "$OUT_DIR"
    fi
    stop_all
}

# hedef: aday görüş açılarında HFOV kalibrasyonu + yatan insan/enkaz piksel boyutu. Özet tablo için sonuçlar $OUT_DIR/hedef_ozet.txt'ye de yazılır.
oturum_hedef() {
    local derece rad ad f eski_fov="$CAM_SDF_HFOV_RAD" adaylar ref_derece
    ref_derece="$(awk -v r="$CAM_SDF_HFOV_RAD" 'BEGIN{printf "%.2f", r*180/3.14159265358979}')"
    adaylar="$HFOV_ADAY_DERECE $ref_derece"
    : > "$OUT_DIR/hedef_ozet.txt"
    for derece in $adaylar; do
        rad="$(awk -v d="$derece" 'BEGIN{printf "%.4f", d*3.14159265358979/180}')"
        if [[ "$derece" == "$ref_derece" ]]; then rad="$eski_fov"; fi
        export CAM_SDF_HFOV_RAD="$rad"
        log_info "== Hedef ölçümü: aday HFOV ${derece}° (SDF ${rad} rad) =="
        # (1) gerçek HFOV: kalibrasyon levhaları (konumlar görüş alanına göre ölçeklenir)
        ad="hedef_kalib_${derece}"
        export KALIB_ORANLI=1
        if start_session "$ad" 1 0 kare; then
            run_py "$ad" 200 k10 "kamera_1/image" "$OUT_DIR/kalib_${derece}"
        fi
        stop_all
        unset KALIB_ORANLI
        # (2) yatan insan ve enkaz
        ad="hedef_insan_${derece}"
        if start_session "$ad" 1 0 insan; then
            run_py "$ad" 200 hedef "kamera_1/image" "$OUT_DIR/hedef_${derece}"
        fi
        stop_all
        for f in "$TMP_DIR"/hedef_kalib_"${derece}"/py.log "$TMP_DIR"/hedef_insan_"${derece}"/py.log; do
            [[ -f "$f" ]] || continue
            { grep -E '^(K10 ozet|K10 dogru_uydurma|HEDEF)' "$f" || true; } | sed "s/^/${derece}° /" >> "$OUT_DIR/hedef_ozet.txt"
        done
    done
    export CAM_SDF_HFOV_RAD="$eski_fov"
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), PX4 $PX4_TAG; ölçümler: ${TESTS[*]}; ham kayıt: ${OUT_DIR#"$ROOT_DIR"/}"

if want k9; then oturum_k9; fi
if want yuk; then oturum_yuk; fi
if want k10; then oturum_k10; fi
if want hedef; then oturum_hedef; fi

# --- Temizlik denetimi ----------------------------------------------------------------
sleep 1
snapshot sonra
if diff -q "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" >/dev/null; then
    log_ok "Süreç denetimi: px4/gz/mavsdk_server/ruby sayıları başlangıçla aynı"
else
    log_fail "Artık süreç var: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" | tr '\n' ';' || true)"
fi
# Yalnız başlangıçta olmayan (yeni) ve sahibi testten sonra başlamış süreçlere ait dinleyiciler hata sayılır (makine geneli değil: kullanıcının tarayıcısı vb. sayılmaz): testle ilgisiz bir uygulamanın başlangıçtaki geçici portu test sırasında
# kapanabilir. Testin bıraktığı artık süreç ayrıca "Süreç denetimi" ile yakalanır; kapanan dinleyici yalnız bilgidir.
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
if diff -q "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" >/dev/null; then
    log_ok "tc/ip durumu (lo) değişmedi"
else
    log_fail "lo üzerindeki tc/ip durumu değişti: $(diff "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" | tr '\n' ';' || true)"
fi
if [[ "$DAEMON_ONCE" -eq 0 ]]; then
    if pgrep -f '[r]os2-daemon' >/dev/null; then log_fail "Artık ros2 daemon süreci var"; else log_ok "ros2 daemon süreci yok"; fi
fi

component_finish "$COMPONENT_NAME" "tamamlandı (${TESTS[*]} ve süreç/port/shm/tc denetimi)"
