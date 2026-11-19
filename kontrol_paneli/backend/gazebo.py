"""Gazebo bağlantısı (gz-transport, ros_gz_bridge yok): araç kameraları, tepeden harita kamerası, araç pozları ve simülasyon saati.

Harita kamerası: koşu başladıktan sonra `/world/<dünya>/create` hizmetiyle dünyaya YALNIZ çalışma anında eklenen, kuzey yukarı bakan sabit bir
kameradır; sahne/dünya dosyalarına dokunmaz. Poz "x y z 0 π/2 π/2": görüntünün yukarısı dünya +Y (kuzey), sağı dünya +X (doğu).
Not: ek kamera GPU'ya ek render yükü getirir; panel ölçüm yapılan koşularda kullanılmamalıdır (yalnız sunum/gösterim aracı).
"""
import threading
import time

import cv2
import numpy as np

_RGB_INT8 = 3
_BGR_INT8 = 8


class Kaynak:
    """Bir görüntü kaynağının son JPEG karesi; MJPEG akışları yeni kare için `bekle` ile uyur."""

    def __init__(self, ad):
        self.ad = ad
        self.jpeg = None
        self.sayac = 0
        self.zaman = 0.0          # son karenin alındığı an (time.time)
        self.boyut = None
        self._kosul = threading.Condition()

    def koy(self, jpeg, boyut):
        with self._kosul:
            self.jpeg, self.boyut = jpeg, boyut
            self.sayac += 1
            self.zaman = time.time()
            self._kosul.notify_all()

    def bekle(self, son_sayac, zaman_asimi=5.0):
        with self._kosul:
            self._kosul.wait_for(lambda: self.sayac != son_sayac, timeout=zaman_asimi)
            return self.sayac, self.jpeg

    def canli(self, esik_sn=3.0):
        return self.jpeg is not None and time.time() - self.zaman < esik_sn

    def sifirla(self):
        with self._kosul:
            self.jpeg, self.boyut, self.zaman = None, None, 0.0


