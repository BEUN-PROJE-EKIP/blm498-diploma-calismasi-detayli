#!/usr/bin/env bash
# setup/lib/common.sh — ortak betik kitaplığı. `source` edilmek için yazılmıştır.
# Kullanım (betik başında):  source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# Betikler kendi başına `set -Eeuo pipefail` kullanmalıdır (ERR tuzağı için -E gerekir).

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Bu dosya doğrudan çalıştırılmaz; bir kurulum betiğinden 'source' edilir." >&2
    echo "Örnek: source setup/lib/common.sh" >&2
    exit 1
fi

# --- Sayı biçimi --------------------------------------------------------------
# Yalnız LC_NUMERIC sabitlenir (LANG ve diğer LC_* dokunulmaz: ön kontrol LANG'i denetler, ileti dili değişmesin).
# Neden: ondalık ayracı yerel ayara bağlıdır. tr_TR'de bash EPOCHREALTIME "123,456" verir, `printf %f 1.5` hata verir,
# mawk "1.5"i 1 diye okur (tc çıktılarındaki "1.5Mbit" yanlış ayrıştırılır). LC_NUMERIC=C hepsini noktalı sayıya sabitler.
export LC_NUMERIC=C

# --- Yollar ------------------------------------------------------------------
COMMON_SH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_DIR="$(dirname "$COMMON_SH_DIR")"
ROOT_DIR="$(dirname "$SETUP_DIR")"
GENERATED_DIR="$ROOT_DIR/.generated"
LOG_DIR="$GENERATED_DIR/logs"

# Root ise hiçbir dosya/klasör oluşturulmaz (root sahipli .generated/ oluşmasın).
SCRIPT_NAME="$(basename "$0" .sh)"
if [[ "$(id -u)" -eq 0 ]]; then
    LOG_FILE="/dev/null"
else
    mkdir -p "$LOG_DIR"
    LOG_FILE="$LOG_DIR/${SCRIPT_NAME}_$(date +%Y%m%d_%H%M%S).log"
    : > "$LOG_FILE"
fi

