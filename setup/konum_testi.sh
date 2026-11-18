#!/usr/bin/env bash
# konum_testi.sh — konum hesaplayıcı (kutu merkezi → ışın → düz zemin → ENU) ve iki modda konumlu kare sonucu kabul testleri (başsız Gazebo + PX4 SITL + araç süreci + yer istasyonu).
# Kullanım: ./konum_testi.sh [--dry-run | --verify | -h] [birim] [isaret] [rota] [iki_mod] [kayma] [kayip]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz, hiçbir şey derlemez; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, kurulu paketler); süreç başlatmaz
# Testler:
#   birim     konum hesaplayıcı ve bağlama birim testleri (ROS'suz); colcon build; rclpy/mavsdk/gz'siz içe aktarma; tek komut yolu ve süreç izi taraması; sözleşme örnekleri
#   isaret    tek araç, uçta mod, tam koşu: Gazebo'ya bilinen ENU konumlarına test işaretleri eklenir (araclar/konum_isaret.py), kamera karelerinde renk eşiğiyle bulunur ve hesaplayıcıdan geçirilir:
#             her ölçüm < 5 m (PX4 pozu ve Gazebo gerçek pozu ile ayrı)
#   rota      aynı koşu: her görev karesinde görüntüde sabit piksellerin gerçek pozla izdüşümü ile PX4 pozuyla hesabı (evreye göre), zemin ölçümü
#   kayma     aynı koşu: odometri zaman kayması incelemesi (Gazebo poz kaynakları, PX4 kaynak kodu satırları, evre bazında çapraz ilişki, hız–kayma ilişkisi, konum hatasına etkisi). Düzeltme YOK.
#   iki_mod   KONUM_TEST_SAHTE ile sabit piksellerde sahte tespit: tek araç uçta, tek araç merkezi ve üç araç merkezi (doygun hat) koşuları; kayıttaki her konum çevrim dışı yeniden hesaplanır (birebir)
#   kayip     tek araç uçta, tam koşu; POZ_TEST_DURDUR (12 sn telemetri durması, tarama başından 58. sn) + KAMERA_ENJEKSIYON (sim kare +121…+130 düşürülür; durma penceresi bunları her iki yanda kapsar): kayıp karelerin poz beklemesi gz geri çağrısını bloke etmez
#             (`kayip()` çağrısı en çok süresi ≪ POZ_BEKLE_SN), kare_poz numara kümesi = kare_sonuc numara kümesi, kayıp karelerin kare_poz kaydında bekleme ölçülür
# isaret/rota/kayma TEK koşuyu paylaşır (kaydediciler `setsid` ile ayrı süreç gruplarında başlar ve her çıkışta bu betik toplar). Araç süreci ve yer istasyonunu `kosu.sh` başlatır.
# Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ. sudo gerekmez. Önizleme (gz sim -g) açıkken ölçüm yapılmaz.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/derleme.sh
source "$SETUP_DIR/lib/derleme.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        birim|isaret|rota|iki_mod|kayma|kayip) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(birim isaret rota iki_mod kayma kayip)
COMPONENT_NAME="Konum hesaplayıcı ve iki modda konumlu kare sonucu"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
ANALIZ="$ROOT_DIR/araclar/konum_analiz.py"
POZ_ANALIZ="$ROOT_DIR/araclar/poz_analiz.py"
KAYIT="$ROOT_DIR/araclar/poz_gercek_kayit.py"
KAYNAKLAR="$ROOT_DIR/araclar/gz_poz_kaynaklari.py"
ISARET="$ROOT_DIR/araclar/konum_isaret.py"
BIRIM_TEST="$ROOT_DIR/src/swarm_vehicle/test/test_konum_hesap.py"
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

# shellcheck disable=SC2317  # common.sh EXIT tuzağı dolaylı çağırır
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
for v in SIM_WORLD UAV_SYS_IDS UAV_START_POSES ZEMIN_Z_M POZ_BEKLE_SN CAM_RATE_HZ KOSU_KAPANIS_SN; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
read -r -a SYS_IDS <<< "$UAV_SYS_IDS"
KIMLIK="${SYS_IDS[0]}"
BEKLE_SN_TAM=900      # tam koşu için kosu.sh bekle üst sınırı (gerçek sn)
# sahte tespit kutuları (piksel): merkez ve dört köşeye yakın; kutu merkezleri (320,240), (60,60), (580,60), (60,420), (580,420)
SAHTE="300,220,340,260;40,40,80,80;560,40,600,80;40,400,80,440;560,400,600,440"

