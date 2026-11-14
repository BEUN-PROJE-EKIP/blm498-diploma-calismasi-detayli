#!/usr/bin/env bash
# swarm_msgs_testi.sh — swarm_msgs ROS 2 mesaj paketinin derleme ve arayüz denetimi (DDS trafiği üretmez; Gazebo/PX4 çalıştırmaz).
# Kullanım: ./swarm_msgs_testi.sh [--dry-run | --verify | -h]
#   (argümansız)  proje derlemesi (ortak yol; üç paket), `ros2 interface list/show` ile 8 mesajın ve alanlarının denetimi, Python birim testi
#                 (src/swarm_msgs/test/test_kare_sonucu.py: "tespit var / açık tespit yok / işlem hatası / kare alınamadı" ayrımı ve
#                 rclpy.serialization gidiş-dönüşü); sonda ros2 daemon kalmadığı doğrulanır. Çıktılar build/, install/, log/ (depoya girmez).
#   --dry-run     hiçbir şey derlemez/çalıştırmaz; ne yapacağını yazar
#   --verify      hafif önkoşul denetimi: colcon, ROS 2 kurulumu, paket dosyaları; derleme yapmaz
# Derleme venv DIŞI sistem Python'uyla yapılır (rosidl üreteçleri sistem paketlerini ister). Bu betik install_all.sh/verify_all.sh sırasına
# GİRMEZ (adı NN_ desenine uymaz). sudo gerekmez.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/derleme.sh
source "$SETUP_DIR/lib/derleme.sh"
parse_common_args "$@"
COMPONENT_NAME="swarm_msgs mesaj paketi"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

PKG_DIR="$ROOT_DIR/src/swarm_msgs"
ROS_SETUP="/opt/ros/$ROS_DISTRO/setup.bash"
TEST_PY="$PKG_DIR/test/test_kare_sonucu.py"
# Beklenen mesajlar ve zorunlu alanları (ad: alan alan ...)
declare -A ALANLAR=(
    [VehicleState]="vehicle_id state sim_stamp mission_item_current mission_item_total last_frame_number"
    [Mission]="mission_id vehicle_id region_id region_x_min region_x_max region_y_min region_y_max waypoints altitude_m speed_ms"
    [ScanStart]="mission_id"
    [ScanFinished]="mission_id vehicle_id numbering_mode n_first n_last t_s t_b k_last"
    [Complete]="mission_id"
    [Detection]="class_id confidence box_x_min box_y_min box_x_max box_y_max has_position east north candidate"
    [FrameResult]="vehicle_id numbering_mode frame_number sim_stamp status detections"
    [Command]="vehicle_id sequence ack_state"
)

# venv'siz PATH (ROS araçları sistem Python'unu kullansın)
clean_path() { local p="" d; local IFS=':'; for d in $PATH; do [[ "$d" == "$ROOT_DIR/.venv"* || "$d" == "$ROOT_DIR/.venv-px4/"* ]] || p+="${p:+:}$d"; done; echo "$p"; }
# shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
ros_run() { # ros_run <komut...> : venv dışı ortamda ROS 2 (ve derlendiyse install) kurulu olarak çalıştırır
    env -u VIRTUAL_ENV PATH="$(clean_path)" bash -c 'source "$1"; if [[ -f "$2/install/setup.bash" ]]; then source "$2/install/setup.bash"; fi; shift 2; "$@"' _ "$ROS_SETUP" "$ROOT_DIR" "$@"
}

check_prereqs() {
    local f
    check "colcon mevcut" command -v colcon
    check "ROS 2 setup.bash ($ROS_DISTRO)" test -f "$ROS_SETUP"
    for f in package.xml CMakeLists.txt; do check "Paket dosyası: src/swarm_msgs/$f" test -f "$PKG_DIR/$f"; done
    for f in "${!ALANLAR[@]}"; do check "Mesaj tanımı: src/swarm_msgs/msg/$f.msg" test -f "$PKG_DIR/msg/$f.msg"; done
    check "Birim testi: ${TEST_PY#"$ROOT_DIR"/}" test -f "$TEST_PY"
}

