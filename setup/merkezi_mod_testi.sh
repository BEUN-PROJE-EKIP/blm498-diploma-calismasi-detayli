#!/usr/bin/env bash
# merkezi_mod_testi.sh — merkezi mod (araç başına TCP görüntü kanalı + yer istasyonunda çıkarım, B12 1/2) kabul testleri (başsız Gazebo + PX4 SITL + araç süreci + yer istasyonu).
# Kullanım: ./merkezi_mod_testi.sh [--dry-run | --verify | -h] [birim] [tek] [hata] [basinc] [kapat] [sigterm] [uc] [erken] [tasma]
#   (argümansız)  hepsini çalıştırır; adlar verilirse yalnız onlar.
#   --dry-run     hiçbir süreç başlatmaz, hiçbir şey derlemez; ne çalıştıracağını yazar
#   --verify      hafif önkoşul denetimi (araçlar, betikler, kurulu paketler); süreç başlatmaz
# Testler:
#   birim    ileti kodlama/çözme, gönderim kuyruğu, alıcı birim testleri (ROS'suz), colcon build, rclpy/mavsdk'sız içe aktarma, tek komut yolu ve süreç izi taraması, yeni kayıt örnekleri
#   tek      önce uçta mod başvuru koşusu (tek araç; L ve CPU eşlemesi karşılaştırması için), sonra `kosu.sh baslat --arac 1 --yer-istasyonu var --mimari merkezi`: her numara için tam bir sonuç, gönderilen =
#            alınan = işlenen, tekrar/aralık dışı/atılan 0, başlıktaki poz = araçtaki kare_poz, görüntü SHA-256 (MERKEZI_SHA=1), CPU kümesi, L (uçta mod yan yana), tc sayacı, kuyruk durumu
#   hata     merkezi mod, enjeksiyon açık (KAMERA_ENJEKSIYON=dusur=+20, ISCI_ENJEKSIYON=hata=+40): kare alınamadı iletisi TCP'den geçer, işçi hatası islem_hatasi olur
#   basinc   merkezi mod, yer istasyonu alıcısı okumayı durdurur (MERKEZI_ENJEKSIYON=okuma_dur=60:20): araç kuyruğu büyür, hiçbir kare atılmaz, hepsi gelir, COMPLETE beklenen sırada
#   kapat    merkezi mod, araç süreci tarama ortasında kanalı bilerek TEMİZ kapatır (MERKEZI_ARAC_ENJEKSIYON=kanal_kapat=<n>): yer istasyonu `merkezi_kanal_hatasi` ile zaman aşımından ÖNCE açık hatayla biter, COMPLETE yayımlanmaz
#   sigterm  merkezi mod, araç süreci tarama ortasında SIGTERM alır: kayıt yazıcıları boşalır, çıkış kodu 143
#   uc       üç araç, doygun hat (25 Mbit/s): önce aynı makinede tek araç merkezi başvuru koşusu (L farkı için), sonra üç araçlı koşu UC_TEKRAR kez; ölçütler HER ARAÇ İÇİN ayrı (sayılar, SHA-256, poz, kalibrasyon,
#            üç işçi sonucu, COMPLETE, tc sayacı); L, kuyruk derinlikleri, kontrol iletisi gecikmesi ve koşular arası değişkenlik ham sayılarla raporlanır (yorumsuz)
#   tasma    merkezi mod, araç gönderim kuyruğunun TASMA_N'inci yazması yapay ENOSPC alır (KUYRUK_TEST_TASMA=gonderim_<araç>:<n>): hiçbir kare sessiz atılmaz; `kuyruk_tasmasi` kaydı + `(-)` günlük, koşu `yarida_kaldi`,
#            COMPLETE yok, sayaç denkliği (üretilen = kuyruğa giren + taşan + düşen; kuyruğa giren = gönderilen + kuyrukta kalan; alınan = gönderilen, her alınan kare için sonuç) [bitti ölçütü: kapasite taşması sessiz kare atlamaz]
#   erken    gerçek `kosu.sh` yönetimli üç araçlı koşu, `GCS_UST_SN` geçersiz kılınmadan (1800 sn): (a) bir araç t0'dan önce çıkar (ARAC_TEST_CIKIS=<araç>:bariyer), (b) bir araç t0'dan sonra tarama ortasında
#            çıkar (ARAC_TEST_CIKIS=<araç>:tarama:<sn>); yer istasyonu ilk araç çıkışından sonra ERKEN_SINIR_SN içinde açık hatayla biter (gerçek süre ölçülür), COMPLETE yok, `yarida_kaldi`, artık süreç/port yok
# Araç süreci ve yer istasyonunu `kosu.sh` başlatır. Bu betik install_all.sh/verify_all.sh sırasına GİRMEZ. sudo gerekmez.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
# shellcheck source=lib/derleme.sh
source "$SETUP_DIR/lib/derleme.sh"

TESTS=()
ARGS=()
for a in "$@"; do
    case "$a" in
        birim|tek|hata|basinc|kapat|sigterm|uc|erken|tasma) TESTS+=("$a") ;;
        *) ARGS+=("$a") ;;
    esac
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
[[ "${#TESTS[@]}" -gt 0 ]] || TESTS=(birim tek hata basinc kapat sigterm uc erken tasma)
COMPONENT_NAME="Merkezi mod (TCP görüntü kanalı)"
require_not_root
load_versions
export LC_NUMERIC=C   # tr_TR ondalık virgülü tuzağı

trap 'exit 130' INT
trap 'exit 143' TERM

KOSU="$ROOT_DIR/araclar/kosu.sh"
HELPER="$ROOT_DIR/araclar/kosu_ustveri.py"
DOGRULA="$ROOT_DIR/araclar/sozlesme_dogrula.py"
ANALIZ="$ROOT_DIR/araclar/merkezi_analiz.py"
UC_ANALIZ="$ROOT_DIR/araclar/uc_mod_analiz.py"
BIRIM_TESTLER=("$ROOT_DIR/src/swarm_vehicle/test/test_goruntu_ileti.py" "$ROOT_DIR/src/swarm_gcs/test/test_merkezi_alici.py" "$ROOT_DIR/src/swarm_gcs/test/test_gorev_mantik.py" "$ROOT_DIR/src/swarm_vehicle/test/test_port_denetimi.py" "$ROOT_DIR/src/swarm_vehicle/test/test_arac_kapanis.py" "$ROOT_DIR/src/swarm_gcs/test/test_sonuc_defteri.py" "$ROOT_DIR/src/swarm_vehicle/test/test_poz_tamponu.py" "$ROOT_DIR/src/swarm_vehicle/test/test_disk_kuyrugu.py" "$ROOT_DIR/src/swarm_vehicle/test/test_kamera_alici.py" "$ROOT_DIR/src/swarm_vehicle/test/test_kare_asamalari.py")
PKG_DIR="$ROOT_DIR/src/swarm_vehicle"
GCS_DIR="$ROOT_DIR/src/swarm_gcs"
VENV_PY="$ROOT_DIR/.venv/bin/python"
DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
KOK="$GENERATED_DIR/kosular"
TMP_DIR=""

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

exit_hook() {
    [[ "${DRY_RUN:-0}" -eq 0 && "${MODE:-install}" != verify ]] || return 0   # --dry-run/--verify hiçbir süreç başlatmaz; yaşayan (başkasına ait) koşuya DOKUNMAZ
    if [[ -f "$KOK/aktif" ]]; then "$KOSU" temizle >/dev/null 2>&1 || true; fi
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
    TMP_DIR=""
}

[[ -f "$DENEY_ENV" ]] || fail_stop "Yapılandırma yok: $DENEY_ENV"
# shellcheck source=/dev/null
source "$DENEY_ENV"
for v in SIM_WORLD UAV_SYS_IDS GCS_ADDR UAV1_ADDR MERKEZI_TCP_PORT_TABAN MERKEZI_BAGLAN_SN MERKEZI_BOSALT_SN MERKEZI_KUYRUK_KAYIT_SN MERKEZI_YUK_MAKS_BAYT KOSU_MIMARILER CAM_RATE_HZ; do
    [[ -n "${!v:-}" ]] || fail_stop "$DENEY_ENV içinde $v tanımsız"
