#!/usr/bin/env bash
# arac_kimlik_testi.sh — tek araç ve üç araç bağlantı/kimlik testleri ile simülasyon/PX4 zaman ekseni ölçümü (başsız Gazebo + PX4 SITL).
# Kullanım: ./arac_kimlik_testi.sh [--dry-run | --verify | -h] [tek] [uc] [zaman]
#   (argümansız)  üç testi de çalıştırır; adlar verilirse yalnız onlar. `tek` ve `zaman` aynı tek araçlı oturumu paylaşır.
#   --dry-run     hiçbir süreç başlatmaz; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (ikililer, yapılandırma tutarlılığı); süreç başlatmaz
# Testler (Python tarafı: araclar/arac_kimlik_testi.py):
#   tek    PX4 örneği 0 (MAV_SYS_ID=1, UDP 14540) + mavsdk_server (gRPC 50051): sistem kimliği doğrulanır; yanlış beklenen kimlikle komut reddedilir
#   uc     3 PX4 örneği aynı Gazebo dünyasında, 3 mavsdk_server: her araç kendi kimliğiyle eşleşir, çapraz bağlanma reddedilir, aynı anda akış
#   zaman  tek araç: gz /world/<dünya>/clock (sim saati) ile PX4 IMU zamanı ≥ ZAMAN_SURE_SN boyunca karşılaştırılır (fark, eğim, RTF)
# Kimlik, port, ad alanı ve konumlar config/deney.env'den okunur (betikte sabit yok). Arm/kalkış YOK. sudo gerekmez.
# Her oturum kendi GZ_PARTITION değerini kullanır; başlatılan her süreç `setsid` ile ayrı süreç grubunda çalışır ve her çıkışta
# (hata, Ctrl-C dahil) öldürülür. Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz).
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

# Test adları betiğe özgü; ortak ayrıştırıcıya geçmeden ayır.
TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        tek|uc|zaman) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(tek uc zaman)
COMPONENT_NAME="Araç kimlik ve zaman ekseni testleri"
require_not_root
load_versions

