#!/usr/bin/env bash
# uc_mod_testi.sh — uçta mod kabul testleri (B11): araçlar kare sonuçlarını reliable DDS ile yer istasyonuna gönderir; yer istasyonu alıcı modülü ve sonuç defteri; deneme
# koordinatöründe COMPLETE kare koşulu (başsız Gazebo + PX4 SITL + ROS 2 araç süreçleri). Olağan akış (tek, hata, uc) araclar/kosu.sh + ASIL yer istasyonu koordinatörüyle (kosu.sh baslat --yer-istasyonu var → bekle → durdur);
# gecikme/eksik sonuç senaryoları (gecikme) deneme koordinatörüyle (araçları bu betik başlatır).
# Kullanım: ./uc_mod_testi.sh [--dry-run | --verify | -h] [birim] [tek] [hata] [uc] [gecikme]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz, hiçbir şey derlemez; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, kurulu paketler); süreç başlatmaz
# Testler:
#   birim     birim testleri (sonuç defteri, yayımcı, QoS ayarı; ROS'suz), colcon build (swarm_msgs, swarm_vehicle, swarm_gcs), saf modüllerin rclpy'siz içe aktarımı, py_compile, tek komut yolu,
#             SHM/taşıma profili denetimi
#   tek       --arac 1 (kosu.sh + asıl koordinatör), enjeksiyon kapalı: [n_ilk, n_son] her numara için yer istasyonunda tam bir sonuç; araç ↔ yer istasyonu birebir; COMPLETE yalnız son sonuçtan sonra; L = kullanilabilir − uretim;
#             sürü ağı sayaçları (tc), araç soketleri yalnız 10.10.0.x, SHM yok
#   hata      --arac 1 (kosu.sh + asıl koordinatör), enjeksiyon açık (KAMERA_ENJEKSIYON=dusur=+20, ISCI_ENJEKSIYON=hata=+40): yer istasyonunda STATUS_FRAME_NOT_RECEIVED ve STATUS_PROCESSING_ERROR; COMPLETE yine her numara tamamken
#   uc        --arac 3 (kosu.sh + asıl koordinatör), tam rota, enjeksiyon kapalı: üç araçta tam küme; bariyer bütün eşleşmelerden sonra; t0, tarama bitişleri, son sonuç, t1 sırası; araç başına L, RTF, tc
#   gecikme   (1) araç 1'in sondan üçüncü sonucunun yayımı KARE_SONUC_ENJEKSIYON=gecik=+379:20 ile 20 sn geciktirilir: koordinatör COMPLETE'i bekler; (2) sonuç hiç gelmez (gecik=+379:100000):
#             COMPLETE yayımlanmaz, koordinatör açık hata ile çıkar
# Araç süreçleri ve koordinatör `setsid` ile ayrı süreç gruplarında başlatılır; her çıkışta (hata, Ctrl-C dahil) bu betik kendisi toplar. Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ. sudo gerekmez.
# Ölçüm disiplini: Gazebo görsel istemcisi (gz sim -g) açıkken ölçüm yapılmaz.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/derleme.sh
source "$SETUP_DIR/lib/derleme.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        birim|tek|hata|uc|gecikme) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(birim tek hata uc gecikme)
COMPONENT_NAME="Uçta mod kare sonucu gönderimi"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
KOORD="$ROOT_DIR/araclar/deneme/koordinator_deneme.py"
ANALIZ="$ROOT_DIR/araclar/analiz/uc_mod_analiz.py"
VENV_PY="$ROOT_DIR/.venv/bin/python"
ENV_SH="$SETUP_DIR/env.sh"
DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
ROS_SETUP="/opt/ros/$ROS_DISTRO/setup.bash"
PROFIL="$ROOT_DIR/config/fastdds_profil.xml"
KOK="$GENERATED_DIR/kosular"
TMP_DIR=""
PGIDS=()
BIRIM_TESTLER=("$ROOT_DIR/src/swarm_gcs/test/test_sonuc_defteri.py" "$ROOT_DIR/src/swarm_gcs/test/test_hedef_birlestirme.py" "$ROOT_DIR/src/swarm_gcs/test/test_sonuc_alici.py" "$ROOT_DIR/src/swarm_vehicle/test/test_sonuc_yayin.py" "$ROOT_DIR/src/swarm_vehicle/test/test_rota_yon.py" "$ROOT_DIR/src/swarm_vehicle/test/test_disk_kuyrugu.py" "$ROOT_DIR/src/swarm_vehicle/test/test_kamera_alici.py")

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
for v in SIM_WORLD UAV_SYS_IDS UAV_NAMESPACES UAV1_ADDR UAV2_ADDR UAV3_ADDR GCS_ADDR KONU_KARE_SONUC KOSU_KAPANIS_SN; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
UAV_ADDRS=("$UAV1_ADDR" "$UAV2_ADDR" "$UAV3_ADDR")

