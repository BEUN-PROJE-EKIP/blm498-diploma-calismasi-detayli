#!/usr/bin/env python3
"""Sentetik yük üretici (YALNIZ test aracı; merkezi modun AĞ YÜKÜNÜ taklit eder, B12 değildir): üç araç için araç başına bir TCP bağlantısı, kaynak adresi `UAVn_ADDR` (bind), hedef `GCS_ADDR` üzerinde
aynı süreçteki alıcı (veriyi okuyup atar). Gönderim, merkezi modun uygulama davranışını taklit eder: araç başına `CAM_RATE_HZ` (2 Hz) hızla `CAM_WIDTH × CAM_HEIGHT × 3` (= 921 600) baytlık "kare" (+ 20 bayt başlık)
uygulama kuyruğuna girer; kuyruk ATILMADAN, sırayla TCP'ye yazılır (geri basınç: soket dolunca gönderici bekler, uygulama kuyruğu büyür). Bütün trafik 10.10.0.x adresleri arasındadır (ölçülen hattan, lo üzerindeki htb'den geçer).

Kullanım:  python araclar/sentetik_yuk.py --cikti <jsonl> [--arac N] [--bosalt-sn S]
  SIGTERM/SIGINT: yeni kare üretimi durur, kuyruk (en çok --bosalt-sn, öntanımlı 600 sn) boşalana dek gönderim sürer; sonra çıkar. Çıkış 0.
  stdout: `SENTETIK hazir` (bütün bağlantılar kuruldu), kapanışta `SENTETIK kapandi ...`.
Kayıt (`--cikti`, JSON Lines, serbest biçim, şema değildir): {"k":"kare","a":araç,"seq","enq_ns","gonderim_bitis_ns","alim_bitis_ns"} (CLOCK_MONOTONIC), {"k":"kuyruk","a","mono_ns","derinlik","gonderilen_bayt"} (0,5 sn'de bir) ve
{"k":"ozet",...}. Yapılandırma: config/deney.env (CAM_*, UAVn_ADDR, GCS_ADDR, SENTETIK_YUK_PORT_TABAN). Yalnız standart kitaplık."""
import collections
import json
import os
import signal
import socket
import struct
import sys
import threading
import time

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

BASLIK = struct.Struct("!QIQ")        # seq, yük boyu, kuyruğa giriş anı (mono ns)


class KareKuyrugu:
    """Uygulama kuyruğu: kare ATILMAZ, sıra korunur; derinlik sorgulanır. İş parçacığı güvenlidir."""

    def __init__(self):
        self._q = collections.deque()
        self._k = threading.Condition()
        self.giren = 0

    def koy(self, seq, enq_ns):
        with self._k:
            self._q.append((seq, enq_ns))
            self.giren += 1
            self._k.notify()

    def al(self, bekle_sn=0.2):
        with self._k:
            if not self._q:
                self._k.wait(bekle_sn)
            return self._q.popleft() if self._q else None

    def derinlik(self):
        with self._k:
            return len(self._q)


class AracYuku:
    """Bir aracın gönderici + alıcı çifti."""

    def __init__(self, arac, kaynak, hedef_ip, port, kare_bayt, hz, kayit):
        self.arac, self.kaynak, self.hedef_ip, self.port, self.kare_bayt, self.hz, self.kayit = arac, kaynak, hedef_ip, port, kare_bayt, hz, kayit
        self.kuyruk = KareKuyrugu()
        self.yuk = b"\x00" * kare_bayt                  # bütün karelerde ortak (bellek tasarrufu); TCP'de sıkıştırma yoktur
        self.gonderilen_bayt = self.alinan_bayt = 0
        self.gonderilen_kare = self.alinan_kare = 0
        self.dur_uret = threading.Event()               # yeni kare üretimi durdu
        self.bitti_gonder = threading.Event()
        self._dinle = socket.socket()
        self._dinle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._dinle.bind((hedef_ip, port))
        self._dinle.listen(1)
        self._giris = {}                                 # seq → (enq_ns, gonderim_bitis_ns, alim_bitis_ns)
        self._kilit = threading.Lock()
        self.hazir = threading.Event()
        self.hata = None
        self._is = []

    # --- alıcı ------------------------------------------------------------------------------------------------------------------------
    def _alici(self):
        try:
            c, _ = self._dinle.accept()
            f = c.makefile("rb", buffering=1 << 20)
            while True:
                h = f.read(BASLIK.size)
                if len(h) < BASLIK.size:
                    break
                seq, boy, enq = BASLIK.unpack(h)
                veri = f.read(boy)
                if len(veri) < boy:
                    break
                t = time.monotonic_ns()
                self.alinan_bayt += BASLIK.size + boy
                self.alinan_kare += 1
                with self._kilit:
                    g = self._giris.get(seq, [enq, None, None])
                    g[2] = t
                    self._giris[seq] = g
            c.close()
        except OSError as e:
            self.hata = f"alıcı: {e!r}"

    # --- gönderici ---------------------------------------------------------------------------------------------------------------------
    def _uretici(self):
        sinir, seq, periyot = time.monotonic(), 0, 1.0 / self.hz
        while not self.dur_uret.is_set():
            self.kuyruk.koy(seq, time.monotonic_ns())
            seq += 1
            sinir += periyot
            while not self.dur_uret.is_set() and time.monotonic() < sinir:
                time.sleep(min(0.02, max(0.0, sinir - time.monotonic())))

    def _gonderici(self, s):
        try:
            while True:
                o = self.kuyruk.al()
                if o is None:
                    if self.dur_uret.is_set():
                        break
                    continue
                seq, enq = o
                s.sendall(BASLIK.pack(seq, self.kare_bayt, enq))
                s.sendall(self.yuk)
                t = time.monotonic_ns()
                self.gonderilen_bayt += BASLIK.size + self.kare_bayt
                self.gonderilen_kare += 1
                with self._kilit:
                    g = self._giris.get(seq, [enq, None, None])
                    g[1] = t
                    self._giris[seq] = g
        except OSError as e:
            self.hata = f"gönderici: {e!r}"
        finally:
            self.bitti_gonder.set()

    def baslat(self):
        t_al = threading.Thread(target=self._alici, daemon=True)
        t_al.start()
        s = socket.socket()
        s.bind((self.kaynak, 0))
        s.connect((self.hedef_ip, self.port))
        self._soket = s
        self.hazir.set()
        for hedef, arg in ((self._uretici, ()), (self._gonderici, (s,))):
            t = threading.Thread(target=hedef, args=arg, daemon=True)
            t.start()
            self._is.append(t)
        self._is.append(t_al)

    def kapat(self):
        for t in self._is:
            t.join(5)
        try:
            self._soket.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        self._is[-1].join(10)            # alıcı: kalan baytları okuyup bitirir
        self._soket.close()
        self._dinle.close()

    def kare_kayitlari(self):
        with self._kilit:
            return [{"k": "kare", "a": self.arac, "seq": s, "enq_ns": g[0], "gonderim_bitis_ns": g[1], "alim_bitis_ns": g[2]} for s, g in sorted(self._giris.items())]