def _goruntu_jpeg(m, kalite):
    w, h = m.width, m.height
    if w == 0 or h == 0:
        return None
    adim = m.step or w * 3
    dizi = np.frombuffer(m.data, dtype=np.uint8)
    if dizi.size < adim * h:
        return None
    dizi = dizi[: adim * h].reshape(h, adim)[:, : w * 3].reshape(h, w, 3)
    if m.pixel_format_type != _BGR_INT8:            # Gazebo kameraları R8G8B8 (RGB_INT8) üretir
        dizi = cv2.cvtColor(dizi, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", dizi, [cv2.IMWRITE_JPEG_QUALITY, int(kalite)])
    return buf.tobytes() if ok else None


def _harita_sdf(ad, konu, h):
    cx, cy = h["merkez_m"]
    return f"""<?xml version="1.0"?>
<sdf version="1.9">
  <model name="{ad}">
    <static>true</static>
    <pose>{cx} {cy} {h['yukseklik_m']} 0 1.5707963 1.5707963</pose>
    <link name="link">
      <sensor name="harita" type="camera">
        <always_on>1</always_on>
        <update_rate>{h['hz']}</update_rate>
        <visualize>false</visualize>
        <topic>{konu}</topic>
        <camera>
          <horizontal_fov>{h['hfov_rad']}</horizontal_fov>
          <image><width>{h['genislik_px']}</width><height>{h['yukseklik_px']}</height><format>R8G8B8</format></image>
          <clip><near>1</near><far>{h['uzak_kirpma_m']}</far></clip>
        </camera>
      </sensor>
    </link>
  </model>
</sdf>"""


class GazeboBaglantisi:
    def __init__(self, yap, gunluk_yaz):
        self.yap = yap
        self._yaz = gunluk_yaz
        self.kalite = yap.ayar.get("jpeg_kalite", 75)
        self.kameralar = {a.no: Kaynak(f"iha{a.no}") for a in yap.araclar}
        self.harita = Kaynak("harita")
        self.pozlar = {}                  # araç no → {"x","y","z","yaw","t"}
        self.sim_saat = None              # sn
        self._sim_saat_zaman = 0.0
        self.harita_durum = "yok"         # yok | ekleniyor | eklendi | hata
        self._node = None
        self._konular = []
        self._partition = None
        self._nesil = 0
        self._k = threading.Lock()
        self._model_no = {a.model_adi: a.no for a in yap.araclar}
        self._son_poz_islem = 0.0

    # ---- bağlantı yönetimi ------------------------------------------------------------------
    def partition_ayarla(self, partition):
        from gz.msgs10.clock_pb2 import Clock
        from gz.msgs10.image_pb2 import Image
        from gz.msgs10.pose_v_pb2 import Pose_V
        from gz.transport13 import Node, NodeOptions

        with self._k:
            self._nesil += 1
            nesil = self._nesil
            if self._node is not None:
                for konu in self._konular:
                    try:
                        self._node.unsubscribe(konu)
                    except Exception:  # noqa: BLE001
                        pass
            self._node, self._konular, self._partition = None, [], partition
            for k in (*self.kameralar.values(), self.harita):
                k.sifirla()
            self.pozlar, self.sim_saat, self.harita_durum = {}, None, "yok"
            if not partition:
                return
            secenek = NodeOptions()
            secenek.partition = partition
            node = Node(secenek)
            w = self.yap.dunya
            for a in self.yap.araclar:
                kaynak = self.kameralar[a.no]
                node.subscribe(Image, a.kamera_konusu, lambda m, k=kaynak: self._kare(k, m))
                self._konular.append(a.kamera_konusu)
            hk = self.yap.ayar["harita"]["konu"]
            node.subscribe(Image, hk, lambda m: self._kare(self.harita, m))
            node.subscribe(Pose_V, f"/world/{w}/pose/info", self._poz)
            node.subscribe(Clock, f"/world/{w}/clock", self._saat)
            self._konular += [hk, f"/world/{w}/pose/info", f"/world/{w}/clock"]
            self._node = node
        self._yaz(f"(i) Gazebo'ya bağlanıldı (partition {partition})")
        threading.Thread(target=self._modelleri_ekle, args=(nesil,), name="model-ekle", daemon=True).start()

    def _modelleri_ekle(self, nesil):
        """Dünyaya çalışma anında panel modellerini ekler: harita kamerası ve (varsa) test pisti."""
        h = self.yap.ayar["harita"]
        self.harita_durum = "ekleniyor"
        # Harita kamerası her panel açılışında güncel ayarla yeniden kurulur (eski ayarlı kopya kaldırılır).
        ok = self._model_ekle(nesil, h["model_adi"], _harita_sdf(h["model_adi"], h["konu"], h), yenile=True)
        if nesil != self._nesil:
            return
        self.harita_durum = "eklendi" if ok else "hata"
        if ok:
            self._yaz(f"(+) Harita kamerası hazır ({h['yukseklik_m']:g} m yükseklik)")
        else:
            self._yaz("(-) Harita kamerası eklenemedi (Gazebo yanıt vermedi)")
        pist = self.yap.ayar.get("test_pisti", {})
        if pist.get("etkin") and self.yap.dunya in pist.get("dunyalar", []):
            from test_pisti import pist_sdf
            if self._model_ekle(nesil, pist["model_adi"], pist_sdf(pist["model_adi"], pist), yenile=False):
                self._yaz("(+) Test pisti dünyada")

    def _model_ekle(self, nesil, ad, sdf, yenile):
        """Modeli ekler; başarılıysa True. KALDIRMA EN FAZLA BİR KEZ yapılır: kameralı model eklemek (render hazırlığı) hizmet
        zaman aşımından uzun sürebilir; her denemede kaldırılsaydı az önce eklenen model silinirdi. Yeniden deneme güvenlidir:
        aynı adlı model varsa Gazebo yalnız reddeder (allow_renaming=false)."""
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10.entity_factory_pb2 import EntityFactory
        from gz.msgs10.entity_pb2 import Entity

        w = self.yap.dunya
        istek = EntityFactory()
        istek.sdf, istek.name, istek.allow_renaming = sdf, ad, False
        son = time.time() + 120
        while self.sim_saat is None:                 # dünya çalışana dek bekle
            if nesil != self._nesil or time.time() > son:
                return False
            time.sleep(1.0)
        with self._k:
            node = self._node if nesil == self._nesil else None
        if node is None:
            return False
        if yenile:
            sil = Entity()
            sil.name, sil.type = ad, Entity.MODEL
            try:
                _, yanit = node.request(f"/world/{w}/remove", sil, Entity, Boolean, 10000)
                if yanit is not None and yanit.data:
                    self._yaz(f"(i) Eski {ad} kaldırıldı")
                    time.sleep(2.0)
            except Exception:  # noqa: BLE001
                pass
        for _ in range(3):
            if nesil != self._nesil:
                return False
            try:
                tamam, yanit = node.request(f"/world/{w}/create", istek, EntityFactory, Boolean, 30000)
            except Exception as e:  # noqa: BLE001
                tamam, yanit = False, None
                self._yaz(f"(!) {ad} ekleme isteği: {e}")
            if tamam:
                # data=false: aynı adla zaten var (önceki deneme yanıtı geç geldiyse ya da panel yeniden açıldıysa) → yine hazır
                return True
            time.sleep(3.0)
        return False

    # ---- geri çağrılar ----------------------------------------------------------------------
    def _kare(self, kaynak, m):
        try:
            jpeg = _goruntu_jpeg(m, self.kalite)
        except Exception:  # noqa: BLE001 — bozuk kare akışı durdurmamalı
            return
        if jpeg:
            kaynak.koy(jpeg, (m.width, m.height))

    def _poz(self, m):
        simdi = time.time()
        if simdi - self._son_poz_islem < 0.1:        # 10 Hz yeterli
            return
        self._son_poz_islem = simdi
        yeni = {}
        for p in m.pose:
            no = self._model_no.get(p.name)
            if no is None:
                continue
            q = p.orientation
            yaw = float(np.arctan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z)))
            yeni[no] = {"x": p.position.x, "y": p.position.y, "z": p.position.z, "yaw": yaw, "t": simdi}
        if yeni:
            self.pozlar = {**self.pozlar, **yeni}

    def _saat(self, m):
        self.sim_saat = m.sim.sec + m.sim.nsec * 1e-9
        self._sim_saat_zaman = time.time()

    # ---- durum ------------------------------------------------------------------------------
    def durum(self):
        simdi = time.time()
        h = self.yap.ayar["harita"]
        return {
            "partition": self._partition,
            "bagli": self._node is not None,
            "sim_saat": self.sim_saat,
            "sim_akiyor": self.sim_saat is not None and simdi - self._sim_saat_zaman < 3.0,
            "kameralar": {no: {"canli": k.canli(), "sayac": k.sayac, "boyut": k.boyut} for no, k in self.kameralar.items()},
            "harita": {"canli": self.harita.canli(), "durum": self.harita_durum, "merkez_m": h["merkez_m"],
                       "yukseklik_m": h["yukseklik_m"], "hfov_rad": h["hfov_rad"],
                       "genislik_px": h["genislik_px"], "yukseklik_px": h["yukseklik_px"]},
            "pozlar": {no: p for no, p in self.pozlar.items() if simdi - p["t"] < 3.0},
        }
