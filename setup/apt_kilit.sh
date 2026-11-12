#!/usr/bin/env bash
# apt_kilit.sh — kritik apt paketlerini (çekirdek, NVIDIA, ROS 2, Gazebo) sabitler (apt-mark hold) / çözer ve kilit durumunu denetler.
# Kullanım: ./apt_kilit.sh [--dry-run | --verify | --kilitle | --coz | -h]
#   (argümansız)  --verify ile aynı
#   --verify      sudo'suz, salt okunur: küme kurulu paketlerden çalışma anında üretilir ve apt-mark showhold ile karşılaştırılır; ayrıca otomatik
#                 güncelleme (apt-daily-upgrade.timer, unattended-upgrades, 20auto-upgrades), çalışan ve kurulu en yeni çekirdek, reboot-required
#                 raporlanır. Kilitsiz paket varsa (-); yeniden başlatma bekliyorsa (!); otomatik güncelleme açıksa (!). Küme listesi
#                 .generated/apt_kilit_listesi.txt dosyasına yazılır.
#   --kilitle     (sudo) kümede olup hold'da olmayanlara tek komutta `apt-mark hold`; sonda doğrular. Gerçek çalıştırmayı kullanıcı yapar.
#   --coz         (sudo) kümede olup hold'da olanlara tek komutta `apt-mark unhold`; sonda doğrular.
#   --dry-run     hiçbir şey değiştirmez, dosya yazmaz; --kilitle/--coz ile birlikte çalıştırılacak komutu yazar
# Küme (sabit liste yok; kurulu paketlerden): çekirdek (linux-image-*, linux-headers-*, linux-modules*, linux-tools-*, linux-generic*, linux-hwe*,
# linux-main-modules*), NVIDIA (nvidia-*, libnvidia-*, xserver-xorg-video-nvidia*, cuda*, linux-firmware-nvidia*), ROS 2 (ros-*, ros2-apt-source,
# python3-colcon-*, python3-rosdep*, python3-rosdistro*, python3-rospkg*, python3-catkin-pkg*, python3-vcstool, python3-bloom, python3-rosinstall*),
# Gazebo (gz-*, libgz-*, libsdformat*, libignition*, sdformat*, python3-gz-*, python3-sdformat*). libc, systemd vb. sistem paketleri kapsama alınmaz.
# Otomatik güncelleme ayarlarına, çekirdeğe ve NVIDIA'ya DOKUNULMAZ (yalnız denetlenir; kapatma komutu önerilir). Bu betik install_all.sh /
# verify_all.sh sırasına GİRMEZ (adı NN_ desenine uymaz).
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

ACTION="verify"
ARGS=()
for a in "$@"; do
    case "$a" in
        --kilitle) ACTION="kilitle" ;;
        --coz) ACTION="coz" ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
COMPONENT_NAME="apt sürüm kilidi"
require_not_root
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

LIST_FILE="$GENERATED_DIR/apt_kilit_listesi.txt"
APT_RECORD="$SETUP_DIR/locks/apt-surumleri.txt"
# Geçici dosyalar .generated/ altında sabit klasörde tutulur ve her çalıştırmada üzerine yazılır (silme/rm yok)
TMP_DIR="$GENERATED_DIR/apt_kilit_gecici"
mkdir -p "$TMP_DIR"

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }
have_cmd dpkg-query || fail_stop "dpkg-query bulunamadı"
have_cmd apt-mark || fail_stop "apt-mark bulunamadı"

# Paket adı → grup (awk işlevi; küme üretimi ve kayıt kapsamı aynı kuralı kullanır)
AWK_GRUP='
function grup(p) {
    if (p ~ /^(linux-image-|linux-headers-|linux-modules|linux-tools-|linux-generic|linux-hwe|linux-main-modules)/) return "cekirdek"
    if (p ~ /^(nvidia-|libnvidia-|xserver-xorg-video-nvidia|cuda|linux-firmware-nvidia)/) return "nvidia"
    if (p ~ /^(ros-|ros2-apt-source$|python3-colcon-|python3-rosdep|python3-rosdistro|python3-rospkg|python3-catkin-pkg|python3-vcstool$|python3-bloom$|python3-rosinstall)/) return "ros2"
    if (p ~ /^(gz-|libgz-|libsdformat|libignition|sdformat|python3-gz-|python3-sdformat|python3-ignition)/) return "gazebo"
    return ""
}'

