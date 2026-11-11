#!/usr/bin/env bash
# 30_px4_sitl.sh — PX4 SITL'i kilitli etiketle (PX4_TAG) proje içine klonlar, Python bağımlılıklarını AYRI venv'e (.venv-px4) kurar ve derler.
# Kullanım: ./30_px4_sitl.sh [--dry-run | --verify | --update-lock | -h]
#   (argümansız)  apt bağımlılıkları (sudo) + klon + .venv-px4 + derleme; sonda doğrular; kuruluysa atlar
#   --dry-run     hiçbir şey kurmaz/oluşturmaz; yapacağı komutları yazar
#   --verify      yalnız denetim (sudo/ağ gerektirmez): klon, etiket, alt modüller, .venv-px4, derleme çıktısı;
#                 .venv-px4 freeze'i (.generated/px4-freeze.txt) kilitten farklıysa (!) (başarısız sayılmaz)
#   --update-lock kilidi bilinçli güncellemek için: pip kısıtlayıcısız kurar ve freeze'i px4-requirements.lock.txt'e yazar
# Kilit varsa PX4 requirements kurulumu kısıtlayıcıyla yapılır (pip install -c kilit -r requirements.txt); kilit üzerine yazılmaz.
# Sistem Python'u değiştirilmez (--break-system-packages / --user kullanılmaz). Gazebo yoksa derleme atlanır ve bileşen tamamlanmamış sayılır.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# --update-lock betiğe özgü bayrak; ortak ayrıştırıcıya geçmeden ayır.
UPDATE_LOCK=0
ARGS=()
for a in "$@"; do
    if [[ "$a" == "--update-lock" ]]; then UPDATE_LOCK=1; else ARGS+=("$a"); fi
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
if [[ "$UPDATE_LOCK" -eq 1 && "$MODE" == "verify" ]]; then echo "--update-lock ile --verify birlikte kullanılamaz" >&2; exit 2; fi
COMPONENT_NAME="PX4 SITL ${PX4_TAG:-}"
require_not_root
load_versions
COMPONENT_NAME="PX4 SITL $PX4_TAG"

PX4_URL="https://github.com/PX4/PX4-Autopilot.git"
PX4_DIR="$ROOT_DIR/third_party/PX4-Autopilot"
VENV_PX4="$ROOT_DIR/.venv-px4"
PY_PX4="$VENV_PX4/bin/python"
COMMIT_FILE="$SETUP_DIR/locks/px4-commit.txt"
REQ_LOCK="$SETUP_DIR/locks/px4-requirements.lock.txt"
FREEZE_FILE="$GENERATED_DIR/px4-freeze.txt"
PX4_BIN="$PX4_DIR/build/px4_sitl_default/bin/px4"
# empy 3.3.4 paketinin modül adı "em"dir (import empy ModuleNotFoundError verir)
PX4_IMPORTS="import em, jinja2, pymavlink, pyulog, kconfiglib, yaml"
APT_PKGS=(astyle ccache cppcheck file g++ gdb lcov libssl-dev libxml2-dev libxml2-utils make ninja-build rsync zip unzip python3-setuptools python3-wheel
          libopencv-dev libgstreamer-plugins-base1.0-dev libimage-exiftool-perl)
# Son üç paket PX4'ün Tools/setup/ubuntu.sh dosyasındaki "Simulation tools" bölümünden gelir (optical_flow gz eklentisi OpenCV ister).
# gstreamer çalışma zamanı eklentileri video akışı içindir; kapsam dışı olduğundan eklenmedi.
SIM_DEV_PKGS=(libopencv-dev libgstreamer-plugins-base1.0-dev libimage-exiftool-perl)

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

build_jobs() { # min(nproc, RAM_GiB/2), en az 1
    local n ram j
    n="$(nproc)"; ram=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
    j=$(( ram / 2 )); [[ "$j" -gt "$n" ]] && j="$n"; [[ "$j" -lt 1 ]] && j=1
    echo "$j"
}

