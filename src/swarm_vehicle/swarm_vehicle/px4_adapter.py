"""px4_adapter: bir aracın PX4 örneğine erişen TEK modül (FR-1, FR-7, FR-8).

Belge (İletişim ve Telemetri Yönetimi): her İHA için ayrı bir MAVSDK System nesnesi ve onun kendi başlattığı mavsdk_server süreci, araca atanan gRPC
portunda; MAVSDK'nın asenkron döngüsü ayrı bir iş parçacığında; kimlik, UDP portu ve gRPC portu config/deney.env'den; bağlantıda beklenen sistem
kimliği doğrulanmadan PX4'e komut verilmez; PX4'e görev komutu yazan tek uygulama px4_adapter'dır (ikinci, çakışan komut yolu yoktur).

Bu dosya, depoda MAVSDK'yı içe aktaran TEK dosyadır. PX4'e yazan her çağrı (görev yükleme/temizleme, arm, görev başlatma) `_yaz` iç yönteminden geçer:
kimlik denetimi + komut sayacı + günlük. Okumalar (parametre okuma, görev indirme, telemetri akışları) `_yaz`'dan geçmez ve komut sayacına girmez.
Tek PX4 parametresi yazımı: kalkış irtifası (MIS_TAKEOFF_ALT, `action.set_takeoff_altitude`), değeri ROTA_IRTIFA_M. rclpy içe aktarılmaz; dışa açık yöntemler eşzamanlıdır ve iş parçacığı güvenlidir (ROS geri çağrısından çağrılabilir).

Yerel ENU çerçevesi planlama/sozlesmeler.md'dedir: orijin alan merkezi (x doğu, y kuzey, z yukarı). [varsayım] Alan merkezi = Gazebo dünya orijini; bu yüzden
aracın başlangıç konumu (UAV_START_POSES) bu çerçevededir. ENU → enlem/boylam dönüşümünün dayanağı çalışma anında elde edilir: PX4 ev konumu (araç başlangıç
konumunda alınır) eksi başlangıç konumunun ENU ofseti = dünya orijininin enlem/boylamı; sabit koordinat yazılmaz.
"""
import asyncio
import concurrent.futures
import datetime
import json
import math
import os
import socket
import threading
import time
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)   # mavsdk paketinin yeniden adlandırma uyarısı (kilitli sürüm kullanılır)

from mavsdk import System  # noqa: E402
from mavsdk.mission import MissionItem, MissionPlan  # noqa: E402

from . import komut_yolu as _komut  # noqa: E402
from . import rota as _rota  # noqa: E402

# WGS84
_A = 6378137.0
_E2 = 0.00669437999014


class KimlikHatasi(RuntimeError):
    """Beklenen sistem kimliği doğrulanamadı; hiçbir komut gönderilmedi."""


class Px4Hatasi(RuntimeError):
    """Bağdaştırıcı işlemi başarısız (zaman aşımı, ön koşul, doğrulama uyuşmazlığı)."""


# --- Coğrafi dönüşüm (WGS84, küçük ofsetler için yerel doğrusal; sabit koordinat yok) ----------------------------------------------------------
def _yaricaplar(enlem_derece):
    s = math.sin(math.radians(enlem_derece))
    w = 1 - _E2 * s * s
    return _A * (1 - _E2) / w ** 1.5, _A / math.sqrt(w)      # meridyen, ana düşey eğrilik yarıçapı


def enu_ofsetini_uygula(enlem0, boylam0, dogu_m, kuzey_m):
    """(enlem0, boylam0) noktasından doğuya/kuzeye ofset: (enlem, boylam) derece."""
    m, n = _yaricaplar(enlem0)
    return (enlem0 + math.degrees(kuzey_m / m),
            boylam0 + math.degrees(dogu_m / (n * math.cos(math.radians(enlem0)))))


def enu_ofseti(enlem0, boylam0, enlem, boylam):
    """(enlem0, boylam0) noktasına göre (doğu_m, kuzey_m)."""
    m, n = _yaricaplar(enlem0)
    return (math.radians(boylam - boylam0) * n * math.cos(math.radians(enlem0)), math.radians(enlem - enlem0) * m)


def _saat_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


