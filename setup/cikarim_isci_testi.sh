#!/usr/bin/env bash
# cikarim_isci_testi.sh — çıkarım işçisi (B9), kare sonucu (B10) ve geriye dönük inceleme düzeltmeleri kabul testleri (başsız Gazebo + PX4 SITL + araç süreçleri + deneme koordinatörü).
# Kullanım: ./cikarim_isci_testi.sh [--dry-run | --verify | -h] [birim] [isci] [duzeltme] [tek] [hata] [uc]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz, hiçbir şey derlemez; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, kurulu paketler); süreç başlatmaz
# Testler:
#   birim     birim testleri (durum makinesi, kamera alıcısı, çıkarım/kare sonucu; ROS'suz), colcon build, saf modüllerin ağır kitaplıksız içe aktarımı, rclpy denetimi, py_compile, shellcheck
#   isci      simülasyonsuz işçi denemesi (araclar/cikarim_isci_deneme.py): GPU ve ONNX Runtime CPU arka uçları, üç sonuç türü, uçtan uca başlık kanıtı, kanal/CPU kanıtı, süreler, GPU belleği
#   duzeltme  geriye dönük inceleme düzeltmeleri: yayım ölçüm betiği tam koşusu, deney.env anahtarları, runtime_smoke temel gövde (simülasyon yok)
#   tek       --arac 1, enjeksiyon kapalı: her görev numarası için tam bir kare sonucu, damga birleşmesi, bariyer sırası, işçi CPU sabitlemesi, GZ_IP verilmeden gz soketleri, RTF
#   hata      --arac 1, enjeksiyon AÇIK: bir kare kayıp, bir karede işçi hatası, bir kez işçi ölümü (yeniden başlatma); hiçbir numara sonuçsuz değil
#   uc        --arac 3, enjeksiyon kapalı: üç işçi (üç alt süreç), her araçta tam sonuç kümesi, çakışmayan CPU çiftleri, RTF
# Araç süreçleri, koordinatör ve canlı denetim `setsid` ile ayrı süreç gruplarında başlatılır, günlükleri koşu klasöründe; her çıkışta bu betik kendisi toplar.
# Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ. sudo gerekmez.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/derleme.sh
source "$SETUP_DIR/lib/derleme.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        birim|isci|duzeltme|tek|hata|uc) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(birim isci duzeltme tek hata uc)
COMPONENT_NAME="Çıkarım işçisi ve kare sonucu"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
KOORD="$ROOT_DIR/araclar/koordinator_deneme.py"
ANALIZ="$ROOT_DIR/araclar/cikarim_analiz.py"
CANLI="$ROOT_DIR/araclar/cikarim_canli_denetim.py"
ISCI_DENEME="$ROOT_DIR/araclar/cikarim_isci_deneme.py"
BIRIM_TEST="$ROOT_DIR/src/swarm_vehicle/test/test_durum_makinesi.py"
BIRIM_TEST2="$ROOT_DIR/src/swarm_vehicle/test/test_kamera_alici.py"
BIRIM_TEST3="$ROOT_DIR/src/swarm_vehicle/test/test_cikarim.py"
EK_ENV=()
PKG_DIR="$ROOT_DIR/src/swarm_vehicle"
VENV_PY="$ROOT_DIR/.venv/bin/python"
ENV_SH="$SETUP_DIR/env.sh"
DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
ROS_SETUP="/opt/ros/$ROS_DISTRO/setup.bash"
KOK="$GENERATED_DIR/kosular"
TMP_DIR=""
PGIDS=()

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

grup_oldur() { # grup_oldur <pgid> : önce TERM, 5 sn sonra KILL
    local pg="$1" i
    kill -TERM -- "-$pg" 2>/dev/null || true
    for ((i = 0; i < 50; i++)); do kill -0 -- "-$pg" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL -- "-$pg" 2>/dev/null || true
}

