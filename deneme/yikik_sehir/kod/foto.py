#!/usr/bin/env python3
"""DENEME: çalışan bir Gazebo bölümüne kamera ekleyip fotoğraf çeker.
Kullanım: foto.py <cikti_klasoru> <ad>:<x>:<y>:<z>:<pitch>:<yaw>:<hfov>:<gen>:<yuk> [...]   (GZ_PARTITION, GZ_IP ortamdan)"""
import os
import subprocess
import sys
import time

import numpy as np
from gz.msgs10.image_pb2 import Image
from gz.transport13 import Node
from PIL import Image as PImage

cikti = sys.argv[1]
os.makedirs(cikti, exist_ok=True)
kameralar = []
for a in sys.argv[2:]:
    ad, *s = a.split(":")
    kameralar.append((ad, *[float(v) for v in s]))
node = Node()
kareler = {}
for ad, x, y, z, p, yw, fov, w, h in kameralar:
    konu = f"foto/{ad}"
    sdf = os.path.join(cikti, f"k_{ad}.sdf")
    with open(sdf, "w") as f:
        f.write(f'<?xml version="1.0"?><sdf version="1.9"><model name="foto_{ad}_{os.getpid()}"><static>true</static>'
                f'<pose>{x} {y} {z} 0 {p} {yw}</pose><link name="l"><sensor name="c" type="camera"><always_on>1</always_on>'
                f'<update_rate>2</update_rate><topic>{konu}</topic><camera><horizontal_fov>{fov}</horizontal_fov><image><width>{int(w)}</width>'
                f'<height>{int(h)}</height><format>R8G8B8</format></image><clip><near>0.1</near><far>1500</far></clip></camera></sensor>'
                f'</link></model></sdf>')
    subprocess.run(["gz", "service", "-s", "/world/default/create", "--reqtype", "gz.msgs.EntityFactory", "--reptype", "gz.msgs.Boolean",
                    "--timeout", "20000", "--req", f'sdf_filename: "{sdf}"'], capture_output=True, timeout=60)
    node.subscribe(Image, konu, lambda m, ad=ad: kareler.setdefault(ad, []).append(m))
t0 = time.monotonic()
while time.monotonic() - t0 < 180 and any(len(kareler.get(k[0], [])) < 3 for k in kameralar):
    time.sleep(0.5)
for ad, *_ in kameralar:
    if len(kareler.get(ad, [])) < 3:
        print("kare gelmedi:", ad)
        continue
    m = kareler[ad][2]
    PImage.fromarray(np.frombuffer(m.data, np.uint8).reshape(m.height, m.width, 3)).save(os.path.join(cikti, ad + ".png"))
    print("kaydedildi:", ad)
