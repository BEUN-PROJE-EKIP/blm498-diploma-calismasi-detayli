#!/usr/bin/env bash
# kamera_alici_testi.sh — araç kamerası (B6), Gazebo damga bileşeni (B7) ve kamera alıcısı (B8) kabul testleri (başsız Gazebo + PX4 SITL + araç süreçleri + deneme koordinatörü).
# Kullanım: ./kamera_alici_testi.sh [--dry-run | --verify | -h] [birim] [tek] [kayip] [uc]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz, hiçbir şey derlemez; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, kurulu paketler); süreç başlatmaz
# Testler:
#   birim   kamera alıcısı ve durum makinesi birim testleri (ROS'suz), kalibrasyon --check, damga bileşeni derlemesi, colcon build, tek komut yolu taraması
#   tek     --arac 1, hata enjeksiyonu KAPALI: kayıpsız tam akış, damga birleşmesi, 640×480 RGB8 kare biçimi, kare hızı, kamera yönelim/eksen denemesi (yer işareti, Gazebo pozu)
#   kayip   --arac 1, hata enjeksiyonu AÇIK (KAMERA_ENJEKSIYON): tek ve ardışık iki kare düşürülür, bir kare geciktirilip "kare alınamadı"dan sonra teslim edilir, n_son düşürülür
#   uc      --arac 3, enjeksiyon kapalı: üç alıcı, kimlik eşlemesi, her araçta kayıpsız tam aralık ve damga birleşmesi, RTF ve kare üretim hızı
# Araç süreçleri, koordinatör ve görüş denemesi `setsid` ile ayrı süreç gruplarında başlatılır, günlükleri koşu klasöründe; her çıkışta bu betik kendisi toplar.
# Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ. sudo gerekmez.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/derleme.sh
source "$SETUP_DIR/lib/derleme.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        birim|tek|kayip|uc) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(birim tek kayip uc)
COMPONENT_NAME="Araç kamerası, damga bileşeni ve kamera alıcısı"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
KOORD="$ROOT_DIR/araclar/deneme/koordinator_deneme.py"
ANALIZ="$ROOT_DIR/araclar/analiz/kamera_alici_analiz.py"
GORUS="$ROOT_DIR/araclar/deneme/kamera_gorus_deneme.py"
KAMERA_URET="$ROOT_DIR/araclar/uretim/kamera_uret.py"
BIRIM_TEST="$ROOT_DIR/src/swarm_vehicle/test/test_durum_makinesi.py"
BIRIM_TEST2="$ROOT_DIR/src/swarm_vehicle/test/test_kamera_alici.py"
EK_ENV=()
PKG_DIR="$ROOT_DIR/src/swarm_vehicle"
VENV_PY="$ROOT_DIR/.venv/bin/python"
ENV_SH="$SETUP_DIR/env.sh"
DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
ROS_SETUP="/opt/ros/$ROS_DISTRO/setup.bash"
KOK="$GENERATED_DIR/kosular"
TMP_DIR=""
PGIDS=()

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

grup_oldur() { # grup_oldur <pgid> : önce TERM, 5 sn sonra KILL
    local pg="$1" i
    kill -TERM -- "-$pg" 2>/dev/null || true
    for ((i = 0; i < 50; i++)); do kill -0 -- "-$pg" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL -- "-$pg" 2>/dev/null || true
}