# --- Renk: yalnız terminal ise ----------------------------------------------
if [[ -t 1 ]]; then
    C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[36m'; C_OFF=$'\033[0m'
else
    C_GREEN=""; C_RED=""; C_YELLOW=""; C_BLUE=""; C_OFF=""
fi

# --- Sayaçlar ----------------------------------------------------------------
COUNT_OK=0
COUNT_FAIL=0
COUNT_WARN=0

_log() { # _log <renk> <simge> <ileti...>
    local color="$1" sym="$2"; shift 2
    printf '%s%s%s %s\n' "$color" "$sym" "$C_OFF" "$*"
    printf '%s %s\n' "$sym" "$*" >> "$LOG_FILE"
}
log_ok()   { COUNT_OK=$((COUNT_OK + 1));     _log "$C_GREEN"  "(+)" "$*"; }
log_fail() { COUNT_FAIL=$((COUNT_FAIL + 1)); _log "$C_RED"    "(-)" "$*"; }
log_warn() { COUNT_WARN=$((COUNT_WARN + 1)); _log "$C_YELLOW" "(!)" "$*"; }
log_info() { _log "$C_BLUE" "(i)" "$*"; }

print_summary() {
    local line="Özet: ${COUNT_OK} başarılı, ${COUNT_FAIL} başarısız, ${COUNT_WARN} uyarı"
    printf '%s\n' "$line"
    printf '%s\n' "$line" >> "$LOG_FILE"
    log_info "Günlük dosyası: $LOG_FILE"
    [[ "$COUNT_FAIL" -eq 0 ]]
}

# check <açıklama> <komut...> : başarılıysa (+), değilse (-); betiği durdurmaz.
check() {
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then log_ok "$desc"; else log_fail "$desc"; fi
    return 0
}

# check_warn <açıklama> <komut...> : başarılıysa (+), değilse (!) uyarı; betiği durdurmaz.
check_warn() {
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then log_ok "$desc"; else log_warn "$desc"; fi
    return 0
}

# --- Yardımcılar -------------------------------------------------------------
have_cmd() { command -v "$1" >/dev/null 2>&1; }

require_not_root() {
    if [[ "$(id -u)" -eq 0 ]]; then
        log_fail "Betik root olarak çalıştırılmamalı; normal kullanıcıyla çalıştırın (gerekince kendi içinde sudo çağırır)."
        exit 1
    fi
}

# version_ge a b : a >= b ise 0 (ör. 13.2 >= 13.0)
version_ge() {
    [[ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | sed -n 1p)" == "$2" ]]
}

# cpulist_expand <cpulist> : Linux cpulist (ör. "0-1", "0,16") değerini virgülle ayrılmış
# tam listeye açar. Tam 2 üyeli ise "a,b" yazar (dönüş 0). 3+ üye ise tam listeyi yazar ve
# 2 döndürür (çağıran uyarı verir). Tek üye ise o sayıyı yazar (dönüş 0).
cpulist_expand() {
    local list="$1" part lo hi i
    local -a nums=()
    local IFS=','
    for part in $list; do
        if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
            lo="${BASH_REMATCH[1]}"; hi="${BASH_REMATCH[2]}"
            for ((i = lo; i <= hi; i++)); do nums+=("$i"); done
        elif [[ "$part" =~ ^[0-9]+$ ]]; then
            nums+=("$part")
        else
            return 1
        fi
    done
    printf '%s\n' "${nums[*]}"
    [[ "${#nums[@]}" -le 2 ]] || return 2
}

load_versions() {
    local f="$SETUP_DIR/versions.env"
    if [[ ! -f "$f" ]]; then
        log_fail "Sürüm dosyası bulunamadı: $f"
        exit 1
    fi
    # shellcheck disable=SC1090
    source "$f"
}

# write_env_kv KEY VALUE FILE : anahtarı günceller veya ekler (idempotent).
# Değer çift tırnak içine yazılır; \ " $ ` kaçışlanır, böylece source güvenlidir.
write_env_kv() {
    local key="$1" value="$2" file="$3" esc
    esc="${value//\\/\\\\}"; esc="${esc//\"/\\\"}"; esc="${esc//\$/\\\$}"; esc="${esc//\`/\\\`}"
    [[ -f "$file" ]] || : > "$file"
    local tmp
    tmp="$(mktemp "${file}.XXXXXX")"
    KV_KEY="$key" KV_LINE="${key}=\"${esc}\"" awk '
        BEGIN { k = ENVIRON["KV_KEY"] "="; line = ENVIRON["KV_LINE"]; done = 0 }
        index($0, k) == 1 { if (!done) { print line; done = 1 } ; next }
        { print }
        END { if (!done) print line }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

# --- Python kilit dosyaları (FR-31) -------------------------------------------
# freeze_pkgs <python> <çıktı> : venv paketlerini (editable hariç) sıralı biçimde yazar. Kilidi DEĞİL, çıktıyı üretir.
freeze_pkgs() {
    local py="$1" out="$2"
    mkdir -p "$(dirname "$out")"
    "$py" -m pip freeze --local --exclude-editable | LC_ALL=C sort -f > "$out.tmp"
    mv "$out.tmp" "$out"
}

# lock_report <ad> <kilit> <freeze> : kilitle venv freeze'ini karşılaştırır. Aynıysa (+); farklıysa (!) ile satır satır
# fark yazar ('<' kilitte olup venv'de olmayan/farklı, '>' venv'de olup kilitte olmayan/farklı). Başarısız SAYMAZ.
lock_report() {
    local name="$1" lock="$2" frz="$3" d line
    if [[ ! -f "$lock" ]]; then
        log_warn "$name: kilit dosyası yok (${lock#"$ROOT_DIR"/}); karşılaştırılamadı"
        return 0
    fi
    d="$(diff "$lock" "$frz" || true)"
    if [[ -z "$d" ]]; then
        log_ok "$name kilitle birebir aynı ($(wc -l < "$lock") paket)"
    else
        log_warn "$name kilitten FARKLI (kurulum başarısız sayılmaz; '<' kilit, '>' venv):"
        while IFS= read -r line; do
            if [[ "$line" == "<"* || "$line" == ">"* ]]; then log_warn "  $line"; fi
        done <<< "$d"
    fi
    return 0
}

# --- Betik sözleşmesi: argümanlar, run/sudo_run, bileşen satırı --------------
MODE="install"
DRY_RUN=0
COMPONENT_NAME=""
COMPONENT_FINAL=0
SUDO_KEEPALIVE_PID=""
APT_UPDATED=0

# Betiğin başındaki açıklama yorumunu (2. satırdan ilk yorum olmayan satıra kadar) yazar.
print_help() {
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

# parse_common_args "$@" : MODE (install|verify) ve DRY_RUN (0|1) ayarlar.
parse_common_args() {
    MODE="install"; DRY_RUN=0
    local a
    for a in "$@"; do
        case "$a" in
            --dry-run) DRY_RUN=1 ;;
            --verify)  MODE="verify" ;;
            -h|--help) print_help; exit 0 ;;
            *) echo "Bilinmeyen argüman: $a" >&2
               echo "Kullanım: ${0##*/} [--dry-run | --verify | -h]" >&2
               exit 2 ;;
        esac
    done
}

_write_result() { # _write_result <ok|fail|dry> <ad>
    if [[ -n "${COMPONENT_RESULT_FILE:-}" ]]; then
        printf '%s\t%s\n' "$1" "$2" >> "$COMPONENT_RESULT_FILE"
    fi
    return 0
}

# component_done <ad> [ifade] : sözleşmenin son satırı (başarı).
component_done() {
    local name="$1" text="${2:-}"
    COMPONENT_FINAL=1
    if [[ -z "$text" ]]; then
        if [[ "$MODE" == "verify" ]]; then text="doğrulandı"
        elif [[ "$DRY_RUN" -eq 1 ]]; then text="dry-run tamamlandı (hiçbir şey değiştirilmedi)"
        else text="başarıyla kuruldu ve yapılandırıldı"; fi
    fi
    log_ok "$name $text"
    _write_result ok "$name"
}

component_failed() {
    COMPONENT_FINAL=1
    log_fail "$1 BAŞARISIZ"
    _write_result fail "$1"
}

# component_finish <ad> [ifade] : özet + son satır; çıkış 0 (başarı) / 1 (başarısız).
component_finish() {
    local name="$1" text="${2:-}" rc=0
    print_summary || true
    if [[ "$COUNT_FAIL" -eq 0 ]]; then
        component_done "$name" "$text"
    else
        component_failed "$name"; rc=1
    fi
    exit "$rc"
}

# run <açıklama> <komut...> : dry-run'da yalnız yazar; aksi halde çalıştırır, hatada betiği 1 ile bitirir.
run() {
    local desc="$1"; shift
    local shown
    shown="$(printf '%q ' "$@")"; shown="${shown% }"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] $shown"
        return 0
    fi
    log_info "$desc"
    printf '+ %s\n' "$shown" >> "$LOG_FILE"
    if "$@" 2>&1 | tee -a "$LOG_FILE"; then
        return 0
    else
        local rc="${PIPESTATUS[0]}"
        log_fail "Komut başarısız (çıkış kodu $rc): $shown"
        component_failed "${COMPONENT_NAME:-$SCRIPT_NAME}"
        exit 1
    fi
}