exit_hook() {
    [[ "${DRY_RUN:-0}" -eq 0 && "${MODE:-install}" != verify ]] || return 0   # --dry-run/--verify hiçbir süreç başlatmaz; yaşayan (başkasına ait) koşuya DOKUNMAZ
    local i
    for ((i = ${#PGIDS[@]} - 1; i >= 0; i--)); do grup_oldur "${PGIDS[$i]}"; done
    PGIDS=()
    if [[ -f "$KOK/aktif" ]]; then "$KOSU" temizle >/dev/null 2>&1 || true; fi
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
    TMP_DIR=""
}

[[ -f "$DENEY_ENV" ]] || fail_stop "Yapılandırma yok: $DENEY_ENV"
# shellcheck source=/dev/null
source "$DENEY_ENV"
for v in SIM_WORLD UAV_SYS_IDS UAV_NAMESPACES UAV1_ADDR UAV2_ADDR UAV3_ADDR GCS_ADDR DURUM_YAYIN_HZ KONU_DURUM KOSU_KAPANIS_SN ISCI_ARKA_UC ISCI_MANTIKSAL_CPU ISCI_CPU_SABITLE; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
read -r -a SYS_IDS <<< "$UAV_SYS_IDS"

# venv dışı PATH (ROS araçları sistem Python'unu kullansın)
clean_path() { local p="" d; local IFS=':'; for d in $PATH; do [[ "$d" == "$ROOT_DIR/.venv"* || "$d" == "$ROOT_DIR/.venv-px4/"* ]] || p+="${p:+:}$d"; done; echo "$p"; }
# shellcheck disable=SC2016  # tek tırnak bilerek: $1 alt kabukta açılır
ros_run() { env -u VIRTUAL_ENV PATH="$(clean_path)" bash -c 'source "$1"; shift; "$@"' _ "$ROS_SETUP" "$@"; }

check_prereqs() {
    local c f
    for c in gz ss pgrep python3 awk colcon git tc taskset; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "setup/env.sh" test -f "$ENV_SH"
    check "ROS 2 setup.bash" test -f "$ROS_SETUP"
    for f in "$KOSU" "$KOORD" "$ANALIZ" "$CANLI" "$ISCI_DENEME" "$BIRIM_TEST" "$BIRIM_TEST2" "$BIRIM_TEST3" "$PKG_DIR/swarm_vehicle/arac.py" "$PKG_DIR/swarm_vehicle/cikarim/cikarim_isci.py" "$PKG_DIR/swarm_vehicle/cikarim/cikarim_istemci.py" \
        "$PKG_DIR/swarm_vehicle/cikarim/cikarim_yardimci.py" "$PKG_DIR/swarm_vehicle/cikarim/kare_sonuc.py" "$PKG_DIR/swarm_vehicle/cikarim/kare_isleyici.py" "$PKG_DIR/swarm_vehicle/kamera/kamera_alici.py" "$PKG_DIR/swarm_vehicle/kamera/kamera_alici_gz.py"; do
        check "Dosya: ${f#"$ROOT_DIR"/}" test -f "$f"
    done
    # shellcheck disable=SC2016  # tek tırnak bilerek: alt kabukta açılır
    check "Yapılandırılmış sürü ağı (lo üzerinde htb)" bash -c '[[ "$(tc qdisc show dev lo)" == *htb* ]]'
    check "kosu.sh --dry-run baslat çıkış 0" "$KOSU" --dry-run baslat
}

print_plan() {
    log_info "[dry-run] birim: birim testleri (durum makinesi, kamera alıcısı, çıkarım ve kare sonucu), colcon build swarm_msgs swarm_vehicle, saf modüllerin ağır kitaplıksız içe aktarımı, rclpy denetimi, py_compile, shellcheck -x"
    log_info "[dry-run] isci: araclar/cikarim_isci_deneme.py --cpu-yolu (simülasyonsuz; GPU + ONNX Runtime CPU işçisi, bus/zidane/gri/bozuk görüntü)"
    log_info "[dry-run] duzeltme: yayim_olcum_testi.sh tam koşusu açık iletiyle durur, --verify/--dry-run çalışır; deney.env anahtarları; runtime_smoke.sh SIM_MODEL_TEMEL"
    log_info "[dry-run] tek: kosu.sh baslat --arac 1 → koordinatör + araç süreci 1 (GZ_IP verilmeden, enjeksiyon kapalı) + canlı denetim → analiz (tam sonuç kümesi, damga birleşmesi, bariyer sırası, CPU, soketler, RTF) → durdur"
    log_info "[dry-run] hata: araç süreci KAMERA_ENJEKSIYON='dusur=+20' ISCI_ENJEKSIYON='hata=+40;olum=+80' → kare alınamadı / işlem hatası / işçi ölümü + yeniden başlatma; hiçbir numara sonuçsuz değil"
    log_info "[dry-run] uc: kosu.sh baslat --arac 3 → koordinatör + üç araç süreci (üç işçi, enjeksiyon kapalı) → her araçta tam sonuç kümesi, çakışmayan CPU çiftleri, RTF"
    log_info "[dry-run] Her testten sonra araç süreci/işçi/koordinatör/px4/gz/mavsdk_server artığı, yeni dinleyen port, /dev/shm; sonda ros2 daemon, tc/ip denetimi. Hiçbir süreç başlatılmadı"
}

if [[ "$MODE" == "verify" ]]; then
    check_prereqs
    component_finish "$COMPONENT_NAME"
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
    print_plan
    component_finish "$COMPONENT_NAME"
fi

check_prereqs
[[ "$COUNT_FAIL" -eq 0 ]] || fail_stop "Önkoşullar eksik"
TMP_DIR="$(mktemp -d)"

# --- Ölçüm anlık görüntüleri -------------------------------------------------------
shm_list() { find /dev/shm -maxdepth 1 -printf '%f\n' 2>/dev/null | LC_ALL=C sort || true; }
snapshot() { # snapshot <ad>
    local n="$1" c
    {
        for c in px4 gz mavsdk_server ruby; do echo "proc $c $(pgrep -x -c "$c" || true)"; done
        echo "proc arac $(pgrep -f -c 'swarm_vehicle[.]arac' || true)"
        echo "proc koordinator $(pgrep -f -c 'koordinator_deneme[.]py' || true)"
        echo "proc isci $(pgrep -f -c 'swarm_vehicle[.]cikarim_isci' || true)"
        echo "proc canli $(pgrep -f -c 'cikarim_canli_denetim[.]py' || true)"
    } > "$TMP_DIR/$n.proc"
    port_snapshot "$TMP_DIR/$n.ports"
    shm_list > "$TMP_DIR/$n.shm"
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$TMP_DIR/$n.net"
}

kalan_yok() { # kalan_yok <etiket>
    local et="$1" ok=1 yeni k
    sleep 1
    # canlı denetim izleyicisi araç süreci kalkınca en geç bir örnekleme aralığı (2 sn) sonra çıkar: en çok 5 sn beklenir; süre dolarsa kontrol yine (-) verir (gevşetilmez)
    for ((k = 0; k < 50; k++)); do [[ "$(pgrep -f -c 'cikarim_canli_denetim[.]py' || true)" == "0" ]] && break; sleep 0.1; done
    snapshot "k_$et"
    if ! diff -q "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" >/dev/null; then ok=0; log_fail "$et: artık süreç var: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" | tr '\n' ';' || true)"; fi
    yeni="$(port_yeni "$TMP_DIR/once.ports" "$TMP_DIR/k_$et.ports")"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: yeni dinleyen port(lar): $yeni"; fi
    yeni="$(comm -13 "$TMP_DIR/once.shm" "$TMP_DIR/k_$et.shm" | tr '\n' ' ')"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: /dev/shm artığı: $yeni"; fi
    if [[ "$(pgrep -a -x ruby; pgrep -af '[g]z sim')" != "" ]]; then ok=0; log_fail "$et: gz sim süreci kaldı"; fi
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0 (gz/ruby/px4/mavsdk_server/araç süreci/çıkarım işçisi/koordinatör), yeni dinleyen port 0, /dev/shm artığı 0"; fi
    return 0
}

KOSU_DIR=""
PART=""
kosu_baslat() { # kosu_baslat <ad> [kosu.sh argümanları...]
    local ad="$1" out id rc=0 l; shift
    out="$("$KOSU" baslat "$@" 2>&1)" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: baslat başarısız (çıkış $rc)"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; return 1
    fi
    id="$(cat "$KOK/aktif")"
    KOSU_DIR="$KOK/$id"
    PART="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" gz_partition)"
    log_ok "$ad: baslat tamam, koşu $id"
    return 0
}

komut_dene() {
    local log="$1" ok="$2" hata="$3"; shift 3
    if "$@" > "$log" 2>&1; then log_ok "$ok"; else log_fail "$hata"; tail -n 8 "$log"; fi
}

json_gecerli() { # json_gecerli <ad> <beklenen_bitis_durumu>
    local ad="$1" bekl="$2" out bd l
    if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kosu.json" 2>&1)"; then log_ok "$ad: kosu.json doğrulayıcıdan geçti"; else log_fail "$ad: kosu.json GEÇERSİZ"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; fi
    bd="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" bitis_durumu)"
    if [[ "$bd" == "$bekl" ]]; then log_ok "$ad: bitiş durumu '$bd'"; else log_fail "$ad: bitiş durumu '$bd' (beklenen '$bekl')"; fi
}

