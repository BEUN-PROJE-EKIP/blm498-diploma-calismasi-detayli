#!/usr/bin/env bash
# runtime_smoke.sh — çalışma zamanı duman testleri: bileşenlerin BİRLİKTE çalıştığını gösterir (kurulum denetimi değil).
# Kullanım: ./runtime_smoke.sh [--dry-run | --verify | -h]
#   (argümansız)  T1-T4'ü çalıştırır, sonda süreç/port/tc/ip denetimi yapar (sudo gerekmez; arm/kalkış YOK)
#   --dry-run     hiçbir süreç başlatmaz; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar ve ikililer var mı); süreç başlatmaz
# Testler:
#   T1  gz sim sunucusu + venv Python'unda gz.transport13/gz.msgs10 ile GERÇEK mesaj (/clock aboneliği, Image yayın/al)
#   T2  venv: torch + ultralytics + rclpy aynı süreçte; rclpy.init / düğüm / shutdown
#   T3  ROS 2 talker/listener (demo_nodes_cpp, sonra venv DIŞI sistem Python'uyla demo_nodes_py)
#   T4  PX4 SITL + Gazebo (başsız) + MAVSDK: udp://:14540 bağlan, health/konum örneği al
# Her test ayrı GZ_PARTITION / ROS_DOMAIN_ID kullanır; başlatılan her süreç `setsid` ile ayrı süreç grubunda çalışır ve
# her çıkışta (hata, Ctrl-C dahil) öldürülür. Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz).
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
parse_common_args "$@"
COMPONENT_NAME="Çalışma zamanı duman testleri"
require_not_root
load_versions

export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

# Ctrl-C / SIGTERM: normal çıkışa çevir ki EXIT tuzağı (exit_hook) süreçleri öldürsün.
trap 'exit 130' INT
trap 'exit 143' TERM

ENV_SH="$SETUP_DIR/env.sh"
VENV_PY="$ROOT_DIR/.venv/bin/python"
PX4_BUILD="$ROOT_DIR/third_party/PX4-Autopilot/build/px4_sitl_default"
PX4_BIN="$PX4_BUILD/bin/px4"
TMP_DIR=""
PGIDS=()           # başlatılan süreç grupları (grup lideri PID'leri)
LAST_PG=""

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

# --- Süreç grubu yönetimi ----------------------------------------------------
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
    for pg in "${PGIDS[@]+"${PGIDS[@]}"}"; do stop_group "$pg"; done
    PGIDS=()
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
    TMP_DIR=""
}
exit_hook() { cleanup_all; }

start_group() { # start_group <günlük> <komut...> : arka planda, kendi oturumunda; LAST_PG = grup lideri
    local log="$1"; shift
    setsid "$@" > "$log" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
}

# run_group_wait <sn> <günlük> <komut...> : zaman aşımlı çalıştırır, bitmesini bekler, grubu temizler; komutun çıkış kodunu döndürür
run_group_wait() {
    local secs="$1" log="$2"; shift 2
    local rc=0
    start_group "$log" timeout -k 3 "$secs" "$@"
    wait "$LAST_PG" || rc=$?
    stop_group "$LAST_PG"
    return "$rc"
}

wait_for_log() { # wait_for_log <dosya> <ERE> <sn> : desen görünene kadar bekler
    local f="$1" re="$2" secs="$3" i
    for ((i = 0; i < secs * 10; i++)); do
        if grep -qE "$re" "$f" 2>/dev/null; then return 0; fi
        sleep 0.1
    done
    return 1
}

dump_log() { # tam günlüğü (kısaltmadan) log'a yazar
    local f="$1" line
    log_info "---- tam çıktı: ${f#"$TMP_DIR"/} ----"
    while IFS= read -r line; do log_info "  | $line"; done < "$f"
    log_info "---- çıktı sonu ----"
}

# Kullanıcının etkin bir venv'i varsa sistem Python'u testi (T3-py) bozulmasın: venv bin yolu PATH'ten çıkarılır.
clean_path() { local p="" d; local IFS=':'; for d in $PATH; do [[ "$d" == "$ROOT_DIR/.venv/bin" || "$d" == "$ROOT_DIR/.venv-px4/bin" ]] || p+="${p:+:}$d"; done; echo "$p"; }

snapshot() { # snapshot <ad> : süreç sayıları, dinleyen portlar, tc/ip durumu
    local n="$1"
    {
        for c in gz px4 mavsdk_server ruby; do echo "proc $c $(pgrep -x -c "$c" || true)"; done
    } > "$TMP_DIR/$n.proc"
    ss -lntuH 2>/dev/null | awk '{print $1, $5}' | LC_ALL=C sort > "$TMP_DIR/$n.ports" || true
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$TMP_DIR/$n.net"
}

