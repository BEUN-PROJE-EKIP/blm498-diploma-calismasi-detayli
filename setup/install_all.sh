#!/usr/bin/env bash
# install_all.sh — setup/NN_*.sh betiklerini sırayla çalıştırır (başarısız adımda durur).
# Kullanım: ./install_all.sh [--dry-run] [--only NN[,NN...]] [--from NN] [--check-order] [-h]
#   --dry-run      hiçbir şey kurmaz; her adımı --dry-run ile çalıştırır (sudo çağrılmaz)
#   --only         yalnız verilen numaralı adımlar
#   --from         verilen numaradan (dahil) itibaren
#   --check-order  yalnız statik denetim: adım sırası 00,05,10,20,30,40,50,60 mı ve her adımın bağımlılığı ondan önce mi (hiçbir şey çalıştırmaz)
# Gerçek çalıştırmada önce 00_sistem_onkontrol.sh çalışır; geçmezse şifre SORULMAZ ve kurulum başlamaz.
# Geçerse başta bir kez `sudo -v` ister ve yetkiyi canlı tutar; çıkışta (Ctrl-C dahil) canlı tutma süreci sonlandırılır.
# Sonda .generated/kurulum_raporu.md yazılır (dry-run'da yazılmaz).
set -Eeuo pipefail

if [[ $EUID -eq 0 ]]; then
    echo "(-) Betik root olarak çalıştırılmamalı; normal kullanıcıyla çalıştırın." >&2
    exit 1
fi

# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/rapor.sh
source "$SETUP_DIR/lib/rapor.sh"

# Ctrl-C / SIGTERM: normal çıkışa çevir; EXIT tuzağı (common.sh) sudo canlı tutma sürecini ve geçici dosyaları temizler.
trap 'exit 130' INT
trap 'exit 143' TERM

usage() { echo "Kullanım: ${0##*/} [--dry-run] [--only NN[,NN...]] [--from NN] [--check-order] [-h]" >&2; }

# Beklenen adım sırası ve bağımlılıklar (statik; yeni adım eklenirse burası güncellenmelidir).
EXPECTED_ORDER=(00 05 10 20 30 40 50 60)
declare -A STEP_DEPS=(
    [00]=""        # ön kontrol: bağımlılık yok
    [05]="00"      # temel paketler (python3-venv, iproute2, curl…)
    [10]="05"      # ROS 2: curl, gnupg, python3-pip
    [20]="05"      # Gazebo: curl, gnupg, lsb-release
    [30]="05 20"   # PX4: python3-venv (.venv-px4 için) ve Gazebo geliştirme paketleri (derleme)
    [40]="05"      # Python ortamı: python3-venv, pip
    [50]="10 20 40"  # proje derlemesi: ROS 2 (colcon, rclpy), Gazebo geliştirme paketleri (damga bileşeni), Python ortamı (kosu/test araçları)
    [60]="05"      # tc ağ emülasyonu: iproute2
)

# check_order : (+)/(-) yazar; sıra veya bağımlılık hatası varsa 1 döndürür.
check_order() {
    local -a actual=()
    local -A idx=()
    local f n d i rc=0
    for f in "${STEP_FILES[@]}"; do actual+=("$(step_num "$f")"); done
    for i in "${!actual[@]}"; do idx[${actual[$i]}]="$i"; done
    if [[ "${actual[*]}" == "${EXPECTED_ORDER[*]}" ]]; then
        log_ok "Adım sırası beklenenle aynı: ${actual[*]}"
    else
        log_fail "Adım sırası beklenenden farklı: bulunan '${actual[*]}', beklenen '${EXPECTED_ORDER[*]}'"
        rc=1
    fi
    for n in "${actual[@]}"; do
        for d in ${STEP_DEPS[$n]:-}; do
            if [[ -n "${idx[$d]:-}" && "${idx[$d]}" -lt "${idx[$n]}" ]]; then
                log_ok "Adım $n: bağımlılık $d ondan önce"
            else
                log_fail "Adım $n: bağımlılık $d yok veya sonra geliyor"
                rc=1
            fi
        done
    done
    return "$rc"
}

