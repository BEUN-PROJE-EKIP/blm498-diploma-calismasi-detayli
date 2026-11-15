#!/usr/bin/env bash
# poz_tamponu_testi.sh — telemetri tamponu ve kare–poz enterpolasyonu kabul testleri (başsız Gazebo + PX4 SITL + araç süreci + yer istasyonu).
# Kullanım: ./poz_tamponu_testi.sh [--dry-run | --verify | -h] [birim] [tek] [hata]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz, hiçbir şey derlemez; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, kurulu paketler); süreç başlatmaz
# Testler:
#   birim   poz tamponu birim testleri (ROS'suz), colcon build, rclpy/mavsdk'sız içe aktarma, tek komut yolu taraması (PX4'e yazan çağrı yalnız `_yaz`, komut sayacı), süreç izi taraması,
#           yeni kayıt türlerinin örnekleri
#   tek     tek araç, tam koşu (kosu.sh baslat --arac 1 --yer-istasyonu var): telemetri hızı, her görev numarası için kare_poz, Gazebo gerçek poz karşılaştırması, PX4 − sim zaman farkı
#   hata    tek araç, tam koşu; POZ_TEST_DURDUR ile tarama başından 60 sn sonra 3 sn telemetri örneği tampona eklenmez: pencerede geçersiz poz, dışında geçerli; kare sonucu ve COMPLETE etkilenmez
# Araç süreci ve yer istasyonunu `kosu.sh` başlatır; gerçek poz kaydedicisi `setsid` ile ayrı süreç grubunda başlar ve her çıkışta (hata, Ctrl-C dahil) bu betik toplar.
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
        birim|tek|hata) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(birim tek hata)
COMPONENT_NAME="Poz tamponu ve kare–poz enterpolasyonu"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
ANALIZ="$ROOT_DIR/araclar/poz_analiz.py"
KAYIT="$ROOT_DIR/araclar/poz_gercek_kayit.py"
BIRIM_TEST="$ROOT_DIR/src/swarm_vehicle/test/test_poz_tamponu.py"
PKG_DIR="$ROOT_DIR/src/swarm_vehicle"
VENV_PY="$ROOT_DIR/.venv/bin/python"
ENV_SH="$SETUP_DIR/env.sh"
DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
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
for v in SIM_WORLD UAV_SYS_IDS POZ_ARALIK_SINIR_MS POZ_BEKLE_SN POZ_TAMPON_SN CAM_RATE_HZ KOSU_KAPANIS_SN; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
read -r -a SYS_IDS <<< "$UAV_SYS_IDS"
KIMLIK="${SYS_IDS[0]}"
BEKLE_SN_TAM=900      # tam koşu için kosu.sh bekle üst sınırı (gerçek sn)
ENJ_BASLANGIC=60      # hata: tarama başından sonra enjeksiyon başlangıcı (gerçek sn)
ENJ_SURE=3            # hata: enjeksiyon süresi (gerçek sn)

check_prereqs() {
    local c f
    for c in gz ss pgrep python3 awk colcon git tc; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "setup/env.sh" test -f "$ENV_SH"
    for f in "$KOSU" "$ANALIZ" "$KAYIT" "$BIRIM_TEST" "$PKG_DIR/swarm_vehicle/poz_tamponu.py" "$PKG_DIR/swarm_vehicle/px4_adapter.py"; do
        check "Dosya: ${f#"$ROOT_DIR"/}" test -f "$f"
    done
    check "Yapılandırılmış sürü ağı (lo üzerinde htb)" bash -c '[[ "$(tc qdisc show dev lo)" == *htb* ]]'
    check "kosu.sh --dry-run baslat çıkış 0" "$KOSU" --dry-run baslat
}

