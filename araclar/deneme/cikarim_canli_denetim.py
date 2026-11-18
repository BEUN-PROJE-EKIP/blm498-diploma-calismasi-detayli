#!/usr/bin/env python3
"""Çalışan araç süreci için canlı denetim (YALNIZ test yardımcısı): araç sürecinin ve çocuğu olan çıkarım işçisinin soketlerini ve CPU kümesini örnekler.

Kullanım:  python araclar/deneme/cikarim_canli_denetim.py <araç_pid> <çıktı.json> [--aralik-sn 2]
Araç süreci yaşadığı sürece her aralıkta: (1) araç sürecinin inet soketleri (yerel adres:port, protokol, durum; /proc/<pid>/fd + /proc/net/{tcp,udp,tcp6,udp6}) — gz-transport'un 127.0.0.1'de
kaldığını göstermek için; (2) araç sürecinin çocuklarından komut satırında `swarm_vehicle.cikarim.cikarim_isci` geçenler (işçi): pid, `sched_getaffinity` CPU kümesi (taskset -p ile aynı), soket türleri
(unix/tcp/udp...). Gözlemlerin birleşimi çıktı dosyasına her turda yazılır (süreç ani ölse bile dosya vardır). Yalnız standart kitaplık; hiçbir süreç değiştirilmez.
"""
import json
import os
import re
import sys
import time


def inode_kumesi(pid):
    s = set()
    try:
        for ad in os.listdir(f"/proc/{pid}/fd"):
            try:
                m = re.fullmatch(r"socket:\[(\d+)\]", os.readlink(f"/proc/{pid}/fd/{ad}"))
            except OSError:
                continue
            if m:
                s.add(m.group(1))
    except OSError:
        pass
    return s


def hex_adres(h, v6):
    ip, port = h.split(":")
    if v6:
        b = bytes.fromhex(ip)
        b = b"".join(b[i:i + 4][::-1] for i in range(0, 16, 4))
        import ipaddress
        return str(ipaddress.IPv6Address(b)), int(port, 16)
    return ".".join(str(int(ip[i:i + 2], 16)) for i in (6, 4, 2, 0)), int(port, 16)


DURUMLAR = {"0A": "LISTEN", "01": "ESTAB", "06": "TIME_WAIT", "07": "CLOSE", "02": "SYN_SENT", "08": "CLOSE_WAIT"}


def inet_soketler(pid):
    inode = inode_kumesi(pid)
    sonuc = []
    for tur in ("tcp", "udp", "tcp6", "udp6"):
        try:
            with open(f"/proc/net/{tur}", encoding="utf-8") as f:
                satirlar = f.read().splitlines()[1:]
        except OSError:
            continue
        for s in satirlar:
            p = s.split()
            if p[9] in inode:
                ip, port = hex_adres(p[1], tur.endswith("6"))
                sonuc.append({"tur": tur, "yerel": f"{ip}:{port}", "durum": DURUMLAR.get(p[3], p[3])})
    return sonuc, inode


def soket_turleri(pid):
    inode = inode_kumesi(pid)
    turler = {}
    for tur in ("unix", "tcp", "udp", "tcp6", "udp6", "raw", "raw6", "packet", "netlink"):
        try:
            with open(f"/proc/net/{tur}", encoding="utf-8") as f:
                satirlar = f.read().splitlines()[1:]
        except OSError:
            continue
        for s in satirlar:
            p = s.split()
            ino = p[6] if tur == "unix" else (p[9] if len(p) > 9 else None)
            if ino in inode:
                turler[tur] = turler.get(tur, 0) + 1
    return turler


def cocuklar(pid):
    sonuc = []
    for ad in os.listdir("/proc"):
        if not ad.isdigit():
            continue
        try:
            with open(f"/proc/{ad}/stat", encoding="utf-8") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            if ppid != pid:
                continue
            with open(f"/proc/{ad}/cmdline", encoding="utf-8") as f:
                komut = f.read().replace("\0", " ")
        except (OSError, ValueError, IndexError):
            continue
        sonuc.append((int(ad), komut))
    return sonuc


def ana(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    pid, cikti = int(argv[0]), argv[1]
    aralik = float(argv[3]) if len(argv) > 3 and argv[2] == "--aralik-sn" else 2.0
    gozlem = {"arac_pid": pid, "arac_inet": {}, "isciler": {}, "tur_sayisi": 0}
    while os.path.exists(f"/proc/{pid}"):
        soketler, _ = inet_soketler(pid)
        for s in soketler:
            gozlem["arac_inet"][f"{s['tur']} {s['yerel']} {s['durum']}"] = True
        for cp, komut in cocuklar(pid):
            if "swarm_vehicle.cikarim.cikarim_isci" not in komut:
                continue
            try:
                cpu = sorted(os.sched_getaffinity(cp))
            except OSError:
                continue
            gozlem["isciler"][str(cp)] = {"pid": cp, "cpu": cpu, "soket_turleri": soket_turleri(cp), "komut": komut.strip()}
        gozlem["tur_sayisi"] += 1
        with open(cikti + ".gecici", "w", encoding="utf-8") as f:
            json.dump(gozlem, f, ensure_ascii=False, indent=1)
        os.replace(cikti + ".gecici", cikti)
        time.sleep(aralik)
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
