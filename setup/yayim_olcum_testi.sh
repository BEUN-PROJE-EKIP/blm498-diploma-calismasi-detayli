#!/usr/bin/env bash
# yayim_olcum_testi.sh — kare yayımlanma anı keşfi (FR-23): sunucu sürecinde çalışan damga bileşeninin (src/yayim_damga) derlenmesi ve ölçümü.
# Kullanım: ./yayim_olcum_testi.sh [--dry-run | --verify | -h] [saat] [k1] [uc] [px4] [kapanis]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz, derleme yapmaz; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (derleme araçları, geliştirme paketleri, ikililer, sahne üretimi, SDF doğrulaması); derleme ve süreç yok
# Ölçümler (Python tarafı: araclar/yayim_olcum.py ve araclar/kamera_olcum.py; sahne config/deney.env CAM_* değerlerinden üretilir):
#   saat      bileşenin saati (CLOCK_MONOTONIC) ile Python time.monotonic_ns() saatinin eşliği
#   k1        tek sabit kamera, CAM_K9_SIM_SN sim sn: bileşen açık iki tekrar (farklı GZ_PARTITION), bileşen kapalı bir tekrar
#   uc        üç kamera, CAM_YUK_SIM_SN sim sn: bileşen açık ve kapalı
#   px4       tek kamera + PX4 SITL (x500), CAM_YUK_SIM_SN sim sn: bileşen açık ve kapalı
#   kapanis   sunucu SIGTERM / SIGKILL ile durdurulunca bileşen kaydının sonu
# Kamera yatay görüş açısı kilitli CAM_HFOV_RAD değeridir. Ham kayıtlar .generated/yayim/<zaman>/ altına yazılır (depoya girmez). sudo gerekmez.
# Her oturum kendi GZ_PARTITION değerini kullanır; süreçler `setsid` ile ayrı grupta çalışır ve her çıkışta öldürülür.
# TAM KOŞU KAPALIDIR (çıkış 2): keşif `442da7e` sürümünde koşturuldu, bileşen kalıcı hâle getirildi; --verify ve --dry-run çalışır. Aşağıdaki ölçüm açıklamaları tarihsel kayıttır.
# Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz).
# shellcheck disable=SC2317  # tam koşu kapalıdır (exit 2 sonrası kod erişilemez; tarihsel ölçüm gövdesi korunur)
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        saat|k1|uc|px4|kapanis) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(saat k1 uc px4 kapanis)
COMPONENT_NAME="Kare yayımlanma anı keşfi (damga bileşeni)"
require_not_root
load_versions

export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
ENV_SH="$SETUP_DIR/env.sh"
VENV_PY="$ROOT_DIR/.venv/bin/python"
PY_KAMERA="$ROOT_DIR/araclar/kamera_olcum.py"
PY_YAYIM="$ROOT_DIR/araclar/yayim_olcum.py"
SRC_DIR="$ROOT_DIR/src/yayim_damga"
BUILD_DIR="$GENERATED_DIR/yayim_damga/build"
PX4_BUILD="$ROOT_DIR/third_party/PX4-Autopilot/build/px4_sitl_default"
PX4_BIN="$PX4_BUILD/bin/px4"
TMP_DIR=""
OUT_DIR=""
PGIDS=()
LAST_PG=""
GZ_PID=""

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

