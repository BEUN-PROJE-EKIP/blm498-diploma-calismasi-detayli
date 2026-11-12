#!/usr/bin/env bash
# apt_kilit_testi.sh — apt kilit kümesi üretiminin regresyon testi (sahte dpkg-query, apt-mark ve sudo; sudo gerekmez, sistemde hiçbir şey değişmez).
# Kullanım: ./apt_kilit_testi.sh [--dry-run | --verify | -h]
#   (argümansız)  karışık durumlu (ii, hi, rc, un, ri) sahte paket veritabanıyla: küme hold'lu 'hi' paketleri de içermeli, rc/un/ri hariç tutmalı;
#                 kurulu en yeni çekirdek hold'lu paketlerden bulunmalı; --coz kümedeki bütün hold'lu paketlere `apt-mark unhold` kaydetmeli.
#   --dry-run     hiçbir şey çalıştırmaz; ne sınayacağını yazar
#   --verify      hafif önkoşul denetimi (apt_kilit.sh ve ortam kitaplığı var mı)
# Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz).
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
parse_common_args "$@"
COMPONENT_NAME="apt kilit kümesi testleri"
require_not_root
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

KILIT="$SETUP_DIR/apt_kilit.sh"
WORK="$GENERATED_DIR/apt_kilit_testi_gecici"

check_prereqs() {
    check "apt_kilit.sh çalıştırılabilir" test -x "$KILIT"
    check "lib/ortam.sh var" test -f "$SETUP_DIR/lib/ortam.sh"
}

if [[ "$MODE" == "verify" ]]; then
    check_prereqs
    component_finish "$COMPONENT_NAME"
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
    log_info "[dry-run] sahte dpkg-query (ii, hi, rc, un, ri karışık) ile küme: hi dahil, rc/un/ri hariç olmalı"
    log_info "[dry-run] sahte apt-mark showhold ile 'hold'da' sayısı doğru çıkmalı; kurulu en yeni çekirdek 'hi' paketlerden bulunmalı"
    log_info "[dry-run] sahte sudo ile --coz kümedeki hold'lu paketlere 'apt-mark unhold' kaydetmeli; hiçbir gerçek komut çalıştırılmaz"
    component_finish "$COMPONENT_NAME"
fi

check_prereqs
[[ "$COUNT_FAIL" -eq 0 ]] || { component_failed "$COMPONENT_NAME"; exit 1; }

BIN="$WORK/bin"
mkdir -p "$BIN"

# Sahte paket veritabanı: "durum paket sürüm mimari"
cat > "$WORK/db.txt" <<'DB'
ii linux-image-6.8.0-31-generic 6.8.0-31.31 amd64
hi linux-image-7.0.0-43-generic 7.0.0-43.43 amd64
rc linux-image-6.8.0-20-generic 6.8.0-20.20 amd64
hi linux-headers-7.0.0-43-generic 7.0.0-43.43 amd64
hi nvidia-driver-580 580.1-0ubuntu1 amd64
un nvidia-driver-470 <yok> amd64
ii libnvidia-compute-580 580.1-0ubuntu1 amd64
ii libnvidia-compute-580 580.1-0ubuntu1 i386
hi ros-jazzy-ros-base 0.11.0-1 amd64
ri ros-jazzy-demo-nodes 0.33-1 amd64
ii gz-harmonic 1.0.0-1 amd64
hi libgz-sim8 8.0.0-1 amd64
rc libgz-old 7.0.0-1 amd64
ii libc6 2.39-0ubuntu8 amd64
hi systemd 255.4-1 amd64
DB
cat > "$WORK/hold.txt" <<'HOLD'
libgz-sim8
linux-headers-7.0.0-43-generic
linux-image-7.0.0-43-generic
nvidia-driver-580
ros-jazzy-ros-base
HOLD
: > "$WORK/apt_mark_kayit.txt"

cat > "$BIN/dpkg-query" <<'FAKE'
#!/usr/bin/env bash
# sahte dpkg-query: -W -f='${db:Status-Abbrev} ${Package}[ ${Version} ${Architecture}]\n' [desen...]
fmt=""; pats=()
for a in "$@"; do
    case "$a" in
        -W) ;;
        -f=*) fmt="${a#-f=}" ;;
        *) pats+=("$a") ;;
    esac
done
n=0
while read -r durum paket surum mimari; do
    if [[ "${#pats[@]}" -gt 0 ]]; then
        eslesti=0
        for p in "${pats[@]}"; do
            # shellcheck disable=SC2254
            case "$paket" in $p) eslesti=1 ;; esac
        done
        [[ "$eslesti" -eq 1 ]] || continue
    fi
    n=$((n + 1))
    s="${fmt//\$\{db:Status-Abbrev\}/$durum }"
    s="${s//\$\{Package\}/$paket}"; s="${s//\$\{Version\}/$surum}"; s="${s//\$\{Architecture\}/$mimari}"
    printf '%b' "$s"
