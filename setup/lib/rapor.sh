#!/usr/bin/env bash
# setup/lib/rapor.sh — kurulum raporunu oluşturan işlevler (.generated/kurulum_raporu.md). `source` edilmek için yazılmıştır
# (common.sh'ten SONRA). install_all.sh ve verify_all.sh sonunda write_install_report çağırır.
# Gizlilik: ev dizini "~" olur; kullanıcı adı ve makine adı maskelenir. Gizli bilgi (şifre/token) hiç toplanmaz.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Bu dosya doğrudan çalıştırılmaz; bir betikten 'source' edilir." >&2
    exit 1
fi

# shellcheck source=ortam.sh
source "$SETUP_DIR/lib/ortam.sh"

REPORT_FILE="$GENERATED_DIR/kurulum_raporu.md"

# _sed_escape <metin> : sed düzenli ifadesinde sabit metin olarak kullanılabilsin
_sed_escape() { printf '%s' "$1" | sed 's/[][\.*^$/|]/\\&/g'; }

# _report_sanitize : stdin -> stdout; ev dizini "~", kullanıcı adı ve makine adı maskelenir
_report_sanitize() {
    local home_re user_re host_re user host
    user="$(id -un 2>/dev/null || true)"; host="$(hostname 2>/dev/null || true)"
    home_re="$(_sed_escape "$HOME")"
    local -a prog=(-e "s|${home_re}|~|g")
    if [[ "${#user}" -ge 3 ]]; then user_re="$(_sed_escape "$user")"; prog+=(-e "s|${user_re}|<kullanıcı>|g"); fi
    if [[ "${#host}" -ge 3 ]]; then host_re="$(_sed_escape "$host")"; prog+=(-e "s|${host_re}|<makine>|g"); fi
    sed "${prog[@]}"
}

# _pip_ver <paket> : venv'deki kurulu sürüm (PIP_FREEZE değişkeninden); yoksa boş
_pip_ver() {
    awk -F'==' -v p="$(printf '%s' "$1" | tr 'A-Z_' 'a-z-')" '{ n = tolower($1); gsub(/_/, "-", n); if (n == p && !f) { print $2; f = 1 } }' <<< "${PIP_FREEZE:-}"
}

# _report_env_record : apt ve NVIDIA/CUDA kayıtlarının şu anki durumla farkını tek satırda özetler
_report_env_record() {
    local tmp d n m
    if [[ -f "$ORTAM_APT_FILE" ]]; then
        tmp="$(mktemp)"
        ortam_apt_now > "$tmp"
        n="$(wc -l < "$ORTAM_APT_FILE")"
        d="$(ortam_apt_diff "$ORTAM_APT_FILE" "$tmp")"
        rm -f "$tmp"
        m=0; if [[ -n "$d" ]]; then m="$(wc -l <<< "$d")"; fi
        echo "- apt kaydı: $n paket, kilitle fark: $m"
    else
        echo "- apt kaydı: kayıt yok"
    fi
    if [[ -f "$ORTAM_NV_FILE" ]]; then
        local rec now
        rec="$(sed -n 1p "$ORTAM_NV_FILE")"; now="$(ortam_nvidia_now | sed -n 1p)"
        if [[ "$rec" == "$now" ]]; then echo "- NVIDIA/CUDA kaydı: $rec (kayıtla aynı)"; else echo "- NVIDIA/CUDA kaydı: $rec; şimdi: $now (FARKLI)"; fi
    else
        echo "- NVIDIA/CUDA kaydı: kayıt yok"
    fi
}

