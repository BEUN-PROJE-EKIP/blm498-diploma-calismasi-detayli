"""Test pisti: dokusuz `default` dünyada kameraların bakacağı bir şey olsun diye çalışma anında eklenen görsel pist (çarpışmasız).

Yalnız panel_ayar.json "test_pisti.dunyalar" içindeki dünyalarda eklenir; detaylı dünyada eklenmez. Sahne/dünya dosyalarına dokunmaz.
"""

_ASFALT = "0.22 0.23 0.24"
_BEYAZ = "0.92 0.92 0.9"


def _kutu(ad, x, y, sx, sy, sz, z, renk):
    return (f'      <visual name="{ad}"><pose>{x} {y} {z} 0 0 0</pose>'
            f'<geometry><box><size>{sx} {sy} {sz}</size></box></geometry>'
            f'<material><ambient>{renk} 1</ambient><diffuse>{renk} 1</diffuse><specular>0.05 0.05 0.05 1</specular></material>'
            f'</visual>')


def pist_sdf(ad, ayar):
    boy, en = float(ayar.get("boy_m", 240)), float(ayar.get("en_m", 30))
    cx, cy = ayar.get("merkez_m", [0, 0])
    zc = 0.0225                       # işaretler asfaltın (0,02 m) hemen üstünde: z-çatışması olmasın
    parcalar = [_kutu("asfalt", 0, 0, boy, en, 0.02, 0.01, _ASFALT),
                _kutu("kenar_k", 0, en / 2 - 1, boy - 4, 0.6, 0.005, zc, _BEYAZ),
                _kutu("kenar_g", 0, -en / 2 + 1, boy - 4, 0.6, 0.005, zc, _BEYAZ)]
    adim, yari = 20, int(boy / 2 - 40)
    for i, x in enumerate(range(-yari, yari + 1, adim)):
        parcalar.append(_kutu(f"orta_{i}", x, 0, 9, 0.6, 0.005, zc, _BEYAZ))
    seritler = [en / 2 * f for f in (-0.77, -0.6, -0.43, -0.27, 0.27, 0.43, 0.6, 0.77)]
    for uc, xe in (("bati", -boy / 2 + 6), ("dogu", boy / 2 - 6)):
        for j, y in enumerate(seritler):
            parcalar.append(_kutu(f"esik_{uc}_{j}", xe, round(y, 2), 9, 1.4, 0.005, zc, _BEYAZ))
    govde = "\n".join(parcalar)
    return f"""<?xml version="1.0"?>
<sdf version="1.9">
  <model name="{ad}">
    <static>true</static>
    <pose>{cx} {cy} 0 0 0 0</pose>
    <link name="link">
{govde}
    </link>
  </model>
</sdf>"""
