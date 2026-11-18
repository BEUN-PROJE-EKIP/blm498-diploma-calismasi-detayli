#!/usr/bin/env bash
# yer_istasyonu_testi.sh — yer istasyonu görev koordinatörü, izleme, komut yolu iskeleti ve koşuya bağlama kabul testleri (başsız Gazebo + PX4 SITL + yer istasyonu + araç süreçleri; hepsi araclar/kosu.sh ile).
# Kullanım: ./yer_istasyonu_testi.sh [--dry-run | --verify | -h] [birim] [uc] [komut] [mission] [bayat]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz, hiçbir şey derlemez; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, kurulu paketler); süreç başlatmaz
# Testler:
#   birim     birim testleri (koordinatör mantığı, izleme, görev kaydı, Mission ↔ bolge_rota.json, komut denetimi, sonuç defteri), colcon build (3 paket), saf modüllerin rclpy'siz içe aktarımı, py_compile,
#             tek komut yolu (MAVSDK yalnız px4_adapter.py; komut_isle `_yaz` çağırmaz), süreç izi taraması, kosu.sh --dry-run (süreç sırası)
#   uc        `kosu.sh baslat --arac 3 --yer-istasyonu var` → `bekle` → `durdur`, enjeksiyon kapalı, tam rota: Mission ulaştı, t0 → bitişler → son sonuç → t1 → TAMAMLANDI, ortak başlangıç/bitiş, T, izleme geçişleri
#   komut     uc + koşu sürerken (t0'dan sonra) araç 2'ye `komut_gonder --sira 1` iki kez: ACK_REJECTED (tür tanımsız), ACK_REJECTED (tekrar sıra); diğer araçlar tepkisiz; PX4 yazma olayı yeni yok
#   mission   GOREV_ENJEKSIYON=sapma=2: araç 2'nin Mission'ı yerel dosyayla uyuşmaz → araç yüklemez (çıkış 4), koşu başlamaz (t0 yok), koordinatör süreç çıkışını açık hata (arac_erken_cikti) olarak yazıp gecikmesiz biter (GCS_UST_SN=150 beklenmez), temiz kapanış
#   bayat     ARAC_DURUM_SUS=2:60:15: araç 2'nin durum yayımı tarama başından 60 sn sonra 15 sn susar → izleme bayat uyarısı; akış değişmez
# Süreçler `setsid` ile ayrı gruplarda başlar; her çıkışta (hata, Ctrl-C dahil) `kosu.sh temizle` çalıştırılır. Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ. sudo gerekmez.
# Ölçüm disiplini: Gazebo görsel istemcisi (gz sim -g) açıkken ölçüm yapılmaz.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/derleme.sh
source "$SETUP_DIR/lib/derleme.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        birim|uc|komut|mission|bayat) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(birim uc komut mission bayat)
COMPONENT_NAME="Yer istasyonu görev koordinatörü"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
ANALIZ="$ROOT_DIR/araclar/analiz/yer_istasyonu_analiz.py"
VENV_PY="$ROOT_DIR/.venv/bin/python"
ENV_SH="$SETUP_DIR/env.sh"
DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
ROS_SETUP="/opt/ros/$ROS_DISTRO/setup.bash"
KOK="$GENERATED_DIR/kosular"
TMP_DIR=""
BIRIM_TESTLER=("$ROOT_DIR/src/swarm_gcs/test/test_gorev_mantik.py" "$ROOT_DIR/src/swarm_gcs/test/test_sonuc_defteri.py" "$ROOT_DIR/src/swarm_vehicle/test/test_gorev.py" "$ROOT_DIR/src/swarm_vehicle/test/test_sonuc_yayin.py" "$ROOT_DIR/src/swarm_vehicle/test/test_rota_yon.py")

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

exit_hook() {
    [[ "$DRY_RUN" -eq 0 && "$MODE" != verify ]] || return 0   # --dry-run/--verify hiçbir süreç başlatmaz; yaşayan (başkasına ait) koşuya DOKUNMAZ
    if [[ -f "$KOK/aktif" ]]; then "$KOSU" temizle >/dev/null 2>&1 || true; fi
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
    TMP_DIR=""
}