GZ_IP_AYAR=(GZ_IP=127.0.0.1)   # araç süreçleri için boşaltılır (GZ_IP verilmeden başlatılır: arac.py kendisi 127.0.0.1 yapar)
# ros_baslat <çıktı_dosyası> <komut...> : setsid ile ayrı süreç grubunda, ROS + venv ortamında; LAST_PG = grup lideri
LAST_PG=""
ros_baslat() {
    local cikti="$1"; shift
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    setsid env -u GZ_IP GZ_PARTITION="$PART" ${GZ_IP_AYAR[@]+"${GZ_IP_AYAR[@]}"} LC_NUMERIC=C "${EK_ENV[@]+"${EK_ENV[@]}"}" bash -c 'source "$1" >/dev/null 2>&1; source "$2/install/setup.bash"; shift 2; exec "$@"' _ "$ENV_SH" "$ROOT_DIR" "$@" \
        > "$cikti" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
}

tc_bayt() { # sürü sınıfı (1:10) için gönderilen bayt sayısı
    tc -s class show dev lo 2>/dev/null | awk '/^class htb 1:10 / {f=1} f && /Sent/ {print $2; exit}'
}

# senaryo_calistir <ad> <araç_sayısı> <koordinatör_argümanları...> : araç süreçleri (GZ_IP verilmeden) + canlı denetim + koordinatör; koordinatör çıkışı beklenir
senaryo_calistir() {
    local ad="$1" n="$2" i kpg kmax rc=0 t0=$SECONDS tc0 tc1; shift 2
    local -a apid=()
    tc0="$(tc_bayt)"
    ros_baslat "$KOSU_DIR/koordinator.out" timeout -k 5 1200 python "$KOORD" --arac "$n" --zaman-asimi-sn 1100 "$@"
    kpg="$LAST_PG"
    sleep 4
    for ((i = 1; i <= n; i++)); do
        local ozel=("${GZ_IP_AYAR[@]}")
        GZ_IP_AYAR=()                                   # araç süreci GZ_IP'siz başlar
        ros_baslat "$KOSU_DIR/arac_$i.out" python -m swarm_vehicle.arac "$i"
        GZ_IP_AYAR=("${ozel[@]}")
        apid+=("$LAST_PG")
        setsid python3 -I "$CANLI" "$LAST_PG" "$KOSU_DIR/canli_${SYS_IDS[$((i - 1))]}.json" > /dev/null 2>&1 < /dev/null &
        PGIDS+=("$!")
    done
    log_info "$ad: koordinatör pid $kpg, araç süreçleri pid ${apid[*]} (GZ_IP verilmeden); enjeksiyon: ${EK_ENV[*]:-kapalı}"
    wait "$kpg" 2>/dev/null || rc=$?
    for ((i = 0; i < n; i++)); do
        local arc=0
        for ((kmax = 0; kmax < 300; kmax++)); do kill -0 "${apid[$i]}" 2>/dev/null || break; sleep 0.1; done
        if kill -0 "${apid[$i]}" 2>/dev/null; then log_fail "$ad: araç $((i + 1)) süreci TAMAMLANDI'dan sonra 30 sn içinde kapanmadı"; else wait "${apid[$i]}" 2>/dev/null || arc=$?; fi
        if [[ "$arc" -eq 0 ]]; then log_ok "$ad: araç $((i + 1)) süreci kendiliğinden kapandı (çıkış 0)"; else log_fail "$ad: araç $((i + 1)) süreci çıkış kodu $arc"; tail -n 6 "$KOSU_DIR/arac_$((i + 1)).out"; fi
    done
    if [[ "$rc" -eq 0 ]]; then log_ok "$ad: koordinatör çıkış 0 ($((SECONDS - t0)) sn gerçek)"; else log_fail "$ad: koordinatör çıkış kodu $rc"; tail -n 8 "$KOSU_DIR/koordinator.out"; fi
    tc1="$(tc_bayt)"
    log_info "$ad: sürü sınıfı (tc 1:10) gönderilen bayt: $tc0 → $tc1"
    PGIDS=()
}