export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
ENV_SH="$SETUP_DIR/env.sh"
VENV_PY="$ROOT_DIR/.venv/bin/python"
PY_TEST="$ROOT_DIR/araclar/arac_kimlik_testi.py"
PX4_BUILD="$ROOT_DIR/third_party/PX4-Autopilot/build/px4_sitl_default"
PX4_BIN="$PX4_BUILD/bin/px4"
ZAMAN_SURE_SN="${ZAMAN_SURE_SN:-70}"
TMP_DIR=""
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
cleanup_all() {
    local pg
    for ((i = ${#PGIDS[@]} - 1; i >= 0; i--)); do stop_group "${PGIDS[$i]}"; done
    PGIDS=()
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
    TMP_DIR=""
}
exit_hook() { cleanup_all; }

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
for v in UAV_SYS_IDS UAV_NAMESPACES UAV_START_POSES PX4_MAVLINK_PORTS MAVSDK_GRPC_PORTS SIM_WORLD SIM_MODEL_TEMEL; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
read -r -a SYS_IDS <<< "$UAV_SYS_IDS"
read -r -a NSS <<< "$UAV_NAMESPACES"
read -r -a POSES <<< "$UAV_START_POSES"
read -r -a UDPS <<< "$PX4_MAVLINK_PORTS"
read -r -a GRPCS <<< "$MAVSDK_GRPC_PORTS"
N_UAV="${#SYS_IDS[@]}"

config_check() { # PX4 SITL kuralları: MAV_SYS_ID = örnek+1, UDP = 14540+örnek; listeler aynı uzunlukta
    local i
    [[ "${#NSS[@]}" -eq "$N_UAV" && "${#POSES[@]}" -eq "$N_UAV" && "${#UDPS[@]}" -eq "$N_UAV" && "${#GRPCS[@]}" -eq "$N_UAV" ]] || return 1
    for ((i = 0; i < N_UAV; i++)); do
        [[ "${SYS_IDS[$i]}" -eq $((i + 1)) ]] || return 1
        [[ "${UDPS[$i]}" -eq $((14540 + i)) ]] || return 1
    done
}
mavsdk_server_bin() { "$VENV_PY" -c 'import os, warnings; warnings.filterwarnings("ignore"); import mavsdk; print(os.path.join(os.path.dirname(mavsdk.__file__), "bin", "mavsdk_server"))' 2>/dev/null; }

check_prereqs() {
    local c ms
    for c in gz ss pgrep setsid timeout; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "PX4 SITL ikilisi" test -x "$PX4_BIN"
    check "PX4 gz_env.sh (rootfs)" test -f "$PX4_BUILD/rootfs/gz_env.sh"
    check "Python test kodu" test -f "$PY_TEST"
    ms="$(mavsdk_server_bin || true)"
    check "mavsdk_server ikilisi (venv)" test -x "$ms"
    check "Yapılandırma tutarlı ($N_UAV araç: sys_id=örnek+1, UDP=14540+örnek, listeler eşit uzunlukta)" config_check
    check "gz.transport13 + gz.msgs10 (venv)" "$VENV_PY" -c 'from gz.transport13 import Node; from gz.msgs10.clock_pb2 import Clock'
}

print_plan() {
    local i
    log_info "[dry-run] testler: ${TESTS[*]}; GZ_PARTITION oturum başına ayrı; dünya $SIM_WORLD, model $SIM_MODEL_TEMEL (başsız)"
    for ((i = 0; i < N_UAV; i++)); do
        log_info "[dry-run] araç $((i + 1)): px4 -i $i (MAV_SYS_ID ${SYS_IDS[$i]}, UDP ${UDPS[$i]}, konum ${POSES[$i]}), mavsdk_server -p ${GRPCS[$i]} udpin://0.0.0.0:${UDPS[$i]}, ad alanı /${NSS[$i]}"
    done
    log_info "[dry-run] tek: 1 araç; kimlik doğrulama (MAVSDK param MAV_SYS_ID), yanlış kimlikle komut reddi, sağlık/konum akışı"
    log_info "[dry-run] uc: $N_UAV araç; kimlik, çapraz bağlanma reddi, aynı anda akış"
    log_info "[dry-run] zaman: tek araç, ${ZAMAN_SURE_SN} sn, gz /world/$SIM_WORLD/clock ile PX4 IMU zamanı; fark, eğim, RTF"
    log_info "[dry-run] Süreç grupları (setsid) her çıkışta öldürülür; sonda px4/gz/mavsdk_server, port, /dev/shm, ros2 daemon denetimi"
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
[[ "$COUNT_FAIL" -eq 0 ]] || fail_stop "Önkoşullar eksik veya yapılandırma tutarsız"
MAVSDK_SERVER="$(mavsdk_server_bin)"
TMP_DIR="$(mktemp -d)"

# --- Ölçüm anlık görüntüleri -------------------------------------------------------
shm_list() { find /dev/shm -maxdepth 1 -printf '%f\n' 2>/dev/null | LC_ALL=C sort || true; }
snapshot() { # snapshot <ad>
    local n="$1"
    {
        for c in px4 gz mavsdk_server ruby; do echo "proc $c $(pgrep -x -c "$c" || true)"; done
    } > "$TMP_DIR/$n.proc"
    ss -lntuH 2>/dev/null | awk '{print $1, $5}' | LC_ALL=C sort > "$TMP_DIR/$n.ports" || true
    shm_list > "$TMP_DIR/$n.shm"
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$TMP_DIR/$n.net"
}

# --- Oturum: gz + N PX4 örneği + N mavsdk_server ------------------------------------
# start_session <ad> <araç_sayısı> : OTURUM_PART değişkenini ayarlar; başarısızlıkta 1
OTURUM_PART=""
start_session() {
    local ad="$1" n="$2" d="$TMP_DIR/$1" i pg
    mkdir -p "$d"
    OTURUM_PART="arac_${ad}_$$"
    for ((i = 0; i < n; i++)); do
        mkdir -p "$d/w$i"
        # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2/$3 alt kabukta açılır
        # İlk örnek Gazebo dünyasını başlatır; sonrakiler çalışan dünyaya model ekler (aynı GZ_PARTITION).
        start_group "$d/px4_$i.log" env LC_NUMERIC=C GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 HEADLESS=1 \
            PX4_SIM_MODEL="$SIM_MODEL_TEMEL" PX4_GZ_WORLD="$SIM_WORLD" PX4_GZ_MODEL_POSE="${POSES[$i]}" \
            bash -c '. "$1/rootfs/gz_env.sh"; cd "$2"; exec "$1/bin/px4" -i "$3" -d -s "$1/etc/init.d-posix/rcS" "$1/etc"' _ "$PX4_BUILD" "$d/w$i" "$i"
        pg="$LAST_PG"
        if ! wait_for_log "$d/px4_$i.log" 'Startup script returned successfully' 90; then
            log_fail "$ad: PX4 örneği $i 90 sn içinde hazır olmadı"
            dump_log "$d/px4_$i.log"; return 1
        fi
        log_info "$ad: PX4 örneği $i hazır (MAV_SYS_ID ${SYS_IDS[$i]}, UDP ${UDPS[$i]}, konum ${POSES[$i]})"
        # başlatılan modelin kanıtı: Gazebo konu listesinde bu örneğin modeli var ve kamera/görüntü algılayıcısı YOK (kamerasız temel gövde: $SIM_MODEL_TEMEL)
        local konular
        konular="$(GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 timeout 10 gz topic -l 2>/dev/null || true)"
        if [[ "$konular" == *"/model/${SIM_MODEL_TEMEL#gz_}_$i/"* && "$konular" != *"/image"* ]]; then
            log_ok "$ad: başlatılan model ${SIM_MODEL_TEMEL#gz_}_$i (kamerasız temel gövde $SIM_MODEL_TEMEL; Gazebo konularında görüntü (kamera) konusu yok)"
        else
            log_fail "$ad: başlatılan model beklenen kamerasız ${SIM_MODEL_TEMEL#gz_}_$i değil (Gazebo konu listesi: $(grep -c . <<< "$konular") konu; görüntü konuları: $(grep '/image' <<< "$konular" | tr '\n' ' ' || true))"
        fi
        : "$pg"
    done
    for ((i = 0; i < n; i++)); do
        start_group "$d/mavsdk_server_$i.log" "$MAVSDK_SERVER" -p "${GRPCS[$i]}" "udpin://0.0.0.0:${UDPS[$i]}"
    done
    sleep 2
    return 0
}

stop_session() { # tüm grupları ters sırayla durdur
    local i
    for ((i = ${#PGIDS[@]} - 1; i >= 0; i--)); do stop_group "${PGIDS[$i]}"; done
    PGIDS=()
}

# run_py <ad> <mod> : Python testini çalıştırır; SONUC satırlarını (+)/(-) yapar; ham zaman satırlarını bilgi olarak yazar
run_py() {
    local ad="$1" mod="$2" d="$TMP_DIR/$1" rc=0 line t0=$SECONDS
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2/$3 alt kabukta açılır
    env GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 UAV_SYS_IDS="$UAV_SYS_IDS" UAV_NAMESPACES="$UAV_NAMESPACES" \
        PX4_MAVLINK_PORTS="$PX4_MAVLINK_PORTS" MAVSDK_GRPC_PORTS="$MAVSDK_GRPC_PORTS" SIM_WORLD="$SIM_WORLD" ZAMAN_SURE_SN="$ZAMAN_SURE_SN" \
        timeout -k 3 330 bash -c 'source "$1"; exec python "$2" "$3"' _ "$ENV_SH" "$PY_TEST" "$mod" > "$d/py_$mod.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "${line#SONUC kaldi }" ;;
            ZAMAN_*) log_info "$line" ;;
        esac
    done < "$d/py_$mod.log"
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$mod: Python testi çıkış kodu $rc ($((SECONDS - t0)) sn)"
        dump_log "$d/py_$mod.log"
    fi
}

run_session_tek() {  # tek ve zaman aynı oturumda
    local want_tek=0 want_zaman=0 t
    for t in "${TESTS[@]}"; do [[ "$t" == tek ]] && want_tek=1; [[ "$t" == zaman ]] && want_zaman=1; done
    [[ $((want_tek + want_zaman)) -gt 0 ]] || return 0
    log_info "== Oturum: tek araç =="
    if start_session tek 1; then
        [[ "$want_tek" -eq 1 ]] && run_py tek tek
        [[ "$want_zaman" -eq 1 ]] && run_py tek zaman
    fi
    stop_session
}
run_session_uc() {
    local t found=0
    for t in "${TESTS[@]}"; do [[ "$t" == uc ]] && found=1; done
    [[ "$found" -eq 1 ]] || return 0
    log_info "== Oturum: $N_UAV araç =="
    if start_session uc "$N_UAV"; then
        run_py uc uc
    fi
    stop_session
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), PX4 $PX4_TAG, mavsdk $MAVSDK_VERSION; testler: ${TESTS[*]}"

run_session_tek
run_session_uc

# --- Temizlik denetimi ----------------------------------------------------------------
sleep 1
snapshot sonra
if diff -q "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" >/dev/null; then
    log_ok "Süreç denetimi: px4/gz/mavsdk_server/ruby sayıları başlangıçla aynı"
else
    log_fail "Artık süreç var: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" | tr '\n' ';' || true)"
fi
# Yalnız başlangıçta olmayan (yeni) dinleyiciler hata sayılır: testle ilgisiz bir uygulamanın başlangıçtaki geçici portu test sırasında
# kapanabilir. Testin bıraktığı artık süreç ayrıca "Süreç denetimi" ile yakalanır; kapanan dinleyici yalnız bilgidir.
port_yeni="$(LC_ALL=C comm -13 "$TMP_DIR/once.ports" "$TMP_DIR/sonra.ports" | tr '\n' ';' || true)"
port_kapanan="$(LC_ALL=C comm -23 "$TMP_DIR/once.ports" "$TMP_DIR/sonra.ports" | tr '\n' ';' || true)"
if [[ -z "$port_yeni" ]]; then
    log_ok "Yeni dinleyen TCP/UDP portu yok (başlangıçtakilere göre)"
else
    log_fail "Yeni dinleyen port(lar) kaldı: $port_yeni"
fi
if [[ -n "$port_kapanan" ]]; then log_info "Başlangıçta var olup kapanan dinleyiciler (testle ilgisiz, hata değil): $port_kapanan"; fi
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
