"""Sentetik yük üretici ve tc ayrıştırıcı birim testleri (ROS 2 gerekmez; 127.0.0.1 üzerinde). Çalıştırma: python3 src/swarm_vehicle/test/test_sentetik_yuk.py"""
import json
import os
import socket
import sys
import threading
import time
import unittest

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(KOK, "araclar"))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))
import sentetik_yuk as sy  # noqa: E402
import tc_izle  # noqa: E402
from swarm_vehicle.ucus import rota  # noqa: E402


def bos_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Kuyruk(unittest.TestCase):
    def test_kare_atilmaz_sira_korunur(self):
        k = sy.KareKuyrugu()
        for i in range(500):
            k.koy(i, i * 10)
        self.assertEqual((k.derinlik(), k.giren), (500, 500))
        self.assertEqual([k.al()[0] for _ in range(500)], list(range(500)))
        self.assertIsNone(k.al(0.01))


class Yuk(unittest.TestCase):
    def test_loopback_sayim_ve_sira(self):
        y = sy.AracYuku(1, "127.0.0.1", "127.0.0.1", bos_port(), 4096, 40, None)
        y.baslat()
        time.sleep(1.0)
        y.dur_uret.set()
        self.assertTrue(y.bitti_gonder.wait(10))
        y.kapat()
        n = y.kuyruk.giren
        self.assertTrue(30 <= n <= 50, n)                               # 40 Hz × ~1 sn
        self.assertEqual((y.gonderilen_kare, y.alinan_kare), (n, n))     # hiçbir kare atılmadı, hepsi alındı
        self.assertEqual(y.gonderilen_bayt, n * (4096 + sy.BASLIK.size))
        self.assertEqual(y.alinan_bayt, y.gonderilen_bayt)
        kayit = y.kare_kayitlari()
        self.assertEqual([r["seq"] for r in kayit], list(range(n)))      # sıra korunur
        self.assertTrue(all(r["enq_ns"] <= r["gonderim_bitis_ns"] and r["gonderim_bitis_ns"] <= r["alim_bitis_ns"] + 5 * 10 ** 6 for r in kayit))

    def test_geri_basinc_kuyruk_buyur_kare_atilmaz(self):
        """Yavaş soket (her kare 0,1 sn): kuyruk derinliği artar, hiçbir kare atılmaz; durunca kalanlar sırayla gönderilir."""
        y = sy.AracYuku(1, "127.0.0.1", "127.0.0.1", bos_port(), 1000, 100, None)

        class Yavas:
            def __init__(self):
                self.gelen = []

            def sendall(self, veri):
                if len(veri) == sy.BASLIK.size:
                    self.gelen.append(sy.BASLIK.unpack(veri)[0])
                    time.sleep(0.1)
        s = Yavas()
        ut = threading.Thread(target=y._uretici, daemon=True)
        gt = threading.Thread(target=y._gonderici, args=(s,), daemon=True)
        ut.start()
        gt.start()
        time.sleep(0.6)
        self.assertGreater(y.kuyruk.derinlik(), 30)                      # üretim 100 Hz, gönderim ~10 Hz: kuyruk büyüyor
        y.dur_uret.set()
        self.assertTrue(y.bitti_gonder.wait(15))
        self.assertEqual(s.gelen, list(range(y.kuyruk.giren)))           # hepsi, sırayla
        y._dinle.close()


class Yapilandirma(unittest.TestCase):
    def test_kare_boyutu_ve_hizi_anahtardan(self):
        ham = rota.deney_env_oku()
        self.assertEqual(int(ham["CAM_WIDTH"]) * int(ham["CAM_HEIGHT"]) * 3, 921600)
        self.assertEqual(float(ham["CAM_RATE_HZ"]), 2.0)
        self.assertIn("SENTETIK_YUK_PORT_TABAN", ham)
        yuk_mbit = 3 * (921600 + sy.BASLIK.size) * 2 * 8 / 1e6
        self.assertAlmostEqual(yuk_mbit, 44.2368, delta=0.01)             # GŞÖA 6.5: 3 × 640 × 480 × 3 × 2 × 8 = 44,2368 Mbit/s


class TcAyristirici(unittest.TestCase):
    SINIF = """class htb 1:10 parent 1:1 leaf 10: prio 0 rate 25Mbit ceil 25Mbit burst 128Kb cburst 128Kb 
 Sent 1103062169 bytes 2817139 pkt (dropped 7, overlimits 55695 requeues 0) 
 backlog 4Mb 2800p requeues 0
 lended: 2816749 borrowed: 0 giants: 0

class htb 1:1 root rate 100Gbit ceil 100Gbit burst 2400b cburst 2400b 
 Sent 5 bytes 1 pkt (dropped 0, overlimits 0 requeues 0) 
 backlog 0b 0p requeues 0
"""

    def test_sinif(self):
        d = tc_izle.sinif_ayristir(self.SINIF)
        self.assertEqual(d, {"bayt": 1103062169, "paket": 2817139, "dusen": 7, "overlimits": 55695, "backlog_bayt": 4 * 1024 ** 2, "backlog_paket": 2800})
        self.assertEqual(tc_izle.sinif_ayristir(self.SINIF, "1:1")["bayt"], 5)
        self.assertIsNone(tc_izle.sinif_ayristir(self.SINIF, "1:99"))

    def test_qdisc_json(self):
        j = json.dumps([{"kind": "htb", "handle": "1:", "overlimits": 57269}, {"kind": "bfifo", "handle": "10:", "bytes": 100, "packets": 3, "drops": 2, "overlimits": 0, "backlog": 4096, "qlen": 5}])
        yaprak, kok = tc_izle.qdisc_ayristir(j)
        self.assertEqual((yaprak["dusen"], yaprak["backlog_bayt"], yaprak["backlog_paket"], kok), (2, 4096, 5, 57269))

    def test_gercek_tc_okunur(self):
        o = tc_izle.oku()
        self.assertIsNotNone(o["sinif"])
        self.assertIsNotNone(o["yaprak"])


if __name__ == "__main__":
    unittest.main()