analiz() { # analiz <ad> <analiz argümanları...> : SONUC satırlarını (+)/(-) yapar
    local ad="$1" line rc=0; shift
    python3 -I "$ANALIZ" "$KOSU_DIR" "$@" > "$TMP_DIR/$ad.analiz.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            "OLCUM "*) log_info "$ad: ${line#OLCUM }" ;;
            Traceback*|*Error*) log_fail "$ad: analiz hatası: $line" ;;
        esac
    done < "$TMP_DIR/$ad.analiz.log"
    if [[ "$rc" -ne 0 ]]; then log_fail "$ad: analiz çıkış kodu $rc"; tail -n 12 "$TMP_DIR/$ad.analiz.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
}

kayit_dosyalari_gecerli() { # kayit_dosyalari_gecerli <ad> <n> : gerçek koşu kayıtları (damga, alıcılar, işçiler, kare sonuçları, kaynak) doğrulayıcıdan geçer
    local ad="$1" n="$2" i out f
    for f in "$KOSU_DIR/kayit/gazebo_damga.jsonl" $(for ((i = 1; i <= n; i++)); do for t in kamera_alici cikarim_iscisi kare_sonuc isci_kaynak; do echo "$KOSU_DIR/kayit/${t}_${SYS_IDS[$((i - 1))]}.jsonl"; done; done); do
        if out="$(python3 -I "$DOGRULA" "$f" 2>&1)"; then
            log_ok "$ad: gerçek kayıt doğrulayıcıdan geçti: ${f##*/} ($(tail -n 1 <<< "$out" | sed 's/, .*jsonl)/)/'))"
        else
            log_fail "$ad: kayıt GEÇERSİZ: ${f##*/}: $(head -n 3 <<< "$out" | tr '\n' ';')"
        fi
    done
}

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