sudo_run() { # sudo_run <açıklama> <komut...>
    local desc="$1"; shift
    run "$desc" sudo "$@"
}

apt_pkg_installed() {
    local st; st="$(dpkg-query -W -f='${Status}' "$1" 2>/dev/null || true)"
    # apt-mark hold'lu paketlerin durumu "hold ok installed" olur; onlar da kuruludur
    [[ "$st" == "install ok installed" || "$st" == "hold ok installed" ]]
}

# apt_ensure <paket...> : eksikleri kurar (ilk çağrıda bir kez apt-get update).
apt_ensure() {
    local pkg
    local -a missing=()
    for pkg in "$@"; do
        apt_pkg_installed "$pkg" || missing+=("$pkg")
    done
    if [[ "${#missing[@]}" -eq 0 ]]; then
        log_ok "Paketler zaten kurulu: $*"
        return 0
    fi
    log_info "Eksik paketler (${#missing[@]}): ${missing[*]}"
    if [[ "$APT_UPDATED" -eq 0 ]]; then
        sudo_run "Paket dizinleri güncelleniyor" apt-get update
        APT_UPDATED=1
    fi
    sudo_run "Paketler kuruluyor: ${missing[*]}" apt-get install -y --no-install-recommends "${missing[@]}"
}

# sudo_keepalive_start/stop : sudo -v (şifre bir kez) ve 50 sn'de bir sudo -n -v.
sudo_keepalive_start() {
    [[ "$DRY_RUN" -eq 1 ]] && return 0
    log_info "sudo yetkisi isteniyor (şifre bir kez sorulur)"
    if ! sudo -v; then
        log_fail "sudo yetkisi alınamadı"
        exit 1
    fi
    local parent=$$
    ( while kill -0 "$parent" 2>/dev/null; do sleep 50; sudo -n -v 2>/dev/null || exit 0; done ) &
    SUDO_KEEPALIVE_PID=$!
    disown "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
}