print_plan() {
    log_info "[dry-run] birim: poz tamponu birim testleri (ROS'suz); colcon build; rclpy/mavsdk'sız içe aktarma; tek komut yolu ve süreç izi taraması; yeni kayıt örnekleri"
    log_info "[dry-run] tek: kosu.sh baslat --arac 1 --yer-istasyonu var → gerçek poz kaydedicisi → kosu.sh bekle → analiz (telemetri hızı, kare_poz kümesi, gerçek poz, zaman farkı) → durdur"
    log_info "[dry-run] hata: aynı koşu, POZ_TEST_DURDUR=1:$ENJ_BASLANGIC:$ENJ_SURE (araç 1, tarama başından $ENJ_BASLANGIC sn sonra $ENJ_SURE sn) → analiz --enjeksiyon → durdur"
    log_info "[dry-run] Her testten sonra araç süreci/koordinatör/px4/gz/mavsdk_server artığı, yeni dinleyen port, /dev/shm; sonda ros2 daemon, tc/ip denetimi. Hiçbir süreç başlatılmadı"
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
shm_list() { find /dev/shm -maxdepth 1 -printf '%f\n' 2>/dev/null | grep -v "^lttng-ust" | LC_ALL=C sort || true; }
snapshot() { # snapshot <ad>
    local n="$1" c
    {
        for c in px4 gz mavsdk_server ruby; do echo "proc $c $(pgrep -x -c "$c" || true)"; done
        echo "proc arac $(pgrep -f -c 'swarm_vehicle[.]arac' || true)"
        echo "proc kayitci $(pgrep -f -c 'poz_gercek_kayit[.]py' || true)"
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
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0 (gz/ruby/px4/mavsdk_server/araç süreci/kaydedici), yeni dinleyen port 0, /dev/shm artığı 0"; fi
    return 0
}

KOSU_DIR=""
PART=""
kosu_baslat() { # kosu_baslat <ad> [kosu.sh argümanları...] (ek ortam: EK_ENV)
    local ad="$1" out id rc=0 l; shift
    out="$(env "${EK_ENV[@]+"${EK_ENV[@]}"}" "$KOSU" baslat "$@" 2>&1)" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: baslat başarısız (çıkış $rc)"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; return 1
    fi
    id="$(cat "$KOK/aktif")"
    KOSU_DIR="$KOK/$id"
    PART="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" gz_partition)"
    log_ok "$ad: baslat tamam, koşu $id"
    return 0
}
EK_ENV=()

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

LAST_PG=""
kayitci_baslat() { # gerçek poz kaydedicisi: ayrı süreç grubu, ROS/venv ortamında
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    setsid env GZ_PARTITION="$PART" GZ_IP=127.0.0.1 LC_NUMERIC=C bash -c 'source "$1" >/dev/null 2>&1; shift; exec "$@"' _ "$ENV_SH" python "$KAYIT" --arac 1 \
        > "$KOSU_DIR/poz_gercek_kayit.out" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
}

analiz() { # analiz <ad> <analiz argümanları...> : SONUC satırlarını (+)/(-) yapar, TABLO/BILGI satırlarını bilgi olarak yazar
    local ad="$1" line rc=0; shift
    python3 -I "$ANALIZ" "$KOSU_DIR" --arac 1 "$@" > "$TMP_DIR/$ad.analiz.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            TABLO*|BILGI*) log_info "$ad: $line" ;;
            Traceback*|*Error*) log_fail "$ad: analiz hatası: $line" ;;
        esac
    done < "$TMP_DIR/$ad.analiz.log"
    if [[ "$rc" -ne 0 ]]; then log_fail "$ad: analiz çıkış kodu $rc"; tail -n 12 "$TMP_DIR/$ad.analiz.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
    cp "$TMP_DIR/$ad.analiz.log" "$KOSU_DIR/poz_analiz_$ad.log" 2>/dev/null || true
}

kayit_gecerli() { # kayit_gecerli <ad> : telemetri ve kare_poz dosyaları doğrulayıcıdan geçmeli
    local ad="$1" f out
    for f in "telemetri_$KIMLIK" "kare_poz_$KIMLIK"; do
        if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kayit/$f.jsonl" 2>&1)"; then
            log_ok "$ad: gerçek kayıt doğrulayıcıdan geçti: $f.jsonl ($(tail -n 1 <<< "$out" | sed 's/, .*jsonl)/)/'))"
        else
            log_fail "$ad: kayıt GEÇERSİZ: $f.jsonl: $(head -n 3 <<< "$out" | tr '\n' ';')"
        fi
    done
}

