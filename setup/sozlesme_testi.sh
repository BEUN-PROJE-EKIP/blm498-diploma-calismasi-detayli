#!/usr/bin/env bash
# sozlesme_testi.sh — sözleşme dosyası doğrulayıcısının testi (sahne, bölge/rota, kamera kalibrasyonu, hedef listesi, koşu üst verisi, kare olay kaydı, araç durum kaydı).
# Kullanım: ./sozlesme_testi.sh [--dry-run | --verify | -h]
#   (argümansız)  geçerli örnekler doğrulayıcıdan geçmeli; config/ornek/bozuk/ altındaki her dosya beklenen nedenle reddedilmeli
#                 (beklenenler config/ornek/bozuk/beklenen.txt); hedef listesi örneği sahneden türetilenle aynı olmalı;
#                 örneklerin SHA-256'sı setup/locks/sha256sums.txt içinde olmalı. Süreç başlatmaz, hiçbir şey yazmaz (sudo gerekmez).
#   --dry-run     hiçbir doğrulayıcı çalıştırmaz; ne sınayacağını yazar
#   --verify      hafif önkoşul denetimi: python3, doğrulayıcı, örnek dosyaları ve beklenen.txt var mı
# Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz).
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
parse_common_args "$@"
COMPONENT_NAME="Sözleşme dosyası testleri"
require_not_root
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
ORNEK="$ROOT_DIR/config/ornek"
BOZUK="$ORNEK/bozuk"
BEKLENEN="$BOZUK/beklenen.txt"
LOCK="$SETUP_DIR/locks/sha256sums.txt"
GECERLI=(sahne_ornek_test.json bolge_rota_ornek.json kamera_kalibrasyon_ornek.json hedef_listesi_ornek.json kosu_ustveri_ornek.json
         kare_olay_gazebo_damga_ornek.jsonl kare_olay_yer_istasyonu_ornek.jsonl arac_durum_kaydi_ornek.jsonl kare_olay_kamera_alici_ornek.jsonl)

dogrula() { python3 -I "$DOGRULA" "$@"; }

check_prereqs() {
    local f
    check "python3 mevcut" command -v python3
    check "Doğrulayıcı: ${DOGRULA#"$ROOT_DIR"/}" test -f "$DOGRULA"
    check "config/deney.env" test -f "$ROOT_DIR/config/deney.env"
    for f in "${GECERLI[@]}"; do check "Geçerli örnek: config/ornek/$f" test -f "$ORNEK/$f"; done
    check "Bozuk örnek beklenenleri: ${BEKLENEN#"$ROOT_DIR"/}" test -f "$BEKLENEN"
}

if [[ "$MODE" == "verify" ]]; then
    check_prereqs
    component_finish "$COMPONENT_NAME"
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
    log_info "[dry-run] geçerli örnekler (${GECERLI[*]}) doğrulayıcıdan geçmeli"
    log_info "[dry-run] ${BEKLENEN#"$ROOT_DIR"/} içindeki her bozuk örnek (çıkış 1 + beklenen neden) reddedilmeli"
    log_info "[dry-run] hedef listesi örneği = --hedef-listesi-uret çıktısı; örnek dosyalarının SHA-256'sı $(basename "$LOCK") içinde olmalı"
    log_info "[dry-run] Hiçbir doğrulayıcı çalıştırılmadı"
    component_finish "$COMPONENT_NAME"
fi

check_prereqs
[[ "$COUNT_FAIL" -eq 0 ]] || { component_failed "$COMPONENT_NAME"; exit 1; }

# 1) geçerli örnekler
sahne="$ORNEK/sahne_ornek_test.json"
for f in "${GECERLI[@]}"; do
    extra=()
    [[ "$f" == hedef_listesi_ornek.json ]] && extra=(--sahne "$sahne")
    if out="$(dogrula "$ORNEK/$f" "${extra[@]+"${extra[@]}"}" 2>&1)"; then
        log_ok "Geçerli örnek geçti: $f ($(tail -n 1 <<< "$out"))"
    else
        log_fail "Geçerli örnek REDDEDİLDİ: $f"
        while IFS= read -r l; do log_info "  | $l"; done <<< "$out"
    fi