exit_hook() {
    [[ "${DRY_RUN:-0}" -eq 0 && "${MODE:-install}" != verify ]] || return 0   # --dry-run/--verify hiçbir süreç başlatmaz; yaşayan (başkasına ait) koşuya DOKUNMAZ
    local i
    for ((i = ${#PGIDS[@]} - 1; i >= 0; i--)); do grup_oldur "${PGIDS[$i]}"; done
    PGIDS=()
    if [[ -f "$KOK/aktif" ]]; then "$KOSU" temizle >/dev/null 2>&1 || true; fi
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
    TMP_DIR=""
}

[[ -f "$DENEY_ENV" ]] || fail_stop "Yapılandırma yok: $DENEY_ENV"
# shellcheck source=/dev/null
source "$DENEY_ENV"
for v in SIM_WORLD UAV_SYS_IDS UAV_NAMESPACES UAV1_ADDR UAV2_ADDR UAV3_ADDR GCS_ADDR DURUM_YAYIN_HZ KONU_DURUM KOSU_KAPANIS_SN; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
read -r -a SYS_IDS <<< "$UAV_SYS_IDS"

# venv dışı PATH (ROS araçları sistem Python'unu kullansın)
clean_path() { local p="" d; local IFS=':'; for d in $PATH; do [[ "$d" == "$ROOT_DIR/.venv"* || "$d" == "$ROOT_DIR/.venv-px4/"* ]] || p+="${p:+:}$d"; done; echo "$p"; }
# shellcheck disable=SC2016  # tek tırnak bilerek: $1 alt kabukta açılır
ros_run() { env -u VIRTUAL_ENV PATH="$(clean_path)" bash -c 'source "$1"; shift; "$@"' _ "$ROS_SETUP" "$@"; }

check_prereqs() {
    local c f
    for c in gz ss pgrep python3 awk colcon git tc; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "setup/env.sh" test -f "$ENV_SH"
    check "ROS 2 setup.bash" test -f "$ROS_SETUP"
    for f in "$KOSU" "$KOORD" "$ANALIZ" "$GORUS" "$KAMERA_URET" "$BIRIM_TEST" "$BIRIM_TEST2" "$PKG_DIR/swarm_vehicle/arac.py" "$PKG_DIR/swarm_vehicle/kamera/kamera_alici.py" "$PKG_DIR/swarm_vehicle/kamera/kamera_alici_gz.py" "$PKG_DIR/swarm_vehicle/ucus/px4_adapter.py" "$ROOT_DIR/src/yayim_damga/yayim_damga.cc"; do
        check "Dosya: ${f#"$ROOT_DIR"/}" test -f "$f"
    done
    check "Yapılandırılmış sürü ağı (lo üzerinde htb)" bash -c '[[ "$(tc qdisc show dev lo)" == *htb* ]]'
    check "kosu.sh --dry-run baslat çıkış 0" "$KOSU" --dry-run baslat
}

print_plan() {
    log_info "[dry-run] birim: birim testleri (durum makinesi, kamera alıcısı), kamera_uret.py kalibrasyon --check, damga bileşeni derlemesi (kosu.sh), colcon build swarm_msgs swarm_vehicle, tek komut yolu taraması"
    log_info "[dry-run] tek: kosu.sh baslat --arac 1 → koordinatör + araç süreci 1 (enjeksiyon kapalı) + görüş denemesi → analiz (görev aralığı, damga birleşmesi, kare biçimi/hızı, eksen) → durdur"
    log_info "[dry-run] kayip: araç süreci KAMERA_ENJEKSIYON='bekle=0.6;dusur=+20,+60,+61,son;gecik=+100' → kare alınamadı / geç geldi / sondaki kayıp denetimi"
    log_info "[dry-run] uc: kosu.sh baslat --arac 3 → koordinatör + üç araç süreci (enjeksiyon kapalı) → her araçta kayıpsız aralık ve damga birleşmesi, RTF"
    log_info "[dry-run] Her testten sonra araç süreci/koordinatör/px4/gz/mavsdk_server artığı, yeni dinleyen port, /dev/shm; sonda ros2 daemon, tc/ip denetimi. Hiçbir süreç başlatılmadı"
}

if [[ "$MODE" == "verify" ]]; then
    check_prereqs
    component_finish "$COMPONENT_NAME"
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
    print_plan
    component_finish "$COMPONENT_NAME"
fi

check_prereqs
[[ "$COUNT_FAIL" -eq 0 ]] || fail_stop "Önkoşullar eksik"
TMP_DIR="$(mktemp -d)"

# --- Ölçüm anlık görüntüleri -------------------------------------------------------
shm_list() { find /dev/shm -maxdepth 1 -printf '%f\n' 2>/dev/null | LC_ALL=C sort || true; }
snapshot() { # snapshot <ad>
    local n="$1" c
    {
        for c in px4 gz mavsdk_server ruby; do echo "proc $c $(pgrep -x -c "$c" || true)"; done
        echo "proc arac $(pgrep -f -c 'swarm_vehicle[.]arac' || true)"
        echo "proc koordinator $(pgrep -f -c 'koordinator_deneme[.]py' || true)"
    } > "$TMP_DIR/$n.proc"
    port_snapshot "$TMP_DIR/$n.ports"
    shm_list > "$TMP_DIR/$n.shm"
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$TMP_DIR/$n.net"
}

kalan_yok() { # kalan_yok <etiket>
    local et="$1" ok=1 yeni
    sleep 1
    snapshot "k_$et"
    if ! diff -q "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" >/dev/null; then ok=0; log_fail "$et: artık süreç var: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" | tr '\n' ';' || true)"; fi
    yeni="$(port_yeni "$TMP_DIR/once.ports" "$TMP_DIR/k_$et.ports")"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: yeni dinleyen port(lar): $yeni"; fi
    yeni="$(comm -13 "$TMP_DIR/once.shm" "$TMP_DIR/k_$et.shm" | tr '\n' ' ')"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: /dev/shm artığı: $yeni"; fi
    if [[ "$(pgrep -a -x ruby; pgrep -af '[g]z sim')" != "" ]]; then ok=0; log_fail "$et: gz sim süreci kaldı"; fi
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0 (gz/ruby/px4/mavsdk_server/araç süreci/koordinatör), yeni dinleyen port 0, /dev/shm artığı 0"; fi
    return 0
}

KOSU_DIR=""
PART=""
kosu_baslat() { # kosu_baslat <ad> [kosu.sh argümanları...]
    local ad="$1" out id rc=0 l; shift
    out="$("$KOSU" baslat "$@" 2>&1)" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: baslat başarısız (çıkış $rc)"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; return 1
    fi
    id="$(cat "$KOK/aktif")"
    KOSU_DIR="$KOK/$id"
    PART="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" gz_partition)"
    log_ok "$ad: baslat tamam, koşu $id"
    return 0
}

komut_dene() {
    local log="$1" ok="$2" hata="$3"; shift 3
    if "$@" > "$log" 2>&1; then log_ok "$ok"; else log_fail "$hata"; tail -n 8 "$log"; fi
}

json_gecerli() { # json_gecerli <ad> <beklenen_bitis_durumu>
    local ad="$1" bekl="$2" out bd l
    if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kosu.json" 2>&1)"; then log_ok "$ad: kosu.json doğrulayıcıdan geçti"; else log_fail "$ad: kosu.json GEÇERSİZ"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; fi
    bd="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" bitis_durumu)"
    if [[ "$bd" == "$bekl" ]]; then log_ok "$ad: bitiş durumu '$bd'"; else log_fail "$ad: bitiş durumu '$bd' (beklenen '$bekl')"; fi
}

