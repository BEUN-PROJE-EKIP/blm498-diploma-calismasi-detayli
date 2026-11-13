#!/usr/bin/env bash
# kosu.sh — koşu başlat / durdur / durum / temizle: başsız Gazebo sunucusu + N PX4 SITL örneği, koşu klasörü ve koşu üst verisi.
# Kullanım: araclar/kosu.sh [--dry-run] baslat [--arac N] | durdur | durum | temizle
#   baslat    yeni koşu klasörü (.generated/kosular/<koşu kimliği>/) açar; Gazebo sunucusunu, sonra N PX4 örneğini ayrı süreç gruplarında
#             (setsid) başlatır; hazır olmazsa başlattığını geri alır. Koşu başarıyla başlayınca arka planda yaşar.
#             Başka gz sim/ruby/px4/mavsdk_server süreci ya da bitmemiş koşu varsa REDDEDER.
#   durdur    önce MAVSDK_GRPC_PORTS üzerinde dinleyen yetim mavsdk_server süreçlerini (bağdaştırıcı kapatmadıysa), sonra süreçleri SIGTERM ile
#             ters sırada (PX4'ler, Gazebo en son) bekleyerek kapatır; KOSU_KAPANIS_SN dolarsa SIGKILL ve kosu.json'a "zorla_kapatildi" yazılır.
#             Yetim sunucular kosu.json süreç listesine "mavsdk_server_<gRPC portu>" adıyla yazılır (adı kaynağını gösterir).
#   durum     yaşayan koşuyu, süreçleri ve dinleyen portları gösterir; ölü süreç varsa (-) ve çıkış 1.
#   temizle   yarım/çökmüş koşunun yalnız bu betiğin başlattığı süreç gruplarını ve yetim mavsdk_server'ları kapatır; koşu klasörünü silmez;
#             kosu.json "yarida_kaldi".
# Kimlik, port, başlangıç pozu, dünya ve model YALNIZ config/deney.env'den okunur. Bekleme süreleri KOSU_* anahtarlarıdır; aynı adlı ortam
# değişkeni (örn. KOSU_KAPANIS_SN=0) yapılandırmayı yalnız o çağrı için geçersiz kılar (test amaçlı). sudo gerekmez.
set -Eeuo pipefail
# shellcheck source=../setup/lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/../setup/lib/common.sh"