_report_body() { # _report_body <kip> <toplam_sn>
    local mode="$1" total="$2" i
    local venv_py="$ROOT_DIR/.venv/bin/python"
    local os_pretty="" os_ver="" ros_inst="" gz_inst="" px4_inst="" py_inst="" cuda_inst="" v

    # shellcheck disable=SC1091
    os_pretty="$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-?}")"
    os_ver="$(. /etc/os-release 2>/dev/null; echo "${VERSION_ID:-?}")"
    ros_inst="$(dpkg-query -W -f='${Version}' "ros-${ROS_DISTRO}-ros-base" 2>/dev/null || true)"
    if have_cmd gz; then gz_inst="$(timeout 10 gz sim --versions 2>/dev/null | sed -n 1p || true)"; fi
    if [[ -e "$ROOT_DIR/third_party/PX4-Autopilot/.git" ]]; then
        px4_inst="$(git -C "$ROOT_DIR/third_party/PX4-Autopilot" describe --tags --exact-match 2>/dev/null || true)"
        if [[ -n "$px4_inst" ]]; then
            px4_inst="$px4_inst ($(git -C "$ROOT_DIR/third_party/PX4-Autopilot" rev-parse --short=12 HEAD 2>/dev/null || true))"
        else
            px4_inst="etiketsiz"
        fi
    fi
    PIP_FREEZE=""
    if [[ -x "$venv_py" ]]; then
        py_inst="$("$venv_py" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
        PIP_FREEZE="$("$venv_py" -m pip list --format=freeze 2>/dev/null || true)"
    fi

    echo "# Kurulum raporu"
    echo
    echo "- Tarih: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "- Kip: $([[ "$mode" == "install" ]] && echo 'kurulum (install_all.sh)' || echo 'doğrulama (verify_all.sh)')"
    echo "- Proje dizini: $ROOT_DIR"
    echo "- İşletim sistemi: $os_pretty"
    echo
    echo "## Donanım"
    echo
    if [[ -f "$GENERATED_DIR/hardware.env" ]]; then
        (
            set +u
            # shellcheck disable=SC1091
            source "$GENERATED_DIR/hardware.env"
            echo "| Öğe | Değer |"
            echo "|---|---|"
            echo "| CPU | ${HW_CPU_MODEL:-?} |"
            echo "| Fiziksel çekirdek / mantıksal CPU | ${HW_CPU_PHYSICAL_CORES:-?} / ${HW_CPU_LOGICAL:-?} |"
            echo "| RAM | ${HW_RAM_GIB:-?} GiB |"
            echo "| GPU | ${HW_GPU_NAME:-yok} (${HW_GPU_VRAM_MIB:-?} MiB) |"
            echo "| NVIDIA sürücüsü | ${HW_NVIDIA_DRIVER:-?} |"
            echo "| CUDA (nvidia-smi) | ${HW_CUDA_VERSION:-?} |"
            echo "| Boş disk | ${HW_DISK_FREE_GIB:-?} GiB |"
            echo "| Hibrit grafik | ${HW_HYBRID_GRAPHICS:-?} |"
        )
    else
        echo "_hardware.env yok (00_sistem_onkontrol.sh henüz çalışmadı)._"
    fi
    echo
    echo "## Sürümler"
    echo
    echo "| Bileşen | Kilitli (versions.env) | Kurulu (gerçek) |"
    echo "|---|---|---|"
    echo "| Ubuntu | $REQUIRED_UBUNTU | $os_ver |"
    echo "| ROS 2 | $ROS_DISTRO | $([[ -n "$ros_inst" ]] && echo "ros-base $ros_inst" || echo 'kurulu değil') |"
    echo "| Gazebo | $GZ_RELEASE | ${gz_inst:-kurulu değil} |"
    echo "| PX4 | $PX4_TAG | ${px4_inst:-kurulu değil} |"
    echo "| Python (.venv) | $PYTHON_REQUIRED | ${py_inst:-.venv yok} |"
    local -a pairs=("torch:$TORCH_VERSION" "torchvision:$TORCHVISION_VERSION" "ultralytics:$ULTRALYTICS_VERSION" \
                    "mavsdk:$MAVSDK_VERSION" "onnxruntime:$ONNXRUNTIME_VERSION" "numpy:$NUMPY_VERSION" "scipy:$SCIPY_VERSION")
    local pair name want
    for pair in "${pairs[@]}"; do
        name="${pair%%:*}"; want="${pair#*:}"
        v="$(_pip_ver "$name")"
        if [[ -z "$v" && "$name" == "onnxruntime" ]]; then v="$(_pip_ver onnxruntime-gpu)"; fi
        echo "| $name | $want | ${v:-kurulu değil} |"
    done
    cuda_inst="$(set +u; source "$GENERATED_DIR/hardware.env" 2>/dev/null; echo "${HW_CUDA_VERSION:-}")"
    echo "| CUDA | ≥ $CUDA_MIN | ${cuda_inst:-okunamadı} |"
    echo
    echo "## Ortam kaydı"
    echo
    _report_env_record
    echo
    echo "## Adımlar"
    echo
    echo "| NN | Bileşen | Sonuç | Süre |"
    echo "|---|---|---|---|"
    for i in "${!RES_NUM[@]}"; do
        echo "| ${RES_NUM[$i]} | ${RES_NAME[$i]} | ${RES_SYM[$i]} | ${RES_SECS[$i]} |"
    done
    echo
    echo "Toplam süre: ${total} sn"
}

# write_install_report <install|verify> <toplam_sn> : .generated/kurulum_raporu.md dosyasının üzerine yazar.
# RES_NUM/RES_NAME/RES_SYM/RES_SECS (run_steps) ve versions.env değişkenleri (load_versions) hazır olmalı.
write_install_report() {
    local mode="$1" total="$2" tmp
    mkdir -p "$GENERATED_DIR"
    tmp="$(mktemp "$REPORT_FILE.XXXXXX")"
    REPORT_TMP="$tmp"
    _report_body "$mode" "$total" | _report_sanitize > "$tmp"
    mv "$tmp" "$REPORT_FILE"
    REPORT_TMP=""
    log_info "Kurulum raporu yazıldı: ${REPORT_FILE/#$HOME/\~}"
}