done
read -r -a SYS_IDS <<< "$UAV_SYS_IDS"
KIMLIK="${SYS_IDS[0]}"
BEKLE_SN_TAM=900      # tam koşu için kosu.sh bekle üst sınırı (gerçek sn)
BASINC_BASLANGIC=60   # basinc: ilk iletiden sonra okumanın durması (gerçek sn)
BASINC_SURE=20        # basinc: okuma durma süresi (gerçek sn)
KAPAT_N=350           # kapat: bu numaradan sonra araç kanalı temiz kapatır (tarama ortası; tek araç aralığı yaklaşık [161, 543])
SIGTERM_KARE=60       # sigterm: kare_poz kaydı bu kadar satıra ulaşınca (tarama ortası) araç sürecine SIGTERM gönderilir
SIGTERM_BEKLE_SN=600  # sigterm: tarama ortasına ulaşmak için en çok bu kadar gerçek sn
KAPAT_BEKLE_SN=3      # kapat: kanal kapandıktan sonra araç süreci bu kadar sn daha yaşar (yer istasyonunun süreç çıkışı payı 1 sn; neden YALNIZ kanal_hatasi olmalı)
KAPAT_SINIR_SN=60     # kapat: kanal kapanışından yer istasyonunun hatayla bitişine en çok bu kadar gerçek sn
UC_TEKRAR=3           # uc: üç araçlı koşunun tekrar sayısı (güvenli ama yavaş: her koşu ayrı satır)
ERKEN_SINIR_SN=10     # erken: ilk araç çıkışından yer istasyonunun açık hatayla bitişine en çok bu kadar gerçek sn
ERKEN_TARAMA_SN=60    # erken (b): araç, tarama başladıktan bu kadar gerçek sn sonra çıkar (tarama ortasında; tek araç taraması ≈190 sn)
TASMA_N=100           # tasma: gönderim kuyruğunun bu numaralı yazması yapay ENOSPC alır (tarama başından ≈50 sn sonra; öncesinde kuyruğa giren kareler olur)
ERKEN_BEKLE_SN=900    # erken: kosu.sh bekle üst sınırı; kural işlemezse test 1800 sn'yi beklemez, başarısız olur
N_ARAC=1              # merkezi_kosu: araç sayısı (uc testinde 3)

check_prereqs() {
    local c f
    for c in gz ss pgrep python3 awk colcon git tc; do check "Araç mevcut: $c" command -v "$c"; done
    check "venv Python (.venv)" test -x "$VENV_PY"
    for f in "$KOSU" "$ANALIZ" "$UC_ANALIZ" "${BIRIM_TESTLER[@]}" "$PKG_DIR/swarm_vehicle/merkezi_mod/goruntu_ileti.py" "$PKG_DIR/swarm_vehicle/merkezi_mod/goruntu_kanali.py" "$GCS_DIR/swarm_gcs/merkezi_mod/merkezi_alici.py"; do
        check "Dosya: ${f#"$ROOT_DIR"/}" test -f "$f"
    done
    check "Yapılandırılmış sürü ağı (lo üzerinde htb)" bash -c '[[ "$(tc qdisc show dev lo)" == *htb* ]]'
    check "kosu.sh --dry-run baslat --mimari merkezi çıkış 0" "$KOSU" --dry-run baslat --arac 1 --yer-istasyonu var --mimari merkezi
}

print_plan() {
    log_info "[dry-run] birim: ileti/kuyruk/alıcı birim testleri (ROS'suz); colcon build; rclpy/mavsdk'sız içe aktarma; tek komut yolu ve süreç izi taraması; yeni kayıt örnekleri"
    log_info "[dry-run] tek: uçta mod başvuru koşusu (kosu.sh baslat --arac 1 --yer-istasyonu var) → merkezi koşu (… --mimari merkezi, MERKEZI_SHA=1) → analiz (sayılar, poz, SHA-256, CPU, L, tc, kuyruk) → durdur"
    log_info "[dry-run] hata: merkezi koşu + KAMERA_ENJEKSIYON=dusur=+20, ISCI_ENJEKSIYON=hata=+40 → analiz --hata"
    log_info "[dry-run] basinc: merkezi koşu + MERKEZI_ENJEKSIYON=okuma_dur=$BASINC_BASLANGIC:$BASINC_SURE → analiz --basinc"
    log_info "[dry-run] kapat: merkezi koşu + MERKEZI_ARAC_ENJEKSIYON=kanal_kapat=$KAPAT_N:$KAPAT_BEKLE_SN → yer istasyonu en çok $KAPAT_SINIR_SN sn içinde açık hatayla biter (zaman aşımından önce), COMPLETE yok"
    log_info "[dry-run] sigterm: merkezi koşu, tarama ortasında (kare_poz >= $SIGTERM_KARE satır) araç süreci PID ile SIGTERM alır → kare_poz ve gonderim_kuyrugu son satırları yazılmış, satir_yazici_ozet var (yazilan = dosya satırı, dusen 0), çıkış kodu 143 (134 değil)"
    log_info "[dry-run] uc: tek araç merkezi başvuru koşusu (L farkı için) → $UC_TEKRAR kez kosu.sh baslat --arac 3 --yer-istasyonu var --mimari merkezi (MERKEZI_SHA=1, tc sürü ağı açık): her araç için sayılar/SHA-256/poz/kalibrasyon/işçi sonucu/COMPLETE/tc → analiz --arac 3 --sha --tek-klasoru → durdur; her koşu ayrı satır"
    log_info "[dry-run] erken: (a) ARAC_TEST_CIKIS=<araç 2>:bariyer, (b) ARAC_TEST_CIKIS=<araç 3>:tarama:$ERKEN_TARAMA_SN (GCS_UST_SN geçersiz kılınmaz) → yer istasyonu ilk araç çıkışından sonra en çok $ERKEN_SINIR_SN sn içinde açık hatayla biter (gerçek süre ölçülür), COMPLETE yok, kosu.json yarida_kaldi, artık süreç/port yok"
    log_info "[dry-run] tasma: merkezi koşu + KUYRUK_TEST_TASMA=gonderim_<araç>:$TASMA_N → araç kuyruk_tasmasi kaydı + (-) günlük + hata çıkışı, yer istasyonu en çok $KAPAT_SINIR_SN sn içinde açık hatayla biter, COMPLETE yok, koşu yarida_kaldi, sayaç denkliği (analiz --tasma): kare sessiz atılmaz"
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
[[ "$COUNT_FAIL" -eq 0 ]] || { component_failed "$COMPONENT_NAME"; exit 1; }
TMP_DIR="$(mktemp -d)"

# --- Ölçüm anlık görüntüleri -------------------------------------------------------
shm_list() { find /dev/shm -maxdepth 1 -printf '%f\n' 2>/dev/null | grep -v "^lttng-ust" | LC_ALL=C sort || true; }
snapshot() { # snapshot <ad>
    local n="$1" c
    {
        for c in px4 gz mavsdk_server ruby; do echo "proc $c $(pgrep -x -c "$c" || true)"; done
        echo "proc arac $(pgrep -f -c 'swarm_vehicle[.]arac' || true)"
        echo "proc yer_istasyonu $(pgrep -f -c 'swarm_gcs[.]gorev_koordinatoru' || true)"
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
    if [[ "$ok" -eq 1 ]]; then log_ok "$et: artık süreç 0 (gz/ruby/px4/mavsdk_server/araç süreci/yer istasyonu/işçi), yeni dinleyen port 0, /dev/shm artığı 0"; fi
    return 0
}

KOSU_DIR=""
EK_ENV=()
kosu_baslat() { # kosu_baslat <ad> [kosu.sh argümanları...] (ek ortam: EK_ENV)
    local ad="$1" out id rc=0 l; shift
    out="$(env "${EK_ENV[@]+"${EK_ENV[@]}"}" "$KOSU" baslat "$@" 2>&1)" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        log_fail "$ad: baslat başarısız (çıkış $rc)"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; return 1
    fi
    id="$(cat "$KOK/aktif")"
    KOSU_DIR="$KOK/$id"
    log_ok "$ad: baslat tamam, koşu $id"
    return 0
}

komut_dene() {
    local log="$1" ok="$2" hata="$3"; shift 3
    if "$@" > "$log" 2>&1; then log_ok "$ok"; else log_fail "$hata"; tail -n 8 "$log"; fi
}

json_gecerli() { # json_gecerli <ad> <beklenen_bitis_durumu> <beklenen_mimari>
    local ad="$1" bekl="$2" mim="$3" out bd md l
    if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kosu.json" 2>&1)"; then log_ok "$ad: kosu.json doğrulayıcıdan geçti"; else log_fail "$ad: kosu.json GEÇERSİZ"; while IFS= read -r l; do log_info "  | $l"; done <<< "$out"; fi
    bd="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" bitis_durumu)"
    md="$(python3 -I "$HELPER" durum-alani "$KOSU_DIR/kosu.json" mimari_modu)"
    if [[ "$bd" == "$bekl" ]]; then log_ok "$ad: bitiş durumu '$bd'"; else log_fail "$ad: bitiş durumu '$bd' (beklenen '$bekl')"; fi
    if [[ "$md" == "$mim" ]]; then log_ok "$ad: kosu.json mimari_modu '$md'"; else log_fail "$ad: mimari_modu '$md' (beklenen '$mim')"; fi
}

tc_bayt() { # sürü sınıfı (1:10) için gönderilen bayt sayısı
    tc -s class show dev lo 2>/dev/null | awk '/^class htb 1:10 / {f=1} f && /Sent/ {print $2; exit}'
}

analiz() { # analiz <ad> <analiz argümanları...> : SONUC satırlarını (+)/(-) yapar, OLCUM satırlarını bilgi olarak yazar
    local ad="$1" line rc=0; shift
    python3 -I "$ANALIZ" "$KOSU_DIR" --arac "$N_ARAC" "$@" > "$TMP_DIR/$ad.analiz.log" 2>&1 || rc=$?
    while IFS= read -r line; do
        case "$line" in
            "SONUC gecti "*) log_ok "$ad: ${line#SONUC gecti }" ;;
            "SONUC kaldi "*) log_fail "$ad: ${line#SONUC kaldi }" ;;
            OLCUM*) log_info "$ad: $line" ;;
            Traceback*|*Error*) log_fail "$ad: analiz hatası: $line" ;;
        esac
    done < "$TMP_DIR/$ad.analiz.log"
    if [[ "$rc" -ne 0 ]]; then log_fail "$ad: analiz çıkış kodu $rc"; tail -n 12 "$TMP_DIR/$ad.analiz.log" | while IFS= read -r line; do log_info "  | $line"; done; fi
    cp "$TMP_DIR/$ad.analiz.log" "$KOSU_DIR/merkezi_analiz_$ad.log" 2>/dev/null || true
}

