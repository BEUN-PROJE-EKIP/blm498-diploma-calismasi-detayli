#!/usr/bin/env bash
# kosu_testi.sh — araclar/kosu.sh (koşu başlat/durdur/durum/temizle) ve koşu üst verisi kabul testleri; başsız Gazebo + PX4 SITL.
# Kullanım: ./kosu_testi.sh [--dry-run | --verify | -h] [tek] [uc] [crash] [zorla]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, kosu.sh --dry-run); süreç başlatmaz
# Testler (en uzun tek koşu ≤ 60 sim sn):
#   tek     tek araç döngüsü ×3: baslat → hazır → ≥ 20 sim sn → durdur; kosu.json geçerli + "tamamlandi", artık süreç/port/shm yok
#   uc      üç araç ×1 (≤ 30 sim sn): üç PX4 örneği doğru örnek numarası/portla yaşıyor; yaşarken ikinci baslat reddedilir ve koşuya dokunmaz
#   crash   yaşayan koşuda bir PX4'e SIGKILL: durum bunu gösterir; temizle artık bırakmaz, kosu.json "yarida_kaldi"; ardından yeni baslat çalışır
#   zorla   KOSU_KAPANIS_SN=0 ile durdur SIGKILL'e düşer: kosu.json "zorla_kapatildi" (+ zorla_kapatilan listesi)
# Her çıkışta yaşayan koşu kalmışsa temizle çalıştırılır. Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz). sudo gerekmez.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        tek|uc|crash|zorla) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(tek uc crash zorla)
COMPONENT_NAME="Koşu başlat/durdur betiği ve koşu kaydı"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
KOK="$GENERATED_DIR/kosular"
TMP_DIR=""

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

exit_hook() {
    if [[ -f "$KOK/aktif" ]]; then "$KOSU" temizle >/dev/null 2>&1 || true; fi
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
    TMP_DIR=""
}

[[ -f "$DENEY_ENV" ]] || fail_stop "Yapılandırma yok: $DENEY_ENV"
# shellcheck source=/dev/null
source "$DENEY_ENV"
for v in SIM_WORLD UAV_SYS_IDS KOSU_KAPANIS_SN; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
read -r -a SYS_IDS <<< "$UAV_SYS_IDS"

check_prereqs() {
    local c
    for c in gz ss pgrep python3 awk; do check "Araç mevcut: $c" command -v "$c"; done
    check "Koşu betiği: ${KOSU#"$ROOT_DIR"/}" test -x "$KOSU"
    check "Koşu üst veri yazıcısı" test -f "$HELPER"
    check "Sözleşme doğrulayıcısı" test -f "$DOGRULA"
    check "kosu.sh --dry-run baslat çıkış 0" "$KOSU" --dry-run baslat
    check "kosu.sh --dry-run durdur çıkış 0" "$KOSU" --dry-run durdur
}

print_plan() {
    log_info "[dry-run] tek: baslat → ≥ 20 sim sn → durdur ×3; her seferinde kosu.json doğrulayıcıdan geçer, 'tamamlandi', artık süreç/port/shm 0"
    log_info "[dry-run] uc: baslat --arac 3 (≤ 30 sim sn): px4 -i 0..2 + dinleyen portlar; yaşarken ikinci baslat reddedilir; durdur temiz"
    log_info "[dry-run] crash: bir PX4'e SIGKILL → durum ölü gösterir; temizle → 'yarida_kaldi', artık süreç yok; yeni baslat çalışır"
    log_info "[dry-run] zorla: KOSU_KAPANIS_SN=0 ile durdur → 'zorla_kapatildi'"
    log_info "[dry-run] Sonda px4/gz/mavsdk_server/ruby, port, /dev/shm, ros2 daemon, tc/ip denetimi. Hiçbir süreç başlatılmadı"
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
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0, yeni dinleyen port 0, /dev/shm artığı 0"; fi
    return 0
}

# --- Yardımcılar ----------------------------------------------------------------------
KOSU_DIR=""
kosu_baslat() { # kosu_baslat <ad> [kosu.sh argümanları...] : KOSU_DIR ayarlanır; başarısızlıkta 1
    local ad="$1" out id rc=0; shift
    out="$("$KOSU" baslat "$@" 2>&1)" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: baslat başarısız (çıkış $rc)"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; return 1
    fi
    id="$(cat "$KOK/aktif")"
    KOSU_DIR="$KOK/$id"
    log_ok "$ad: baslat tamam, koşu $id"
    return 0
}