[[ -f "$DENEY_ENV" ]] || fail_stop "Yapılandırma yok: $DENEY_ENV"
# shellcheck source=/dev/null
source "$DENEY_ENV"
N_ARAC=3

# venv dışı PATH (ROS araçları sistem Python'unu kullansın)
clean_path() { local p="" d; local IFS=':'; for d in $PATH; do [[ "$d" == "$ROOT_DIR/.venv"* || "$d" == "$ROOT_DIR/.venv-px4/"* ]] || p+="${p:+:}$d"; done; echo "$p"; }
# shellcheck disable=SC2016  # tek tırnak bilerek: $1 alt kabukta açılır
ros_run() { env -u VIRTUAL_ENV PATH="$(clean_path)" bash -c 'source "$1"; shift; "$@"' _ "$ROS_SETUP" "$@"; }

check_prereqs() {
    local c f
    for c in gz ss pgrep python3 awk colcon tc; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "setup/env.sh" test -f "$ENV_SH"
    check "ROS 2 setup.bash" test -f "$ROS_SETUP"
    check "Kurulu paketler (install/setup.bash; colcon build)" test -f "$ROOT_DIR/install/setup.bash"
    for f in "$KOSU" "$ANALIZ" "${BIRIM_TESTLER[@]}" "$ROOT_DIR/src/swarm_gcs/swarm_gcs/gorev_koordinatoru.py" "$ROOT_DIR/src/swarm_gcs/swarm_gcs/komut_gonder.py"; do
        check "Dosya: ${f#"$ROOT_DIR"/}" test -f "$f"
    done
    # shellcheck disable=SC2016  # tek tırnak bilerek: alt kabukta açılır
    check "Yapılandırılmış sürü ağı (lo üzerinde htb)" bash -c '[[ "$(tc qdisc show dev lo)" == *htb* ]]'
    check "kosu.sh --dry-run baslat --yer-istasyonu var çıkış 0" "$KOSU" --dry-run baslat --arac 3 --yer-istasyonu var
}

print_plan() {
    log_info "[dry-run] birim: ${BIRIM_TESTLER[*]##*/}; colcon build (swarm_msgs swarm_vehicle swarm_gcs); rclpy'siz içe aktarım; py_compile; tek komut yolu; süreç izi; kosu.sh --dry-run sırası"
    log_info "[dry-run] uc: kosu.sh baslat --arac 3 --yer-istasyonu var → kosu.sh bekle → analiz (yer_istasyonu_analiz.py) → kosu.sh durdur"
    log_info "[dry-run] komut: uc + t0'dan sonra araç 2'ye python -m swarm_gcs.komut_gonder --arac 2 --sira 1 (iki kez)"
    log_info "[dry-run] mission: GOREV_ENJEKSIYON=sapma=2 GCS_UST_SN=150 → araç 2 Mission uyuşmazlığı (çıkış 4), t0 yok, açık hata (arac_erken_cikti)"
    log_info "[dry-run] bayat: ARAC_DURUM_SUS=2:60:15 → izleme bayat uyarısı"
    log_info "[dry-run] Her testten sonra araç süreci/yer istasyonu/px4/gz/mavsdk_server artığı, yeni dinleyen port, /dev/shm; sonda ros2 daemon, tc/ip denetimi. Hiçbir süreç başlatılmadı"
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
        echo "proc yer_istasyonu $(pgrep -f -c 'swarm_gcs[.]gorev_koordinatoru' || true)"
        echo "proc komut $(pgrep -f -c 'swarm_gcs[.]komut_gonder' || true)"
        echo "proc isci $(pgrep -f -c 'swarm_vehicle[.]cikarim_isci' || true)"
    } > "$TMP_DIR/$n.proc"
    port_snapshot "$TMP_DIR/$n.ports"
    shm_list > "$TMP_DIR/$n.shm"
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$TMP_DIR/$n.net"
}

