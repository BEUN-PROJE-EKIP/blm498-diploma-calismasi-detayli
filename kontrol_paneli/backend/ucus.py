"""Uçuş yöneticisi (MAVSDK-Python): toplu kalkış, toplu iniş, manuel (oyun kolu) sürüş ve telemetri.

Bağlantı: her PX4 SITL örneği GCS bağlantısını 18570+örnek UDP portunda dinler (PX4 init.d-posix/px4-rc.mavlink). Panel her araç için kendi
mavsdk_server'ını (panel_ayar.json: mavsdk_grpc_portlari) `udpout://127.0.0.1:<18570+i>` ile bu porta bağlar; projenin px4_adapter hattı
(14540-14542, gRPC 20051-20053) kullanılmaz ve değişmez. Bu panel projeden bağımsız bir sunum aracıdır.

Yaşam döngüsü: panelin mavsdk_server'ları YALNIZ koşu açıkken yaşar. araclar/kosu.sh baslat makinede herhangi bir mavsdk_server görürse
koşuyu reddeder; bu yüzden sistem yöneticisi kosu.sh'ı çağırmadan önce `baglantilari_kapat()` çağrılır, koşu dosyası belirince `baglan()`.

Manuel sürüş: offboard modunda gövde eksenli hız + sapma hızı (VelocityBodyYawspeed). Oyun kolu ekseni tarayıcıdan gelir; `komut_zaman_asimi_sn`
içinde yeni eksen gelmezse sıfır hız gönderilir (araç yerinde durur). Bitirince offboard durur, PX4 Hold'a geçer.
"""
import asyncio
import subprocess
import threading
import time
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    from mavsdk import System
    from mavsdk.offboard import OffboardError, VelocityBodyYawspeed


class AracDurumu:
    def __init__(self, arac):
        self.arac = arac
        self.system = None
        self.bagli = False
        self.silahli = False
        self.havada = False
        self.mod = "-"
        self.irtifa_m = None
        self.batarya = None
        self.saglik = False
        self.yer_hizi_ms = None
        self.son_islem = ""
        self.gorevler = []

    def sifirla(self):
        self.system, self.gorevler = None, []
        self.bagli = self.silahli = self.havada = self.saglik = False
        self.mod, self.irtifa_m, self.batarya, self.yer_hizi_ms, self.son_islem = "-", None, None, None, ""

    def sozluk(self):
        return {"no": self.arac.no, "bagli": self.bagli, "silahli": self.silahli, "havada": self.havada, "mod": self.mod,
                "irtifa_m": self.irtifa_m, "batarya": self.batarya, "saglik": self.saglik, "yer_hizi_ms": self.yer_hizi_ms,
                "son_islem": self.son_islem}


