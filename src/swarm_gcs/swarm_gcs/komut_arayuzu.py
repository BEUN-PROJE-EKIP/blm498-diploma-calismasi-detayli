"""Yer istasyonu komut arayüzü iskeleti (rclpy): `swarm_gcs → araç komut konusu → px4_adapter` yolunun yer istasyonu ucu [belge: komutlar araç kimliği, sıra numarası ve onay durumu içerir].

Belge komut TÜRLERİNİ tanımlamaz ve kullanıcı kararı gereği yeni tür uydurulmaz: `Command` iletisi yalnız {vehicle_id, sequence, ack_state} taşır; araç komutu `px4_adapter.komut_isle` ile denetler ve her durumda
ACK_REJECTED döner (PX4'e hiçbir şey yazılmaz). Komut gönderimi yalnız test/elle kullanım içindir; koşu akışında koordinatör komut göndermez.
Konular [varsayım]: araç komut konusu `/<ad_alanı>/<KONU_KOMUT>` (reliable, volatile, keep_last 10); ortak onay konusu `KONU_KOMUT_ONAY` (reliable, transient_local, keep_last 20).
Kayıt: `kayit/yer_istasyonu_komut.jsonl` (serbest biçim, şema değildir; görev olay kaydı `gorev_olay` komut olayı içermez): gönderim ve onay satırları.
"""
import json
import threading
import time


class KomutArayuzu:
    def __init__(self, dugum, ham, arac_kimlikleri, kayit_yol=None):
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from swarm_msgs.msg import Command
        self._Command = Command
        self.ham, self.kayit_yol, self._k = ham, kayit_yol, threading.Lock()
        kimlikler = [int(x) for x in ham["UAV_SYS_IDS"].split()]
        ad_alanlari = ham["UAV_NAMESPACES"].split()
        self.arac_kimlikleri = [int(a) for a in arac_kimlikleri]
        qos_komut = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
        qos_onay = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=20, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._pub = {}
        for a in self.arac_kimlikleri:
            konu = f"/{ad_alanlari[kimlikler.index(a)].strip('/')}/{ham['KONU_KOMUT'].strip('/')}"
            self._pub[a] = dugum.create_publisher(Command, konu, qos_komut)
        self.onaylar = {}                               # (araç, sıra) → (ack_state, mono_ns)
        self.gonderilen = {}                            # (araç, sıra) → mono_ns
        self._abone = dugum.create_subscription(Command, ham["KONU_KOMUT_ONAY"], self._onay_geldi, qos_onay)

    def _yaz(self, d):
        if self.kayit_yol:
            with self._k, open(self.kayit_yol, "a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def eslesme_var(self, arac):
        return self._pub[int(arac)].get_subscription_count() > 0

    def komut_gonder(self, arac, sira):
        """Araca `sira` numaralı komutu (ack_state = ACK_PENDING) gönderir; komut türü yoktur."""
        arac, sira = int(arac), int(sira)
        m = self._Command()
        m.vehicle_id, m.sequence, m.ack_state = arac, sira, self._Command.ACK_PENDING
        mono = time.monotonic_ns()
        self._pub[arac].publish(m)
        self.gonderilen[(arac, sira)] = mono
        self._yaz({"olay": "komut_gonderildi", "mono_ns": mono, "arac_kimligi": arac, "sequence": sira, "ack_state": "ACK_PENDING"})

    def _onay_geldi(self, m):
        mono = time.monotonic_ns()
        if (int(m.vehicle_id), int(m.sequence)) not in self.gonderilen:
            return                                      # bu arayüzün göndermediği komutun onayı (transient_local ile yeniden oynatılan eski onay): kayda alınmaz
        ad = {self._Command.ACK_ACCEPTED: "ACK_ACCEPTED", self._Command.ACK_REJECTED: "ACK_REJECTED", self._Command.ACK_PENDING: "ACK_PENDING"}.get(m.ack_state, f"ACK_{m.ack_state}")
        self.onaylar[(int(m.vehicle_id), int(m.sequence))] = (ad, mono)
        self._yaz({"olay": "onay_alindi", "mono_ns": mono, "arac_kimligi": int(m.vehicle_id), "sequence": int(m.sequence), "ack_state": ad})

    def onay(self, arac, sira):
        return self.onaylar.get((int(arac), int(sira)))
