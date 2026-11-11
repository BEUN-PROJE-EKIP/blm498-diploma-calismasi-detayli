#!/usr/bin/env bash
# setup/env.sh — proje ortamı: ROS 2, Python venv, RMW ve alan kimliği.
# DOĞRUDAN ÇALIŞTIRILMAZ; kabuğa alınır:  source setup/env.sh
# Sırayla: (a) ROS 2 setup.bash (varsa), (b) .venv etkinleştirme (varsa), (c) RMW ve ROS_DOMAIN_ID, (d) ROOT_DIR/PROJE_ROOT.
# Çoklu `source` zararsızdır; `set -u` altında kaynaklanan kabukları bozmaz.
# ROS_LOCALHOST_ONLY BİLEREK ayarlanmaz (ölçülen ağ 10.10.0.0/24 olacak).
# Fast DDS profil değişkeni (FASTRTPS_DEFAULT_PROFILES_FILE) ilerleyen aşamada buraya eklenecek.

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
    export ROOT_DIR="$root"
    export PROJE_ROOT="$root"

    [[ "$had_u" -eq 1 ]] && set -u
    return 0
}
_proje_env_main
unset -f _proje_env_main
