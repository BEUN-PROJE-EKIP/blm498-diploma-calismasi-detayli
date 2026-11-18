#!/usr/bin/env python3
"""Ölçülen sürü ağının (lo üzerindeki htb 1:10 + bfifo yaprağı) tc sayaçlarını periyodik OKUR (YALNIZ okuma: `tc -s class show` ve `tc -s -j qdisc show`; sudo gerekmez, hiçbir ayar değişmez).

Kullanım:  python araclar/olcum/tc_izle.py --cikti <jsonl> [--aralik-sn 1] [--dev lo]      (SIGTERM/SIGINT ile durur)
Her örnekte bir JSON satırı: {"mono_ns", "sinif": {bayt, paket, dusen, overlimits, backlog_bayt, backlog_paket}, "yaprak": {aynı alanlar; bfifo yaprağı: gerçek kuyruk}, "kok_overlimits"}.
Sayaçlar kümülatiftir; analiz farkları alır. Kullanım oranı = Δbayt·8 / Δt (örnekler arası)."""
import json
import os
import re
import signal
import subprocess
import sys
import time

_SAYI = re.compile(r"^\s*Sent (\d+) bytes (\d+) pkt \(dropped (\d+), overlimits (\d+) requeues (\d+)\)")
_BACKLOG = re.compile(r"^\s*backlog (\d+(?:\.\d+)?)([KMG]?)b (\d+)p")
_BIRIM = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}


def sinif_ayristir(metin, kimlik="1:10"):
    """`tc -s class show` metninden htb sınıfının sayaçları. Sınıf yoksa None."""
    satirlar = metin.splitlines()
    for i, s in enumerate(satirlar):
        parca = s.split()
        if len(parca) >= 3 and parca[0] == "class" and parca[1] == "htb" and parca[2] == kimlik:
            return _sayac_oku(satirlar[i + 1:i + 4])
    return None


def _sayac_oku(satirlar):
    d = {}
    for s in satirlar:
        m = _SAYI.match(s)
        if m:
            d.update(bayt=int(m.group(1)), paket=int(m.group(2)), dusen=int(m.group(3)), overlimits=int(m.group(4)))
        m = _BACKLOG.match(s)
        if m:
            d.update(backlog_bayt=int(float(m.group(1)) * _BIRIM[m.group(2)]), backlog_paket=int(m.group(3)))
    return d if "bayt" in d and "backlog_bayt" in d else None


def qdisc_ayristir(json_metni):
    """`tc -s -j qdisc show` JSON'undan: (bfifo yaprağı sayaçları, htb kökü overlimits)."""
    yaprak, kok = None, None
    for q in json.loads(json_metni):
        if q.get("kind") == "bfifo":
            yaprak = {"bayt": q["bytes"], "paket": q["packets"], "dusen": q["drops"], "overlimits": q["overlimits"], "backlog_bayt": q["backlog"], "backlog_paket": q["qlen"]}
        elif q.get("kind") == "htb":
            kok = q.get("overlimits")
    return yaprak, kok


def oku(dev="lo"):
    c = subprocess.run(["tc", "-s", "class", "show", "dev", dev], capture_output=True, text=True, check=True).stdout
    q = subprocess.run(["tc", "-s", "-j", "qdisc", "show", "dev", dev], capture_output=True, text=True, check=True).stdout
    yaprak, kok = qdisc_ayristir(q)
    return {"mono_ns": time.monotonic_ns(), "sinif": sinif_ayristir(c), "yaprak": yaprak, "kok_overlimits": kok}


def ana(argv):
    cikti, aralik, dev = None, 1.0, "lo"
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--cikti" and a:
            cikti = a.pop(0)
        elif k == "--aralik-sn" and a:
            aralik = float(a.pop(0))
        elif k == "--dev" and a:
            dev = a.pop(0)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if not cikti:
        print(__doc__, file=sys.stderr)
        return 2
    dur = []
    signal.signal(signal.SIGTERM, lambda *_: dur.append(1))
    signal.signal(signal.SIGINT, lambda *_: dur.append(1))
    with open(cikti, "a", encoding="utf-8") as f:
        while not dur:
            f.write(json.dumps(oku(dev)) + "\n")
            f.flush()
            sinir = time.monotonic() + aralik
            while not dur and time.monotonic() < sinir:
                time.sleep(0.05)
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
