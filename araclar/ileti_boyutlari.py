#!/usr/bin/env python3
"""ROS 2 ileti türlerinin serileştirilmiş (CDR) boyutlarını yazar (DDS uygulama yükünü TAHMİN etmek için; ölçüm değil): `swarm_msgs` FrameResult (boş tespit listesi), VehicleState, ScanFinished, ScanStart, Complete, Mission (rota
noktalarıyla). Çıktı: JSON (stdout). Ortam: setup/env.sh (ROS + install). Kullanım: python araclar/ileti_boyutlari.py"""
import json
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))


def ana():
    from geometry_msgs.msg import Point
    from rclpy.serialization import serialize_message
    from swarm_msgs.msg import Complete, FrameResult, Mission, ScanFinished, ScanStart, VehicleState
    from swarm_vehicle import gorev, rota
    br = gorev.bolge_rota_oku(os.path.join(rota.KOK, "config", "bolge_rota.json"))
    mission = gorev.mesaj_doldur(Mission, Point, gorev.mission_sozlugu(br, 1, "G_20260101_000000"))
    fr = FrameResult()
    fr.vehicle_id, fr.numbering_mode, fr.frame_number, fr.status = 1, FrameResult.NUMBERING_GRID, 200, FrameResult.STATUS_NO_DETECTION
    vs = VehicleState()
    vs.vehicle_id, vs.state = 1, VehicleState.STATE_TARAMA
    sf = ScanFinished()
    sf.mission_id, sf.vehicle_id, sf.numbering_mode = "G_20260101_000000", 1, ScanFinished.NUMBERING_GRID
    ss, cm = ScanStart(), Complete()
    ss.mission_id = cm.mission_id = "G_20260101_000000"
    boy = lambda m: len(serialize_message(m))  # noqa: E731
    print(json.dumps({"FrameResult": boy(fr), "VehicleState": boy(vs), "ScanFinished": boy(sf), "ScanStart": boy(ss), "Complete": boy(cm), "Mission": boy(mission)}))
    return 0


if __name__ == "__main__":
    sys.exit(ana())