# ros_baslat <çıktı_dosyası> <komut...> : setsid ile ayrı süreç grubunda, ROS + venv ortamında; LAST_PG = grup lideri
LAST_PG=""
ros_baslat() {
    local cikti="$1"; shift
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    setsid env GZ_PARTITION="$PART" GZ_IP=127.0.0.1 LC_NUMERIC=C "${EK_ENV[@]+"${EK_ENV[@]}"}" bash -c 'source "$1" >/dev/null 2>&1; source "$2/install/setup.bash"; shift 2; exec "$@"' _ "$ENV_SH" "$ROOT_DIR" "$@" \
        > "$cikti" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
}

tc_bayt() { # sürü sınıfı (1:10) için gönderilen bayt sayısı
    tc -s class show dev lo 2>/dev/null | awk '/^class htb 1:10 / {f=1} f && /Sent/ {print $2; exit}'
}

# senaryo_calistir <ad> <araç_sayısı> <görüş:0|1> <koordinatör_argümanları...> : araç süreçleri + koordinatör (+ görüş denemesi); koordinatör çıkışı beklenir
senaryo_calistir() {
    local ad="$1" n="$2" gorus="$3" i kpg gpg="" kmax rc=0 t0=$SECONDS tc0 tc1; shift 3
    local -a apid=()
    tc0="$(tc_bayt)"
    ros_baslat "$KOSU_DIR/koordinator.out" timeout -k 5 1200 python "$KOORD" --arac "$n" --zaman-asimi-sn 1100 "$@"
    kpg="$LAST_PG"
    sleep 4
    for ((i = 1; i <= n; i++)); do
        ros_baslat "$KOSU_DIR/arac_$i.out" python -m swarm_vehicle.arac "$i"
        apid+=("$LAST_PG")
    done
    if [[ "$gorus" -eq 1 ]]; then ros_baslat "$KOSU_DIR/gorus.out" python "$GORUS" --arac-sirasi 1; gpg="$LAST_PG"; fi
    log_info "$ad: koordinatör pid $kpg, araç süreçleri pid ${apid[*]}${gpg:+, görüş denemesi pid $gpg}; enjeksiyon: ${EK_ENV[*]:-kapalı}"
    wait "$kpg" 2>/dev/null || rc=$?
    for ((i = 0; i < n; i++)); do
        local arc=0
        for ((kmax = 0; kmax < 300; kmax++)); do kill -0 "${apid[$i]}" 2>/dev/null || break; sleep 0.1; done
        if kill -0 "${apid[$i]}" 2>/dev/null; then log_fail "$ad: araç $((i + 1)) süreci TAMAMLANDI'dan sonra 30 sn içinde kapanmadı"; else wait "${apid[$i]}" 2>/dev/null || arc=$?; fi
        if [[ "$arc" -eq 0 ]]; then log_ok "$ad: araç $((i + 1)) süreci kendiliğinden kapandı (çıkış 0)"; else log_fail "$ad: araç $((i + 1)) süreci çıkış kodu $arc"; tail -n 6 "$KOSU_DIR/arac_$((i + 1)).out"; fi
    done
    if [[ -n "$gpg" ]]; then
        kill -TERM "$gpg" 2>/dev/null || true
        for ((kmax = 0; kmax < 100; kmax++)); do kill -0 "$gpg" 2>/dev/null || break; sleep 0.1; done
        wait "$gpg" 2>/dev/null || true
    fi
    if [[ "$rc" -eq 0 ]]; then log_ok "$ad: koordinatör çıkış 0 ($((SECONDS - t0)) sn gerçek)"; else log_fail "$ad: koordinatör çıkış kodu $rc"; tail -n 8 "$KOSU_DIR/koordinator.out"; fi
    tc1="$(tc_bayt)"
    log_info "$ad: sürü sınıfı (tc 1:10) gönderilen bayt: $tc0 → $tc1"
    PGIDS=()
}