# venv dışı PATH (ROS araçları sistem Python'unu kullansın)
clean_path() { local p="" d; local IFS=':'; for d in $PATH; do [[ "$d" == "$ROOT_DIR/.venv"* || "$d" == "$ROOT_DIR/.venv-px4/"* ]] || p+="${p:+:}$d"; done; echo "$p"; }
# shellcheck disable=SC2016  # tek tırnak bilerek: $1 alt kabukta açılır
ros_run() { env -u VIRTUAL_ENV PATH="$(clean_path)" bash -c 'source "$1"; shift; "$@"' _ "$ROS_SETUP" "$@"; }

check_prereqs() {
    local c f
    for c in gz ss pgrep python3 awk colcon tc; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "setup/env.sh" test -f "$ENV_SH"
    check "ROS 2 setup.bash" test -f "$ROS_SETUP"
    check "Kurulu araç paketleri (install/setup.bash; colcon build)" test -f "$ROOT_DIR/install/setup.bash"
    for f in "$KOSU" "$KOORD" "$ANALIZ" "${BIRIM_TESTLER[@]}" "$ROOT_DIR/src/swarm_gcs/swarm_gcs/uc_mod/sonuc_alici.py" "$ROOT_DIR/src/swarm_vehicle/swarm_vehicle/uc_mod/sonuc_yayin.py"; do
        check "Dosya: ${f#"$ROOT_DIR"/}" test -f "$f"
    done
    # shellcheck disable=SC2016  # tek tırnak bilerek: alt kabukta açılır
    check "Yapılandırılmış sürü ağı (lo üzerinde htb)" bash -c '[[ "$(tc qdisc show dev lo)" == *htb* ]]'
    check "kosu.sh --dry-run baslat çıkış 0" "$KOSU" --dry-run baslat
}

print_plan() {
    log_info "[dry-run] birim: birim testleri (${BIRIM_TESTLER[*]##*/}); colcon build --base-paths src --packages-select swarm_msgs swarm_vehicle swarm_gcs; saf modüllerin rclpy'siz içe aktarımı; py_compile; tek komut yolu; SHM/taşıma profili"
    log_info "[dry-run] tek: kosu.sh baslat --arac 1 --yer-istasyonu var (asıl koordinatör + araç 1; SWARM_BIND_ADDR=$UAV1_ADDR) → bekle → uc_mod_analiz.py → durdur"
    log_info "[dry-run] hata: tek + KAMERA_ENJEKSIYON=dusur=+20, ISCI_ENJEKSIYON=hata=+40"
    log_info "[dry-run] uc: kosu.sh baslat --arac 3 --yer-istasyonu var (asıl koordinatör + üç araç süreci: ${UAV_ADDRS[*]}) → bekle → tc sayacı, soket ve SHM denetimi → analiz → durdur"
    log_info "[dry-run] gecikme: (1) KARE_SONUC_ENJEKSIYON=gecik=+379:20 (2) gecik=+379:100000 + koordinatör --sonuc-zaman-asimi-sn 40"
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
        echo "proc yer_istasyonu $(pgrep -f -c 'swarm_gcs[.]gorev_koordinatoru' || true)"
        echo "proc isci $(pgrep -f -c 'swarm_vehicle[.]cikarim_isci' || true)"
    } > "$TMP_DIR/$n.proc"
    port_snapshot "$TMP_DIR/$n.ports"
    shm_list > "$TMP_DIR/$n.shm"
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$TMP_DIR/$n.net"
}

