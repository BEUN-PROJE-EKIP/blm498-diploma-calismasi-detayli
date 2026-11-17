#!/usr/bin/env python3
"""DENEME: çalışan Gazebo'dan zemin (ground_plane) dışındaki bütün modelleri kaldırır (GZ_PARTITION ortamdan)."""
import subprocess, time
r = subprocess.run(["gz", "model", "--list"], capture_output=True, text=True, timeout=60)
adlar = [s.strip().lstrip("- ").strip() for s in r.stdout.splitlines() if s.strip().startswith("-")]
adlar = [a for a in adlar if a and a != "ground_plane"]
for a in adlar:
    subprocess.run(["gz", "service", "-s", "/world/default/remove", "--reqtype", "gz.msgs.Entity", "--reptype", "gz.msgs.Boolean",
                    "--timeout", "10000", "--req", f'name: "{a}", type: MODEL'], capture_output=True, timeout=60)
print(f"(+) {len(adlar)} model kaldırıldı")