check_prereqs() {
    local c f
    for c in gz ss pgrep python3 awk colcon git tc; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    check "setup/env.sh" test -f "$ENV_SH"
    for f in "$KOSU" "$ANALIZ" "$POZ_ANALIZ" "$KAYIT" "$KAYNAKLAR" "$ISARET" "$BIRIM_TEST" "$PKG_DIR/swarm_vehicle/cikarim/konum_hesap.py" "$PKG_DIR/swarm_vehicle/cikarim/kare_isleyici.py"; do
        check "Dosya: ${f#"$ROOT_DIR"/}" test -f "$f"
    done
    check "Yapılandırılmış sürü ağı (lo üzerinde htb)" bash -c "[[ \"\$(tc qdisc show dev lo)\" == *htb* ]]"
    check "kosu.sh --dry-run baslat çıkış 0" "$KOSU" --dry-run baslat
}

print_plan() {
    log_info "[dry-run] birim: konum hesaplayıcı birim testleri (ROS'suz); colcon build; rclpy/mavsdk/gz'siz içe aktarma; tek komut yolu ve süreç izi taraması; sözleşme örnekleri"
    log_info "[dry-run] isaret/rota/kayma (tek koşu): KONUM_TEST_SAHTE ile kosu.sh baslat --arac 1 --yer-istasyonu var → kaydediciler (gerçek poz, poz kaynakları, test işaretleri) → kosu.sh bekle → konum_analiz.py isaret|rota|kayma → durdur"
    log_info "[dry-run] iki_mod: KONUM_TEST_SAHTE ile tek araç uçta (tek koşu varsa o), tek araç merkezi ve üç araç merkezi koşuları → konum_analiz.py iki_mod (çevrim dışı yeniden hesap, birebir) → durdur"
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
        echo "proc kayitci $(pgrep -f -c 'poz_gercek_kayit[.]py|gz_poz_kaynaklari[.]py|konum_isaret[.]py' || true)"
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
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0 (gz/ruby/px4/mavsdk_server/araç süreci/kaydediciler), yeni dinleyen port 0, /dev/shm artığı 0"; fi
    return 0
}

KOSU_DIR=""
PART=""
EK_ENV=()
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
arka_plan() { # arka_plan <günlük> <komut ve argümanlar...> : ROS/venv ortamında, ayrı süreç grubunda
    local gunluk="$1"; shift
    # shellcheck disable=SC2016  # tek tırnak bilerek: $1/$2 alt kabukta açılır
    setsid env GZ_PARTITION="$PART" GZ_IP=127.0.0.1 LC_NUMERIC=C bash -c 'source "$1" >/dev/null 2>&1; shift; exec "$@"' _ "$ENV_SH" python "$@" > "$gunluk" 2>&1 < /dev/null &
    LAST_PG=$!
    PGIDS+=("$LAST_PG")
}

analiz() { # analiz <ad> <mod> <analiz argümanları...> : SONUC satırlarını (+)/(-) yapar, TABLO/BILGI satırlarını bilgi olarak yazar
    local ad="$1" mod="$2" line rc=0; shift 2
    "$VENV_PY" -I "$ANALIZ" "$mod" "$@" > "$TMP_DIR/$ad.analiz.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            TABLO*|BILGI*) log_info "$ad: $line" ;;
            Traceback*|*Error*) log_fail "$ad: analiz hatası: $line" ;;
        esac
    done < "$TMP_DIR/$ad.analiz.log"
    if [[ "$rc" -ne 0 ]]; then log_fail "$ad: analiz çıkış kodu $rc"; tail -n 12 "$TMP_DIR/$ad.analiz.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
    cp "$TMP_DIR/$ad.analiz.log" "$KOSU_DIR/konum_analiz_$ad.log" 2>/dev/null || true
}