# --- Testler ----------------------------------------------------------------------------
test_birim() {
    local out rc=0 l mod
    log_info "== birim: birim testleri, derleme, içe aktarma, statik denetimler =="
    for mod in "$BIRIM_TEST" "$BIRIM_TEST2" "$BIRIM_TEST3"; do
        if out="$("$VENV_PY" -I "$mod" 2>&1)"; then log_ok "birim: ${mod##*/} geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: ${mod##*/} BAŞARISIZ"; tail -n 20 <<< "$out"; fi
    done
    out="$GENERATED_DIR/isci_derleme.txt"
    if proje_derle "$out"; then
        log_ok "birim: proje derlendi (swarm_msgs + swarm_vehicle + swarm_gcs; ortak yol: setup/lib/derleme.sh)"
    else
        log_fail "birim: proje derlemesi BAŞARISIZ; günlük: ${out#"$ROOT_DIR"/}"
        tail -n 12 "$out" | while IFS= read -r l; do log_info "  | $l"; done
    fi
    for mod in kamera_alici durum_makinesi rota cikarim_yardimci cikarim_istemci cikarim_isci kare_sonuc kare_isleyici; do
        rc=0
        # shellcheck disable=SC2016  # tek tırnak bilerek: Python kodu
        "$VENV_PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import importlib; importlib.import_module("swarm_vehicle." + sys.argv[2]); assert not ({"rclpy", "mavsdk", "gz", "torch", "numpy", "ultralytics", "onnxruntime", "cv2"} & set(sys.modules))' \
            "$PKG_DIR" "$mod" > "$TMP_DIR/ice_$mod.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "birim: swarm_vehicle.$mod rclpy/mavsdk/gz/torch/numpy olmadan içe aktarıldı"; else log_fail "birim: swarm_vehicle.$mod içe aktarma hatası"; tail -n 5 "$TMP_DIR/ice_$mod.log"; fi
    done
    out="$(git -C "$ROOT_DIR" grep --untracked -nE '^\s*(import|from)\s+(rclpy|rcl_interfaces|swarm_msgs|gz|mavsdk)\b' -- 'src/swarm_vehicle/swarm_vehicle/cikarim/cikarim_*.py' 'src/swarm_vehicle/swarm_vehicle/cikarim/kare_sonuc.py' 'src/swarm_vehicle/swarm_vehicle/cikarim/kare_isleyici.py' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: işçi/istemci/yardımcı/kare sonucu modüllerinde rclpy, swarm_msgs, gz, mavsdk içe aktarımı yok"; else log_fail "birim: yasak içe aktarım: $out"; fi
    rc=0
    "$VENV_PY" -m py_compile "$PKG_DIR/swarm_vehicle/arac.py" "$PKG_DIR/swarm_vehicle/cikarim/cikarim_isci.py" "$PKG_DIR/swarm_vehicle/cikarim/cikarim_istemci.py" "$PKG_DIR/swarm_vehicle/cikarim/cikarim_yardimci.py" "$PKG_DIR/swarm_vehicle/cikarim/kare_sonuc.py" \
        "$PKG_DIR/swarm_vehicle/cikarim/kare_isleyici.py" "$PKG_DIR/swarm_vehicle/kamera/kamera_alici.py" "$PKG_DIR/swarm_vehicle/kamera/kamera_alici_gz.py" "$PKG_DIR/swarm_vehicle/ucus/px4_adapter.py" "$ANALIZ" "$CANLI" "$ISCI_DENEME" "$DOGRULA" > "$TMP_DIR/pyc.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: py_compile temiz"; else log_fail "birim: py_compile hata"; tail -n 5 "$TMP_DIR/pyc.log"; fi
    rc=0
    bash -n "${BASH_SOURCE[0]}" && bash -n "$SETUP_DIR/yayim_olcum_testi.sh" && bash -n "$SETUP_DIR/runtime_smoke.sh" || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: bash -n temiz (bu betik, yayim_olcum_testi.sh, runtime_smoke.sh)"; else log_fail "birim: bash -n hata"; fi
    if command -v shellcheck >/dev/null 2>&1; then
        rc=0
        (cd "$SETUP_DIR" && shellcheck -x -S warning cikarim_isci_testi.sh yayim_olcum_testi.sh runtime_smoke.sh) > "$TMP_DIR/shellcheck.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "birim: shellcheck -x -S warning temiz (bu betik, yayim_olcum_testi.sh, runtime_smoke.sh; info düzeyi bulgular önceki betiklerle aynı türde)"; else log_fail "birim: shellcheck bulgusu"; head -n 20 "$TMP_DIR/shellcheck.log"; fi
    else
        log_warn "birim: shellcheck yok; atlandı"
    fi
    rc=0
    "$VENV_PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); from swarm_vehicle import arac' "$PKG_DIR" || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: swarm_vehicle.arac içe aktarılır (rclpy yalnız calistir içinde)"; else log_fail "birim: arac içe aktarma hatası"; fi
}

