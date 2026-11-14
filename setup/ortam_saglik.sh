#!/usr/bin/env bash
# ortam_saglik.sh — tek komutla ortamın "sağlam mı?" özeti (salt okunur, sudo gerektirmez).
# Kullanım: ./ortam_saglik.sh [--dry-run | --verify | -h]
#   (argümansız)  --verify ile aynı
#   --dry-run     hiçbir kontrol çalıştırmaz; ne denetleyeceğini yazar
# Denetimler: (a) çalışan/kurulu en yeni çekirdek ve reboot-required, (b) apt_kilit.sh --verify (hold durumu), (c) ortam_kaydi.sh fark özeti,
# (d) lock_ozet.sh --check, (e) nvidia-smi ve CUDA (versions.env), (f) artık süreçler (px4, gz, mavsdk_server, ruby, ros2 daemon),
# (g) lo üzerinde sürü adresleri ve tc sınıfı/süzgeçleri, (h) boş disk, (i) git: temiz mi, push edilmemiş commit sayısı.
# Hata (-): kilit eksik, lock_ozet farkı, GPU/sürücü sorunu, artık süreç, sürü ağı yok, disk yetersiz. Uyarı (!): yeniden başlatma bekliyor,
# push edilmemiş commit, apt kayıt farkı, kirli çalışma ağacı. Çıktının sonunda tek satır özet vardır. Bu betik install_all.sh /
# verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz).
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/ortam.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/ortam.sh"
parse_common_args "$@"
COMPONENT_NAME="Ortam sağlık kontrolü"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
# Alt betik çıktıları .generated/ altında sabit klasörde tutulur ve her çalıştırmada üzerine yazılır (silme/rm yok)
WORK="$GENERATED_DIR/ortam_saglik_gecici"
mkdir -p "$WORK"

strip_colors() { sed 's/\x1b\[[0-9;]*m//g'; }

print_plan() {
    log_info "[dry-run] (a) uname -r ve dpkg'deki en yeni linux-image; /var/run/reboot-required"
    log_info "[dry-run] (b) setup/apt_kilit.sh --verify (hold durumu, otomatik güncelleme)"
    log_info "[dry-run] (c) setup/ortam_kaydi.sh (apt kaydı fark özeti)"
    log_info "[dry-run] (d) setup/lock_ozet.sh --check"
    log_info "[dry-run] (e) nvidia-smi: sürücü ve CUDA (CUDA_MIN=${CUDA_MIN:-?}), compute süreçleri"
    log_info "[dry-run] (f) artık süreçler: px4 gz mavsdk_server ruby, ros2 daemon"
    log_info "[dry-run] (g) lo: sürü adresleri ve çoklu yayın süzgeci, tc htb sınıfı 1:10 ve süzgeçler"
    log_info "[dry-run] (h) boş disk (MIN_FREE_DISK_GIB=${MIN_FREE_DISK_GIB:-?}); (i) git: temiz mi, push edilmemiş commit sayısı"
    log_info "[dry-run] Hiçbir kontrol çalıştırılmadı"
}
if [[ "$DRY_RUN" -eq 1 ]]; then
    print_plan
    component_finish "$COMPONENT_NAME"
fi

# --- (a) çekirdek ---------------------------------------------------------------------
kontrol_cekirdek() {
    local calisan yeni
    calisan="$(uname -r)"
    yeni="$(ortam_en_yeni_cekirdek)"
    if [[ -n "$yeni" && "$yeni" != "$calisan" ]]; then
        log_warn "(a) Yeniden başlatma bekliyor: çalışan çekirdek $calisan, kurulu en yeni $yeni"
    else
        log_ok "(a) Çalışan çekirdek $calisan kurulu en yeniyle aynı"
    fi
    if [[ -f /var/run/reboot-required ]]; then
        log_warn "(a) /var/run/reboot-required var (paketler: $(sort -u /var/run/reboot-required.pkgs 2>/dev/null | head -n 4 | tr '\n' ' '))"
    else
        log_ok "(a) reboot-required yok"
    fi
}

