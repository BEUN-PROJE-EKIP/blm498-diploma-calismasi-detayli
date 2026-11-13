#!/usr/bin/env bash
# px4_adapter_testi.sh — px4_adapter (src/swarm_vehicle) ve bölge/rota üretimi kabul testleri; başsız Gazebo + PX4 SITL.
# Kullanım: ./px4_adapter_testi.sh [--dry-run | --verify | -h] [statik] [rota] [tek] [uc] [yetim]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz, hiçbir şey derlemez; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, yapılandırma); süreç başlatmaz
# Testler:
#   statik  colcon build (swarm_vehicle); px4_adapter ve rota rclpy olmadan yüklenir; tek komut yolu taraması (MAVSDK yalnız px4_adapter.py'de)
#   rota    rota_uret.py iki kez bayt bayt aynı; doğrulayıcı kabul; örnekle değerce aynı; --check güncel (+) / bozuk (-)
#   tek     tek araç koşusu: kimlik koruması (yanlış kimlik, yüklenmemiş görev) ve araç 1 tam görev (kanıt: Gazebo model pozu)
#   uc      üç araç koşusu: üç bağdaştırıcı, üç ayrı mavsdk_server, üç rota yüklenir ve başlatılır; her biri ilk noktaya yaklaşır (Gazebo)
#   yetim   bağdaştırıcıyı barındıran sürece SIGKILL: yetim kalan mavsdk_server'ı kosu.sh temizle kapatır
# Her testten sonra artık süreç / yeni dinleyen port / /dev/shm artığı denetlenir. Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ
# (adı NN_ desenine uymaz). sudo gerekmez.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        statik|rota|tek|uc|yetim) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(statik rota tek uc yetim)
COMPONENT_NAME="px4_adapter ve bölge/rota üretimi"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
ROTA_URET="$ROOT_DIR/araclar/rota_uret.py"
DENEME="$ROOT_DIR/araclar/px4_adapter_deneme.py"
ROTA_DOSYA="$ROOT_DIR/config/bolge_rota.json"
ORNEK_ROTA="$ROOT_DIR/config/ornek/bolge_rota_ornek.json"
PKG_DIR="$ROOT_DIR/src/swarm_vehicle"
VENV_PY="$ROOT_DIR/.venv/bin/python"
DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
ROS_SETUP="/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
KOK="$GENERATED_DIR/kosular"
TMP_DIR=""

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

exit_hook() {
    if [[ -f "$KOK/aktif" ]]; then "$KOSU" temizle >/dev/null 2>&1 || true; fi
    if [[ -n "${YETIM_PY_PID:-}" ]]; then kill -KILL "$YETIM_PY_PID" 2>/dev/null || true; fi
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
    TMP_DIR=""
}

[[ -f "$DENEY_ENV" ]] || fail_stop "Yapılandırma yok: $DENEY_ENV"
# shellcheck source=/dev/null
source "$DENEY_ENV"
for v in SIM_WORLD UAV_SYS_IDS MAVSDK_GRPC_PORTS KOSU_KAPANIS_SN ROTA_IRTIFA_M PX4A_KOMUT_SN; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
read -r -a SYS_IDS <<< "$UAV_SYS_IDS"
read -r -a GRPC_PORTS <<< "$MAVSDK_GRPC_PORTS"

# venv dışı PATH (ROS araçları sistem Python'unu kullansın)
clean_path() { local p="" d; local IFS=':'; for d in $PATH; do [[ "$d" == "$ROOT_DIR/.venv"* || "$d" == "$ROOT_DIR/.venv-px4/"* ]] || p+="${p:+:}$d"; done; echo "$p"; }
# shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
ros_run() { # ros_run <komut...> : venv dışı ortamda ROS 2 kurulu olarak çalıştırır
    env -u VIRTUAL_ENV PATH="$(clean_path)" bash -c 'source "$1"; shift; "$@"' _ "$ROS_SETUP" "$@"
}