sudo_keepalive_stop() {
    if [[ -n "$SUDO_KEEPALIVE_PID" ]]; then
        pkill -P "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
        kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
        SUDO_KEEPALIVE_PID=""
    fi
    return 0
}

# --- Çalıştırıcılar için adım listesi ve tablo -------------------------------
RESULT_TMP=""      # run_steps'in geçici sonuç dosyası (çıkışta temizlenir)
REPORT_TMP=""      # lib/rapor.sh'in geçici rapor dosyası (çıkışta temizlenir)
STEP_FILES=()      # setup/NN_*.sh (ada göre sıralı)
SELECTED_FILES=()  # çalıştırılacaklar
RES_NUM=(); RES_NAME=(); RES_SYM=(); RES_SECS=()

discover_steps() {
    STEP_FILES=()
    local f
    for f in "$SETUP_DIR"/[0-9][0-9]_*.sh; do
        [[ -e "$f" ]] && STEP_FILES+=("$f")
    done
    return 0
}

step_num() { local b; b="$(basename "$1")"; echo "${b:0:2}"; }

# run_steps <failfast 0|1> <betik argümanları...> : SELECTED_FILES'ı sırayla çalıştırır.
run_steps() {
    local failfast="$1"; shift
    local f n b name sym secs t0 rc stop=0 rf
    RES_NUM=(); RES_NAME=(); RES_SYM=(); RES_SECS=()
    rf="$(mktemp)"
    RESULT_TMP="$rf"   # Ctrl-C/hata çıkışında _on_exit siler
    export COMPONENT_RESULT_FILE="$rf"
    for f in "${SELECTED_FILES[@]}"; do
        n="$(step_num "$f")"; b="$(basename "$f" .sh)"; name="${b:3}"
        if [[ "$stop" -eq 1 ]]; then
            sym="(–)"; secs="-"
        else
            : > "$rf"
            log_info "=== Adım $n: $(basename "$f") ==="
            t0=$SECONDS; rc=0
            bash "$f" "$@" || rc=$?
            secs="$((SECONDS - t0)) sn"
            if [[ -s "$rf" ]]; then name="$(tail -n1 "$rf" | cut -f2)"; fi
            if [[ "$rc" -eq 0 ]]; then
                sym="(+)"
            else
                sym="(-)"
                if [[ "$failfast" -eq 1 ]]; then stop=1; fi
            fi
        fi
        RES_NUM+=("$n"); RES_NAME+=("$name"); RES_SYM+=("$sym"); RES_SECS+=("$secs")
    done
    rm -f "$rf"
    RESULT_TMP=""
    unset COMPONENT_RESULT_FILE
    return 0
}