# --- (b) apt kilidi ----------------------------------------------------------------------
kontrol_apt_kilit() {
    local out="$WORK/apt_kilit.txt" rc=0 satir metin
    "$SETUP_DIR/apt_kilit.sh" --verify > "$out" 2>&1 || rc=$?
    satir="$(strip_colors < "$out" | grep -E 'Kilit kümesi' | sed -n 1p | sed 's/^([^)]*) //; s/ (kurulu paketlerden, çalışma anında)//' || true)"
    if [[ "$rc" -eq 0 ]]; then
        log_ok "(b) apt kilidi: $satir"
    else
        log_fail "(b) apt kilidi eksik: $satir (ayrıntı ve kilitleme: ./setup/apt_kilit.sh --verify / --kilitle)"
    fi
    metin="$(strip_colors < "$out")"   # önce değişkene: grep -q + pipefail → SIGPIPE tuzağı olmasın
    if grep -qE '^\(!\).*(AÇIK|Unattended-Upgrade "1")' <<< "$metin"; then
        log_warn "(b) otomatik güncelleme ayarı/zamanlayıcısı açık görünüyor (ayrıntı: ./setup/apt_kilit.sh --verify)"
    fi
}

# --- (c) apt kaydı farkı ------------------------------------------------------------------
kontrol_ortam_kaydi() {
    local out="$WORK/ortam_kaydi.txt" satir metin
    "$SETUP_DIR/ortam_kaydi.sh" > "$out" 2>&1 || true
    metin="$(strip_colors < "$out")"   # önce değişkene: grep -q + pipefail → SIGPIPE tuzağı olmasın
    satir="$(grep -E 'apt kaydından FARKLI|apt kaydı' <<< "$metin" | sed -n 1p || true)"
    if grep -q 'apt kaydından FARKLI' <<< "$metin"; then
        log_warn "(c) apt kaydı farkı: ${satir#*) }"
    elif [[ -z "$satir" ]] && grep -qE '^\(-\)' <<< "$metin"; then
        log_fail "(c) ortam_kaydi.sh hata verdi: $(grep -E '^\(-\)' <<< "$metin" | sed -n 1p | cut -c1-160)"
    else
        log_ok "(c) apt kaydı güncel"
    fi
}

# --- (d) lock_ozet -------------------------------------------------------------------------
kontrol_lock_ozet() {
    local out="$WORK/lock_ozet.txt" rc=0
    "$SETUP_DIR/lock_ozet.sh" --check > "$out" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then
        log_ok "(d) lock_ozet --check: ortam kilidi özeti güncel"
    else
        log_fail "(d) lock_ozet --check fark buldu: $(strip_colors < "$out" | grep -E '^\(-\)|farklı|FARKLI' | sed -n 1,3p | tr '\n' ' ' | cut -c1-200) (ayrıntı: ./setup/lock_ozet.sh --check)"
    fi
}

# --- (e) NVIDIA ----------------------------------------------------------------------------
kontrol_nvidia() {
    local drv cuda apps ad
    if ! have_cmd nvidia-smi; then log_fail "(e) nvidia-smi bulunamadı"; return 0; fi
    drv="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | sed -n 1p || true)"
    ad="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | sed -n 1p || true)"
    cuda="$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: *\([0-9][0-9.]*\).*/\1/p' | sed -n 1p || true)"
    if [[ -z "$drv" ]]; then log_fail "(e) nvidia-smi çalışmıyor (sürücü yanıt vermiyor)"; return 0; fi
    if [[ -n "$cuda" ]] && version_ge "$cuda" "$CUDA_MIN"; then
        log_ok "(e) nvidia-smi çalışıyor: $ad, sürücü $drv, CUDA $cuda (≥ $CUDA_MIN)"
    else
        log_fail "(e) CUDA sürümü beklenenin altında/okunamadı: '${cuda:-yok}' (gerekli ≥ $CUDA_MIN)"
    fi
    if [[ -f "$SETUP_DIR/locks/nvidia-cuda.txt" ]]; then
        local kayit; kayit="$(sed -n 1p "$SETUP_DIR/locks/nvidia-cuda.txt")"
        if [[ "$kayit" != "sürücü=$drv cuda=$cuda" ]]; then log_warn "(e) sürücü/CUDA kayıttan farklı: kayıt '$kayit', şimdi 'sürücü=$drv cuda=$cuda'"; fi
    fi
    apps="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | wc -l || true)"
    if [[ "${apps:-0}" -gt 0 ]]; then log_info "(e) GPU'da şu an $apps compute süreci var"; fi
}

# --- (f) artık süreçler -----------------------------------------------------------------------
kontrol_surecler() {
    local c n ps temiz=1
    for c in px4 gz mavsdk_server ruby; do
        n="$(pgrep -x -c "$c" || true)"
        if [[ "${n:-0}" -gt 0 ]]; then
            ps="$(pgrep -x "$c" | tr '\n' ' ')"
            log_fail "(f) artık süreç: $c ($n adet: $ps)"; temiz=0
        fi
    done
    if pgrep -f '[r]os2-daemon' >/dev/null; then
        log_fail "(f) artık ros2 daemon süreci var (ölçülen ağa trafik basar; ros2 daemon stop)"; temiz=0
    fi
    if [[ "$temiz" -eq 1 ]]; then log_ok "(f) artık süreç yok (px4, gz, mavsdk_server, ruby, ros2 daemon)"; fi
}