kalan_yok() { # kalan_yok <etiket>
    local et="$1" ok=1 yeni k
    sleep 1
    for ((k = 0; k < 50; k++)); do [[ "$(pgrep -f -c 'cikarim_canli_denetim[.]py' || true)" == "0" ]] && break; sleep 0.1; done
    snapshot "k_$et"
    if ! diff -q "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" >/dev/null; then ok=0; log_fail "$et: artık süreç var: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" | tr '\n' ';' || true)"; fi
    yeni="$(port_yeni "$TMP_DIR/once.ports" "$TMP_DIR/k_$et.ports")"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: yeni dinleyen port(lar): $yeni"; fi
    yeni="$(comm -13 "$TMP_DIR/once.shm" "$TMP_DIR/k_$et.shm" | tr '\n' ' ')"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: /dev/shm artığı: $yeni"; fi
    if [[ "$(pgrep -a -x ruby; pgrep -af '[g]z sim')" != "" ]]; then ok=0; log_fail "$et: gz sim süreci kaldı"; fi
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0 (gz/ruby/px4/mavsdk_server/araç süreci/işçi/koordinatör), yeni dinleyen port 0, /dev/shm artığı 0"; fi
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
    local ad="$1" bekl="$2" out bd l f
    if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kosu.json" 2>&1)"; then log_ok "$ad: kosu.json doğrulayıcıdan geçti"; else log_fail "$ad: kosu.json GEÇERSİZ"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; fi
    bd="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" bitis_durumu)"
    if [[ "$bd" == "$bekl" ]]; then log_ok "$ad: bitiş durumu '$bd'"; else log_fail "$ad: bitiş durumu '$bd' (beklenen '$bekl')"; fi
    for f in "$KOSU_DIR/kayit/yer_istasyonu_kare.jsonl" "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" "$KOSU_DIR"/kayit/arac_sureci_*.jsonl; do
        [[ -f "$f" ]] || continue
        if out="$(python3 -I "$DOGRULA" "$f" 2>&1)"; then log_ok "$ad: ${f#"$KOSU_DIR"/} doğrulayıcıdan geçti ($(tail -n 1 <<< "$out" | sed 's/, .*jsonl)/)/'))"; else log_fail "$ad: ${f#"$KOSU_DIR"/} GEÇERSİZ: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
    done
}

# ros_baslat <çıktı_dosyası> <komut...> : setsid ile ayrı süreç grubunda, ROS + venv ortamında; LAST_PG = grup lideri. EK_ENV: ek ortam değişkenleri (KEY=VAL)
LAST_PG=""
EK_ENV=()
ros_baslat() {
    local cikti="$1"; shift
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    setsid env -u VIRTUAL_ENV GZ_PARTITION="$PART" GZ_IP=127.0.0.1 LC_NUMERIC=C "${EK_ENV[@]+"${EK_ENV[@]}"}" bash -c 'source "$1" >/dev/null 2>&1; source "$2/install/setup.bash"; shift 2; exec "$@"' _ "$ENV_SH" "$ROOT_DIR" "$@" \
        > "$cikti" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
}

tc_bayt() { # sürü sınıfı (1:10) için gönderilen bayt sayısı
    tc -s class show dev lo 2>/dev/null | awk '/^class htb 1:10 / {f=1} f && /Sent/ {print $2; exit}'
}