tam_kosu() { # tam_kosu <ad> <kayitci:0|1> <analiz argümanları...>
    local ad="$1" kayitci="$2" rc=0; shift 2
    if kosu_baslat "$ad" --arac 1 --yer-istasyonu var; then
        [[ "$kayitci" -eq 0 ]] || kayitci_baslat
        "$KOSU" bekle --sure-sn "$BEKLE_SN_TAM" > "$TMP_DIR/$ad.bekle.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "$ad: kosu.sh bekle çıkış 0 (yer istasyonu tamamlandı)"; else log_fail "$ad: kosu.sh bekle çıkış kodu $rc"; tail -n 6 "$TMP_DIR/$ad.bekle.log"; fi
        if [[ "$kayitci" -ne 0 ]]; then grup_oldur "$LAST_PG"; PGIDS=(); fi
        local i
        for ((i = 0; i < 100; i++)); do pgrep -f 'swarm_vehicle[.]arac' >/dev/null || break; sleep 0.3; done   # araç süreci kendi kapanır (ARAC_KAPANIS_BEKLE_SN): kayıtlar tamamlansın
        kayit_gecerli "$ad"
        analiz "$ad" "$@"
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
        local arc
        arc="$(cat "$KOSU_DIR/arac_${KIMLIK}.cikis" 2>/dev/null || echo yok)"
        if [[ "$arc" == "0" ]]; then log_ok "$ad: araç süreci çıkış kodu 0"; else log_fail "$ad: araç süreci çıkış kodu '$arc'"; fi
        if grep -q "poz_ozeti" "$KOSU_DIR/arac_${KIMLIK}.log" 2>/dev/null; then log_info "$ad: $(grep -h 'poz_ozeti' "$KOSU_DIR/arac_${KIMLIK}.log" | sed 's/^[^ ]* [^ ]* //')"; fi
        if grep -q "kare_poz_hatasi" "$KOSU_DIR/arac_${KIMLIK}.log" 2>/dev/null; then log_fail "$ad: araç günlüğünde kare_poz_hatasi var"; else log_ok "$ad: araç günlüğünde kare_poz_hatasi yok"; fi
    fi
}

# iz_tara: depoya girecek içerikte süreç izi (rol adları, iş numaraları, iç belge yolları ve ilgili sözcükler) arar; bulunan satırları yazar (boş = temiz).
# Kapsam: çalışma ağacı farkında eklenen satırlar + izlenmeyen yeni dosyalar + son commit'te (git show HEAD) eklenen satırlar. Desen kendi metnini eşlemesin diye köşeli parantez kalıbı kullanır.
# IZ_HEAD_ATLA=1: son commit taranmaz (yalnız commit'i yeniden yazmadan önceki koşular için; commit sonrası koşu anahtarsız yapılır).
# Açık izin listesi (yanlış alarm): donanım adları (ekran/ses/grafik + ilgili sözcük).
IZ_DESEN='(^|[^A-Za-z0-9])[Tt]-0[0-9]{2}|[Uu]retic[i]|[Üü]retic[i]|[Dd]enetle[y]ici|[Cc]lau[d]e|review[s]/|task[s]/|\<[Kk]ar[t]'
iz_tara() {
    { git -C "$ROOT_DIR" diff -U0 HEAD -- . ':!setup/locks' | grep -E '^\+[^+]' || true
      git -C "$ROOT_DIR" ls-files --others --exclude-standard | (cd "$ROOT_DIR" && xargs -r cat)
      [[ "${IZ_HEAD_ATLA:-0}" == 1 ]] || git -C "$ROOT_DIR" show HEAD --format= -U0 -- . ':!setup/locks' | grep -E '^\+[^+]' || true
    } | grep -nE "$IZ_DESEN" | grep -vE '(ekran|ses|grafik) kar[t]' || true
}

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