def ana(argv):
    cikti, n_arac, bosalt = None, None, 600.0
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--cikti" and a:
            cikti = a.pop(0)
        elif k == "--arac" and a:
            n_arac = int(a.pop(0))
        elif k == "--bosalt-sn" and a:
            bosalt = float(a.pop(0))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if not cikti:
        print(__doc__, file=sys.stderr)
        return 2
    from swarm_vehicle import rota
    ham = rota.deney_env_oku()
    n_arac = n_arac or len(ham["UAV_SYS_IDS"].split())
    kare_bayt = int(ham["CAM_WIDTH"]) * int(ham["CAM_HEIGHT"]) * 3
    hz = float(ham["CAM_RATE_HZ"])
    taban = int(ham["SENTETIK_YUK_PORT_TABAN"])
    kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()][:n_arac]
    yukler = [AracYuku(k, ham[f"UAV{i + 1}_ADDR"], ham["GCS_ADDR"], taban + i, kare_bayt, hz, cikti) for i, k in enumerate(kimlikler)]
    dur = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: dur.set())
    signal.signal(signal.SIGINT, lambda *_: dur.set())
    for y in yukler:
        y.baslat()
    t_basla = time.monotonic_ns()
    print(f"SENTETIK hazir arac={n_arac} kare_bayt={kare_bayt} hz={hz:g} yuk_mbit_s={n_arac * (kare_bayt + BASLIK.size) * hz * 8 / 1e6:.2f}", flush=True)
    kuyruk_satirlari = []
    while not dur.is_set():
        t = time.monotonic_ns()
        for y in yukler:
            kuyruk_satirlari.append({"k": "kuyruk", "a": y.arac, "mono_ns": t, "derinlik": y.kuyruk.derinlik(), "gonderilen_bayt": y.gonderilen_bayt})
        dur.wait(0.5)
    t_dur = time.monotonic_ns()
    for y in yukler:
        y.dur_uret.set()
    sinir = time.monotonic() + bosalt
    while time.monotonic() < sinir and not all(y.bitti_gonder.is_set() for y in yukler):
        t = time.monotonic_ns()
        for y in yukler:
            kuyruk_satirlari.append({"k": "kuyruk", "a": y.arac, "mono_ns": t, "derinlik": y.kuyruk.derinlik(), "gonderilen_bayt": y.gonderilen_bayt})
        time.sleep(0.5)
    t_bosal = time.monotonic_ns()
    tamam = all(y.bitti_gonder.is_set() for y in yukler)
    if tamam:
        for y in yukler:
            y.kapat()
    ozet = []
    with open(cikti, "w", encoding="utf-8") as f:
        for y in yukler:
            for r in y.kare_kayitlari():
                f.write(json.dumps(r) + "\n")
        for r in kuyruk_satirlari:
            f.write(json.dumps(r) + "\n")
        for y in yukler:
            o = {"k": "ozet", "a": y.arac, "uretilen_kare": y.kuyruk.giren, "gonderilen_kare": y.gonderilen_kare, "alinan_kare": y.alinan_kare, "gonderilen_bayt": y.gonderilen_bayt,
                 "alinan_bayt": y.alinan_bayt, "kuyrukta_kalan": y.kuyruk.derinlik(), "hata": y.hata, "baslangic_ns": t_basla, "durdurma_ns": t_dur, "bosalma_ns": t_bosal, "bosaldi": tamam}
            ozet.append(o)
            f.write(json.dumps(o) + "\n")
    print("SENTETIK kapandi " + " ".join(f"a{o['a']}:uretilen={o['uretilen_kare']},gonderilen={o['gonderilen_kare']},alinan={o['alinan_kare']},kalan={o['kuyrukta_kalan']}" for o in ozet)
          + f" bosalma_sn={(t_bosal - t_dur) / 1e9:.1f} bosaldi={tamam}", flush=True)
    return 0


if __name__ == "__main__":
    kod = ana(sys.argv[1:])
    sys.stdout.flush()
    os._exit(kod)