kayit_gecerli() { # kayit_gecerli <ad> <kimlik...> : kare sonucu ve kare_poz dosyaları doğrulayıcıdan geçmeli
    local ad="$1" f out k; shift
    for k in "$@"; do
        for f in "kare_sonuc_$k" "kare_poz_$k"; do
            if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kayit/$f.jsonl" 2>&1)"; then
                log_ok "$ad: gerçek kayıt doğrulayıcıdan geçti: $f.jsonl ($(tail -n 1 <<< "$out" | sed 's/, .*jsonl)/)/'))"
            else
                log_fail "$ad: kayıt GEÇERSİZ: $f.jsonl: $(head -n 3 <<< "$out" | tr '\n' ';')"
            fi
        done
    done
}

arac_bitti_bekle() { local i; for ((i = 0; i < 100; i++)); do pgrep -f 'swarm_vehicle[.]arac' >/dev/null || break; sleep 0.3; done; }   # araç süreci kendi kapanır: kayıtlar tamamlansın

arac_cikis_denetle() { # arac_cikis_denetle <ad> <araç sayısı>
    local ad="$1" n="$2" k arc
    for ((k = 1; k <= n; k++)); do
        arc="$(cat "$KOSU_DIR/arac_${k}.cikis" 2>/dev/null || echo yok)"
        if [[ "$arc" == "0" ]]; then log_ok "$ad: araç $k süreci çıkış kodu 0"; else log_fail "$ad: araç $k süreci çıkış kodu '$arc'"; fi
        if grep -q "kare_poz_hatasi" "$KOSU_DIR/arac_${k}.log" 2>/dev/null; then log_fail "$ad: araç $k günlüğünde kare_poz_hatasi var"; else log_ok "$ad: araç $k günlüğünde kare_poz_hatasi yok"; fi
        if grep -qh "konum_ozeti" "$KOSU_DIR/arac_${k}.log" 2>/dev/null; then log_info "$ad: araç $k: $(grep -h 'konum_ozeti' "$KOSU_DIR/arac_${k}.log" | sed 's/^[^ ]* [^ ]* [^ ]* //')"; fi
    done
    if grep -qh "konum_ozeti" "$KOSU_DIR/yer_istasyonu.log" 2>/dev/null; then log_info "$ad: yer istasyonu: $(grep -h 'konum_ozeti' "$KOSU_DIR/yer_istasyonu.log" | sed 's/^[^ ]* [^ ]* [^ ]* //' | tr '\n' ';')"; fi
}

