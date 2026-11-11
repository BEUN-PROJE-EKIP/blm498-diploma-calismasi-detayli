#!/usr/bin/env bash
# verify_all.sh — setup/NN_*.sh betiklerini --verify ile çalıştırır (salt okunur; root/sudo gerekmez).
# Hata olsa da bütün adımlar çalışır; sonda tablo yazar. Herhangi biri başarısızsa çıkış 1.
# Sonda .generated/kurulum_raporu.md yazılır (üzerine yazar).
# Kullanım: ./verify_all.sh [-h]
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/rapor.sh
source "$SETUP_DIR/lib/rapor.sh"

case "${1:-}" in
    "") ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "Bilinmeyen argüman: $1" >&2; echo "Kullanım: ${0##*/} [-h]" >&2; exit 2 ;;
esac

START=$SECONDS
discover_steps
SELECTED_FILES=("${STEP_FILES[@]}")
run_steps 0 --verify

rc=0
total=$((SECONDS - START))
print_steps_table "$total" || rc=$?
load_versions
write_install_report verify "$total"
if [[ "$rc" -eq 0 ]]; then log_ok "Tüm doğrulamalar geçti"; else log_fail "Başarısız doğrulama var"; fi
exit "$rc"
