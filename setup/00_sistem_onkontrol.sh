#!/usr/bin/env bash
# 00_sistem_onkontrol.sh — kurulumdan önce makinenin uygunluğunu denetler, donanımı raporlar.
# Salt okunur: hiçbir şey kurmaz/değiştirmez. Yalnız proje içindeki .generated/ altına yazar.
# Kullanım: ./00_sistem_onkontrol.sh [--dry-run | --verify | -h]
#   --dry-run ve --verify bu betik için ön kontrolü çalıştırmakla aynıdır.
set -Eeuo pipefail

# Root koruması: common.sh kaynaklanmadan önce; hiçbir dosya oluşturulmaz.
if [[ $EUID -eq 0 ]]; then
    echo "(-) Betik root olarak çalıştırılmamalı; normal kullanıcıyla çalıştırın." >&2
    exit 1
fi

# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
parse_common_args "$@"
COMPONENT_NAME="Sistem ön kontrolü"
load_versions

HW_FILE="$GENERATED_DIR/hardware.env"
printf '# Bu dosya 00_sistem_onkontrol.sh tarafından üretilir; elle düzenlemeyin.\n# HW_CPU_L3_GROUPS: Linux cpulist biçimi (aralıklı olabilir, ör. 0-7,16-23).\n' > "$HW_FILE"

# packages.ros.org sertifikası osuosl.org için verilmiş; HTTPS adı uyuşmuyor, apt HTTP+GPG kullanır.
NET_URLS=(
    "http://packages.ros.org/ros2/ubuntu/dists/noble/InRelease"
    "https://packages.osrfoundation.org/gazebo.gpg"
    "https://pypi.org/simple/pip/"
    "https://download.pytorch.org/whl/torch/"
    "https://github.com/PX4/PX4-Autopilot"
)

log_info "Sistem ön kontrolü başlıyor (sürüm kilidi: Ubuntu $REQUIRED_UBUNTU, CUDA >= $CUDA_MIN)"

# --- 1) İşletim sistemi ve mimari -------------------------------------------
os_id=""; os_ver=""
if [[ -r /etc/os-release ]]; then
    os_id="$(. /etc/os-release; echo "${ID:-}")"
    os_ver="$(. /etc/os-release; echo "${VERSION_ID:-}")"
fi
arch="$(uname -m)"
if [[ "$os_id" == "ubuntu" && "$os_ver" == "$REQUIRED_UBUNTU" ]]; then
    log_ok "İşletim sistemi: Ubuntu $os_ver"
else
    log_fail "İşletim sistemi Ubuntu $REQUIRED_UBUNTU olmalı; bulunan: '${os_id:-?} ${os_ver:-?}'"
fi
if [[ "$arch" == "x86_64" ]]; then log_ok "Mimari: $arch"; else log_fail "Mimari x86_64 olmalı; bulunan: $arch"; fi

# --- 2) root değil, sudo var -------------------------------------------------
if [[ "$(id -u)" -ne 0 ]]; then
    log_ok "Betik normal kullanıcıyla çalışıyor ($(id -un))"
else
    log_fail "Betik root olarak çalıştırılıyor; normal kullanıcıyla çalıştırın"
fi
if have_cmd sudo; then log_ok "sudo komutu mevcut"; else log_fail "sudo komutu bulunamadı"; fi

# --- 3) Dil ------------------------------------------------------------------
if [[ "${LANG:-}" == en_* ]]; then
    log_ok "Dil: LANG=$LANG"
else
    log_warn "LANG 'en_' ile başlamıyor (LANG='${LANG:-}'); hedef sistem İngilizce olmalı"
fi

# --- 4) Ağ erişimi -----------------------------------------------------------
if have_cmd curl; then
    for url in "${NET_URLS[@]}"; do
        check "Ağ erişimi: $url" curl -fsS --max-time 10 -o /dev/null "$url"
    done
else
    log_fail "Ağ erişimi denetlenemedi: curl yok"
fi

# --- 5-7) NVIDIA GPU, açık çekirdek modülü, CUDA ----------------------------
gpu_name=""; gpu_vram=""; gpu_driver=""; cuda_ver=""
if have_cmd nvidia-smi && gpu_line="$(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits 2>/dev/null | sed -n 1p)" && [[ -n "$gpu_line" ]]; then
    IFS=',' read -r gpu_name gpu_driver gpu_vram <<< "$gpu_line"
    gpu_name="${gpu_name#"${gpu_name%%[![:space:]]*}"}"; gpu_driver="${gpu_driver//[[:space:]]/}"; gpu_vram="${gpu_vram//[[:space:]]/}"
    log_ok "GPU: $gpu_name, sürücü $gpu_driver, VRAM ${gpu_vram} MiB"
    cuda_ver="$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: *\([0-9][0-9.]*\).*/\1/p' | sed -n 1p)"