test_isci() {
    local line rc=0
    log_info "== isci: simülasyonsuz işçi denemesi (GPU + ONNX Runtime CPU) =="
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1 alt kabukta açılır
    env -u VIRTUAL_ENV YOLO_OFFLINE=1 bash -c 'source "$1" >/dev/null 2>&1; shift; exec python "$@"' _ "$ENV_SH" "$ISCI_DENEME" --tekrar 60 --cpu-yolu > "$TMP_DIR/isci.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "isci: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "isci: ${line#SONUC kaldi }" ;;
            "OLCUM "*) log_info "isci: ${line#OLCUM }" ;;
            Traceback*|*Error*) log_fail "isci: hata: $line" ;;
        esac
    done < "$TMP_DIR/isci.log"
    if [[ "$rc" -ne 0 ]]; then log_fail "isci: deneme çıkış kodu $rc"; tail -n 12 "$TMP_DIR/isci.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
}

test_duzeltme() {
    local rc out ad
    log_info "== duzeltme: geriye dönük inceleme düzeltmeleri (simülasyonsuz) =="
    rc=0
    out="$("$SETUP_DIR/yayim_olcum_testi.sh" 2>&1)" || rc=$?
    if [[ "$rc" -eq 2 && "$out" != *"(-)"* && "$out" == *"442da7e"* && "$out" == *"yeniden üretilemez"* ]]; then log_ok "duzeltme: yayim_olcum_testi.sh tam koşusu açık iletiyle durdu (çıkış 2, (i) iletisi, (-) yok, hiçbir süreç başlatılmadı)"; else log_fail "duzeltme: tam koşu beklenen gibi durmadı (çıkış $rc): $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
    if [[ "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4)" == "" ]]; then log_ok "duzeltme: tam koşu denemesinden sonra gz/ruby/px4 süreci yok"; else log_fail "duzeltme: gz/ruby/px4 süreci kaldı"; fi
    rc=0
    out="$("$SETUP_DIR/yayim_olcum_testi.sh" --verify 2>&1)" || rc=$?
    if [[ "$rc" -eq 0 && "$out" != *"(-)"* ]]; then log_ok "duzeltme: yayim_olcum_testi.sh --verify çalışmaya devam ediyor ((-) yok)"; else log_fail "duzeltme: --verify çıkış $rc: $(grep -F '(-)' <<< "$out" | head -n 3 | tr '\n' ';')"; fi
    rc=0
    "$SETUP_DIR/yayim_olcum_testi.sh" --dry-run > "$TMP_DIR/yayim_dry.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "duzeltme: yayim_olcum_testi.sh --dry-run çalışmaya devam ediyor"; else log_fail "duzeltme: --dry-run çıkış $rc"; fi
    for ad in PX4A_HEARTBEAT_SN PX4A_BASLAT_TOLERANS_M ISCI_ARKA_UC ISCI_CPU_SABITLE; do
        if grep -qE "^${ad}=" "$DENEY_ENV"; then log_ok "duzeltme: deney.env anahtarı var: $ad=${!ad}"; else log_fail "duzeltme: deney.env anahtarı yok: $ad"; fi
    done
    out="$(git -C "$ROOT_DIR" grep -nE 'time\.monotonic\(\) \+ 5\b|_kabul_m \+ 1\.0|_yukseklik_tol \+ 1\.0' -- src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py || true)"
    if [[ -z "$out" ]]; then log_ok "duzeltme: px4_adapter.py'de sabit '+ 5' sn bekleme ve '+ 1.0' tolerans kalmadı (deney.env'den okunur)"; else log_fail "duzeltme: sabit değer kaldı: $out"; fi
    out="$(grep -nF 'PX4_SIM_MODEL=gz_x500' "$SETUP_DIR/runtime_smoke.sh" | grep -vE '^[0-9]+:\s*#' || true)"
    if [[ -z "$out" ]] && grep -q 'SIM_MODEL_TEMEL' "$SETUP_DIR/runtime_smoke.sh"; then log_ok "duzeltme: runtime_smoke.sh sabit gz_x500 yerine SIM_MODEL_TEMEL kullanıyor"; else log_fail "duzeltme: runtime_smoke.sh'ta sabit gz_x500 kaldı: $out"; fi
    rc=0
    "$SETUP_DIR/lock_ozet.sh" --check > "$TMP_DIR/lock.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "duzeltme: lock_ozet.sh --check (+)"; else log_fail "duzeltme: lock_ozet.sh --check kaldı"; tail -n 5 "$TMP_DIR/lock.log"; fi
}

