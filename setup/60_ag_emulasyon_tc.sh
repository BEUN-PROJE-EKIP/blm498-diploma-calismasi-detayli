#!/usr/bin/env bash
# 60_ag_emulasyon_tc.sh — Ağ emülasyonu (tc): loopback üzerinde sürü ağı (SWARM_NET) ve tek ortak kapasite sınırlayıcı (LINK_RATE_MBIT).
# Kullanım: ./60_ag_emulasyon_tc.sh [--dry-run | --verify | --remove | -h]
#   (argümansız)  4 adresi lo'ya /32 ekler; lo'ya htb kök + 1:10 sınırlayıcı sınıf + bfifo + u32 süzgeç kurar (sudo); sonda doğrular
#   --dry-run     hiçbir şey değiştirmez; yapacağı ip/tc komutlarını yazar
#   --verify      yalnız denetim (sudo gerekmez): adresler, tc yapısı, sayaçlar, iki kısa soket testi (a: sürü ağı sınırlı, b: 127.0.0.1 sınırsız)
#   --remove      bu betiğin eklediği her şeyi geri alır (htb kök, adresler; sudo)
# Yapılandırma: config/deney.env (DENEY_ENV ortam değişkeniyle başka dosya verilebilir). Sabit ek gecikme / kasıtlı paket kaybı YOK (netem kullanılmaz).
# Kalıcı değildir: yeniden başlatmada install_all.sh yeniden uygular.
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

# --remove betiğe özgü bayrak; ortak ayrıştırıcıya geçmeden ayır.
REMOVE=0
ARGS=()
for a in "$@"; do
    if [[ "$a" == "--remove" ]]; then REMOVE=1; else ARGS+=("$a"); fi
done
parse_common_args "${ARGS[@]+"${ARGS[@]}"}"
if [[ "$REMOVE" -eq 1 && "$MODE" == "verify" ]]; then
    echo "--remove ile --verify birlikte kullanılamaz" >&2
    exit 2
fi
COMPONENT_NAME="Ağ emülasyonu (tc)"
require_not_root

DENEY_ENV="${DENEY_ENV:-$ROOT_DIR/config/deney.env}"
DEV="lo"
ROOT_HANDLE="1:"
OPEN_CLASS="1:1"      # varsayılan sınıf: sınırlanmayan her şey (127.0.0.1 dahil)
LIMIT_CLASS="1:10"    # ortak kapasite sınırlayıcı
LEAF_HANDLE="10:"
OPEN_RATE="100gbit"   # "sınırsız" sayılacak yüksek hız
FILTER_PRIO=1

fail_stop() { log_fail "$1"; component_failed "$COMPONENT_NAME"; exit 1; }