kalan_yok() { # kalan_yok <etiket>
    local et="$1" ok=1 yeni
    sleep 1
    snapshot "k_$et"
    if ! diff -q "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" >/dev/null; then ok=0; log_fail "$et: artık süreç var: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" | tr '\n' ';' || true)"; fi
    yeni="$(port_yeni "$TMP_DIR/once.ports" "$TMP_DIR/k_$et.ports")"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: yeni dinleyen port(lar): $yeni"; fi
    yeni="$(comm -13 "$TMP_DIR/once.shm" "$TMP_DIR/k_$et.shm" | tr '\n' ' ')"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: /dev/shm artığı: $yeni"; fi
    if [[ "$(pgrep -a -x ruby; pgrep -af '[g]z sim')" != "" ]]; then ok=0; log_fail "$et: gz sim süreci kaldı"; fi
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0 (gz/ruby/px4/mavsdk_server/araç süreci/işçi/yer istasyonu/komut aracı), yeni dinleyen port 0, /dev/shm artığı 0"; fi
    return 0
}

KOSU_DIR=""
tc_bayt() { tc -s class show dev lo 2>/dev/null | awk '/^class htb 1:10 / {f=1} f && /Sent/ {print $2; exit}'; }

json_gecerli() { # json_gecerli <ad> <beklenen_bitis_durumu|->
    local ad="$1" bekl="$2" out bd l f
    if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kosu.json" 2>&1)"; then log_ok "$ad: kosu.json doğrulayıcıdan geçti"; else log_fail "$ad: kosu.json GEÇERSİZ"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; fi
    bd="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" bitis_durumu)"
    if [[ "$bekl" == "-" ]]; then log_info "$ad: bitiş durumu '$bd' (olumsuz senaryo: değer denetlenmez)"; elif [[ "$bd" == "$bekl" ]]; then log_ok "$ad: bitiş durumu '$bd'"; else log_fail "$ad: bitiş durumu '$bd' (beklenen '$bekl')"; fi
    for f in "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" "$KOSU_DIR/kayit/yer_istasyonu_kare.jsonl"; do
        [[ -s "$f" ]] || { log_info "$ad: ${f#"$KOSU_DIR"/} yok ya da boş (bu senaryoda sonuç üretilmedi); doğrulanmadı"; continue; }
        if out="$(python3 -I "$DOGRULA" "$f" 2>&1)"; then log_ok "$ad: ${f#"$KOSU_DIR"/} doğrulayıcıdan geçti ($(tail -n 1 <<< "$out" | sed 's/, .*jsonl)/)/'))"; else log_fail "$ad: ${f#"$KOSU_DIR"/} GEÇERSİZ: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
    done
}

EK_ENV=()
# ros_calistir <komut...> : setup/env.sh + install ortamında, bu betiğin önünde (eşzamanlı) çalıştırır
ros_calistir() {
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    env -u VIRTUAL_ENV LC_NUMERIC=C bash -c 'source "$1" >/dev/null 2>&1; source "$2/install/setup.bash"; cd "$2"; shift 2; "$@"' _ "$ENV_SH" "$ROOT_DIR" "$@"
}