# soket_denetimi <ad> <pid...> : araç süreçlerinin DDS soketleri yalnız sürü ağı adreslerinde; FASTRTPS paylaşımlı bellek bölümü yok
soket_denetimi() {
    local ad="$1" i pid soketler adres yanlis taban dom shm yeni; shift
    dom="${ROS_DOMAIN_ID:-42}"; taban=$((7400 + 250 * dom))
    i=0
    for pid in "$@"; do
        adres="${UAV_ADDRS[$i]}"; i=$((i + 1))
        soketler="$(ss -H -u -a -n -p 2>/dev/null | awk -v p="pid=$pid," 'index($0, p) {print $4}' | sort -u | tr '\n' ' ')"
        yanlis="$(tr ' ' '\n' <<< "$soketler" | awk -F: -v t="$taban" 'NF == 2 && $2 >= t && $2 < t + 250 && $1 !~ /^10\.10\.0\./ {print $0}' | tr '\n' ' ')"
        if [[ "$soketler" == *"$adres:"* && -z "$yanlis" ]]; then log_ok "$ad: araç $i DDS soketleri yalnız sürü ağı adreslerinde (kendi adresi $adres dahil)"; else log_fail "$ad: araç $i DDS soketi sürü ağında değil ya da kendi adresi ($adres) yok; soketler: $soketler; yanlış: $yanlis"; fi
        # Fast DDS SHM taşıması /dev/shm altında fastrtps_* / fastdds_* bölümleri ve sem.fastrtps_* semaforları açar; kitaplık (.so) eşlemeleri bu değildir
        shm="$(grep -cE '/dev/shm/(sem\.)?(fastrtps|fastdds|fast_datasharing)' "/proc/$pid/maps" 2>/dev/null || true)"
        yeni="$(shm_list | grep -cE '^(sem\.)?(fastrtps|fastdds|fast_datasharing)' || true)"
        if [[ "${shm:-0}" == "0" && "${yeni:-0}" == "0" ]]; then log_ok "$ad: araç $i süreci /dev/shm altında Fast DDS paylaşımlı bellek bölümü eşlemiyor, /dev/shm'de fastrtps/fastdds bölümü yok (SHM yok)"; else log_fail "$ad: araç $i süreci Fast DDS paylaşımlı bellek bölümü eşlemiş ($shm eşleme, /dev/shm'de $yeni dosya)"; fi
    done
}

# senaryo <ad> <araç_sayısı> <analiz_argümanları|-> <koordinatör_argümanları...> : EK_ENV ve koordinatör argümanlarıyla bir koşu
senaryo() {
    local ad="$1" n="$2" analiz_arg="$3" i kpg rc=0 t0=$SECONDS tc0 tc1 arc line kmax; shift 3
    local -a apid=() aa=()
    kosu_baslat "$ad" --arac "$n" || return 0
    tc0="$(tc_bayt)"
    ros_baslat "$KOSU_DIR/koordinator.out" timeout -k 5 1700 python "$KOORD" --arac "$n" --zaman-asimi-sn 1600 "$@"
    kpg="$LAST_PG"
    sleep 4
    for ((i = 1; i <= n; i++)); do
        ros_baslat "$KOSU_DIR/arac_$i.out" python -m swarm_vehicle.arac "$i"
        apid+=("$LAST_PG")
    done
    log_info "$ad: koordinatör pid $kpg, araç süreçleri pid ${apid[*]}; ek ortam: ${EK_ENV[*]:-yok}"
    # t0 yayımlanınca soket ve SHM denetimi
    for ((i = 0; i < 6000; i++)); do
        if grep -q '^KOORDINATOR t0' "$KOSU_DIR/koordinator.out" 2>/dev/null; then break; fi
        kill -0 "$kpg" 2>/dev/null || break
        sleep 0.25
    done
    if grep -q '^KOORDINATOR t0' "$KOSU_DIR/koordinator.out" 2>/dev/null; then soket_denetimi "$ad" "${apid[@]}"; fi
    wait "$kpg" 2>/dev/null || rc=$?
    if [[ "$analiz_arg" == "--hic" ]]; then
        # bir sonuç hiç gelmez: araçlar WAIT'te bekler; koordinatör açık hata ile çıkmalı
        if [[ "$rc" -eq 1 ]]; then log_ok "$ad: koordinatör zaman aşımıyla çıktı (çıkış 1), COMPLETE yayımlanmadı"; else log_fail "$ad: koordinatör çıkış kodu $rc (beklenen 1)"; fi
        for ((i = 0; i < n; i++)); do grup_oldur "${apid[$i]}"; done
    else
        if [[ "$rc" -eq 0 ]]; then log_ok "$ad: koordinatör çıkış 0 ($((SECONDS - t0)) sn gerçek)"; else log_fail "$ad: koordinatör çıkış kodu $rc"; tail -n 8 "$KOSU_DIR/koordinator.out"; fi
        for ((i = 0; i < n; i++)); do
            arc=0
            for ((kmax = 0; kmax < 400; kmax++)); do kill -0 "${apid[$i]}" 2>/dev/null || break; sleep 0.1; done
            if kill -0 "${apid[$i]}" 2>/dev/null; then log_fail "$ad: araç $((i + 1)) süreci TAMAMLANDI'dan sonra 40 sn içinde kapanmadı"; else wait "${apid[$i]}" 2>/dev/null || arc=$?; fi
            if [[ "$arc" -eq 0 ]]; then log_ok "$ad: araç $((i + 1)) süreci kendiliğinden kapandı (çıkış 0)"; else log_fail "$ad: araç $((i + 1)) süreci çıkış kodu $arc"; tail -n 6 "$KOSU_DIR/arac_$((i + 1)).out"; fi
        done
    fi
    tc1="$(tc_bayt)"
    PGIDS=()
    if [[ "$analiz_arg" == "--hic" ]]; then aa=(--hic); elif [[ "$analiz_arg" != "-" ]]; then read -r -a aa <<< "$analiz_arg"; fi
    "$VENV_PY" -I "$ANALIZ" "$KOSU_DIR" --arac "$n" "${aa[@]+"${aa[@]}"}" --tc-once "${tc0:-0}" --tc-sonra "${tc1:-0}" > "$TMP_DIR/$ad.analiz.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            "OLCUM "*) log_info "$ad: ${line#OLCUM }" ;;
            Traceback*|*Error*) log_fail "$ad: analiz hatası: $line" ;;
        esac
    done < "$TMP_DIR/$ad.analiz.log"
    if [[ "$rc" -gt 1 ]]; then log_fail "$ad: analiz çıkış kodu $rc"; tail -n 12 "$TMP_DIR/$ad.analiz.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
    komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
    json_gecerli "$ad" tamamlandi
}