done < "$FAKE_DPKG_DB"
[[ "$n" -gt 0 ]] || exit 1
FAKE
cat > "$BIN/apt-mark" <<'FAKE'
#!/usr/bin/env bash
case "${1:-}" in
    showhold) cat "$FAKE_HOLD" ;;
    *) echo "apt-mark $*" >> "$FAKE_KAYIT" ;;
esac
FAKE
cat > "$BIN/sudo" <<'FAKE'
#!/usr/bin/env bash
# sahte sudo: komutu çalıştırmaz, yalnız kaydeder (sahte apt-mark ayrıca kaydeder)
echo "sudo $*" >> "$FAKE_KAYIT"
FAKE
chmod +x "$BIN/dpkg-query" "$BIN/apt-mark" "$BIN/sudo"

export FAKE_DPKG_DB="$WORK/db.txt" FAKE_HOLD="$WORK/hold.txt" FAKE_KAYIT="$WORK/apt_mark_kayit.txt"
sahte() { PATH="$BIN:$PATH" "$@"; }

# 1) küme: hi dahil, rc/un/ri ve sistem paketleri hariç; aynı ad iki mimaride tek sayılır
beklenen_kume="$(printf '%s\n' \
    'cekirdek linux-headers-7.0.0-43-generic' 'cekirdek linux-image-6.8.0-31-generic' 'cekirdek linux-image-7.0.0-43-generic' \
    'gazebo gz-harmonic' 'gazebo libgz-sim8' 'nvidia libnvidia-compute-580' 'nvidia nvidia-driver-580' 'ros2 ros-jazzy-ros-base' | LC_ALL=C sort -k2)"
out="$(sahte "$KILIT" --verify 2>&1 || true)"
kume="$(cat "$GENERATED_DIR/apt_kilit_listesi.txt" 2>/dev/null || true)"
# gerçek küme listesi dosyası bu testte sahte veriyle yazılır; test sonunda gerçek veriyle yeniden üretilir (aşağıda)
if [[ "$kume" == "$beklenen_kume" ]]; then
    log_ok "Küme: 8 paket (hi dahil; rc, un, ri ve libc6/systemd hariç)"
else
    log_fail "Küme beklenenden farklı"
    { diff <(echo "$beklenen_kume") <(echo "$kume") || true; } | while IFS= read -r l; do log_info "  | $l"; done
fi
if grep -qF 'Kilit kümesi' <<< "$out" && grep -qF '8 paket; hold'"'"'da 5, kilitsiz 3' <<< "$out"; then
    log_ok "Rapor: 8 paket; hold'da 5, kilitsiz 3 (hold'lu 'hi' paketler kümede sayıldı)"
else
    log_fail "Rapor sayıları beklenenden farklı: $(grep -F 'Kilit kümesi' <<< "$out" | sed -n 1p)"
fi
if grep -qF 'kurulu en yeni çekirdek: 7.0.0-43-generic' <<< "$out"; then
    log_ok "Kurulu en yeni çekirdek hold'lu 'hi' paketlerden bulundu: 7.0.0-43-generic"
else
    log_fail "Kurulu en yeni çekirdek bulunamadı: $(grep -F 'Çalışan çekirdek' <<< "$out" | sed -n 1p)"
fi

# 2) --coz: kümedeki hold'lu paketlere tek unhold komutu (bugün boş kalırdı)
: > "$FAKE_KAYIT"
sahte "$KILIT" --coz > "$WORK/coz.txt" 2>&1 || true
beklenen_unhold="sudo apt-mark unhold libgz-sim8 linux-headers-7.0.0-43-generic linux-image-7.0.0-43-generic nvidia-driver-580 ros-jazzy-ros-base"
if grep -qxF "$beklenen_unhold" "$FAKE_KAYIT"; then
    log_ok "--coz: 5 hold'lu paket için unhold komutu kaydedildi"
else
    log_fail "--coz beklenen unhold komutunu kaydetmedi (kayıt: $(tr '\n' '|' < "$FAKE_KAYIT"))"
fi

# 3) --kilitle: kümede olup hold'da olmayan 3 paket hold'a alınmalı
: > "$FAKE_KAYIT"
sahte "$KILIT" --kilitle > "$WORK/kilitle.txt" 2>&1 || true
beklenen_hold="sudo apt-mark hold gz-harmonic libnvidia-compute-580 linux-image-6.8.0-31-generic"
if grep -qxF "$beklenen_hold" "$FAKE_KAYIT"; then
    log_ok "--kilitle: kümede olup hold'da olmayan 3 paket için hold komutu kaydedildi"
else
    log_fail "--kilitle beklenen hold komutunu kaydetmedi (kayıt: $(tr '\n' '|' < "$FAKE_KAYIT"))"
fi

# sahte veriyle yazılan küme listesini gerçek veriyle yenile (sahte listeyi bırakma)
"$KILIT" > /dev/null 2>&1 || true

component_finish "$COMPONENT_NAME" "tamamlandı (hold'lu paketler kümeye girdi; --coz/--kilitle komutları kaydedildi)"
