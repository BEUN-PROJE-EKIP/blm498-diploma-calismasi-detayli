#!/usr/bin/env bash
# dds_doygunluk_testi.sh — doygun hatta DDS canlılığı denemesi (M2 2.4; riskler U21/U14): merkezi modun ağ yükünü taklit eden sentetik TCP yükü (3 × 2 Hz × 921 600 B; araclar/sentetik_yuk.py) ile aynı anda gerçek üç araçlı
# uçta mod koşusu (araclar/kosu.sh + asıl yer istasyonu koordinatörü). Bu bir ÖLÇÜMDÜR: ölçüm "sorun var" gösterirse test hatası değildir, olduğu gibi raporlanır; öneri/hafifletme uygulanmaz. Ağ profiline DOKUNULMAZ
# (tc yalnız okunur: `tc -s class/qdisc show dev lo`, sudo gerekmez).
# Kullanım: ./dds_doygunluk_testi.sh [--dry-run | --verify | -h] [birim] [s0] [s1] [s2] [dryrun]
#   (argümansız)  birim s0 s1 s2 sırasıyla; adlar verilirse yalnız onlar. `dryrun` (madde 7 kanıtı) argümansız çalışmaz, adıyla istenir.
#   --dry-run     hiçbir süreç başlatmaz; ne çalıştıracağını yazar        --verify  hafif önkoşul denetimi
# Testler:
#   birim   sentetik yük üretici ve tc ayrıştırıcı birim testleri, py_compile, tek komut yolu, süreç izi, yük aracı başlığı/adres denetimi
#   s0      taban: yük yok; kosu.sh baslat --arac 3 --yer-istasyonu var → bekle → durdur
#   s1      sürekli doygunluk: yük hazırlık evresinde (t0'dan önce, araç süreçleri başladıktan sonra) başlar, COMPLETE'ten sonra durur (kuyruk boşalana dek gönderim sürer)
#   s2      başlangıçta doygunluk: yük kosu.sh baslat'tan ÖNCE başlar (araç süreçleri ve yer istasyonu başlamadan; keşif ve eşleşme doygun hatta kurulur)
#   dryrun  bir koşu yaşarken setup/*_testi.sh betiklerinin --dry-run ve --verify çağrıları koşuyu ÖLDÜRMEZ (exit_hook düzeltmesi kanıtı)
# Her ölçüm koşusunda tc örnekleyici (1 sn) çalışır; ham kayıtlar koşu klasörüne kopyalanır (tc_ornek.jsonl, sentetik_yuk.jsonl). s0, s1 ve s2 tamamlanınca karşılaştırma tabloları yazılır
# (.generated/dds_doygunluk_ozet.md). Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ. sudo gerekmez.
# Ölçüm disiplini: Gazebo görsel istemcisi (gz sim -g) açıkken ve başka ağır iş (derleme, ikinci test) sürerken ölçüm yapılmaz.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/derleme.sh
source "$SETUP_DIR/lib/derleme.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        birim|s0|s1|s2|dryrun) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(birim s0 s1 s2)
COMPONENT_NAME="Doygun hatta DDS canlılığı"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
YUK="$ROOT_DIR/araclar/sentetik_yuk.py"
TCIZLE="$ROOT_DIR/araclar/tc_izle.py"
ANALIZ="$ROOT_DIR/araclar/dds_doygunluk_analiz.py"
BOYUT="$ROOT_DIR/araclar/ileti_boyutlari.py"
VENV_PY="$ROOT_DIR/.venv/bin/python"
ENV_SH="$SETUP_DIR/env.sh"
ROS_SETUP="/opt/ros/$ROS_DISTRO/setup.bash"
DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
KOK="$GENERATED_DIR/kosular"
DURUM_DOSYASI="$GENERATED_DIR/dds_doygunluk_son.json"
OZET_MD="$GENERATED_DIR/dds_doygunluk_ozet.md"
TMP_DIR=""
PGIDS=()
BIRIM_TESTLER=("$ROOT_DIR/src/swarm_vehicle/test/test_sentetik_yuk.py")

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

