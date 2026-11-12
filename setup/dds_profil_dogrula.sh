#!/usr/bin/env bash
# dds_profil_dogrula.sh — Fast DDS ortak profilinin (config/fastdds_profil.xml) ROS 2 tarafından GERÇEKTEN uygulandığının kanıtı.
# Kullanım: ./dds_profil_dogrula.sh [--dry-run | --verify | -h]
#   (argümansız)  iki ayrı süreç (talker/listener, farklı sürü adresleri) ile (a)-(f) ve tek süreçli intraprocess/data-sharing
#                 kanıtını çalıştırır; sonra AYNI testi profilsiz yineler (olumsuz kontrol: test profili ayırt ediyor mu). sudo gerekmez.
#   --dry-run     hiçbir süreç başlatmaz; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi: araçlar, XML iyi biçimli, XML adresleri config/deney.env ile tutarlı; süreç başlatmaz
# Kanıtlar:
#   (a) dinleyici >=3 mesaj alır           (b) DDS süreçlerinin UDP soketleri yalnız sürü adreslerinde (ss -uanp)
#   (c) /dev/shm'de fastrtps_*/fast_datasharing_* oluşmaz     (d1) çoklu yayın alıcısı yok (IGMP üyeliği ve ss soketi yok)    (d2) giden çoklu yayın baytları 1:10'a girer (direct paket sayacı + 1:10 baytı)
#   (e) profilsiz aynı test b/c/d koşullarından en az birini ihlal eder    (f) tc varsa htb sınıf sayacı artar, yoksa ATLANDI
#   (g) tek süreçte yayıncı+abone, 1000 mesaj: boşta hızı düşülmüş UDP OutDatagrams farkı >= mesaj sayısı; profilsiz < yarısı
# Not: SWARM_BIND_ADDR tanımsızken Fast DDS yalnız hata satırı basar ve profili hiç yüklemeden varsayılana düşer (sessiz profilsiz
# çalışma); bu betik değişkeni her sürece açıkça verir ve profilsiz düşüşü (b) ile yakalar. Hata satırı tek başına yeterli değildir.
# Ortam geçersiz kılma (yalnız geliştirme): DENEY_ENV (varsayılan config/deney.env), DDS_PROFIL (varsayılan config/fastdds_profil.xml).
# Başlatılan her süreç `setsid` ile ayrı süreç grubunda çalışır ve her çıkışta (hata, Ctrl-C dahil) öldürülür.
# Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz).
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
parse_common_args "$@"
COMPONENT_NAME="Fast DDS profili doğrulaması"
require_not_root
load_versions

export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
DDS_PROFIL="${DDS_PROFIL:-$ROOT_DIR/config/fastdds_profil.xml}"
ENV_SH="$SETUP_DIR/env.sh"
TEST_DOMAIN=$((120 + RANDOM % 80))      # izole alan kimliği
N_SEND=1000                             # (g) testinde gönderilen mesaj sayısı (keşif/arka plan UDP'sinden ayrışsın diye çok)
TMP_DIR=""
PGIDS=()
LAST_PG=""

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

# --- Süreç grubu yönetimi (runtime_smoke.sh ile aynı desen) --------------------
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

start_group() { # start_group <günlük> <komut...> : LAST_PG = grup lideri
    local log="$1"; shift
    setsid "$@" > "$log" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
}

# --- Yapılandırma ve XML tutarlılığı -------------------------------------------
[[ -f "$DENEY_ENV" ]] || fail_stop "Yapılandırma yok: $DENEY_ENV"
# shellcheck source=/dev/null
source "$DENEY_ENV"
for v in SWARM_NET UAV1_ADDR UAV2_ADDR UAV3_ADDR GCS_ADDR DDS_MCAST_ADDR; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done