# tam_kosu <ad> <analiz_argümanları|-> <bekle_sn> <beklenen_bekle_çıkışı> [komut]: kosu.sh baslat (EK_ENV ile) → (komut) → bekle → analiz → durdur
tam_kosu() {
    local ad="$1" analiz_arg="$2" bekle_sn="$3" bekle_beklenen="$4" komut="${5:-}" rc=0 id line tc0 tc1 i adp oncesi=0 k
    local -a aa=()
    log_info "$ad: kosu.sh baslat --arac $N_ARAC --yer-istasyonu var; ek ortam: ${EK_ENV[*]:-yok}"
    tc0="$(tc_bayt)"
    env "${EK_ENV[@]+"${EK_ENV[@]}"}" "$KOSU" baslat --arac "$N_ARAC" --yer-istasyonu var > "$TMP_DIR/$ad.baslat.log" 2>&1 || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: baslat başarısız (çıkış $rc)"; tail -n 10 "$TMP_DIR/$ad.baslat.log"; return 0
    fi
    id="$(cat "$KOK/aktif")"
    KOSU_DIR="$KOK/$id"
    log_ok "$ad: baslat tamam, koşu $id (GZ_PARTITION=$id)"
    if [[ -n "$komut" ]]; then
        # t0'dan sonra (TARAMA sürerken) araç $komut'a iki komut gönder
        for ((i = 0; i < 1200; i++)); do
            if [[ -f "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" ]] && [[ "$(grep -c '"olay": "t0"' "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" || true)" -ge 1 ]]; then break; fi
            sleep 0.5
        done
        adp="$KOSU_DIR/px4_adapter_$komut.log"
        for ((i = 0; i < 40; i++)); do                    # t0'dan hemen sonra adaptör mission.start yazar; sayım ondan sonra alınır (yoksa yarış)
            if [[ -f "$adp" ]] && [[ "$(grep -c 'ad=mission.start' "$adp" || true)" -ge 1 ]]; then break; fi
            sleep 0.5
        done
        if [[ "$i" -ge 40 ]]; then log_warn "$ad: 20 sn içinde adaptör günlüğünde mission.start görülmedi; komut öncesi sayım eksik olabilir"; fi
        oncesi="$(awk '$3 == "komut" {n++} END {print n + 0}' "$adp" 2>/dev/null || true)"
        oncesi="${oncesi:-0}"
        for k in 1 2; do
            ros_calistir python -m swarm_gcs.komut_gonder --arac "$komut" --sira 1 --bekle-sn 20 > "$TMP_DIR/$ad.komut$k.log" 2>&1 || log_fail "$ad: komut $k gönderilemedi/onaylanmadı"
            log_info "$ad: $(grep '^KOMUT' "$TMP_DIR/$ad.komut$k.log" | tr '\n' ';')"
        done
    fi
    rc=0
    "$KOSU" bekle --sure-sn "$bekle_sn" > "$TMP_DIR/$ad.bekle.log" 2>&1 || rc=$?
    if [[ "$rc" -eq "$bekle_beklenen" ]]; then log_ok "$ad: kosu.sh bekle çıkış kodu $rc (beklenen $bekle_beklenen)"; else log_fail "$ad: kosu.sh bekle çıkış kodu $rc (beklenen $bekle_beklenen)"; tail -n 5 "$TMP_DIR/$ad.bekle.log"; fi
    tc1="$(tc_bayt)"
    rc=0
    if [[ "$analiz_arg" != "-" ]]; then read -r -a aa <<< "$analiz_arg"; fi
    if [[ -n "$komut" ]]; then aa+=(--komut "$komut" --komut-oncesi "$oncesi"); fi
    "$VENV_PY" -I "$ANALIZ" "$KOSU_DIR" --arac "$N_ARAC" "${aa[@]+"${aa[@]}"}" > "$TMP_DIR/$ad.analiz.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            "OLCUM "*) log_info "$ad: ${line#OLCUM }" ;;
            Traceback*|*Error*) log_fail "$ad: analiz hatası: $line" ;;
        esac
    done < "$TMP_DIR/$ad.analiz.log"
    if [[ "$rc" -gt 1 ]]; then log_fail "$ad: analiz çıkış kodu $rc"; tail -n 12 "$TMP_DIR/$ad.analiz.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
    log_info "$ad: tc htb 1:10 (sürü ağı) koşu boyunca: $((${tc1:-0} - ${tc0:-0})) bayt"
    if "$KOSU" durdur > "$TMP_DIR/$ad.durdur.log" 2>&1; then log_ok "$ad: durdur tamam"; else log_fail "$ad: durdur başarısız"; tail -n 8 "$TMP_DIR/$ad.durdur.log"; fi
    json_gecerli "$ad" "${BITIS_BEKLENEN:-tamamlandi}"
}

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