analiz() { # analiz <ad> <analiz argümanları...> : SONUC satırlarını (+)/(-) yapar
    local ad="$1" line rc=0; shift
    python3 -I "$ANALIZ" "$KOSU_DIR" "$@" > "$TMP_DIR/$ad.analiz.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            "OLCUM "*) log_info "$ad: ${line#OLCUM }" ;;
            Traceback*|*Error*) log_fail "$ad: analiz hatası: $line" ;;
        esac
    done < "$TMP_DIR/$ad.analiz.log"
    if [[ "$rc" -ne 0 ]]; then log_fail "$ad: analiz çıkış kodu $rc"; tail -n 12 "$TMP_DIR/$ad.analiz.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
}

kayit_dosyalari_gecerli() { # kayit_dosyalari_gecerli <ad> <n> : gerçek koşu kayıtları (damga + alıcılar) doğrulayıcıdan geçer
    local ad="$1" n="$2" i out f
    for f in "$KOSU_DIR/kayit/gazebo_damga.jsonl" $(for ((i = 1; i <= n; i++)); do echo "$KOSU_DIR/kayit/kamera_alici_${SYS_IDS[$((i - 1))]}.jsonl"; done); do
        if out="$(python3 -I "$DOGRULA" "$f" 2>&1)"; then
            log_ok "$ad: gerçek kayıt doğrulayıcıdan geçti: ${f##*/} ($(tail -n 1 <<< "$out" | sed 's/, .*jsonl)/)/'))"
        else
            log_fail "$ad: kayıt GEÇERSİZ: ${f##*/}: $(head -n 3 <<< "$out" | tr '\n' ';')"
        fi
    done
}

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

