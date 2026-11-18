#!/usr/bin/env bash
# alan_pilot_testi.sh — alan ve rota mini pilotu: üç araç tam rotayı uçar; süre, uzunluk, RTF, yönelim, kapsama, bölge taşması ölçülür (başsız Gazebo + PX4 SITL
# + ROS 2 araç süreçleri + asıl yer istasyonu koordinatörü, hepsi araclar/kosu.sh ile + salt okuma gözlemci).
# Kullanım: ./alan_pilot_testi.sh [--dry-run | --verify | -h]
#   (argümansız)  tek ölçüm koşusu: kosu.sh baslat --arac 3 --yer-istasyonu var → asıl koordinatör + üç araç süreci (çıkarım işçisi açık, enjeksiyon kapalı) + gözlemci
#                 (araclar/olcum/alan_pilot_olcum.py: Gazebo model pozları ve PX4 yönelim/konum/hız telemetrisi, salt okuma) → araclar/analiz/alan_pilot_analiz.py
#                 → kosu.sh bekle → kosu.sh durdur. Çözümleme tabloları koşu klasöründe `alan_pilot_ozet.md` dosyasına da yazılır; ayrıca aday alan tablosu
#                 (araclar/analiz/alan_aday_tablo.py, simülasyonsuz) yazdırılır.
#   --dry-run     hiçbir süreç başlatmaz, hiçbir şey yazmaz; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, numpy); süreç başlatmaz
# Bu bir ölçümdür, sınama değil: yönelim ve kapsama sayıları eşiğe bağlanmaz; geçti/kaldı yalnız kare sonucu bütünlüğü, görev sınırı ve süreç artığı için verilir.
# Ölçüm disiplini: Gazebo görsel istemcisi (gz sim -g) açıkken ölçüm yapılmaz (GPU/CPU yükü ekler). Araç süreçleri, koordinatör ve gözlemci `setsid` ile ayrı süreç
# gruplarında başlatılır; her çıkışta (hata, Ctrl-C dahil) bu betik kendisi toplar. Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ. sudo gerekmez.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

parse_common_args "$@"
COMPONENT_NAME="Alan ve rota pilotu"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
KOORD="$ROOT_DIR/araclar/deneme/koordinator_deneme.py"
OLCUM="$ROOT_DIR/araclar/olcum/alan_pilot_olcum.py"
ANALIZ="$ROOT_DIR/araclar/analiz/alan_pilot_analiz.py"
ADAY="$ROOT_DIR/araclar/analiz/alan_aday_tablo.py"
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
    [[ "$DRY_RUN" -eq 0 && "$MODE" != verify ]] || return 0   # --dry-run/--verify hiçbir süreç başlatmaz; yaşayan (başkasına ait) koşuya DOKUNMAZ
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
for v in SIM_WORLD UAV_SYS_IDS UAV_NAMESPACES UAV1_ADDR UAV2_ADDR UAV3_ADDR GCS_ADDR MAVSDK_GRPC_PORTS KOSU_KAPANIS_SN; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
read -r -a GRPC_PORTS <<< "$MAVSDK_GRPC_PORTS"
N_ARAC=3

check_prereqs() {
    local c f
    for c in gz ss pgrep python3 awk colcon tc; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "setup/env.sh" test -f "$ENV_SH"
    check "ROS 2 setup.bash" test -f "$ROS_SETUP"
    check "Kurulu araç paketleri (install/setup.bash; colcon build)" test -f "$ROOT_DIR/install/setup.bash"
    for f in "$KOSU" "$KOORD" "$OLCUM" "$ANALIZ" "$ADAY"; do
        check "Dosya: ${f#"$ROOT_DIR"/}" test -f "$f"
    done
    check "numpy (venv)" "$VENV_PY" -I -c 'import numpy'
    # shellcheck disable=SC2016  # tek tırnak bilerek: alt kabukta açılır
    check "Yapılandırılmış sürü ağı (lo üzerinde htb)" bash -c '[[ "$(tc qdisc show dev lo)" == *htb* ]]'
    check "kosu.sh --dry-run baslat çıkış 0" "$KOSU" --dry-run baslat
    check "Aday alan tablosu (simülasyonsuz) hesaplanıyor" python3 -I "$ADAY"
}

print_plan() {
    log_info "[dry-run] kosu.sh baslat --arac $N_ARAC --yer-istasyonu var (asıl yer istasyonu koordinatörü + üç araç süreci: SWARM_BIND_ADDR=$UAV1_ADDR $UAV2_ADDR $UAV3_ADDR)"
    log_info "[dry-run] gRPC portları ($MAVSDK_GRPC_PORTS) dinlemeye geçince gözlemci: python araclar/olcum/alan_pilot_olcum.py --arac $N_ARAC (Gazebo model pozları + PX4 telemetri, salt okuma)"
    log_info "[dry-run] kosu.sh bekle (koordinatör ve araçlar biter); gözlemci SIGTERM ile kapatılır; araclar/analiz/alan_pilot_analiz.py <koşu> --arac $N_ARAC; kosu.sh durdur; araclar/analiz/alan_aday_tablo.py"
    log_info "[dry-run] Her koşu sonunda araç süreci/koordinatör/gözlemci/px4/gz/mavsdk_server artığı, yeni dinleyen port, /dev/shm; sonda ros2 daemon, tc/ip denetimi. Hiçbir süreç başlatılmadı"
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
        echo "proc olcum $(pgrep -f -c 'alan_pilot_olcum[.]py' || true)"
        echo "proc isci $(pgrep -f -c 'swarm_vehicle[.]cikarim_isci' || true)"
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
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0 (gz/ruby/px4/mavsdk_server/araç süreci/işçi/koordinatör/gözlemci), yeni dinleyen port 0, /dev/shm artığı 0"; fi
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
    log_info "$ad: GZ_PARTITION=$PART (görsel önizleme için: GZ_PARTITION=$PART GZ_IP=127.0.0.1 gz sim -g; önizleme açıkken yapılan koşu ölçüm sayılmaz)"
    return 0
}