gazebo_ready() { # Gazebo geliştirme paketleri: gz sim + gz-transport13 + gz-msgs10
    have_cmd gz && have_cmd pkg-config && pkg-config --exists gz-transport13 gz-msgs10
}

NUTTX_DIR="$PX4_DIR/platforms/nuttx/NuttX/nuttx"
NUTTX_TAG_RE='^nuttx-[0-9]+\.[0-9]+\.[0-9]+'

# NuttX alt modülündeki nuttx-X.Y.Z etiket sayısı (çıktı değişkene alınır; grep -q + pipefail SIGPIPE kalıbından kaçınmak için sayım grep -c ile)
nuttx_tag_count() {
    local tags
    tags="$(git -C "$NUTTX_DIR" tag 2>/dev/null || true)"
    grep -cE "$NUTTX_TAG_RE" <<< "$tags" || true
}

px4_describe() { git -C "$PX4_DIR" describe --tags --exact-match 2>/dev/null || true; }

install_component() {
    # 1) apt bağımlılıkları
    apt_ensure "${APT_PKGS[@]}"

    # 2) Klon (etiket kilitli; farklı dizin SİLİNMEZ)
    if [[ -d "$PX4_DIR" ]]; then
        local tag; tag="$(px4_describe)"
        if [[ "$tag" == "$PX4_TAG" ]]; then
            log_ok "PX4 klonu zaten var (etiket $tag): ${PX4_DIR#"$ROOT_DIR"/}"
        else
            fail_stop "Hedef dizin var ama etiketi '$PX4_TAG' değil (bulunan: '${tag:-etiketsiz/git değil}'): $PX4_DIR — silinmedi; elle inceleyin"
        fi
    else
        if [[ "$DRY_RUN" -eq 0 ]]; then
            mkdir -p "$ROOT_DIR/third_party"
            rm -rf "$PX4_DIR.partial"   # yarım kalmış önceki klon (proje içi)
        fi
        run "PX4 klonlanıyor ($PX4_TAG)" git clone --branch "$PX4_TAG" --depth 1 --recurse-submodules --shallow-submodules \
            "$PX4_URL" "$PX4_DIR.partial"
        run "Klon yerine taşınıyor" mv "$PX4_DIR.partial" "$PX4_DIR"
    fi
    # 2b) NuttX etiketleri. PX4 sürüm başlığı (src/lib/version/px_update_git_header.py) NuttX alt modülünden bir
    #     nuttx-X.Y.Z etiketi ister; --shallow-submodules klonu etiket getirmez ve derleme IndexError ile düşer.
    #     Yalnız bu etiketler alınır (alt modül commit'i değişmez). Ölçüm: 146 etiket ≈ 42 sn, ≈ 203 MB.
    if [[ -d "$NUTTX_DIR" ]]; then
        local ntags; ntags="$(nuttx_tag_count)"
        if [[ "$ntags" -gt 0 ]]; then
            log_ok "NuttX etiketleri zaten var ($ntags adet nuttx-X.Y.Z)"
        else
            run "NuttX etiketleri alınıyor (yalnız nuttx-*)" git -C "$NUTTX_DIR" fetch --depth 1 origin 'refs/tags/nuttx-*:refs/tags/nuttx-*'
        fi
    elif [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] klon sonrası: git -C $NUTTX_DIR fetch --depth 1 origin 'refs/tags/nuttx-*:refs/tags/nuttx-*' (yalnız etiket yoksa)"
    else
        fail_stop "NuttX alt modülü bulunamadı: $NUTTX_DIR"
    fi

    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$(dirname "$COMMIT_FILE")"
        printf 'tag=%s\ncommit=%s\n' "$PX4_TAG" "$(git -C "$PX4_DIR" rev-parse HEAD)" > "$COMMIT_FILE"
        log_ok "Commit özeti yazıldı: ${COMMIT_FILE#"$ROOT_DIR"/}"
    else
        log_info "[dry-run] git -C $PX4_DIR rev-parse HEAD → ${COMMIT_FILE#"$ROOT_DIR"/}"
    fi

    # 3) Ayrı venv (sistem site-paketleri YOK)
    if [[ -x "$PY_PX4" ]]; then
        log_ok "venv zaten var: $VENV_PX4"
    elif python3 -c "import ensurepip" >/dev/null 2>&1; then
        run "PX4 venv oluşturuluyor" python3 -m venv "$VENV_PX4"
    elif [[ "$DRY_RUN" -eq 1 ]]; then
        log_warn "python3-venv (ensurepip) yok: gerçek modda durulur; önce 05_temel_paketler.sh çalıştırılmalı"
        log_info "[dry-run] python3 -m venv $VENV_PX4"
    else
        fail_stop "python3-venv (ensurepip) yok: önce 05_temel_paketler.sh (python3-venv) çalıştırılmalı"
    fi

    # 4) PX4 Python bağımlılıkları. Kilit varsa kısıtlayıcı (-c) kullanılır; depodaki kilit ÜZERİNE YAZILMAZ
    #    (yalnız ilk üretimde veya --update-lock ile). Kurulum sonrası freeze .generated/ altına yazılıp kilitle karşılaştırılır.
    local -a constraint=()
    if [[ -f "$REQ_LOCK" && "$UPDATE_LOCK" -eq 0 ]]; then constraint=(-c "$REQ_LOCK"); fi
    if [[ -x "$PY_PX4" && "$UPDATE_LOCK" -eq 0 ]] && "$PY_PX4" -c "$PX4_IMPORTS" >/dev/null 2>&1; then
        log_ok "PX4 Python bağımlılıkları zaten kurulu (.venv-px4)"
    else
        run "PX4 requirements kuruluyor" "$PY_PX4" -m pip install --disable-pip-version-check --no-input \
            "${constraint[@]}" -r "$PX4_DIR/Tools/setup/requirements.txt"
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] $PY_PX4 -m pip freeze --local > ${FREEZE_FILE#"$ROOT_DIR"/}; kilitle karşılaştırılır"
        if [[ ! -f "$REQ_LOCK" || "$UPDATE_LOCK" -eq 1 ]]; then log_info "[dry-run] freeze → ${REQ_LOCK#"$ROOT_DIR"/} (kilit yok veya --update-lock)"; fi
    elif [[ -x "$PY_PX4" ]]; then
        freeze_pkgs "$PY_PX4" "$FREEZE_FILE"
        if [[ ! -f "$REQ_LOCK" || "$UPDATE_LOCK" -eq 1 ]]; then
            mkdir -p "$(dirname "$REQ_LOCK")"
            cp "$FREEZE_FILE" "$REQ_LOCK.tmp"; mv "$REQ_LOCK.tmp" "$REQ_LOCK"
            log_ok "Kilit dosyası yazıldı: ${REQ_LOCK#"$ROOT_DIR"/} ($(wc -l < "$REQ_LOCK") paket)"
        else
            lock_report ".venv-px4" "$REQ_LOCK" "$FREEZE_FILE"
        fi
    fi

    # 5) Derleme
    if [[ -x "$PX4_BIN" ]]; then
        log_ok "Derleme çıktısı zaten var: ${PX4_BIN#"$ROOT_DIR"/}"
    elif gazebo_ready; then
        run "px4_sitl_default derleniyor (-j$(build_jobs))" bash -c \
            'cd "$1" && PATH="$2:$PATH" CCACHE_DIR="${CCACHE_DIR:-$HOME/.ccache}" make -j"$3" px4_sitl_default' \
            _ "$PX4_DIR" "$VENV_PX4/bin" "$(build_jobs)"
    elif [[ "$DRY_RUN" -eq 1 ]]; then
        log_warn "Gazebo yok (gz / gz-transport13 / gz-msgs10 bulunamadı): gerçek modda derleme atlanır, bileşen tamamlanmadı sayılır"
        log_info "[dry-run] (cd $PX4_DIR && PATH=$VENV_PX4/bin:\$PATH make -j$(build_jobs) px4_sitl_default)"
    else
        log_warn "Gazebo yok; derleme atlandı"
        log_fail "Bileşen tamamlanmadı: derleme yapılmadı (önce 20_gazebo_harmonic.sh)"
    fi
}