ONLY=""; FROM=""; DRY_RUN=0; CHECK_ORDER=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --check-order) CHECK_ORDER=1; shift ;;
        --only) [[ $# -ge 2 ]] || { usage; exit 2; }; ONLY="$2"; shift 2 ;;
        --from) [[ $# -ge 2 ]] || { usage; exit 2; }; FROM="$2"; shift 2 ;;
        -h|--help) print_help; exit 0 ;;
        *) echo "Bilinmeyen argüman: $1" >&2; usage; exit 2 ;;
    esac
done
if [[ -n "$ONLY" && ! "$ONLY" =~ ^[0-9]{2}(,[0-9]{2})*$ ]]; then echo "--only değeri NN[,NN...] olmalı: '$ONLY'" >&2; usage; exit 2; fi
if [[ -n "$FROM" && ! "$FROM" =~ ^[0-9]{2}$ ]]; then echo "--from değeri NN olmalı: '$FROM'" >&2; usage; exit 2; fi

START=$SECONDS
discover_steps

# Statik sıra/bağımlılık denetimi her çalıştırmada yapılır (ucuz); hata varsa hiçbir şey çalıştırılmaz.
if ! check_order; then
    log_fail "Adım sırası/bağımlılık denetimi başarısız; hiçbir şey çalıştırılmadı"
    exit 1
fi
if [[ "$CHECK_ORDER" -eq 1 ]]; then exit 0; fi

# Varolmayan --only numaralarını yok say (uyarı ver).
if [[ -n "$ONLY" ]]; then
    for n in ${ONLY//,/ }; do
        found=0
        for f in "${STEP_FILES[@]}"; do [[ "$(step_num "$f")" == "$n" ]] && found=1; done
        if [[ "$found" -eq 0 ]]; then log_warn "Adım $n yok; yok sayıldı"; fi
    done
fi

for f in "${STEP_FILES[@]}"; do
    n="$(step_num "$f")"
    if [[ -n "$ONLY" && ! ",$ONLY," == *",$n,"* ]]; then continue; fi
    if [[ -n "$FROM" && "$((10#$n))" -lt "$((10#$FROM))" ]]; then continue; fi
    SELECTED_FILES+=("$f")
done
if [[ "${#SELECTED_FILES[@]}" -eq 0 ]]; then
    log_fail "Çalıştırılacak adım seçilmedi"
    exit 1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    log_info "Kip: dry-run (hiçbir şey kurulmaz/değiştirilmez)"
    run_steps 1 --dry-run
else
    log_info "Bu betik ROS 2, Gazebo, PX4 SITL ve Python ortamını kurar; ağ hızına ve işlemciye göre onlarca dakika sürebilir (PX4 derlemesi en uzun adımdır). Önce ön kontrol çalışır; geçerse sudo şifresi BİR kez istenir. Ctrl-C ile durdurmak güvenlidir: betikler tekrar çalıştırılabilir (idempotent), kaldığı yerden devam eder."
    log_info "=== Ön kontrol kapısı (00_sistem_onkontrol.sh) ==="
    if ! bash "$SETUP_DIR/00_sistem_onkontrol.sh"; then
        log_fail "Ön kontrol başarısız: sudo şifresi istenmedi, kurulum başlatılmadı. Yukarıdaki (-) satırlarını giderip yeniden çalıştırın."
        exit 1
    fi
    sudo_keepalive_start
    run_steps 1
fi

rc=0
total=$((SECONDS - START))
print_steps_table "$total" || rc=$?
if [[ "$DRY_RUN" -eq 0 ]]; then
    load_versions
    write_install_report install "$total"
fi
if [[ "$rc" -eq 0 ]]; then log_ok "Tüm adımlar başarılı"; else log_fail "Başarısız adım var; kurulum durduruldu"; fi
exit "$rc"
