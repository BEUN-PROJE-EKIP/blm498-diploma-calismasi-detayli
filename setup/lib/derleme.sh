#!/usr/bin/env bash
# lib/derleme.sh — proje derlemesi ortak yardımcıları (KAYNAK ALINIR, doğrudan çalıştırılmaz). 50_proje_derleme.sh, araclar/kosu.sh ve test betikleri derleme kodunu BURADAN kullanır (kopyalamaz).
# Gerekli: lib/common.sh kaynak alınmış (ROOT_DIR, log_*), load_versions çağrılmış (ROS_DISTRO).

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Bu dosya doğrudan çalıştırılmaz; kaynak alın: source setup/lib/derleme.sh" >&2
    exit 1
fi

# Derlenen paketler (src/ altında): ileti tanımları, araç paketi, yer istasyonu paketi.
PROJE_PAKETLERI=(swarm_msgs swarm_vehicle swarm_gcs)

# venv'siz PATH: colcon ve ROS araçları sistem Python'unu (ROS'un Python'u) kullansın; .venv ve .venv-px4 PATH'ten çıkarılır.
derleme_temiz_path() {
    local p="" d
    local IFS=':'
    for d in $PATH; do
        [[ "$d" == "$ROOT_DIR/.venv"* || "$d" == "$ROOT_DIR/.venv-px4/"* ]] || p+="${p:+:}$d"
    done
    echo "$p"
}

# proje_derle <günlük_dosyası> : PROJE_PAKETLERI'ni proje kökünde `colcon build` ile derler (ROS kaynaklı, venv DIŞI). Çıktı günlük dosyasına yazılır.
# Dönen: 0 = bütün paketler derlendi (günlüğün sonunda "N packages finished"); aksi hâlde 1. Değişiklik yoksa colcon hızlıdır (idempotent).
proje_derle() {
    local out="$1" rc=0 n="${#PROJE_PAKETLERI[@]}" ros_setup="/opt/ros/${ROS_DISTRO}/setup.bash"
    mkdir -p "$(dirname "$out")"
    if [[ ! -f "$ros_setup" ]]; then echo "ROS 2 setup.bash yok: $ros_setup (önce setup/10_ros2_jazzy.sh)" > "$out"; return 1; fi
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1.. alt kabukta açılır
    (cd "$ROOT_DIR" && env -u VIRTUAL_ENV PATH="$(derleme_temiz_path)" bash -c 'source "$1"; shift; colcon build --base-paths src --packages-select "$@"' _ "$ros_setup" "${PROJE_PAKETLERI[@]}") > "$out" 2>&1 || rc=$?
    [[ "$rc" -eq 0 && "$(tail -n 3 "$out")" == *"$n packages finished"* ]]
}

# damga_derle <kaynak_klasör> <yapı_klasörü> [günlük_klasörü] : Gazebo damga bileşenini (src/yayim_damga) cmake ile derler; yapı klasöründeki libYayimDamga.so kaynaktan yeniyse atlar.
# Çıktı klasörü yalnız verilen yapı klasörüdür. Dönen: 0 = lib hazır. Mesajları log_ok/log_fail/log_info ile yazar.
damga_derle() {
    local src="$1" build="$2" glog="${3:-$2/..}" jobs gen=() lib yeni
    lib="$build/libYayimDamga.so"
    yeni="$(find "$src" -type f \( -name '*.cc' -o -name '*.hh' -o -name CMakeLists.txt \) -newer "$lib" 2>/dev/null | head -n 1 || true)"
    if [[ -f "$lib" && -z "$yeni" ]]; then log_ok "Damga bileşeni güncel: ${lib#"$ROOT_DIR"/}"; return 0; fi
    jobs="$(nproc)"
    if command -v ninja >/dev/null; then gen=(-G Ninja); fi
    log_info "Damga bileşeni derleniyor: cmake -S ${src#"$ROOT_DIR"/} -B ${build#"$ROOT_DIR"/} (-j $jobs)"
    mkdir -p "$build" "$glog"
    cmake -S "$src" -B "$build" "${gen[@]}" > "$glog/cmake.log" 2>&1 || { log_fail "cmake yapılandırması başarısız (${glog#"$ROOT_DIR"/}/cmake.log)"; return 1; }
    cmake --build "$build" -j "$jobs" > "$glog/build.log" 2>&1 || { log_fail "Damga bileşeni derlenemedi (${glog#"$ROOT_DIR"/}/build.log)"; return 1; }
    [[ -f "$lib" ]] || { log_fail "Derleme çıktısı eksik: $lib"; return 1; }
    log_ok "Damga bileşeni derlendi: ${lib#"$ROOT_DIR"/}"
}