verify_component() {
    local tag
    if [[ -d "$PX4_DIR/.git" || -f "$PX4_DIR/.git" ]]; then
        tag="$(px4_describe)"
        if [[ "$tag" == "$PX4_TAG" ]]; then log_ok "PX4 klonu var, etiket $tag"; else log_fail "PX4 etiketi $PX4_TAG olmalı; bulunan: '${tag:-yok}'"; fi
        local head want
        head="$(git -C "$PX4_DIR" rev-parse HEAD 2>/dev/null || true)"
        want="$(sed -n 's/^commit=//p' "$COMMIT_FILE" 2>/dev/null || true)"
        if [[ -n "$head" && "$head" == "$want" ]]; then log_ok "Commit ${head:0:12} px4-commit.txt ile uyumlu"; else log_fail "Commit px4-commit.txt ile uyumsuz (klon: '${head:0:12}', dosya: '${want:0:12}')"; fi
        local subs
        subs="$(git -C "$PX4_DIR" submodule status 2>/dev/null || true)"
        if [[ -n "$subs" ]] && ! grep -q '^-' <<< "$subs"; then
            log_ok "Alt modüller dolu ($(wc -l <<< "$subs") adet)"
        else
            log_fail "Alt modüller eksik veya okunamadı (başında '-' olan satır var ya da liste boş)"
        fi
    else
        log_fail "PX4 klonu yok: ${PX4_DIR#"$ROOT_DIR"/}"
    fi

    if [[ -d "$NUTTX_DIR" ]]; then
        local nt; nt="$(nuttx_tag_count)"
        if [[ "$nt" -gt 0 ]]; then log_ok "NuttX alt modülünde nuttx-X.Y.Z etiketi var ($nt adet)"; else log_fail "NuttX alt modülünde nuttx-X.Y.Z etiketi yok (sürüm başlığı için gerekli)"; fi
    else
        log_fail "NuttX alt modülü yok: ${NUTTX_DIR#"$ROOT_DIR"/}"
    fi

    local pkg
    for pkg in "${SIM_DEV_PKGS[@]}"; do
        if apt_pkg_installed "$pkg"; then log_ok "apt paketi kurulu: $pkg"; else log_fail "apt paketi kurulu değil: $pkg"; fi
    done

    if [[ -x "$PY_PX4" ]]; then
        log_ok ".venv-px4 var"
        check "PX4 Python içe aktarmaları ($PX4_IMPORTS)" "$PY_PX4" -c "$PX4_IMPORTS"
        freeze_pkgs "$PY_PX4" "$FREEZE_FILE"
        lock_report ".venv-px4" "$REQ_LOCK" "$FREEZE_FILE"
    else
        log_fail ".venv-px4 yok"
    fi

    if [[ -x "$PX4_BIN" ]]; then log_ok "Derleme çıktısı var: ${PX4_BIN#"$ROOT_DIR"/}"; else log_fail "Derleme çıktısı yok: ${PX4_BIN#"$ROOT_DIR"/}"; fi
}

if [[ "$MODE" == "install" ]]; then
    install_component
fi
if [[ "$MODE" == "verify" || "$DRY_RUN" -eq 0 ]]; then
    verify_component
fi
component_finish "$COMPONENT_NAME"
