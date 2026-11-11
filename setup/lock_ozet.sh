#!/usr/bin/env bash
# lock_ozet.sh — ortam kilidi özeti (FR-31): kilitli dosyaların SHA-256 listesini setup/locks/sha256sums.txt dosyasına yazar / denetler.
# Kullanım: ./lock_ozet.sh [--dry-run | --check | -h]
#   (argümansız)  listeyi üretir/günceller (aynı girdi → bayt bayt aynı çıktı; tarih/makine adı yok); sonda doğrular
#   --dry-run     hiçbir şey yazmaz; neyin yazılacağını söyler
#   --check       yalnız denetim (--verify ile aynı): her özeti doğrular, fark/eksik/fazla dosyaları (-) ile yazar; fark varsa çıkış 1
# Kapsam: setup/versions.env, config/deney.env, setup/*.sh, setup/lib/*.sh, setup/locks/*.txt (sha256sums.txt hariç).
# PX4 etiketi+commit özeti setup/locks/px4-commit.txt içindedir ve bu sayede kapsanır.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

ARGS=()
for a in "$@"; do
    if [[ "$a" == "--check" ]]; then ARGS+=("--verify"); else ARGS+=("$a"); fi
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
COMPONENT_NAME="Ortam kilidi özeti"
require_not_root

LOCK_FILE="$SETUP_DIR/locks/sha256sums.txt"
LOCK_REL="${LOCK_FILE#"$ROOT_DIR"/}"
GEN_TMP=""
exit_hook() { if [[ -n "$GEN_TMP" ]]; then rm -f "$GEN_TMP"; fi; }

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

# Kapsamdaki dosyalar: ROOT_DIR'e göre yollar, C yerel ayarında sıralı, tekrarsız
list_files() {
    (
        cd "$ROOT_DIR"
        shopt -s nullglob
        local f
        for f in setup/versions.env config/deney.env setup/*.sh setup/lib/*.sh setup/locks/*.txt; do
            [[ "$f" == "$LOCK_REL" ]] && continue
            [[ -f "$f" ]] && printf '%s\n' "$f"
        done | LC_ALL=C sort -u
    )
}

# generate <hedef_dosya> : sha256sum uyumlu liste
generate() {
    local -a files
    mapfile -t files < <(list_files)
    [[ "${#files[@]}" -gt 0 ]] || fail_stop "Kapsamda dosya bulunamadı"
    (cd "$ROOT_DIR" && sha256sum -- "${files[@]}") > "$1"
}

install_component() {
    local n; n="$(list_files | wc -l)"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] $n dosyanın SHA-256 özeti → $LOCK_REL (yazılmadı)"
        return 0
    fi
    mkdir -p "$(dirname "$LOCK_FILE")"
    GEN_TMP="$(mktemp "$LOCK_FILE.XXXXXX")"
    generate "$GEN_TMP"
    if [[ -f "$LOCK_FILE" ]] && cmp -s "$GEN_TMP" "$LOCK_FILE"; then
        log_ok "$LOCK_REL zaten güncel ($n dosya)"
        rm -f "$GEN_TMP"
    else
        mv "$GEN_TMP" "$LOCK_FILE"
        log_ok "$LOCK_REL yazıldı ($n dosya)"
    fi
    GEN_TMP=""
}

verify_component() {
    if [[ ! -f "$LOCK_FILE" ]]; then
        log_fail "$LOCK_REL yok (önce ./setup/lock_ozet.sh çalıştırılmalı)"
        return 0
    fi
    local out line bad=0 listed now
    out="$(cd "$ROOT_DIR" && sha256sum -c -- "$LOCK_REL" 2>&1 || true)"
    while IFS= read -r line; do
        case "$line" in
            *": OK") ;;
            *": FAILED open or read") log_fail "Dosya yok/okunamadı: ${line%%: FAILED*}"; bad=1 ;;
            *": FAILED") log_fail "Özet farklı: ${line%%: FAILED}"; bad=1 ;;
            "") ;;
            sha256sum:*) ;;   # özet cümlesi (WARNING: ...) aşağıda ele alınır
        esac
    done <<< "$out"
    # Listede olup diskte olmayan / diskte olup listede olmayan dosyalar
    listed="$(awk '{ print $2 }' "$LOCK_FILE" | LC_ALL=C sort -u)"
    now="$(list_files)"
    while IFS= read -r line; do
        [[ -n "$line" ]] && { log_fail "Kapsamda ama listede yok (yeni/eklenmiş dosya): $line"; bad=1; }
    done < <(LC_ALL=C comm -13 <(printf '%s\n' "$listed") <(printf '%s\n' "$now"))
    if [[ "$bad" -eq 0 ]]; then
        log_ok "Ortam kilidi doğrulandı: $(wc -l < "$LOCK_FILE") dosyanın SHA-256 özeti eşleşiyor"
    fi
}

if [[ "$MODE" == "install" ]]; then
    install_component
fi
if [[ "$MODE" == "verify" || "$DRY_RUN" -eq 0 ]]; then
    verify_component
fi
component_finish "$COMPONENT_NAME"