# --- Testler ----------------------------------------------------------------------------
test_birim() {
    local out rc=0 l mod
    log_info "== birim: birim testleri, kalibrasyon, damga bileşeni, derleme, tek komut yolu =="
    for mod in "$BIRIM_TEST" "$BIRIM_TEST2"; do
        if out="$("$VENV_PY" -I "$mod" 2>&1)"; then log_ok "birim: ${mod##*/} geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: ${mod##*/} BAŞARISIZ"; tail -n 15 <<< "$out"; fi
    done
    if out="$(python3 -I "$KAMERA_URET" kalibrasyon --check 2>&1)"; then log_ok "birim: kalibrasyon dosyası güncel: $out"; else log_fail "birim: kalibrasyon dosyası güncel değil: $out"; fi
    if out="$(python3 -I "$DOGRULA" "$ROOT_DIR/config/kamera_kalibrasyon.json" 2>&1)"; then log_ok "birim: kalibrasyon doğrulayıcıdan geçti"; else log_fail "birim: kalibrasyon reddedildi: $out"; fi
    if python3 -I -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])) == json.load(open(sys.argv[2])) else 1)' "$ROOT_DIR/config/kamera_kalibrasyon.json" "$ROOT_DIR/config/ornek/kamera_kalibrasyon_ornek.json"; then
        log_ok "birim: kalibrasyon örnekle değerce aynı"
    else
        log_fail "birim: kalibrasyon örnekten farklı"
    fi
    out="$GENERATED_DIR/kamera_derleme.txt"
    if proje_derle "$out"; then
        log_ok "birim: proje derlendi (swarm_msgs + swarm_vehicle + swarm_gcs; ortak yol: setup/lib/derleme.sh)"
    else
        log_fail "birim: proje derlemesi BAŞARISIZ; günlük: ${out#"$ROOT_DIR"/}"
        tail -n 12 "$out" | while IFS= read -r l; do log_info "  | $l"; done
    fi
    rc=0
    ( cmake -S "$ROOT_DIR/src/yayim_damga" -B "$GENERATED_DIR/yayim_damga/build" > "$TMP_DIR/cmake.log" 2>&1 && cmake --build "$GENERATED_DIR/yayim_damga/build" -j "$(nproc)" > "$TMP_DIR/derle.log" 2>&1 ) || rc=$?
    if [[ "$rc" -eq 0 && -f "$GENERATED_DIR/yayim_damga/build/libYayimDamga.so" ]]; then log_ok "birim: damga bileşeni derlendi (.generated/yayim_damga/build/libYayimDamga.so)"; else log_fail "birim: damga bileşeni derlenemedi"; tail -n 12 "$TMP_DIR/derle.log" 2>/dev/null; fi
    for mod in kamera_alici durum_makinesi rota; do
        rc=0
        # shellcheck disable=SC2016  # tek tırnak bilerek: Python kodu
        "$VENV_PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import importlib; importlib.import_module("swarm_vehicle." + sys.argv[2]); assert not ({"rclpy", "mavsdk", "gz"} & set(sys.modules))' \
            "$PKG_DIR" "$mod" > "$TMP_DIR/ice_$mod.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "birim: swarm_vehicle.$mod rclpy/mavsdk/gz olmadan içe aktarıldı"; else log_fail "birim: swarm_vehicle.$mod içe aktarma hatası"; tail -n 5 "$TMP_DIR/ice_$mod.log"; fi
    done
    rc=0
    "$VENV_PY" -m py_compile "$PKG_DIR/swarm_vehicle/arac.py" "$PKG_DIR/swarm_vehicle/kamera/kamera_alici.py" "$PKG_DIR/swarm_vehicle/kamera/kamera_alici_gz.py" "$KAMERA_URET" "$GORUS" "$ANALIZ" "$KOORD" > "$TMP_DIR/pyc.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: py_compile temiz"; else log_fail "birim: py_compile hata"; tail -n 5 "$TMP_DIR/pyc.log"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '^\s*(from|import) mavsdk' -- src || true)"
    if [[ -n "$out" && "$(awk -F: '{print $1}' <<< "$out" | sort -u)" == "src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py" ]]; then log_ok "birim: src/ altında mavsdk'yı içe aktaran tek dosya px4_adapter.py"; else log_fail "birim: mavsdk içe aktarımı beklenenden farklı: $out"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '\.action\.|\.mission\b|\.mission_raw|\.param\.set|set_param|set_rate_|\.offboard\.|send_message' -- src ':!src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: src/ altında px4_adapter.py dışında PX4'e yazan çağrı yok"; else log_fail "birim: dış çağrı: $out"; fi
    log_info "birim: PX4 model dizininde 'kamera' adlı dosya/dizin sayısı (0 beklenir; PX4 kaynağına dokunulmaz): $(find "$ROOT_DIR/third_party/PX4-Autopilot/Tools/simulation/gz/models" -maxdepth 1 -name '*kamera*' | wc -l)"
}