# --- Testler ----------------------------------------------------------------------------------------------------------
test_birim() {
    local out rc=0 l mod t govde
    log_info "== birim: birim testleri, derleme, içe aktarma, tek komut yolu, süreç izi =="
    for t in "${BIRIM_TESTLER[@]}"; do
        rc=0
        out="$("$VENV_PY" -I "$t" 2>&1)" || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "birim: ${t##*/} geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: ${t##*/} BAŞARISIZ"; tail -n 15 <<< "$out"; fi
    done
    out="$GENERATED_DIR/yer_istasyonu_derleme.txt"
    if proje_derle "$out"; then
        log_ok "birim: proje derlendi (swarm_msgs + swarm_vehicle + swarm_gcs; ortak yol: setup/lib/derleme.sh)"
    else
        log_fail "birim: proje derlemesi BAŞARISIZ; günlük: ${out#"$ROOT_DIR"/}"
        tail -n 12 "$out" | while IFS= read -r l; do log_info "  | $l"; done
    fi
    for mod in swarm_gcs.gorev.gorev_mantik swarm_gcs.gorev.izleme swarm_gcs.gorev.gorev_kayit swarm_gcs.birlestirme.sonuc_defteri swarm_vehicle.ucus.gorev swarm_vehicle.ucus.komut_yolu; do
        rc=0
        # shellcheck disable=SC2016  # tek tırnak bilerek: Python kodu
        "$VENV_PY" -I -c 'import sys; sys.path[:0] = sys.argv[1:3]; import importlib; importlib.import_module(sys.argv[3]); assert "rclpy" not in sys.modules and "mavsdk" not in sys.modules' \
            "$ROOT_DIR/src/swarm_vehicle" "$ROOT_DIR/src/swarm_gcs" "$mod" > "$TMP_DIR/ice_$mod.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "birim: $mod rclpy ve mavsdk olmadan içe aktarıldı"; else log_fail "birim: $mod içe aktarma hatası"; tail -n 5 "$TMP_DIR/ice_$mod.log"; fi
    done
    rc=0
    "$VENV_PY" -m py_compile "$ROOT_DIR"/src/swarm_gcs/swarm_gcs/*.py "$ROOT_DIR"/src/swarm_gcs/swarm_gcs/*/*.py "$ROOT_DIR"/src/swarm_vehicle/swarm_vehicle/*.py "$ROOT_DIR"/src/swarm_vehicle/swarm_vehicle/*/*.py "$ROOT_DIR/araclar/deneme/koordinator_deneme.py" "$ANALIZ" > "$TMP_DIR/pyc.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: py_compile temiz"; else log_fail "birim: py_compile hata"; tail -n 5 "$TMP_DIR/pyc.log"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '^\s*(from|import) mavsdk' -- src || true)"
    if [[ -n "$out" && "$(awk -F: '{print $1}' <<< "$out" | sort -u)" == "src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py" ]]; then log_ok "birim: src/ altında mavsdk'yı içe aktaran tek dosya px4_adapter.py (yer istasyonunun PX4'e doğrudan bağlantısı yok)"; else log_fail "birim: mavsdk içe aktarımı beklenenden farklı: $out"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '\.action\.|\.mission\b|\.mission_raw|\.param\.set|set_param|set_rate_|\.offboard\.|send_message' -- src ':!src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: src/ altında px4_adapter.py dışında PX4'e yazan çağrı yok"; else log_fail "birim: dış çağrı: $out"; fi
    govde="$(awk '/    def komut_isle\(/ {f=1; next} f && /^    (def|async def) |^    # ---/ {exit} f {print}' "$ROOT_DIR/src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py")"
    if [[ -n "$govde" && "$govde" != *"_yaz("* && "$govde" != *"self._sys"* && "$govde" != *"komut_sayaci"* ]]; then log_ok "birim: px4_adapter.komut_isle gövdesi _yaz, MAVSDK sistemi ve komut sayacına dokunmaz"; else log_fail "birim: komut_isle gövdesi PX4'e yazabilir: $govde"; fi
    # süreç izi: depoya giren kodda/belgede süreç ifadesi yok (ekran kartı gibi meşru kullanımlar hariç)
    out="$(cd "$ROOT_DIR" && git grep --untracked -nIiE '[d]enetleyici|[c]laude|\b[k]art(ta|tır|lar|ın)?\b|\b[T]-0[0-9]{2}b?\b' -- src araclar setup config planlama | grep -viE 'ekran kartı' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: süreç izi taraması temiz"; else log_fail "birim: süreç izi: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
    if out="$("$KOSU" --dry-run baslat --arac 3 --yer-istasyonu var 2>&1)" && [[ "$out" == *"sıra: gz_sunucu → px4_0..px4_2 → yer_istasyonu"* && "$out" == *"→ arac_1..arac_3"* && "$out" == *"durdur sırası: araç süreçleri → yer istasyonu"* ]]; then
        log_ok "birim: kosu.sh --dry-run başlatma ve durdurma sırasını yazıyor, süreç başlatmıyor"
    else
        log_fail "birim: kosu.sh --dry-run çıktısı beklenen sırayı içermiyor"
    fi
    if out="$("$KOSU" --dry-run baslat --arac 3 --yer-istasyonu yok 2>&1)" && [[ "$out" == *"yer istasyonu BAŞLATILMAZ"* ]]; then log_ok "birim: --yer-istasyonu yok: koordinatör başlatılmaz (dry-run)"; else log_fail "birim: --yer-istasyonu yok dry-run"; fi
}