check_prereqs() {
    local c f
    for c in ss pgrep python3 awk tc; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "setup/env.sh" test -f "$ENV_SH"
    check "Kurulu paketler (install/setup.bash; colcon build)" test -f "$ROOT_DIR/install/setup.bash"
    for f in "$KOSU" "$YUK" "$TCIZLE" "$ANALIZ" "$BOYUT" "${BIRIM_TESTLER[@]}"; do check "Dosya: ${f#"$ROOT_DIR"/}" test -f "$f"; done
    # shellcheck disable=SC2016  # tek tırnak bilerek: alt kabukta açılır
    check "Yapılandırılmış sürü ağı (lo üzerinde htb)" bash -c '[[ "$(tc qdisc show dev lo)" == *htb* ]]'
    # shellcheck disable=SC2016  # tek tırnak bilerek: alt kabukta açılır
    check "tc sayaçları sudo'suz okunuyor" bash -c 'o="$(tc -s class show dev lo)"; [[ "$o" == *"class htb 1:10"* ]]'
    check "kosu.sh --dry-run baslat çıkış 0" "$KOSU" --dry-run baslat --arac 3 --yer-istasyonu var
}

print_plan() {
    log_info "[dry-run] birim: ${BIRIM_TESTLER[*]##*/}; py_compile; tek komut yolu; süreç izi; araclar/sentetik_yuk.py başlığı ('B12 değildir') ve adreslerin yapılandırmadan okunması"
    log_info "[dry-run] s0: araclar/tc_izle.py (1 sn) + kosu.sh baslat --arac 3 --yer-istasyonu var (GCS_UST_SN=900) → bekle → durdur; yük yok"
    log_info "[dry-run] s1: s0 + sentetik yük (araclar/sentetik_yuk.py: 3 TCP, $UAV1_ADDR $UAV2_ADDR $UAV3_ADDR → $GCS_ADDR, 3 × ${CAM_RATE_HZ} Hz × $((CAM_WIDTH * CAM_HEIGHT * 3)) B) baslat'tan SONRA (hazırlık evresinde) başlar; bekle'den sonra SIGTERM, kuyruk boşalana dek"
    log_info "[dry-run] s2: s0 + sentetik yük baslat'tan ÖNCE başlar"
    log_info "[dry-run] dryrun: kosu.sh baslat --arac 1 (yalnız sim) iken setup/*_testi.sh --dry-run ve --verify; kosu.sh durum (+) olmalı; durdur"
    log_info "[dry-run] Her senaryodan sonra yük/örnekleyici/araç/yer istasyonu/px4/gz/mavsdk_server artığı, yeni dinleyen port, /dev/shm; sonda ros2 daemon, tc/ip denetimi. Hiçbir süreç başlatılmadı"
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
        echo "proc isci $(pgrep -f -c 'swarm_vehicle[.]cikarim_isci' || true)"
        echo "proc sentetik_yuk $(pgrep -f -c 'python[^ ]* -I [^ ]*araclar/sentetik_yu[k][.]py' || true)"
        echo "proc tc_izle $(pgrep -f -c 'python[^ ]* -I [^ ]*araclar/tc_izl[e][.]py' || true)"
    } > "$TMP_DIR/$n.proc"
    ss -lntuH 2>/dev/null | awk '{print $1, $5}' | LC_ALL=C sort > "$TMP_DIR/$n.ports" || true
    shm_list > "$TMP_DIR/$n.shm"
    { tc qdisc show dev lo 2>/dev/null | sed 's/direct_packets_stat [0-9]*//' || true; ip -4 addr show lo 2>/dev/null || true; } > "$TMP_DIR/$n.net"
}

kalan_yok() { # kalan_yok <etiket>
    local et="$1" ok=1 yeni k
    sleep 1
    for ((k = 0; k < 50; k++)); do [[ "$(pgrep -f -c 'cikarim_canli_denetim[.]py' || true)" == "0" ]] && break; sleep 0.1; done
    snapshot "k_$et"
    if ! diff -q "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" >/dev/null; then ok=0; log_fail "$et: artık süreç var: $(diff "$TMP_DIR/once.proc" "$TMP_DIR/k_$et.proc" | tr '\n' ';' || true)"; fi
    yeni="$(LC_ALL=C comm -13 "$TMP_DIR/once.ports" "$TMP_DIR/k_$et.ports" | tr '\n' ';' || true)"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: yeni dinleyen port(lar): $yeni"; fi
    yeni="$(comm -13 "$TMP_DIR/once.shm" "$TMP_DIR/k_$et.shm" | tr '\n' ' ')"
    if [[ -n "$yeni" ]]; then ok=0; log_fail "$et: /dev/shm artığı: $yeni"; fi
    if [[ "$(pgrep -a -x ruby; pgrep -af '[g]z sim')" != "" ]]; then ok=0; log_fail "$et: gz sim süreci kaldı"; fi
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0 (gz/ruby/px4/mavsdk_server/araç/işçi/yer istasyonu/yük üretici/tc örnekleyici), yeni dinleyen port 0, /dev/shm artığı 0"; fi
    return 0
}