# xml_check : XML iyi biçimli mi, initialPeersList == deney.env adresleri mi, hepsi SWARM_NET içinde mi, yasak öğe yok mu
xml_check() {
    python3 -I - "$DDS_PROFIL" "$SWARM_NET" "$UAV1_ADDR" "$UAV2_ADDR" "$UAV3_ADDR" "$GCS_ADDR" <<'PY'
import ipaddress, sys, xml.etree.ElementTree as ET
path, net, *addrs = sys.argv[1:]
ns = {"p": "http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles"}
root = ET.parse(path).getroot()
errs = []
peers = [e.text.strip() for e in root.findall(".//p:initialPeersList//p:udpv4/p:address", ns)]
if sorted(peers) != sorted(addrs):
    errs.append(f"initialPeersList {sorted(peers)} != deney.env {sorted(addrs)}")
n = ipaddress.ip_network(net)
for a in peers:
    if ipaddress.ip_address(a) not in n:
        errs.append(f"{a} {net} içinde değil")
if root.findall(".//p:multicastLocatorList", ns) or root.findall(".//p:metatrafficMulticastLocatorList", ns):
    errs.append("çoklu yayın konum listesi tanımlı")
def val(path):
    e = root.find(path, ns)
    return e.text.strip() if e is not None and e.text else None
checks = {
    ".//p:useBuiltinTransports": "false",
    ".//p:library_settings/p:intraprocess_delivery": "OFF",
    ".//p:publisher//p:data_sharing/p:kind": "OFF",
    ".//p:subscriber//p:data_sharing/p:kind": "OFF",
    ".//p:discoveryProtocol": "SIMPLE",
    ".//p:transport_descriptor/p:type": "UDPv4",
}
for p, want in checks.items():
    if val(p) != want:
        errs.append(f"{p.split('p:',1)[1]} = {val(p)!r}, beklenen {want!r}")
for tag in ("metatrafficUnicastLocatorList", "defaultUnicastLocatorList"):
    v = val(f".//p:{tag}//p:udpv4/p:address")
    if v != "${SWARM_BIND_ADDR}":
        errs.append(f"{tag} adresi {v!r}, beklenen '${{SWARM_BIND_ADDR}}'")
wl = sorted(e.text.strip() for e in root.findall(".//p:interfaceWhiteList/p:address", ns))
if wl != sorted(addrs):
    errs.append(f"interfaceWhiteList {wl} != deney.env {sorted(addrs)}")
for e in errs:
    print(e)
sys.exit(1 if errs else 0)
PY
}

all_addrs_on_lo() { # sürü adreslerinin hepsi bu makinede yerel mi (ip route get "local" der; çıktı önce değişkene alınır)
    local out a
    for a in "$UAV1_ADDR" "$UAV2_ADDR" "$UAV3_ADDR" "$GCS_ADDR"; do
        out="$(ip -4 route get "$a" 2>/dev/null || true)"
        [[ "$out" == local* ]] || return 1
    done
}

check_prereqs() {
    local c out
    for c in ss pgrep setsid timeout ip tc python3; do check "Araç mevcut: $c" command -v "$c"; done
    check "ROS 2 setup.bash ($ROS_DISTRO)" test -f "/opt/ros/$ROS_DISTRO/setup.bash"
    check "demo_nodes_cpp kurulu" test -d "/opt/ros/$ROS_DISTRO/lib/demo_nodes_cpp"
    check "setup/env.sh" test -f "$ENV_SH"
    check "XML iyi biçimli: $DDS_PROFIL" python3 -I -c 'import sys,xml.etree.ElementTree as E; E.parse(sys.argv[1])' "$DDS_PROFIL"
    if out="$(xml_check 2>&1)"; then
        log_ok "XML ile deney.env tutarlı (eşler = UAV1/2/3/GCS, hepsi $SWARM_NET içinde; taşıma/data-sharing/intraprocess/keşif ayarları beklenen)"
    else
        log_fail "XML tutarsız: $(tr '\n' ';' <<<"$out")"
    fi
    if all_addrs_on_lo; then
        log_ok "Sürü adresleri lo üzerinde mevcut"
    else
        log_warn "Sürü adreslerinden biri lo üzerinde yok (gerçek mod için ./setup/60_ag_emulasyon_tc.sh uygulanmış olmalı)"
    fi
}