if [[ "$MODE" == "verify" ]]; then
    check_prereqs
    component_finish "$COMPONENT_NAME"
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
    log_info "[dry-run] cd $ROOT_DIR && colcon build --base-paths src --packages-select swarm_msgs swarm_vehicle swarm_gcs (setup/lib/derleme.sh; venv dışı, source $ROS_SETUP)"
    log_info "[dry-run] ros2 interface list | swarm_msgs/msg/{${!ALANLAR[*]}}; ros2 interface show <her mesaj>: alan denetimi"
    log_info "[dry-run] python3 ${TEST_PY#"$ROOT_DIR"/} (rclpy.serialization; kare sonucu dört durum ayrımı)"
    log_info "[dry-run] sonda: pgrep -f ros2-daemon boş olmalı (ros2 daemon başlatılmaz)"
    log_info "[dry-run] Hiçbir şey çalıştırılmadı"
    component_finish "$COMPONENT_NAME"
fi

check_prereqs
[[ "$COUNT_FAIL" -eq 0 ]] || { component_failed "$COMPONENT_NAME"; exit 1; }
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi

# 1) derleme (ortak yol: setup/lib/derleme.sh; üç paketin hepsi derlenir, install/ güncel kalır)
out="$GENERATED_DIR/swarm_msgs_derleme.txt"
mkdir -p "$GENERATED_DIR"
if proje_derle "$out"; then
    log_ok "proje derlendi (swarm_msgs, swarm_vehicle, swarm_gcs; ortak yol: setup/lib/derleme.sh)"
else
    log_fail "proje derlemesi BAŞARISIZ; günlük: ${out#"$ROOT_DIR"/}"
    while IFS= read -r l; do log_info "  | $l"; done < <(tail -n 15 "$out")
    component_failed "$COMPONENT_NAME"; exit 1
fi

# 2) arayüz listesi ve alanlar (ros2 interface; DDS trafiği yok)
liste="$(ros_run ros2 interface list 2>/dev/null || true)"
for m in "${!ALANLAR[@]}"; do
    if [[ "$liste" == *"swarm_msgs/msg/$m"* ]]; then log_ok "Arayüz listesinde: swarm_msgs/msg/$m"; else log_fail "Arayüz listesinde YOK: swarm_msgs/msg/$m"; fi
done
for m in "${!ALANLAR[@]}"; do
    goster="$(ros_run ros2 interface show "swarm_msgs/msg/$m" 2>/dev/null || true)"
    govde="$(grep -vE '^[[:space:]]*#' <<< "$goster" || true)"
    eksik=""
    for a in ${ALANLAR[$m]}; do
        grep -qE "^[][A-Za-z0-9_/<>=]+[[:space:]]+$a([[:space:]]|$)" <<< "$govde" || eksik+="$a "
    done
    if [[ -z "$eksik" ]]; then
        log_ok "$m alanları tamam (${ALANLAR[$m]// /, })"
    else
        log_fail "$m alanları eksik: $eksik"
    fi
done

# 3) Python birim testi (rclpy.serialization; sistem Python'u)
rc=0
t_out="$(ros_run /usr/bin/python3 "$TEST_PY" 2>&1)" || rc=$?
if [[ "$rc" -eq 0 ]]; then
    log_ok "Birim testi geçti: $(grep -E '^Ran ' <<< "$t_out") (tespit yok ≠ kare alınamadı ≠ işlem hatası; gidiş-dönüş)"
else
    log_fail "Birim testi BAŞARISIZ (çıkış $rc)"
    while IFS= read -r l; do log_info "  | $l"; done <<< "$t_out"
fi

# 4) ros2 daemon kalmadı
if [[ "$DAEMON_ONCE" -eq 0 ]]; then
    if pgrep -f '[r]os2-daemon' >/dev/null; then
        ros_run ros2 daemon stop >/dev/null 2>&1 || true
        sleep 1
        if pgrep -f '[r]os2-daemon' >/dev/null; then log_fail "ros2 daemon süreci kaldı"; else log_warn "ros2 daemon başlamıştı ve durduruldu"; fi
    else
        log_ok "ros2 daemon süreci yok"
    fi
fi

component_finish "$COMPONENT_NAME" "tamamlandı (derleme, arayüz denetimi, birim testi)"