check_prereqs() {
    local c
    for c in gz ss pgrep python3 awk colcon git; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "Koşu betiği: ${KOSU#"$ROOT_DIR"/}" test -x "$KOSU"
    check "Deneme sürücüsü: ${DENEME#"$ROOT_DIR"/}" test -f "$DENEME"
    check "Rota üretim aracı: ${ROTA_URET#"$ROOT_DIR"/}" test -f "$ROTA_URET"
    check "Paket: src/swarm_vehicle/package.xml" test -f "$PKG_DIR/package.xml"
    check "Modül: src/swarm_vehicle/swarm_vehicle/px4_adapter.py" test -f "$PKG_DIR/swarm_vehicle/px4_adapter.py"
    check "Modül: src/swarm_vehicle/swarm_vehicle/rota.py" test -f "$PKG_DIR/swarm_vehicle/rota.py"
    check "ROS 2 setup.bash" test -f "$ROS_SETUP"
    check "gz.transport13 + gz.msgs10 (venv)" "$VENV_PY" -c 'from gz.transport13 import Node; from gz.msgs10.pose_v_pb2 import Pose_V'
    check "kosu.sh --dry-run baslat çıkış 0" "$KOSU" --dry-run baslat
}

print_plan() {
    log_info "[dry-run] statik: colcon build --base-paths src --packages-select swarm_vehicle (venv dışı); px4_adapter/rota rclpy olmadan içe aktarılır; git grep taraması"
    log_info "[dry-run] rota: rota_uret.py iki kez (bayt bayt aynı), doğrulayıcı, örnekle değerce aynılık, --check (+) ve bozuk kopyada (-)"
    log_info "[dry-run] tek: kosu.sh baslat --arac 1 → deneme kimlik (yanlış kimlik reddi, yüklenmemiş görev reddi) → deneme tam (araç 1 tam görev, Gazebo pozu kanıtı) → durdur"
    log_info "[dry-run] uc: kosu.sh baslat --arac 3 → deneme uc (3 bağdaştırıcı, 3 mavsdk_server, 3 rota yükle/indir/doğrula/başlat, ilk noktaya yaklaşma) → durdur"
    log_info "[dry-run] yetim: baslat → bağdaştırıcıyı barındıran sürece SIGKILL → yetim mavsdk_server → kosu.sh temizle kapatır"
    log_info "[dry-run] Sonda px4/gz/mavsdk_server/ruby, port, /dev/shm, ros2 daemon, tc/ip denetimi. Hiçbir süreç başlatılmadı, hiçbir şey derlenmedi"
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
    } > "$TMP_DIR/$n.proc"
    ss -lntuH 2>/dev/null | awk '{print $1, $5}' | LC_ALL=C sort > "$TMP_DIR/$n.ports" || true
    shm_list > "$TMP_DIR/$n.shm"
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$TMP_DIR/$n.net"
}

kalan_yok() { # kalan_yok <etiket> : başlangıca göre artık süreç / yeni port / yeni shm yok mu?
    local et="$1" ok=1 yeni
    sleep 1
    snapshot "k_$et"
    if ! diff -q "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" >/dev/null; then ok=0; log_fail "$et: artık süreç var: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" | tr '\n' ';' || true)"; fi
    yeni="$(LC_ALL=C comm -13 "$TMP_DIR/once.ports" "$TMP_DIR/k_$et.ports" | tr '\n' ';' || true)"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: yeni dinleyen port(lar): $yeni"; fi
    yeni="$(comm -13 "$TMP_DIR/once.shm" "$TMP_DIR/k_$et.shm" | tr '\n' ' ')"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: /dev/shm artığı: $yeni"; fi
    if [[ "$(pgrep -a -x ruby; pgrep -af '[g]z sim')" != "" ]]; then ok=0; log_fail "$et: gz sim süreci kaldı"; fi
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0 (gz/ruby/px4/mavsdk_server), yeni dinleyen port 0, /dev/shm artığı 0"; fi
    return 0
}