# kume_uret : "grup paket" satırları (kurulu 'ii' paketlerden; aynı ad farklı mimaride tek sayılır; LC_ALL=C sıralı)
kume_uret() {
    dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' | awk "$AWK_GRUP"'
        $1 == "ii" { g = grup($2); if (g != "" && !($2 in gor)) { gor[$2] = 1; print g, $2 } }' | LC_ALL=C sort -k2
}

# Kayıttaki (apt-surumleri.txt) aynı kümenin kapsamı: "grup paket"
kume_kayit() {
    [[ -f "$APT_RECORD" ]] || return 0
    awk "$AWK_GRUP"' { g = grup($1); if (g != "" && !($1 in gor)) { gor[$1] = 1; print g, $1 } }' "$APT_RECORD" | LC_ALL=C sort -k2
}

kume_uret > "$TMP_DIR/kume.txt"
awk '{print $2}' "$TMP_DIR/kume.txt" > "$TMP_DIR/kume_paket.txt"
apt-mark showhold 2>/dev/null | LC_ALL=C sort -u > "$TMP_DIR/hold.txt" || true
LC_ALL=C comm -23 "$TMP_DIR/kume_paket.txt" "$TMP_DIR/hold.txt" > "$TMP_DIR/eksik.txt"      # kümede olup hold'da olmayan
LC_ALL=C comm -12 "$TMP_DIR/kume_paket.txt" "$TMP_DIR/hold.txt" > "$TMP_DIR/kilitli.txt"    # kümede olup hold'da olan
LC_ALL=C comm -13 "$TMP_DIR/kume_paket.txt" "$TMP_DIR/hold.txt" > "$TMP_DIR/disarida.txt"   # hold'da olup kümede olmayan
N_KUME="$(wc -l < "$TMP_DIR/kume_paket.txt")"
N_EKSIK="$(wc -l < "$TMP_DIR/eksik.txt")"
N_KILITLI="$(wc -l < "$TMP_DIR/kilitli.txt")"

kume_raporu() {
    local g n r
    log_info "Kilit kümesi (kurulu paketlerden, çalışma anında): $N_KUME paket; hold'da $N_KILITLI, kilitsiz $N_EKSIK"
    for g in cekirdek nvidia ros2 gazebo; do
        n="$(awk -v g="$g" '$1 == g' "$TMP_DIR/kume.txt" | wc -l)"
        r="$(kume_kayit | awk -v g="$g" '$1 == g' | wc -l)"
        log_info "  grup $g: şimdi $n paket (apt-surumleri.txt kaydında $r)"
    done
    # Kayıtla küme farkı (kayda göre): kayıtta olup kurulu olmayan / kurulu olup kayıtta olmayan
    kume_kayit | awk '{print $2}' | LC_ALL=C sort -u > "$TMP_DIR/kayit_paket.txt"
    local yeni kalkan
    yeni="$(LC_ALL=C comm -13 "$TMP_DIR/kayit_paket.txt" "$TMP_DIR/kume_paket.txt" | wc -l)"
    kalkan="$(LC_ALL=C comm -23 "$TMP_DIR/kayit_paket.txt" "$TMP_DIR/kume_paket.txt" | wc -l)"
    if [[ ! -f "$APT_RECORD" ]]; then
        log_warn "apt kaydı yok ($APT_RECORD); kapsam karşılaştırması yapılamadı"
    elif [[ "$yeni" -eq 0 && "$kalkan" -eq 0 ]]; then
        log_ok "Küme apt-surumleri.txt kaydındaki aynı kümeyle birebir aynı"
    else
        log_info "Kayıtla fark: kümede olup kayıtta olmayan $yeni, kayıtta olup artık kurulu olmayan $kalkan (kayıt bayat olabilir: ./setup/ortam_kaydi.sh)"
    fi
    if [[ -s "$TMP_DIR/disarida.txt" ]]; then
        log_info "hold'da olup kümede olmayan $(wc -l < "$TMP_DIR/disarida.txt") paket (dokunulmaz): $(head -n 5 "$TMP_DIR/disarida.txt" | tr '\n' ' ')"
    fi
}

