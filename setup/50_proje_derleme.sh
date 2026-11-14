#!/usr/bin/env bash
# 50_proje_derleme.sh — proje paketlerini (src/swarm_msgs, src/swarm_vehicle, src/swarm_gcs) proje kökünde `colcon build` ile derler; yeni koşular `install/` içindeki bu çıktıyı kullanır.
# Kullanım: ./50_proje_derleme.sh [--dry-run | --verify | -h]
#   (argümansız)  derler (sudo gerekmez; yalnız proje içine yazar: build/, install/, log/); ardından kendini doğrular. Tekrar çalıştırmak güvenlidir (colcon değişmeyen paketleri hızla geçer).
#   --dry-run     hiçbir şey derlemez/yazmaz; ne yapacağını yazar
#   --verify      yalnız denetim: install/setup.bash var; üç paket ROS kaynaklı ortamda içe aktarılabiliyor (rclpy'li `import swarm_msgs.msg`, `swarm_vehicle`, `swarm_gcs`); damga bileşeni (src/yayim_damga) cmake ile
#                 DERLENEBİLİYOR (geçici yapı klasörü; araclar/kosu.sh'ın kullandığı kaynakla)
# Derleme ROS kaynaklı ve venv DIŞI ortamda yapılır (ROS araçları sistem Python'unu kullanır; .venv PATH'ten çıkarılır): bu, test betiklerinde ve araclar/kosu.sh'ta kullanılan biçimle birebir aynıdır.
# Derleme kodu tek yerdedir: setup/lib/derleme.sh (proje_derle, damga_derle). Kurulum sırası: ROS 2 (10), Gazebo (20) ve Python ortamı (40) hazır olmalıdır (install_all.sh --check-order).
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/derleme.sh
source "$SETUP_DIR/lib/derleme.sh"
parse_common_args "$@"
COMPONENT_NAME="Proje derlemesi"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

LOG_DERLEME="$GENERATED_DIR/proje_derleme.log"
DAMGA_SRC="$ROOT_DIR/src/yayim_damga"
TMP_DIR=""
exit_hook() { if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi; }

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

install_component() {
    local t0 t1 l
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] cd $ROOT_DIR && colcon build --base-paths src --packages-select ${PROJE_PAKETLERI[*]} (ROS kaynaklı, venv dışı; günlük: ${LOG_DERLEME#"$ROOT_DIR"/})"
        log_info "[dry-run] sonra --verify denetimleri çalışır (içe aktarma, damga derlemesi); hiçbir şey derlenmedi/yazılmadı"
        return 0
    fi
    [[ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]] || fail_stop "ROS 2 $ROS_DISTRO kurulu değil (önce setup/10_ros2_jazzy.sh)"
    command -v colcon >/dev/null || fail_stop "colcon bulunamadı (önce setup/10_ros2_jazzy.sh)"
    t0="$(date +%s%N)"
    if proje_derle "$LOG_DERLEME"; then
        t1="$(date +%s%N)"
        log_ok "Proje derlendi: ${PROJE_PAKETLERI[*]} ($(awk -v a="$t0" -v b="$t1" 'BEGIN {printf "%.1f", (b - a) / 1e9}') sn)"
    else
        log_fail "Proje derlemesi BAŞARISIZ; günlük: ${LOG_DERLEME#"$ROOT_DIR"/}"
        tail -n 15 "$LOG_DERLEME" | while IFS= read -r l; do log_info "  | $l"; done
        component_failed "$COMPONENT_NAME"; exit 1
    fi
}

verify_component() {
    local out rc=0
    if [[ ! -f "$ROOT_DIR/install/setup.bash" ]]; then
        log_fail "install/setup.bash yok: proje derlenmemiş (./setup/50_proje_derleme.sh)"
        return 0
    fi
    log_ok "install/setup.bash var"
    # üç paket, ROS kaynaklı (venv dışı) ortamda içe aktarılabilmeli
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    out="$(env -u VIRTUAL_ENV PATH="$(derleme_temiz_path)" bash -c 'source "/opt/ros/$1/setup.bash"; source "$2/install/setup.bash"; python3 -c "import swarm_msgs.msg, swarm_vehicle, swarm_gcs; from swarm_msgs.msg import FrameResult, Mission; print(swarm_msgs.msg.__name__, swarm_vehicle.__name__, swarm_gcs.__name__)"' _ "$ROS_DISTRO" "$ROOT_DIR" 2>&1)" || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "Paketler içe aktarılabiliyor (ROS kaynaklı ortam): $out"; else log_fail "Paketler içe aktarılamıyor: $(tail -n 3 <<< "$out" | tr '\n' ';')"; fi
    # damga bileşeni: geçici yapı klasöründe cmake ile derlenebilmeli (kosu.sh aynı kaynağı ve aynı işlevi kullanır)
    if ! command -v cmake >/dev/null; then log_fail "cmake bulunamadı (damga bileşeni derlenemez; setup/05_temel_paketler.sh)"; return 0; fi
    TMP_DIR="$(mktemp -d)"
    if damga_derle "$DAMGA_SRC" "$TMP_DIR/yapi" "$TMP_DIR/log" > "$TMP_DIR/damga.out" 2>&1; then
        log_ok "Damga bileşeni (src/yayim_damga) cmake ile derlenebiliyor (geçici yapı klasörü)"
    else
        log_fail "Damga bileşeni derlenemiyor: $(tail -n 3 "$TMP_DIR/damga.out" | tr '\n' ';')"
    fi
}

START=$SECONDS
if [[ "$MODE" == "install" ]]; then install_component; fi
if [[ "$MODE" == "verify" || "$DRY_RUN" -eq 0 ]]; then verify_component; fi
if [[ "$DRY_RUN" -eq 1 ]]; then log_info "[dry-run] doğrulama adımları yalnız kurulumdan sonra çalışır"; fi
log_info "Geçen süre: $((SECONDS - START)) sn"
component_finish "$COMPONENT_NAME"