KOSU_DIR=""

# venv dışı PATH (ROS araçları sistem Python'unu kullansın)
clean_path() { local p="" d; local IFS=':'; for d in $PATH; do [[ "$d" == "$ROOT_DIR/.venv"* || "$d" == "$ROOT_DIR/.venv-px4/"* ]] || p+="${p:+:}$d"; done; echo "$p"; }
# shellcheck disable=SC2016  # tek tırnak bilerek: $1 alt kabukta açılır
ros_run() { env -u VIRTUAL_ENV PATH="$(clean_path)" bash -c 'source "$1"; shift; "$@"' _ "$ROS_SETUP" "$@"; }

# ---- yük ve örnekleyici ----------------------------------------------------------------------------------------------------
YUK_PID=""
TC_PID=""
tc_baslat() { # tc_baslat <çıktı>
    setsid "$VENV_PY" -I "$TCIZLE" --cikti "$1" --aralik-sn 1 > /dev/null 2>&1 < /dev/null &
    TC_PID=$!
    PGIDS+=("$TC_PID")
}
tc_durdur() {
    if [[ -n "$TC_PID" ]]; then kill -TERM "$TC_PID" 2>/dev/null || true; wait "$TC_PID" 2>/dev/null || true; fi
    TC_PID=""
}
yuk_baslat() { # yuk_baslat <ad> <çıktı>
    local ad="$1" cikti="$2" i
    setsid env LC_NUMERIC=C "$VENV_PY" -I "$YUK" --cikti "$cikti" --bosalt-sn 600 > "$TMP_DIR/$ad.yuk.out" 2>&1 < /dev/null &
    YUK_PID=$!
    PGIDS+=("$YUK_PID")
    for ((i = 0; i < 120; i++)); do
        if grep -q '^SENTETIK hazir' "$TMP_DIR/$ad.yuk.out" 2>/dev/null; then break; fi
        kill -0 "$YUK_PID" 2>/dev/null || break
        sleep 0.25
    done
    if grep -q '^SENTETIK hazir' "$TMP_DIR/$ad.yuk.out" 2>/dev/null; then log_ok "$ad: sentetik yük başladı: $(grep '^SENTETIK hazir' "$TMP_DIR/$ad.yuk.out")"; else log_fail "$ad: sentetik yük başlayamadı"; tail -n 5 "$TMP_DIR/$ad.yuk.out"; fi
}
yuk_adres_denetimi() { # yük sürecinin soketleri yalnız 10.10.0.x adreslerinde mi
    local ad="$1" out disari
    [[ -n "$YUK_PID" ]] || return 0
    out="$(ss -H -t -a -n -p 2>/dev/null | awk -v p="pid=$YUK_PID," 'index($0, p) {print $4, $5}' | tr ' ' '\n' | sed 's/:[0-9*]*$//' | grep -vE '^(0\.0\.0\.0|\*)?$' | sort -u | tr '\n' ' ')"
    disari="$(tr ' ' '\n' <<< "$out" | grep -v '^$' | grep -v '^10\.10\.0\.' | tr '\n' ' ' || true)"
    if [[ -n "$out" && -z "$disari" ]]; then log_ok "$ad: yük sürecinin TCP soketleri yalnız sürü ağı adreslerinde: $out"; else log_fail "$ad: yük sürecinin soketleri sürü ağı dışında ya da yok: '$out' dışarıda: '$disari'"; fi
}
yuk_durdur() { # yuk_durdur <ad>
    local ad="$1" i
    [[ -n "$YUK_PID" ]] || return 0
    kill -TERM "$YUK_PID" 2>/dev/null || true
    log_info "$ad: sentetik yük durduruldu (yeni kare üretimi biter); uygulama kuyruğu boşalana dek (en çok 600 sn) bekleniyor"
    for ((i = 0; i < 1500; i++)); do kill -0 "$YUK_PID" 2>/dev/null || break; sleep 0.5; done
    if kill -0 "$YUK_PID" 2>/dev/null; then log_fail "$ad: yük üretici 750 sn içinde kapanmadı"; kill -KILL "$YUK_PID" 2>/dev/null || true; else log_ok "$ad: yük üretici kapandı: $(grep '^SENTETIK kapandi' "$TMP_DIR/$ad.yuk.out" | cut -c1-260)"; fi
    wait "$YUK_PID" 2>/dev/null || true
    YUK_PID=""
}