test_uc() {
    local ad=uc
    log_info "== uc: tek komutla üç araç (kosu.sh baslat → bekle → durdur), enjeksiyon kapalı, tam rota =="
    EK_ENV=()
    tam_kosu "$ad" - 600 0 ; kalan_yok "$ad"
}

test_komut() {
    local ad=komut
    log_info "== komut: koşu sürerken araç 2'ye komut → ACK_REJECTED (komut yolu iskeleti) =="
    EK_ENV=()
    tam_kosu "$ad" - 600 0 2 ; kalan_yok "$ad"
}

test_mission() {
    local ad=mission
    log_info "== mission: araç 2'nin Mission'ı yerel dosyayla uyuşmaz → yükleme yok, koşu başlamaz, temiz kapanış =="
    EK_ENV=("GOREV_ENJEKSIYON=sapma=2" "GCS_UST_SN=150")
    BITIS_BEKLENEN=- tam_kosu "$ad" "--mission-hata 2" 300 1 ; EK_ENV=(); kalan_yok "$ad"
}

test_bayat() {
    local ad=bayat
    log_info "== bayat: araç 2'nin durum yayımı tarama başından 60 sn sonra 15 sn susar → izleme uyarısı, akış değişmez =="
    EK_ENV=("ARAC_DURUM_SUS=2:60:15")
    tam_kosu "$ad" "--bayat 2" 600 0 ; EK_ENV=(); kalan_yok "$ad"
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server; pgrep -af 'swarm_vehicle[.]arac|swarm_gcs[.]|koordinator_deneme[.]py|swarm_vehicle[.]cikarim_isci')" ]]; then
    fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server/araç süreci/işçi/yer istasyonu yaşıyor; önce kapatın (görsel istemci 'gz sim -g' açıksa kapatın)"
fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), ROS $ROS_DISTRO, PX4 $PX4_TAG; testler: ${TESTS[*]}"

if want birim; then test_birim; fi
if want uc; then test_uc; fi
if want komut; then test_komut; fi
if want mission; then test_mission; fi
if want bayat; then test_bayat; fi

# --- Son denetim ------------------------------------------------------------------------------
snapshot sonra
if diff -q "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" >/dev/null; then
    log_ok "tc/ip durumu (lo) değişmedi"
else
    log_fail "lo üzerindeki tc/ip durumu değişti: $(diff "$TMP_DIR/once.net" "$TMP_DIR/sonra.net" | tr '\n' ';' || true)"
fi
if [[ "$DAEMON_ONCE" -eq 0 ]]; then
    if pgrep -f '[r]os2-daemon' >/dev/null; then log_fail "Artık ros2 daemon süreci var"; else log_ok "ros2 daemon süreci yok"; fi
fi

component_finish "$COMPONENT_NAME" "tamamlandı (${TESTS[*]} ve süreç/port/shm/tc denetimi)"
