#!/usr/bin/env python3
"""Araç kamerası üretim aracı: kalibrasyon dosyası ve Gazebo araç modeli (hepsi config/deney.env değerlerinden; sabit sayı yok).

Kullanım:
  kamera_uret.py kalibrasyon [--check] [--cikti <yol>]   config/kamera_kalibrasyon.json'u (sozlesmeler.md §4) yazar; --check güncel değilse çıkış 1
  kamera_uret.py model <klasör>                          <klasör>/<SIM_MODEL öneksiz>/model.sdf yazar: PX4'ün x500 modeli + gövdeye sabit, aşağı bakan kamera
Model: x500 (PX4 modelleri, `<include>`), KAL_KAMERA_KONUM_Z_M yüksekliğinde, pitch +90° ile aşağı bakan kamera bağlantısı (KAMERA_LINK) ve algılayıcısı
(KAMERA_ALGILAYICI): CAM_WIDTH × CAM_HEIGHT, R8G8B8 (sıkıştırmasız), CAM_RATE_HZ (simülasyon zamanında), yatay görüş açısı CAM_HFOV_RAD (kilitli 65°).
Görüntüde yukarı = aracın ileri (+x gövde) yönü, sağ = gövdenin sağı (sozlesmeler.md §4); yatay görüntü ekseni uçuş yönüne diktir. PX4 kaynağı değişmez.
Çıkış: 0 tamam, 1 güncel değil, 2 kullanım/okuma hatası. Yalnız standart kitaplık.
"""
import json
import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

from swarm_vehicle.ucus import rota  # noqa: E402

GEREKLI = ("CAM_WIDTH CAM_HEIGHT CAM_RATE_HZ CAM_HFOV_DEG CAM_HFOV_RAD CAM_CLIP_NEAR_M CAM_CLIP_FAR_M KAL_KAMERA_KONUM_Z_M KAMERA_LINK KAMERA_ALGILAYICI SIM_MODEL").split()


def sayi(m):
    return rota.sayi(m)


def kalibrasyon_sozlugu(ham):
    """sozlesmeler.md §4: fx = (genişlik/2)/tan(HFOV/2), fy = fx (kare piksel), cx = genişlik/2, cy = yükseklik/2; ideal iğne deliği, bozulma yok."""
    w, h = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
    hfov_deg, hfov_rad = float(ham["CAM_HFOV_DEG"]), float(ham["CAM_HFOV_RAD"])
    fx = (w / 2) / math.tan(hfov_rad / 2)
    return {
        "surum": 1, "tur": "kamera_kalibrasyon",
        "kalibrasyon_kimligi": f"KAL-{sayi(ham['CAM_HFOV_DEG'])}-{w}x{h}-v1", "kamera_kimligi": "kamera_1",
        "cozunurluk": {"genislik_px": w, "yukseklik_px": h},
        "hfov_derece": hfov_deg,
        "ic_parametreler": {"fx": round(fx, 4), "fy": round(fx, 4), "cx": w / 2, "cy": h / 2},
        "bozulma": "yok",
        "arac_kamera": {"arac_cercevesi": "FLU", "kamera_cercevesi": "OpenCV",
                        "R": [[0, -1, 0], [-1, 0, 0], [0, 0, -1]],       # aşağı bakan kamera: kamera x → gövde −y, kamera y → gövde −x, optik eksen → gövde −z
                        "t_m": [0.0, 0.0, float(ham["KAL_KAMERA_KONUM_Z_M"])]},
    }