class Px4Adapter:
    """Bir aracın PX4 örneğine erişen bağdaştırıcı. `arac_no` 1 tabanlı sıradır (UAV_SYS_IDS içindeki konum), kimlik değildir."""

    def __init__(self, arac_no, deney_env=None, beklenen_kimlik=None, gunluk_dizini=None, son_nokta_geri_cagrisi=None):
        """deney_env: yapılandırma yolu ya da sözlük (öntanımlı config/deney.env). beklenen_kimlik: yalnız kimlik koruması denemesi için
        UAV_SYS_IDS'ten gelen değerin yerine konur. gunluk_dizini: olay günlüğünün yazılacağı klasör (öntanımlı: yaşayan koşunun klasörü;
        yoksa dosyaya yazılmaz). son_nokta_geri_cagrisi: son noktaya ulaşıldığında bir kez çağrılır (bağdaştırıcının döngü iş parçacığında; kısa tutun)."""
        ham = deney_env if isinstance(deney_env, dict) else _rota.deney_env_oku(deney_env)
        liste = lambda k: ham[k].split()  # noqa: E731
        kimlikler, udp, grpc, pozlar = (liste(k) for k in ("UAV_SYS_IDS", "PX4_MAVLINK_PORTS", "MAVSDK_GRPC_PORTS", "UAV_START_POSES"))
        if not (len(kimlikler) == len(udp) == len(grpc) == len(pozlar)):
            raise ValueError("UAV_SYS_IDS, PX4_MAVLINK_PORTS, MAVSDK_GRPC_PORTS, UAV_START_POSES aynı uzunlukta olmalı")
        if not 1 <= arac_no <= len(kimlikler):
            raise ValueError(f"arac_no 1..{len(kimlikler)} olmalı (verilen: {arac_no})")
        i = arac_no - 1
        self.arac_no = arac_no
        self.arac_kimligi = int(kimlikler[i])
        self.beklenen_kimlik = int(beklenen_kimlik) if beklenen_kimlik is not None else self.arac_kimligi
        self.udp_port, self.grpc_port = int(udp[i]), int(grpc[i])
        self._baslangic_poz = tuple(float(v) for v in pozlar[i].split(","))      # (x doğu, y kuzey, z yukarı) m
        self._irtifa, self._hiz = float(ham["ROTA_IRTIFA_M"]), float(ham["ROTA_HIZ_MS"])
        self._baglan_sn, self._komut_sn = float(ham["PX4A_BAGLAN_SN"]), float(ham["PX4A_KOMUT_SN"])
        self._hazir_sn, self._kapat_sn = float(ham["PX4A_HAZIR_SN"]), float(ham["PX4A_KAPAT_SN"])
        self._kabul_m = float(ham["PX4A_KABUL_YARICAPI_M"])
        self._hb_sn, self._baslat_tol = float(ham["PX4A_HEARTBEAT_SN"]), float(ham["PX4A_BASLAT_TOLERANS_M"])
        self._hazirlik_sn, self._yukseklik_tol = float(ham["PX4A_HAZIRLIK_SN"]), float(ham["PX4A_IRTIFA_TOLERANS_M"])
        self._yon_esik, self._yon_hiz_esik, self._yon_sn = float(ham["PX4A_YON_ESIK_DERECE"]), float(ham["PX4A_YON_HIZ_ESIK_MS"]), float(ham["PX4A_YON_SN"])
        self._cb = son_nokta_geri_cagrisi

        self.komut_sayaci = 0                 # PX4'e giden yazma komutu sayısı (yalnız _yaz artırır)
        self.sunucu_pid = None
        self._loop = None
        self._thread = None
        self._sys = None
        self._sunucu = None                   # mavsdk_server süreci (System'in başlattığı)
        self._gorevler = []
        self._islem = None                    # asyncio.Lock: birden çok adımlı işlemler birbirine girmesin
        self._kapandi = False
        self._kilit = threading.Lock()        # durum önbelleği
        self._durum = {}
        self._saglik = None
        self._hb_kimlikleri = set()
        self._kimlik_gercek = None
        self._kimlik_ok = False
        self._origin = None                   # (enlem, boylam): yerel ENU orijini
        self._yuklu = 0                       # PX4'e yüklenip geri indirilerek doğrulanan görev öğesi sayısı
        self._ilk_hedef = None                # rotanın ilk noktası (enlem, boylam)
        self._son_komut_sira = None           # bu araçta görülen en büyük komut sıra numarası (komut yolu iskeleti)
        self._ilk_yon = None                  # ilk tarama doğrusunun yönü (kuzeyden saat yönünde derece); rotadan hesaplanır, yoksa None
        self._hazir_tamam = False             # hazırlık: havada ve ilk noktada
        self._ilerleme = (0, 0)
        self._izle_son = False                # görev başlatıldı, son nokta bekleniyor
        self._ara_gorulen = False
        self.son_nokta_sayisi = 0
        self._gunluk_kilit = threading.Lock()
        self._gunluk_yol = None
        if gunluk_dizini is None:
            aktif = os.path.join(_rota.KOK, ".generated", "kosular", "aktif")
            if os.path.isfile(aktif):
                with open(aktif, encoding="utf-8") as f:
                    gunluk_dizini = os.path.join(_rota.KOK, ".generated", "kosular", f.read().strip())
        if gunluk_dizini and os.path.isdir(gunluk_dizini):
            self._gunluk_yol = os.path.join(gunluk_dizini, f"px4_adapter_{self.arac_kimligi}.log")

    # --- günlük ---------------------------------------------------------------------------------------------------------------------------
    def _gunluk(self, olay, **kv):
        satir = f"{_saat_iso()} {time.monotonic_ns()} {olay}" + "".join(f" {k}={v}" for k, v in kv.items())
        if self._gunluk_yol:
            with self._gunluk_kilit, open(self._gunluk_yol, "a", encoding="utf-8") as f:
                f.write(satir + "\n")

    # --- dışa açık eşzamanlı yöntemler -------------------------------------------------------------------------------------------------------
    def baglan(self):
        """mavsdk_server'ı kendisi başlatır (gRPC: araca atanan port), PX4'e bağlanır ve kimliği doğrular. Kimlik uyuşmazlığında İSTİSNA FIRLATMAZ:
        bağlanır, uyuşmazlığı günlüğe yazar ve False döner; her yazma komutu KimlikHatasi ile reddedilir. Doğrulandıysa True."""
        if self._thread is not None:
            raise Px4Hatasi("bağdaştırıcı zaten başlatıldı")
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", self.grpc_port)) == 0:
                raise Px4Hatasi(f"gRPC portu {self.grpc_port} zaten kullanımda (yetim mavsdk_server olabilir; araclar/kosu.sh temizle)")
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._dongu, name=f"px4_adapter_{self.arac_kimligi}", daemon=True)
        self._thread.start()
        try:
            return self._cagir(self._baglan(), self._baglan_sn * 3 + self._komut_sn * 2)
        except BaseException:
            self.kapat()
            raise

    @property
    def kimlik_dogrulandi(self):
        return self._kimlik_ok

    def kimlik_dogrula(self):
        """Beklenen sistem kimliğini yeniden doğrular (MAV_SYS_ID parametresi + HEARTBEAT kaynağı); uyuşmazsa KimlikHatasi."""
        return self._cagir(self._kimlik_dogrula(), self._komut_sn * 2)

    def gorev_yukle(self, noktalar_enu):
        """Rota noktalarını (yerel ENU [(x, y), ...], m) yerden ROTA_IRTIFA_M yükseklikte görev olarak PX4'e yükler, geri indirip karşılaştırır.
        Araç havadayken reddedilir. Dönen sözlük: oge_sayisi, en_buyuk_sapma_m, sure_s."""
        return self._cagir(self._gorev_yukle(list(noktalar_enu)), self._hazir_sn + self._komut_sn * 5)

    def gorev_indir(self):
        """PX4'teki görevi (yalnız okuma) [{enlem, boylam, goreli_yukseklik_m}, ...] olarak verir."""
        return self._cagir(self._gorev_indir(), self._komut_sn * 2)

    def gorev_temizle(self):
        """PX4'teki görevi siler (yazma komutu)."""
        return self._cagir(self._gorev_temizle(), self._komut_sn * 2)

    def hazirlik(self):
        """Hazırlık evresi (t0'dan ÖNCE; toplam görev süresine girmez): doğrulanmış yüklü görev varsa arm eder, ROTA_IRTIFA_M irtifaya kalkar ve rotanın
        ilk noktasına gider; ilk noktaya PX4A_KABUL_YARICAPI_M içinde ve irtifada (± PX4A_IRTIFA_TOLERANS_M) varınca döner. Dönen sözlük: kalkis_sure_s,
        gidis_sure_s, sure_s. Yüklü görev yoksa, kimlik doğrulanamazsa ya da araç havadaysa reddedilir (arm edilmez)."""
        return self._cagir(self._hazirlik(), self._hazirlik_sn + self._hazir_sn + self._komut_sn * 8)

    def gorev_baslat(self):
        """Görevi başlatır (ilk öğeden). YALNIZ hazırlık tamamlandıysa ve araç havada, ilk noktadayken; yerdeyken reddedilir. Arm/kalkış yapmaz."""
        return self._cagir(self._gorev_baslat(), self._komut_sn * 4)

    def durum(self):
        """Durum önbelleğinin kopyası: araç kimliği, PX4 kaynak damgası (odometri time_usec), konum/yönelim, görev ilerlemesi."""
        with self._kilit:
            d = dict(self._durum)
        d["arac_kimligi"] = self.arac_kimligi
        d["gorev_ilerleme"] = self._ilerleme
        d["yuklu_oge_sayisi"] = self._yuklu
        d["son_nokta_sayisi"] = self.son_nokta_sayisi
        d["komut_sayaci"] = self.komut_sayaci
        return d

    def kapat(self):
        """Akışları, döngü iş parçacığını ve mavsdk_server sürecini kapatır (önce SIGTERM, PX4A_KAPAT_SN dolarsa SIGKILL). Tekrar çağrılabilir."""
        if self._kapandi:
            return
        self._kapandi = True
        self._gunluk("kapanis_basladi", sunucu_pid=self.sunucu_pid)
        if self._loop is not None and self._thread is not None and self._thread.is_alive():
            try:
                asyncio.run_coroutine_threadsafe(self._akislari_kapat(), self._loop).result(10)
            except Exception as e:  # noqa: BLE001
                self._gunluk("kapanis_uyari", ayrinti=repr(e))
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(10)
        if self._loop is not None and not self._loop.is_running():
            self._loop.close()
        kod = self._sunucuyu_kapat()
        self._gunluk("kapanis", sunucu_pid=self.sunucu_pid, sunucu_cikis=kod, komut_sayaci=self.komut_sayaci)

    def __enter__(self):
        self.baglan()
        return self

    def __exit__(self, *_):
        self.kapat()

    # --- iç: iş parçacığı ve süreç ----------------------------------------------------------------------------------------------------------
    def _dongu(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _cagir(self, coro, zaman_asimi):
        if self._loop is None or self._kapandi:
            coro.close()
            raise Px4Hatasi("bağdaştırıcı bağlı değil ya da kapatıldı")
        if threading.current_thread() is self._thread:
            coro.close()
            raise Px4Hatasi("eşzamanlı yöntem bağdaştırıcının kendi döngü iş parçacığından çağrılamaz")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(zaman_asimi)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise Px4Hatasi(f"işlem {zaman_asimi:g} sn içinde bitmedi") from None

    def _sunucuyu_kapat(self):
        p = self._sunucu
        if p is None:
            return None
        kod = p.poll()
        if kod is None:
            p.terminate()
            try:
                kod = p.wait(self._kapat_sn)
            except Exception:  # noqa: BLE001  (zaman aşımı)
                self._gunluk("sunucu_sigkill", pid=p.pid)
                p.kill()
                kod = p.wait(5)
        return kod

    async def _akislari_kapat(self):
        for g in self._gorevler:
            g.cancel()
        await asyncio.gather(*self._gorevler, return_exceptions=True)
        self._gorevler = []

    # --- iç: bağlantı ve akışlar ------------------------------------------------------------------------------------------------------------
    async def _ilk(self, akis, sn):
        async def al():
            async for x in akis:
                return x
        return await asyncio.wait_for(al(), sn)

    async def _baglan(self):
        self._islem = asyncio.Lock()
        self._sys = System(port=self.grpc_port)           # adres verilmez: System kendi mavsdk_server sürecini bu portta başlatır
        await asyncio.wait_for(self._sys.connect(system_address=f"udpin://127.0.0.1:{self.udp_port}"), self._baglan_sn)
        self._sunucu = self._sys._server_process
        self.sunucu_pid = self._sunucu.pid
        self._gunluk("sunucu", pid=self.sunucu_pid, grpc_port=self.grpc_port, udp_port=self.udp_port)

        async def baglandi():
            async for st in self._sys.core.connection_state():
                if st.is_connected:
                    return
        await asyncio.wait_for(baglandi(), self._baglan_sn)
        self._gunluk("baglanti", udp_port=self.udp_port)
        self._gorevler = [
            asyncio.create_task(self._akis("heartbeat", self._sys.mavlink_direct.message("HEARTBEAT"), self._hb_isle)),
            asyncio.create_task(self._akis("odometri", self._sys.telemetry.odometry(), self._odometri_isle)),
            asyncio.create_task(self._akis("konum", self._sys.telemetry.position(), self._konum_isle)),
            asyncio.create_task(self._akis("saglik", self._sys.telemetry.health(), self._saglik_isle)),
            asyncio.create_task(self._akis("silahli", self._sys.telemetry.armed(), self._silahli_isle)),
            asyncio.create_task(self._akis("havada", self._sys.telemetry.in_air(), self._havada_isle)),
            asyncio.create_task(self._akis("gorev_ilerleme", self._sys.mission.mission_progress(), self._ilerleme_isle)),
        ]
        sinir = time.monotonic() + self._hb_sn
        while not self._hb_kimlikleri and time.monotonic() < sinir:
            await asyncio.sleep(0.1)
        if not self._hb_kimlikleri:
            self._gunluk("kimlik_uyari", ayrinti="HEARTBEAT kaynak kimliği okunamadı; yalnız MAV_SYS_ID parametresi karşılaştırılır")
        try:
            await self._kimlik_dogrula()
            return True
        except KimlikHatasi:
            return False

    async def _akis(self, ad, akis, isle):
        try:
            async for x in akis:
                isle(x)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self._gunluk("akis_hatasi", ad=ad, hata=repr(e))

    def _hb_isle(self, m):
        self._hb_kimlikleri.add(int(m.system_id))

    def _odometri_isle(self, o):
        n, e, d = o.position_body.x_m, o.position_body.y_m, o.position_body.z_m          # yerel NED (PX4 yerel orijini: araç ev konumu)
        x0, y0, z0 = self._baslangic_poz
        with self._kilit:
            self._durum.update(
                px4_zaman_us=int(o.time_usec), alinma_ns=time.monotonic_ns(),
                konum_ned_m=(n, e, d), konum_enu_m=(x0 + e, y0 + n, z0 - d),
                yonelim_q_wxyz=(o.q.w, o.q.x, o.q.y, o.q.z),
                yatay_hiz_ms=math.hypot(o.velocity_body.x_m_s, o.velocity_body.y_m_s))

    def _konum_isle(self, p):
        with self._kilit:
            self._durum.update(enlem_derece=p.latitude_deg, boylam_derece=p.longitude_deg, goreli_yukseklik_m=p.relative_altitude_m,
                               mutlak_yukseklik_m=p.absolute_altitude_m,
                               gnss_alinma_ns=time.monotonic_ns())

    def _saglik_isle(self, h):
        self._saglik = h

    def _silahli_isle(self, v):
        with self._kilit:
            self._durum["silahli"] = bool(v)

    def _havada_isle(self, v):
        with self._kilit:
            self._durum["havada"] = bool(v)

    def _ilerleme_isle(self, pr):
        self._ilerleme = (pr.current, pr.total)
        if not self._izle_son:
            return
        if pr.current < pr.total:
            self._ara_gorulen = True
        elif pr.total == self._yuklu and pr.total > 0 and self._ara_gorulen:
            self._izle_son = False
            self.son_nokta_sayisi += 1
            with self._kilit:
                px4_us = self._durum.get("px4_zaman_us")
            self._gunluk("son_nokta", ilerleme=f"{pr.current}/{pr.total}", px4_zaman_us=px4_us)
            if self._cb is not None:
                try:
                    self._cb({"arac_kimligi": self.arac_kimligi, "ilerleme": (pr.current, pr.total), "px4_zaman_us": px4_us,
                              "monotonik_ns": time.monotonic_ns()})
                except Exception as e:  # noqa: BLE001
                    self._gunluk("geri_cagri_hatasi", hata=repr(e))

    # --- komut yolu iskeleti ------------------------------------------------------------------------------------------------------------------
    def komut_isle(self, vehicle_id, sequence):
        """Yer istasyonundan araç komut konusuyla gelen komutun denetimi (komut yolu: swarm_gcs → araç komut konusu → px4_adapter). Belge komut türlerini tanımlamaz; kullanıcı kararı gereği yeni tür
        uydurulmaz ve PX4'e HİÇBİR ŞEY YAZILMAZ: bu yöntem `_yaz` çağırmaz, komut sayacını artırmaz. Araç kimliği ve sıra numarası denetlenir (yanlış araç, tekrar ya da geriye giden sıra reddedilir);
        denetimi geçen komut da ACK_REJECTED döner (neden: komut türü belgede tanımlı değil). Dönen: (ack_state, neden). Neden `komut_reddedildi` olayıyla günlüğe yazılır (`_yaz`'ın `komut` olayı değildir)."""
        with self._kilit:
            ack, neden, self._son_komut_sira = _komut.denetle(self.arac_kimligi, vehicle_id, sequence, self._son_komut_sira)
        self._gunluk("komut_reddedildi", vehicle_id=int(vehicle_id), sequence=int(sequence), ack="ACK_REJECTED", neden=neden)
        return ack, neden

    # --- iç: kimlik ve TEK komut yolu -------------------------------------------------------------------------------------------------------
    async def _kimlik_dogrula(self):
        gercek = await asyncio.wait_for(self._sys.param.get_param_int("MAV_SYS_ID"), self._komut_sn)
        hb = set(self._hb_kimlikleri)
        self._kimlik_gercek = gercek
        self._kimlik_ok = gercek == self.beklenen_kimlik and hb <= {self.beklenen_kimlik}
        if self._kimlik_ok:
            self._gunluk("kimlik", sonuc="dogrulandi", beklenen=self.beklenen_kimlik, mav_sys_id=gercek, heartbeat=sorted(hb) or "okunamadi")
            return
        self._gunluk("kimlik", sonuc="UYUSMUYOR", beklenen=self.beklenen_kimlik, mav_sys_id=gercek, heartbeat=sorted(hb))
        raise KimlikHatasi(f"beklenen sistem kimliği {self.beklenen_kimlik}; bağlı sistem: MAV_SYS_ID={gercek}, HEARTBEAT kaynakları={sorted(hb)}")

    async def _yaz(self, ad, islev, *arg):
        """PX4'e yazan TEK yol: kimlik denetimi (uyuşmazsa istisna, komut gönderilmez) + sayaç + günlük."""
        await self._kimlik_dogrula()
        self.komut_sayaci += 1
        self._gunluk("komut", ad=ad, no=self.komut_sayaci)
        try:
            return await asyncio.wait_for(islev(*arg), self._komut_sn)
        except Exception as e:  # noqa: BLE001
            self._gunluk("komut_hatasi", ad=ad, hata=repr(e))
            raise

    # --- iç: görev ----------------------------------------------------------------------------------------------------------------------------
    async def _origin_hazirla(self):
        if self._origin is not None:
            return
        ev = await self._ilk(self._sys.telemetry.home(), self._hazir_sn)
        x0, y0, _ = self._baslangic_poz
        # ev konumu = aracın başlangıç konumu; dünya orijini (yerel ENU orijini) = ev konumu − başlangıç ofseti
        self._origin = enu_ofsetini_uygula(ev.latitude_deg, ev.longitude_deg, -x0, -y0)
        self._gunluk("origin", ev_enlem=ev.latitude_deg, ev_boylam=ev.longitude_deg, baslangic_poz=self._baslangic_poz,
                     origin_enlem=f"{self._origin[0]:.9f}", origin_boylam=f"{self._origin[1]:.9f}")

    def enu_den_cografi(self, x, y):
        """Yerel ENU (x doğu, y kuzey, m) → (enlem, boylam) derece; dayanak ev konumu (görev yüklenirken elde edilir)."""
        if self._origin is None:
            raise Px4Hatasi("ENU orijini henüz elde edilmedi (gorev_yukle ile elde edilir)")
        return enu_ofsetini_uygula(self._origin[0], self._origin[1], x, y)

    async def _havada(self):
        return bool(await self._ilk(self._sys.telemetry.in_air(), self._komut_sn))

    async def _gorev_yukle(self, noktalar):
        if not noktalar:
            raise ValueError("rota boş")
        async with self._islem:
            await self._kimlik_dogrula()                      # uyuşmazsa buradan çıkılır: hiçbir komut gönderilmez
            if await self._havada():
                raise Px4Hatasi("araç havada: rota kalkıştan önce yüklenir, yükleme reddedildi")
            t0 = time.monotonic()
            await self._origin_hazirla()
            nan = float("nan")
            ogeler, hedef = [], []
            for x, y in noktalar:
                lat, lon = self.enu_den_cografi(x, y)
                hedef.append((lat, lon))
                ogeler.append(MissionItem(lat, lon, self._irtifa, self._hiz, False, nan, nan, MissionItem.CameraAction.NONE, nan, nan,
                                          self._kabul_m, nan, nan, MissionItem.VehicleAction.NONE))
            self._yuklu = 0
            await self._yaz("mission.upload", self._sys.mission.upload_mission, MissionPlan(ogeler))
            inen = await self._gorev_indir()
            if len(inen) != len(ogeler):
                raise Px4Hatasi(f"görev yüklendi ama geri indirilen öğe sayısı uyuşmuyor: yüklenen {len(ogeler)}, indirilen {len(inen)}")
            en_buyuk = 0.0
            for k, ((lat, lon), g) in enumerate(zip(hedef, inen)):
                de, dn = enu_ofseti(lat, lon, g["enlem"], g["boylam"])
                sapma = math.hypot(de, dn)
                en_buyuk = max(en_buyuk, sapma)
                if sapma > 0.05 or abs(g["goreli_yukseklik_m"] - self._irtifa) > 0.01:
                    raise Px4Hatasi(f"görev öğesi {k} uyuşmuyor: yatay sapma {sapma:.3f} m, yükseklik {g['goreli_yukseklik_m']:.2f} m (beklenen {self._irtifa:g})")
            self._yuklu = len(ogeler)
            self._ilk_hedef = hedef[0]
            self._ilk_yon = _rota.ilk_dogru_yonu_derece(noktalar)
            self._hazir_tamam = False
            sure = time.monotonic() - t0
            self._gunluk("yukleme", oge_sayisi=len(ogeler), en_buyuk_sapma_m=f"{en_buyuk:.4f}", sure_s=f"{sure:.3f}")
            return {"oge_sayisi": len(ogeler), "en_buyuk_sapma_m": en_buyuk, "sure_s": sure}

    async def _gorev_indir(self):
        plan = await asyncio.wait_for(self._sys.mission.download_mission(), self._komut_sn)
        return [{"enlem": o.latitude_deg, "boylam": o.longitude_deg, "goreli_yukseklik_m": o.relative_altitude_m} for o in plan.mission_items]

    async def _gorev_temizle(self):
        async with self._islem:
            await self._yaz("mission.clear", self._sys.mission.clear_mission)
            self._yuklu = 0
            self._hazir_tamam = False

    def _ilk_noktaya_uzaklik(self):
        """Önbellekteki GNSS konumundan ilk rota noktasına (yatay m, yükseklik farkı m); konum yoksa None."""
        with self._kilit:
            lat, lon, yuk = (self._durum.get(k) for k in ("enlem_derece", "boylam_derece", "goreli_yukseklik_m"))
        if lat is None or self._ilk_hedef is None:
            return None
        de, dn = enu_ofseti(self._ilk_hedef[0], self._ilk_hedef[1], lat, lon)
        return math.hypot(de, dn), yuk - self._irtifa

    async def _hazirlik(self):
        async with self._islem:
            await self._kimlik_dogrula()
            if self._yuklu <= 0 or self._ilk_hedef is None:
                raise Px4Hatasi("doğrulanmış yüklü görev yok: hazırlık reddedildi (arm edilmedi)")
            if await self._havada():
                raise Px4Hatasi("araç zaten havada: hazırlık reddedildi")
            t0 = time.monotonic()
            sinir = t0 + self._hazir_sn
            while not (self._saglik is not None and self._saglik.is_armable):
                if time.monotonic() > sinir:
                    raise Px4Hatasi(f"araç {self._hazir_sn:g} sn içinde arm edilebilir olmadı (sağlık: {self._saglik})")
                await asyncio.sleep(0.2)
            sinir = time.monotonic() + self._hazirlik_sn
            await self._yaz("action.set_takeoff_altitude", self._sys.action.set_takeoff_altitude, self._irtifa)
            await self._yaz("action.arm", self._sys.action.arm)
            await self._yaz("action.takeoff", self._sys.action.takeoff)
            while True:                                                   # kalkış: irtifaya yaklaşana dek
                with self._kilit:
                    yuk = self._durum.get("goreli_yukseklik_m")
                if yuk is not None and yuk >= self._irtifa - self._yukseklik_tol:
                    break
                if time.monotonic() > sinir:
                    raise Px4Hatasi(f"kalkış {self._hazirlik_sn:g} sn içinde bitmedi (yükseklik {yuk})")
                await asyncio.sleep(0.2)
            t_kalkis = time.monotonic()
            with self._kilit:
                zemin_mutlak = self._durum["mutlak_yukseklik_m"] - self._durum["goreli_yukseklik_m"]
            await self._yaz("action.goto_location", self._sys.action.goto_location, self._ilk_hedef[0], self._ilk_hedef[1], zemin_mutlak + self._irtifa, float("nan"))
            while True:                                                   # ilk noktaya gidiş
                u = self._ilk_noktaya_uzaklik()
                if u is not None and u[0] <= self._kabul_m and abs(u[1]) <= self._yukseklik_tol:
                    break
                if time.monotonic() > sinir:
                    raise Px4Hatasi(f"ilk noktaya varılamadı ({self._hazirlik_sn:g} sn); son uzaklık {u}")
                await asyncio.sleep(0.2)
            t_varis = time.monotonic()
            await self._ilk_yone_don(zemin_mutlak)
            self._hazir_tamam = True
            t1 = time.monotonic()
            self._gunluk("hazirlik", kalkis_sure_s=f"{t_kalkis - t0:.2f}", gidis_sure_s=f"{t_varis - t_kalkis:.2f}", donus_sure_s=f"{t1 - t_varis:.2f}", sure_s=f"{t1 - t0:.2f}")
            return {"kalkis_sure_s": t_kalkis - t0, "gidis_sure_s": t_varis - t_kalkis, "donus_sure_s": t1 - t_varis, "sure_s": t1 - t0}

    async def _ilk_yone_don(self, zemin_mutlak):
        """İlk noktada konum tutarak ilk tarama doğrusunun yönüne döner (görev başlamadan önce, hazırlık evresinde). Yaw, görev öğesine yazılmaz: aynı noktaya yaw'lı bir
        goto_location (`_yaz` üzerinden) verilir. Yatay hız ve yaw farkı eşiklerin altına inince biter; PX4A_YON_SN aşılırsa hata (görev başlatılmaz)."""
        if self._ilk_yon is None:
            self._gunluk("yon_donusu", durum="atlandi", neden="rotada_ilk_bacak_yok")
            return
        t0 = time.monotonic()
        await self._yaz("action.goto_location", self._sys.action.goto_location, self._ilk_hedef[0], self._ilk_hedef[1], zemin_mutlak + self._irtifa, self._ilk_yon)
        sinir = t0 + self._yon_sn
        fark = hiz = None
        while True:
            with self._kilit:
                q, hiz = self._durum.get("yonelim_q_wxyz"), self._durum.get("yatay_hiz_ms")
            if q is not None and hiz is not None:
                fark = _rota.aci_farki_derece(_rota.yaw_ned_derece(q), self._ilk_yon)
                if abs(fark) <= self._yon_esik and hiz <= self._yon_hiz_esik:
                    self._gunluk("yon_donusu", durum="tamam", hedef_derece=f"{self._ilk_yon:.2f}", son_fark_derece=f"{fark:.2f}", yatay_hiz_ms=f"{hiz:.3f}", sure_s=f"{time.monotonic() - t0:.2f}")
                    return
            if time.monotonic() > sinir:
                raise Px4Hatasi(f"ilk doğru yönüne ({self._ilk_yon:.1f}°) {self._yon_sn:g} sn içinde dönülemedi (son yaw farkı {fark}°, yatay hız {hiz} m/s)")
            await asyncio.sleep(0.1)

    async def _gorev_baslat(self):
        async with self._islem:
            await self._kimlik_dogrula()
            if self._yuklu <= 0:
                raise Px4Hatasi("doğrulanmış yüklü görev yok: görev başlatma reddedildi")
            if not self._hazir_tamam or not await self._havada():
                raise Px4Hatasi("hazırlık tamamlanmadı ya da araç yerde: görev başlatma reddedildi (arm/kalkış yapılmaz)")
            u = self._ilk_noktaya_uzaklik()
            if u is None or u[0] > self._kabul_m + self._baslat_tol or abs(u[1]) > self._yukseklik_tol + self._baslat_tol:
                raise Px4Hatasi(f"araç ilk noktada değil (uzaklık/yükseklik farkı {u}): görev başlatma reddedildi")
            t0 = time.monotonic()
            self._ara_gorulen = self._ilerleme[0] < self._ilerleme[1]
            self._izle_son = True
            try:
                await self._yaz("mission.start", self._sys.mission.start_mission)
            except BaseException:
                self._izle_son = False
                raise
            sure = time.monotonic() - t0
            self._gunluk("baslatma", sure_s=f"{sure:.3f}", oge_sayisi=self._yuklu)
            return {"sure_s": sure}