liste_yaz() { # küme listesini .generated altına yazar (dry-run'da yazmaz)
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log_info "[dry-run] ${LIST_FILE#"$ROOT_DIR"/} yazılacaktı ($N_KUME satır; yazılmadı)"
        return 0
    fi
    mkdir -p "$GENERATED_DIR"
    cp "$TMP_DIR/kume.txt" "$LIST_FILE.tmp" && mv "$LIST_FILE.tmp" "$LIST_FILE"
    log_info "Küme listesi yazıldı: ${LIST_FILE#"$ROOT_DIR"/} ($N_KUME satır: \"grup paket\")"
}

# --- Çekirdek, yeniden başlatma, otomatik güncelleme (yalnız denetim) --------------------
cekirdek_raporu() {
    local calisan yeni
    calisan="$(uname -r)"
    yeni="$(dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' 'linux-image-[0-9]*' 2>/dev/null | awk '$1 == "ii" { sub(/^linux-image-/, "", $2); print $2 }' | sort -V | tail -n 1 || true)"
    log_info "Çalışan çekirdek: $calisan; kurulu en yeni çekirdek: ${yeni:-?}"
    if [[ -n "$yeni" && "$yeni" != "$calisan" ]]; then
        log_warn "Yeniden başlatma bekliyor: çalışan çekirdek ($calisan) kurulu en yeni çekirdekten ($yeni) farklı"
    else
        log_ok "Çalışan çekirdek kurulu en yeni çekirdekle aynı"
    fi
    if [[ -f /var/run/reboot-required ]]; then
        log_warn "/var/run/reboot-required var ($(tr '\n' ' ' < /var/run/reboot-required 2>/dev/null)); paketler: $(sort -u /var/run/reboot-required.pkgs 2>/dev/null | head -n 5 | tr '\n' ' ')"
    else
        log_ok "reboot-required yok"
    fi
}

otomatik_guncelleme_raporu() {
    local u s acik=0 conf
    for u in apt-daily-upgrade.timer unattended-upgrades.service; do
        s="$(systemctl is-enabled "$u" 2>/dev/null || true)"
        s="${s:-bilinmiyor}"
        case "$s" in
            disabled|masked|static|bilinmiyor|not-found) log_ok "$u: $s (kapalı/devre dışı)" ;;
            *) log_warn "$u: $s (otomatik güncelleme AÇIK olabilir)"; acik=1 ;;
        esac
    done
    s="$(systemctl is-enabled apt-daily.timer 2>/dev/null || true)"
    log_info "apt-daily.timer (paket listesi yenileme): ${s:-bilinmiyor}"
    if [[ -f /etc/apt/apt.conf.d/20auto-upgrades ]]; then
        conf="$(tr '\n' ' ' < /etc/apt/apt.conf.d/20auto-upgrades)"
        log_info "20auto-upgrades: $conf"
        if grep -qE 'Unattended-Upgrade[[:space:]]+"1"' /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null; then
            log_warn "20auto-upgrades içinde Unattended-Upgrade \"1\" (zamanlayıcılar kapalıysa tetiklenmez; yeniden açılırsa güncelleme yapar)"
            acik=1
        fi
    else
        log_info "/etc/apt/apt.conf.d/20auto-upgrades yok"
    fi
    if [[ "$acik" -eq 1 ]]; then
        log_info "Önerilen (kullanıcı Konsole'da çalıştırır; bu betik DEĞİŞTİRMEZ): sudo systemctl disable --now apt-daily-upgrade.timer unattended-upgrades.service; sudo sed -i 's/\\(Unattended-Upgrade[[:space:]]*\\)\"1\"/\\1\"0\"/' /etc/apt/apt.conf.d/20auto-upgrades"
    fi
}