# senaryo_asil <ad> <araç_sayısı> <analiz_argümanları|-> : OLAĞAN AKIŞ, ASIL yer istasyonu koordinatörüyle: kosu.sh baslat --yer-istasyonu var (EK_ENV ile) → bekle → analiz → durdur
senaryo_asil() {
    local ad="$1" n="$2" analiz_arg="$3" i rc=0 t0=$SECONDS tc0 tc1 id line w p
    local -a aa=() pids=()
    tc0="$(tc_bayt)"
    env "${EK_ENV[@]+"${EK_ENV[@]}"}" "$KOSU" baslat --arac "$n" --yer-istasyonu var > "$TMP_DIR/$ad.baslat.log" 2>&1 || rc=$?
    if [[ "$rc" -ne 0 ]]; then log_fail "$ad: baslat başarısız (çıkış $rc)"; tail -n 10 "$TMP_DIR/$ad.baslat.log"; return 0; fi
    id="$(cat "$KOK/aktif")"
    KOSU_DIR="$KOK/$id"
    log_ok "$ad: baslat tamam, koşu $id (asıl yer istasyonu koordinatörü + $n araç süreci); ek ortam: ${EK_ENV[*]:-yok}"
    # t0 yayımlanınca soket ve SHM denetimi (araç sürecinin python alt süreci)
    for ((i = 0; i < 6000; i++)); do
        if [[ -f "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" ]] && grep -q '"olay": "t0"' "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl"; then break; fi
        if [[ -f "$KOSU_DIR/yer_istasyonu.cikis" ]]; then break; fi
        sleep 0.25
    done
    if [[ -f "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" ]] && grep -q '"olay": "t0"' "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl"; then
        for ((i = 1; i <= n; i++)); do
            w="$(python3 -I "$HELPER" surecler "$KOSU_DIR/kosu.json" | awk -v a="arac_$i" '$1 == a {print $2}')"
            p="$(pgrep -P "$w" -f 'swarm_vehicle[.]arac' | head -n 1 || true)"
            pids+=("${p:-$w}")
        done
        soket_denetimi "$ad" "${pids[@]}"
    fi
    rc=0
    "$KOSU" bekle --sure-sn 900 > "$TMP_DIR/$ad.bekle.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "$ad: yer istasyonu çıkış 0 ($((SECONDS - t0)) sn gerçek)"; else log_fail "$ad: kosu.sh bekle çıkış kodu $rc"; tail -n 6 "$TMP_DIR/$ad.bekle.log"; fi
    tc1="$(tc_bayt)"
    rc=0
    if [[ "$analiz_arg" != "-" ]]; then read -r -a aa <<< "$analiz_arg"; fi
    "$VENV_PY" -I "$ANALIZ" "$KOSU_DIR" --arac "$n" "${aa[@]+"${aa[@]}"}" --tc-once "${tc0:-0}" --tc-sonra "${tc1:-0}" > "$TMP_DIR/$ad.analiz.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            "OLCUM "*) log_info "$ad: ${line#OLCUM }" ;;
            Traceback*|*Error*) log_fail "$ad: analiz hatası: $line" ;;
        esac
    done < "$TMP_DIR/$ad.analiz.log"
    if [[ "$rc" -gt 1 ]]; then log_fail "$ad: analiz çıkış kodu $rc"; tail -n 12 "$TMP_DIR/$ad.analiz.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
    komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
    json_gecerli "$ad" tamamlandi
}

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