sahte_iz_denetle() { # sahte_iz_denetle <ad> <ucta|merkezi> <1: anahtar açık beklenir | 0: kapalı beklenir>
    local ad="$1" mod="$2" acik="$3" ta uyari_arac uyari_gcs say_log
    ta="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" test_anahtarlari)"
    uyari_arac="$(cat "$KOSU_DIR"/arac_*.log 2>/dev/null | grep -c ' test_anahtari_acik ' || true)"
    uyari_gcs="$(grep -c ' test_anahtari_acik ' "$KOSU_DIR/yer_istasyonu.log" 2>/dev/null || true)"
    if [[ "$acik" == "1" ]]; then
        if [[ "$ta" == *KONUM_TEST_SAHTE* ]]; then log_ok "$ad: kosu.json test_anahtarlari KONUM_TEST_SAHTE içeriyor ($ta)"; else log_fail "$ad: kosu.json test_anahtarlari anahtarı göstermiyor: '$ta'"; fi
        if [[ "${uyari_gcs:-0}" -ge 1 ]]; then log_ok "$ad: yer istasyonu günlüğünde (!) test_anahtari_acik satırı var"; else log_fail "$ad: yer istasyonu günlüğünde test_anahtari_acik yok"; fi
        if [[ "$mod" == "ucta" ]]; then
            if [[ "${uyari_arac:-0}" -ge 1 ]]; then log_ok "$ad: araç günlüğünde (!) test_anahtari_acik satırı var"; else log_fail "$ad: araç günlüğünde test_anahtari_acik yok"; fi
            say_log="$(grep -h ' konum_ozeti ' "$KOSU_DIR"/arac_*.log 2>/dev/null | sed -n 's/.* sahte_tespit=\([0-9]*\).*/\1/p' | head -1)"
        else
            say_log="$(grep -h ' konum_ozeti ' "$KOSU_DIR/yer_istasyonu.log" 2>/dev/null | sed -n 's/.* sahte_tespit=\([0-9]*\).*/\1/p' | head -1)"
        fi
        if [[ "${say_log:-0}" -ge 1 ]]; then log_ok "$ad: konum_ozeti sahte_tespit=$say_log"; else log_fail "$ad: konum_ozeti sahte_tespit sayacı yok ya da 0"; fi
    else
        if [[ "$ta" != *KONUM_TEST_SAHTE* ]]; then log_ok "$ad: anahtar kapalı: kosu.json test_anahtarlari KONUM_TEST_SAHTE içermiyor ($ta)"; else log_fail "$ad: anahtar kapalıyken kosu.json KONUM_TEST_SAHTE gösteriyor"; fi
        if [[ "${uyari_arac:-0}" -eq 0 && "${uyari_gcs:-0}" -eq 0 ]]; then log_ok "$ad: anahtar kapalı: günlüklerde test_anahtari_acik yok"; else log_fail "$ad: anahtar kapalıyken test_anahtari_acik satırı var"; fi
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
    log_info "== birim: konum hesaplayıcı birim testleri, derleme, içe aktarma, tek komut yolu, süreç izi =="
    if out="$("$VENV_PY" -I "$BIRIM_TEST" 2>&1)"; then log_ok "birim: konum hesaplayıcı birim testleri geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: konum hesaplayıcı birim testleri BAŞARISIZ"; tail -n 15 <<< "$out"; fi
    out="$GENERATED_DIR/konum_derleme.txt"
    if proje_derle "$out"; then
        log_ok "birim: proje derlendi (swarm_msgs + swarm_vehicle + swarm_gcs; ortak yol: setup/lib/derleme.sh)"
    else
        log_fail "birim: proje derlemesi BAŞARISIZ; günlük: ${out#"$ROOT_DIR"/}"
        tail -n 12 "$out" | while IFS= read -r l; do log_info "  | $l"; done
    fi
    # shellcheck disable=SC2016  # tek tırnak bilerek: Python kodu
    "$VENV_PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import importlib; importlib.import_module("swarm_vehicle.cikarim.konum_hesap"); assert not {"rclpy", "mavsdk", "gz"} & set(sys.modules)' "$PKG_DIR" > "$TMP_DIR/ice.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: swarm_vehicle.cikarim.konum_hesap rclpy, mavsdk ve gz olmadan içe aktarıldı"; else log_fail "birim: konum_hesap içe aktarma hatası"; tail -n 5 "$TMP_DIR/ice.log"; fi
    rc=0
    "$VENV_PY" -m py_compile "$PKG_DIR/swarm_vehicle/cikarim/konum_hesap.py" "$PKG_DIR/swarm_vehicle/cikarim/kare_isleyici.py" "$PKG_DIR/swarm_vehicle/cikarim/kare_sonuc.py" "$PKG_DIR/swarm_vehicle/arac.py" \
        "$ROOT_DIR/src/swarm_gcs/swarm_gcs/merkezi_mod/merkezi_alici.py" "$ROOT_DIR/src/swarm_gcs/swarm_gcs/gorev_koordinatoru.py" "$ANALIZ" "$ISARET" "$KAYNAKLAR" "$DOGRULA" > "$TMP_DIR/pyc.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: py_compile temiz"; else log_fail "birim: py_compile hata"; tail -n 5 "$TMP_DIR/pyc.log"; fi
    out="$(git -C "$ROOT_DIR" grep --untracked -nE '^\s*(from|import) mavsdk' -- src || true)"
    if [[ -n "$out" && "$(awk -F: '{print $1}' <<< "$out" | sort -u)" == "src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py" ]]; then log_ok "birim: src/ altında mavsdk'yı içe aktaran tek dosya px4_adapter.py"; else log_fail "birim: mavsdk içe aktarımı beklenenden farklı: $out"; fi
    out="$(git -C "$ROOT_DIR" grep --untracked -nE '\.action\.|\.mission\b|\.mission_raw|\.param\.set|set_param|set_rate_|\.offboard\.|send_message' -- src ':!src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: src/ altında px4_adapter.py dışında PX4'e yazan çağrı yok"; else log_fail "birim: dış çağrı: $out"; fi
    out="$(grep -cE '^[[:space:]]*self\.komut_sayaci \+= 1' "$PKG_DIR/swarm_vehicle/ucus/px4_adapter.py" || true)"
    if [[ "$out" == "1" ]]; then log_ok "birim: komut sayacını artıran tek yer _yaz (px4_adapter.py)"; else log_fail "birim: komut_sayaci artışı $out yerde"; fi
    out="$(git -C "$ROOT_DIR" grep --untracked -niE 'param\.set|set_param|set_rate_|set_message_interval|EKF2_GPS_DELAY' -- src araclar/konum_isaret.py araclar/gz_poz_kaynaklari.py || true)"
    if [[ -z "$out" ]]; then log_ok "birim: src/ ve yeni test araçlarında PX4 parametre/hız yazımı ya da EKF2_GPS_DELAY kullanımı yok (kayma incelemesi salt okunur)"; else log_fail "birim: parametre/hız: $out"; fi
    out="$(iz_tara)"
    if [[ -z "$out" ]]; then log_ok "birim: çalışma ağacı farkında, yeni dosyalarda ve son commit'te süreç izi yok"; else log_fail "birim: süreç izi: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
    for f in kare_sonuc_ornek kare_poz_ornek; do
        if out="$(python3 -I "$DOGRULA" "$ROOT_DIR/config/ornek/$f.jsonl" 2>&1)"; then log_ok "birim: örnek doğrulayıcıdan geçti: $f.jsonl"; else log_fail "birim: örnek GEÇERSİZ: $f.jsonl: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
    done
}

