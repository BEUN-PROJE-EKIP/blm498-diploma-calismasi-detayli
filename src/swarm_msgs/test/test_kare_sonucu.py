"""swarm_msgs birim testi: kare sonucundaki dört durumun ("tespit var", açık "tespit yok", "işlem hatası", "kare alınamadı")
birbirine kodlanmadığını ve mesajların seri hâle getirme gidiş-dönüşünü denetler. DDS trafiği üretmez (yalnız rclpy.serialization)."""
import unittest

from builtin_interfaces.msg import Time
from rclpy.serialization import deserialize_message, serialize_message
from swarm_msgs.msg import Command, Complete, Detection, FrameResult, Mission, ScanFinished, ScanStart, VehicleState


def gidis_donus(mesaj):
    return deserialize_message(serialize_message(mesaj), type(mesaj))


def kare(durum, tespitler=(), n=7, arac=2):
    m = FrameResult()
    m.vehicle_id = arac
    m.numbering_mode = FrameResult.NUMBERING_GRID
    m.frame_number = n
    m.sim_stamp = Time(sec=n // 2, nanosec=(n % 2) * 500_000_000)    # ızgara damgası n / 2 s
    m.status = durum
    m.detections = list(tespitler)
    return m


class KareSonucuDurumlari(unittest.TestCase):
    DURUMLAR = {
        "tespit_var": FrameResult.STATUS_DETECTIONS,
        "tespit_yok": FrameResult.STATUS_NO_DETECTION,
        "islem_hatasi": FrameResult.STATUS_PROCESSING_ERROR,
        "kare_alinamadi": FrameResult.STATUS_FRAME_NOT_RECEIVED,
    }

    def test_durum_degerleri_ayri_ve_varsayilan_gecerli_degil(self):
        degerler = list(self.DURUMLAR.values())
        self.assertEqual(len(set(degerler)), 4, "dört durum farklı sayısal değerlere sahip olmalı")
        self.assertNotIn(FrameResult.STATUS_UNKNOWN, degerler)
        # Ayarlanmamış mesaj "tespit yok" sayılmaz
        self.assertEqual(FrameResult().status, FrameResult.STATUS_UNKNOWN)
        self.assertNotEqual(FrameResult().status, FrameResult.STATUS_NO_DETECTION)

    def test_tespit_yok_ile_kare_alinamadi_ile_islem_hatasi_birbirine_kodlanmaz(self):
        yok = kare(FrameResult.STATUS_NO_DETECTION)
        alinamadi = kare(FrameResult.STATUS_FRAME_NOT_RECEIVED)
        hata = kare(FrameResult.STATUS_PROCESSING_ERROR)
        for m in (yok, alinamadi, hata):
            self.assertEqual(len(m.detections), 0, "üç durumda da tespit listesi boş")
        # Liste boş olsa da durumlar birbirinden ayırt edilir (gidiş-dönüşten sonra da)
        gd = [gidis_donus(m).status for m in (yok, alinamadi, hata)]
        self.assertEqual(len(set(gd)), 3)
        self.assertEqual(gd[0], FrameResult.STATUS_NO_DETECTION)
        self.assertEqual(gd[1], FrameResult.STATUS_FRAME_NOT_RECEIVED)
        self.assertEqual(gd[2], FrameResult.STATUS_PROCESSING_ERROR)

    def test_tespitli_kare_ve_alanlar_korunur(self):
        d = Detection()
        d.class_id = Detection.CLASS_DEBRIS
        d.confidence = 0.8
        d.box_x_min, d.box_y_min, d.box_x_max, d.box_y_max = 10.0, 20.0, 50.0, 60.0
        d.has_position, d.east, d.north, d.candidate = True, 12.5, -7.25, True
        m = gidis_donus(kare(FrameResult.STATUS_DETECTIONS, [d], n=9, arac=3))
        self.assertEqual((m.vehicle_id, m.frame_number, m.status), (3, 9, FrameResult.STATUS_DETECTIONS))
        self.assertEqual((m.sim_stamp.sec, m.sim_stamp.nanosec), (4, 500_000_000))
        self.assertEqual(len(m.detections), 1)
        t = m.detections[0]
        self.assertEqual((t.class_id, t.has_position, t.east, t.north, t.candidate), (Detection.CLASS_DEBRIS, True, 12.5, -7.25, True))
        self.assertAlmostEqual(t.confidence, 0.8, places=5)

    def test_yedek_yolda_kare_numarasi_yerine_damga(self):
        m = FrameResult()
        m.vehicle_id, m.numbering_mode, m.status = 1, FrameResult.NUMBERING_FALLBACK, FrameResult.STATUS_FRAME_NOT_RECEIVED
        m.sim_stamp = Time(sec=123, nanosec=500_000_000)
        gd = gidis_donus(m)
        self.assertEqual((gd.numbering_mode, gd.frame_number, gd.sim_stamp.sec), (FrameResult.NUMBERING_FALLBACK, 0, 123))


class DigerMesajlar(unittest.TestCase):
    def test_gidis_donus(self):
        s = VehicleState(vehicle_id=2, state=VehicleState.STATE_WAIT, mission_item_current=5, mission_item_total=6, last_frame_number=640)
        self.assertEqual(gidis_donus(s), s)
        self.assertEqual(VehicleState().state, VehicleState.STATE_UNKNOWN)
        # Belge durum adları (GŞÖA 7.4) ve değerleri
        adlar = {"STATE_HAZIR": 1, "STATE_BARIYER_BEKLE": 2, "STATE_TARAMA": 3, "STATE_WAIT": 4, "STATE_TAMAMLANDI": 5}
        for ad, deger in adlar.items():
            self.assertEqual(getattr(VehicleState, ad), deger, ad)
        self.assertEqual(len(set(adlar.values())) + 1, 6, "durumlar ve UNKNOWN birbirinden farklı")
        for eski in ("STATE_PREPARING", "STATE_READY", "STATE_SCANNING", "STATE_DONE"):
            self.assertFalse(hasattr(VehicleState, eski), f"{eski} kalkmış olmalı")
        mi = Mission(mission_id="G1", vehicle_id=1, region_id="B1", altitude_m=30.0, speed_ms=5.0)
        mi.waypoints = []
        self.assertEqual(gidis_donus(mi), mi)
        self.assertEqual(gidis_donus(ScanStart(mission_id="G1")), ScanStart(mission_id="G1"))
        self.assertEqual(gidis_donus(Complete(mission_id="G1")), Complete(mission_id="G1"))
        b = ScanFinished(mission_id="G1", vehicle_id=3, numbering_mode=ScanFinished.NUMBERING_GRID, n_first=4, n_last=645)
        self.assertEqual(gidis_donus(b), b)
        self.assertEqual(ScanFinished().numbering_mode, ScanFinished.NUMBERING_UNKNOWN)
        k = Command(vehicle_id=2, sequence=17, ack_state=Command.ACK_PENDING)
        self.assertEqual(gidis_donus(k), k)
        self.assertEqual(Command().ack_state, Command.ACK_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
