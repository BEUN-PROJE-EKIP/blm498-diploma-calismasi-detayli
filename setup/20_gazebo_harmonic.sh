#!/usr/bin/env bash
# 20_gazebo_harmonic.sh — Gazebo Harmonic'i OSRF deposundan kurar (anahtar SHA-256 kilitli) ve gz-transport Python bağlamalarını doğrular.
# Kullanım: ./20_gazebo_harmonic.sh [--dry-run | --verify | -h]
#   (argümansız)  kurar (sudo gerekir), sonda doğrular; zaten kuruluysa atlar
#   --dry-run     hiçbir şey kurmaz/indirmez; yapacağı komutları yazar
#   --verify      yalnız denetim (sudo gerektirmez): paketler, sunucu-yalnız duman testi, Python bağlamaları
# Ayar dosyası / ~/.bashrc değişikliği yapmaz.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
parse_common_args "$@"
COMPONENT_NAME="Gazebo Harmonic"
require_not_root
load_versions

ENV_SH="$SETUP_DIR/env.sh"
KEY_FILE="$GENERATED_DIR/downloads/gazebo.gpg"
KEYRING="/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg"
SOURCES_LIST="/etc/apt/sources.list.d/gazebo-stable.list"
PACKAGES=("gz-${GZ_RELEASE}" "libgz-sim${GZ_SIM_MAJOR}-dev" "python3-gz-transport${GZ_TRANSPORT_MAJOR}" "python3-gz-msgs${GZ_MSGS_MAJOR}" cppzmq-dev libunwind-dev)


fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

install_component() {
    local codename source_line got
    codename="$(lsb_release -cs 2>/dev/null || true)"
    [[ -n "$codename" ]] || fail_stop "Ubuntu kod adı (lsb_release -cs) okunamadı; önce 05_temel_paketler.sh çalıştırılmalı"
    source_line="deb [arch=amd64 signed-by=$KEYRING] http://packages.osrfoundation.org/gazebo/ubuntu-stable $codename main"

    # 1) Anahtar halkası (SHA-256 kilitli)
    if [[ -f "$KEYRING" && "$(sha256sum "$KEYRING" | cut -d' ' -f1)" == "$GZ_OSRF_KEY_SHA256" ]]; then
        log_ok "Anahtar halkası zaten kurulu ve özeti doğru: $KEYRING"
    else
        got=""
        if [[ -f "$KEY_FILE" ]]; then got="$(sha256sum "$KEY_FILE" | cut -d' ' -f1)"; fi
        if [[ "$got" == "$GZ_OSRF_KEY_SHA256" ]]; then
            log_ok "Anahtar zaten indirilmiş ve SHA-256 doğru: ${KEY_FILE#"$ROOT_DIR"/}"
        else
            if [[ "$DRY_RUN" -eq 0 ]]; then mkdir -p "$(dirname "$KEY_FILE")"; fi
            run "Gazebo anahtarı indiriliyor" curl -fsSL -o "$KEY_FILE" "$GZ_OSRF_KEY_URL"
            if [[ "$DRY_RUN" -eq 1 ]]; then
                log_info "[dry-run] sha256sum $KEY_FILE == $GZ_OSRF_KEY_SHA256 doğrulanır"
            else
                got="$(sha256sum "$KEY_FILE" | cut -d' ' -f1)"
                if [[ "$got" != "$GZ_OSRF_KEY_SHA256" ]]; then
                    rm -f "$KEY_FILE"
                    fail_stop "Anahtar SHA-256 uyuşmuyor (beklenen $GZ_OSRF_KEY_SHA256, bulunan $got); dosya silindi, sudo çağrılmadı"
                fi
                log_ok "Anahtar SHA-256 doğrulandı"
            fi
        fi
        sudo_run "Anahtar halkası kuruluyor" install -m 0644 "$KEY_FILE" "$KEYRING"
        APT_UPDATED=0
    fi

    # 2) apt kaynak dosyası
    if [[ -f "$SOURCES_LIST" && "$(cat "$SOURCES_LIST")" == "$source_line" ]]; then
        log_ok "Kaynak dosyası zaten doğru: $SOURCES_LIST"
    else
        if [[ "$DRY_RUN" -eq 1 ]]; then
            log_info "[dry-run] printf '%s\\n' '$source_line' | sudo tee $SOURCES_LIST"
        else
            run "Kaynak dosyası yazılıyor ($SOURCES_LIST)" bash -c 'printf "%s\n" "$1" | sudo tee "$2" > /dev/null' _ "$source_line" "$SOURCES_LIST"
        fi
        APT_UPDATED=0
    fi

    # 3) Paketler (eksik varsa apt-get update + install)
    apt_ensure "${PACKAGES[@]}"
}

