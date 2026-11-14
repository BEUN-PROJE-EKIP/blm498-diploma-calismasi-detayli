"""Elle/test komut gönderme aracı (yer istasyonu komut arayüzü iskeleti): `python -m swarm_gcs.komut_gonder --arac N --sira S [--bekle-sn 15]`.
Ayrı bir yer istasyonu düğümü (/gcs/komut_gonder) açar, araç komut konusundaki aboneyle eşleşmeyi bekler, `Command` gönderir ve onayı bekler. Komut türü yoktur; araç ACK_REJECTED döner (planlama/sozlesmeler.md §9, kararlar.md).
Çıkış: 0 onay alındı (durumu `KOMUT onay ...` satırında), 1 onay gelmedi / eşleşme olmadı, 2 kullanım. Ortam: setup/env.sh, GZ_PARTITION gerekmez."""
import os
import sys
import time

from swarm_vehicle import rota


def ana(argv):
    arac, sira, bekle = None, None, 15.0
    a = list(argv)
    while a:
        k = a.pop(0)
        if k == "--arac" and a:
            arac = int(a.pop(0))
        elif k == "--sira" and a:
            sira = int(a.pop(0))
        elif k == "--bekle-sn" and a:
            bekle = float(a.pop(0))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if arac is None or sira is None:
        print(__doc__, file=sys.stderr)
        return 2
    ham = rota.deney_env_oku()
    if not os.environ.get("FASTRTPS_DEFAULT_PROFILES_FILE"):
        print("(-) FASTRTPS_DEFAULT_PROFILES_FILE tanımsız: setup/env.sh ile ortamı kurun", file=sys.stderr)
        return 2
    os.environ["SWARM_BIND_ADDR"] = ham["GCS_ADDR"]
    import rclpy
    from rclpy.node import Node
    from .komut_arayuzu import KomutArayuzu
    klasor = rota.aktif_kosu_klasoru()
    rclpy.init()
    dugum = Node("komut_gonder", namespace="/gcs")
    ara = KomutArayuzu(dugum, ham, [arac], os.path.join(klasor, "kayit", "yer_istasyonu_komut.jsonl") if klasor else None)
    kod = 1
    try:
        sinir = time.monotonic() + bekle
        while not ara.eslesme_var(arac) and time.monotonic() < sinir:
            rclpy.spin_once(dugum, timeout_sec=0.1)
        if not ara.eslesme_var(arac):
            print(f"KOMUT eslesme_yok arac={arac}", flush=True)
            return 1
        ara.komut_gonder(arac, sira)
        print(f"KOMUT gonderildi arac={arac} sira={sira} ack=ACK_PENDING", flush=True)
        while ara.onay(arac, sira) is None and time.monotonic() < sinir:
            rclpy.spin_once(dugum, timeout_sec=0.1)
        o = ara.onay(arac, sira)
        if o is None:
            print(f"KOMUT onay_yok arac={arac} sira={sira}", flush=True)
        else:
            print(f"KOMUT onay arac={arac} sira={sira} ack={o[0]}", flush=True)
            kod = 0
    finally:
        dugum.destroy_node()
        rclpy.shutdown()
    return kod


def main():
    kod = ana(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(kod)      # gz/rclpy yıkımı kapanışta çekirdek dökümü üretmesin (koordinator_deneme.py ile aynı gerekçe)


if __name__ == "__main__":
    main()