# --- Testler ----------------------------------------------------------------------------------------------------------
test_birim() {
    local out rc=0 l mod t
    log_info "== birim: birim testleri, derleme, içe aktarma, tek komut yolu, SHM/taşıma profili =="
    for t in "${BIRIM_TESTLER[@]}"; do
        rc=0
        out="$("$VENV_PY" -I "$t" 2>&1)" || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "birim: ${t##*/} geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: ${t##*/} BAŞARISIZ"; tail -n 15 <<< "$out"; fi
    done
    out="$GENERATED_DIR/uc_mod_derleme.txt"
    if proje_derle "$out"; then
        log_ok "birim: proje derlendi (swarm_msgs + swarm_vehicle + swarm_gcs; ortak yol: setup/lib/derleme.sh)"
    else
        log_fail "birim: proje derlemesi BAŞARISIZ; günlük: ${out#"$ROOT_DIR"/}"
        tail -n 12 "$out" | while IFS= read -r l; do log_info "  | $l"; done
    fi
    for mod in swarm_gcs.birlestirme.sonuc_defteri swarm_vehicle.uc_mod.sonuc_yayin swarm_vehicle.ucus.rota; do
        rc=0
        # shellcheck disable=SC2016  # tek tırnak bilerek: Python kodu
        "$VENV_PY" -I -c 'import sys; sys.path[:0] = sys.argv[1:3]; import importlib; importlib.import_module(sys.argv[3]); assert "rclpy" not in sys.modules and "mavsdk" not in sys.modules' \
            "$ROOT_DIR/src/swarm_vehicle" "$ROOT_DIR/src/swarm_gcs" "$mod" > "$TMP_DIR/ice_$mod.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "birim: $mod rclpy ve mavsdk olmadan içe aktarıldı"; else log_fail "birim: $mod içe aktarma hatası"; tail -n 5 "$TMP_DIR/ice_$mod.log"; fi
    done
    rc=0
    "$VENV_PY" -m py_compile "$ROOT_DIR/src/swarm_gcs/swarm_gcs/uc_mod/sonuc_alici.py" "$ROOT_DIR/src/swarm_gcs/swarm_gcs/birlestirme/sonuc_defteri.py" "$ROOT_DIR/src/swarm_vehicle/swarm_vehicle/uc_mod/sonuc_yayin.py" "$ROOT_DIR/src/swarm_vehicle/swarm_vehicle/arac.py" "$KOORD" "$ANALIZ" > "$TMP_DIR/pyc.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: py_compile temiz"; else log_fail "birim: py_compile hata"; tail -n 5 "$TMP_DIR/pyc.log"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '^\s*(from|import) mavsdk' -- src || true)"
    if [[ -n "$out" && "$(awk -F: '{print $1}' <<< "$out" | sort -u)" == "src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py" ]]; then log_ok "birim: src/ altında mavsdk'yı içe aktaran tek dosya px4_adapter.py"; else log_fail "birim: mavsdk içe aktarımı beklenenden farklı: $out"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '\.action\.|\.mission\b|\.mission_raw|\.param\.set|set_param|set_rate_|\.offboard\.|send_message' -- src ':!src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: src/ altında px4_adapter.py dışında PX4'e yazan çağrı yok"; else log_fail "birim: dış çağrı: $out"; fi
    # taşıma profili: yerleşik taşımalar kapalı, yalnız UDPv4; data-sharing ve intraprocess kapalı (SHM yolu yok)
    out="$(cat "$PROFIL")"
    if [[ "$out" == *"<useBuiltinTransports>false</useBuiltinTransports>"* && "$out" == *"<type>UDPv4</type>"* && "$out" != *"<type>SHM</type>"* && "$out" == *"<kind>OFF</kind>"* && "$out" == *"<intraprocess_delivery>OFF</intraprocess_delivery>"* ]]; then
        log_ok "birim: Fast DDS profili: yerleşik taşımalar kapalı, yalnız UDPv4, data-sharing ve intraprocess teslimi kapalı (paylaşımlı bellek yok)"
    else
        log_fail "birim: Fast DDS profilinde SHM'ye izin veren ayar olabilir: $PROFIL"
    fi
}