# --- Doğrulama ---------------------------------------------------------------
in_env() { bash -c 'source "$1" 2>/dev/null; shift; "$@"' _ "$ENV_SH" "$@"; }

SMOKE_PIDS=()
smoke_cleanup() {
    local p
    for p in "${SMOKE_PIDS[@]}"; do kill -TERM -- "-$p" 2>/dev/null || true; done
    sleep 0.5
    for p in "${SMOKE_PIDS[@]}"; do kill -KILL -- "-$p" 2>/dev/null || true; done
    SMOKE_PIDS=()
    return 0
}
exit_hook() { smoke_cleanup; }

gz_versions_ok() {
    local v; v="$(gz sim --versions 2>/dev/null || true)"
    [[ "$v" == 8.* ]]
}

# Sunucu-yalnız duman testi: gz sim -s (grafik arayüzsüz) arka planda; gz topic -l içinde /clock veya /stats.
gz_server_smoke() {
    export GZ_PARTITION="proje_smoke_$$"
    setsid timeout -s INT -k 3 15 gz sim -s -r -v 2 empty.sdf > /dev/null 2>&1 &
    SMOKE_PIDS+=("$!")
    local topics="" i
    for i in 1 2 3 4 5 6; do
        sleep 1
        topics="$(timeout 5 gz topic -l 2>/dev/null || true)"
        if grep -qE '^/(clock|stats)$' <<< "$topics"; then break; fi
    done
    local ok=1
    grep -qE '^/(clock|stats)$' <<< "$topics" || ok=0
    smoke_cleanup
    [[ "$ok" -eq 1 ]]
}

verify_component() {
    if [[ -f "$KEYRING" && "$(sha256sum "$KEYRING" | cut -d' ' -f1)" == "$GZ_OSRF_KEY_SHA256" ]]; then
        log_ok "Anahtar halkası var ve SHA-256 doğru: $KEYRING"
    else
        log_fail "Anahtar halkası yok veya özeti uyuşmuyor: $KEYRING"
    fi
    if [[ -f "$SOURCES_LIST" ]] && grep -q "signed-by=$KEYRING" "$SOURCES_LIST"; then
        log_ok "Kaynak dosyası var: $SOURCES_LIST"
    else
        log_fail "Kaynak dosyası yok veya anahtar halkasını göstermiyor: $SOURCES_LIST"
    fi
    local pkg
    for pkg in "${PACKAGES[@]}"; do
        if apt_pkg_installed "$pkg"; then log_ok "Paket kurulu: $pkg"; else log_fail "Paket kurulu değil: $pkg"; fi
    done

    if ! have_cmd gz; then
        log_fail "gz komutu yok; sürüm, sunucu duman testi ve Python bağlama denetimleri yapılamadı"
        return 0
    fi
    check "gz sim --versions '8.' ile başlıyor (Harmonic)" gz_versions_ok
    check "Sunucu-yalnız duman testi (gz sim -s -r empty.sdf; gz topic -l → /clock veya /stats)" gz_server_smoke
    smoke_cleanup

    if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
        local err
        if err="$(in_env python -c 'from gz.transport13 import Node; from gz.msgs10.image_pb2 import Image' 2>&1)"; then
            log_ok "venv içinde gz.transport13 ve gz.msgs10.image_pb2 içe aktarıldı"
        else
            log_fail "venv içinde gz Python bağlamaları içe aktarılamadı (tam hata aşağıda)"
            log_info "$err"
        fi
        local venv_pb sys_pb
        venv_pb="$("$ROOT_DIR/.venv/bin/python" -c 'import google.protobuf as p; print(p.__version__)' 2>/dev/null || echo "?")"
        sys_pb="$(/usr/bin/python3 -I -c 'import google.protobuf as p; print(p.__version__)' 2>/dev/null || echo "?")"
        log_info "protobuf sürümleri — venv: $venv_pb | sistem (python3, apt): $sys_pb | apt paketi python3-protobuf: $(dpkg-query -W -f='${Version}' python3-protobuf 2>/dev/null || echo yok)"
    else
        log_warn ".venv yok; gz Python bağlama denetimi atlandı"
    fi
}

if [[ "$MODE" == "install" ]]; then
    install_component
fi
if [[ "$MODE" == "verify" || "$DRY_RUN" -eq 0 ]]; then
    verify_component
fi
component_finish "$COMPONENT_NAME"