def model_sdf(ham):
    ad = ham["SIM_MODEL"].removeprefix("gz_")
    z = float(ham["KAL_KAMERA_KONUM_Z_M"])
    yarim_pi = math.pi / 2
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Üretilmiştir (araclar/uretim/kamera_uret.py, config/deney.env değerlerinden); elle düzenlemeyin. PX4'ün x500 modeli + gövdeye sabit, aşağı bakan kamera. -->
<sdf version='1.9'>
  <model name='{ad}'>
    <self_collide>false</self_collide>
    <include merge='true'>
      <uri>x500</uri>
    </include>
    <link name='{ham["KAMERA_LINK"]}'>
      <pose>0 0 {z:g} 0 {yarim_pi!r} 0</pose>
      <inertial>
        <pose>0.03 0.03 0.03 0 0 0</pose>
        <mass>0.050</mass>
        <inertia><ixx>0.00004</ixx><ixy>0</ixy><ixz>0</ixz><iyy>0.00004</iyy><iyz>0</iyz><izz>0.00004</izz></inertia>
      </inertial>
      <visual name='kamera_govde'>
        <geometry><box><size>0.02 0.04 0.04</size></box></geometry>
      </visual>
      <sensor name='{ham["KAMERA_ALGILAYICI"]}' type='camera'>
        <always_on>1</always_on>
        <update_rate>{float(ham["CAM_RATE_HZ"]):g}</update_rate>
        <visualize>false</visualize>
        <camera>
          <horizontal_fov>{float(ham["CAM_HFOV_RAD"])!r}</horizontal_fov>
          <image><width>{int(ham["CAM_WIDTH"])}</width><height>{int(ham["CAM_HEIGHT"])}</height><format>R8G8B8</format></image>
          <clip><near>{float(ham["CAM_CLIP_NEAR_M"]):g}</near><far>{float(ham["CAM_CLIP_FAR_M"]):g}</far></clip>
        </camera>
      </sensor>
    </link>
    <joint name='KameraEklemi' type='fixed'>
      <parent>base_link</parent>
      <child>{ham["KAMERA_LINK"]}</child>
    </joint>
  </model>
</sdf>
"""


def ana(argv):
    a = list(argv)
    if not a or a[0] not in ("kalibrasyon", "model"):
        print(__doc__, file=sys.stderr)
        return 2
    komut = a.pop(0)
    try:
        ham = rota.deney_env_oku()
        eksik = [k for k in GEREKLI if k not in ham]
        if eksik:
            raise ValueError("yapılandırmada eksik anahtar: " + ", ".join(eksik))
        if komut == "model":
            if len(a) != 1:
                print(__doc__, file=sys.stderr)
                return 2
            klasor = os.path.join(a[0], ham["SIM_MODEL"].removeprefix("gz_"))
            os.makedirs(klasor, exist_ok=True)
            with open(os.path.join(klasor, "model.sdf"), "w", encoding="utf-8") as f:
                f.write(model_sdf(ham))
            print(f"(+) Model yazıldı: {os.path.join(klasor, 'model.sdf')}")
            return 0
        kontrol, cikti = False, os.path.join(KOK, "config", "kamera_kalibrasyon.json")
        while a:
            k = a.pop(0)
            if k == "--check":
                kontrol = True
            elif k == "--cikti" and a:
                cikti = a.pop(0)
            else:
                print(__doc__, file=sys.stderr)
                return 2
        metin = json.dumps(kalibrasyon_sozlugu(ham), indent=2, ensure_ascii=False) + "\n"
        ad = os.path.relpath(cikti, KOK) if cikti.startswith(KOK) else os.path.basename(cikti)
        if kontrol:
            try:
                with open(cikti, encoding="utf-8") as f:
                    mevcut = f.read()
            except OSError as e:
                print(f"(-) {ad} okunamadı: {e}")
                return 1
            if mevcut == metin:
                print(f"(+) {ad} güncel (yapılandırmadan üretilenle bayt bayt aynı)")
                return 0
            print(f"(-) {ad} güncel değil (yeniden üretmek için: python3 araclar/uretim/kamera_uret.py kalibrasyon)")
            return 1
        with open(cikti, "w", encoding="utf-8") as f:
            f.write(metin)
        print(f"(i) Yazıldı: {ad}")
        return 0
    except (OSError, ValueError) as e:
        print(f"(-) {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