durum_kaydet() { # durum_kaydet <ad> <koşu_klasörü>
    "$VENV_PY" -I - "$DURUM_DOSYASI" "$1" "$2" <<'PY'
import json, os, sys
yol, ad, klasor = sys.argv[1:4]
d = json.load(open(yol, encoding="utf-8")) if os.path.isfile(yol) else {}
d[ad] = klasor
json.dump(d, open(yol, "w", encoding="utf-8"))
PY
}

# senaryo <ad: s0|s1|s2> <yük: yok|hazirlik|bas>
senaryo() {
    local ad="$1" yuk="$2" rc=0 id t0=$SECONDS
    local tc_cikti="$TMP_DIR/$ad.tc.jsonl" yuk_cikti="$TMP_DIR/$ad.yuk.jsonl"
    log_info "== $ad: yük=$yuk; kosu.sh baslat --arac 3 --yer-istasyonu var → bekle → durdur (GCS_UST_SN=900) =="
    tc_baslat "$tc_cikti"
    if [[ "$yuk" == bas ]]; then yuk_baslat "$ad" "$yuk_cikti"; fi
    env GCS_UST_SN=900 "$KOSU" baslat --arac 3 --yer-istasyonu var > "$TMP_DIR/$ad.baslat.log" 2>&1 || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: baslat başarısız (çıkış $rc)"; tail -n 10 "$TMP_DIR/$ad.baslat.log"
        yuk_durdur "$ad"; tc_durdur; return 0
    fi
    id="$(cat "$KOK/aktif")"
    KOSU_DIR="$KOK/$id"
    log_ok "$ad: baslat tamam, koşu $id"
    if [[ "$yuk" == hazirlik ]]; then yuk_baslat "$ad" "$yuk_cikti"; fi
    if [[ -n "$YUK_PID" ]]; then sleep 3; yuk_adres_denetimi "$ad"; fi
    rc=0
    "$KOSU" bekle --sure-sn 1100 > "$TMP_DIR/$ad.bekle.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "$ad: koşu tamamlandı (yer istasyonu çıkış 0, $((SECONDS - t0)) sn gerçek)"; else log_info "$ad: koşu TAMAMLANMADI (kosu.sh bekle çıkış kodu $rc); ölçüm olduğu gibi raporlanır"; fi
    yuk_durdur "$ad"
    tc_durdur
    cp "$tc_cikti" "$KOSU_DIR/tc_ornek.jsonl" 2>/dev/null || true
    if [[ -f "$yuk_cikti" ]]; then cp "$yuk_cikti" "$KOSU_DIR/sentetik_yuk.jsonl"; fi
    if "$KOSU" durdur > "$TMP_DIR/$ad.durdur.log" 2>&1; then log_ok "$ad: durdur tamam"; else log_fail "$ad: durdur başarısız"; tail -n 8 "$TMP_DIR/$ad.durdur.log"; fi
    durum_kaydet "$ad" "$KOSU_DIR"
    log_info "$ad: ham kayıtlar: ${KOSU_DIR#"$ROOT_DIR"/}/{kayit/yer_istasyonu_*.jsonl, tc_ornek.jsonl, sentetik_yuk.jsonl, arac_*.log, yer_istasyonu.log}"
}