sim_saat() { # sim_saat : yaşayan koşunun simülasyon saniyesi (boş olabilir)
    local part
    part="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" gz_partition)"
    GZ_PARTITION="$part" GZ_IP=127.0.0.1 timeout 5 gz topic -e -t "/world/$SIM_WORLD/clock" -n 1 2>/dev/null \
        | awk '/sim *\{/ {f=1} f && /sec:/ {print $2; exit}' || true
}

bekle_sim() { # bekle_sim <ad> <sim_sn> : saat bu kadar ilerleyene dek bekler (duvar zamanı üst sınırı 4× + 60 sn)
    local ad="$1" sn="$2" t0 t i
    t0="$(sim_saat)"
    [[ -n "$t0" ]] || { log_fail "$ad: simülasyon saati okunamadı"; return 1; }
    for ((i = 0; i < sn * 4 + 60; i++)); do
        t="$(sim_saat)"
        if [[ -n "$t" && "$t" -ge $((t0 + sn)) ]]; then log_ok "$ad: simülasyon saati $t0 → $t sn (≥ $sn sn ilerledi)"; return 0; fi
        sleep 1
    done
    log_fail "$ad: simülasyon saati $sn sn ilerlemedi"; return 1
}

# komut_dene <günlük> <başarı_iletisi> <hata_iletisi> <komut...> : komut çıkışı 0 ise (+), değilse (-) ve günlüğün sonu; ortam değişkeni için env kullanın
komut_dene() {
    local log="$1" ok="$2" hata="$3"; shift 3
    if "$@" > "$log" 2>&1; then log_ok "$ok"; else log_fail "$hata"; tail -n 8 "$log"; fi
}

json_gecerli() { # json_gecerli <ad> <beklenen_bitis_durumu>
    local ad="$1" bekl="$2" out bd
    if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kosu.json" 2>&1)"; then
        log_ok "$ad: kosu.json doğrulayıcıdan geçti"
    else
        log_fail "$ad: kosu.json GEÇERSİZ"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"
    fi
    bd="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" bitis_durumu)"
    if [[ "$bd" == "$bekl" ]]; then log_ok "$ad: bitiş durumu '$bd'"; else log_fail "$ad: bitiş durumu '$bd' (beklenen '$bekl')"; fi
}

# --- Testler ----------------------------------------------------------------------------
want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

test_tek() {
    local r ad
    for r in 1 2 3; do
        ad="tek_$r"
        log_info "== $ad: tek araç döngüsü =="
        if kosu_baslat "$ad" --arac 1; then
            bekle_sim "$ad" 20 || true
            komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
            json_gecerli "$ad" tamamlandi
        fi
        kalan_yok "$ad"
    done
}