kayit_gecerli() { # kayit_gecerli <ad> : yeni kayıt dosyaları doğrulayıcıdan geçmeli (her araç için)
    local ad="$1" f out k dosyalar=("yer_istasyonu_kare")
    for k in "${SYS_IDS[@]:0:$N_ARAC}"; do dosyalar+=("arac_sureci_$k" "kamera_alici_$k" "gonderim_kuyrugu_$k" "isleme_kuyrugu_$k" "kare_sonuc_$k" "kare_poz_$k" "telemetri_$k"); done
    for f in "${dosyalar[@]}"; do
        if [[ ! -f "$KOSU_DIR/kayit/$f.jsonl" ]]; then log_fail "$ad: kayıt yok: $f.jsonl"; continue; fi
        if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kayit/$f.jsonl" 2>&1)"; then
            log_ok "$ad: gerçek kayıt doğrulayıcıdan geçti: $f.jsonl ($(tail -n 1 <<< "$out" | sed 's/, .*jsonl)/)/'))"
        else
            log_fail "$ad: kayıt GEÇERSİZ: $f.jsonl: $(head -n 3 <<< "$out" | tr '\n' ';')"
        fi
    done
    if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" 2>&1)"; then log_ok "$ad: görev olay kaydı doğrulayıcıdan geçti"; else log_fail "$ad: görev olay kaydı GEÇERSİZ: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
}

# kuyruk_dizinleri_temiz <ad> : tamamlanan koşuda disk kuyruğu bölütleri kalmamalı (boş kuyruk kapanışta dizinini siler); kalan en büyük disk kullanımı koşu klasöründe değildir
kuyruk_dizinleri_temiz() {
    local ad="$1" kalan
    if [[ ! -d "$KOSU_DIR/kuyruk" ]]; then log_ok "$ad: koşu klasöründe kuyruk/ dizini yok (bölüt kalmadı)"; return 0; fi
    kalan="$(find "$KOSU_DIR/kuyruk" -name 'bolut_*' 2>/dev/null | wc -l | tr -d ' ')" || kalan="?"
    if [[ "$kalan" == "0" ]]; then log_ok "$ad: disk kuyruğu bölütü kalmadı (boş kuyruklar kapanışta dizinlerini sildi)"; else log_fail "$ad: koşu klasöründe $kalan disk kuyruğu bölütü kaldı"; fi
}

# asama_dogrula <ad> : her kare için aşama damgaları tam ve sıralı (sozlesme_dogrula.py --kare-asamalari)
asama_dogrula() {
    local ad="$1" out
    if out="$(python3 -I "$DOGRULA" --kare-asamalari "$KOSU_DIR" 2>&1)"; then log_ok "$ad: kare aşama damgaları tam ve sıralı ($(tail -n 1 <<< "$out" | cut -c1-200))"; else log_fail "$ad: kare aşama damgaları GEÇERSİZ: $(head -n 4 <<< "$out" | tr '\n' ';')"; fi
}

# merkezi_kosu <ad> <analiz argümanları...> : (EK_ENV ile) merkezi koşu → bekle → doğrulama → analiz → durdur; tc sayaçları bekle çevresinde alınır
UC_KLASOR=""
TEK_KLASOR=""
merkezi_kosu() {
    local ad="$1" rc=0 tc0 tc1 arc k; shift
    if kosu_baslat "$ad" --arac "$N_ARAC" --yer-istasyonu var --mimari merkezi; then
        tc0="$(tc_bayt)"
        "$KOSU" bekle --sure-sn "$BEKLE_SN_TAM" > "$TMP_DIR/$ad.bekle.log" 2>&1 || rc=$?
        tc1="$(tc_bayt)"
        if [[ "$rc" -eq 0 ]]; then log_ok "$ad: kosu.sh bekle çıkış 0 (yer istasyonu tamamlandı)"; else log_fail "$ad: kosu.sh bekle çıkış kodu $rc"; tail -n 6 "$TMP_DIR/$ad.bekle.log"; fi
        local i
        for ((i = 0; i < 100; i++)); do pgrep -f 'swarm_vehicle[.]arac' >/dev/null || break; sleep 0.3; done   # araç süreci kendi kapanır (ARAC_KAPANIS_BEKLE_SN): kayıtlar tamamlansın
        kayit_gecerli "$ad"
        local ek=()
        [[ -z "$UC_KLASOR" || "$ad" != tek ]] || ek=(--uc-klasoru "$UC_KLASOR")
        [[ -z "$TEK_KLASOR" || "$ad" != uc_* ]] || ek=(--tek-klasoru "$TEK_KLASOR")
        analiz "$ad" "$@" --tc-once "$tc0" --tc-sonra "$tc1" "${ek[@]+"${ek[@]}"}"
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" tamamlandi merkezi
        kuyruk_dizinleri_temiz "$ad"
        asama_dogrula "$ad"
        local sira
        for ((sira = 1; sira <= N_ARAC; sira++)); do
            k="${SYS_IDS[$((sira - 1))]}"
            arc="$(cat "$KOSU_DIR/arac_${sira}.cikis" 2>/dev/null || echo yok)"
            if [[ "$arc" == "0" ]]; then log_ok "$ad: araç $k süreci çıkış kodu 0"; else log_fail "$ad: araç $k süreci çıkış kodu '$arc'"; fi
            if grep -q " merkezi_ozet " "$KOSU_DIR/arac_${k}.log" 2>/dev/null; then log_info "$ad: araç $k: $(grep -h ' merkezi_ozet ' "$KOSU_DIR/arac_${k}.log" | sed 's/^[^ ]* [^ ]* [^ ]* //')"; fi
            if grep -q " poz_ozeti " "$KOSU_DIR/arac_${k}.log" 2>/dev/null; then log_info "$ad: araç $k: $(grep -h ' poz_ozeti ' "$KOSU_DIR/arac_${k}.log" | sed 's/^[^ ]* [^ ]* [^ ]* //')"; fi
            if grep -q "kare_poz_hatasi\|merkezi_isleme_hatasi\|merkezi_kanal_hatasi\|goruntu_kanali_hata" "$KOSU_DIR/arac_${k}.log" 2>/dev/null; then log_fail "$ad: araç $k günlüğünde kanal/işleme/poz hatası kaydı var"; else log_ok "$ad: araç $k günlüğünde kanal/işleme/poz hatası kaydı yok"; fi
        done
        if [[ -f "$KOSU_DIR/yer_istasyonu.log" ]] && grep -q "merkezi_ozet" "$KOSU_DIR/yer_istasyonu.log"; then log_info "$ad: yer istasyonu: $(grep -h 'merkezi_ozet' "$KOSU_DIR/yer_istasyonu.log" | sed 's/^[^ ]* [^ ]* //' | cut -c1-900)"; fi
        if grep -q "merkezi_kanal_hatasi\|merkezi_isleme_hatasi" "$KOSU_DIR/yer_istasyonu.log" 2>/dev/null; then log_fail "$ad: yer istasyonu günlüğünde kanal/işleme hatası kaydı var"; else log_ok "$ad: yer istasyonu günlüğünde kanal/işleme hatası kaydı yok"; fi
    fi
}