isci_kapanis_kontrol() { # isci_kapanis_kontrol <ad> <araç_sayısı> : her araç günlüğünde işçi kapandı kaydı
    local ad="$1" n="$2" i
    for ((i = 1; i <= n; i++)); do
        if grep -q ' isci_kapandi ' "$KOSU_DIR/arac_${SYS_IDS[$((i - 1))]}.log"; then log_ok "$ad: araç $i işçisi araç süreciyle birlikte temiz kapandı (isci_kapandi kaydı)"; else log_fail "$ad: araç $i günlüğünde isci_kapandi yok"; fi
    done
}

test_tek() {
    local ad=tek
    log_info "== tek: araç 1, enjeksiyon kapalı, GZ_IP verilmeden =="
    EK_ENV=()
    if kosu_baslat "$ad" --arac 1; then
        senaryo_calistir "$ad" 1
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
        analiz "$ad" --arac 1 --gz-ip-yok
        kayit_dosyalari_gecerli "$ad" 1
        isci_kapanis_kontrol "$ad" 1
        if grep -q 'isci_enjeksiyon_durumu durum=kapali' "$KOSU_DIR/arac_${SYS_IDS[0]}.log"; then log_ok "$ad: işçi hata enjeksiyonunun KAPALI olduğu araç günlüğüne yazıldı"; else log_fail "$ad: işçi enjeksiyon durumu günlükte yok"; fi
    fi
    kalan_yok "$ad"
}