# print_steps_table <toplam_sn> : tabloyu yazar; herhangi biri (-) ise 1 döndürür.
print_steps_table() {
    local total="$1" i bad=0 pad
    for i in "${!RES_SYM[@]}"; do
        if [[ "${RES_SYM[$i]}" == "(-)" ]]; then bad=1; fi
    done
    {
        echo
        echo "NN  Bileşen                       Sonuç  Süre"
        echo "--  ----------------------------  -----  ------"
        for i in "${!RES_NUM[@]}"; do
            pad=$((28 - ${#RES_NAME[$i]})); [[ "$pad" -lt 1 ]] && pad=1
            printf '%s  %s%*s  %-5s  %s\n' "${RES_NUM[$i]}" "${RES_NAME[$i]}" "$pad" "" "${RES_SYM[$i]}" "${RES_SECS[$i]}"
        done
        echo
        echo "Toplam süre: ${total} sn"
    } | tee -a "$LOG_FILE"
    return "$bad"
}

# --- Dinleyen port denetimi (test betikleri) ----------------------------------
# Test, çalıştırmadan önce ve sonra dinleyen portları karşılaştırır. Makine geneli karşılaştırma, testten bağımsız süreçlerin (ör. kullanıcının tarayıcısı) açtığı
# UDP/TCP portlarını yanlış alarm olarak yakalıyordu. Bu yüzden yalnız sahibi ilk anlık görüntüden SONRA başlamış süreçlerin (testin/koşunun başlattığı süreçlerin)
# yeni portları sayılır; ilk anlık görüntüden önce var olan bir sürecin sonradan açtığı port sayılmaz. Sahibi görünmeyen soket (başka kullanıcı) sayılmaz.
# port_snapshot <dosya> : ilk satır "#epoch <şimdi>", sonra sıralı "proto adres sahip_süreç_başlangıç_epoch" satırları (sahip görünmüyorsa "-").
port_snapshot() {
    local dosya="$1" simdi
    simdi="$(date +%s)"
    echo "#epoch $simdi" > "$dosya"
    LC_ALL=C awk -v simdi="$simdi" 'NR == FNR { gecen[$1] = $2; next }
        { pid = ""; if (match($0, /pid=[0-9]+/)) pid = substr($0, RSTART + 4, RLENGTH - 4)
          print $1, $5, ((pid != "" && (pid in gecen)) ? simdi - gecen[pid] : "-") }' \
        <(ps -eo pid=,etimes= 2>/dev/null || true) <(ss -lntupH 2>/dev/null || true) | LC_ALL=C sort -u >> "$dosya" || true
}

# port_yeni <önce_dosya> <sonra_dosya> : "sonra"da olup "önce"de olmayan, sahibi "önce" anından sonra (1 sn payla) başlamış sürecin portlarını "proto adres;" biçiminde yazar (yoksa boş).
port_yeni() {
    local once="$1" sonra="$2" sinir
    sinir="$(awk '/^#epoch / {print $2; exit}' "$once")"
    LC_ALL=C comm -13 <(awk '!/^#/ {print $1, $2}' "$once" | LC_ALL=C sort -u) \
        <(awk -v s="${sinir:-0}" '!/^#/ && $3 != "-" && $3 + 1 >= s {print $1, $2}' "$sonra" | LC_ALL=C sort -u) | tr '\n' ';' || true
}

# --- Hata yakalama -----------------------------------------------------------
_on_err() {
    local rc="$1" line="$2" src="$3" cmd="$4"
    log_fail "Beklenmeyen hata (çıkış kodu ${rc}): ${src##*/}:${line} -> ${cmd}"
}
trap '_on_err "$?" "$LINENO" "${BASH_SOURCE[0]}" "$BASH_COMMAND"' ERR

# Çıkışta: sudo canlı tutma döngüsünü öldür; bileşen satırı yazılmadan hatayla çıkıldıysa BAŞARISIZ yaz.
_on_exit() {
    local rc="$1"
    sudo_keepalive_stop
    if [[ -n "$RESULT_TMP" ]]; then rm -f "$RESULT_TMP"; fi
    if [[ -n "$REPORT_TMP" ]]; then rm -f "$REPORT_TMP"; fi
    if declare -F exit_hook >/dev/null; then exit_hook || true; fi   # betik isteğe bağlı temizlik işlevi tanımlayabilir
    if [[ -n "$COMPONENT_NAME" && "$COMPONENT_FINAL" -eq 0 && "$rc" -ne 0 && "$rc" -ne 2 ]]; then
        component_failed "$COMPONENT_NAME"
    fi
    return 0
}
trap '_on_exit "$?"' EXIT