stop_group() { # stop_group <pgid> [sinyal] : önce TERM (ya da verilen sinyal), 3 sn sonra KILL
    local pg="$1" sig="${2:-TERM}" i
    kill -"$sig" -- "-$pg" 2>/dev/null || true
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
for v in CAM_WIDTH CAM_HEIGHT CAM_RATE_HZ CAM_ALT_M CAM_HFOV_RAD CAM_WORLD CAM_TARGETS CAM_SPACING_M CAM_K9_SIM_SN CAM_YUK_SIM_SN SIM_MODEL_TEMEL; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
# Bu ölçümde sahnenin görüş açısı kilitli CAM_HFOV_RAD'dır (kamera_olcum.py CAM_SDF_HFOV_RAD adını okur).
CAM_SDF_HFOV_RAD="$CAM_HFOV_RAD"
export CAM_WIDTH CAM_HEIGHT CAM_RATE_HZ CAM_ALT_M CAM_SDF_HFOV_RAD CAM_WORLD CAM_TARGETS CAM_SPACING_M

check_prereqs() {
    local c d
    for c in gz ss pgrep setsid timeout cmake pkg-config; do check "Araç mevcut: $c" command -v "$c"; done
    check "C++ derleyicisi (c++)" command -v c++
    check "cmake çalışıyor" cmake --version
    for c in gz-sim8 gz-rendering8 gz-transport13 gz-msgs10 gz-plugin2; do check "Geliştirme paketi (pkg-config): $c" pkg-config --exists "$c"; done
    check "Başka gz sim/ruby/px4 süreci yok (yük ve RTF ölçümünü bozar)" bash -c '! pgrep -x gz >/dev/null && ! pgrep -x ruby >/dev/null && ! pgrep -x px4 >/dev/null && ! pgrep -f "[g]z sim" >/dev/null'
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "PX4 SITL ikilisi" test -x "$PX4_BIN"
    check "PX4 gz_env.sh (rootfs)" test -f "$PX4_BUILD/rootfs/gz_env.sh"
    check "PX4 sunucu yapılandırması (eklenti listesi)" test -f "${PX4_GZ_SERVER_CONFIG:-$ROOT_DIR/third_party/PX4-Autopilot/src/modules/simulation/gz_bridge/server.config}"
    check "Bileşen kaynağı" test -f "$SRC_DIR/yayim_damga.cc"
    check "Python ölçüm kodları" test -f "$PY_YAYIM" -a -f "$PY_KAMERA"
    check "gz.transport13, gz.msgs10 (venv)" "$VENV_PY" -c 'from gz.transport13 import Node; from gz.msgs10.image_pb2 import Image'
    d="$(mktemp -d)"
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1.. alt kabukta açılır
    check "Sahne üretimi (araclar/yayim_olcum.py dunya)" bash -c '. "$1/rootfs/gz_env.sh"; exec "$2" -W ignore "$3" dunya "$4/dunya.sdf" 3 "$4" abone,bilgi,kare' _ "$PX4_BUILD" "$VENV_PY" "$PY_YAYIM" "$d"
    check "Üretilen SDF geçerli (gz sdf -k)" gz sdf -k "$d/dunya.sdf"
    rm -rf "$d"
}

print_plan() {
    log_info "[dry-run] ölçümler: ${TESTS[*]}; kamera ${CAM_WIDTH}x${CAM_HEIGHT} R8G8B8 ${CAM_RATE_HZ} Hz, ${CAM_ALT_M} m, kilitli HFOV ${CAM_HFOV_RAD} rad; dünya $CAM_WORLD"
    log_info "[dry-run] derleme: cmake -S src/yayim_damga -B .generated/yayim_damga/build (yalnız bu dizin), -j <çalışma anında tespit edilen çekirdek sayısı>"
    log_info "[dry-run] saat: saat_kontrol ikilisi 20 tur, Python time.monotonic_ns() ile aralık denetimi"
    log_info "[dry-run] k1: açık×2 (farklı GZ_PARTITION) + kapalı×1, ${CAM_K9_SIM_SN} sim sn; yöntemler abone, bilgi, kare"
    log_info "[dry-run] uc: 3 kamera açık + kapalı, ${CAM_YUK_SIM_SN} sim sn; px4: 1 kamera + PX4 SITL ($SIM_MODEL_TEMEL) açık + kapalı, ${CAM_YUK_SIM_SN} sim sn"
    log_info "[dry-run] kapanis: 30 sim sn sonra sunucuya SIGTERM ve (ayrı oturumda) SIGKILL; bileşen kaydının sonu alıcıyla karşılaştırılır"
    log_info "[dry-run] Süreç grupları (setsid) her çıkışta öldürülür; sonda px4/gz/mavsdk_server/ruby, port, /dev/shm, ros2 daemon, tc/ip denetimi"
    log_info "[dry-run] Hiçbir süreç başlatılmadı, derleme yapılmadı"
}

if [[ "$MODE" == "verify" ]]; then
    check_prereqs
    component_finish "$COMPONENT_NAME"
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
    print_plan
    component_finish "$COMPONENT_NAME"
fi

# Tam koşu KAPALIDIR: yayımlanma anı keşfi `442da7e` sürümünde koşturuldu (yöntem karşılaştırması: abone/bilgi/kare, CSV çıktısı); damga bileşeni sonradan kalıcı hâle getirildi
# (`<yontem>` parametresi ve CSV çıktısı kalktı), bu yüzden ölçüm bu betikle yeniden üretilemez. Kalıcı bileşenin doğrulaması setup/kamera_alici_testi.sh'tadır (damga birleşmesi,
# üretim→alım gecikmesi). --verify (önkoşullar) ve --dry-run çalışmaya devam eder.
log_info "Tam koşu kapatıldı: kare yayımlanma anı keşfi \`442da7e\` sürümünde koşturuldu; damga bileşeni kalıcı hâle getirildi (<yontem> parametresi ve CSV çıktısı kalktı), ölçüm bu betikle yeniden üretilemez."
log_info "Sonuçlar planlama/kararlar.md'dedir; kalıcı bileşenin doğrulaması için setup/kamera_alici_testi.sh kullanın. Hiçbir süreç başlatılmadı, derleme yapılmadı (çıkış 2)."
exit 2

check_prereqs
[[ "$COUNT_FAIL" -eq 0 ]] || fail_stop "Önkoşullar eksik"
TMP_DIR="$(mktemp -d)"
OUT_DIR="$GENERATED_DIR/yayim/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"

# --- Derleme (yalnız .generated/yayim_damga/build altına) -------------------------------
build_plugin() {
    local jobs gen=()
    jobs="$(nproc)"
    if command -v ninja >/dev/null; then gen=(-G Ninja); fi
    log_info "Derleme: cmake -S ${SRC_DIR#"$ROOT_DIR"/} -B ${BUILD_DIR#"$ROOT_DIR"/} (-j $jobs)"
    if ! cmake -S "$SRC_DIR" -B "$BUILD_DIR" "${gen[@]}" > "$TMP_DIR/cmake.log" 2>&1; then
        log_fail "cmake yapılandırması başarısız"; dump_log "$TMP_DIR/cmake.log"; return 1
    fi
    if ! cmake --build "$BUILD_DIR" -j "$jobs" > "$TMP_DIR/build.log" 2>&1; then
        log_fail "Derleme başarısız"; dump_log "$TMP_DIR/build.log"; return 1
    fi
    [[ -f "$BUILD_DIR/libYayimDamga.so" && -x "$BUILD_DIR/saat_kontrol" ]] || { log_fail "Derleme çıktısı eksik"; return 1; }
    log_ok "Bileşen derlendi: ${BUILD_DIR#"$ROOT_DIR"/}/libYayimDamga.so"
}

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

# --- Oturum ---------------------------------------------------------------------------
OTURUM_PART=""
OTURUM_DIZIN=""
# start_session <ad> <kamera_sayısı> <px4:0|1> <yöntem|hicbiri> : OTURUM_PART, OTURUM_DIZIN ayarlanır; başarısızlıkta 1
start_session() {
    local ad="$1" n="$2" px="$3" yontem="$4" d="$TMP_DIR/$1" i out
    mkdir -p "$d"
    OTURUM_DIZIN="$OUT_DIR/$ad"
    mkdir -p "$OTURUM_DIZIN"
    OTURUM_PART="yay_${ad}_$$"
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1.. alt kabukta açılır
    bash -c '. "$1/rootfs/gz_env.sh"; exec "$2" -W ignore "$3" dunya "$4/dunya.sdf" "$5" "$6" "$7"' _ \
        "$PX4_BUILD" "$VENV_PY" "$PY_YAYIM" "$d" "$n" "$OTURUM_DIZIN" "$yontem" || { log_fail "$ad: sahne üretilemedi"; return 1; }
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    start_group "$d/gz.log" env LC_NUMERIC=C GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 \
        bash -c '. "$1/rootfs/gz_env.sh"; export GZ_SIM_SYSTEM_PLUGIN_PATH="${GZ_SIM_SYSTEM_PLUGIN_PATH:+$GZ_SIM_SYSTEM_PLUGIN_PATH:}$3"; exec gz sim -r -s -v 3 "$2"' _ "$PX4_BUILD" "$d/dunya.sdf" "$BUILD_DIR"
    GZ_PID="$LAST_PG"
    for ((i = 0; i < 600; i++)); do
        out="$(GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 gz topic -l 2>/dev/null || true)"
        [[ "$out" == *"/kamera_${n}/image"* ]] && break
        sleep 0.1
    done
    if [[ "$out" != *"/kamera_${n}/image"* ]]; then
        log_fail "$ad: /kamera_${n}/image konusu 60 sn içinde görünmedi"; dump_log "$d/gz.log"; return 1
    fi
    log_info "$ad: gz hazır (GZ_PARTITION=$OTURUM_PART, $n kamera, bileşen yöntemi: $yontem)"
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

# py_calistir <ad> <zaman_aşımı_sn> <betik> <argümanlar...> : çıktıyı <tmp>/<ad>/<betik>.log dosyasına yazar; K9/YAYIM/SAAT satırlarını bilgi,
# SONUC satırlarını (+)/(-) olarak aktarır
py_calistir() {
    local ad="$1" tmo="$2" betik="$3" line rc=0 t0=$SECONDS; shift 3
    mkdir -p "$TMP_DIR/$ad"
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    env GZ_PARTITION="$OTURUM_PART" GZ_IP=127.0.0.1 \
        timeout -k 3 "$tmo" bash -c 'source "$1"; shift; exec python -W ignore "$@"' _ "$ENV_SH" "$betik" "$@" > "$TMP_DIR/$ad/$(basename "$betik").log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            K9\ *|YAYIM\ *|SAAT\ *) log_info "$ad: $line" ;;
        esac
    done < "$TMP_DIR/$ad/$(basename "$betik").log"
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: $(basename "$betik") çıkış kodu $rc ($((SECONDS - t0)) sn)"
        dump_log "$TMP_DIR/$ad/$(basename "$betik").log"
    fi
}

# kayit_oturumu <ad> <kamera_sayısı> <px4> <yöntem|hicbiri> <sim_sn> : oturumu açar, alıcıyı çalıştırır, bileşen açıksa analiz yapar
kayit_oturumu() {
    local ad="$1" n="$2" px="$3" yontem="$4" sim_sn="$5" konular="" i
    for ((i = 1; i <= n; i++)); do konular+="${konular:+,}kamera_${i}/image"; done
    if start_session "$ad" "$n" "$px" "$yontem"; then
        py_calistir "$ad" $((sim_sn * 4 + 150)) "$PY_KAMERA" kare "$konular" "$sim_sn" "$OTURUM_DIZIN/alici.csv"
        if [[ "$yontem" != "hicbiri" && -f "$OTURUM_DIZIN/alici.csv" ]]; then
            stop_all   # son boşaltma için sunucu önce durdurulur (SIGTERM)
            py_calistir "$ad" 120 "$PY_YAYIM" analiz "$OTURUM_DIZIN/alici.csv" "$OTURUM_DIZIN/yayim_damga.csv" "$ad"
            local kare_olay
            kare_olay="$(grep -c 'ilk kare olayı alındı' "$TMP_DIR/$ad/gz.log" || true)"
            log_info "$ad: kare (rendering NewImageFrame) olayı alındı mı: ${kare_olay} (sunucu günlüğünde 'ilk kare olayı alındı' satırı sayısı)"
        fi
    fi
    stop_all
}

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

olc_saat() {
    log_info "== Saat eşliği =="
    py_calistir saat 60 "$PY_YAYIM" saat "$BUILD_DIR/saat_kontrol"
}
olc_k1() {
    log_info "== k1: 1 kamera, ${CAM_K9_SIM_SN} sim sn: bileşen açık×2, kapalı×1 =="
    kayit_oturumu k1_acik_1 1 0 abone,bilgi,kare "$CAM_K9_SIM_SN"
    kayit_oturumu k1_acik_2 1 0 abone,bilgi,kare "$CAM_K9_SIM_SN"
    kayit_oturumu k1_kapali 1 0 hicbiri "$CAM_K9_SIM_SN"
}
olc_uc() {
    log_info "== uc: 3 kamera, ${CAM_YUK_SIM_SN} sim sn: açık, kapalı =="
    kayit_oturumu uc_acik 3 0 abone,bilgi,kare "$CAM_YUK_SIM_SN"
    kayit_oturumu uc_kapali 3 0 hicbiri "$CAM_YUK_SIM_SN"
}
olc_px4() {
    log_info "== px4: 1 kamera + PX4 SITL, ${CAM_YUK_SIM_SN} sim sn: açık, kapalı =="
    kayit_oturumu px4_acik 1 1 abone,bilgi,kare "$CAM_YUK_SIM_SN"
    kayit_oturumu px4_kapali 1 1 hicbiri "$CAM_YUK_SIM_SN"
}
olc_kapanis() {
    local sinyal ad
    for sinyal in TERM KILL; do
        ad="kapanis_${sinyal}"
        log_info "== kapanış: 30 sim sn sonra sunucuya SIG${sinyal} =="
        if start_session "$ad" 1 0 abone,bilgi; then
            py_calistir "$ad" 300 "$PY_KAMERA" kare "kamera_1/image" 30 "$OTURUM_DIZIN/alici.csv"
            stop_group "$GZ_PID" "$sinyal"
            sleep 1
            if [[ -f "$OTURUM_DIZIN/alici.csv" ]]; then
                py_calistir "$ad" 60 "$PY_YAYIM" kapanis "$OTURUM_DIZIN/alici.csv" "$OTURUM_DIZIN/yayim_damga.csv" "$ad" "$sinyal"
            fi
        fi
        stop_all
    done
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), PX4 $PX4_TAG; ölçümler: ${TESTS[*]}; ham kayıt: ${OUT_DIR#"$ROOT_DIR"/}"

build_plugin || fail_stop "Bileşen derlenemedi"
if want saat; then olc_saat; fi
if want k1; then olc_k1; fi
if want uc; then olc_uc; fi
if want px4; then olc_px4; fi
if want kapanis; then olc_kapanis; fi

# --- Temizlik denetimi ----------------------------------------------------------------
sleep 1
snapshot sonra
if diff -q "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" >/dev/null; then
    log_ok "Süreç denetimi: px4/gz/mavsdk_server/ruby sayıları başlangıçla aynı"
else
    log_fail "Artık süreç var: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" | tr '\n' ';' || true)"
fi
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
