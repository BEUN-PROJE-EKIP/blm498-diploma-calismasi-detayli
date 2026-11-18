#!/usr/bin/env bash
# arac_sureci_testi.sh — araç süreci ve görev durum makinesi kabul testleri (başsız Gazebo + PX4 SITL + ROS 2 araç süreçleri + deneme koordinatörü).
# Kullanım: ./arac_sureci_testi.sh [--dry-run | --verify | -h] [birim] [tek] [uc] [erken]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz, hiçbir şey derlemez; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, kurulu paketler); süreç başlatmaz
# Testler:
#   birim   durum makinesi birim testleri (ROS'suz), colcon build (swarm_msgs, swarm_vehicle), rclpy/mavsdk'sız içe aktarma, tek komut yolu taraması
#   tek     --arac 1: araç süreci + deneme koordinatörü (erken tarama başlatma, erken COMPLETE, yanlış kimlikli COMPLETE senaryolarıyla); durum dizisi,
#           t0 ilişkileri, Gazebo pozu, kare aralığı, 2 Hz yayım
#   erken   --arac 3, araç 2'nin gRPC portu önceden tutulur (araç süreci kurulumda çıkar): koşu açık hatayla sonlanır, bütün süreç grupları toplanır, artık süreç yok
#   uc      --arac 3: üç araç süreci (üç ad alanı, kendi sürü adresleri) + koordinatör; diğer araçların durum kayıtları, hazırlıkta çarpışma yok,
#           DDS trafiği sürü ağından (tc sayacı artar, soketler 10.10.0.x)
# Araç süreçleri ve koordinatör `setsid` ile ayrı süreç gruplarında, günlükleri koşu klasöründe başlatılır; her çıkışta (hata, Ctrl-C dahil) bu betik
# kendisi toplar (kosu.sh temizle yalnız kosu.json'daki süreçleri bilir). Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ. sudo gerekmez.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/derleme.sh
source "$SETUP_DIR/lib/derleme.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        birim|tek|uc|erken) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(birim tek uc erken)
COMPONENT_NAME="Araç süreci ve görev durum makinesi"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
KOORD="$ROOT_DIR/araclar/koordinator_deneme.py"
ANALIZ="$ROOT_DIR/araclar/arac_sureci_analiz.py"
BIRIM_TEST="$ROOT_DIR/src/swarm_vehicle/test/test_durum_makinesi.py"
BIRIM_TEST_KAPANIS="$ROOT_DIR/src/swarm_vehicle/test/test_arac_kapanis.py"
BIRIM_TEST_PORT="$ROOT_DIR/src/swarm_vehicle/test/test_port_denetimi.py"
PKG_DIR="$ROOT_DIR/src/swarm_vehicle"
VENV_PY="$ROOT_DIR/.venv/bin/python"
ENV_SH="$SETUP_DIR/env.sh"
DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
ROS_SETUP="/opt/ros/$ROS_DISTRO/setup.bash"
KOK="$GENERATED_DIR/kosular"
TMP_DIR=""
PGIDS=()
ERKEN_BEKLENEN=0   # 1: bir aracın t0'dan önce çıkması beklenen (erken alt kümesi)
ERKEN_SONUC=0      # t0'dan önce çıkan araç numarası (0: yok)
ERKEN_DIGER_CANLI=""   # erken çıkış anında yaşayan diğer araçlar (numaralar; boşsa hiçbiri)
TUTUCU_PID=""      # erken alt kümesinin gRPC portunu tutan yardımcı süreç (PID ile kapatılır)

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
    if [[ -n "$TUTUCU_PID" ]]; then kill "$TUTUCU_PID" 2>/dev/null || true; TUTUCU_PID=""; fi
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
UAV_ADDRS=("$UAV1_ADDR" "$UAV2_ADDR" "$UAV3_ADDR")

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
    for f in "$KOSU" "$KOORD" "$ANALIZ" "$BIRIM_TEST" "$BIRIM_TEST_KAPANIS" "$BIRIM_TEST_PORT" "$PKG_DIR/swarm_vehicle/arac.py" "$PKG_DIR/swarm_vehicle/ucus/durum_makinesi.py" "$PKG_DIR/swarm_vehicle/ucus/px4_adapter.py"; do
        check "Dosya: ${f#"$ROOT_DIR"/}" test -f "$f"
    done
    check "Yapılandırılmış sürü ağı (lo üzerinde htb)" bash -c '[[ "$(tc qdisc show dev lo)" == *htb* ]]'
    check "kosu.sh --dry-run baslat çıkış 0" "$KOSU" --dry-run baslat
}

