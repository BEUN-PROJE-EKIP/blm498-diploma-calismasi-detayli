#!/usr/bin/env bash
# ortam_kaydi.sh — ortam kilidinin apt/NVIDIA kaydı: kurulu bütün apt paketlerinin ve NVIDIA sürücüsü/CUDA bileşenlerinin tam sürüm listesi.
# Kullanım: ./ortam_kaydi.sh [--kaydet | --verify | --dry-run | -h]
#   --kaydet      iki dosya üretir/günceller: setup/locks/apt-surumleri.txt ("paket sürüm mimari"), setup/locks/nvidia-cuda.txt
#                 ("sürücü=… cuda=…" + nvidia/libnvidia/cuda* apt paketleri); aynı durumda bayt bayt aynı çıktı verir
#   (argümansız)  kayıtları şu anki kurulu durumla karşılaştırır (--verify ile aynı). Fark (!) ile ÖZET olarak yazılır
#                 (eklenen/kaldırılan/sürümü değişen sayısı + en çok 20 örnek) ve başarısız sayılmaz: farklı makinelerde
#                 donanım ve sürücü farkı beklenir. Kayıt dosyası yoksa (!).
#   --dry-run     ne yazacağını/karşılaştıracağını söyler, hiçbir şey yazmaz
# Kayıt yalnız izlenebilirlik içindir; apt sürümlerini sabitlemez, kurulumu kısıtlamaz. Bu betik install_all/verify_all sırasına girmez.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/ortam.sh
source "$SETUP_DIR/lib/ortam.sh"

SAVE=0
ARGS=()
for a in "$@"; do
    if [[ "$a" == "--kaydet" ]]; then SAVE=1; else ARGS+=("$a"); fi
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
if [[ "$SAVE" -eq 1 && "$MODE" == "verify" ]]; then echo "--kaydet ile --verify birlikte kullanılamaz" >&2; exit 2; fi
COMPONENT_NAME="Ortam kaydı"
require_not_root

TMP_DIR=""
exit_hook() { if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi; }
TMP_DIR="$(mktemp -d)"

have_cmd dpkg-query || { log_fail "dpkg-query bulunamadı"; component_failed "$COMPONENT_NAME"; exit 1; }

save_records() {
    local f tmp
    ortam_apt_now > "$TMP_DIR/apt.new"
    ortam_nvidia_now > "$TMP_DIR/nv.new"
    for f in apt nv; do
        local dest; if [[ "$f" == apt ]]; then dest="$ORTAM_APT_FILE"; else dest="$ORTAM_NV_FILE"; fi
        if [[ "$DRY_RUN" -eq 1 ]]; then
            log_info "[dry-run] ${dest#"$ROOT_DIR"/} yazılacaktı ($(wc -l < "$TMP_DIR/$f.new") satır; yazılmadı)"
            continue
        fi
        mkdir -p "$(dirname "$dest")"
        tmp="$dest.tmp"
        cp "$TMP_DIR/$f.new" "$tmp"; mv "$tmp" "$dest"
        log_ok "Yazıldı: ${dest#"$ROOT_DIR"/} ($(wc -l < "$dest") satır, $(wc -c < "$dest") bayt)"
    done
}

compare_apt() {
    if [[ ! -f "$ORTAM_APT_FILE" ]]; then log_warn "apt kaydı yok: ${ORTAM_APT_FILE#"$ROOT_DIR"/} (önce ./setup/ortam_kaydi.sh --kaydet)"; return 0; fi
    ortam_apt_now > "$TMP_DIR/apt.now"
    local d add rem chg line n=0
    d="$(ortam_apt_diff "$ORTAM_APT_FILE" "$TMP_DIR/apt.now")"
    if [[ -z "$d" ]]; then
        log_ok "apt kaydı güncel: $(wc -l < "$ORTAM_APT_FILE") paket, fark yok"
        return 0
    fi
    add="$(grep -c '^+' <<< "$d" || true)"; rem="$(grep -c '^-' <<< "$d" || true)"; chg="$(grep -c '^~' <<< "$d" || true)"
    log_warn "apt kaydından FARKLI (başarısız sayılmaz): $add eklenen, $rem kaldırılan, $chg sürümü değişen (kayıt: $(wc -l < "$ORTAM_APT_FILE") paket)"
    while IFS= read -r line; do
        n=$((n + 1))
        if [[ "$n" -le 20 ]]; then log_warn "  $line"; fi
    done <<< "$d"
    if [[ "$n" -gt 20 ]]; then log_warn "  … ve $((n - 20)) satır daha"; fi
}

compare_nvidia() {
    if [[ ! -f "$ORTAM_NV_FILE" ]]; then log_warn "NVIDIA/CUDA kaydı yok: ${ORTAM_NV_FILE#"$ROOT_DIR"/} (önce ./setup/ortam_kaydi.sh --kaydet)"; return 0; fi
    ortam_nvidia_now > "$TMP_DIR/nv.now"
    local d line n=0
    d="$(diff "$ORTAM_NV_FILE" "$TMP_DIR/nv.now" || true)"
    if [[ -z "$d" ]]; then
        log_ok "NVIDIA/CUDA kaydı güncel: $(sed -n 1p "$ORTAM_NV_FILE")"
        return 0
    fi
    log_warn "NVIDIA/CUDA kaydından FARKLI (başarısız sayılmaz; '<' kayıt, '>' şimdi):"
    while IFS= read -r line; do
        if [[ "$line" == "<"* || "$line" == ">"* ]]; then
            n=$((n + 1))
            if [[ "$n" -le 20 ]]; then log_warn "  $line"; fi
        fi
    done <<< "$d"
}

if [[ "$SAVE" -eq 1 ]]; then
    save_records
    if [[ "$DRY_RUN" -eq 0 ]]; then compare_apt; compare_nvidia; fi
else
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] ${ORTAM_APT_FILE#"$ROOT_DIR"/} ve ${ORTAM_NV_FILE#"$ROOT_DIR"/} şu anki kurulu durumla karşılaştırılacaktı (yazılmadı)"
    else
        compare_apt; compare_nvidia
    fi
fi
if [[ "$DRY_RUN" -eq 1 ]]; then FINISH_TEXT=""; elif [[ "$SAVE" -eq 1 ]]; then FINISH_TEXT="kaydedildi"; else FINISH_TEXT="karşılaştırıldı (fark başarısızlık sayılmaz)"; fi
component_finish "$COMPONENT_NAME" "$FINISH_TEXT"