# --- Yardımcılar ----------------------------------------------------------------------
KOSU_DIR=""
kosu_baslat() { # kosu_baslat <ad> [kosu.sh argümanları...] : KOSU_DIR ayarlanır; başarısızlıkta 1
    local ad="$1" out id rc=0 l; shift
    out="$("$KOSU" baslat "$@" 2>&1)" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: baslat başarısız (çıkış $rc)"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; return 1
    fi
    id="$(cat "$KOK/aktif")"
    KOSU_DIR="$KOK/$id"
    log_ok "$ad: baslat tamam, koşu $id"
    return 0
}

komut_dene() { # komut_dene <günlük> <başarı_iletisi> <hata_iletisi> <komut...>
    local log="$1" ok="$2" hata="$3"; shift 3
    if "$@" > "$log" 2>&1; then log_ok "$ok"; else log_fail "$hata"; tail -n 8 "$log"; fi
}

json_gecerli() { # json_gecerli <ad> <beklenen_bitis_durumu>
    local ad="$1" bekl="$2" out bd l
    if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kosu.json" 2>&1)"; then
        log_ok "$ad: kosu.json doğrulayıcıdan geçti"
    else
        log_fail "$ad: kosu.json GEÇERSİZ"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"
    fi
    bd="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" bitis_durumu)"
    if [[ "$bd" == "$bekl" ]]; then log_ok "$ad: bitiş durumu '$bd'"; else log_fail "$ad: bitiş durumu '$bd' (beklenen '$bekl')"; fi
}

# deneme_calistir <ad> <mod> <zaman_asimi_sn> : Python sürücüsünü yaşayan koşuya karşı çalıştırır; SONUC satırlarını (+)/(-) yapar
deneme_calistir() {
    local ad="$1" mod="$2" tmo="$3" part rc=0 line t0=$SECONDS
    part="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" gz_partition)"
    GZ_PARTITION="$part" GZ_IP=127.0.0.1 timeout -k 5 "$tmo" "$VENV_PY" -I "$DENEME" "$mod" > "$TMP_DIR/$ad.$mod.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
        esac
    done < "$TMP_DIR/$ad.$mod.log"
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: $mod sürücüsü çıkış kodu $rc ($((SECONDS - t0)) sn)"
        tail -n 25 "$TMP_DIR/$ad.$mod.log" | while IFS= read -r line; do log_info "  | $line"; done
    else
        log_info "$ad: $mod sürücüsü $((SECONDS - t0)) sn (gerçek zaman)"
    fi
}

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

