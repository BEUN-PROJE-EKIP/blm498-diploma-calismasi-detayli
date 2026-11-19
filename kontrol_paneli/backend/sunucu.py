"""Kontrol paneli HTTP sunucusu (yalnız Python standart kitaplığı + projede kurulu paketler; yeni bağımlılık yok).

Uç noktalar:
  GET  /api/durum                 anlık durum (JSON)
  GET  /api/olaylar               Server-Sent Events: durum her 0,5 sn
  GET  /api/kamera/<1..3>.mjpg    araç kamerası MJPEG akışı
  GET  /api/harita.mjpg           tepeden harita kamerası MJPEG akışı
  POST /api/sistem/baslat | /api/sistem/durdur
  POST /api/gorev/baslat          {"mod": "ucta" | "merkezi"}
  POST /api/ucus/kalkis | /api/ucus/inis
  POST /api/manuel/baslat {"arac": n} | /api/manuel/bitir | /api/manuel/eksen {"ileri","sag","yukari","donus"}
  GET  /*                         derlenmiş React arayüzü (frontend/dist)
Kullanım: kontrol_paneli/calistir.sh (ortamı hazırlar ve bunu çalıştırır).
"""
import json
import mimetypes
import os
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yapilandirma
from gazebo import GazeboBaglantisi
from sistem import SistemYoneticisi
from ucus import UcusYoneticisi

DIST = os.path.join(yapilandirma.PANEL_DIZINI, "frontend", "dist")


class Panel:
    def __init__(self):
        self.yap = yapilandirma.yukle()
        self.gazebo = GazeboBaglantisi(self.yap, self._yaz)
        self.ucus = UcusYoneticisi(self.yap, self._yaz)
        self.sistem = SistemYoneticisi(self.yap, self._partition_degisti, self.ucus.baglantilari_kapat)

    def _partition_degisti(self, partition):
        """Yeni koşu (ya da koşu bitti): Gazebo aboneliklerini yenile; MAVSDK yalnız koşu varken bağlı."""
        self.gazebo.partition_ayarla(partition)
        if partition:
            self.ucus.baglan()
        else:
            self.ucus.baglantilari_kapat()

    def _yaz(self, metin):
        self.sistem._yaz(metin) if hasattr(self, "sistem") else print(metin, flush=True)

    def durum(self):
        s = self.sistem.durum()
        g = self.gazebo.durum()
        u = self.ucus.durum()
        araclar = u["araclar"]
        kontroller = [
            {"ad": "Sürü ağı (tc)", "ok": s["ag_kurulu"], "uyari": True,
             "ipucu": "setup/60_ag_emulasyon_tc.sh kendi terminalinizde (sudo)"},
            {"ad": "Gazebo sunucusu", "ok": g["sim_akiyor"]},
            *({"ad": f"PX4 İHA{a['no']} bağlantısı", "ok": a["bagli"]} for a in araclar),
            *({"ad": f"İHA{a['no']} konum/ev noktası", "ok": a["saglik"]} for a in araclar),
            *({"ad": f"İHA{no} kamerası", "ok": k["canli"]} for no, k in g["kameralar"].items()),
            {"ad": "Harita kamerası", "ok": g["harita"]["canli"]},
        ]
        return {"zaman": time.time(), "sistem": s, "gazebo": g, "araclar": araclar, "manuel_arac": u["manuel_arac"],
                "kontroller": kontroller, "kalkis_irtifa_m": self.yap.kalkis_irtifa_m,
                "baslangic": {a.no: a.baslangic for a in self.yap.araclar}}

    def komut(self, yol, govde):
        s = self.sistem.durum()["durum"]
        gorevde = s in ("gorev", "gorev_hazirlaniyor")
        if yol == "/api/sistem/baslat":
            return self.sistem.sistemi_baslat()
        if yol == "/api/sistem/durdur":
            if self.ucus.manuel_arac is not None:
                self.ucus.manuel_bitir()
            return self.sistem.sistemi_durdur()
        if yol == "/api/gorev/baslat":
            if self.ucus.manuel_arac is not None:
                return False, "Önce manuel sürüşü bitirin."
            return self.sistem.gorevi_baslat(govde.get("mod"), self.ucus.havada_arac_var())
        if yol == "/api/ucus/kalkis":
            if gorevde:
                return False, "Görev sürerken toplu kalkış verilmez (araçları görev akışı yönetir)."
            return self.ucus.toplu_kalkis()
        if yol == "/api/ucus/inis":
            return self.ucus.toplu_inis()
        if yol == "/api/manuel/baslat":
            if gorevde:
                return False, "Görev sürerken manuel sürüş açılmaz."
            return self.ucus.manuel_baslat(int(govde.get("arac", 0)))
        if yol == "/api/manuel/bitir":
            return self.ucus.manuel_bitir()
        if yol == "/api/manuel/eksen":
            self.ucus.manuel_eksen(govde.get("ileri", 0), govde.get("sag", 0), govde.get("yukari", 0), govde.get("donus", 0))
            return True, ""
        return None


