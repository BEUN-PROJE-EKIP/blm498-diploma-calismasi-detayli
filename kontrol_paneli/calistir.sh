#!/usr/bin/env bash
# calistir.sh — İHA sürüsü kontrol panelini (sunum aracı; projeden bağımsız) açar.
# Kullanım: kontrol_paneli/calistir.sh [--dry-run] [--derle]
#   --derle    önce React arayüzünü derler (frontend: npm ci/install + npm run build); Node.js/npm gerekir
#   --dry-run  yalnız ne yapılacağını ve ön koşulları gösterir
# Panel açılınca tarayıcıda http://127.0.0.1:8090 adresine gidin; "Sistemi başlat" Gazebo + PX4'ü araclar/kosu.sh ile açar.
# sudo gerekmez. Sürü ağı (tc) panelin işi değildir: setup/60_ag_emulasyon_tc.sh kendi terminalinizde.
set -Eeuo pipefail
# shellcheck source=../setup/lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/../setup/lib/common.sh"

PANEL_DIR="$ROOT_DIR/kontrol_paneli"
FRONT="$PANEL_DIR/frontend"
DERLE=0
DRY_RUN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --derle) DERLE=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help) sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Bilinmeyen argüman: $1" >&2; exit 2 ;;
    esac
    shift
done
require_not_root

if [[ "$DERLE" -eq 1 || ! -f "$FRONT/dist/index.html" ]]; then
    if ! command -v npm >/dev/null 2>&1; then
        log_fail "npm bulunamadı; React arayüzü derlenemez (Node.js kurun, sonra: kontrol_paneli/calistir.sh --derle)"
        exit 1
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] $FRONT: npm install && npm run build"
    else
        log_info "React arayüzü derleniyor ($(node -v))"
        (cd "$FRONT" && if [[ -f package-lock.json ]]; then npm ci; else npm install; fi && npm run build)
        [[ -f "$FRONT/dist/index.html" ]] || { log_fail "Derleme çıktısı yok: frontend/dist/index.html"; exit 1; }
        log_ok "Arayüz derlendi (frontend/dist)"
    fi
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    log_info "[dry-run] ortam: setup/env.sh; GZ_IP=127.0.0.1; python kontrol_paneli/backend/sunucu.py"
    exit 0
fi

set +u
# shellcheck source=/dev/null
source "$SETUP_DIR/env.sh" >/dev/null 2>&1
set -u
export GZ_IP=127.0.0.1 LC_NUMERIC=C PYTHONDONTWRITEBYTECODE=1
exec python "$PANEL_DIR/backend/sunucu.py"