# --- Testler ----------------------------------------------------------------------------
test_statik() {
    local out rc=0 l mod kural
    log_info "== statik: derleme, içe aktarma, tek komut yolu taraması =="
    out="$GENERATED_DIR/swarm_vehicle_derleme.txt"
    mkdir -p "$GENERATED_DIR"
    (cd "$ROOT_DIR" && ros_run colcon build --base-paths src --packages-select swarm_vehicle) > "$out" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 && "$(tail -n 3 "$out")" == *"1 package finished"* ]]; then
        log_ok "statik: colcon build swarm_vehicle hatasız ($(grep -E 'Finished <<<' "$out" | sed 's/.*<<< //'))"
    else
        log_fail "statik: colcon build BAŞARISIZ (çıkış $rc); günlük: ${out#"$ROOT_DIR"/}"
        tail -n 12 "$out" | while IFS= read -r l; do log_info "  | $l"; done
    fi
    for mod in rota px4_adapter; do
        rc=0
        # shellcheck disable=SC2016  # tek tırnak bilerek: Python kodu
        "$VENV_PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import importlib; importlib.import_module("swarm_vehicle." + sys.argv[2]); assert "rclpy" not in sys.modules, "rclpy yüklendi"' \
            "$PKG_DIR" "$mod" > "$TMP_DIR/ice_$mod.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "statik: swarm_vehicle.$mod rclpy olmadan içe aktarıldı"; else log_fail "statik: swarm_vehicle.$mod içe aktarılamadı"; tail -n 5 "$TMP_DIR/ice_$mod.log"; fi
    done
    rc=0
    "$VENV_PY" -m py_compile "$PKG_DIR/swarm_vehicle/px4_adapter.py" "$PKG_DIR/swarm_vehicle/rota.py" "$ROTA_URET" "$DENEME" > "$TMP_DIR/pyc.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "statik: py_compile temiz"; else log_fail "statik: py_compile hata"; tail -n 5 "$TMP_DIR/pyc.log"; fi
    # tek komut yolu: MAVSDK yalnız px4_adapter.py; yazma çağrıları yalnız px4_adapter.py
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '^\s*(from|import) mavsdk' -- src || true)"
    if [[ -n "$out" && "$(awk -F: '{print $1}' <<< "$out" | sort -u)" == "src/swarm_vehicle/swarm_vehicle/px4_adapter.py" ]]; then
        log_ok "statik: src/ altında mavsdk'yı içe aktaran tek dosya px4_adapter.py"
    else
        log_fail "statik: mavsdk içe aktarımı beklenenden farklı: $out"
    fi
    kural='\.action\.|\.mission\b|\.mission_raw|\.param\.set'
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE "$kural" -- src ':!src/swarm_vehicle/swarm_vehicle/px4_adapter.py' || true)"
    if [[ -z "$out" ]]; then log_ok "statik: src/ altında px4_adapter.py dışında .action./.mission/.mission_raw/.param.set çağrısı yok"; else log_fail "statik: dış çağrı: $out"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE "set_param|set_rate_|\.offboard\.|\.manual_control|send_message" -- src ':!src/swarm_vehicle/swarm_vehicle/px4_adapter.py' || true)"
    if [[ -z "$out" ]]; then log_ok "statik: src/ altında px4_adapter.py dışında başka yazma çağrısı (param/hız/offboard/ham mesaj) yok"; else log_fail "statik: dış çağrı: $out"; fi
    # px4_adapter.py içindeki yazma çağrıları: yalnız _yaz üzerinden (_yaz çağrısı dışında islev geçirilmez)
    out="$(grep -nE "self\._sys\.(action|mission|param|offboard|mission_raw)\.[a-z_]+" "$PKG_DIR/swarm_vehicle/px4_adapter.py" | grep -vE '_yaz\(|get_param|download_mission|mission_progress' || true)"
    if [[ -z "$out" ]]; then log_ok "statik: px4_adapter.py içinde PX4'e yazan çağrılar yalnız _yaz(...) argümanı"; else log_fail "statik: _yaz dışı çağrı: $out"; fi
}

