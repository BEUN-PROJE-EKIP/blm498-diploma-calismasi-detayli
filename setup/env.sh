#!/usr/bin/env bash
# setup/env.sh — proje ortamı: ROS 2, Python venv, RMW ve alan kimliği.
# DOĞRUDAN ÇALIŞTIRILMAZ; kabuğa alınır:  source setup/env.sh
# Sırayla: (a) ROS 2 setup.bash (varsa), (b) .venv etkinleştirme (varsa), (c) RMW ve ROS_DOMAIN_ID, (d) ROOT_DIR/PROJE_ROOT.
# Çoklu `source` zararsızdır; `set -u` altında kaynaklanan kabukları bozmaz.
# ROS_LOCALHOST_ONLY BİLEREK ayarlanmaz (ölçülen ağ 10.10.0.0/24 olacak).
# Fast DDS: tek ortak profil (config/fastdds_profil.xml) FASTRTPS_DEFAULT_PROFILES_FILE ile gösterilir; RMW_FASTRTPS_USE_QOS_FROM_XML=1
# ile yayıncı/abone profilleri (data-sharing kapalı) rmw_fastrtps_cpp tarafından da XML'den alınır. Profildeki ${SWARM_BIND_ADDR}
# yer tutucusu her sürecin kendi sürü adresidir (UAV1_ADDR/UAV2_ADDR/UAV3_ADDR/GCS_ADDR); süreci başlatan betik bunu ayarlar,
# burada ayarlanmaz. Tanımsızken Fast DDS bir hata satırı basar (gürültü kabul) VE profili hiç yüklemeden varsayılan ayarlara
# düşer (sessiz profilsiz çalışma); hata satırı tek başına yeterli koruma değildir, başlatıcılar değişkeni her zaman açıkça verir.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Bu dosya doğrudan çalıştırılmaz; kabuğa alın:  source setup/env.sh" >&2
    exit 1
fi

_proje_env_main() {
    local here root distro ros_setup venv_act
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    root="$(dirname "$here")"
    distro="$(sed -n 's/^ROS_DISTRO="\(.*\)"/\1/p' "$here/versions.env" 2>/dev/null | sed -n 1p)"
    ros_setup="/opt/ros/${distro}/setup.bash"
    venv_act="$root/.venv/bin/activate"

    # ROS ve venv betikleri `set -u` ile uyumlu değildir; geçici olarak kapat.
    local had_u=0
    [[ $- == *u* ]] && had_u=1
    set +u

    if [[ -n "$distro" && -f "$ros_setup" ]]; then
        # shellcheck disable=SC1090
        source "$ros_setup"
    else
        echo "(!) ROS 2 ${distro:-?} kurulu değil: ${ros_setup} yok (setup/10_ros2_jazzy.sh)" >&2
    fi

    if [[ -f "$venv_act" ]]; then
        if [[ "${VIRTUAL_ENV:-}" != "$root/.venv" ]]; then
            # shellcheck disable=SC1090
            source "$venv_act"
        fi
    else
        echo "(!) Python venv yok: $root/.venv (setup/40_python_ortami.sh)" >&2
    fi

    export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
    export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
    local dds_profile="$root/config/fastdds_profil.xml"
    if [[ -f "$dds_profile" ]]; then
        export FASTRTPS_DEFAULT_PROFILES_FILE="$dds_profile"
        export RMW_FASTRTPS_USE_QOS_FROM_XML=1
    else
        echo "(!) Fast DDS profili yok: $dds_profile" >&2
    fi
    export ROOT_DIR="$root"
    export PROJE_ROOT="$root"

    [[ "$had_u" -eq 1 ]] && set -u
    return 0
}
_proje_env_main
unset -f _proje_env_main