TEK_KLASOR=""
test_tek_kosu() { # isaret/rota/kayma: tek koşu (uçta, tek araç), kaydediciler ve analizler
    log_info "== tek koşu (${TESTS[*]}): uçta mod, tek araç, KONUM_TEST_SAHTE, kaydediciler =="
    local rc=0 pg_kayit="" pg_kaynak="" pg_isaret=""
    EK_ENV=("KONUM_TEST_SAHTE=$SAHTE")
    if kosu_baslat tek --arac 1 --yer-istasyonu var; then
        TEK_KLASOR="$KOSU_DIR"
        arka_plan "$KOSU_DIR/poz_gercek_kayit.out" "$KAYIT" --arac 1; pg_kayit="$LAST_PG"
        if want kayma; then arka_plan "$KOSU_DIR/gz_poz_kaynaklari.out" "$KAYNAKLAR" --arac 1; pg_kaynak="$LAST_PG"; fi
        if want isaret; then arka_plan "$KOSU_DIR/konum_isaret.out" "$ISARET" --arac 1; pg_isaret="$LAST_PG"; fi
        "$KOSU" bekle --sure-sn "$BEKLE_SN_TAM" > "$TMP_DIR/tek.bekle.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "tek: kosu.sh bekle çıkış 0 (yer istasyonu tamamlandı)"; else log_fail "tek: kosu.sh bekle çıkış kodu $rc"; tail -n 6 "$TMP_DIR/tek.bekle.log"; fi
        local pg
        for pg in "$pg_isaret" "$pg_kaynak" "$pg_kayit"; do [[ -z "$pg" ]] || grup_oldur "$pg"; done
        PGIDS=()
        arac_bitti_bekle
        kayit_gecerli tek "$KIMLIK"
        arac_cikis_denetle tek 1
        sahte_iz_denetle tek ucta 1
        if want isaret; then analiz tek_isaret isaret "$KOSU_DIR" --arac 1; fi
        if want kayma; then
            analiz tek_kayma kayma "$KOSU_DIR" --arac 1
            python3 -I "$POZ_ANALIZ" "$KOSU_DIR" --arac 1 2>&1 | grep -E '^(TABLO|BILGI)' | grep -E 'zaman_farki|gerçek poz|yatay_hata|yaw_hata|irtifa_hata' | while IFS= read -r l; do log_info "tek_poz_analiz: $l"; done || true
        fi
        if want rota; then analiz tek_rota rota "$KOSU_DIR" --arac 1; fi
        komut_dene "$TMP_DIR/tek.durdur.log" "tek: durdur tamam" "tek: durdur başarısız" "$KOSU" durdur
        json_gecerli tek tamamlandi
    fi
    EK_ENV=()
    kalan_yok tek
}