verify_component() {
    kume_raporu
    liste_yaz
    if [[ "$N_KUME" -eq 0 ]]; then
        log_warn "Kilit kümesi boş (çekirdek/NVIDIA/ROS 2/Gazebo paketi bulunamadı)"
    elif [[ "$N_EKSIK" -eq 0 ]]; then
        log_ok "Kümenin tamamı hold'da ($N_KUME paket)"
    else
        log_fail "$N_EKSIK paket kilitsiz (ilk 10: $(head -n 10 "$TMP_DIR/eksik.txt" | tr '\n' ' ')); kilitlemek için kullanıcı Konsole'da: ./setup/apt_kilit.sh --kilitle"
    fi
    cekirdek_raporu
    otomatik_guncelleme_raporu
}

komut_calistir() { # komut_calistir <hold|unhold> <dosya> : tek komutta toplu apt-mark
    local verb="$1" f="$2" n
    local -a paketler=()
    mapfile -t paketler < "$f"
    n="${#paketler[@]}"
    have_cmd sudo || fail_stop "sudo bulunamadı"
    sudo_run "apt-mark $verb ($n paket)" apt-mark "$verb" "${paketler[@]}"
}

son_dogrulama() { # son_dogrulama <hold|unhold> : durumu yeniden okur
    local verb="$1" kalan
    apt-mark showhold 2>/dev/null | LC_ALL=C sort -u > "$TMP_DIR/hold2.txt" || true
    if [[ "$verb" == "hold" ]]; then
        kalan="$(LC_ALL=C comm -23 "$TMP_DIR/kume_paket.txt" "$TMP_DIR/hold2.txt" | wc -l)"
        if [[ "$kalan" -eq 0 ]]; then log_ok "Doğrulandı: kümenin tamamı ($N_KUME paket) hold'da"; else log_fail "Doğrulama: $kalan paket hâlâ kilitsiz"; fi
    else
        kalan="$(LC_ALL=C comm -12 "$TMP_DIR/kume_paket.txt" "$TMP_DIR/hold2.txt" | wc -l)"
        if [[ "$kalan" -eq 0 ]]; then log_ok "Doğrulandı: kümede hold'da paket kalmadı"; else log_fail "Doğrulama: $kalan paket hâlâ hold'da"; fi
    fi
}

case "$ACTION" in
    kilitle)
        kume_raporu
        liste_yaz
        if [[ "$N_KUME" -eq 0 ]]; then
            log_warn "Kilit kümesi boş; yapılacak bir şey yok"
        elif [[ "$N_EKSIK" -eq 0 ]]; then
            log_ok "Kümenin tamamı zaten hold'da ($N_KUME paket); idempotent: değişiklik yok"
        else
            komut_calistir hold "$TMP_DIR/eksik.txt"
            if [[ "$DRY_RUN" -eq 1 ]]; then log_info "[dry-run] hold uygulanmadı; sonda doğrulama atlandı"; else son_dogrulama hold; fi
        fi
        ;;
    coz)
        kume_raporu
        if [[ "$N_KILITLI" -eq 0 ]]; then
            log_ok "Kümede hold'da paket yok; idempotent: değişiklik yok"
        else
            komut_calistir unhold "$TMP_DIR/kilitli.txt"
            if [[ "$DRY_RUN" -eq 1 ]]; then log_info "[dry-run] unhold uygulanmadı; sonda doğrulama atlandı"; else son_dogrulama unhold; fi
        fi
        ;;
    *)
        if [[ "$DRY_RUN" -eq 1 ]]; then
            kume_raporu
            liste_yaz
            log_info "[dry-run] --kilitle şunu çalıştırırdı: sudo apt-mark hold <$N_EKSIK kilitsiz paket>; --coz: sudo apt-mark unhold <$N_KILITLI hold'daki paket>"
        else
            verify_component
        fi
        ;;
esac

component_finish "$COMPONENT_NAME"