test_tek() {
    local ad=tek
    log_info "== tek: araç 1, enjeksiyon kapalı, kayıpsız tam akış + görüş denemesi =="
    EK_ENV=()
    if kosu_baslat "$ad" --arac 1; then
        senaryo_calistir "$ad" 1 1
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur       # damga kaydının son boşaltması SIGTERM'de yapılır: analizden ÖNCE
        json_gecerli "$ad" tamamlandi
        analiz "$ad" --arac 1 --gorus
        kayit_dosyalari_gecerli "$ad" 1
        if [[ -f "$KOSU_DIR/gorus_ornek_merkez.png" ]]; then log_ok "$ad: görüntü örneği koşu klasöründe: ${KOSU_DIR#"$ROOT_DIR"/}/gorus_ornek_merkez.png (depoya girmez)"; else log_fail "$ad: görüntü örneği yok"; fi
    fi
    kalan_yok "$ad"
}

test_kayip() {
    local ad=kayip
    log_info "== kayip: araç 1, hata enjeksiyonu AÇIK =="
    EK_ENV=(KAMERA_ENJEKSIYON='bekle=0.6;dusur=+20,+60,+61,son;gecik=+100')
    if kosu_baslat "$ad" --arac 1; then
        senaryo_calistir "$ad" 1 0
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
        analiz "$ad" --arac 1 --enjeksiyon
        kayit_dosyalari_gecerli "$ad" 1
        if grep -q 'kamera_enjeksiyon durum=bekle' "$KOSU_DIR/arac_${SYS_IDS[0]}.log"; then log_ok "$ad: enjeksiyonun AÇIK olduğu araç günlüğüne yazıldı"; else log_fail "$ad: araç günlüğünde enjeksiyon kaydı yok"; fi
    fi
    EK_ENV=()
    kalan_yok "$ad"
}

test_uc() {
    local ad=uc
    [[ "${#SYS_IDS[@]}" -ge 3 ]] || { log_fail "uc: yapılandırmada 3 araç yok"; return; }
    log_info "== uc: üç araç, enjeksiyon kapalı =="
    EK_ENV=()
    if kosu_baslat "$ad" --arac 3; then
        senaryo_calistir "$ad" 3 0
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
        analiz "$ad" --arac 3
        kayit_dosyalari_gecerli "$ad" 3
        local i
        for ((i = 1; i <= 3; i++)); do
            if grep -q 'kamera_enjeksiyon durum=kapali' "$KOSU_DIR/arac_${SYS_IDS[$((i - 1))]}.log"; then log_ok "$ad: araç $i günlüğünde hata enjeksiyonu KAPALI kaydı var"; else log_fail "$ad: araç $i günlüğünde enjeksiyon durumu yok"; fi
        done
    fi
    kalan_yok "$ad"
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server; pgrep -af 'swarm_vehicle[.]arac|koordinator_deneme[.]py')" ]]; then
    fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server/araç süreci/koordinatör yaşıyor; önce kapatın"
fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), ROS $ROS_DISTRO, PX4 $PX4_TAG; testler: ${TESTS[*]}"

if want birim; then test_birim; fi
if want tek; then test_tek; fi
if want kayip; then test_kayip; fi
if want uc; then test_uc; fi

# --- Son denetim ------------------------------------------------------------------------------
snapshot sonra
if diff -q "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" >/dev/null; then
    log_ok "tc/ip durumu (lo) değişmedi"
else
    log_fail "lo üzerindeki tc/ip durumu değişti: $(diff "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" | tr '\n' ';' || true)"
fi
if [[ "$DAEMON_ONCE" -eq 0 ]]; then
    if pgrep -f '[r]os2-daemon' >/dev/null; then log_fail "Artık ros2 daemon süreci var"; else log_ok "ros2 daemon süreci yok"; fi
fi

component_finish "$COMPONENT_NAME" "tamamlandı (${TESTS[*]} ve süreç/port/shm/tc denetimi)"