# gunluk_sn <dosya> <olay> : günlükte olayın ilk geçtiği anın (ISO saat) epoch saniyesi (yoksa boş)
gunluk_sn() { local z; z="$(awk -v o="$2" '$3 == o || $4 == o {print $1; exit}' "$1" 2>/dev/null || true)"; [[ -z "$z" ]] || date -d "$z" +%s.%N; }

want() { local t; for t in "${TESTS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

# iz_tara: depoya girecek içerikte süreç izi (rol adları, iş numaraları, iç belge yolları ve ilgili sözcükler) arar; bulunan satırları yazar (boş = temiz).
# Kapsam: çalışma ağacı farkında eklenen satırlar + izlenmeyen yeni dosyalar + son commit'te (git show HEAD) eklenen satırlar. Desen kendi metnini eşlemesin diye köşeli parantez kalıbı kullanır.
# IZ_HEAD_ATLA=1: son commit taranmaz (yalnız commit atmadan önceki koşular için; commit sonrası koşu anahtarsız yapılır).
# Açık izin listesi (yanlış alarm): donanım adları (ekran/ses/grafik + ilgili sözcük).
IZ_DESEN='(^|[^A-Za-z0-9])[Tt]-0[0-9]{2}|[Uu]retic[i]|[Üü]retic[i]|[Dd]enetle[y]ici|[Cc]lau[d]e|review[s]/|task[s]/|\<[Kk]ar[t]'
iz_tara() {
    { git -C "$ROOT_DIR" diff -U0 HEAD -- . ':!setup/locks' | grep -E '^\+[^+]' || true
      git -C "$ROOT_DIR" ls-files --others --exclude-standard | (cd "$ROOT_DIR" && xargs -r cat)
      [[ "${IZ_HEAD_ATLA:-0}" == 1 ]] || git -C "$ROOT_DIR" show HEAD --format= -U0 -- . ':!setup/locks' | grep -E '^\+[^+]' || true
    } | grep -nE "$IZ_DESEN" | grep -vE '(ekran|ses|grafik) kar[t]' || true
}

# --- Testler ----------------------------------------------------------------------------
test_birim() {
    local out rc=0 l f mod
    log_info "== birim: ileti/kuyruk/alıcı birim testleri, derleme, içe aktarma, tek komut yolu, süreç izi =="
    for f in "${BIRIM_TESTLER[@]}"; do
        if out="$("$VENV_PY" -I "$f" 2>&1)"; then log_ok "birim: $(basename "$f") geçti ($(grep -E '^Ran ' <<< "$out"))"; else log_fail "birim: $(basename "$f") BAŞARISIZ"; tail -n 15 <<< "$out"; fi
    done
    out="$GENERATED_DIR/merkezi_mod_derleme.txt"
    if proje_derle "$out"; then
        log_ok "birim: proje derlendi (swarm_msgs + swarm_vehicle + swarm_gcs; ortak yol: setup/lib/derleme.sh)"
    else
        log_fail "birim: proje derlemesi BAŞARISIZ; günlük: ${out#"$ROOT_DIR"/}"
        tail -n 12 "$out" | while IFS= read -r l; do log_info "  | $l"; done
    fi
    # yer istasyonu: dinleme portu geçici port aralığındaysa GPU çıkarım işçileri BAŞLAMADAN açık hata (çıkış 2), temiz kapanış (koşu yok, araç yok; ağa yalnız DDS keşfi çıkar)
    local alt portenv="$TMP_DIR/deney_port_icinde.env" gout="$TMP_DIR/gcs_port.out" t_port
    alt="$(awk '{print $1}' /proc/sys/net/ipv4/ip_local_port_range 2>/dev/null || true)"
    if [[ "$alt" =~ ^[0-9]+$ ]]; then
        sed "s/^MERKEZI_TCP_PORT_TABAN=.*/MERKEZI_TCP_PORT_TABAN=\"$((alt + 10))\"/" "$DENEY_ENV" > "$portenv"
        rc=0; t_port=$SECONDS
        # shellcheck disable=SC2016  # tek tırnak bilerek: $1.. alt kabukta açılır
        env -u VIRTUAL_ENV LC_NUMERIC=C DENEY_ENV="$portenv" MIMARI_MODU=merkezi timeout -k 5 120 bash -c 'source "$1" >/dev/null 2>&1; source "$2/install/setup.bash"; cd "$2"; exec python -m swarm_gcs.gorev_koordinatoru --arac 3' _ "$SETUP_DIR/env.sh" "$ROOT_DIR" > "$gout" 2>&1 || rc=$?
        if [[ "$rc" -eq 2 && "$(cat "$gout")" == *"geçici port aralığının"* && "$(cat "$gout")" != *Traceback* ]]; then
            log_ok "birim: yer istasyonu, geçici aralıktaki dinleme portunu $((SECONDS - t_port)) sn içinde açık hatayla reddetti (çıkış 2, Traceback yok)"
        else
            log_fail "birim: yer istasyonu aralık içi dinleme portunu beklenen biçimde reddetmedi (çıkış $rc)"; tail -n 6 "$gout"
        fi
        if [[ -z "$(pgrep -af 'swarm_vehicle[.]cikarim_isci|swarm_gcs[.]gorev_koordinatoru' || true)" ]]; then log_ok "birim: çıkarım işçisi/yer istasyonu süreci kalmadı"; else log_fail "birim: port reddinden sonra süreç kaldı"; fi
    else
        log_warn "birim: geçici port aralığı okunamadı; yer istasyonu aralık reddi atlandı"
    fi
    for mod in swarm_vehicle.merkezi_mod.goruntu_ileti swarm_vehicle.merkezi_mod.goruntu_kanali swarm_vehicle.kamera.disk_kuyrugu swarm_gcs.merkezi_mod.merkezi_alici; do
        rc=0
        # shellcheck disable=SC2016  # tek tırnak bilerek: Python kodu
        "$VENV_PY" -I -c 'import sys; sys.path[:0] = sys.argv[1:3]; import importlib; importlib.import_module(sys.argv[3]); assert "rclpy" not in sys.modules and "mavsdk" not in sys.modules' "$PKG_DIR" "$GCS_DIR" "$mod" > "$TMP_DIR/ice.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "birim: $mod rclpy ve mavsdk olmadan içe aktarıldı"; else log_fail "birim: $mod içe aktarma hatası"; tail -n 5 "$TMP_DIR/ice.log"; fi
    done
    rc=0
    "$VENV_PY" -m py_compile "$PKG_DIR"/swarm_vehicle/{merkezi_mod/goruntu_ileti,merkezi_mod/goruntu_kanali,kamera/disk_kuyrugu,arac,cikarim/kare_isleyici,cikarim/kare_sonuc,kamera/kamera_alici,kamera/kamera_alici_gz,ucus/rota,ucus/port_denetimi}.py "$GCS_DIR"/swarm_gcs/{merkezi_mod/merkezi_alici,uc_mod/sonuc_alici,gorev_koordinatoru,gorev/gorev_mantik}.py "$ANALIZ" "$DOGRULA" > "$TMP_DIR/pyc.log" 2>&1 || rc=$?
    if [[ "$rc" -eq 0 ]]; then log_ok "birim: py_compile temiz"; else log_fail "birim: py_compile hata"; tail -n 5 "$TMP_DIR/pyc.log"; fi
    out="$(git -C "$ROOT_DIR" grep --untracked -nE '^\s*(from|import) mavsdk' -- src || true)"
    if [[ -n "$out" && "$(awk -F: '{print $1}' <<< "$out" | sort -u)" == "src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py" ]]; then log_ok "birim: src/ altında mavsdk'yı içe aktaran tek dosya px4_adapter.py"; else log_fail "birim: mavsdk içe aktarımı beklenenden farklı: $out"; fi
    out="$(git -C "$ROOT_DIR" grep --untracked -nE '\.action\.|\.mission\b|\.mission_raw|\.param\.set|set_param|set_rate_|\.offboard\.|send_message' -- src ':!src/swarm_vehicle/swarm_vehicle/ucus/px4_adapter.py' || true)"
    if [[ -z "$out" ]]; then log_ok "birim: src/ altında px4_adapter.py dışında PX4'e yazan çağrı yok"; else log_fail "birim: dış çağrı: $out"; fi
    out="$(grep -cE '^[[:space:]]*self\.komut_sayaci \+= 1' "$PKG_DIR/swarm_vehicle/ucus/px4_adapter.py" || true)"
    if [[ "$out" == "1" ]]; then log_ok "birim: komut sayacını artıran tek yer _yaz (px4_adapter.py)"; else log_fail "birim: komut_sayaci artışı $out yerde"; fi
    out="$(git -C "$ROOT_DIR" grep --untracked -nE '127\.0\.0\.1' -- src/swarm_vehicle/swarm_vehicle/merkezi_mod/goruntu_kanali.py src/swarm_gcs/swarm_gcs/merkezi_mod/merkezi_alici.py || true)"
    if [[ -z "$out" ]]; then log_ok "birim: kanal kodunda 127.0.0.1 yok (kanal ölçülen sürü ağı adreslerini kullanır)"; else log_fail "birim: kanal kodunda 127.0.0.1: $out"; fi
    out="$(iz_tara)"
    if [[ -z "$out" ]]; then log_ok "birim: çalışma ağacı farkında, yeni dosyalarda ve son commit'te süreç izi yok"; else log_fail "birim: süreç izi: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
    for f in kuyruk_durumu_ornek isleme_kuyrugu_ornek kuyruk_tasmasi_ornek kare_sonuc_ornek kare_olay_arac_sureci_ornek kare_olay_yer_istasyonu_ornek kare_olay_kamera_alici_ornek; do
        if out="$(python3 -I "$DOGRULA" "$ROOT_DIR/config/ornek/$f.jsonl" 2>&1)"; then log_ok "birim: örnek doğrulayıcıdan geçti: $f.jsonl"; else log_fail "birim: örnek GEÇERSİZ: $f.jsonl: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
    done
    if out="$("$KOSU" --dry-run baslat --arac 1 --mimari merkezi 2>&1)"; then log_fail "birim: --mimari merkezi, --yer-istasyonu olmadan reddedilmeliydi"; else log_ok "birim: --mimari merkezi yer istasyonu olmadan reddedildi"; fi
    if out="$("$KOSU" --dry-run baslat --arac 1 --yer-istasyonu var --mimari yok 2>&1)"; then log_fail "birim: geçersiz mimari reddedilmeliydi"; else log_ok "birim: geçersiz mimari reddedildi"; fi
}

test_tek() {
    log_info "== tek: uçta mod başvuru koşusu, sonra merkezi koşu (tek araç) =="
    EK_ENV=()
    local rc=0
    if kosu_baslat tek_uc_basvuru --arac 1 --yer-istasyonu var; then
        "$KOSU" bekle --sure-sn "$BEKLE_SN_TAM" > "$TMP_DIR/tek_uc.bekle.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then log_ok "tek_uc_basvuru: kosu.sh bekle çıkış 0"; else log_fail "tek_uc_basvuru: kosu.sh bekle çıkış kodu $rc"; fi
        local i
        for ((i = 0; i < 100; i++)); do pgrep -f 'swarm_vehicle[.]arac' >/dev/null || break; sleep 0.3; done
        UC_KLASOR="$KOSU_DIR"
        komut_dene "$TMP_DIR/tek_uc.durdur.log" "tek_uc_basvuru: durdur tamam" "tek_uc_basvuru: durdur başarısız" "$KOSU" durdur
        json_gecerli tek_uc_basvuru tamamlandi ucta
    fi
    kalan_yok tek_uc_basvuru
    EK_ENV=("MERKEZI_SHA=1")
    merkezi_kosu tek --sha
    EK_ENV=()
    kalan_yok tek
}

test_hata() {
    log_info "== hata: merkezi mod, kare kaybı (KAMERA_ENJEKSIYON=dusur=+20) ve işçi hatası (ISCI_ENJEKSIYON=hata=+40) =="
    EK_ENV=("KAMERA_ENJEKSIYON=dusur=+20" "ISCI_ENJEKSIYON=hata=+40" "MERKEZI_SHA=1")
    merkezi_kosu hata --hata --sha
    EK_ENV=()
    kalan_yok hata
}

test_kapat() {
    log_info "== kapat: merkezi mod, araç kanalı n>=$KAPAT_N sonrası bilerek temiz kapatır (MERKEZI_ARAC_ENJEKSIYON=kanal_kapat=$KAPAT_N:$KAPAT_BEKLE_SN) =="
    EK_ENV=("MERKEZI_ARAC_ENJEKSIYON=kanal_kapat=$KAPAT_N:$KAPAT_BEKLE_SN")
    local rc=0 t_kapat t_hata ust fark
    if kosu_baslat kapat --arac 1 --yer-istasyonu var --mimari merkezi; then
        "$KOSU" bekle --sure-sn "$BEKLE_SN_TAM" > "$TMP_DIR/kapat.bekle.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 1 ]]; then log_ok "kapat: yer istasyonu açık hatayla çıktı (çıkış 1; zaman aşımı/öldü değil)"; else log_fail "kapat: kosu.sh bekle çıkış kodu $rc (beklenen 1)"; tail -n 6 "$TMP_DIR/kapat.bekle.log"; fi
        local i
        for ((i = 0; i < 100; i++)); do pgrep -f 'swarm_vehicle[.]arac' >/dev/null || break; sleep 0.3; done
        t_kapat="$(gunluk_sn "$KOSU_DIR/arac_${KIMLIK}.log" goruntu_kanali_enjeksiyon_temiz_kapatildi)"
        t_hata="$(gunluk_sn "$KOSU_DIR/yer_istasyonu.log" merkezi_kanal_hatasi)"
        if [[ -n "$t_kapat" ]]; then log_ok "kapat: araç kanalı bilerek temiz kapattı"; else log_fail "kapat: araç günlüğünde temiz kapatma olayı yok"; fi
        if [[ -n "$t_hata" ]]; then log_ok "kapat: yer istasyonu günlüğünde merkezi_kanal_hatasi var"; else log_fail "kapat: yer istasyonu günlüğünde merkezi_kanal_hatasi yok"; fi
        if [[ -n "$t_kapat" && -n "$t_hata" ]]; then
            fark="$(awk -v a="$t_kapat" -v b="$t_hata" 'BEGIN {printf "%.1f", b - a}')"
            ust="${GCS_UST_SN:-$(sed -n 's/^GCS_UST_SN="\{0,1\}\([0-9.]*\)"\{0,1\}$/\1/p' "$DENEY_ENV")}"
            if awk -v f="$fark" -v s="$KAPAT_SINIR_SN" 'BEGIN {exit !(f >= 0 && f <= s)}'; then log_ok "kapat: kanal kapanışından açık hataya $fark sn (sınır $KAPAT_SINIR_SN sn; yer istasyonu üst süresi ${ust:-?} sn'den çok önce)"; else log_fail "kapat: kanal kapanışından açık hataya $fark sn (sınır $KAPAT_SINIR_SN sn)"; fi
            log_info "kapat: OLCUM açık hata gecikmesi $fark sn"
        fi
        if grep -q "tamamlanmadan_kapand" "$KOSU_DIR/yer_istasyonu.log" 2>/dev/null; then log_ok "kapat: hata nedeni 'bağlantı araç tamamlanmadan kapandı'"; else log_fail "kapat: hata nedeni günlükte yok"; fi
        if grep -q " arac_erken_cikti " "$KOSU_DIR/yer_istasyonu.log" 2>/dev/null; then log_fail "kapat: yazılan neden arac_erken_cikti (kanal kapandıktan sonra araç $KAPAT_BEKLE_SN sn yaşadığı için kanal_hatasi beklenirdi)"; else log_ok "kapat: yazılan neden kanal_hatasi (arac_erken_cikti yok)"; fi
        if grep -q '"olay": "t1"' "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" 2>/dev/null; then log_fail "kapat: COMPLETE yayımlandı (t1 var) — yayımlanmamalıydı"; else log_ok "kapat: COMPLETE yayımlanmadı (t1 yok)"; fi
        if grep -q '"neden": "kanal_hatasi"' "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" 2>/dev/null; then log_ok "kapat: görev kaydında hata olayı (kanal_hatasi)"; else log_fail "kapat: görev kaydında kanal_hatasi olayı yok"; fi
        local arc
        arc="$(cat "$KOSU_DIR/arac_${KIMLIK}.cikis" 2>/dev/null || echo yok)"
        if [[ "$arc" != "0" ]]; then log_ok "kapat: araç süreci hatayla çıktı (çıkış '$arc'; kanal durduğu için COMPLETE beklemedi)"; else log_fail "kapat: araç süreci çıkış 0 (kanal durmuşken tamamlandı sayılmamalı)"; fi
        komut_dene "$TMP_DIR/kapat.durdur.log" "kapat: durdur tamam" "kapat: durdur başarısız" "$KOSU" durdur
    fi
    EK_ENV=()
    kalan_yok kapat
}

# satir_sayisi <dosya> : dosyadaki satır sayısı (yoksa 0)
satir_sayisi() { if [[ -f "$1" ]]; then wc -l < "$1" | tr -d ' '; else echo 0; fi; }

test_sigterm() {
    log_info "== sigterm: merkezi mod, tarama ortasında araç süreci SIGTERM alır; kayıt yazıcıları kapanışta boşalmalı =="
    EK_ENV=()
    local i pid pids son=0 yaz dus kap hata dosya satir ozet arc bekle ver tam sira_ozet sira_kapandi
    if kosu_baslat sigterm --arac 1 --yer-istasyonu var --mimari merkezi; then
        bekle=$((SIGTERM_BEKLE_SN * 2))
        for ((i = 0; i < bekle; i++)); do
            son="$(satir_sayisi "$KOSU_DIR/kayit/kare_poz_${KIMLIK}.jsonl")"
            [[ "$son" -lt "$SIGTERM_KARE" ]] || break
            sleep 0.5
        done
        if [[ "$son" -ge "$SIGTERM_KARE" ]]; then log_ok "sigterm: tarama ortasında ($son kare_poz satırı)"; else log_fail "sigterm: tarama ortasına ulaşılamadı ($son satır)"; fi
        pids="$(pgrep -f ' -m swarm_vehicle[.]arac 1$' || true)"                  # yalnız python süreci (kabuk sarmalayıcısı değil)
        if [[ -z "$pids" ]]; then log_fail "sigterm: araç süreci bulunamadı"; fi
        for pid in $pids; do kill -TERM "$pid" 2>/dev/null || true; done           # PID ile; desenle öldürme yok
        for ((i = 0; i < 200; i++)); do pgrep -f 'swarm_vehicle[.]arac' >/dev/null || break; sleep 0.2; done
        if pgrep -f 'swarm_vehicle[.]arac' >/dev/null; then log_fail "sigterm: araç süreci SIGTERM'den sonra 40 sn içinde çıkmadı"; else log_ok "sigterm: araç süreci SIGTERM ile çıktı"; fi
        sleep 1
        arc="$(cat "$KOSU_DIR/arac_${KIMLIK}.cikis" 2>/dev/null || echo yok)"
        if [[ "$arc" == "143" ]]; then log_ok "sigterm: araç çıkış kodu 143 (128+SIGTERM; 134 çökme değil)"; else log_fail "sigterm: araç çıkış kodu '$arc' (beklenen 143)"; fi
        if grep -q "sinyal numara=15" "$KOSU_DIR/arac_${KIMLIK}.log" 2>/dev/null; then log_ok "sigterm: günlükte sinyal kaydı var"; else log_fail "sigterm: günlükte sinyal kaydı yok"; fi
        if grep -q " kapandi " "$KOSU_DIR/arac_${KIMLIK}.log" 2>/dev/null; then log_ok "sigterm: günlükte kapandi satırı var"; else log_fail "sigterm: günlükte kapandi satırı yok"; fi
        for dosya in "kare_poz_$KIMLIK" "gonderim_kuyrugu_$KIMLIK" "arac_sureci_$KIMLIK"; do
            ozet="$(grep -h " satir_yazici_ozet yol=$dosya.jsonl " "$KOSU_DIR/arac_${KIMLIK}.log" 2>/dev/null || true)"
            if [[ "$(grep -c . <<< "$ozet")" != "1" ]]; then log_fail "sigterm: $dosya için satir_yazici_ozet satır sayısı $(grep -c . <<< "$ozet") (beklenen 1)"; continue; fi
            yaz="$(sed -n 's/.* yazilan=\([0-9]*\) .*/\1/p' <<< "$ozet")"; dus="$(sed -n 's/.* dusen=\([0-9]*\) .*/\1/p' <<< "$ozet")"
            kap="$(sed -n 's/.* kapali_sonrasi=\([0-9]*\) .*/\1/p' <<< "$ozet")"; hata="$(sed -n 's/.* hata=\(.*\)$/\1/p' <<< "$ozet")"
            satir="$(satir_sayisi "$KOSU_DIR/kayit/$dosya.jsonl")"
            ver="$(sed -n 's/.* verilen=\([0-9]*\) .*/\1/p' <<< "$ozet")"; tam="$(sed -n 's/.* tamam=\([A-Za-z]*\) .*/\1/p' <<< "$ozet")"
            if [[ "$yaz" == "$satir" && "$dus" == "0" && "$hata" == "None" ]]; then log_ok "sigterm: $dosya: yazilan=$yaz = dosya satırı $satir, dusen=0, hata yok (kapali_sonrasi=$kap)"; else log_fail "sigterm: $dosya: yazilan=$yaz dosya=$satir dusen=$dus hata=$hata"; fi
            if [[ -n "$ver" && "$((yaz + dus + kap))" == "$ver" && "$tam" == "True" ]]; then log_ok "sigterm: $dosya: yazilan + dusen + kapali_sonrasi = $((yaz + dus + kap)) = verilen $ver, yazıcı tamam"; else log_fail "sigterm: $dosya: denklik bozuk (yazilan=$yaz dusen=$dus kapali_sonrasi=$kap verilen=${ver:-yok} tamam=${tam:-yok})"; fi
            sira_ozet="$(grep -n " satir_yazici_ozet yol=$dosya.jsonl " "$KOSU_DIR/arac_${KIMLIK}.log" | head -n 1 | cut -d: -f1)"
            sira_kapandi="$(grep -n " kapandi " "$KOSU_DIR/arac_${KIMLIK}.log" | tail -n 1 | cut -d: -f1)"
            if [[ -n "$sira_ozet" && -n "$sira_kapandi" && "$sira_ozet" -lt "$sira_kapandi" ]]; then log_ok "sigterm: $dosya: satir_yazici_ozet (satır $sira_ozet) kapandi satırından (satır $sira_kapandi) önce"; else log_fail "sigterm: $dosya: satir_yazici_ozet kapandi'dan önce değil (özet ${sira_ozet:-yok}, kapandi ${sira_kapandi:-yok})"; fi
            log_info "sigterm: OLCUM $dosya yazilan=$yaz dusen=$dus kapali_sonrasi=$kap verilen=${ver:-yok} satir=$satir"
        done
        komut_dene "$TMP_DIR/sigterm.durdur.log" "sigterm: durdur tamam" "sigterm: durdur başarısız" "$KOSU" durdur
    fi
    kalan_yok sigterm
}

test_basinc() {
    log_info "== basinc: merkezi mod, yer istasyonu alıcısı okumayı durdurur (MERKEZI_ENJEKSIYON=okuma_dur=$BASINC_BASLANGIC:$BASINC_SURE) =="
    EK_ENV=("MERKEZI_ENJEKSIYON=okuma_dur=$BASINC_BASLANGIC:$BASINC_SURE" "MERKEZI_SHA=1")
    merkezi_kosu basinc --basinc "$BASINC_BASLANGIC:$BASINC_SURE" --sha
    EK_ENV=()
    kalan_yok basinc
}

# mtime_sn <dosya> : dosyanın son değişiklik anı (epoch saniye, ondalık; yoksa boş)
mtime_sn() { stat -c %.9Y "$1" 2>/dev/null || true; }

test_uc() {
    log_info "== uc: üç araç, doygun hat (25 Mbit/s): merkezi mod, her araç için ayrı kayıpsızlık ölçütü, $UC_TEKRAR koşu =="
    local i
    N_ARAC=1; TEK_KLASOR=""
    EK_ENV=("MERKEZI_SHA=1")
    merkezi_kosu uc_taban --sha                                 # aynı makinede tek araç merkezi koşu: yalnız L farkı raporu için başvuru
    TEK_KLASOR="$KOSU_DIR"
    kalan_yok uc_taban
    N_ARAC=3
    for ((i = 1; i <= UC_TEKRAR; i++)); do
        EK_ENV=("MERKEZI_SHA=1")
        merkezi_kosu "uc_$i" --sha
        kalan_yok "uc_$i"
    done
    EK_ENV=(); N_ARAC=1; TEK_KLASOR=""
}

# erken_senaryo <ad> <ARAC_TEST_CIKIS değeri> <araç kimliği> <beklenen evre> : tek bir erken çıkış koşusu (GCS_UST_SN geçersiz kılınmaz)
erken_senaryo() {
    local ad="$1" anahtar="$2" kimlik="$3" evre="$4" rc=0 t_arac t_gcs fark bd gk l
    EK_ENV=("ARAC_TEST_CIKIS=$anahtar")
    local yapilandirma_ust="${GCS_UST_SN:-}"   # deney.env'den gelen değer ortamda zaten vardır; geçersiz kılma = yapılandırmadan FARKLI değer
    yapilandirma_ust="$(sed -n 's/^GCS_UST_SN="\{0,1\}\([0-9.]*\)"\{0,1\}$/\1/p' "$DENEY_ENV")"
    if [[ "${GCS_UST_SN:-$yapilandirma_ust}" != "$yapilandirma_ust" ]]; then log_fail "$ad: GCS_UST_SN geçersiz kılınmış (${GCS_UST_SN}; yapılandırma $yapilandirma_ust); bu testte geçersiz kılınmamalı"; else log_ok "$ad: GCS_UST_SN geçersiz kılınmadı (yapılandırma değeri $yapilandirma_ust sn)"; fi
    if kosu_baslat "$ad" --arac 3 --yer-istasyonu var --mimari merkezi; then
        "$KOSU" bekle --sure-sn "$ERKEN_BEKLE_SN" > "$TMP_DIR/$ad.bekle.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 1 ]]; then log_ok "$ad: kosu.sh bekle çıkış 1 (yer istasyonu açık hatayla bitti; bekleme süresi dolmadı)"; else log_fail "$ad: kosu.sh bekle çıkış kodu $rc (beklenen 1; 124 = kural işlemedi, süre doldu)"; tail -n 6 "$TMP_DIR/$ad.bekle.log"; fi
        gk="$(cat "$KOSU_DIR/yer_istasyonu.cikis" 2>/dev/null || echo yok)"
        if [[ "$gk" == "1" ]]; then log_ok "$ad: yer istasyonu çıkış kodu 1"; else log_fail "$ad: yer istasyonu çıkış kodu '$gk' (beklenen 1)"; fi
        local sira=0 j
        for ((j = 0; j < 3; j++)); do [[ "${SYS_IDS[$j]}" == "$kimlik" ]] && sira=$((j + 1)); done
        l="$(cat "$KOSU_DIR/arac_${sira}.cikis" 2>/dev/null || echo yok)"
        if [[ "$l" == "70" ]]; then log_ok "$ad: araç $kimlik süreci test anahtarıyla çıkış 70 ile çıktı"; else log_fail "$ad: araç $kimlik çıkış kodu '$l' (beklenen 70)"; fi
        t_arac="$(mtime_sn "$KOSU_DIR/arac_${sira}.cikis")"; t_gcs="$(mtime_sn "$KOSU_DIR/yer_istasyonu.cikis")"
        if [[ -n "$t_arac" && -n "$t_gcs" ]]; then
            fark="$(awk -v a="$t_arac" -v b="$t_gcs" 'BEGIN {printf "%.2f", b - a}')"
            if awk -v f="$fark" -v s="$ERKEN_SINIR_SN" 'BEGIN {exit !(f >= 0 && f <= s)}'; then log_ok "$ad: yer istasyonu ilk araç çıkışından $fark sn sonra bitti (sınır $ERKEN_SINIR_SN sn; GCS_UST_SN 1800 sn)"; else log_fail "$ad: ilk araç çıkışından yer istasyonu çıkışına $fark sn (sınır $ERKEN_SINIR_SN sn)"; fi
            log_info "$ad: OLCUM araç çıkışından yer istasyonu çıkışına $fark sn"
        else
            log_fail "$ad: çıkış dosyası zamanları okunamadı (araç '$t_arac', yer istasyonu '$t_gcs')"
        fi
        if grep -q "$kimlik" "$KOSU_DIR/yer_istasyonu.log" 2>/dev/null && grep -q " arac_erken_cikti arac=$kimlik cikis_kodu=70 evre=$evre" "$KOSU_DIR/yer_istasyonu.log" 2>/dev/null; then
            log_ok "$ad: yer istasyonu günlüğünde 'arac_erken_cikti arac=$kimlik cikis_kodu=70 evre=$evre' satırı var"
        else
            log_fail "$ad: yer istasyonu günlüğünde beklenen arac_erken_cikti satırı yok"; grep -h "arac_erken_cikti" "$KOSU_DIR/yer_istasyonu.log" 2>/dev/null || true
        fi
        if grep -q "(-) KOORDINATOR hata: araç $kimlik süreci COMPLETE'ten önce çıktı" "$KOSU_DIR/yer_istasyonu.out" 2>/dev/null; then log_ok "$ad: yer istasyonu çıktısında açık hata satırı var"; else log_fail "$ad: yer istasyonu çıktısında açık hata satırı yok"; tail -n 4 "$KOSU_DIR/yer_istasyonu.out"; fi
        if grep -q "\"neden\": \"arac_erken_cikti\", \"arac_kimligi\": $kimlik" "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" 2>/dev/null; then log_ok "$ad: görev kaydında hata olayı (arac_erken_cikti, araç $kimlik)"; else log_fail "$ad: görev kaydında arac_erken_cikti olayı yok"; fi
        if grep -q '"olay": "t1"' "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" 2>/dev/null; then log_fail "$ad: COMPLETE yayımlandı (t1 var) — yayımlanmamalıydı"; else log_ok "$ad: COMPLETE yayımlanmadı (t1 yok)"; fi
        if [[ "$evre" == t0_oncesi ]]; then
            if grep -q '"olay": "t0"' "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" 2>/dev/null; then log_fail "$ad: ScanStart yayımlanmış (t0 var); araç t0'dan önce çıkmalıydı"; else log_ok "$ad: ScanStart yayımlanmadı (t0 yok): araç t0'dan önce çıktı"; fi
        else
            if grep -q '"olay": "t0"' "$KOSU_DIR/kayit/yer_istasyonu_gorev.jsonl" 2>/dev/null; then log_ok "$ad: ScanStart yayımlanmıştı (t0 var): araç t0'dan sonra çıktı"; else log_fail "$ad: t0 yok; araç t0'dan sonra çıkmalıydı"; fi
        fi
        komut_dene "$TMP_DIR/$ad.durdur.log" "$ad: durdur tamam" "$ad: durdur başarısız" "$KOSU" durdur
        json_gecerli "$ad" yarida_kaldi merkezi
    fi
    EK_ENV=()
    kalan_yok "$ad"
}

test_erken() {
    log_info "== erken: COMPLETE'ten önce bir araç süreci çıkar; yer istasyonu en çok $ERKEN_SINIR_SN sn içinde açık hatayla biter (GCS_UST_SN geçersiz kılınmaz) =="
    [[ "${#SYS_IDS[@]}" -ge 3 ]] || { log_fail "erken: yapılandırmada 3 araç yok"; return; }
    erken_senaryo erken_a "${SYS_IDS[1]}:bariyer" "${SYS_IDS[1]}" t0_oncesi
    erken_senaryo erken_b "${SYS_IDS[2]}:tarama:$ERKEN_TARAMA_SN" "${SYS_IDS[2]}" t0_sonrasi
}

test_tasma() {
    log_info "== tasma: merkezi mod, araç gönderim kuyruğunun $TASMA_N'inci yazması yapay ENOSPC alır (KUYRUK_TEST_TASMA=gonderim_${KIMLIK}:$TASMA_N); kare sessiz atılmaz =="
    EK_ENV=("KUYRUK_TEST_TASMA=gonderim_${KIMLIK}:$TASMA_N")
    local rc=0 arc t_tasma t_gcs fark i out
    if kosu_baslat tasma --arac 1 --yer-istasyonu var --mimari merkezi; then
        "$KOSU" bekle --sure-sn "$BEKLE_SN_TAM" > "$TMP_DIR/tasma.bekle.log" 2>&1 || rc=$?
        if [[ "$rc" -eq 1 ]]; then log_ok "tasma: yer istasyonu açık hatayla çıktı (çıkış 1; zaman aşımı/öldü değil)"; else log_fail "tasma: kosu.sh bekle çıkış kodu $rc (beklenen 1)"; tail -n 6 "$TMP_DIR/tasma.bekle.log"; fi
        for ((i = 0; i < 100; i++)); do pgrep -f 'swarm_vehicle[.]arac' >/dev/null || break; sleep 0.3; done
        arc="$(cat "$KOSU_DIR/arac_${KIMLIK}.cikis" 2>/dev/null || echo yok)"
        if [[ "$arc" != "0" && "$arc" != "yok" ]]; then log_ok "tasma: araç süreci hata çıkışı yaptı (çıkış '$arc'; kuyruk taşması tamamlanmış sayılmadı)"; else log_fail "tasma: araç süreci çıkış '$arc' (hata çıkışı beklenir)"; fi
        if grep -q "KUYRUK_TEST_TASMA" "$KOSU_DIR/arac_${KIMLIK}.log" 2>/dev/null && grep -q "seviye=(!)" "$KOSU_DIR/arac_${KIMLIK}.log" 2>/dev/null; then log_ok "tasma: araç günlüğünde test anahtarı açık uyarısı ((!) test_anahtari_acik) var"; else log_fail "tasma: araç günlüğünde test anahtarı açık uyarısı yok"; fi
        t_tasma="$(gunluk_sn "$KOSU_DIR/arac_${KIMLIK}.log" kuyruk_tasmasi)"; t_gcs="$(mtime_sn "$KOSU_DIR/yer_istasyonu.cikis")"
        if [[ -n "$t_tasma" && -n "$t_gcs" ]]; then
            fark="$(awk -v a="$t_tasma" -v b="$t_gcs" 'BEGIN {printf "%.1f", b - a}')"
            if awk -v f="$fark" -v s="$KAPAT_SINIR_SN" 'BEGIN {exit !(f >= 0 && f <= s)}'; then log_ok "tasma: taşmadan yer istasyonunun açık hatayla bitişine $fark sn (sınır $KAPAT_SINIR_SN sn)"; else log_fail "tasma: taşmadan yer istasyonunun bitişine $fark sn (sınır $KAPAT_SINIR_SN sn)"; fi
            log_info "tasma: OLCUM taşmadan yer istasyonu çıkışına $fark sn"
        else
            log_fail "tasma: kuyruk_tasmasi günlük anı ya da yer istasyonu çıkışı okunamadı"
        fi
        if out="$(python3 -I "$DOGRULA" "$KOSU_DIR/kayit/kuyruk_tasmasi_gonderim_${KIMLIK}.jsonl" 2>&1)"; then log_ok "tasma: taşma kaydı doğrulayıcıdan geçti: $(tail -n 1 <<< "$out" | cut -c1-120)"; else log_fail "tasma: taşma kaydı GEÇERSİZ: $(head -n 3 <<< "$out" | tr '\n' ';')"; fi
        analiz tasma --tasma "gonderim_${KIMLIK}"
        komut_dene "$TMP_DIR/tasma.durdur.log" "tasma: durdur tamam" "tasma: durdur başarısız" "$KOSU" durdur
        json_gecerli tasma yarida_kaldi merkezi
    fi
    EK_ENV=()
    kalan_yok tasma
}

snapshot once
DAEMON_ONCE=0; if pgrep -f '[r]os2-daemon' >/dev/null; then DAEMON_ONCE=1; fi
[[ "$DAEMON_ONCE" -eq 0 ]] || log_warn "Başlangıçta ros2 daemon yaşıyor (ölçülen ağa trafik basar); önce durdurun"
if [[ -n "$(pgrep -a -x gz; pgrep -a -x ruby; pgrep -a -x px4; pgrep -a -x mavsdk_server; pgrep -af 'swarm_vehicle[.]arac|swarm_gcs[.]gorev_koordinatoru')" ]]; then
    fail_stop "Başlangıçta gz/ruby/px4/mavsdk_server/araç süreci/yer istasyonu yaşıyor; önce kapatın"
fi
[[ ! -f "$KOK/aktif" ]] || fail_stop "Bitmemiş bir koşu var ($(cat "$KOK/aktif")); önce araclar/kosu.sh temizle"
log_info "gz $(gz sim --versions 2>/dev/null | sed -n 1p || true), ROS $ROS_DISTRO, PX4 $PX4_TAG; testler: ${TESTS[*]}"

if want birim; then test_birim; fi
if want tek; then test_tek; fi
if want hata; then test_hata; fi
if want basinc; then test_basinc; fi
if want kapat; then test_kapat; fi
if want sigterm; then test_sigterm; fi
if want uc; then test_uc; fi
if want erken; then test_erken; fi
if want tasma; then test_tasma; fi

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
