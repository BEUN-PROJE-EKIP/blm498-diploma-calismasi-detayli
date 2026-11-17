#!/usr/bin/env python3
"""DENEME: çalışan Gazebo'ya (GZ_PARTITION) şehir parçalarını sırayla ekler; izleyen görsel pencerede belirir.
Kullanım: canli_kur.py <sahne_klasoru> [grup ...]   gruplar: yollar binalar moloz arabalar hedefler (varsayılan hepsi)"""
import json
import os
import subprocess
import sys
import time

klasor = sys.argv[1]
gruplar = sys.argv[2:] or [g for g in ("yollar", "yuzeyler", "binalar", "moloz", "arabalar", "hedefler") if g in json.load(open(os.path.join(klasor, "sira.json")))]
sira = json.load(open(os.path.join(klasor, "sira.json")))
ara = {"yollar": 0.0, "yuzeyler": 1.0, "binalar": 0.8, "moloz": 0.02, "arabalar": 0.03, "hedefler": 0.3}
for g in gruplar:
    t0 = time.monotonic()
    for ad in sira[g]:
        r = subprocess.run(["gz", "service", "-s", "/world/default/create", "--reqtype", "gz.msgs.EntityFactory", "--reptype",
                            "gz.msgs.Boolean", "--timeout", "20000", "--req",
                            f'sdf_filename: "{os.path.join(klasor, "parcalar", ad + ".sdf")}"'], capture_output=True, text=True, timeout=60)
        if "true" not in r.stdout:
            print(f"(!) eklenemedi: {ad} {r.stdout.strip()} {r.stderr.strip()[:120]}", flush=True)
        time.sleep(ara[g])
    print(f"(+) {g}: {len(sira[g])} öğe eklendi ({time.monotonic() - t0:.0f} sn)", flush=True)