test_uc() {
    local n="${#SYS_IDS[@]}" i ad=uc out id pid ports
    [[ "$n" -ge 3 ]] || { log_fail "uc: yapılandırmada 3 araç yok"; return; }
    log_info "== uc: üç araç, yaşarken ikinci baslat =="
    if kosu_baslat "$ad" --arac 3; then
        bekle_sim "$ad" 10 || true
        out="$("$KOSU" durum 2>&1)" || true
        for ((i = 0; i < 3; i++)); do
            pid="$(python3 -I "$HELPER" surecler "$KOSU_DIR/kosu.json" | awk -v a="px4_$i" '$1 == a {print $2}')"
            if [[ -z "$pid" ]] || ! [[ -r "/proc/$pid/cmdline" ]]; then log_fail "$ad: px4_$i süreci yok"; continue; fi
            if [[ "$(tr '\0' ' ' < "/proc/$pid/cmdline")" == *" -i $i "* ]]; then log_ok "$ad: px4_$i çalışıyor: komut satırında '-i $i' (MAV_SYS_ID ${SYS_IDS[$i]}), pid $pid"; else log_fail "$ad: px4_$i komut satırında -i $i yok"; fi
            ports="$(ss -H -l -n -u -t -p 2>/dev/null | awk -v p="pid=$pid," 'index($0, p) {print $1":"$5}' | sort -u | tr '\n' ' ')"
            log_info "$ad: px4_$i (pid $pid) dinleyen: $ports"
            # PX4 SITL: yerel MAVLink portu 18570+i, ek port 14580+i (örnek numarasına göre kayar)
            if [[ "$ports" == *":$((18570 + i)) "* && "$ports" == *":$((14580 + i)) "* ]]; then
                log_ok "$ad: px4_$i örnek portları doğru (udp $((18570 + i)) ve $((14580 + i)))"
            else
                log_fail "$ad: px4_$i beklenen portlar (udp $((18570 + i)), $((14580 + i))) görünmüyor"
            fi
        done
        if [[ "$out" == *px4_2* ]]; then log_ok "$ad: durum üç PX4 örneğini de listeledi"; else log_fail "$ad: durum çıktısında px4_2 yok"; fi
        # ikinci baslat reddedilmeli ve yaşayan koşuya dokunmamalı
        id="$(cat "$KOK/aktif")"
        local rc=0 once sonra
        once="$(python3 -I "$HELPER" surecler "$KOSU_DIR/kosu.json")"
        "$KOSU" baslat > "$TMP_DIR/cift.log" 2>&1 || rc=$?
        sonra="$(python3 -I "$HELPER" surecler "$KOSU_DIR/kosu.json")"
        if [[ "$rc" -ne 0 ]] && [[ "$(cat "$KOK/aktif")" == "$id" ]] && [[ "$once" == "$sonra" ]] && "$KOSU" durum >/dev/null 2>&1; then
            log_ok "$ad: ikinci baslat reddedildi (çıkış $rc); yaşayan koşu ($id) ve süreçleri aynı, durum (+)"
        else
            log_fail "$ad: ikinci baslat reddedilmedi ya da yaşayan koşuyu bozdu (çıkış $rc)"; tail -n 6 "$TMP_DIR/cift.log"
        fi
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
    fi
    kalan_yok "$ad"
}

test_crash() {
    local ad=crash pid rc=0 out
    log_info "== crash: PX4'e SIGKILL, durum, temizle, yeniden baslat =="
    if kosu_baslat "$ad" --arac 1; then
        bekle_sim "$ad" 5 || true
        pid="$(python3 -I "$HELPER" surecler "$KOSU_DIR/kosu.json" | awk '$1 == "px4_0" {print $2}')"
        kill -KILL "$pid" 2>/dev/null || true
        sleep 2
        out="$("$KOSU" durum 2>&1)" || rc=$?
        if [[ "$rc" -ne 0 && "$out" == *"px4_0: ÖLÜ"* ]]; then log_ok "$ad: durum çökmüş PX4'ü gösterdi (çıkış $rc)"; else log_fail "$ad: durum çökmeyi göstermedi (çıkış $rc)"; fi
        komut_dene "$TMP_DIR/$ad.temizle.log" "$ad: temizle tamam" "$ad: temizle başarısız" "$KOSU" temizle
        json_gecerli "$ad" yarida_kaldi
        if [[ -d "$KOSU_DIR" ]]; then log_ok "$ad: koşu klasörü silinmedi"; else log_fail "$ad: koşu klasörü silinmiş"; fi
        kalan_yok "${ad}_temizlik"
        if kosu_baslat "${ad}_yeniden" --arac 1; then
            komut_dene "$TMP_DIR/$ad.durdur2.log" "${ad}_yeniden: durdur tamam" "${ad}_yeniden: durdur başarısız" "$KOSU" durdur
            json_gecerli "${ad}_yeniden" tamamlandi
        fi
    fi
    kalan_yok "$ad"
}

test_zorla() {
    local ad=zorla
    log_info "== zorla: KOSU_KAPANIS_SN=0 ile durdur =="
    if kosu_baslat "$ad" --arac 1; then
        bekle_sim "$ad" 5 || true
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam (SIGKILL'e düştü)" "$ad: durdur başarısız" env KOSU_KAPANIS_SN=0 "$KOSU" durdur
        json_gecerli "$ad" zorla_kapatildi
        log_info "$ad: zorla kapatılan: $(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["zorla_kapatilan"])' "$KOSU_DIR/kosu.json")"
    fi
    kalan_yok "$ad"
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server)" ]]; then fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server süreci yaşıyor; önce kapatın"; fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), PX4 $PX4_TAG; testler: ${TESTS[*]}"

if want tek; then test_tek; fi
if want uc; then test_uc; fi
if want crash; then test_crash; fi
if want zorla; then test_zorla; fi

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
