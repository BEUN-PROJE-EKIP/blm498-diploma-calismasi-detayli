#!/usr/bin/env bash
# 05_temel_paketler.sh — derleme, ağ ve betik araçları gibi temel apt paketlerini kurar.
# Kullanım: ./05_temel_paketler.sh [--dry-run | --verify | -h]
#   (argümansız)  eksik paketleri kurar (sudo gerekir), sonda doğrular; zaten kuruluysa atlar
#   --dry-run     hiçbir şey kurmaz/değiştirmez; yapacağı komutları yazar
#   --verify      yalnız salt okunur denetim (sudo/ağ gerektirmez)
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
parse_common_args "$@"
COMPONENT_NAME="Temel paketler"
require_not_root

PACKAGES=(build-essential cmake git curl wget ca-certificates gnupg lsb-release pciutils
          iproute2 jq unzip python3-pip python3-venv python3-dev shellcheck
          bc dmidecode libeigen3-dev pkg-config protobuf-compiler)
# Son beş paket PX4'ün Tools/setup/ubuntu.sh dosyasındaki "Simulation tools" bölümünden gelir; temiz bir makinede
# PX4 SITL derlemesi bunlara (özellikle eigen3 ve protobuf-compiler) tesadüfen kurulu olmalarına bağımlı kalmasın diye eklendi.
SIM_PKGS=(bc dmidecode libeigen3-dev pkg-config protobuf-compiler)

verify_component() {
    check "cmake çalışıyor" cmake --version
    check "pip çalışıyor" python3 -m pip --version
    check "shellcheck çalışıyor" shellcheck --version
    check "ip (iproute2) çalışıyor" ip -V
    local pkg
    for pkg in "${SIM_PKGS[@]}"; do
        if apt_pkg_installed "$pkg"; then log_ok "apt paketi kurulu: $pkg"; else log_fail "apt paketi kurulu değil: $pkg"; fi
    done
}

if [[ "$MODE" == "install" ]]; then
    apt_ensure "${PACKAGES[@]}"
fi
if [[ "$MODE" == "verify" || "$DRY_RUN" -eq 0 ]]; then
    verify_component
fi
component_finish "$COMPONENT_NAME"