iki_mod_kosu() { # iki_mod_kosu <ad> <ucta|merkezi> <araç sayısı>
    local ad="$1" mod="$2" n="$3" rc=0 k
    local ids=()
    for ((k = 1; k <= n; k++)); do ids+=("${SYS_IDS[$((k - 1))]}"); done
    EK_ENV=("KONUM_TEST_SAHTE=$SAHTE")
    if kosu_baslat "$ad" --arac "$n" --yer-istasyonu var --mimari "$mod"; then
        "$KOSU" bekle --sure-sn "$BEKLE_SN_TAM" > "$TMP_DIR/$ad.bekle.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "$ad: kosu.sh bekle çıkış 0 (yer istasyonu tamamlandı)"; else log_fail "$ad: kosu.sh bekle çıkış kodu $rc"; tail -n 6 "$TMP_DIR/$ad.bekle.log"; fi
        arac_bitti_bekle
        kayit_gecerli "$ad" "${ids[@]}"
        arac_cikis_denetle "$ad" "$n"
        sahte_iz_denetle "$ad" "$mod" 1
        for ((k = 1; k <= n; k++)); do analiz "${ad}_arac$k" iki_mod "$KOSU_DIR" --arac "$k" --mod "$mod"; done
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi
    fi
    EK_ENV=()
    kalan_yok "$ad"
}

test_iki_mod() {
    log_info "== iki_mod: sahte tespit (KONUM_TEST_SAHTE), çevrim dışı yeniden hesap =="
    if [[ -n "$TEK_KLASOR" ]]; then
        KOSU_DIR="$TEK_KLASOR"
        analiz iki_mod_ucta iki_mod "$KOSU_DIR" --arac 1 --mod ucta
        log_info "iki_mod: uçta koşusu olarak tek koşu kullanıldı (${TEK_KLASOR##*/})"
    else
        iki_mod_kosu iki_ucta ucta 1
    fi
    iki_mod_kosu iki_merkezi merkezi 1
    iki_mod_kosu iki_uc_merkezi merkezi 3
}