print_plan() {
    log_info "[dry-run] ROS_DOMAIN_ID=$TEST_DOMAIN (rastgele, izole); profil: $DDS_PROFIL"
    log_info "[dry-run] (a-d,f) talker SWARM_BIND_ADDR=$UAV1_ADDR, listener SWARM_BIND_ADDR=$UAV2_ADDR; >=3 mesaj; ss -uanp, /dev/shm, /proc/net/igmp, tc -s class show dev lo"
    log_info "[dry-run] (e) aynı test profil değişkenleri kaldırılarak; en az bir ihlal beklenir"
    log_info "[dry-run] (g) tek süreç rclpy yayıncı+abone, $N_SEND mesaj; /proc/net/snmp Udp OutDatagrams farkı (boşta hızı düşülmüş) >= $N_SEND; profilsiz < $((N_SEND / 2))"
    log_info "[dry-run] Süreç grupları (setsid) her çıkışta öldürülür; sonda pgrep ve /dev/shm artık denetimi"
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
all_addrs_on_lo || fail_stop "Sürü adresleri lo üzerinde yok: kullanıcı ./setup/60_ag_emulasyon_tc.sh uygulamalı (bu betik tc/ip değiştirmez)"

TMP_DIR="$(mktemp -d)"

# --- Ölçüm yardımcıları ----------------------------------------------------------
shm_list() { # /dev/shm içindeki DDS dosyaları
    find /dev/shm -maxdepth 1 \( -name 'fastrtps_*' -o -name 'fast_datasharing_*' -o -name 'sem.fastrtps_*' \) -printf '%f\n' 2>/dev/null | LC_ALL=C sort || true
}
igmp_groups() { # lo üzerindeki çoklu yayın grupları ve üye sayısı (grup:üye, onaltılı); /proc/net/igmp
    awk '/^[0-9]/ { dev=$2 } /^[ \t]+[0-9A-F]{8}/ { if (dev == "lo") print $1 ":" $2 }' /proc/net/igmp | LC_ALL=C sort || true
}
udp_out() { awk '/^Udp:/ && !h { h=1; next } /^Udp:/ { print $5 }' /proc/net/snmp; } # OutDatagrams
direct_pkts() { # sınıfsız ('direct') paket sayısı; htb yoksa boş
    tc -s qdisc show dev lo 2>/dev/null | sed -n 's/.*direct_packets_stat \([0-9]*\).*/\1/p' | sed -n 1p || true
}
htb_bytes() { # sınırlayıcı sınıf (1:10) gönderilen bayt; htb yoksa boş
    tc -s class show dev lo 2>/dev/null | awk '/^class htb 1:10 /{f=1} f && /Sent/ { print $2; exit }' || true
}
group_pids() { # group_pids <pgid...> : gruplardaki tüm PID'ler
    local pg
    for pg in "$@"; do pgrep -g "$pg" || true; done
}
# sockets_of <pid...> : bu PID'lerin UDP soketleri ("yerel_adres:port" satırları)
sockets_of() {
    local pids=" $* " out line pid
    out="$(ss -uanpH 2>/dev/null || true)"
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        pid="${line##*pid=}"; pid="${pid%%,*}"
        [[ "$pids" == *" $pid "* ]] && awk '{print $4}' <<<"$line"
    done <<<"$out"
    return 0
}
# addr_ok <adres:port> : yerel adres 4 sürü adresinden biri mi
addr_ok() {
    local a="${1%:*}"
    [[ "$a" == "$UAV1_ADDR" || "$a" == "$UAV2_ADDR" || "$a" == "$UAV3_ADDR" || "$a" == "$GCS_ADDR" ]]
}

# --- Ortak başlatma ------------------------------------------------------------
# child_cmd <profil:1|0> <adres> <komut...> : profilli koşuda setup/env.sh (profil değişkenlerini O ayarlar), profilsizde yalnız
# ROS setup.bash alınır. Her iki durumda alan kimliği izole, SWARM_BIND_ADDR yalnız profilli koşuda verilir.
CHILD=()
child_cmd() {
    local use_profile="$1" addr="$2"; shift 2
    local setup_file="/opt/ros/$ROS_DISTRO/setup.bash"
    local -a e=(env -u FASTRTPS_DEFAULT_PROFILES_FILE -u RMW_FASTRTPS_USE_QOS_FROM_XML -u SWARM_BIND_ADDR ROS_DOMAIN_ID="$TEST_DOMAIN" RMW_IMPLEMENTATION=rmw_fastrtps_cpp)
    if [[ "$use_profile" == "1" ]]; then
        setup_file="$ENV_SH"
        e+=(SWARM_BIND_ADDR="$addr")
    fi
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$@ alt kabukta açılır
    CHILD=("${e[@]}" bash -c 'source "$1"; shift; exec "$@"' _ "$setup_file" "$@")
}

# --- İki süreçli test (a-d,f) ---------------------------------------------------
# Sonuç: R_MSGS R_NSOCK R_BAD_SOCKETS R_SHM_NEW R_IGMP_NEW R_TC_DELTA
run_pair() {
    local label="$1" use_profile="$2" d="$TMP_DIR/pair_$1" n=0 i s
    mkdir -p "$d"
    local shm0 igmp0 tc0 tc1 dp0 dp1
    # Çoklu yayın dinleyicisi gruba kendisi katılır; igmp tabanı bundan SONRA alınır, DDS katılımı üye sayısı artışı olarak görünür.
    start_group "$d/mc.log" python3 -I "$TMP_DIR/mcsniff.py" $((7400 + 250 * TEST_DOMAIN)) 7 "$DDS_MCAST_ADDR"; local mpg="$LAST_PG"
    sleep 0.7
    shm0="$(shm_list)"; igmp0="$(igmp_groups)"; tc0="$(htb_bytes)"; dp0="$(direct_pkts)"
    child_cmd "$use_profile" "$UAV2_ADDR" ros2 run demo_nodes_cpp listener
    start_group "$d/listener.log" "${CHILD[@]}"; local lpg="$LAST_PG"
    child_cmd "$use_profile" "$UAV1_ADDR" ros2 run demo_nodes_cpp talker
    start_group "$d/talker.log" "${CHILD[@]}"; local tpg="$LAST_PG"
    for ((i = 0; i < 150; i++)); do
        n="$(grep -c 'I heard' "$d/listener.log" 2>/dev/null || true)"
        [[ "${n:-0}" -ge 3 ]] && break
        sleep 0.1
    done
    sleep 1   # soketler ve sayaçlar otursun
    R_MSGS="${n:-0}"
    local -a pids; mapfile -t pids < <(group_pids "$lpg" "$tpg")
    local socks; socks="$(sockets_of "${pids[@]}" | LC_ALL=C sort -u)"
    printf '%s\n' "$socks" > "$d/soketler.txt"
    R_NSOCK=0; R_BAD_SOCKETS=""
    while IFS= read -r s; do
        [[ -n "$s" ]] || continue
        R_NSOCK=$((R_NSOCK + 1))
        addr_ok "$s" || R_BAD_SOCKETS+="${R_BAD_SOCKETS:+ }$s"
    done <<<"$socks"
    R_SHM_NEW="$(comm -13 <(printf '%s\n' "$shm0") <(shm_list) | tr '\n' ' ')"
    R_IGMP_NEW="$(comm -13 <(printf '%s\n' "$igmp0") <(igmp_groups) | tr '\n' ' ')"
    tc1="$(htb_bytes)"
    if [[ -n "$tc0" && -n "$tc1" ]]; then R_TC_DELTA=$((tc1 - tc0)); else R_TC_DELTA="yok"; fi
    dp1="$(direct_pkts)"
    if [[ -n "$dp0" && -n "$dp1" ]]; then R_DIRECT=$((dp1 - dp0)); else R_DIRECT="yok"; fi
    stop_group "$tpg"; stop_group "$lpg"
    for ((i = 0; i < 80; i++)); do grep -q '^MC_DATAGRAM' "$d/mc.log" 2>/dev/null && break; sleep 0.1; done || true
    R_MC="$(sed -n 's/^MC_DATAGRAM \([0-9]*\).*/\1/p' "$d/mc.log")"; R_MC="${R_MC:-?}"
    stop_group "$mpg"
    log_info "[$label] çoklu yayın grubuna ($DDS_MCAST_ADDR) gelen datagram sayısı (lo üzerinde dinleyici): ${R_MC}"
    log_info "[$label] dinleyici ${R_MSGS} mesaj; ${R_NSOCK} UDP soketi: $(tr '\n' ' ' < "$d/soketler.txt")"
    log_info "[$label] yeni /dev/shm DDS dosyası: '${R_SHM_NEW}'; yeni lo çoklu yayın grubu (/proc/net/igmp): '${R_IGMP_NEW}'; sınırlayıcı 1:10 bayt farkı: ${R_TC_DELTA}; sınıfsız (direct) paket farkı: ${R_DIRECT}"
}

# Çoklu yayın dinleyicisi: <DDS_MCAST_ADDR>:<keşif çoklu yayın portu> grubuna lo arayüzünden katılır ve <sn> boyunca gelen datagramları sayar.
write_sniff_py() {
    cat > "$TMP_DIR/mcsniff.py" <<'PY'
import socket, struct, sys, time
port = int(sys.argv[1]); secs = float(sys.argv[2]); group = sys.argv[3]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((group, port))
s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton("127.0.0.1")))
s.settimeout(0.2); n = 0; t = time.time()
while time.time() - t < secs:
    try:
        s.recvfrom(65535); n += 1
    except socket.timeout:
        pass