done

# 2) bozuk örnekler: reddedilmeli ve beklenen nedeni içermeli
n_bozuk=0
while IFS='|' read -r dosya neden ek; do
    dosya="$(sed 's/^[[:space:]]*//; s/[[:space:]]*$//' <<< "$dosya")"
    neden="$(sed 's/^[[:space:]]*//; s/[[:space:]]*$//' <<< "$neden")"
    ek="$(sed 's/^[[:space:]]*//; s/[[:space:]]*$//' <<< "${ek:-}")"
    [[ -n "$dosya" && "$dosya" != \#* ]] || continue
    n_bozuk=$((n_bozuk + 1))
    [[ -f "$BOZUK/$dosya" ]] || { log_fail "Bozuk örnek dosyası yok: $dosya"; continue; }
    rc=0
    # ek argümanlar (varsa) boşlukla ayrılmış: yalnız --sahne <yol> beklenir
    if [[ -n "$ek" ]]; then
        read -r -a ekler <<< "$ek"
        ekler=("${ekler[0]}" "$ROOT_DIR/${ekler[1]}")
        out="$(dogrula "$BOZUK/$dosya" "${ekler[@]}" 2>&1)" || rc=$?
    else
        out="$(dogrula "$BOZUK/$dosya" 2>&1)" || rc=$?
    fi
    if [[ "$rc" -ne 1 ]]; then
        log_fail "Bozuk örnek beklenen çıkış kodunu (1) vermedi: $dosya (çıkış $rc)"
    elif [[ "$out" != *"$neden"* ]]; then
        log_fail "Bozuk örnek reddedildi ama beklenen neden yok: $dosya (aranan: '$neden')"
        while IFS= read -r l; do log_info "  | $l"; done <<< "$out"
    else
        log_ok "Bozuk örnek reddedildi: $dosya → '$neden'"
    fi
done < "$BEKLENEN"
if [[ "$n_bozuk" -ge 5 ]]; then log_ok "Bozuk örnek sayısı: $n_bozuk (≥ 5)"; else log_fail "Bozuk örnek sayısı yetersiz: $n_bozuk (< 5)"; fi
# beklenen.txt'de olmayan bozuk örnek kalmasın
for f in "$BOZUK"/*.json "$BOZUK"/*.jsonl; do
    if ! grep -qE "^[[:space:]]*$(basename "$f")[[:space:]]*\|" "$BEKLENEN"; then log_fail "beklenen.txt'de karşılığı olmayan bozuk örnek: $(basename "$f")"; fi
done

# 3) hedef listesi örneği = sahneden türetilen
uretilen="$(dogrula --hedef-listesi-uret "$sahne" 2>/dev/null || true)"
if python3 -I -c 'import json, sys; sys.exit(0 if json.loads(sys.argv[1]) == json.load(open(sys.argv[2], encoding="utf-8")) else 1)' "$uretilen" "$ORNEK/hedef_listesi_ornek.json" 2>/dev/null; then
    log_ok "hedef_listesi_ornek.json, sahneden türetilen listeyle birebir aynı"
else
    log_fail "hedef_listesi_ornek.json sahneden türetilen listeyle aynı değil"
fi

# 4) örneklerin SHA-256'sı kilit özetinde
eksik=""
for f in "${GECERLI[@]}"; do grep -qF "config/ornek/$f" "$LOCK" || eksik+="$f "; done
for f in "$BOZUK"/*.json "$BOZUK"/*.jsonl "$BEKLENEN"; do grep -qF "config/ornek/bozuk/$(basename "$f")" "$LOCK" || eksik+="bozuk/$(basename "$f") "; done
if [[ -z "$eksik" ]]; then log_ok "Örneklerin SHA-256'sı $(basename "$LOCK") içinde"; else log_fail "Kilit özetinde olmayan örnekler: $eksik(./setup/lock_ozet.sh)"; fi

component_finish "$COMPONENT_NAME" "tamamlandı (geçerli örnekler geçti, bozuk örnekler beklenen nedenle reddedildi)"