test_kayip() {
    log_info "== kayip: telemetri durması + kare kaybı: gz geri çağrısı poz beklemesiyle bloke olmamalı =="
    local rc=0 out
    # Zaman ekseni: telemetri durması gerçek sn ile (tarama başından 58–70. sn), düşürülen kareler sim kare numarasıyla (+121…+130 = tarama başından 60,5–65 sn sim). Sim gerçek zamanda koştuğundan ikisi aynı eksendedir;
    # durma penceresi düşürülen aralıktan her iki yanda ≈ 2,5 sn geniş seçilir (tarama başlangıcı ile ilk kare arasındaki fark ve saat sapması için pay). Hizanın gerçekten tuttuğu aşağıda ölçülür: en az bir kayıp karede bekleme_ms > 0.
    EK_ENV=("POZ_TEST_DURDUR=1:58:12" "KAMERA_ENJEKSIYON=dusur=+121,+122,+123,+124,+125,+126,+127,+128,+129,+130")
    if kosu_baslat kayip --arac 1 --yer-istasyonu var; then
        "$KOSU" bekle --sure-sn "$BEKLE_SN_TAM" > "$TMP_DIR/kayip.bekle.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "kayip: kosu.sh bekle çıkış 0 (yer istasyonu tamamlandı)"; else log_fail "kayip: kosu.sh bekle çıkış kodu $rc"; tail -n 6 "$TMP_DIR/kayip.bekle.log"; fi
        arac_bitti_bekle
        kayit_gecerli kayip "$KIMLIK"
        arac_cikis_denetle kayip 1
        sahte_iz_denetle kayip ucta 0
        out="$(python3 -I - "$KOSU_DIR" "$KIMLIK" "$POZ_BEKLE_SN" <<'PY'
import json, sys
k, kim, bekle = sys.argv[1], sys.argv[2], float(sys.argv[3])
oku = lambda y: [json.loads(x) for x in open(y, encoding="utf-8") if x.strip()]
ks, kp = oku(f"{k}/kayit/kare_sonuc_{kim}.jsonl"), oku(f"{k}/kayit/kare_poz_{kim}.jsonl")
kayip = sorted(r["n"] for r in ks if r["durum"] == "kare_alinamadi")
bek = {r["n"]: r for r in kp}
ozet = [l for l in open(f"{k}/arac_{kim}.log", encoding="utf-8") if " konum_ozeti " in l]
maks = float(ozet[-1].split("kayip_cagri_maks_ms=")[1].split()[0]) if ozet else -1.0
print(f"KUME {int(sorted(r['n'] for r in ks) == sorted(bek))} {len(ks)} {len(kp)}")
print(f"KAYIP {len(kayip)} {' '.join(str(n) for n in kayip)}")
print(f"BEKLEME {' '.join('%d:%s:%.1f' % (n, bek[n]['neden'], bek[n]['bekleme_ms']) for n in kayip if n in bek)}")
kb = [bek[n] for n in kayip if n in bek]
print(f"BEKOZET {sum(1 for r in kb if r['bekleme_ms'] > 0)} {sum(1 for r in kb if r['neden'] == 'bekleme_asildi')} {sum(1 for r in kb if r['gecerli'] and r['bekleme_ms'] > 0)} {len(kb)}")
print(f"MAKS {maks} {bekle * 1000}")
PY
)"
        log_info "kayip: $(tr '\n' ';' <<< "$out")"
        if grep -q '^KUME 1 ' <<< "$out"; then log_ok "kayip: kare_poz numara kümesi = kare_sonuc numara kümesi"; else log_fail "kayip: kare_poz ve kare_sonuc numara kümeleri farklı"; fi
        if [[ "$(sed -n 's/^KAYIP \([0-9]*\) .*/\1/p' <<< "$out")" -ge 10 ]]; then log_ok "kayip: kare alınamadı sonucu en az 10 numara için üretildi"; else log_fail "kayip: beklenen kayıp kare sonuçları yok"; fi
        # asıl senaryo: telemetri durmuşken düşen karede poz beklenir. Beklenen: en az bir kayıp karede bekleme_ms > 0 VE en az birinde bekleme_asildi (pencerenin içinde kalan kare); gecikmiş geçerli poz (pencere sonu) ayrıca sayılır
        read -r _ bpoz basildi bgecik bkayip <<< "$(grep '^BEKOZET' <<< "$out")"
        if [[ "${bpoz:-0}" -ge 1 && "${basildi:-0}" -ge 1 ]]; then
            log_ok "kayip: kayıp karelerde poz beklendi: bekleme_ms > 0 olan $bpoz/$bkayip, bekleme_asildi $basildi, gecikmiş geçerli poz $bgecik"
        else
            log_fail "kayip: telemetri durması ile düşürülen kareler hizalanmadı ya da beklenen poz beklemesi görülmedi (bekleme_ms > 0: ${bpoz:-?}, bekleme_asildi: ${basildi:-?}, kayıp kare: ${bkayip:-?})"
        fi
        if awk -v m="$(sed -n 's/^MAKS \([-0-9.]*\) .*/\1/p' <<< "$out")" -v b="$(sed -n 's/^MAKS [-0-9.]* \(.*\)/\1/p' <<< "$out")" 'BEGIN {exit !(m >= 0 && m < b / 5)}'; then
            log_ok "kayip: kayip() çağrısının kendisi (gz geri çağrısının bloke olabileceği süre; poz beklemesi hariç) POZ_BEKLE_SN'den belirgin küçük (konum_ozeti kayip_cagri_maks_ms)"
        else
            log_fail "kayip: kayip() çağrı süresi sınırı aşıyor ya da ölçülemedi: $(grep '^MAKS' <<< "$out")"
        fi
        komut_dene "$TMP_DIR/kayip.durdur.log" "kayip: durdur tamam" "kayip: durdur başarısız" "$KOSU" durdur
        json_gecerli kayip tamamlandi
    fi
    EK_ENV=()
    kalan_yok kayip
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server; pgrep -af 'swarm_vehicle[.]arac|poz_gercek_kayit[.]py|gz_poz_kaynaklari[.]py|konum_isaret[.]py')" ]]; then
    fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server/araç süreci/kaydedici yaşıyor; önce kapatın"
fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), ROS $ROS_DISTRO, PX4 $PX4_TAG; testler: ${TESTS[*]}"

if want birim; then test_birim; fi
if want isaret || want rota || want kayma; then test_tek_kosu; fi
if want iki_mod; then test_iki_mod; fi
if want kayip; then test_kayip; fi

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