print("MC_DATAGRAM", n, flush=True)
PY
}

# --- Tek süreçli test (g) ---------------------------------------------------------
write_inproc_py() {
    cat > "$TMP_DIR/inproc.py" <<'PY'
# Tek süreçte yayıncı + abone; mesajların UDP'den geçtiği /proc/net/snmp Udp OutDatagrams farkıyla ölçülür.
import os, sys, time
import rclpy
from std_msgs.msg import String

def udp_out():
    with open("/proc/net/snmp") as f:
        rows = [l.split() for l in f if l.startswith("Udp:")]
    return int(dict(zip(rows[0][1:], rows[1][1:]))["OutDatagrams"])

n_send = int(sys.argv[1]); stop_file = sys.argv[2]
rclpy.init()
node = rclpy.create_node("dds_profil_tek_surec")
got = []
node.create_subscription(String, "dds_profil_test", lambda m: got.append(1), n_send + 100)
pub = node.create_publisher(String, "dds_profil_test", n_send + 100)   # geçmiş derinliği mesaj sayısından büyük: toplu yayında düşme olmasın
t0 = time.time()
while pub.get_subscription_count() < 1 and time.time() - t0 < 8:
    rclpy.spin_once(node, timeout_sec=0.1)
time.sleep(1.0)                      # keşif trafiği otursun
# Boşta taban hızı: ölçüm penceresindeki keşif/arka plan UDP'si bundan kestirilir ve düşülür.
i0 = udp_out(); ti = time.time()
while time.time() - ti < 1.0:
    rclpy.spin_once(node, timeout_sec=0.05)
idle_rate = (udp_out() - i0) / (time.time() - ti)
before = udp_out(); tb = time.time()
msg = String(); msg.data = "x" * 200
for _ in range(n_send):
    pub.publish(msg)
    rclpy.spin_once(node, timeout_sec=0)
t1 = time.time()
while len(got) < n_send and time.time() - t1 < 10:   # güvenilir teslim: son mesajlar sınırlayıcı kuyruğunda gecikebilir
    rclpy.spin_once(node, timeout_sec=0.01)
after = udp_out(); dur = time.time() - tb
net = max(0, after - before - int(idle_rate * dur))
print(f"INPROC eslesen_abone={pub.get_subscription_count()} alinan={len(got)} udp_ham={after - before} bosta_hiz={idle_rate:.1f}/sn sure={dur:.2f}sn udp_out_farki={net}", flush=True)
print("HAZIR", flush=True)               # kabuk bu noktada ss ile soketleri okur
t2 = time.time()
while not os.path.exists(stop_file) and time.time() - t2 < 15:
    time.sleep(0.1)
node.destroy_node(); rclpy.shutdown()
PY
}