analiz_calistir() {
    local s0 s1 s2 line rc=0 boyut="$TMP_DIR/boyutlar.json"
    [[ -f "$DURUM_DOSYASI" ]] || return 0
    s0="$("$VENV_PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("s0",""))' "$DURUM_DOSYASI")"
    s1="$("$VENV_PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("s1",""))' "$DURUM_DOSYASI")"
    s2="$("$VENV_PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("s2",""))' "$DURUM_DOSYASI")"
    [[ -n "$s0" && -n "$s1" && -n "$s2" ]] || { log_info "analiz: s0, s1 ve s2 henüz birlikte yok; karşılaştırma yazılmadı"; return 0; }
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    env -u VIRTUAL_ENV bash -c 'source "$1" >/dev/null 2>&1; source "$2/install/setup.bash"; python "$3"' _ "$ENV_SH" "$ROOT_DIR" "$BOYUT" > "$boyut" 2>/dev/null || true
    "$VENV_PY" -I "$ANALIZ" --s0 "$s0" --s1 "$s1" --s2 "$s2" --boyutlar "$boyut" --cikti "$OZET_MD" > "$TMP_DIR/analiz.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "analiz: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "analiz: ${line#SONUC kaldi }" ;;
            Traceback*|*Error*) log_fail "analiz hatası: $line" ;;
        esac
    done < "$TMP_DIR/analiz.log"
    if [[ "$rc" -gt 1 ]]; then log_fail "analiz çıkış kodu $rc"; tail -n 12 "$TMP_DIR/analiz.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
    if [[ -f "$OZET_MD" ]]; then log_ok "analiz: karşılaştırma tabloları yazıldı: ${OZET_MD#"$ROOT_DIR"/}"; fi
}

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

# --- Testler ----------------------------------------------------------------------------------------------------------
test_birim() {
    local out rc=0 t
    log_info "== birim: yük üretici ve tc ayrıştırıcı birim testleri, derleme, tek komut yolu, süreç izi =="
    for t in "${BIRIM_TESTLER[@]}"; do
        rc=0
        out="$("$VENV_PY" -I "$t" 2>&1)" || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "birim: ${t##*/} geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: ${t##*/} BAŞARISIZ"; tail -n 15 <<< "$out"; fi
    done
    out="$GENERATED_DIR/dds_doygunluk_derleme.txt"
    if proje_derle "$out"; then
        log_ok "birim: proje derlendi (swarm_msgs + swarm_vehicle + swarm_gcs; ortak yol: setup/lib/derleme.sh)"
    else
        log_fail "birim: proje derlemesi BAŞARISIZ; günlük: ${out#"$ROOT_DIR"/}"
        tail -n 12 "$out" | while IFS= read -r l; do log_info "  | $l"; done
    fi
    rc=0
    "$VENV_PY" -m py_compile "$YUK" "$TCIZLE" "$ANALIZ" "$BOYUT" > "$TMP_DIR/pyc.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: py_compile temiz"; else log_fail "birim: py_compile hata"; tail -n 5 "$TMP_DIR/pyc.log"; fi
    out="$(head -n 3 "$YUK")"
    if [[ "$out" == *'merkezi modun AĞ YÜKÜNÜ taklit eder, B12 değildir'* ]]; then log_ok "birim: araclar/sentetik_yuk.py başlığında 'merkezi modun ağ yükünü taklit eder, B12 değildir' yazıyor"; else log_fail "birim: yük aracı başlığı eksik"; fi
    out="$(grep -nE '10\.10\.0\.[0-9]+' "$YUK" || true)"
    if [[ -z "$out" ]]; then log_ok "birim: yük aracı adresleri koda gömmez (UAVn_ADDR/GCS_ADDR yapılandırmadan okunur)"; else log_fail "birim: yük aracında sabit adres: $out"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '^\s*(from|import) mavsdk' -- src araclar/sentetik_yuk.py araclar/tc_izle.py || true)"
    if [[ -n "$out" && "$(awk -F: '{print $1}' <<< "$out" | sort -u)" == "src/swarm_vehicle/swarm_vehicle/px4_adapter.py" ]]; then log_ok "birim: mavsdk'yı içe aktaran tek dosya px4_adapter.py"; else log_fail "birim: mavsdk içe aktarımı beklenenden farklı: $out"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE 'tc (qdisc|class|filter) (add|change|replace|del)|sudo_run|\["sudo"' -- araclar/sentetik_yuk.py araclar/tc_izle.py araclar/dds_doygunluk_analiz.py | grep -vE '^\S+:[0-9]+:\s*#' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: yeni araçlar tc'yi DEĞİŞTİRMEZ (yalnız okur) ve sudo çağırmaz"; else log_fail "birim: tc değiştiren ya da sudo çağıran satır: $out"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nIiE '[d]enetleyici|[c]laude|\b[k]art(ta|tır|lar|ın)?\b|\b[T]-0[0-9]{2}b?\b' -- src araclar setup config planlama | grep -viE 'ekran kartı' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: süreç izi taraması temiz"; else log_fail "birim: süreç izi: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
}