# --- (g) sürü ağı (hafif kontrol; ayrıntılı sınama: ./setup/60_ag_emulasyon_tc.sh --verify) -----------
kontrol_ag() {
    local a eksik="" out t ok=1
    if [[ ! -f "$DENEY_ENV" ]]; then log_fail "(g) $DENEY_ENV yok"; return 0; fi
    # shellcheck source=/dev/null
    source "$DENEY_ENV"
    out="$(ip -4 -o addr show dev lo 2>/dev/null || true)"
    for a in "$UAV1_ADDR" "$UAV2_ADDR" "$UAV3_ADDR" "$GCS_ADDR"; do
        [[ "$out" == *" $a/32"* ]] || eksik+="$a "
    done
    if [[ -n "$eksik" ]]; then log_fail "(g) lo üzerinde sürü adresi yok: $eksik(./setup/60_ag_emulasyon_tc.sh gerekir)"; ok=0; fi
    t="$(tc qdisc show dev lo 2>/dev/null || true)"
    if [[ "$t" != *"qdisc htb 1:"* ]]; then log_fail "(g) lo üzerinde htb kök kuyruk yok"; ok=0; fi
    t="$(tc class show dev lo 2>/dev/null || true)"
    if [[ "$t" != *"class htb 1:10 "* ]]; then log_fail "(g) tc sınıfı 1:10 (sınırlayıcı) yok"; ok=0; fi
    t="$(tc filter show dev lo parent 1: 2>/dev/null || true)"
    if [[ "$(grep -c 'flowid 1:10' <<< "$t" || true)" -lt 2 ]]; then log_fail "(g) tc süzgeçleri eksik (sürü ağı ve çoklu yayın → 1:10 beklenir)"; ok=0; fi
    if [[ "$ok" -eq 1 ]]; then log_ok "(g) lo: 4 sürü adresi, htb 1:10 sınıfı ve iki süzgeç (sürü ağı + $DDS_MCAST_ADDR) var"; fi
}

# --- (h) disk ----------------------------------------------------------------------------------
kontrol_disk() {
    local bos
    bos="$(df -BG --output=avail "$ROOT_DIR" 2>/dev/null | tail -n 1 | tr -dc '0-9' || true)"
    if [[ -z "$bos" ]]; then log_warn "(h) boş disk okunamadı"; return 0; fi
    if [[ "$bos" -ge "$MIN_FREE_DISK_GIB" ]]; then
        log_ok "(h) boş disk ${bos} GiB (≥ $MIN_FREE_DISK_GIB)"
    else
        log_fail "(h) boş disk ${bos} GiB (< $MIN_FREE_DISK_GIB)"
    fi
}

# --- (i) git --------------------------------------------------------------------------------------
kontrol_git() {
    local kirli up n dal
    if ! git -C "$ROOT_DIR" rev-parse --git-dir >/dev/null 2>&1; then log_warn "(i) git deposu değil"; return 0; fi
    dal="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
    kirli="$(git -C "$ROOT_DIR" status --porcelain 2>/dev/null | wc -l || true)"
    if [[ "${kirli:-0}" -eq 0 ]]; then
        log_ok "(i) git: çalışma ağacı temiz (dal $dal)"
    else
        log_warn "(i) git: çalışma ağacında $kirli değişiklik/izlenmeyen dosya var (dal $dal)"
    fi
    up="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref '@{u}' 2>/dev/null || true)"
    if [[ -z "$up" ]]; then
        log_warn "(i) git: yukarı akış (upstream) tanımlı değil; push durumu belirlenemedi"
    else
        n="$(git -C "$ROOT_DIR" rev-list --count '@{u}..HEAD' 2>/dev/null || echo '?')"
        if [[ "$n" == "0" ]]; then
            log_ok "(i) git: $up ile aynı; push edilmemiş commit yok"
        else
            log_warn "(i) git: $n commit $up'a push edilmemiş (push'u kullanıcı kendi terminalinde yapar)"
        fi
    fi
}

kontrol_cekirdek
kontrol_apt_kilit
kontrol_ortam_kaydi
kontrol_lock_ozet
kontrol_nvidia
kontrol_surecler
kontrol_ag
kontrol_disk
kontrol_git

printf 'SAĞLIK ÖZETİ: %s (+), %s (!), %s (-)\n' "$COUNT_OK" "$COUNT_WARN" "$COUNT_FAIL"
component_finish "$COMPONENT_NAME"