# run_inproc <etiket> <profil:1|0> : R_IN_RECV R_IN_UDP R_IN_NSOCK R_IN_BAD
run_inproc() {
    local label="$1" use_profile="$2" d="$TMP_DIR/inproc_$1" i line
    mkdir -p "$d"
    child_cmd "$use_profile" "$UAV1_ADDR" python3 "$TMP_DIR/inproc.py" "$N_SEND" "$d/dur"
    start_group "$d/py.log" "${CHILD[@]}"; local pg="$LAST_PG"
    for ((i = 0; i < 300; i++)); do grep -q '^HAZIR' "$d/py.log" 2>/dev/null && break; sleep 0.1; done || true
    line="$(grep '^INPROC' "$d/py.log" || true)"
    R_IN_RECV="$(sed -n 's/.*alinan=\([0-9]*\).*/\1/p' <<<"$line")"
    R_IN_UDP="$(sed -n 's/.*udp_out_farki=\(-\{0,1\}[0-9]*\).*/\1/p' <<<"$line")"
    local -a pids; mapfile -t pids < <(group_pids "$pg")
    local socks s; socks="$(sockets_of "${pids[@]}" | LC_ALL=C sort -u)"
    R_IN_NSOCK=0; R_IN_BAD=""
    while IFS= read -r s; do
        [[ -n "$s" ]] || continue
        R_IN_NSOCK=$((R_IN_NSOCK + 1)); addr_ok "$s" || R_IN_BAD+="${R_IN_BAD:+ }$s"
    done <<<"$socks"
    touch "$d/dur"; stop_group "$pg"
    log_info "[$label] tek süreç: ${line:-çıktı yok}; ${R_IN_NSOCK} UDP soketi: $(tr '\n' ' ' <<<"$socks")"
}