# --- Python yardımcıları (geçici dizine yazılır) -----------------------------
write_helpers() {
    cat > "$TMP_DIR/t1.py" <<'PY'
import sys, time, traceback
try:
    import google.protobuf
    from gz.transport13 import Node
    from gz.msgs10.clock_pb2 import Clock
    from gz.msgs10.image_pb2 import Image
    n = Node()
    got = []
    if not n.subscribe(Clock, "/clock", lambda m: got.append(m.sim.sec + m.sim.nsec * 1e-9)):
        raise RuntimeError("/clock aboneliği başarısız")
    t0 = time.time()
    while len(got) < 5 and time.time() - t0 < 20:
        time.sleep(0.1)
    if len(got) < 5:
        raise RuntimeError(f"/clock: yalnız {len(got)} mesaj alındı (>=5 gerekli)")
    print(f"CLOCK mesaj={len(got)} ilk_sim={got[0]:.3f} son_sim={got[-1]:.3f} protobuf={google.protobuf.__version__}")
    rx = []
    if not n.subscribe(Image, "/smoke/image", lambda m: rx.append(m)):
        raise RuntimeError("Image aboneliği başarısız")
    pub = n.advertise("/smoke/image", Image)
    payload = bytes(range(24))
    img = Image()
    img.width = 4; img.height = 2; img.step = 12; img.pixel_format_type = 3
    img.data = payload
    time.sleep(1.0)
    t0 = time.time()
    while not rx and time.time() - t0 < 10:
        pub.publish(img); time.sleep(0.1)
    if not rx:
        raise RuntimeError("Image mesajı alınamadı")
    m = rx[0]
    if (m.width, m.height, m.step) != (4, 2, 12) or m.data != payload:
        raise RuntimeError(f"Image içeriği uyuşmuyor: {m.width}x{m.height} step={m.step} veri_uzunluk={len(m.data)}")
    print(f"IMAGE ok boyut={m.width}x{m.height} bayt={len(m.data)} icerik_esit=True")
except Exception:
    traceback.print_exc()
    sys.exit(1)
PY
    cat > "$TMP_DIR/t2.py" <<'PY'
import sys, traceback
try:
    import torch, ultralytics, rclpy
    print(f"torch={torch.__version__} ultralytics={ultralytics.__version__} rclpy={getattr(rclpy, '__file__', '?')} python={sys.version.split()[0]}")
    rclpy.init()
    node = rclpy.create_node("smoke_node")
    rclpy.spin_once(node, timeout_sec=0.1)
    name = node.get_name()
    node.destroy_node()
    rclpy.shutdown()
    print(f"rclpy init/düğüm({name})/shutdown ok")
except Exception:
    traceback.print_exc()
    sys.exit(1)
PY
    cat > "$TMP_DIR/t4.py" <<'PY'
import asyncio, sys, time, traceback, warnings
warnings.filterwarnings("ignore")
async def main():
    from mavsdk import System
    s = System()
    await s.connect(system_address="udp://:14540")
    t0 = time.time()
    async for st in s.core.connection_state():
        if st.is_connected:
            print(f"bağlı sure={time.time() - t0:.1f}sn"); break
    async for h in s.telemetry.health():
        print(f"health global_position_ok={h.is_global_position_ok} local_position_ok={h.is_local_position_ok} home_ok={h.is_home_position_ok}"); break
    async for p in s.telemetry.position():
        print(f"konum lat={p.latitude_deg:.5f} lon={p.longitude_deg:.5f} yuk={p.absolute_altitude_m:.1f}"); break
try:
    asyncio.run(asyncio.wait_for(main(), 50))
except Exception:
    traceback.print_exc()
    sys.exit(1)
PY
}

# --- Testler -----------------------------------------------------------------
test_t1() {
    local d="$TMP_DIR/t1" t0=$SECONDS rc=0 part="smoke_t1_$$" out
    mkdir -p "$d"
    start_group "$d/gz.log" env GZ_PARTITION="$part" gz sim -s -r -v 2 empty.sdf
    local gzpg="$LAST_PG"
    run_group_wait 60 "$d/py.log" bash -c 'source "$1"; export GZ_PARTITION="$2"; exec python "$3"' _ "$ENV_SH" "$part" "$TMP_DIR/t1.py" || rc=$?
    stop_group "$gzpg"
    if [[ "$rc" -eq 0 ]]; then
        while IFS= read -r out; do log_info "T1: $out"; done < <(grep -E '^(CLOCK|IMAGE)' "$d/py.log")
        log_ok "T1 gz sunucusu + gz.transport13/gz.msgs10 (venv, protobuf) gerçek mesaj alışverişi ($((SECONDS - t0)) sn)"
    else
        log_fail "T1 gz + Python bağlama BAŞARISIZ (çıkış $rc, $((SECONDS - t0)) sn)"
        dump_log "$d/py.log"; dump_log "$d/gz.log"
    fi
}