test_hata() {
    local ad=hata
    log_info "== hata: araç 1, kamera ve işçi hata enjeksiyonu AÇIK =="
    EK_ENV=(KAMERA_ENJEKSIYON='dusur=+20' ISCI_ENJEKSIYON='hata=+40;olum=+80')
    if kosu_baslat "$ad" --arac 1; then
        senaryo_calistir "$ad" 1
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
        analiz "$ad" --arac 1 --enjeksiyon
        kayit_dosyalari_gecerli "$ad" 1
        isci_kapanis_kontrol "$ad" 1
        if grep -q 'isci_enjeksiyon_durumu durum=hata=+40;olum=+80' "$KOSU_DIR/arac_${SYS_IDS[0]}.log" && grep -q 'kamera_enjeksiyon durum=bekle=0;dusur=+20' "$KOSU_DIR/arac_${SYS_IDS[0]}.log"; then
            log_ok "$ad: enjeksiyonların AÇIK olduğu (kamera ve işçi) araç günlüğüne yazıldı"
        else
            log_fail "$ad: araç günlüğünde enjeksiyon kayıtları eksik"
        fi
    fi
    EK_ENV=()
    kalan_yok "$ad"
}

test_uc() {
    local ad=uc i sonuc
    [[ "${#SYS_IDS[@]}" -ge 3 ]] || { log_fail "uc: yapılandırmada 3 araç yok"; return; }
    log_info "== uc: üç araç, üç işçi, enjeksiyon kapalı =="
    EK_ENV=()
    if kosu_baslat "$ad" --arac 3; then
        senaryo_calistir "$ad" 3
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
        analiz "$ad" --arac 3
        kayit_dosyalari_gecerli "$ad" 3
        isci_kapanis_kontrol "$ad" 3
        sonuc="$(python3 -I -c '
import json, sys
k = sys.argv[1]
kume = {}
for a in sys.argv[2:5]:
    c = json.load(open(f"{k}/canli_{a}.json", encoding="utf-8"))
    kume[a] = sorted({x for i in c["isciler"].values() for x in i["cpu"]})
hepsi = [x for v in kume.values() for x in v]
print("cakisma_yok" if len(hepsi) == len(set(hepsi)) and all(len(v) == 2 for v in kume.values()) else "CAKISMA", kume)
' "$KOSU_DIR" "${SYS_IDS[@]}")"
        if [[ "$sonuc" == cakisma_yok* ]]; then log_ok "$ad: üç işçinin CPU çiftleri çakışmıyor (sched_getaffinity = taskset -p): ${sonuc#cakisma_yok }"; else log_fail "$ad: işçi CPU kümeleri: $sonuc"; fi
        for ((i = 1; i <= 3; i++)); do
            if grep -q 'isci_enjeksiyon_durumu durum=kapali' "$KOSU_DIR/arac_${SYS_IDS[$((i - 1))]}.log"; then log_ok "$ad: araç $i günlüğünde işçi enjeksiyonu KAPALI kaydı var"; else log_fail "$ad: araç $i günlüğünde işçi enjeksiyon durumu yok"; fi
        done
    fi
    kalan_yok "$ad"
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server; pgrep -af 'swarm_vehicle[.]arac|swarm_vehicle[.]cikarim_isci|koordinator_deneme[.]py')" ]]; then
    fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server/araç süreci/işçi/koordinatör yaşıyor; önce kapatın"
fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), ROS $ROS_DISTRO, PX4 $PX4_TAG; GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1); testler: ${TESTS[*]}"

if want birim; then test_birim; fi
if want isci; then test_isci; fi
if want duzeltme; then test_duzeltme; fi
if want tek; then test_tek; fi
if want hata; then test_hata; fi
if want uc; then test_uc; fi

# --- Son denetim ------------------------------------------------------------------------------
snapshot sonra
if diff -q "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" >/dev/null; then
    log_ok "tc/ip durumu (lo) değişmedi"
else
    log_fail "lo üzerindeki tc/ip durumu değişti: $(diff "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" | tr '\n' ';' || true)"
fi
if diff -q "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" >/dev/null; then log_ok "test sonrası süreç sayıları başlangıçla aynı (işçi dahil)"; else log_fail "test sonrası süreç farkı: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/sonra.proc" | tr '\n' ';' || true)"; fi
if [[ "$DAEMON_ONCE" -eq 0 ]]; then
    if pgrep -f '[r]os2-daemon' >/dev/null; then log_fail "Artık ros2 daemon süreci var"; else log_ok "ros2 daemon süreci yok"; fi
fi

component_finish "$COMPONENT_NAME" "tamamlandı (${TESTS[*]} ve süreç/port/shm/tc denetimi)"