komut_dene() {
    local log="$1" ok="$2" hata="$3"; shift 3
    if "$@" > "$log" 2>&1; then log_ok "$ok"; else log_fail "$hata"; tail -n 8 "$log"; fi
}

# ros_baslat <çıktı_dosyası> <komut...> : setsid ile ayrı süreç grubunda, ROS + venv ortamında; LAST_PG = grup lideri
LAST_PG=""
ros_baslat() {
    local cikti="$1"; shift
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    setsid env -u VIRTUAL_ENV GZ_PARTITION="$PART" GZ_IP=127.0.0.1 LC_NUMERIC=C bash -c 'source "$1" >/dev/null 2>&1; source "$2/install/setup.bash"; shift 2; exec "$@"' _ "$ENV_SH" "$ROOT_DIR" "$@" \
        > "$cikti" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
}

portlar_dinliyor() { # tüm gRPC portları dinlemede mi
    local p out
    out="$(ss -lntH 2>/dev/null || true)"
    for p in "${GRPC_PORTS[@]:0:$N_ARAC}"; do [[ "$out" == *":$p "* ]] || return 1; done
    return 0
}

olcum_kosusu() {
    local ad=olcum i opg rc=0 t0=$SECONDS out line
    log_info "== $ad: üç araç tam rota (çıkarım işçisi açık, enjeksiyon kapalı; kosu.sh baslat --yer-istasyonu var → bekle → durdur) =="
    kosu_baslat "$ad" --arac "$N_ARAC" --yer-istasyonu var || return 0
    log_info "$ad: asıl yer istasyonu koordinatörü ve $N_ARAC araç süreci kosu.sh ile başlatıldı"
    # gözlemci: araçların mavsdk_server'ları dinlemeye geçince (bağdaştırıcı bağlanınca; hazırlık evresi sürerken)
    for ((i = 0; i < 1200; i++)); do
        portlar_dinliyor && break
        [[ ! -f "$KOSU_DIR/yer_istasyonu.cikis" ]] || break
        sleep 0.25
    done
    if portlar_dinliyor; then
        ros_baslat "$KOSU_DIR/olcum.out" python "$OLCUM" --arac "$N_ARAC"
        opg="$LAST_PG"
        for ((i = 0; i < 400; i++)); do
            if grep -q '^OLCUM baglandi' "$KOSU_DIR/olcum.out" 2>/dev/null; then break; fi
            kill -0 "$opg" 2>/dev/null || break
            sleep 0.25
        done
        if grep -q '^OLCUM baglandi' "$KOSU_DIR/olcum.out" 2>/dev/null; then
            log_ok "$ad: gözlemci bağlandı (Gazebo pozları + PX4 telemetrisi, salt okuma): $(sed -n 1p "$KOSU_DIR/olcum.out")"
        else
            log_fail "$ad: gözlemci bağlanamadı"; tail -n 8 "$KOSU_DIR/olcum.out"
        fi
    else
        opg=""
        log_fail "$ad: mavsdk_server portları dinlemeye geçmedi; gözlemci başlatılamadı"
    fi
    "$KOSU" bekle --sure-sn 900 > "$TMP_DIR/bekle.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "$ad: yer istasyonu çıkış 0, araç süreçleri kapandı ($((SECONDS - t0)) sn gerçek)"; else log_fail "$ad: kosu.sh bekle çıkış kodu $rc"; tail -n 6 "$TMP_DIR/bekle.log"; fi
    if [[ -n "${opg:-}" ]]; then grup_oldur "$opg"; log_info "$ad: gözlemci kapatıldı: $(tail -n 1 "$KOSU_DIR/olcum.out")"; fi
    PGIDS=()
    # çözümleme
    rc=0
    out="$KOSU_DIR/alan_pilot_ozet.md"
    "$VENV_PY" -I "$ANALIZ" "$KOSU_DIR" --arac "$N_ARAC" --cikti "$out" > "$TMP_DIR/analiz.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            Traceback*|*Error*) log_fail "$ad: analiz hatası: $line" ;;
        esac
    done < "$TMP_DIR/analiz.log"
    if [[ "$rc" -ne 0 && "$rc" -ne 1 ]]; then log_fail "$ad: analiz çıkış kodu $rc"; tail -n 12 "$TMP_DIR/analiz.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
    if [[ -f "$out" ]]; then log_ok "$ad: ölçüm tabloları yazıldı: ${out#"$ROOT_DIR"/}"; fi
    komut_dene "$TMP_DIR/durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
    kalan_yok "$ad"
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server; pgrep -af 'swarm_vehicle[.]arac|koordinator_deneme[.]py|alan_pilot_olcum[.]py|swarm_vehicle[.]cikarim_isci')" ]]; then
    fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server/araç süreci/işçi/koordinatör/gözlemci yaşıyor; önce kapatın (görsel istemci 'gz sim -g' açıksa kapatın: ölçüm sayılmaz)"
fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), ROS $ROS_DISTRO, PX4 $PX4_TAG"

olcum_kosusu

log_info "== aday alan tablosu (simülasyonsuz; config/ değişmedi) =="
python3 -I "$ADAY" | while IFS= read -r l; do log_info "  $l"; done || true

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

component_finish "$COMPONENT_NAME" "tamamlandı (ölçüm koşusu, çözümleme, süreç/port/shm/tc denetimi)"