else
    log_fail "nvidia-smi bulunamadı veya GPU görünmüyor"
fi

if [[ -r /proc/driver/nvidia/version ]] && grep -q "Open Kernel Module" /proc/driver/nvidia/version; then
    log_ok "NVIDIA sürücüsü açık çekirdek modülü (Open Kernel Module)"
else
    log_fail "NVIDIA sürücüsü açık çekirdek modülü değil veya /proc/driver/nvidia/version okunamadı"
fi

if [[ -n "$cuda_ver" ]] && version_ge "$cuda_ver" "$CUDA_MIN"; then
    log_ok "CUDA sürümü (nvidia-smi): $cuda_ver >= $CUDA_MIN"
else
    log_fail "CUDA sürümü >= $CUDA_MIN olmalı; bulunan: '${cuda_ver:-okunamadı}'"
fi

# --- 8) Hibrit grafik --------------------------------------------------------
hybrid="no"
if have_cmd lspci; then
    other_gfx="$(lspci 2>/dev/null | grep -E 'VGA compatible|Display controller|3D controller' | grep -vi nvidia || true)"
    if [[ -n "$other_gfx" ]]; then
        hybrid="yes"
        log_info "Hibrit grafik: NVIDIA dışında ayrıca görüntü aygıtı var: $(echo "$other_gfx" | cut -d: -f3- | sed 's/^ *//' | paste -sd';' -)"
        log_info "PRIME/Gazebo'nun NVIDIA kullandığı ilerleyen aşamada doğrulanacak"
    else
        log_info "Hibrit grafik: NVIDIA dışında görüntü aygıtı görünmüyor"
    fi
else
    log_warn "lspci bulunamadı (pciutils); hibrit grafik denetlenemedi"
fi

# --- 9) CPU ------------------------------------------------------------------
cpu_model="$(lscpu | sed -n 's/^Model name:[[:space:]]*//p' | sed -n 1p)"
cpu_logical="$(nproc --all)"
cpu_physical="$(lscpu -p=CORE,SOCKET | grep -v '^#' | sort -u | wc -l)"
tpc=0
if [[ "$cpu_physical" -gt 0 ]]; then tpc=$((cpu_logical / cpu_physical)); fi
log_info "CPU: $cpu_model | fiziksel çekirdek: $cpu_physical | mantıksal CPU: $cpu_logical | iş parçacığı/çekirdek: $tpc"
if [[ "$cpu_logical" -ge 12 ]]; then log_ok "Mantıksal CPU sayısı >= 12 ($cpu_logical)"; else log_fail "Mantıksal CPU sayısı >= 12 olmalı; bulunan: $cpu_logical"; fi
if [[ "$tpc" -eq 2 ]]; then log_ok "SMT açık (2 iş parçacığı/çekirdek)"; else log_fail "SMT kapalı veya beklenmeyen değer (iş parçacığı/çekirdek = $tpc)"; fi

# --- 10) CPU topolojisi ------------------------------------------------------
# Çekirdek aralık yazabilir (0-1); her satır cpulist_expand ile "a,b" biçimine açılır.
sibling_pairs=""
raw_siblings="$(cat /sys/devices/system/cpu/cpu[0-9]*/topology/thread_siblings_list 2>/dev/null | sort -u || true)"
if [[ -n "$raw_siblings" ]]; then
    norm=""
    while IFS= read -r line; do
        rc_exp=0
        exp="$(cpulist_expand "$line")" || rc_exp=$?
        if [[ "$rc_exp" -eq 1 ]]; then log_warn "thread_siblings_list ayrıştırılamadı: '$line'"; continue; fi
        if [[ "$rc_exp" -eq 2 ]]; then log_warn "Çekirdekte 3+ iş parçacığı var ($line); çift olarak yazılmadı"; fi
        exp="${exp// /,}"
        norm+="$exp"$'\n'
    done <<< "$raw_siblings"
    sibling_pairs="$(printf '%s' "$norm" | sort -u -t, -k1,1n | paste -sd' ' - || true)"