print_plan() {
    log_info "[dry-run] birim: durum makinesi birim testleri (ROS'suz); colcon build --base-paths src --packages-select swarm_msgs swarm_vehicle (venv dışı); rclpy/mavsdk'sız içe aktarma; tek komut yolu taraması"
    log_info "[dry-run] tek: kosu.sh baslat --arac 1 → koordinatör (--erken-scan-start --erken-complete --yanlis-complete) + araç süreci 1 (python -m swarm_vehicle.arac 1, SWARM_BIND_ADDR=$UAV1_ADDR) → analiz → durdur"
    log_info "[dry-run] uc: kosu.sh baslat --arac 3 → koordinatör + üç araç süreci (SWARM_BIND_ADDR=${UAV_ADDRS[*]}) → tc sayacı ve soket denetimi → analiz → durdur"
    log_info "[dry-run] erken: kosu.sh baslat --arac 3 → araç 2'nin gRPC portunu tutan yardımcı süreç → koordinatör + üç araç; araç 2 kurulumda çıkar → koşu sonlandırılır, süreç grupları toplanır → temizle (bitiş durumu yarida_kaldi) → artık süreç denetimi"
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
    setsid env GZ_PARTITION="$PART" GZ_IP=127.0.0.1 LC_NUMERIC=C bash -c 'source "$1" >/dev/null 2>&1; source "$2/install/setup.bash"; shift 2; exec "$@"' _ "$ENV_SH" "$ROOT_DIR" "$@" \
        > "$cikti" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
}

tc_bayt() { # sürü sınıfı (1:10) için gönderilen bayt sayısı
    tc -s class show dev lo 2>/dev/null | awk '/^class htb 1:10 / {f=1} f && /Sent/ {print $2; exit}'
}