PANEL = None


class Isleyici(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):     # erişim günlüğü kapalı (MJPEG ve olay akışı çok satır üretir)
        pass

    def _json(self, kod, veri):
        b = json.dumps(veri, ensure_ascii=False).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):  # noqa: N802
        yol = self.path.split("?", 1)[0]
        try:
            if yol == "/api/durum":
                return self._json(200, PANEL.durum())
            if yol == "/api/olaylar":
                return self._olaylar()
            if yol.startswith("/api/kamera/") and yol.endswith(".mjpg"):
                no = int(yol[len("/api/kamera/"):-len(".mjpg")])
                kaynak = PANEL.gazebo.kameralar.get(no)
                return self._mjpeg(kaynak) if kaynak else self._json(404, {"hata": "kamera yok"})
            if yol == "/api/harita.mjpg":
                return self._mjpeg(PANEL.gazebo.harita)
            if yol.startswith("/api/"):
                return self._json(404, {"hata": "bilinmeyen uç nokta"})
            return self._statik(yol)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):  # noqa: N802
        uzunluk = int(self.headers.get("Content-Length") or 0)
        try:
            govde = json.loads(self.rfile.read(uzunluk) or b"{}") if uzunluk else {}
        except ValueError:
            return self._json(400, {"ok": False, "ileti": "geçersiz JSON"})
        try:
            sonuc = PANEL.komut(self.path.split("?", 1)[0], govde)
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"ok": False, "ileti": str(e)})
        if sonuc is None:
            return self._json(404, {"ok": False, "ileti": "bilinmeyen komut"})
        ok, ileti = sonuc
        return self._json(200 if ok else 409, {"ok": ok, "ileti": ileti})

    def _olaylar(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        while True:
            veri = json.dumps(PANEL.durum(), ensure_ascii=False)
            self.wfile.write(f"data: {veri}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.5)

    def _mjpeg(self, kaynak):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=kare")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        sayac = -1
        while True:
            sayac, jpeg = kaynak.bekle(sayac)
            if jpeg is None:
                continue
            self.wfile.write(b"--kare\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n")
            self.wfile.write(jpeg)
            self.wfile.write(b"\r\n")
            self.wfile.flush()

    def _statik(self, yol):
        if not os.path.isdir(DIST):
            return self._json(503, {"hata": "Arayüz derlenmemiş: kontrol_paneli/frontend içinde `npm install && npm run build` çalıştırın."})
        hedef = os.path.normpath(os.path.join(DIST, yol.lstrip("/")))
        if not hedef.startswith(DIST) or not os.path.isfile(hedef):
            hedef = os.path.join(DIST, "index.html")      # tek sayfa uygulaması
        with open(hedef, "rb") as f:
            b = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(hedef)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def main():
    global PANEL
    PANEL = Panel()
    adres, port = PANEL.yap.ayar["http_adres"], int(PANEL.yap.ayar["http_port"])
    sunucu = ThreadingHTTPServer((adres, port), Isleyici)
    sunucu.daemon_threads = True
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"(+) Kontrol paneli: http://{adres}:{port}", flush=True)
    try:
        sunucu.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        PANEL.ucus.baglantilari_kapat()
        print("(i) Panel kapanıyor (koşu açık kalır; kapatmak için panelden 'Durdur' ya da araclar/kosu.sh durdur)", flush=True)


if __name__ == "__main__":
    main()
