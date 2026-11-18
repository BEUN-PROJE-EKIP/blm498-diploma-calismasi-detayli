#!/usr/bin/env python3
"""Bölge ve rota dosyasını (config/bolge_rota.json) config/deney.env değerlerinden üretir.

Kullanım:
  rota_uret.py                  config/bolge_rota.json yazar ve sozlesme_dogrula.py ile doğrular
  rota_uret.py --check          dosya güncel değilse (yapılandırmadan üretilenle bayt bayt aynı değilse) çıkış 1
  rota_uret.py --cikti <yol>    başka yola yazar (--check ile birlikte: o dosyayı denetler)
  rota_uret.py --env <yol>      başka yapılandırma dosyası
Alan kilitli değildir (U23): dosya 1.7'de yeniden üretilebilir. Çıktı belirlenimcidir. Yalnız standart kitaplık; sudo gerekmez.
Çıkış: 0 tamam, 1 güncel değil/doğrulama hatası, 2 kullanım/okuma hatası.
"""
import os
import subprocess
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

from swarm_vehicle.ucus import rota  # noqa: E402


def ana(argv):
    kontrol, cikti, env = False, os.path.join(KOK, "config", "bolge_rota.json"), None
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--check":
            kontrol = True
        elif k in ("--cikti", "--env") and a:
            if k == "--cikti":
                cikti = a.pop(0)
            else:
                env = a.pop(0)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    try:
        metin = rota.json_metni(rota.uret(rota.deney_env_oku(env)))
    except (OSError, ValueError) as e:
        print(f"(-) Yapılandırma okunamadı ya da geçersiz: {e}", file=sys.stderr)
        return 2
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
        print(f"(-) {ad} güncel değil: yapılandırmadan üretilenden farklı (yeniden üretmek için: python3 araclar/rota_uret.py)")
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(cikti)), exist_ok=True)
    gecici = cikti + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        f.write(metin)
    os.replace(gecici, cikti)
    print(f"(i) Yazıldı: {ad}")
    sonuc = subprocess.run([sys.executable, "-I", os.path.join(KOK, "araclar", "sozlesme_dogrula.py"), cikti, *(["--yapilandirma", env] if env else [])],
                           capture_output=True, text=True, check=False)
    if sonuc.returncode == 0:
        print("(+) Doğrulayıcı kabul etti (sozlesme_dogrula.py: GEÇERLİ)")
        return 0
    print(f"(-) Doğrulayıcı reddetti:\n{sonuc.stdout}{sonuc.stderr}")
    return 1


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