test_tek() {
    local ad=tek
    log_info "== tek: araç 1 + koordinatör, enjeksiyon kapalı =="
    EK_ENV=()
    senaryo_asil "$ad" 1 - ; kalan_yok "$ad"
}

test_hata() {
    local ad=hata
    log_info "== hata: araç 1, kare kaybı (KAMERA_ENJEKSIYON=dusur=+20) ve işçi hatası (ISCI_ENJEKSIYON=hata=+40) =="
    EK_ENV=("KAMERA_ENJEKSIYON=dusur=+20" "ISCI_ENJEKSIYON=hata=+40")
    senaryo_asil "$ad" 1 --hata ; EK_ENV=(); kalan_yok "$ad"
}

test_uc() {
    local ad=uc
    log_info "== uc: üç araç, tam rota, enjeksiyon kapalı =="
    EK_ENV=()
    senaryo_asil "$ad" 3 - ; kalan_yok "$ad"
}

test_gecikme() {
    local ad=gecikme
    log_info "== gecikme (1): sondan üçüncü sonucun yayımı 20 sn geciktirilir; COMPLETE beklenir =="
    EK_ENV=("KARE_SONUC_ENJEKSIYON=gecik=+379:20")
    senaryo "$ad" 1 "--gecikme-sn 20" ; EK_ENV=(); kalan_yok "$ad"
    ad=hic
    log_info "== gecikme (2): bir sonuç hiç gelmez; COMPLETE yayımlanmaz, koordinatör açık hata verir =="
    EK_ENV=("KARE_SONUC_ENJEKSIYON=gecik=+379:100000")
    senaryo "$ad" 1 --hic --sonuc-zaman-asimi-sn 40 ; EK_ENV=(); kalan_yok "$ad"
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server; pgrep -af 'swarm_vehicle[.]arac|koordinator_deneme[.]py|swarm_gcs[.]gorev_koordinatoru|swarm_vehicle[.]cikarim_isci')" ]]; then
    fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server/araç süreci/işçi/koordinatör yaşıyor; önce kapatın (görsel istemci 'gz sim -g' açıksa kapatın)"
fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), ROS $ROS_DISTRO, PX4 $PX4_TAG; testler: ${TESTS[*]}"

if want birim; then test_birim; fi
if want tek; then test_tek; fi
if want hata; then test_hata; fi
if want uc; then test_uc; fi
if want gecikme; then test_gecikme; fi

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