usage() { sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

ALT=""
ARAC_ARG=""
# shellcheck disable=SC2034  # common.sh (component_done) okur
MODE="install"
DRY_RUN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        baslat|durdur|durum|temizle) [[ -z "$ALT" ]] || { echo "Yalnız bir alt komut verilebilir" >&2; exit 2; }; ALT="$1" ;;
        --arac) [[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || { echo "--arac için sayı gerekli" >&2; exit 2; }; ARAC_ARG="$2"; shift ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Bilinmeyen argüman: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
[[ -n "$ALT" ]] || { usage >&2; exit 2; }
[[ -z "$ARAC_ARG" || "$ALT" == baslat ]] || { echo "--arac yalnız baslat ile kullanılır" >&2; exit 2; }
COMPONENT_NAME="Koşu: $ALT"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
PX4_BUILD="$ROOT_DIR/third_party/PX4-Autopilot/build/px4_sitl_default"
PX4_BIN="$PX4_BUILD/bin/px4"
YAYIM_SRC="$ROOT_DIR/src/yayim_damga"
YAYIM_BUILD="$GENERATED_DIR/yayim_damga/build"
KAMERA_URET="$ROOT_DIR/araclar/kamera_uret.py"
KOSU_KOK="$GENERATED_DIR/kosular"
AKTIF="$KOSU_KOK/aktif"

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

# --- Yapılandırma (ortamda verilmiş KOSU_* değerleri korunur) ---------------------------------
for v in KOSU_ARAC_SAYISI KOSU_GZ_HAZIR_SN KOSU_PX4_HAZIR_SN KOSU_KAPANIS_SN; do
    if [[ -n "${!v+x}" ]]; then declare "ONCEKI_$v=${!v}"; fi
done
[[ -f "$DENEY_ENV" ]] || fail_stop "Yapılandırma yok: $DENEY_ENV"
# shellcheck source=/dev/null
source "$DENEY_ENV"
for v in KOSU_ARAC_SAYISI KOSU_GZ_HAZIR_SN KOSU_PX4_HAZIR_SN KOSU_KAPANIS_SN; do
    o="ONCEKI_$v"
    if [[ -n "${!o+x}" ]]; then declare "$v=${!o}"; fi
    [[ -n "${!v:-}" && "${!v}" =~ ^[0-9]+$ ]] || fail_stop "$DENEY_ENV içinde $v tanımsız ya da sayı değil"
done
for v in UAV_SYS_IDS UAV_START_POSES MAVSDK_GRPC_PORTS SIM_WORLD SIM_MODEL CAM_RATE_HZ; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
read -r -a SYS_IDS <<< "$UAV_SYS_IDS"
read -r -a POSES <<< "$UAV_START_POSES"
read -r -a GRPC_PORTS <<< "$MAVSDK_GRPC_PORTS"
N_MAKS="${#SYS_IDS[@]}"
[[ "${#POSES[@]}" -eq "$N_MAKS" ]] || fail_stop "UAV_START_POSES ile UAV_SYS_IDS aynı uzunlukta olmalı"
N_ARAC="${ARAC_ARG:-$KOSU_ARAC_SAYISI}"
if [[ "$ALT" == baslat ]]; then
    [[ "$N_ARAC" -ge 1 && "$N_ARAC" -le "$N_MAKS" ]] || fail_stop "Araç sayısı 1..$N_MAKS olmalı (verilen: $N_ARAC)"
fi

# --- Süreç grubu yardımcıları ------------------------------------------------------------
GRUP_AD=()   # bu çağrıda başlatılan gruplar (baslat geri alma için)
GRUP_ID=()

start_group() { # start_group <ad> <günlük> <komut...> : LAST_PG = grup lideri (pid = pgid)
    local ad="$1" log="$2"; shift 2
    setsid "$@" > "$log" 2>&1 < /dev/null &
    LAST_PG=$!
    local pg="" k
    for ((k = 0; k < 20; k++)); do   # setsid() çağrısı fork'tan hemen sonra tamamlanmamış olabilir
        pg="$(ps -o pgid= -p "$LAST_PG" 2>/dev/null | tr -d ' ' || true)"
        [[ "$pg" == "$LAST_PG" ]] && break
        sleep 0.05
    done
    GRUP_AD+=("$ad"); GRUP_ID+=("$LAST_PG")
    [[ "$pg" == "$LAST_PG" ]] || { log_fail "$ad: süreç grubu lideri olmadı (pid $LAST_PG, pgid '$pg')"; return 1; }
    python3 -I "$HELPER" surec-ekle "$KOSU_DIR/kosu.json" "$ad" "$LAST_PG" "$LAST_PG"
}

group_alive() { kill -0 -- "-$1" 2>/dev/null; }

# stop_group <pgid> <bekleme_sn> : SIGTERM, bekle; süre dolarsa SIGKILL. Çıkış 0 = kendiliğinden kapandı, 3 = SIGKILL gerekti.
stop_group() {
    local pg="$1" sn="$2" i rc=0
    group_alive "$pg" || return 0
    kill -TERM -- "-$pg" 2>/dev/null || true
    for ((i = 0; i < sn * 10; i++)); do
        group_alive "$pg" || return 0
        sleep 0.1
    done
    if group_alive "$pg"; then
        kill -KILL -- "-$pg" 2>/dev/null || true
        rc=3
        for ((i = 0; i < 50; i++)); do group_alive "$pg" || break; sleep 0.1; done
    fi
    return "$rc"
}

wait_for_log() { # wait_for_log <dosya> <ERE> <sn> <pgid> : grup ölürse erken bırakır
    local f="$1" re="$2" secs="$3" pg="$4" i out
    for ((i = 0; i < secs * 10; i++)); do
        out="$(cat "$f" 2>/dev/null || true)"   # grep -q + pipefail tuzağı olmasın
        if [[ "$out" =~ $re ]]; then return 0; fi
        group_alive "$pg" || return 1
        sleep 0.1
    done
    return 1
}

dump_log() {
    local f="$1" line
    log_info "---- tam çıktı: ${f#"$ROOT_DIR"/} ----"
    while IFS= read -r line; do log_info "  | $line"; done < "$f"
    log_info "---- çıktı sonu ----"
}

gz_saat_sn() { # gz_saat_sn <partition> : simülasyon saniyesi (yoksa boş)
    GZ_PARTITION="$1" GZ_IP=127.0.0.1 timeout 5 gz topic -e -t "/world/$SIM_WORLD/clock" -n 1 2>/dev/null \
        | awk '/sim *\{/ {f=1} f && /sec:/ {print $2; exit}' || true
}

diger_surecler() { # başlatılmış gz sim / ruby / px4 / mavsdk_server var mı? (satır satır yazar)
    local c
    for c in gz ruby px4 mavsdk_server; do pgrep -a -x "$c" || true; done
    pgrep -af '[g]z sim' || true
}

dinleyen_portlar() { # dinleyen_portlar <pid> : o sürecin dinleyen UDP/TCP soketleri
    ss -H -l -n -u -t -p 2>/dev/null | awk -v p="pid=$1," 'index($0, p) {print $1, $5}' | LC_ALL=C sort -u | tr '\n' ';' || true
}

aktif_kosu() { if [[ -f "$AKTIF" ]]; then cat "$AKTIF"; fi; }

# damga_derle : damga bileşeni (src/yayim_damga) güncel değilse .generated/yayim_damga/build altında derler (yalnız bu dizin; çıktı depoya girmez)
damga_derle() {
    local jobs gen=() lib="$YAYIM_BUILD/libYayimDamga.so" yeni
    yeni="$(find "$YAYIM_SRC" -type f \( -name '*.cc' -o -name '*.hh' -o -name CMakeLists.txt \) -newer "$lib" 2>/dev/null | head -n 1 || true)"
    if [[ -f "$lib" && -z "$yeni" ]]; then log_ok "Damga bileşeni güncel: ${lib#"$ROOT_DIR"/}"; return 0; fi
    jobs="$(nproc)"
    if command -v ninja >/dev/null; then gen=(-G Ninja); fi
    log_info "Damga bileşeni derleniyor: cmake -S ${YAYIM_SRC#"$ROOT_DIR"/} -B ${YAYIM_BUILD#"$ROOT_DIR"/} (-j $jobs)"
    mkdir -p "$YAYIM_BUILD"
    cmake -S "$YAYIM_SRC" -B "$YAYIM_BUILD" "${gen[@]}" > "$YAYIM_BUILD/../cmake.log" 2>&1 || { log_fail "cmake yapılandırması başarısız (${YAYIM_BUILD#"$ROOT_DIR"/}/../cmake.log)"; return 1; }
    cmake --build "$YAYIM_BUILD" -j "$jobs" > "$YAYIM_BUILD/../build.log" 2>&1 || { log_fail "Damga bileşeni derlenemedi (${YAYIM_BUILD#"$ROOT_DIR"/}/../build.log)"; return 1; }
    [[ -f "$lib" ]] || { log_fail "Derleme çıktısı eksik: $lib"; return 1; }
    log_ok "Damga bileşeni derlendi: ${lib#"$ROOT_DIR"/}"
}

# uretim_hazirla <koşu_klasörü> : bu koşu için araç modeli (PX4 modellerine dokunmadan) ve Gazebo sunucu yapılandırması (PX4'ün yapılandırması + damga bileşeni) üretir
uretim_hazirla() {
    local kd="$1" px4_cfg onek ud="$1/uretim" kimlikler
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1 alt kabukta açılır
    px4_cfg="$(bash -c '. "$1/rootfs/gz_env.sh" >/dev/null 2>&1; printf "%s" "$PX4_GZ_SERVER_CONFIG"' _ "$PX4_BUILD")"
    [[ -f "$px4_cfg" ]] || { log_fail "PX4 sunucu yapılandırması bulunamadı: $px4_cfg"; return 1; }
    mkdir -p "$ud/modeller"
    python3 -I "$KAMERA_URET" model "$ud/modeller" > /dev/null || { log_fail "araç modeli üretilemedi"; return 1; }
    onek="${SIM_MODEL#gz_}_"
    kimlikler="${SYS_IDS[*]}"
    # PX4'ün yapılandırmasındaki bütün eklentiler korunur (fizik, sensörler, IMU, köprü eklentileri...); damga bileşeni sona eklenir.
    awk -v ek="    <plugin entity_name=\"*\" entity_type=\"world\" filename=\"libYayimDamga.so\" name=\"yayim::YayimDamga\">
      <cikti_yolu>$kd/kayit/gazebo_damga.jsonl</cikti_yolu><hz>$CAM_RATE_HZ</hz><model_onek>$onek</model_onek><arac_kimlikleri>$kimlikler</arac_kimlikleri>
    </plugin>" '/<\/plugins>/ {print ek} {print}' "$px4_cfg" > "$ud/server.config"
    grep -c '<plugin ' "$ud/server.config" > /dev/null || return 1
}

# --- baslat ---------------------------------------------------------------------------------
KOSU_DIR=""
BASLAT_BASLADI=0
BASLAT_TAMAM=0

exit_hook() { # baslat tamamlanmadan çıkılırsa (hata, Ctrl-C) başlatılanları geri al
    [[ "$ALT" == baslat && "$BASLAT_BASLADI" -eq 1 && "$BASLAT_TAMAM" -eq 0 ]] || return 0
    local i
    for ((i = ${#GRUP_ID[@]} - 1; i >= 0; i--)); do stop_group "${GRUP_ID[$i]}" 3 || true; done
    if [[ -n "$KOSU_DIR" && -f "$KOSU_DIR/kosu.json" ]]; then python3 -I "$HELPER" bitir "$KOSU_DIR/kosu.json" yarida_kaldi || true; fi
    rm -f "$AKTIF"
}

komut_baslat() {
    local i part id derece pg out
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] koşu klasörü: ${KOSU_KOK#"$ROOT_DIR"/}/<koşu kimliği>/ ; GZ_PARTITION koşu kimliğinden; dünya $SIM_WORLD, model $SIM_MODEL (başsız)"
        log_info "[dry-run] önce reddedilir: başka gz sim/ruby/px4/mavsdk_server süreci ya da bitmemiş koşu varsa"
        log_info "[dry-run] damga bileşeni güncel değilse derlenir (${YAYIM_BUILD#"$ROOT_DIR"/}); koşu için araç modeli ($SIM_MODEL, config/deney.env'den) ve sunucu yapılandırması (PX4'ün yapılandırması + damga bileşeni) ${KOSU_KOK#"$ROOT_DIR"/}/<koşu kimliği>/uretim/ altına üretilir"
        log_info "[dry-run] gz sunucusu (setsid, gz_sunucu.log); hazır ölçütü: simülasyon saati ilerliyor (en çok ${KOSU_GZ_HAZIR_SN} sn); damga kaydı kayit/gazebo_damga.jsonl"
        for ((i = 0; i < N_ARAC; i++)); do
            log_info "[dry-run] araç $((i + 1)): px4 -i $i (MAV_SYS_ID ${SYS_IDS[$i]}, konum ${POSES[$i]}), px4_$i.log; hazır: başlangıç betiği tamam (en çok ${KOSU_PX4_HAZIR_SN} sn)"
        done
        log_info "[dry-run] kosu.json: kimlik, sürüm, zamanlar, depo, SHA-256'lar, araçlar, süreçler; hazır olamazsa geri alınır"
        log_info "[dry-run] Hiçbir süreç başlatılmadı, hiçbir dosya yazılmadı"
        component_finish "$COMPONENT_NAME"
    fi
    check "Araç mevcut: gz" command -v gz
    check "PX4 SITL ikilisi" test -x "$PX4_BIN"
    check "PX4 gz_env.sh (rootfs)" test -f "$PX4_BUILD/rootfs/gz_env.sh"
    check "Dünya dosyası: $SIM_WORLD" test -f "$ROOT_DIR/third_party/PX4-Autopilot/Tools/simulation/gz/worlds/$SIM_WORLD.sdf"
    check "Araç kamerası üretim aracı" test -f "$KAMERA_URET"
    check "Araç: cmake" command -v cmake
    [[ "$COUNT_FAIL" -eq 0 ]] || fail_stop "Önkoşullar eksik"

    id="$(aktif_kosu)"
    if [[ -n "$id" ]]; then
        log_fail "Bitmemiş koşu var ($id); ikinci koşu başlatılmaz. Yaşıyorsa 'durdur', çökmüşse 'temizle' çalıştırın."
        component_failed "$COMPONENT_NAME"; exit 1
    fi
    out="$(diger_surecler)"
    if [[ -n "$out" ]]; then
        log_fail "Başka gz sim/ruby/px4/mavsdk_server süreci yaşıyor; koşu başlatılmaz:"
        while IFS= read -r i; do log_info "  | ${i:0:160}"; done <<< "$out"
        component_failed "$COMPONENT_NAME"; exit 1
    fi
    if pgrep -f '[r]os2-daemon' >/dev/null; then
        derece="$(tc qdisc show dev lo 2>/dev/null || true)"
        if [[ "$derece" != *htb* ]]; then
            log_warn "ros2 daemon yaşıyor ve lo üzerinde sürü ağı (tc) uygulanmamış; ölçülen ağ bozulabilir (tc'yi uygulamak kullanıcı işidir)"
        fi
    fi

    id="kosu_$(date +%Y%m%d_%H%M%S)"
    while [[ -e "$KOSU_KOK/$id" ]]; do sleep 1; id="kosu_$(date +%Y%m%d_%H%M%S)"; done
    part="$id"
    KOSU_DIR="$KOSU_KOK/$id"
    mkdir -p "$KOSU_DIR/calisma" "$KOSU_DIR/kayit"
    BASLAT_BASLADI=1
    python3 -I "$HELPER" baslangic "$KOSU_DIR/kosu.json" "$id" "$N_ARAC" "${SYS_IDS[*]:0:$N_ARAC}" "$part" "$SIM_WORLD" "$SIM_MODEL" "$DENEY_ENV" \
        || fail_stop "kosu.json yazılamadı"
    printf '%s\n' "$id" > "$AKTIF"
    log_info "Koşu $id (GZ_PARTITION=$part), $N_ARAC araç; klasör ${KOSU_DIR#"$ROOT_DIR"/}"
    damga_derle || exit 1
    uretim_hazirla "$KOSU_DIR" || fail_stop "Koşu üretimi hazırlanamadı"

    # Gazebo sunucusu (başsız). PX4 örnekleri çalışan dünyaya bağlanır; sunucu ayrı grupta olduğundan en son kapatılabilir.
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    start_group gz_sunucu "$KOSU_DIR/gz_sunucu.log" env LC_NUMERIC=C GZ_PARTITION="$part" GZ_IP=127.0.0.1 \
        bash -c '. "$1/rootfs/gz_env.sh"; export GZ_SIM_SERVER_CONFIG_PATH="$3/server.config"; export GZ_SIM_SYSTEM_PLUGIN_PATH="${GZ_SIM_SYSTEM_PLUGIN_PATH:+$GZ_SIM_SYSTEM_PLUGIN_PATH:}$4"; exec gz sim -r -s -v 2 "$PX4_GZ_WORLDS/$2.sdf"' \
        _ "$PX4_BUILD" "$SIM_WORLD" "$KOSU_DIR/uretim" "$YAYIM_BUILD" || exit 1
    pg="$LAST_PG"
    local t0 t1 ok=0
    for ((i = 0; i < KOSU_GZ_HAZIR_SN * 2; i++)); do
        group_alive "$pg" || break
        t0="$(gz_saat_sn "$part")"
        if [[ -n "$t0" ]]; then
            sleep 1
            t1="$(gz_saat_sn "$part")"
            if [[ -n "$t1" && "$t1" -gt "$t0" ]]; then ok=1; break; fi
        else
            sleep 0.5
        fi
    done
    if [[ "$ok" -ne 1 ]]; then
        log_fail "Gazebo simülasyon saati ${KOSU_GZ_HAZIR_SN} sn içinde ilerlemedi"; dump_log "$KOSU_DIR/gz_sunucu.log"; exit 1
    fi
    log_ok "Gazebo sunucusu hazır (simülasyon saati ilerliyor: $t0 → $t1 sn)"
    if [[ -f "$KOSU_DIR/kayit/gazebo_damga.jsonl" ]]; then log_ok "Damga bileşeni yüklendi (kayit/gazebo_damga.jsonl açıldı)"; else log_fail "Damga bileşeni yüklenmedi (kayit/gazebo_damga.jsonl yok)"; dump_log "$KOSU_DIR/gz_sunucu.log"; exit 1; fi

    for ((i = 0; i < N_ARAC; i++)); do
        mkdir -p "$KOSU_DIR/calisma/px4_$i"
        # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2/$3 alt kabukta açılır
        start_group "px4_$i" "$KOSU_DIR/px4_$i.log" env LC_NUMERIC=C GZ_PARTITION="$part" GZ_IP=127.0.0.1 HEADLESS=1 \
            PX4_SIM_MODEL="$SIM_MODEL" PX4_GZ_WORLD="$SIM_WORLD" PX4_GZ_MODEL_POSE="${POSES[$i]}" \
            bash -c '. "$1/rootfs/gz_env.sh"; export PX4_GZ_MODELS="$4"; cd "$2"; exec "$1/bin/px4" -i "$3" -d -s "$1/etc/init.d-posix/rcS" "$1/etc"' _ \
            "$PX4_BUILD" "$KOSU_DIR/calisma/px4_$i" "$i" "$KOSU_DIR/uretim/modeller" || exit 1
        pg="$LAST_PG"
        if ! wait_for_log "$KOSU_DIR/px4_$i.log" 'Startup script returned successfully' "$KOSU_PX4_HAZIR_SN" "$pg"; then
            log_fail "PX4 örneği $i ${KOSU_PX4_HAZIR_SN} sn içinde hazır olmadı"; dump_log "$KOSU_DIR/px4_$i.log"; exit 1
        fi
        log_ok "PX4 örneği $i hazır (MAV_SYS_ID ${SYS_IDS[$i]}, konum ${POSES[$i]})"
    done
    # son denetim: bütün gruplar yaşıyor
    for ((i = 0; i < ${#GRUP_ID[@]}; i++)); do
        group_alive "${GRUP_ID[$i]}" || { log_fail "${GRUP_AD[$i]} hazır olduktan sonra öldü"; exit 1; }
    done
    BASLAT_TAMAM=1   # bundan sonra çıkış tuzağı süreçlere dokunmaz: koşu arka planda yaşar
    log_ok "Koşu başladı: $id (süreç grupları: ${GRUP_AD[*]})"
    component_finish "$COMPONENT_NAME" "tamamlandı (koşu $id yaşıyor)"
}

# --- koşu bilgisi okuma ----------------------------------------------------------------------
kosu_yukle() { # AKTIF'ten KOSU_DIR ve süreç listesini yükler; yoksa 1
    local id
    id="$(aktif_kosu)"
    [[ -n "$id" ]] || return 1
    KOSU_DIR="$KOSU_KOK/$id"
    [[ -f "$KOSU_DIR/kosu.json" ]] || { log_fail "Aktif koşu işaretli ($id) ama kosu.json yok"; return 2; }
    SUR_AD=(); SUR_PID=(); SUR_GRUP=()
    local ad pid grup
    while read -r ad pid grup; do SUR_AD+=("$ad"); SUR_PID+=("$pid"); SUR_GRUP+=("$grup"); done < <(python3 -I "$HELPER" surecler "$KOSU_DIR/kosu.json")
    KOSU_ID="$id"
}

komut_durum() {
    local i rc=0
    if [[ "$DRY_RUN" -eq 1 ]]; then log_info "[dry-run] aktif koşu işaretini, süreçleri ve dinleyen portları gösterirdi"; component_finish "$COMPONENT_NAME"; fi
    kosu_yukle || rc=$?
    if [[ "$rc" -eq 1 ]]; then log_info "Yaşayan koşu yok"; component_finish "$COMPONENT_NAME" "yaşayan koşu yok"; fi
    [[ "$rc" -eq 0 ]] || fail_stop "Koşu bilgisi okunamadı"
    log_info "Koşu $KOSU_ID; klasör ${KOSU_DIR#"$ROOT_DIR"/}; GZ_PARTITION=$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" gz_partition)"
    for ((i = 0; i < ${#SUR_AD[@]}; i++)); do
        if group_alive "${SUR_GRUP[$i]}"; then
            log_ok "${SUR_AD[$i]}: yaşıyor (pid ${SUR_PID[$i]}, grup ${SUR_GRUP[$i]}); dinleyen: $(dinleyen_portlar "${SUR_PID[$i]}")"
        else
            log_fail "${SUR_AD[$i]}: ÖLÜ (pid ${SUR_PID[$i]}, grup ${SUR_GRUP[$i]}); koşu bozuk, 'temizle' çalıştırın"
        fi
    done
    component_finish "$COMPONENT_NAME" "tamamlandı"
}

# surecleri_kapat <bekleme_sn> : ters sırada kapatır; ZORLA (SIGKILL gerekenler) ve OLU_BULUNAN dizilerini doldurur
ZORLA=(); OLU_BULUNAN=()
surecleri_kapat() {
    local sn="$1" i rc
    ZORLA=(); OLU_BULUNAN=()
    for ((i = ${#SUR_AD[@]} - 1; i >= 0; i--)); do
        if ! group_alive "${SUR_GRUP[$i]}"; then
            OLU_BULUNAN+=("${SUR_AD[$i]}"); log_warn "${SUR_AD[$i]}: kapatma öncesi zaten ölüydü"; continue
        fi
        rc=0; stop_group "${SUR_GRUP[$i]}" "$sn" || rc=$?
        if [[ "$rc" -eq 3 ]]; then
            ZORLA+=("${SUR_AD[$i]}"); log_warn "${SUR_AD[$i]}: ${sn} sn içinde kapanmadı, SIGKILL uygulandı"
        elif [[ "$rc" -eq 0 ]]; then
            log_ok "${SUR_AD[$i]}: kapandı"
        fi
        if group_alive "${SUR_GRUP[$i]}"; then log_fail "${SUR_AD[$i]}: kapatılamadı (grup ${SUR_GRUP[$i]})"; fi
    done
}

# yetim_mavsdk_kapat <bekleme_sn> : MAVSDK_GRPC_PORTS üzerinde dinleyen mavsdk_server süreçlerini (yalnız süreç adı mavsdk_server ise) kosu.json'a
# "mavsdk_server_<port>" adıyla yazar ve önce SIGTERM ile kapatır; süre dolarsa SIGKILL. SIGKILL gerekenler YETIM_ZORLA dizisine girer.
YETIM_ZORLA=()
YETIM_SAYI=0
yetim_mavsdk_kapat() {
    local sn="$1" port out pid ad pgid i
    YETIM_ZORLA=(); YETIM_SAYI=0
    for port in "${GRPC_PORTS[@]}"; do
        out="$(ss -H -l -n -t -p "sport = :$port" 2>/dev/null || true)"
        pid="$(sed -n 's/.*pid=\([0-9]*\),.*/\1/p' <<< "$out" | head -n 1 || true)"
        [[ -n "$pid" ]] || continue
        if [[ "$(cat "/proc/$pid/comm" 2>/dev/null || true)" != mavsdk_server ]]; then
            log_warn "gRPC portu $port mavsdk_server olmayan bir süreç tarafından dinleniyor (pid $pid); dokunulmadı"
            continue
        fi
        ad="mavsdk_server_$port"
        pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
        python3 -I "$HELPER" surec-ekle "$KOSU_DIR/kosu.json" "$ad" "$pid" "${pgid:-$pid}"
        YETIM_SAYI=$((YETIM_SAYI + 1))
        log_warn "$ad: yetim süreç (pid $pid, gRPC portu $port); bağdaştırıcı kapatmamış, SIGTERM gönderiliyor"
        kill -TERM "$pid" 2>/dev/null || true
        for ((i = 0; i < sn * 10; i++)); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null || true
            YETIM_ZORLA+=("$ad")
            log_warn "$ad: ${sn} sn içinde kapanmadı, SIGKILL uygulandı"
        else
            log_ok "$ad: kapandı"
        fi
    done
    [[ "$YETIM_SAYI" -gt 0 ]] || log_info "Yetim mavsdk_server yok (gRPC portları: ${GRPC_PORTS[*]})"
}

komut_durdur() {
    local rc=0 durum
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] önce gRPC portlarında (${GRPC_PORTS[*]}) dinleyen yetim mavsdk_server süreçleri SIGTERM ile kapatılır ve kosu.json'a yazılır"
        log_info "[dry-run] SIGTERM ile ters sırada (PX4'ler, gz sunucusu en son), grup başına en çok ${KOSU_KAPANIS_SN} sn beklenir; dolarsa SIGKILL + kosu.json 'zorla_kapatildi'"
        log_info "[dry-run] Hiçbir süreç durdurulmadı"; component_finish "$COMPONENT_NAME"
    fi
    kosu_yukle || rc=$?
    if [[ "$rc" -eq 1 ]]; then log_info "Yaşayan koşu yok; yapılacak bir şey yok"; component_finish "$COMPONENT_NAME" "yaşayan koşu yok"; fi
    [[ "$rc" -eq 0 ]] || fail_stop "Koşu bilgisi okunamadı"
    log_info "Koşu $KOSU_ID durduruluyor (bekleme üst sınırı ${KOSU_KAPANIS_SN} sn)"
    yetim_mavsdk_kapat "$KOSU_KAPANIS_SN"
    surecleri_kapat "$KOSU_KAPANIS_SN"
    ZORLA=("${YETIM_ZORLA[@]+"${YETIM_ZORLA[@]}"}" "${ZORLA[@]+"${ZORLA[@]}"}")
    if [[ "${#ZORLA[@]}" -gt 0 ]]; then durum=zorla_kapatildi
    elif [[ "${#OLU_BULUNAN[@]}" -gt 0 ]]; then durum=yarida_kaldi; log_warn "Kapatma öncesi ölü süreç vardı (${OLU_BULUNAN[*]}); koşu 'yarida_kaldi' yazıldı"
    else durum=tamamlandi; fi
    python3 -I "$HELPER" bitir "$KOSU_DIR/kosu.json" "$durum" "${ZORLA[@]+"${ZORLA[@]}"}"
    rm -f "$AKTIF"
    log_info "Bitiş durumu: $durum"
    if [[ "$durum" == zorla_kapatildi ]]; then log_warn "Zorla kapatılan: ${ZORLA[*]} (kosu.json'a yazıldı)"; fi
    component_finish "$COMPONENT_NAME" "tamamlandı (bitiş durumu: $durum)"
}

komut_temizle() {
    local rc=0
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] gRPC portlarında (${GRPC_PORTS[*]}) dinleyen yetim mavsdk_server'ları ve bu betiğin başlattığı (kosu.json'daki) süreç gruplarını kapatır; koşu klasörünü silmez; 'yarida_kaldi' yazar"
        log_info "[dry-run] Hiçbir süreç durdurulmadı"; component_finish "$COMPONENT_NAME"
    fi
    kosu_yukle || rc=$?
    if [[ "$rc" -eq 1 ]]; then log_info "Temizlenecek koşu yok"; component_finish "$COMPONENT_NAME" "temizlenecek koşu yok"; fi
    [[ "$rc" -eq 0 ]] || fail_stop "Koşu bilgisi okunamadı"
    log_info "Koşu $KOSU_ID temizleniyor (kosu.json'daki süreç grupları ve yetim mavsdk_server'lar)"
    yetim_mavsdk_kapat "$KOSU_KAPANIS_SN"
    surecleri_kapat "$KOSU_KAPANIS_SN"
    python3 -I "$HELPER" bitir "$KOSU_DIR/kosu.json" yarida_kaldi
    rm -f "$AKTIF"
    log_ok "Koşu 'yarida_kaldi' olarak işaretlendi; klasör silinmedi: ${KOSU_DIR#"$ROOT_DIR"/}"
    component_finish "$COMPONENT_NAME" "tamamlandı (koşu klasörü korundu)"
}

case "$ALT" in
    baslat) komut_baslat ;;
    durdur) komut_durdur ;;
    durum) komut_durum ;;
    temizle) komut_temizle ;;
esac