fi
l3_groups="$(cat /sys/devices/system/cpu/cpu[0-9]*/cache/index3/shared_cpu_list 2>/dev/null | sort -t- -k1,1n -u | paste -sd' ' - || true)"
if [[ -n "$sibling_pairs" ]]; then log_info "Kardeş çiftleri: $sibling_pairs"; else log_warn "thread_siblings_list okunamadı"; fi
if [[ -n "$l3_groups" ]]; then log_info "L3 önbellek grupları: $l3_groups"; else log_warn "L3 önbellek grupları (index3/shared_cpu_list) okunamadı"; fi

# --- 11) RAM -----------------------------------------------------------------
ram_gib=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
if [[ "$ram_gib" -ge "$MIN_RAM_GIB" ]]; then log_ok "RAM: ${ram_gib} GiB >= ${MIN_RAM_GIB}"; else log_fail "RAM >= ${MIN_RAM_GIB} GiB olmalı; bulunan: ${ram_gib} GiB"; fi

# --- 12) Boş disk ------------------------------------------------------------
disk_gib="$(df -BG --output=avail "$ROOT_DIR" | tail -n1 | tr -dc '0-9')"
if [[ -n "$disk_gib" && "$disk_gib" -ge "$MIN_FREE_DISK_GIB" ]]; then
    log_ok "Boş disk ($ROOT_DIR): ${disk_gib} GiB >= ${MIN_FREE_DISK_GIB}"
else
    log_fail "Boş disk >= ${MIN_FREE_DISK_GIB} GiB olmalı; bulunan: '${disk_gib:-?}' GiB"
fi

# --- 13) Gerekli araçlar (eksikler uyarıdır; sonraki betikler kurar) --------
py_ver=""
if have_cmd python3; then py_ver="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"; fi
if [[ "$py_ver" == "$PYTHON_REQUIRED" ]]; then log_ok "python3 sürümü: $py_ver"; else log_warn "python3 sürümü $PYTHON_REQUIRED olmalı; bulunan: '${py_ver:-yok}'"; fi
check_warn "python3-venv (ensurepip)" python3 -c "import ensurepip"
check_warn "pip (python3 -m pip)" python3 -m pip --version
for tool in git curl wget tc gcc cmake; do
    check_warn "Araç mevcut: $tool" command -v "$tool"
done

# --- 14) ROS 2 / Gazebo / PX4 ön durumu (yalnız bilgi) ----------------------
if [[ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]]; then log_info "ROS 2 $ROS_DISTRO: kurulu"; else log_info "ROS 2 $ROS_DISTRO: kurulu değil"; fi
if have_cmd gz; then log_info "Gazebo (gz): kurulu"; else log_info "Gazebo (gz): kurulu değil"; fi
if [[ -d "$ROOT_DIR/PX4-Autopilot" || -d "$ROOT_DIR/third_party/PX4-Autopilot" ]]; then log_info "PX4-Autopilot: proje içinde var"; else log_info "PX4-Autopilot: proje içinde yok"; fi

# --- Çıktı: hardware.env -----------------------------------------------------
write_env_kv HW_CPU_MODEL          "$cpu_model"      "$HW_FILE"
write_env_kv HW_CPU_PHYSICAL_CORES "$cpu_physical"   "$HW_FILE"
write_env_kv HW_CPU_LOGICAL        "$cpu_logical"    "$HW_FILE"
write_env_kv HW_CPU_SIBLING_PAIRS  "$sibling_pairs"  "$HW_FILE"
write_env_kv HW_CPU_L3_GROUPS      "$l3_groups"      "$HW_FILE"
write_env_kv HW_RAM_GIB            "$ram_gib"        "$HW_FILE"
write_env_kv HW_GPU_NAME           "$gpu_name"       "$HW_FILE"
write_env_kv HW_GPU_VRAM_MIB       "$gpu_vram"       "$HW_FILE"
write_env_kv HW_NVIDIA_DRIVER      "$gpu_driver"     "$HW_FILE"
write_env_kv HW_CUDA_VERSION       "$cuda_ver"       "$HW_FILE"
write_env_kv HW_DISK_FREE_GIB      "${disk_gib:-}"   "$HW_FILE"
write_env_kv HW_HYBRID_GRAPHICS    "$hybrid"         "$HW_FILE"
log_info "Donanım raporu yazıldı: $HW_FILE"

component_finish "$COMPONENT_NAME" "geçti"
