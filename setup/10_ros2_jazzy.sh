#!/usr/bin/env bash
# 10_ros2_jazzy.sh — ROS 2 (sürüm versions.env'de) apt ile kurar: ros2-apt-source (SHA-256 doğrulamalı), ros-base,
# Fast DDS RMW, demo düğümleri, ros-dev-tools, rosdep. ~/.bashrc'ye DOKUNMAZ (ortam için: source setup/env.sh).
# Kullanım: ./10_ros2_jazzy.sh [--dry-run | --verify | -h]
#   (argümansız)  kurar (sudo gerekir), sonda doğrular; zaten kuruluysa atlar
#   --dry-run     hiçbir şey kurmaz/indirmez; yapacağı komutları yazar
#   --verify      yalnız salt okunur denetim (sudo gerektirmez)
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
parse_common_args "$@"
COMPONENT_NAME="ROS 2 Jazzy"
require_not_root
load_versions

ENV_SH="$SETUP_DIR/env.sh"
DEB_URL="https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.noble_all.deb"
DEB_FILE="$GENERATED_DIR/downloads/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.noble_all.deb"
WANT_SRC_VERSION="${ROS_APT_SOURCE_VERSION}~noble"
ROSDEP_LIST="/etc/ros/rosdep/sources.list.d/20-default.list"
PACKAGES=(ros-dev-tools "ros-${ROS_DISTRO}-ros-base" "ros-${ROS_DISTRO}-rmw-fastrtps-cpp"
          "ros-${ROS_DISTRO}-demo-nodes-cpp" "ros-${ROS_DISTRO}-demo-nodes-py" python3-rosdep)

apt_source_version() { dpkg-query -W -f='${Version}' ros2-apt-source 2>/dev/null || true; }

universe_enabled() { # çıktı önce değişkene alınır (grep -q + pipefail → SIGPIPE yanlış negatifi olmasın)
    local pol; pol="$(apt-cache policy 2>/dev/null || true)"
    grep -q 'c=universe' <<< "$pol"
}

fail_stop() { # fail_stop <ileti> : (-) yaz, bileşeni başarısız say, çık
    log_fail "$1"
    component_failed "$COMPONENT_NAME"
    exit 1
}

# --- Kurulum -----------------------------------------------------------------
install_component() {
    # 1) universe bileşeni
    if universe_enabled; then
        log_ok "Ubuntu 'universe' bileşeni etkin"
    elif [[ "$DRY_RUN" -eq 1 ]]; then
        log_warn "Ubuntu 'universe' bileşeni etkin görünmüyor; gerçek modda durulur (sudo add-apt-repository universe elle çalıştırılmalı)"
    else
        fail_stop "Ubuntu 'universe' bileşeni etkin değil: ROS paketleri için gerekli. Elle: sudo add-apt-repository universe && sudo apt-get update (betik bunu kendisi çalıştırmaz)"
    fi

    # 2) ros2-apt-source (sürüm + SHA-256 kilitli)
    if [[ "$(apt_source_version)" == "$WANT_SRC_VERSION" ]]; then
        log_ok "ros2-apt-source $WANT_SRC_VERSION zaten kurulu"
    else
        local got=""
        if [[ -f "$DEB_FILE" ]]; then got="$(sha256sum "$DEB_FILE" | cut -d' ' -f1)"; fi
        if [[ "$got" == "$ROS_APT_SOURCE_SHA256" ]]; then
            log_ok "Deb zaten indirilmiş ve SHA-256 doğru: ${DEB_FILE#"$ROOT_DIR"/}"
        else
            if [[ "$DRY_RUN" -eq 0 ]]; then mkdir -p "$(dirname "$DEB_FILE")"; fi
            run "ros2-apt-source indiriliyor" curl -fsSL -o "$DEB_FILE" "$DEB_URL"
            if [[ "$DRY_RUN" -eq 1 ]]; then
                log_info "[dry-run] sha256sum $DEB_FILE == $ROS_APT_SOURCE_SHA256 doğrulanır"
            else
                got="$(sha256sum "$DEB_FILE" | cut -d' ' -f1)"
                if [[ "$got" != "$ROS_APT_SOURCE_SHA256" ]]; then
                    rm -f "$DEB_FILE"
                    fail_stop "SHA-256 uyuşmuyor (beklenen $ROS_APT_SOURCE_SHA256, bulunan $got); dosya silindi, sudo çağrılmadı"
                fi
                log_ok "SHA-256 doğrulandı"
            fi
        fi
        sudo_run "ros2-apt-source kuruluyor" dpkg -i "$DEB_FILE"
        APT_UPDATED=0   # yeni apt kaynağı: dizinler yeniden güncellenmeli
    fi

    # 3) Paketler (eksik varsa apt-get update + install)
    apt_ensure "${PACKAGES[@]}"

    # 4) rosdep
    if [[ -f "$ROSDEP_LIST" ]]; then
        log_ok "rosdep zaten başlatılmış ($ROSDEP_LIST)"
    else
        sudo_run "rosdep init" rosdep init
    fi
    if [[ -d "$HOME/.ros/rosdep/sources.cache" ]]; then
        log_ok "rosdep update zaten yapılmış"
    elif have_cmd rosdep || [[ "$DRY_RUN" -eq 1 ]]; then
        run "rosdep update" rosdep update
    else
        log_warn "rosdep komutu yok; rosdep update atlandı"
    fi
}