# senaryo_calistir <ad> <araç_sayısı> <koordinatör_argümanları...> : araç süreçleri + koordinatör; koordinatör çıkışı beklenir
senaryo_calistir() {
    local ad="$1" n="$2" i j l pg erken=0 kpg kmax rc=0 t0=$SECONDS tc0 tc1 soket_yok=1; shift 2
    local -a apg=() apid=()
    tc0="$(tc_bayt)"
    ros_baslat "$KOSU_DIR/koordinator.out" timeout -k 5 1200 python "$KOORD" --arac "$n" --zaman-asimi-sn 1100 "$@"
    kpg="$LAST_PG"
    sleep 4
    for ((i = 1; i <= n; i++)); do
        ros_baslat "$KOSU_DIR/arac_$i.out" python -m swarm_vehicle.arac "$i"
        apg+=("$LAST_PG"); apid+=("$LAST_PG")
    done
    log_info "$ad: koordinatör pid $kpg, araç süreçleri pid ${apid[*]}"
    # t0 yayımlanınca araç süreçlerinin soketlerini denetle (DDS soketleri yalnız kendi sürü adreslerinde)
    for ((i = 0; i < 4000; i++)); do
        if grep -q '^KOORDINATOR t0' "$KOSU_DIR/koordinator.out" 2>/dev/null; then break; fi
        kill -0 "$kpg" 2>/dev/null || break
        for ((j = 0; j < n; j++)); do
            if ! kill -0 "${apid[$j]}" 2>/dev/null; then erken=$((j + 1)); break; fi
        done
        [[ "$erken" -eq 0 ]] || break
        sleep 0.25
    done
    if [[ "$erken" -gt 0 ]]; then
        # Bir araç t0'dan önce çıktı: diğerleri bariyerde sonsuza dek beklerdi; koşu açık hatayla sonlandırılır, bütün gruplar toplanır
        local arc=0; wait "${apid[$((erken - 1))]}" 2>/dev/null || arc=$?
        if [[ "$ERKEN_BEKLENEN" -eq 1 ]]; then
            log_ok "$ad: araç $erken süreci t0'dan önce çıktı (çıkış kodu $arc; beklenen): koşu sonlandırılıyor"
        else
            log_fail "$ad: araç $erken süreci t0'dan önce çıktı (çıkış kodu $arc): koşu sonlandırılıyor"
        fi
        tail -n 6 "$KOSU_DIR/arac_$erken.out" | while IFS= read -r l; do log_info "  | $l"; done
        ERKEN_DIGER_CANLI=""
        for ((j = 0; j < n; j++)); do
            if [[ "$((j + 1))" -ne "$erken" ]] && kill -0 "${apid[$j]}" 2>/dev/null; then ERKEN_DIGER_CANLI+="$((j + 1)) "; fi
        done
        for pg in "${apg[@]}" "$kpg"; do grup_oldur "$pg"; done
        ERKEN_SONUC=$erken
        PGIDS=()
        return 0
    fi
    local dom="${ROS_DOMAIN_ID:-42}" taban
    taban=$((7400 + 250 * dom))
    for ((i = 1; i <= n; i++)); do
        local pid="${apid[$((i - 1))]}" soketler adres="${UAV_ADDRS[$((i - 1))]}" yanlis
        soketler="$(ss -H -u -a -n -p 2>/dev/null | awk -v p="pid=$pid," 'index($0, p) {print $4}' | sort -u | tr '\n' ' ')"
        # DDS port aralığı: taban .. taban+249; bu aralıktaki her soket sürü ağı (10.10.0.x) adreslerinde olmalı (profilin beyaz listesi dört sürü adresidir);
        # kendi adresi (ilan edilen konum) bulunmalı; 127.0.0.1 ya da 0.0.0.0 üzerinde DDS soketi olmamalı
        yanlis="$(tr ' ' '\n' <<< "$soketler" | awk -F: -v t="$taban" 'NF == 2 && $2 >= t && $2 < t + 250 && $1 !~ /^10\.10\.0\./ {print $0}' | tr '\n' ' ')"
        if [[ "$soketler" == *"$adres:"* && -z "$yanlis" ]]; then
            log_ok "$ad: araç $i DDS soketleri yalnız sürü ağı adreslerinde (kendi adresi $adres dahil): $soketler"
        else
            soket_yok=0; log_fail "$ad: araç $i DDS soketi sürü ağında değil ya da kendi adresi ($adres) yok; soketler: $soketler; yanlış: $yanlis"
        fi
    done
    : "$soket_yok"
    # koordinatörün bitmesini bekle
    wait "$kpg" 2>/dev/null || rc=$?
    for ((i = 0; i < n; i++)); do
        local arc=0
        # araç süreçleri kendi kapanır (TAMAMLANDI + ARAC_KAPANIS_BEKLE_SN); en çok 30 sn bekle
        for ((kmax = 0; kmax < 300; kmax++)); do kill -0 "${apid[$i]}" 2>/dev/null || break; sleep 0.1; done
        if kill -0 "${apid[$i]}" 2>/dev/null; then log_fail "$ad: araç $((i + 1)) süreci TAMAMLANDI'dan sonra 30 sn içinde kapanmadı"; else wait "${apid[$i]}" 2>/dev/null || arc=$?; fi
        if [[ "$arc" -eq 0 ]]; then log_ok "$ad: araç $((i + 1)) süreci kendiliğinden kapandı (çıkış 0)"; else log_fail "$ad: araç $((i + 1)) süreci çıkış kodu $arc"; tail -n 6 "$KOSU_DIR/arac_$((i + 1)).out"; fi
    done
    if [[ "$rc" -eq 0 ]]; then log_ok "$ad: koordinatör çıkış 0 ($((SECONDS - t0)) sn gerçek)"; else log_fail "$ad: koordinatör çıkış kodu $rc"; tail -n 8 "$KOSU_DIR/koordinator.out"; fi
    tc1="$(tc_bayt)"
    if [[ -n "$tc0" && -n "$tc1" && "$tc1" -gt "$tc0" ]]; then
        log_ok "$ad: sürü sınıfı (tc htb 1:10) sayacı arttı: $tc0 → $tc1 bayt (+$((tc1 - tc0))): ROS 2 trafiği ölçülen ağdan geçti"
    else
        log_fail "$ad: tc sayacı artmadı ($tc0 → $tc1)"
    fi
    # Hâlâ canlı grup varsa (araç kapanmadı, koordinatör zaman aşımı) bırakılmaz: hata yazılır ve grup toplanır
    for pg in "${apg[@]}" "$kpg"; do
        if kill -0 -- "-$pg" 2>/dev/null; then log_fail "$ad: süreç grubu $pg hâlâ canlı; sonlandırılıyor"; grup_oldur "$pg"; fi
    done
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

kayit_dosyalari_gecerli() { # kayit_dosyalari_gecerli <ad> <n>
    local ad="$1" n="$2" i out
    for ((i = 1; i <= n; i++)); do
        if [[ "$n" -eq 1 ]]; then log_info "$ad: araç 1: diğer araç yok; durum kayıt dosyası boş/yok olabilir"; continue; fi
        if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kayit/arac_durum_${SYS_IDS[$((i - 1))]}.jsonl" 2>&1)"; then
            log_ok "$ad: gerçek kayıt dosyası doğrulayıcıdan geçti: arac_durum_${SYS_IDS[$((i - 1))]}.jsonl ($(tail -n 1 <<< "$out" | sed 's/, .*jsonl)/)/'))"
        else
            log_fail "$ad: kayıt dosyası GEÇERSİZ: arac_durum_${SYS_IDS[$((i - 1))]}.jsonl: $(head -n 3 <<< "$out" | tr '\n' ';')"
        fi
    done
}

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

# --- Testler ----------------------------------------------------------------------------
test_birim() {
    local out rc=0 l mod
    log_info "== birim: durum makinesi birim testleri, derleme, içe aktarma, tek komut yolu =="
    if out="$("$VENV_PY" -I "$BIRIM_TEST" 2>&1)"; then log_ok "birim: durum makinesi birim testleri geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: durum makinesi birim testleri BAŞARISIZ"; tail -n 15 <<< "$out"; fi
    if out="$("$VENV_PY" -I "$BIRIM_TEST_KAPANIS" 2>&1)"; then log_ok "birim: araç kapanış yolu birim testleri geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: araç kapanış yolu birim testleri BAŞARISIZ"; tail -n 15 <<< "$out"; fi
    if out="$("$VENV_PY" -I "$BIRIM_TEST_PORT" 2>&1)"; then log_ok "birim: sabit port / geçici port aralığı denetimi birim testleri geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: port aralığı denetimi birim testleri BAŞARISIZ"; tail -n 15 <<< "$out"; fi
    out="$GENERATED_DIR/arac_sureci_derleme.txt"
    if proje_derle "$out"; then
        log_ok "birim: proje derlendi (swarm_msgs + swarm_vehicle + swarm_gcs; ortak yol: setup/lib/derleme.sh)"
    else
        log_fail "birim: proje derlemesi BAŞARISIZ; günlük: ${out#"$ROOT_DIR"/}"
        tail -n 12 "$out" | while IFS= read -r l; do log_info "  | $l"; done
    fi
    for mod in durum_makinesi rota; do
        rc=0
        # shellcheck disable=SC2016  # tek tırnak bilerek: Python kodu
        "$VENV_PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import importlib; importlib.import_module("swarm_vehicle." + sys.argv[2]); assert "rclpy" not in sys.modules and "mavsdk" not in sys.modules' \
            "$PKG_DIR" "$mod" > "$TMP_DIR/ice_$mod.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "birim: swarm_vehicle.$mod rclpy ve mavsdk olmadan içe aktarıldı"; else log_fail "birim: swarm_vehicle.$mod içe aktarma hatası"; tail -n 5 "$TMP_DIR/ice_$mod.log"; fi
    done
    rc=0
    "$VENV_PY" -m py_compile "$PKG_DIR/swarm_vehicle/arac.py" "$PKG_DIR/swarm_vehicle/ucus/durum_makinesi.py" "$PKG_DIR/swarm_vehicle/ucus/px4_adapter.py" "$KOORD" "$ANALIZ" > "$TMP_DIR/pyc.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: py_compile temiz"; else log_fail "birim: py_compile hata"; tail -n 5 "$TMP_DIR/pyc.log"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '^\s*(from|import) mavsdk' -- src || true)"
    if [[ -n "$out" && "$(awk -F: '{print $1}' <<< "$out" | sort -u)" == "src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py" ]]; then log_ok "birim: src/ altında mavsdk'yı içe aktaran tek dosya px4_adapter.py"; else log_fail "birim: mavsdk içe aktarımı beklenenden farklı: $out"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '\.action\.|\.mission\b|\.mission_raw|\.param\.set|set_param|set_rate_|\.offboard\.|send_message' -- src ':!src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: src/ altında px4_adapter.py dışında PX4'e yazan çağrı yok"; else log_fail "birim: dış çağrı: $out"; fi
}