test_t2() {
    local d="$TMP_DIR/t2" t0=$SECONDS rc=0 out
    mkdir -p "$d"
    run_group_wait 60 "$d/py.log" bash -c 'source "$1"; export ROS_DOMAIN_ID="$2" ROS_LOCALHOST_ONLY=1; exec python "$3"' _ "$ENV_SH" "$((100 + RANDOM % 100))" "$TMP_DIR/t2.py" || rc=$?
    if [[ "$rc" -eq 0 ]]; then
        while IFS= read -r out; do log_info "T2: $out"; done < <(grep -E '^(torch|rclpy)' "$d/py.log")
        log_ok "T2 rclpy + torch + ultralytics aynı süreçte (venv); rclpy.init/düğüm/shutdown ($((SECONDS - t0)) sn)"
    else
        log_fail "T2 rclpy + venv BAŞARISIZ (çıkış $rc, $((SECONDS - t0)) sn)"
        dump_log "$d/py.log"
    fi
}

# ros_pair <etiket> <paket> : talker + listener, <=8 sn, listener >=3 mesaj; venv dışı (ROS setup.bash + temiz PATH)
ros_pair() {
    local label="$1" pkg="$2" d="$TMP_DIR/t3_$1" t0=$SECONDS dom n=0 i
    mkdir -p "$d"
    dom=$((100 + RANDOM % 100))
    local cpath; cpath="$(clean_path)"
    local -a envv=(env -u VIRTUAL_ENV PATH="$cpath" ROS_DOMAIN_ID="$dom" ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST RMW_IMPLEMENTATION=rmw_fastrtps_cpp)
    start_group "$d/listener.log" "${envv[@]}" bash -c 'source "/opt/ros/$1/setup.bash"; exec ros2 run "$2" listener' _ "$ROS_DISTRO" "$pkg"
    local lpg="$LAST_PG"
    start_group "$d/talker.log" "${envv[@]}" bash -c 'source "/opt/ros/$1/setup.bash"; exec ros2 run "$2" talker' _ "$ROS_DISTRO" "$pkg"
    local tpg="$LAST_PG"
    for ((i = 0; i < 80; i++)); do
        n="$(grep -c 'I heard' "$d/listener.log" 2>/dev/null || true)"
        [[ "${n:-0}" -ge 3 ]] && break
        sleep 0.1
    done
    stop_group "$tpg"; stop_group "$lpg"
    n="$(grep -c 'I heard' "$d/listener.log" 2>/dev/null || true)"
    if [[ "${n:-0}" -ge 3 ]]; then
        log_ok "T3 $label: $pkg talker/listener, domain $dom, listener $n mesaj aldı ($((SECONDS - t0)) sn)"
    else
        log_fail "T3 $label: $pkg listener yalnız ${n:-0} mesaj aldı (>=3 gerekli, domain $dom, $((SECONDS - t0)) sn)"
        dump_log "$d/listener.log"; dump_log "$d/talker.log"
    fi
}

test_t3() {
    ros_pair "cpp" demo_nodes_cpp
    ros_pair "py (sistem Python, venv dışı)" demo_nodes_py
}

test_t4() {
    local d="$TMP_DIR/t4" t0=$SECONDS rc=0 part="smoke_t4_$$" out
    mkdir -p "$d/work"
    # Başlatma: make hedefi 'gz_x500', ninja ile güncellik denetimi yapıp aynı komutu çalıştırır
    # (cmake -E env PX4_SIM_MODEL=gz_x500 PX4_GZ_WORLD=… GZ_IP=127.0.0.1 …/bin/px4). Derleme ağacına dosya yazmasın
    # ve ninja yeniden yapılandırması tetiklenmesin diye aynı ortamla ikili doğrudan, geçici çalışma dizininde başlatılır
    # (-d: etkileşimli kabuk yok; günlük/parametre dosyaları geçici dizinde kalır ve silinir).
    start_group "$d/px4.log" env LC_NUMERIC=C GZ_PARTITION="$part" GZ_IP=127.0.0.1 HEADLESS=1 PX4_SIM_MODEL=gz_x500 PX4_GZ_WORLD=default \
        bash -c '. "$1/rootfs/gz_env.sh"; cd "$2"; exec "$1/bin/px4" -d -s "$1/etc/init.d-posix/rcS" "$1/etc"' _ "$PX4_BUILD" "$d/work"
    local pxpg="$LAST_PG"
    if ! wait_for_log "$d/px4.log" 'Startup script returned successfully' 60; then
        log_fail "T4 PX4 SITL 60 sn içinde hazır olmadı ($((SECONDS - t0)) sn)"
        dump_log "$d/px4.log"; stop_group "$pxpg"; return 0
    fi
    log_info "T4: PX4 hazır ($((SECONDS - t0)) sn, 'Startup script returned successfully')"
    run_group_wait 70 "$d/py.log" bash -c 'source "$1"; exec python "$2"' _ "$ENV_SH" "$TMP_DIR/t4.py" || rc=$?
    stop_group "$pxpg"
    if [[ "$rc" -eq 0 ]]; then
        while IFS= read -r out; do log_info "T4: $out"; done < <(grep -E '^(bağlı|health|konum)' "$d/py.log")
        log_ok "T4 PX4 SITL + Gazebo (başsız) + MAVSDK udp://:14540 bağlantısı, health ve konum örneği ($((SECONDS - t0)) sn)"
    else
        log_fail "T4 PX4 + MAVSDK BAŞARISIZ (çıkış $rc, $((SECONDS - t0)) sn)"
        dump_log "$d/py.log"; dump_log "$d/px4.log"
    fi
}