class UcusYoneticisi:
    def __init__(self, yap, gunluk_yaz):
        self.yap = yap
        self._yaz = gunluk_yaz
        self.m = yap.ayar["manuel"]
        self.araclar = {a.no: AracDurumu(a) for a in yap.araclar}
        self.manuel_arac = None           # manuel sürülen araç no
        self._eksen = (0.0, 0.0, 0.0, 0.0, 0.0)   # ileri, sağ, yukarı, dönüş, zaman
        self._manuel_gorev = None
        self._dongu = asyncio.new_event_loop()
        threading.Thread(target=self._dongu.run_forever, name="ucus-asyncio", daemon=True).start()
        self._artiklari_temizle()

    def _artiklari_temizle(self):
        """Çöken bir panelden kalmış, panelin KENDİ gRPC portlarındaki mavsdk_server'ları kapatır (projeninkilere dokunmaz)."""
        for d in self.araclar.values():
            subprocess.run(["pkill", "-f", f"mavsdk_server -p {d.arac.grpc_port} "], check=False)

    def baglan(self):
        for d in self.araclar.values():
            if d.system is None:
                asyncio.run_coroutine_threadsafe(self._baglan(d), self._dongu)

    async def _kapat_async(self):
        await self._manuel_bitir_async()
        for d in self.araclar.values():
            for g in d.gorevler:
                g.cancel()
            if d.system is not None:
                try:
                    d.system._stop_mavsdk_server()   # noqa: SLF001 — MAVSDK-Python'da genel kapatma yok
                except Exception:  # noqa: BLE001
                    pass
            d.sifirla()

    def baglantilari_kapat(self):
        try:
            self._calistir(self._kapat_async(), zaman_asimi=15)
        except Exception:  # noqa: BLE001
            pass
        self._artiklari_temizle()

    # ---- bağlantı ve telemetri ---------------------------------------------------------------
    async def _baglan(self, d):
        if d.system is not None:
            return
        s = d.system = System(port=d.arac.grpc_port)
        try:
            await s.connect(system_address=f"udpout://127.0.0.1:{d.arac.gcs_udp_port}")
        except Exception as e:  # noqa: BLE001
            self._yaz(f"(-) İHA{d.arac.no}: mavsdk_server başlatılamadı: {e}")
            d.sifirla()
            return
        akislar = [
            (s.core.connection_state, lambda v: setattr(d, "bagli", v.is_connected)),
            (s.telemetry.armed, lambda v: setattr(d, "silahli", v)),
            (s.telemetry.in_air, lambda v: setattr(d, "havada", v)),
            (s.telemetry.flight_mode, lambda v: setattr(d, "mod", str(v))),
            (s.telemetry.position, lambda v: setattr(d, "irtifa_m", round(v.relative_altitude_m, 1))),
            (s.telemetry.battery, lambda v: setattr(d, "batarya", round(v.remaining_percent, 1))),
            (s.telemetry.health, lambda v: setattr(d, "saglik", bool(v.is_global_position_ok and v.is_home_position_ok))),
            (s.telemetry.velocity_ned, lambda v: setattr(d, "yer_hizi_ms", round((v.north_m_s ** 2 + v.east_m_s ** 2) ** 0.5, 1))),
        ]
        d.gorevler = [asyncio.ensure_future(self._akis(akis, isle)) for akis, isle in akislar]

    @staticmethod
    async def _akis(akis, isle):
        while True:
            try:
                async for v in akis():
                    isle(v)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — bağlantı koptuysa yeniden dene
                await asyncio.sleep(1.0)

    # ---- yardımcılar ---------------------------------------------------------------------------
    def _calistir(self, coro, zaman_asimi=None):
        f = asyncio.run_coroutine_threadsafe(coro, self._dongu)
        return f.result(zaman_asimi) if zaman_asimi else f

    def havada_arac_var(self):
        return any(d.havada for d in self.araclar.values())

    # ---- toplu kalkış / iniş -----------------------------------------------------------------
    async def _kalkis(self, d):
        if not d.bagli:
            d.son_islem = "bağlı değil"
            return
        if d.havada:
            d.son_islem = "zaten havada"
            return
        s = d.system
        d.son_islem = "sağlık bekleniyor"
        son = time.time() + float(self.yap.ayar.get("kalkis_bekleme_sn", 60))
        while not d.saglik and time.time() < son:
            await asyncio.sleep(0.5)
        if not d.saglik:
            d.son_islem = "kalkış reddedildi: konum/ev noktası hazır değil"
            self._yaz(f"(-) İHA{d.arac.no}: {d.son_islem}")
            return
        try:
            await s.action.set_takeoff_altitude(self.yap.kalkis_irtifa_m)
            await s.action.arm()
            await s.action.takeoff()
            d.son_islem = f"kalkış ({self.yap.kalkis_irtifa_m:g} m)"
            self._yaz(f"(+) İHA{d.arac.no}: kalkış komutu kabul edildi ({self.yap.kalkis_irtifa_m:g} m)")
        except Exception as e:  # noqa: BLE001
            d.son_islem = f"kalkış hatası: {e}"
            self._yaz(f"(-) İHA{d.arac.no}: kalkış hatası: {e}")

    async def _inis(self, d):
        if not d.bagli:
            d.son_islem = "bağlı değil"
            return
        if self.manuel_arac == d.arac.no:
            await self._manuel_bitir_async()
        try:
            await d.system.action.land()
            d.son_islem = "iniş"
            self._yaz(f"(+) İHA{d.arac.no}: iniş komutu kabul edildi")
        except Exception as e:  # noqa: BLE001
            d.son_islem = f"iniş hatası: {e}"
            self._yaz(f"(-) İHA{d.arac.no}: iniş hatası: {e}")

    def toplu_kalkis(self):
        bagli = [d for d in self.araclar.values() if d.bagli]
        if not bagli:
            return False, "Bağlı İHA yok; önce sistemi başlatın."
        self._yaz(f"(i) Toplu kalkış: {', '.join(f'İHA{d.arac.no}' for d in bagli)}")
        self._calistir(asyncio.gather(*(self._kalkis(d) for d in bagli)))
        return True, "Toplu kalkış başlatıldı"

    def toplu_inis(self):
        bagli = [d for d in self.araclar.values() if d.bagli]
        if not bagli:
            return False, "Bağlı İHA yok."
        self._yaz("(i) Toplu iniş")
        self._calistir(asyncio.gather(*(self._inis(d) for d in bagli)))
        return True, "Toplu iniş başlatıldı"

    # ---- manuel sürüş --------------------------------------------------------------------------
    async def _manuel_baslat_async(self, no):
        d = self.araclar[no]
        if not d.bagli:
            raise RuntimeError(f"İHA{no} bağlı değil")
        if not d.havada:
            raise RuntimeError(f"İHA{no} havada değil; önce kalkış yapın")
        if self.manuel_arac is not None:
            await self._manuel_bitir_async()
        s = d.system
        await s.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
        try:
            await s.offboard.start()
        except OffboardError as e:
            raise RuntimeError(f"offboard başlatılamadı: {e._result.result}") from e
        self._eksen = (0.0, 0.0, 0.0, 0.0, time.time())
        self.manuel_arac = no
        d.son_islem = "manuel sürüş"
        self._manuel_gorev = asyncio.ensure_future(self._manuel_gonder(d))
        self._yaz(f"(+) İHA{no}: manuel sürüş başladı (offboard)")

    async def _manuel_gonder(self, d):
        aralik = 1.0 / float(self.m["gonderim_hz"])
        while True:
            ileri, sag, yukari, donus, t = self._eksen
            if time.time() - t > float(self.m["komut_zaman_asimi_sn"]):
                ileri = sag = yukari = donus = 0.0
            h, v, r = float(self.m["maks_yatay_hiz_ms"]), float(self.m["maks_dikey_hiz_ms"]), float(self.m["maks_donus_derece_sn"])
            try:
                await d.system.offboard.set_velocity_body(VelocityBodyYawspeed(ileri * h, sag * h, -yukari * v, donus * r))
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(aralik)

    async def _manuel_bitir_async(self):
        no = self.manuel_arac
        if no is None:
            return
        if self._manuel_gorev:
            self._manuel_gorev.cancel()
            self._manuel_gorev = None
        self.manuel_arac = None
        d = self.araclar[no]
        if d.system is None:
            return
        try:
            await d.system.offboard.set_velocity_body(VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
            await d.system.offboard.stop()
        except Exception:  # noqa: BLE001
            pass
        d.son_islem = "manuel bitti (Hold)"
        self._yaz(f"(i) İHA{no}: manuel sürüş bitti")

    def manuel_baslat(self, no):
        if no not in self.araclar:
            return False, f"Geçersiz İHA: {no}"
        try:
            self._calistir(self._manuel_baslat_async(no), zaman_asimi=10)
        except Exception as e:  # noqa: BLE001
            return False, str(e)
        return True, f"İHA{no} manuel sürüşte"

    def manuel_bitir(self):
        self._calistir(self._manuel_bitir_async(), zaman_asimi=10)
        return True, "Manuel sürüş bitti"

    def manuel_eksen(self, ileri, sag, yukari, donus):
        def sinirla(x):
            return max(-1.0, min(1.0, float(x)))
        self._eksen = (sinirla(ileri), sinirla(sag), sinirla(yukari), sinirla(donus), time.time())

    # ---- durum ---------------------------------------------------------------------------------
    def durum(self):
        if self.manuel_arac is not None and not self.araclar[self.manuel_arac].bagli and self._manuel_gorev is not None:
            self._calistir(self._manuel_bitir_async())
        return {"araclar": [d.sozluk() for d in self.araclar.values()], "manuel_arac": self.manuel_arac}