test_tek() {
    local ad=tek
    log_info "== tek: araç 1 + koordinatör (erken ScanStart, erken COMPLETE, yanlış COMPLETE) =="
    if kosu_baslat "$ad" --arac 1; then
        senaryo_calistir "$ad" 1 --erken-scan-start --erken-complete --yanlis-complete --yanlis-bekle-sn 6
        analiz "$ad" --arac 1 --erken-scan-start --erken-complete --yanlis-complete
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
    fi
    kalan_yok "$ad"
}

test_uc() {
    local ad=uc
    [[ "${#SYS_IDS[@]}" -ge 3 ]] || { log_fail "uc: yapılandırmada 3 araç yok"; return; }
    log_info "== uc: üç araç süreci + koordinatör =="
    if kosu_baslat "$ad" --arac 3; then
        senaryo_calistir "$ad" 3
        analiz "$ad" --arac 3
        kayit_dosyalari_gecerli "$ad" 3
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
    fi
    kalan_yok "$ad"
}

test_erken() {
    local ad=erken port
    [[ "${#SYS_IDS[@]}" -ge 3 ]] || { log_fail "erken: yapılandırmada 3 araç yok"; return; }
    read -r -a GRPC_PORTS <<< "$MAVSDK_GRPC_PORTS"
    port="${GRPC_PORTS[1]}"
    log_info "== erken: araç 2'nin gRPC portu ($port) önceden tutulur; araç süreci kurulumda çıkar, koşu açık hatayla sonlanır =="
    if kosu_baslat "$ad" --arac 3; then
        python3 -I -c 'import socket, sys, time; s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("127.0.0.1", int(sys.argv[1]))); s.listen(); time.sleep(1800)' "$port" &
        TUTUCU_PID=$!
        local tutuldu=0 k
        for ((k = 0; k < 40; k++)); do
            if ! kill -0 "$TUTUCU_PID" 2>/dev/null; then break; fi
            if [[ -n "$(ss -H -l -t -n "sport = :$port" 2>/dev/null)" ]]; then tutuldu=1; break; fi
            sleep 0.25
        done
        if [[ "$tutuldu" -ne 1 ]]; then
            log_fail "erken: port tutucu süreç $port portunu tutamadı; senaryo koşulmadı"
            kill "$TUTUCU_PID" 2>/dev/null || true; wait "$TUTUCU_PID" 2>/dev/null || true; TUTUCU_PID=""
            komut_dene "$TMP_DIR/$ad.temizle.log" "$ad: temizle tamam" "$ad: temizle başarısız" "$KOSU" temizle
            kalan_yok "$ad"
            return
        fi
        log_ok "erken: gRPC portu $port tutucu süreç tarafından tutuluyor (PID $TUTUCU_PID)"
        ERKEN_BEKLENEN=1; ERKEN_SONUC=0; ERKEN_DIGER_CANLI=""
        senaryo_calistir "$ad" 3
        ERKEN_BEKLENEN=0
        if [[ "$ERKEN_SONUC" -eq 2 ]]; then log_ok "erken: yalnız araç 2 erken çıktı; koşu bariyerde asılı kalmadan sonlandırıldı"; else log_fail "erken: beklenen erken çıkış (araç 2) tespit edilmedi (sonuç: $ERKEN_SONUC)"; fi
        if [[ "$ERKEN_SONUC" -eq 2 ]]; then
            if [[ "$ERKEN_DIGER_CANLI" == "1 3 " ]]; then log_ok "erken: erken çıkış anında araç 1 ve 3 canlıydı (bariyerde bekliyorlardı)"; else log_fail "erken: erken çıkış anında canlı araçlar '${ERKEN_DIGER_CANLI}' (beklenen '1 3 ')"; fi
        fi
        if grep -q "zaten kullanımda" "$KOSU_DIR/arac_2.out" "$KOSU_DIR/arac_2.log" 2>/dev/null; then log_ok "erken: araç 2 açık hata yazdı (gRPC portu zaten kullanımda)"; else log_fail "erken: araç 2 çıktısında 'zaten kullanımda' hatası yok"; tail -n 6 "$KOSU_DIR/arac_2.out"; fi
        kill "$TUTUCU_PID" 2>/dev/null || true; wait "$TUTUCU_PID" 2>/dev/null || true; TUTUCU_PID=""
        # araçları bu betik başlattığı için 'durdur' ölü aracı görmez ve 'tamamlandi' yazardı; yarım kalan koşu 'temizle' ile 'yarida_kaldi' işaretlenir
        komut_dene "$TMP_DIR/$ad.temizle.log" "$ad: temizle tamam" "$ad: temizle başarısız" "$KOSU" temizle
        json_gecerli "$ad" yarida_kaldi
    fi
    if [[ -n "$TUTUCU_PID" ]]; then kill "$TUTUCU_PID" 2>/dev/null || true; TUTUCU_PID=""; fi
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
if want uc; then test_uc; fi
if want erken; then test_erken; fi

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