test_rota() {
    local a="$TMP_DIR/rota_a.json" b="$TMP_DIR/rota_b.json" bozuk="$TMP_DIR/rota_bozuk.json" out rc=0
    log_info "== rota: üretim, doğrulama, örnekle karşılaştırma, --check =="
    if out="$("$VENV_PY" -I "$ROTA_URET" --cikti "$a" 2>&1)"; then log_ok "rota: üretildi ve doğrulayıcı kabul etti"; else log_fail "rota: üretim/doğrulama başarısız: $out"; fi
    "$VENV_PY" -I "$ROTA_URET" --cikti "$b" > /dev/null 2>&1 || true
    if cmp -s "$a" "$b"; then log_ok "rota: iki üretim bayt bayt aynı ($(sha256sum "$a" | cut -c1-16)…)"; else log_fail "rota: iki üretim farklı"; fi
    if cmp -s "$a" "$ROTA_DOSYA"; then log_ok "rota: üretim config/bolge_rota.json ile bayt bayt aynı"; else log_fail "rota: config/bolge_rota.json üretilenden farklı"; fi
    if out="$(python3 -I "$DOGRULA" "$ROTA_DOSYA" 2>&1)"; then log_ok "rota: config/bolge_rota.json sozlesme_dogrula.py'den geçti"; else log_fail "rota: config/bolge_rota.json reddedildi: $out"; fi
    # örnekle değerce aynı (JSON nesne eşitliği)
    if python3 -I -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])) == json.load(open(sys.argv[2])) else 1)' "$ROTA_DOSYA" "$ORNEK_ROTA"; then
        log_ok "rota: config/bolge_rota.json, config/ornek/bolge_rota_ornek.json ile değerce aynı"
    else
        log_fail "rota: örnekle değerce FARKLI"
    fi
    if out="$("$VENV_PY" -I "$ROTA_URET" --check 2>&1)"; then log_ok "rota: --check güncel dosyada: $out"; else log_fail "rota: --check güncel dosyada başarısız: $out"; fi
    sed 's/-130\.89/-130.0/' "$ROTA_DOSYA" > "$bozuk"
    out="$("$VENV_PY" -I "$ROTA_URET" --check --cikti "$bozuk" 2>&1)" || rc=$?
    if [[ "$rc" -eq 1 && "$out" == "(-)"* ]]; then log_ok "rota: --check elle bozulmuş kopyada (-) ve çıkış 1: $out"; else log_fail "rota: --check bozuk kopyayı yakalamadı (çıkış $rc): $out"; fi
    # deney.env'deki değer değişince dosya güncel değil sayılır (yapılandırma kopyası; kilitli dosyaya dokunulmaz)
    sed 's/^ROTA_ORTUSME_MIN_M=.*/ROTA_ORTUSME_MIN_M="3"/' "$DENEY_ENV" > "$TMP_DIR/deney_degisik.env"
    rc=0
    out="$("$VENV_PY" -I "$ROTA_URET" --check --env "$TMP_DIR/deney_degisik.env" 2>&1)" || rc=$?
    if [[ "$rc" -eq 1 ]]; then log_ok "rota: yapılandırma (kopya) değişince --check (-) verdi"; else log_info "rota: ROTA_ORTUSME_MIN_M=3 aynı rotayı üretti (çıkış $rc); örtüşme payı yeterli, yalnız bilgi"; fi
}

test_tek() {
    local ad=tek out
    log_info "== tek: tek araç koşusu (kimlik koruması + tam görev) =="
    if kosu_baslat "$ad" --arac 1; then
        deneme_calistir "$ad" kimlik 120
        deneme_calistir "$ad" tam 900
        out="$KOSU_DIR/px4_adapter_${SYS_IDS[0]}.log"
        if [[ -f "$out" ]]; then
            log_ok "$ad: bağdaştırıcı günlüğü koşu klasöründe: ${out#"$ROOT_DIR"/} ($(wc -l < "$out") satır)"
            log_info "$ad: günlükteki olay türleri: $(awk '{print $3}' "$out" | LC_ALL=C sort | uniq -c | awk '{printf "%s×%s ", $2, $1}')"
            if grep -q ' yukleme ' "$out" && grep -q ' baslatma ' "$out" && grep -q ' son_nokta ' "$out"; then log_ok "$ad: günlükte yükleme, başlatma ve son_nokta olayları var"; else log_fail "$ad: günlükte yükleme/başlatma/son_nokta olayı eksik"; fi
        else
            log_fail "$ad: bağdaştırıcı günlüğü yok: ${out#"$ROOT_DIR"/}"
        fi
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
    fi
    kalan_yok "$ad"
}

test_uc() {
    local ad=uc
    [[ "${#SYS_IDS[@]}" -ge 3 ]] || { log_fail "uc: yapılandırmada 3 araç yok"; return; }
    log_info "== uc: üç araç =="
    if kosu_baslat "$ad" --arac 3; then
        deneme_calistir "$ad" uc 600
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
    fi
    kalan_yok "$ad"
}