test_s0() { senaryo s0 yok; kalan_yok s0; }
test_s1() { senaryo s1 hazirlik; kalan_yok s1; }
test_s2() { senaryo s2 bas; kalan_yok s2; }

test_dryrun() {
    local ad=dryrun t rc id betik n=0 olu=0 once
    log_info "== dryrun: koşu yaşarken setup/*_testi.sh --dry-run ve --verify koşuyu ÖLDÜRMEZ =="
    rc=0
    "$KOSU" baslat --arac 1 > "$TMP_DIR/$ad.baslat.log" 2>&1 || rc=$?
    if [[ "$rc" -ne 0 ]]; then log_fail "$ad: baslat başarısız"; tail -n 8 "$TMP_DIR/$ad.baslat.log"; return 0; fi
    id="$(cat "$KOK/aktif")"
    KOSU_DIR="$KOK/$id"
    log_ok "$ad: koşu $id yaşıyor (yalnız Gazebo + PX4)"
    for betik in "$SETUP_DIR"/*_testi.sh; do
        [[ "$(basename "$betik")" != dds_doygunluk_testi.sh ]] || continue
        for t in --dry-run --verify; do
            rc=0
            timeout 300 "$betik" "$t" > "$TMP_DIR/$ad.$(basename "$betik").$t.log" 2>&1 < /dev/null || rc=$?
            n=$((n + 1))
            if "$KOSU" durum > "$TMP_DIR/$ad.durum.log" 2>&1 && [[ -f "$KOK/aktif" ]]; then
                log_ok "$ad: $(basename "$betik") $t (çıkış $rc) sonrası koşu yaşıyor (kosu.sh durum (+))"
            else
                olu=$((olu + 1)); log_fail "$ad: $(basename "$betik") $t (çıkış $rc) koşuyu ÖLDÜRDÜ ya da bozdu"; tail -n 6 "$TMP_DIR/$ad.durum.log"
                break 2
            fi
        done
    done
    once="$n"
    if [[ "$olu" -eq 0 ]]; then log_ok "$ad: $once çağrı (--dry-run ve --verify × $(find "$SETUP_DIR" -maxdepth 1 -name '*_testi.sh' | wc -l | tr -d ' ') betik − bu betik) boyunca koşu yaşamaya devam etti"; fi
    if "$KOSU" durdur > "$TMP_DIR/$ad.durdur.log" 2>&1; then log_ok "$ad: durdur tamam"; else log_fail "$ad: durdur başarısız"; tail -n 8 "$TMP_DIR/$ad.durdur.log"; fi
    kalan_yok "$ad"
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server; pgrep -af 'swarm_vehicle[.]arac|swarm_gcs[.]|koordinator_deneme[.]py|swarm_vehicle[.]cikarim_isci|python[^ ]* -I [^ ]*araclar/sentetik_yu[k][.]py|python[^ ]* -I [^ ]*araclar/tc_izl[e][.]py')" ]]; then
    fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server/araç süreci/yer istasyonu/yük üretici/tc örnekleyici yaşıyor; önce kapatın (görsel istemci 'gz sim -g' açıksa kapatın)"
fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), ROS $ROS_DISTRO, PX4 $PX4_TAG; testler: ${TESTS[*]}"
if want s0 || want s1 || want s2; then rm -f "$DURUM_DOSYASI"; fi

if want birim; then test_birim; fi
if want s0; then test_s0; fi
if want s1; then test_s1; fi
if want s2; then test_s2; fi
if want s0 && want s1 && want s2; then analiz_calistir; fi
if want dryrun; then test_dryrun; fi

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