post_checks() {
    snapshot sonra
    if diff -q "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" >/dev/null; then
        log_ok "Süreç denetimi: gz/px4/mavsdk_server/ruby sayıları başlangıçla aynı"
    else
        log_fail "Artık süreç var (gz/px4/mavsdk_server/ruby): $(diff "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" | tr '\n' ';')"
    fi
    if diff -q "$TMP_DIR/once.ports" "$TMP_DIR/sonra.ports" >/dev/null; then
        log_ok "Dinleyen TCP/UDP portları başlangıçla aynı"
    else
        log_fail "Dinleyen portlar değişti: $(diff "$TMP_DIR/once.ports" "$TMP_DIR/sonra.ports" | tr '\n' ';')"
    fi
    if [[ "$DAEMON_ONCE" -eq 0 ]]; then
        if pgrep -f '[r]os2-daemon' >/dev/null; then log_fail "Artık ros2 daemon süreci var"; else log_ok "ros2 daemon süreci yok"; fi
    fi
    if diff -q "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" >/dev/null; then
        log_ok "tc/ip durumu (lo) değişmedi"
    else
        log_fail "lo üzerindeki tc/ip durumu değişti: $(diff "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" | tr '\n' ';')"
    fi
}

# --- Önkoşul denetimi / dry-run ----------------------------------------------
check_prereqs() {
    local c
    for c in gz ss pgrep setsid timeout; do check "Araç mevcut: $c" command -v "$c"; done
    check "ROS 2 setup.bash ($ROS_DISTRO)" test -f "/opt/ros/$ROS_DISTRO/setup.bash"
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "PX4 SITL ikilisi" test -x "$PX4_BIN"
    check "PX4 gz_env.sh (rootfs)" test -f "$PX4_BUILD/rootfs/gz_env.sh"
    check "setup/env.sh" test -f "$ENV_SH"
}

print_plan() {
    log_info "[dry-run] T1: gz sim -s -r -v 2 empty.sdf (GZ_PARTITION ayrı) + venv Python: /clock >=5 mesaj, Image yayın/al"
    log_info "[dry-run] T2: source setup/env.sh; python: import torch, ultralytics, rclpy; rclpy.init/düğüm/shutdown"
    log_info "[dry-run] T3: ros2 run demo_nodes_cpp talker|listener, sonra demo_nodes_py (sistem Python); ayrı ROS_DOMAIN_ID, <=8 sn, >=3 mesaj"
    log_info "[dry-run] T4: HEADLESS=1 PX4_SIM_MODEL=gz_x500 $PX4_BIN -d (geçici dizin) + MAVSDK udp://:14540 (health/konum, arm/kalkış YOK)"
    log_info "[dry-run] Süreç grupları (setsid) her çıkışta öldürülür; sonda süreç/port/tc/ip karşılaştırması"
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
[[ "$COUNT_FAIL" -eq 0 ]] || fail_stop "Önkoşullar eksik: önce setup/install_all.sh çalıştırılmalı"

TMP_DIR="$(mktemp -d)"
write_helpers
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi   # başlangıçta zaten varsa sonda denetlenmez
snapshot once
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), ROS $ROS_DISTRO, PX4 $PX4_TAG, mavsdk $MAVSDK_VERSION, protobuf (venv) $("$VENV_PY" -c 'import google.protobuf as p; print(p.__version__)' 2>/dev/null || echo '?')"

test_t1
test_t2
test_t3
test_t4
post_checks
component_finish "$COMPONENT_NAME" "tamamlandı (T1-T4 ve süreç/port/tc denetimi)"