# --- Çalıştırma ---------------------------------------------------------------------
write_inproc_py
write_sniff_py
SHM_BASELINE="$(shm_list)"
PROC_BASELINE="$(pgrep -a -x -f 'demo_nodes_cpp|dds_profil_tek_surec' || true)"
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi

log_info "Fast DDS $(dpkg-query -W -f='${Version}' ros-"$ROS_DISTRO"-fastrtps 2>/dev/null || echo '?'), rmw_fastrtps_cpp $(dpkg-query -W -f='${Version}' ros-"$ROS_DISTRO"-rmw-fastrtps-cpp 2>/dev/null || echo '?'); alan kimliği $TEST_DOMAIN"
if [[ -n "$(htb_bytes)" ]]; then TC_ACTIVE=1; log_info "tc: htb sınırlayıcı (1:10) lo üzerinde uygulanmış"; else TC_ACTIVE=0; log_info "tc: htb sınırlayıcı lo üzerinde YOK (f maddesi ATLANDI)"; fi

# --- Profilli koşu
run_pair "profilli" 1
P_MSGS="$R_MSGS"; P_NSOCK="$R_NSOCK"; P_BAD="$R_BAD_SOCKETS"; P_SHM="$R_SHM_NEW"; P_IGMP="$R_IGMP_NEW"; P_TC="$R_TC_DELTA"; P_MC="$R_MC"; P_DIRECT="$R_DIRECT"
if [[ "$P_MSGS" -ge 3 ]]; then log_ok "(a) dinleyici $P_MSGS mesaj aldı (>=3)"; else log_fail "(a) dinleyici yalnız $P_MSGS mesaj aldı (>=3 gerekli); günlük: $(tr '\n' '|' < "$TMP_DIR/pair_profilli/listener.log" | cut -c1-400)"; fi
if [[ "$P_NSOCK" -gt 0 && -z "$P_BAD" ]]; then
    log_ok "(b) $P_NSOCK UDP soketinin hepsi sürü adreslerinde (başka adres yok)"
