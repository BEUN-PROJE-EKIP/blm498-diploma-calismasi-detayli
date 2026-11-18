"""Sabit portların Linux geçici (ephemeral) port aralığının DIŞINDA olduğunun denetimi (ROS'suz, yalnız standart kitaplık).

Neden: aralıktaki bir port başka bir sürecin giden bağlantısına kaynak port olarak atanmış olabilir; bu durumda dinleme (`bind`) SO_REUSEADDR/SO_REUSEPORT ile bile
"Address already in use" verir ve `connect_ex` denetimi (dinleyen yok → reddedildi) bunu göremez. Aralık makine ayarıdır (`/proc/sys/net/ipv4/ip_local_port_range`),
sabit yazılmaz; çalışma anında okunur. Yeniden deneme yoktur: aralık içindeki port açık hatayla reddedilir.
"""

import sys

ARALIK_DOSYASI = "/proc/sys/net/ipv4/ip_local_port_range"


class PortAraligiHatasi(ValueError):
    """Sabit port, geçici port aralığının içinde."""


def gecici_aralik(yol=ARALIK_DOSYASI):
    """(en_kucuk, en_buyuk) ya da dosya okunamıyorsa None (Linux dışı)."""
    try:
        with open(yol, encoding="ascii") as f:
            alt, ust = f.read().split()
        return int(alt), int(ust)
    except (OSError, ValueError):
        return None


def aralik_disinda_mi(port, aralik):
    return aralik is None or not (aralik[0] <= int(port) <= aralik[1])


def denetle(port, ad, yol=ARALIK_DOSYASI, uyar=None):
    """Port geçici aralığın içindeyse PortAraligiHatasi fırlatır. Aralık okunamıyorsa denetim yapılamaz ve çalışma durmaz; ama sessiz de geçmez:
    `uyar(metin)` verilmişse çağrılır, verilmemişse standart hataya `(!)` satırı yazılır."""
    aralik = gecici_aralik(yol)
    if aralik is None:
        metin = f"{ad} portu {port}: geçici port aralığı okunamadı ({yol}); aralık denetimi yapılamadı (çalışma durmuyor)"
        if uyar is not None:
            uyar(metin)
        else:
            print(f"(!) {metin}", file=sys.stderr, flush=True)
    if not aralik_disinda_mi(port, aralik):
        raise PortAraligiHatasi(
            f"{ad} portu {port}, Linux geçici port aralığının ({aralik[0]}–{aralik[1]}, {yol}) içinde: başka sürecin giden bağlantısı bu portu alıp dinlemeyi "
            f"engelleyebilir; config/deney.env içinde portu aralığın dışına alın")
    return aralik