test_yetim() {
    local ad=yetim part spid i hazir=0 rc=0 out
    log_info "== yetim: bağdaştırıcıyı barındıran sürece SIGKILL, kosu.sh temizle =="
    if kosu_baslat "$ad" --arac 1; then
        part="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" gz_partition)"
        GZ_PARTITION="$part" GZ_IP=127.0.0.1 "$VENV_PY" -I "$DENEME" yetim > "$TMP_DIR/yetim.log" 2>&1 &
        YETIM_PY_PID=$!
        for ((i = 0; i < 300; i++)); do
            if grep -q '^HAZIR ' "$TMP_DIR/yetim.log" 2>/dev/null; then hazir=1; break; fi
            sleep 0.2
        done
        if [[ "$hazir" -ne 1 ]]; then
            log_fail "$ad: bağdaştırıcı 60 sn içinde hazır olmadı"; tail -n 8 "$TMP_DIR/yetim.log"
        else
            spid="$(sed -n 's/^HAZIR \([0-9]*\)$/\1/p' "$TMP_DIR/yetim.log" | head -n 1)"
            log_info "$ad: bağdaştırıcı barındıran süreç pid $YETIM_PY_PID, mavsdk_server pid $spid (gRPC ${GRPC_PORTS[0]}); SIGKILL gönderiliyor"
            kill -KILL "$YETIM_PY_PID" 2>/dev/null || true
            wait "$YETIM_PY_PID" 2>/dev/null || true
            YETIM_PY_PID=""
            sleep 2
            if [[ -d "/proc/$spid" && "$(cat "/proc/$spid/comm" 2>/dev/null || true)" == mavsdk_server ]]; then
                log_ok "$ad: sunucu sahipsiz kaldı: mavsdk_server pid $spid yaşıyor (yetim), dinleyen: $(ss -H -l -n -t -p 2>/dev/null | awk -v p="pid=$spid," 'index($0, p) {print $4}' | tr '\n' ' ')"
            else
                log_fail "$ad: mavsdk_server kendiliğinden kapanmış (pid $spid); yetim durumu oluşmadı, temizle denemesi anlamsız"
            fi
            "$KOSU" temizle > "$TMP_DIR/yetim_temizle.log" 2>&1 || rc=$?
            if [[ "$rc" -eq 0 ]]; then log_ok "$ad: kosu.sh temizle tamam"; else log_fail "$ad: kosu.sh temizle başarısız (çıkış $rc)"; tail -n 10 "$TMP_DIR/yetim_temizle.log"; fi
            out="$(grep -E 'mavsdk_server' "$TMP_DIR/yetim_temizle.log" | sed 's/^[^ ]* //' | tr '\n' ';' || true)"
            log_info "$ad: temizle çıktısı (mavsdk_server): $out"
            if [[ -d "/proc/$spid" ]]; then log_fail "$ad: temizle sonrası mavsdk_server pid $spid hâlâ yaşıyor"; else log_ok "$ad: temizle sonrası mavsdk_server pid $spid yok"; fi
            json_gecerli "$ad" yarida_kaldi
            out="$(python3 -I "$HELPER" surecler "$KOSU_DIR/kosu.json" | awk '$1 ~ /^mavsdk_server_/ {print $1 "(pid " $2 ")"}' | tr '\n' ' ')"
            if [[ "$out" == *"mavsdk_server_${GRPC_PORTS[0]}(pid $spid)"* ]]; then log_ok "$ad: kosu.json süreç listesine yazıldı: $out"; else log_fail "$ad: kosu.json süreç listesinde yetim sunucu yok: '$out'"; fi
        fi
    fi
    kalan_yok "$ad"
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server)" ]]; then fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server süreci yaşıyor; önce kapatın"; fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), PX4 $PX4_TAG, mavsdk $MAVSDK_VERSION; testler: ${TESTS[*]}"

if want statik; then test_statik; fi
if want rota; then test_rota; fi
if want tek; then test_tek; fi
if want uc; then test_uc; fi
if want yetim; then test_yetim; fi

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