elif [[ "$P_NSOCK" -eq 0 ]]; then
    log_fail "(b) DDS süreçlerinin UDP soketi görülemedi (ölçüm geçersiz)"
else
    log_fail "(b) sürü dışı UDP soketi: $P_BAD"
fi
if [[ -z "$P_SHM" ]]; then log_ok "(c) test sırasında /dev/shm altında fastrtps_*/fast_datasharing_* oluşmadı"; else log_fail "(c) yeni /dev/shm dosyası: $P_SHM"; fi
if [[ -z "$P_IGMP" && "$P_BAD" != *"$DDS_MCAST_ADDR"* && "$P_BAD" != *" 224."* ]]; then
    log_ok "(d1) çoklu yayın alıcısı yok: /proc/net/igmp lo üye sayısı artmadı, ss'te $DDS_MCAST_ADDR soketi yok"
else
    log_fail "(d1) çoklu yayın alıcısı var: igmp farkı='${P_IGMP}' ss='${P_BAD}'"
fi
if [[ "$TC_ACTIVE" -ne 1 ]]; then
    log_fail "(d2) ölçülemedi: lo üzerinde htb sınırlayıcı yok"
elif [[ ! "$P_MC" =~ ^[0-9]+$ || ! "$P_DIRECT" =~ ^[0-9]+$ ]]; then
    log_fail "(d2) ölçülemedi: çoklu yayın datagram sayısı='${P_MC}' direct farkı='${P_DIRECT}'"
elif [[ "$P_MC" -eq 0 ]]; then
    log_ok "(d2) profilli koşuda $DDS_MCAST_ADDR'e hiç datagram gitmedi (sınırlayıcıya alınacak trafik yok)"
elif [[ $((P_DIRECT * 2)) -lt "$P_MC" ]]; then
    log_ok "(d2) $DDS_MCAST_ADDR'e giden $P_MC datagram sınırlayıcıya (1:10) alındı: sınıfsız (direct) paket farkı yalnız $P_DIRECT (< $P_MC/2; arka plan payı), 1:10 +${P_TC} bayt"
else
    log_fail "(d2) $DDS_MCAST_ADDR'e giden $P_MC datagram sınırlayıcı dışında kalıyor: sınıfsız (direct) paket farkı $P_DIRECT (>= $P_MC/2); 60'taki ikinci süzgeç (dst $DDS_MCAST_ADDR -> 1:10) uygulanmamış olabilir"
fi
if [[ "$TC_ACTIVE" -eq 1 ]]; then
    if [[ "$P_TC" =~ ^[0-9]+$ && "$P_TC" -gt 0 ]]; then log_ok "(f) sınırlayıcı sınıf 1:10 sayacı arttı: +$P_TC bayt"; else log_fail "(f) sınırlayıcı sayacı artmadı (fark: $P_TC)"; fi
else
    log_info "(f) ATLANDI: lo üzerinde htb sınırlayıcı yok (tc uygulanmamış; bu betik tc uygulamaz)"
fi