# --- Yapılandırma ------------------------------------------------------------
ip_to_int() { # a.b.c.d -> tamsayı; geçersizse 1
    local a b c d
    [[ "$1" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
    a="${BASH_REMATCH[1]}"; b="${BASH_REMATCH[2]}"; c="${BASH_REMATCH[3]}"; d="${BASH_REMATCH[4]}"
    [[ "$a" -le 255 && "$b" -le 255 && "$c" -le 255 && "$d" -le 255 ]] || return 1
    echo $(( (a << 24) | (b << 16) | (c << 8) | d ))
}

# net_match_hex a.b.c.d/n : u32 'match' çıktısındaki gösterim (ör. 0a0a0000/ffffff00)
net_match_hex() {
    local ip="${1%/*}" len="${1#*/}" n mask
    n="$(ip_to_int "$ip")" || return 1
    mask=$(( len == 0 ? 0 : (0xFFFFFFFF << (32 - len)) & 0xFFFFFFFF ))
    printf '%08x/%08x\n' $(( n & mask )) "$mask"
}

ip_in_net() { # ip_in_net <ip> <cidr>
    local n net len mask nn
    n="$(ip_to_int "$1")" || return 1
    net="$(ip_to_int "${2%/*}")" || return 1
    len="${2#*/}"
    mask=$(( len == 0 ? 0 : (0xFFFFFFFF << (32 - len)) & 0xFFFFFFFF ))
    nn=$(( n & mask ))
    [[ "$nn" -eq $(( net & mask )) ]]
}

load_deney_config() {
    if [[ ! -f "$DENEY_ENV" ]]; then
        fail_stop "Yapılandırma dosyası bulunamadı: $DENEY_ENV"
    fi
    # shellcheck disable=SC1090
    source "$DENEY_ENV"
    local k
    for k in SWARM_NET UAV1_ADDR UAV2_ADDR UAV3_ADDR GCS_ADDR LINK_RATE_MBIT LINK_QUEUE_BYTES; do
        [[ -n "${!k:-}" ]] || fail_stop "Yapılandırmada '$k' tanımlı değil: $DENEY_ENV"
    done
    [[ "$LINK_RATE_MBIT" =~ ^[1-9][0-9]*$ ]] || fail_stop "LINK_RATE_MBIT pozitif tamsayı olmalı: '$LINK_RATE_MBIT'"
    [[ "$LINK_QUEUE_BYTES" =~ ^[1-9][0-9]*$ ]] || fail_stop "LINK_QUEUE_BYTES pozitif tamsayı olmalı: '$LINK_QUEUE_BYTES'"
    [[ "$SWARM_NET" =~ ^[0-9.]+/([0-9]|[12][0-9]|3[0-2])$ ]] && ip_to_int "${SWARM_NET%/*}" >/dev/null \
        || fail_stop "SWARM_NET geçerli bir a.b.c.d/n olmalı: '$SWARM_NET'"
    ADDRS=("$UAV1_ADDR" "$UAV2_ADDR" "$UAV3_ADDR" "$GCS_ADDR")
    local a
    for a in "${ADDRS[@]}"; do
        ip_in_net "$a" "$SWARM_NET" || fail_stop "Adres SWARM_NET ($SWARM_NET) içinde değil veya geçersiz: '$a'"
    done
    FILTER_MATCH="$(net_match_hex "$SWARM_NET")"
    LO_MTU="$(cat "/sys/class/net/$DEV/mtu" 2>/dev/null || true)"
    [[ "$LO_MTU" =~ ^[0-9]+$ ]] || fail_stop "$DEV arayüzünün MTU değeri okunamadı"
    # burst/cburst = 2 × MTU: htb, belirteç kovasının en az bir paket (lo'da 65536 B'a kadar GSO/"büyük" paket)
    # sığacak büyüklükte olmasını ister; kova tek pakete tam sığarsa paket sürekli bölünür/bekler ve hız
    # hedefin altına düşer. 2 × MTU, 25 Mbit/s'te ilk 2.5 sn'lik ölçümde ~%1,6'lık başlangıç taşması demektir (±%15 payın içinde).
    BURST="$(( 2 * LO_MTU ))"
}

# --- Durum okuma (sudo gerekmez) ---------------------------------------------
has_addr() { # çıktı önce değişkene alınır (grep -q + pipefail → SIGPIPE yanlış negatifi olmasın)
    local addrs
    addrs="$(ip -o -4 addr show dev "$DEV" 2>/dev/null | awk '{print $4}' || true)"
    grep -qx "$1/32" <<< "$addrs"
}

# Kök kuyruk disiplininin satırı (yoksa/noqueue ise boş)
root_qdisc_line() {
    # awk girdiyi sonuna kadar okur (erken exit yok): tc SIGPIPE almasın
    tc qdisc show dev "$DEV" 2>/dev/null | awk '!f && $1 == "qdisc" && / root / && $2 != "noqueue" { print; f = 1 }'
}
root_is_ours() { local l; l="$(root_qdisc_line)"; [[ -n "$l" ]] && [[ "$(awk '{print $2, $3}' <<< "$l")" == "htb $ROOT_HANDLE" ]]; }
root_is_empty() { [[ -z "$(root_qdisc_line)" ]]; }

# tc satırından 'anahtar değer' çifti: tc_field <satır> <anahtar>
tc_field() { awk -v k="$2" '{ for (i = 1; i < NF; i++) if ($i == k) { print $(i + 1); exit } }' <<< "$1"; }
# '25Mbit' -> bit/sn ; '128Kb' -> bayt (tc insan-okur gösterimleri)
tc_rate_bps() { awk -v s="$1" 'BEGIN { if (match(s, /^[0-9.]+/)) { n = substr(s, 1, RLENGTH); u = substr(s, RLENGTH + 1); m["bit"]=1; m["Kbit"]=1e3; m["Mbit"]=1e6; m["Gbit"]=1e9; m["Tbit"]=1e12; if (u in m) { printf "%.0f\n", n * m[u]; exit 0 } } exit 1 }'; }
tc_size_bytes() { awk -v s="$1" 'BEGIN { if (match(s, /^[0-9.]+/)) { n = substr(s, 1, RLENGTH); u = substr(s, RLENGTH + 1); m["b"]=1; m["Kb"]=1024; m["Mb"]=1048576; m["Gb"]=1073741824; if (u in m) { printf "%.0f\n", n * m[u]; exit 0 } } exit 1 }'; }

class_line() { tc class show dev "$DEV" 2>/dev/null | awk -v c="$1" '!f && $1 == "class" && $2 == "htb" && $3 == c { print; f = 1 }'; }
leaf_line() { tc qdisc show dev "$DEV" 2>/dev/null | awk -v p="$LIMIT_CLASS" '!f && $1 == "qdisc" && $2 == "bfifo" && $3 == "'"$LEAF_HANDLE"'" { print; f = 1 }'; }

# class_ok <sınıf> <hız_bit/sn> <alt_sınır_modu: eq|ge> : sınıf var, rate/ceil beklenene uyuyor
class_rate_ok() {
    local l want="$2" mode="$3" rate ceil
    l="$(class_line "$1")"; [[ -n "$l" ]] || return 1
    rate="$(tc_rate_bps "$(tc_field "$l" rate)")" || return 1
    ceil="$(tc_rate_bps "$(tc_field "$l" ceil)")" || return 1
    if [[ "$mode" == "eq" ]]; then
        # tc gösterimi yuvarlayabilir: %0,5 hoşgörü
        awk -v a="$rate" -v b="$ceil" -v w="$want" 'BEGIN { d = w * 0.005; exit !((a-w <= d && w-a <= d) && (b-w <= d && w-b <= d)) }'
    else
        [[ "$rate" -ge "$want" ]]
    fi
}
limit_class_ok() {
    local l b
    class_rate_ok "$LIMIT_CLASS" "$(( LINK_RATE_MBIT * 1000000 ))" eq || return 1
    l="$(class_line "$LIMIT_CLASS")"
    [[ "$(tc_field "$l" parent)" == "$OPEN_CLASS" ]] || return 1
    # burst htb tick yuvarlamasıyla az farklı gösterilebilir: yalnız "en az 1 MTU" aranır
    b="$(tc_size_bytes "$(tc_field "$l" burst)")" || return 1
    [[ "$b" -ge "$LO_MTU" ]]
}
open_class_ok() {
    local l
    class_rate_ok "$OPEN_CLASS" 10000000000 ge || return 1
    l="$(class_line "$OPEN_CLASS")"
    # kök kuyruğun doğrudan çocuğu olan sınıf, tc çıktısında "parent 1:" yerine "root" olarak gösterilir
    [[ "$(tc_field "$l" parent)" == "$ROOT_HANDLE" || "$l" == "class htb $OPEN_CLASS root "* ]]
}
leaf_ok() {
    local l lim
    l="$(leaf_line)"; [[ -n "$l" ]] || return 1
    [[ "$(tc_field "$l" parent)" == "$LIMIT_CLASS" ]] || return 1
    lim="$(tc_size_bytes "$(tc_field "$l" limit)")" || return 1
    [[ "$lim" -eq "$LINK_QUEUE_BYTES" ]]
}
filter_text() { tc filter show dev "$DEV" parent "$ROOT_HANDLE" 2>/dev/null || true; }
filter_any() { [[ -n "$(filter_text)" ]]; }
filter_ok() {
    local t; t="$(filter_text)"
    grep -q "flowid $LIMIT_CLASS" <<< "$t" && grep -q "match $FILTER_MATCH at 16" <<< "$t"
}
root_default_ok() { local l; l="$(root_qdisc_line)"; [[ "$(tc_field "$l" default)" == "0x1" ]]; }

# tc -s class show : sınıfın 'Sent N bytes' sayacı (okunamazsa boş + dönüş 1)
class_sent_bytes() {
    local v
    v="$(tc -s class show dev "$DEV" 2>/dev/null | awk -v c="$1" '
        $1 == "class" { cur = ($2 == "htb" && $3 == c) }
        !f && cur && $1 == "Sent" { print $2; f = 1 }')"
    [[ "$v" =~ ^[0-9]+$ ]] || return 1
    echo "$v"
}

# class_stats <sınıf> : "<Sent_bayt> <backlog>" (ör. "8229399 0b"); okunamazsa boş + dönüş 1.
# Gerçek tc -s çıktısı (iproute2 6.1):
#   class htb 1:10 parent 1:1 leaf 10: prio 0 rate 25Mbit ceil 25Mbit burst 128Kb cburst 128Kb
#    Sent 8229399 bytes 218 pkt (dropped 19, overlimits 141 requeues 0)
#    backlog 0b 0p requeues 0
class_stats() {
    local v
    v="$(tc -s class show dev "$DEV" 2>/dev/null | awk -v c="$1" '
        $1 == "class" { cur = ($2 == "htb" && $3 == c) }
        cur && $1 == "Sent" { sent = $2 }
        cur && $1 == "backlog" { bl = $2 }
        END { if (sent != "" && bl != "") print sent, bl }')"
    [[ "$v" =~ ^[0-9]+\ [0-9]+[A-Za-z]*$ ]] || return 1
    echo "$v"
}

# wait_limiter_idle : sınırlayıcı kuyruğu (1:10) boşalana kadar bekler. Boşalma = 'backlog 0b' VE 'Sent' sayacı
# arka arkaya iki okumada (100 ms arayla) değişmemiş. Bir önceki soket testinin bfifo'da bıraktığı veri
# 25 Mbit/s hızla (≈ 80 ms) boşalırken sayaç hâlâ artar; bekleme bu yarışı ortadan kaldırır.
# En çok 3 sn; zaman aşımında (!) yazıp döner (dönüş 0). Bekleme süresi WAIT_MS değişkenine (ms) yazılır.
WAIT_MS=0
wait_limiter_idle() {
    # EPOCHREALTIME ondalık ayracı yerel ayara bağlıdır (tr_TR: virgül); [.,] ikisini de sıyırır → mikrosaniye tamsayısı
    local t0 now prev="" cur sent bl
    t0="${EPOCHREALTIME/[.,]/}"; t0=$(( t0 / 1000 ))
    while :; do
        if ! cur="$(class_stats "$LIMIT_CLASS")"; then WAIT_MS=0; return 0; fi   # sınıf yok: sayaç denetimi zaten (-) verir
        sent="${cur% *}"; bl="${cur#* }"
        now="${EPOCHREALTIME/[.,]/}"; now=$(( now / 1000 ))
        WAIT_MS=$(( now - t0 ))
        if [[ "$bl" == "0b" && "$sent" == "$prev" ]]; then return 0; fi
        if [[ "$WAIT_MS" -ge 3000 ]]; then
            log_warn "Sınırlayıcı kuyruğu 3 sn içinde boşalmadı (backlog $bl); devam ediliyor"
            return 0
        fi
        prev="$sent"
        sleep 0.1
    done
}

# --- Soket testi (ortak kitaplığa taşınabilir: yalnız argümanlara dayanır) ----
# net_throughput_test <kaynak_adres> <hedef_adres> <saniye> : TCP verisi akıtır, alıcıda ölçer.
# Başarıda stdout: "<Mbit/s> <alınan_bayt>"; hata (bind/connect vb.) olursa 1 ve stderr'e neden.
net_throughput_test() {
    python3 -I - "$1" "$2" "$3" <<'PY'
import socket, sys, threading, time

src, dst, dur = sys.argv[1], sys.argv[2], float(sys.argv[3])
res = {}
stop = threading.Event()

try:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.settimeout(3)
    srv.bind((dst, 0))
    srv.listen(1)
    port = srv.getsockname()[1]
except OSError as e:
    print(f"alıcı {dst} adresine bağlanamadı: {e}", file=sys.stderr)
    sys.exit(1)

def serve():
    try:
        c, _ = srv.accept()
        c.settimeout(3)
        first = None
        total = 0
        while True:
            d = c.recv(262144)
            if not d:
                break
            now = time.monotonic()
            if first is None:
                first = now          # ilk parça ölçüme dahil edilmez (zaman başlangıcı)
            else:
                total += len(d)
            if first is not None and now - first >= dur:
                break
        res["total"] = total
        res["secs"] = (time.monotonic() - first) if first is not None else 0.0
        stop.set()               # gönderici, bağlantı kapanmadan önce durdurulur (RST yarışı olmasın)
        c.close()
    except OSError as e:
        res["err"] = f"alıcı: {e}"
    finally:
        stop.set()

def send():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.bind((src, 0))
        s.connect((dst, port))
        buf = b"\0" * 65536
        while not stop.is_set():
            s.send(buf)
        s.close()
    except OSError as e:
        if not stop.is_set() and "total" not in res:
            res.setdefault("err", f"gönderici ({src} -> {dst}): {e}")
            stop.set()

t_srv = threading.Thread(target=serve, daemon=True)
t_cli = threading.Thread(target=send, daemon=True)
t_srv.start(); t_cli.start()
t_srv.join(dur + 4)
stop.set()
t_cli.join(2)
if "err" in res or res.get("secs", 0) <= 0:
    print(res.get("err", "veri alınamadı"), file=sys.stderr)
    sys.exit(1)
print(f"{res['total'] * 8 / res['secs'] / 1e6:.2f} {res['total']}")
PY
}

# --- Kurulum / geri alma -----------------------------------------------------
install_component() {
    have_cmd ip || fail_stop "'ip' komutu bulunamadı (iproute2)"
    have_cmd tc || fail_stop "'tc' komutu bulunamadı (iproute2)"

    # Başkasına ait kök kuyruk disiplinini ezme.
    if ! root_is_empty && ! root_is_ours; then
        fail_stop "$DEV üzerinde bizim olmayan bir kök kuyruk disiplini kurulu: '$(root_qdisc_line)' — dokunulmadı"
    fi

    # 1) Adresler
    local a
    for a in "${ADDRS[@]}"; do
        if has_addr "$a"; then
            log_ok "Adres zaten var: $a/32 ($DEV)"
        else
            sudo_run "Adres ekleniyor: $a/32" ip addr add "$a/32" dev "$DEV"
        fi
    done

    # 2) htb kök (varsayılan sınıf 1:1)
    if root_is_empty; then
        sudo_run "htb kök kuyruk kuruluyor" tc qdisc add dev "$DEV" root handle "$ROOT_HANDLE" htb default 1
    elif root_default_ok; then
        log_ok "htb kök zaten kurulu ($ROOT_HANDLE, varsayılan sınıf 1)"
    else
        sudo_run "htb kökün varsayılan sınıfı düzeltiliyor" tc qdisc change dev "$DEV" root handle "$ROOT_HANDLE" htb default 1
    fi

    # 3) Sınıflar. 'quantum' açıkça verilir: aksi halde htb, hızdan türettiği quantum için çekirdek günlüğüne
    #    "quantum of class ... is big/small" uyarısı yazar.
    if open_class_ok; then
        log_ok "Sınıf $OPEN_CLASS (sınırsız) zaten kurulu"
    else
        sudo_run "Sınıf $OPEN_CLASS kuruluyor (sınırsız, $OPEN_RATE)" \
            tc class replace dev "$DEV" parent "$ROOT_HANDLE" classid "$OPEN_CLASS" htb rate "$OPEN_RATE" quantum "$LO_MTU"
    fi
    if limit_class_ok; then
        log_ok "Sınıf $LIMIT_CLASS (${LINK_RATE_MBIT}Mbit) zaten kurulu"
    else
        sudo_run "Sınıf $LIMIT_CLASS kuruluyor (rate=ceil=${LINK_RATE_MBIT}mbit, burst=cburst=$BURST)" \
            tc class replace dev "$DEV" parent "$OPEN_CLASS" classid "$LIMIT_CLASS" htb \
            rate "${LINK_RATE_MBIT}mbit" ceil "${LINK_RATE_MBIT}mbit" burst "$BURST" cburst "$BURST" quantum "$LO_MTU"
    fi

    # 4) Yaprak kuyruk (bayt sınırlı FIFO)
    if leaf_ok; then
        log_ok "Yaprak bfifo (limit $LINK_QUEUE_BYTES B) zaten kurulu"
    else
        sudo_run "Yaprak bfifo kuruluyor (limit $LINK_QUEUE_BYTES B)" \
            tc qdisc replace dev "$DEV" parent "$LIMIT_CLASS" handle "$LEAF_HANDLE" bfifo limit "$LINK_QUEUE_BYTES"
    fi

    # 5) Süzgeç: hedefi sürü ağı olan trafik -> 1:10
    if filter_ok; then
        log_ok "Süzgeç zaten kurulu (dst $SWARM_NET -> $LIMIT_CLASS)"
    else
        if filter_any; then
            sudo_run "Eski süzgeç siliniyor (yapı farklı)" tc filter del dev "$DEV" parent "$ROOT_HANDLE" prio "$FILTER_PRIO"
        fi
        sudo_run "Süzgeç ekleniyor (dst $SWARM_NET -> $LIMIT_CLASS)" \
            tc filter add dev "$DEV" parent "$ROOT_HANDLE" protocol ip prio "$FILTER_PRIO" u32 match ip dst "$SWARM_NET" flowid "$LIMIT_CLASS"
    fi
}

remove_component() {
    have_cmd ip || fail_stop "'ip' komutu bulunamadı (iproute2)"
    have_cmd tc || fail_stop "'tc' komutu bulunamadı (iproute2)"
    if root_is_ours; then
        sudo_run "htb kök kuyruk kaldırılıyor (sınıf, yaprak ve süzgeçle birlikte)" tc qdisc del dev "$DEV" root
    elif root_is_empty; then
        log_ok "Kaldırılacak kök kuyruk yok"
    else
        log_warn "$DEV üzerindeki kök kuyruk bizim değil, dokunulmadı: '$(root_qdisc_line)'"
    fi
    local a
    for a in "${ADDRS[@]}"; do
        if has_addr "$a"; then
            sudo_run "Adres kaldırılıyor: $a/32" ip addr del "$a/32" dev "$DEV"
        else
            log_ok "Adres zaten yok: $a/32"
        fi
    done
}

# --- Doğrulama ---------------------------------------------------------------
verify_removed() {
    local a
    for a in "${ADDRS[@]}"; do
        if has_addr "$a"; then log_fail "Adres hâlâ var: $a/32"; else log_ok "Adres yok: $a/32"; fi
    done
    if root_is_ours; then log_fail "htb kök hâlâ kurulu"; else log_ok "htb kök kurulu değil"; fi
}

verify_component() {
    local a
    have_cmd ip && have_cmd tc || { log_fail "'ip'/'tc' bulunamadı (iproute2)"; return 0; }

    for a in "${ADDRS[@]}"; do
        if has_addr "$a"; then log_ok "Adres var: $a/32 ($DEV)"; else log_fail "Adres yok: $a/32 ($DEV) — betik uygulanmamış"; fi
    done
    if root_is_ours; then
        log_ok "Kök kuyruk: htb $ROOT_HANDLE"
        if root_default_ok; then log_ok "Varsayılan sınıf 1 ($OPEN_CLASS)"; else log_fail "htb varsayılan sınıfı 1 değil"; fi
    else
        log_fail "Kök kuyruk htb $ROOT_HANDLE değil: '$(root_qdisc_line || true)' (boşsa: yok/noqueue; uygulanmamış?)"
    fi
    if open_class_ok; then log_ok "Sınıf $OPEN_CLASS yüksek hızlı (≥10 Gbit)"; else log_fail "Sınıf $OPEN_CLASS yok veya yüksek hızlı değil"; fi
    if limit_class_ok; then
        log_ok "Sınıf $LIMIT_CLASS: rate=ceil=${LINK_RATE_MBIT}Mbit, burst ≥ MTU ($LO_MTU)"
    else
        log_fail "Sınıf $LIMIT_CLASS beklenen yapıda değil (rate=ceil=${LINK_RATE_MBIT}Mbit, parent $OPEN_CLASS, burst ≥ $LO_MTU)"
    fi
    if leaf_ok; then log_ok "Yaprak bfifo, limit $LINK_QUEUE_BYTES B"; else log_fail "Yaprak bfifo yok veya limit $LINK_QUEUE_BYTES B değil"; fi
    if filter_ok; then log_ok "Süzgeç: dst $SWARM_NET ($FILTER_MATCH) -> $LIMIT_CLASS"; else log_fail "Süzgeç yok veya hedefi yanlış (beklenen: $FILTER_MATCH -> $LIMIT_CLASS)"; fi
    local qd_all
    qd_all="$(tc qdisc show dev "$DEV" 2>/dev/null || true)"   # önce değişkene: grep -q + pipefail → SIGPIPE
    if grep -q netem <<< "$qd_all"; then
        log_fail "netem bulundu: sabit gecikme/kayıp bulunmamalı"
    else
        log_ok "netem yok (ek gecikme/kasıtlı kayıp yok)"
    fi

    # Sayaçlar okunabiliyor mu
    local c0 c1 c2 out mbit bytes
    if c0="$(class_sent_bytes "$LIMIT_CLASS")"; then
        log_ok "Sayaç okunuyor: tc -s class show dev $DEV → sınıf $LIMIT_CLASS Sent $c0 bayt"
    else
        log_fail "Sayaç okunamadı: sınıf $LIMIT_CLASS 'Sent … bytes' yok"
        c0=""
    fi

    # (a) Sürü ağı: ~LINK_RATE_MBIT, sayaç artar
    local secs=2.5 wait_a wait_b
    wait_limiter_idle; wait_a="$WAIT_MS"
    c0="$(class_sent_bytes "$LIMIT_CLASS" || true)"
    if out="$(net_throughput_test "$UAV1_ADDR" "$UAV2_ADDR" "$secs" 2>&1)"; then
        mbit="${out%% *}"; bytes="${out##* }"
        c1="$(class_sent_bytes "$LIMIT_CLASS" || true)"
        if awk -v m="$mbit" -v r="$LINK_RATE_MBIT" 'BEGIN { exit !(m >= r * 0.85 && m <= r * 1.15) }'; then
            log_ok "(a) $UAV1_ADDR → $UAV2_ADDR: ${mbit} Mbit/s (hedef ${LINK_RATE_MBIT} ±%15), alınan $bytes bayt"
        else
            log_fail "(a) $UAV1_ADDR → $UAV2_ADDR: ${mbit} Mbit/s, hedef ${LINK_RATE_MBIT} ±%15 dışında"
        fi
        if [[ -n "$c0" && -n "$c1" && "$c1" -gt "$c0" ]]; then
            log_ok "(a) $LIMIT_CLASS sayacı arttı: $c0 → $c1 (+$(( c1 - c0 )) bayt; kuyruk bekleme ${wait_a} ms)"
        else
            log_fail "(a) $LIMIT_CLASS sayacı artmadı veya okunamadı (önce: '${c0:-yok}', sonra: '${c1:-yok}')"
        fi
    else
        log_fail "(a) $UAV1_ADDR → $UAV2_ADDR soket testi çalışmadı: $out"
    fi

    # (b) 127.0.0.1: sınırsız (hedefin ≥4 katı), sayaç tam 0 değişir. (a)'nın bıraktığı kuyruk önce boşalmalı.
    wait_limiter_idle; wait_b="$WAIT_MS"
    c1="$(class_sent_bytes "$LIMIT_CLASS" || true)"
    if out="$(net_throughput_test 127.0.0.1 127.0.0.1 "$secs" 2>&1)"; then
        mbit="${out%% *}"; bytes="${out##* }"
        c2="$(class_sent_bytes "$LIMIT_CLASS" || true)"
        if awk -v m="$mbit" -v r="$LINK_RATE_MBIT" 'BEGIN { exit !(m >= r * 4) }'; then
            log_ok "(b) 127.0.0.1 → 127.0.0.1: ${mbit} Mbit/s (sınırlanmıyor; ≥ 4 × ${LINK_RATE_MBIT}), alınan $bytes bayt"
        else
            log_fail "(b) 127.0.0.1 → 127.0.0.1: ${mbit} Mbit/s; sınırlandığı düşünülüyor (beklenen ≥ 4 × ${LINK_RATE_MBIT})"
        fi
        if [[ -n "$c1" && -n "$c2" && "$c2" -eq "$c1" ]]; then
            log_ok "(b) $LIMIT_CLASS sayacı değişmedi (fark 0; $c1 bayt; kuyruk bekleme ${wait_b} ms)"
        elif [[ -n "$c1" && -n "$c2" ]]; then
            log_fail "(b) $LIMIT_CLASS sayacı değişti: fark $(( c2 - c1 )) bayt (önce: $c1, sonra: $c2; kuyruk bekleme ${wait_b} ms)"
        else
            log_fail "(b) $LIMIT_CLASS sayacı okunamadı (önce: '${c1:-yok}', sonra: '${c2:-yok}')"
        fi
    else
        log_fail "(b) 127.0.0.1 soket testi çalışmadı: $out"
    fi
}

load_deney_config
if [[ "$REMOVE" -eq 1 ]]; then
    remove_component
    if [[ "$DRY_RUN" -eq 0 ]]; then verify_removed; fi
    component_finish "$COMPONENT_NAME" "$([[ "$DRY_RUN" -eq 1 ]] && echo 'dry-run tamamlandı (hiçbir şey değiştirilmedi)' || echo 'geri alındı')"
fi
if [[ "$MODE" == "install" ]]; then
    install_component
fi
if [[ "$MODE" == "verify" || "$DRY_RUN" -eq 0 ]]; then
    verify_component
fi
component_finish "$COMPONENT_NAME"