# --- Testler ----------------------------------------------------------------------------
test_birim() {
    local out rc=0 l f
    log_info "== birim: poz tamponu birim testleri, derleme, içe aktarma, tek komut yolu, süreç izi =="
    if out="$("$VENV_PY" -I "$BIRIM_TEST" 2>&1)"; then log_ok "birim: poz tamponu birim testleri geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: poz tamponu birim testleri BAŞARISIZ"; tail -n 15 <<< "$out"; fi
    out="$GENERATED_DIR/poz_tamponu_derleme.txt"
    if proje_derle "$out"; then
        log_ok "birim: proje derlendi (swarm_msgs + swarm_vehicle + swarm_gcs; ortak yol: setup/lib/derleme.sh)"
    else
        log_fail "birim: proje derlemesi BAŞARISIZ; günlük: ${out#"$ROOT_DIR"/}"
        tail -n 12 "$out" | while IFS= read -r l; do log_info "  | $l"; done
    fi
    # shellcheck disable=SC2016  # tek tırnak bilerek: Python kodu
    "$VENV_PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import importlib; importlib.import_module("swarm_vehicle.poz_tamponu"); assert "rclpy" not in sys.modules and "mavsdk" not in sys.modules' "$PKG_DIR" > "$TMP_DIR/ice.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: swarm_vehicle.poz_tamponu rclpy ve mavsdk olmadan içe aktarıldı"; else log_fail "birim: poz_tamponu içe aktarma hatası"; tail -n 5 "$TMP_DIR/ice.log"; fi
    rc=0
    "$VENV_PY" -m py_compile "$PKG_DIR/swarm_vehicle/poz_tamponu.py" "$PKG_DIR/swarm_vehicle/px4_adapter.py" "$PKG_DIR/swarm_vehicle/arac.py" "$PKG_DIR/swarm_vehicle/kare_isleyici.py" "$ANALIZ" "$KAYIT" "$DOGRULA" > "$TMP_DIR/pyc.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: py_compile temiz"; else log_fail "birim: py_compile hata"; tail -n 5 "$TMP_DIR/pyc.log"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '^\s*(from|import) mavsdk' -- src || true)"
    if [[ -n "$out" && "$(awk -F: '{print $1}' <<< "$out" | sort -u)" == "src/swarm_vehicle/swarm_vehicle/px4_adapter.py" ]]; then log_ok "birim: src/ altında mavsdk'yı içe aktaran tek dosya px4_adapter.py"; else log_fail "birim: mavsdk içe aktarımı beklenenden farklı: $out"; fi
    out="$(cd "$ROOT_DIR" && git grep --untracked -nE '\.action\.|\.mission\b|\.mission_raw|\.param\.set|set_param|set_rate_|\.offboard\.|send_message' -- src ':!src/swarm_vehicle/swarm_vehicle/px4_adapter.py' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: src/ altında px4_adapter.py dışında PX4'e yazan çağrı yok"; else log_fail "birim: dış çağrı: $out"; fi
    out="$(git -C "$ROOT_DIR" grep --untracked -niE 'set_rate_|set_message_interval' -- src || true)"
    if [[ -z "$out" ]]; then log_ok "birim: src/ altında telemetri hızı artırma çağrısı yok (set_rate_*, SET_MESSAGE_INTERVAL)"; else log_fail "birim: hız komutu: $out"; fi
    out="$(grep -cE '^[[:space:]]*self\.komut_sayaci \+= 1' "$PKG_DIR/swarm_vehicle/px4_adapter.py" || true)"
    if [[ "$out" == "1" ]]; then log_ok "birim: komut sayacını artıran tek yer _yaz (px4_adapter.py)"; else log_fail "birim: komut_sayaci artışı $out yerde"; fi
    out="$(iz_tara)"
    if [[ -z "$out" ]]; then log_ok "birim: çalışma ağacı farkında, yeni dosyalarda ve son commit'te süreç izi yok"; else log_fail "birim: süreç izi: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
    for f in telemetri_ornek kare_poz_ornek; do
        if out="$(python3 -I "$DOGRULA" "$ROOT_DIR/config/ornek/$f.jsonl" 2>&1)"; then log_ok "birim: örnek doğrulayıcıdan geçti: $f.jsonl"; else log_fail "birim: örnek GEÇERSİZ: $f.jsonl: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
    done
}

test_tek() {
    log_info "== tek: tek araç tam koşu (gerçek poz kaydedicisiyle) =="
    EK_ENV=()
    tam_kosu tek 1
    kalan_yok tek
}

test_hata() {
    log_info "== hata: telemetri örneği enjeksiyonu (POZ_TEST_DURDUR=1:$ENJ_BASLANGIC:$ENJ_SURE) =="
    EK_ENV=("POZ_TEST_DURDUR=1:$ENJ_BASLANGIC:$ENJ_SURE")
    tam_kosu hata 0 --enjeksiyon
    EK_ENV=()
    kalan_yok hata
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server; pgrep -af 'swarm_vehicle[.]arac|poz_gercek_kayit[.]py')" ]]; then
    fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server/araç süreci/kaydedici yaşıyor; önce kapatın"
fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), ROS $ROS_DISTRO, PX4 $PX4_TAG; testler: ${TESTS[*]}"

if want birim; then test_birim; fi
if want tek; then test_tek; fi
if want hata; then test_hata; fi

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