# --- Olumsuz kontrol (profilsiz)
run_pair "profilsiz" 0
N_BAD="$R_BAD_SOCKETS"; N_SHM="$R_SHM_NEW"; N_IGMP="$R_IGMP_NEW"; N_MC="$R_MC"
viol=""
[[ -n "$N_BAD" ]] && viol+=" (b: sürü dışı soket: $N_BAD)"
[[ -n "$N_SHM" ]] && viol+=" (c: /dev/shm: $N_SHM)"
[[ -n "$N_IGMP" ]] && viol+=" (d: igmp: $N_IGMP)"
[[ "$N_MC" =~ ^[0-9]+$ && "$N_MC" -gt 0 ]] && viol+=" (d: $DDS_MCAST_ADDR'e $N_MC datagram)"
if [[ -n "$viol" ]]; then
    log_ok "(e) olumsuz kontrol: profilsiz koşuda ihlal görüldü —$viol; test profili ayırt ediyor"
else
    log_fail "(e) olumsuz kontrol: profilsiz koşuda b/c/d ihlali GÖRÜLMEDİ — test ayırt edici değil"
fi

# --- Tek süreç (g)
run_inproc "profilli" 1
if [[ "${R_IN_RECV:-0}" -ge "$N_SEND" && "${R_IN_UDP:-0}" -ge "$N_SEND" ]]; then
    log_ok "(g) tek süreç, profilli: $R_IN_RECV/$N_SEND mesaj alındı ve boşta hızı düşülmüş UDP OutDatagrams farkı ${R_IN_UDP} >= $N_SEND (mesajlar UDP'den geçti: intraprocess/data-sharing kapalı)"
else
    log_fail "(g) tek süreç, profilli: alınan=${R_IN_RECV:-?}/$N_SEND, UDP farkı=${R_IN_UDP:-?} (>= $N_SEND beklenir)"
fi
if [[ "$R_IN_NSOCK" -gt 0 && -z "$R_IN_BAD" ]]; then log_ok "(g) tek süreç soketleri yalnız sürü adreslerinde ($R_IN_NSOCK soket)"; else log_fail "(g) tek süreç soketleri: sayı=$R_IN_NSOCK sürü dışı='$R_IN_BAD'"; fi
run_inproc "profilsiz" 0
if [[ "${R_IN_RECV:-0}" -ge "$N_SEND" && "${R_IN_UDP:-0}" -lt $((N_SEND / 2)) ]]; then
    log_ok "(g-olumsuz) profilsiz tek süreç: $R_IN_RECV/$N_SEND teslim, UDP farkı ${R_IN_UDP:-0} < $((N_SEND / 2)) (mesajlar süreç içinde kaldı; profil ayırt ediliyor)"
else
    log_fail "(g-olumsuz) profilsiz tek süreç: alınan=${R_IN_RECV:-?}/$N_SEND UDP farkı=${R_IN_UDP:-?} (beklenen: tam teslim ve fark < $((N_SEND / 2))); ölçüm profili ayırt etmiyor"
fi

# --- Temizlik denetimi
cleanup_all
sleep 0.5
left="$(pgrep -a -x -f 'demo_nodes_cpp|dds_profil_tek_surec' || true)"
if [[ "$left" == "$PROC_BASELINE" ]]; then log_ok "Artık talker/listener/tek süreç yok"; else log_fail "Artık süreç var: $left"; fi
if [[ "$DAEMON_ONCE" -eq 0 ]]; then
    if pgrep -f '[r]os2-daemon' >/dev/null; then log_fail "Artık ros2 daemon süreci var"; else log_ok "ros2 daemon süreci yok"; fi
fi
shm_new="$(comm -13 <(printf '%s\n' "$SHM_BASELINE") <(shm_list) | tr '\n' ' ')"
if [[ -z "$shm_new" ]]; then log_ok "/dev/shm altında başlangıçta olmayan DDS dosyası kalmadı"; else log_fail "/dev/shm altında artık DDS dosyası: $shm_new"; fi

component_finish "$COMPONENT_NAME" "tamamlandı (a-g ve olumsuz kontroller)"