# --- Doğrulama ---------------------------------------------------------------
in_env() { bash -c 'source "$1" 2>/dev/null; shift; "$@"' _ "$ENV_SH" "$@"; }

rmw_report_ok() {
    local rep; rep="$(in_env ros2 doctor --report 2>/dev/null || true)"
    grep -q 'rmw_fastrtps_cpp' <<< "$rep"
}

# Konuş/dinle duman testi: ayrı oturum gruplarında başlatılır, her durumda temizlenir.
SMOKE_OUT=""
SMOKE_PIDS=()
smoke_cleanup() {
    local p
    for p in "${SMOKE_PIDS[@]}"; do kill -TERM -- "-$p" 2>/dev/null || true; done
    sleep 0.5
    for p in "${SMOKE_PIDS[@]}"; do kill -KILL -- "-$p" 2>/dev/null || true; done
    SMOKE_PIDS=()
    [[ -n "$SMOKE_OUT" ]] && rm -f "$SMOKE_OUT"
    return 0
}
smoke_talker_listener() {
    SMOKE_OUT="$(mktemp)"
    local script='source "$1" 2>/dev/null; export ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1; exec timeout -s INT -k 3 6 ros2 run demo_nodes_cpp "$2"'
    setsid bash -c "$script" _ "$ENV_SH" listener > "$SMOKE_OUT" 2>&1 &
    SMOKE_PIDS+=("$!")
    setsid bash -c "$script" _ "$ENV_SH" talker > /dev/null 2>&1 &
    SMOKE_PIDS+=("$!")
    sleep 7
    local ok=1
    grep -q 'I heard' "$SMOKE_OUT" || ok=0
    smoke_cleanup
    [[ "$ok" -eq 1 ]]
}

rclpy_venv_combo() {
    in_env python -c 'import sys, rclpy, numpy, torch, ultralytics; print("rclpy tamam; numpy", numpy.__version__, "torch", torch.__version__, "ultralytics", ultralytics.__version__, "python", sys.version.split()[0])'
}

exit_hook() { smoke_cleanup; }

verify_component() {
    local src_ver pkg
    src_ver="$(apt_source_version)"
    if [[ "$src_ver" == "$WANT_SRC_VERSION" ]]; then log_ok "ros2-apt-source sürümü: $src_ver"; else log_fail "ros2-apt-source $WANT_SRC_VERSION olmalı; bulunan: '${src_ver:-kurulu değil}'"; fi
    if [[ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]]; then log_ok "/opt/ros/$ROS_DISTRO/setup.bash var"; else log_fail "/opt/ros/$ROS_DISTRO/setup.bash yok"; fi
    for pkg in "${PACKAGES[@]}"; do
        if apt_pkg_installed "$pkg"; then log_ok "Paket kurulu: $pkg"; else log_fail "Paket kurulu değil: $pkg"; fi
    done

    if [[ "$(in_env bash -c 'echo "$RMW_IMPLEMENTATION"' 2>/dev/null)" == "rmw_fastrtps_cpp" ]]; then
        log_ok "env.sh: RMW_IMPLEMENTATION=rmw_fastrtps_cpp"
    else
        log_fail "env.sh: RMW_IMPLEMENTATION beklenen değil"
    fi

    if ! in_env command -v ros2 >/dev/null 2>&1; then
        log_fail "ros2 komutu bulunamadı (env.sh sonrası); ros2/colcon/rosdep, RMW raporu, konuş/dinle ve rclpy+venv denetimleri yapılamadı"
        return 0
    fi
    check "ros2 --help çalışıyor" in_env ros2 --help
    check "colcon --help çalışıyor" in_env colcon --help
    check "rosdep --version çalışıyor" in_env rosdep --version
    check "ros2 doctor --report RMW olarak rmw_fastrtps_cpp gösteriyor" rmw_report_ok
    check "Konuş/dinle duman testi (talker→listener, ROS_DOMAIN_ID=77, 'I heard')" smoke_talker_listener
    smoke_cleanup
    if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
        local combo
        if combo="$(rclpy_venv_combo 2>&1)"; then log_ok "rclpy + venv birlikte: ${combo##*$'\n'}"; else log_fail "rclpy + venv çakışması: ${combo##*$'\n'}"; fi
    else
        log_warn ".venv yok; rclpy + venv denetimi atlandı"
    fi
}

if [[ "$MODE" == "install" ]]; then
    install_component
fi
if [[ "$MODE" == "verify" || "$DRY_RUN" -eq 0 ]]; then
    verify_component
fi
component_finish "$COMPONENT_NAME"
