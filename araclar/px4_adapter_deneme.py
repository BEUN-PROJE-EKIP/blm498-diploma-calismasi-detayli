#!/usr/bin/env python3
"""px4_adapter deneme sürücüsü (geçici: araç süreci gelene kadar bağdaştırıcıyı uçtan uca çalıştırır).

Kullanım:  python araclar/px4_adapter_deneme.py {donusum|kimlik|tam|uc|yetim}
  donusum  SITL gerekmez: ENU↔enlem/boylam gidiş-dönüşü, rota dosyası, rclpy olmadan içe aktarma
  kimlik   yaşayan tek araçlı koşu: yanlış beklenen kimlik reddi (a); görev yüklenmeden başlatma reddi (b)
  tam      yaşayan tek araçlı koşu: araç 1 tam görev (bağlan → kimlik → yükle → indirip karşılaştır → hazırlık (kalkış + ilk nokta) → başlat → son nokta bir kez);
           bağımsız kanıt Gazebo model pozudur (PX4 telemetrisi değil); havadayken yükleme reddi
  uc       yaşayan üç araçlı koşu: üç bağdaştırıcı, üç mavsdk_server, üç rota; eş zamanlı hazırlık (ilk noktada, Gazebo pozu), başlatma, ikinci noktaya varış
  yetim    tek bağdaştırıcı açar, "HAZIR <sunucu pid>" yazıp bekler (testin SIGKILL ile yetim bıraktığı süreç)
Gazebo erişimi için GZ_PARTITION ve GZ_IP ortam değişkenleri koşuya göre verilmelidir (setup/px4_adapter_testi.sh verir).
Her sonuç satırı "SONUC <gecti|kaldi> <ad> | <ayrıntı>" biçimindedir; kaldı varsa çıkış kodu 1.
"""
import math
import os
import subprocess
import sys
import threading
import time

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "src", "swarm_vehicle"))

from swarm_vehicle.ucus import rota  # noqa: E402
from swarm_vehicle.ucus import px4_adapter as pa  # noqa: E402

KALDI = 0
ENV = rota.deney_env_oku()
ROTA_DOSYASI = os.path.join(KOK, "config", "bolge_rota.json")
YAKLASMA_M = 5.0           # kabul ölçütü: rota noktasına yatay yaklaşma (Gazebo pozu)
IRTIFA = float(ENV["ROTA_IRTIFA_M"])
HIZ = float(ENV["ROTA_HIZ_MS"])


def sonuc(gecti, ad, ayrinti):
    global KALDI
    if not gecti:
        KALDI += 1
    print(f"SONUC {'gecti' if gecti else 'kaldi'} {ad} | {ayrinti}", flush=True)


def olcum(ad, ayrinti):
    """Ölçüm/bilgi satırı: geçti/kaldı sayılmaz (test betikleri bilgi olarak yazar)."""
    print(f"OLCUM {ad} | {ayrinti}", flush=True)


class GzPoz:
    """Gazebo dünyasındaki model pozlarını (gz-transport pose/info) dinler; bağımsız doğrulama kaynağıdır."""

    def __init__(self):
        from gz.transport13 import Node
        from gz.msgs10.pose_v_pb2 import Pose_V
        self._kilit = threading.Lock()
        self._poz = {}
        self.sim_sn = None
        self._node = Node()
        dunya = ENV["SIM_WORLD"]
        if not self._node.subscribe(Pose_V, f"/world/{dunya}/pose/info", self._al):
            raise RuntimeError(f"/world/{dunya}/pose/info aboneliği kurulamadı")

    def _al(self, m):
        with self._kilit:
            self.sim_sn = m.header.stamp.sec + m.header.stamp.nsec * 1e-9
            for p in m.pose:
                self._poz[p.name] = (p.position.x, p.position.y, p.position.z)

    def al(self, ad):
        with self._kilit:
            return self._poz.get(ad), self.sim_sn

    def bekle(self, ad, sn=30):
        t = time.monotonic()
        while time.monotonic() - t < sn:
            p, s = self.al(ad)
            if p is not None:
                return p
            time.sleep(0.1)
        raise RuntimeError(f"Gazebo'da '{ad}' modeli görünmedi")


def model_adi(i):
    """PX4 gz betiği model adını '<model>_<örnek>' koyar (örnek = -i değeri, 0 tabanlı)."""
    return f"{ENV['SIM_MODEL'].removeprefix('gz_')}_{i}"


def yatay(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def rota_al(arac_kimligi):
    return rota.rota_oku(ROTA_DOSYASI, arac_kimligi)


def sunucu_dinleyen_port(pid):
    c = subprocess.run(["ss", "-H", "-l", "-n", "-t", "-p"], capture_output=True, text=True, check=False).stdout
    return sorted({s.split()[3] for s in c.splitlines() if f"pid={pid}," in s})


def sunucu_yasiyor(pid):
    return os.path.exists(f"/proc/{pid}")


# ---------------------------------------------------------------------------------------------------------------------------------
def donusum():
    # ENU ↔ coğrafi gidiş-dönüş ve bağımsız (küresel yaklaşım) karşılaştırma
    lat0, lon0 = 47.0, 8.0          # yalnız bu test için örnek çıkış noktası (bağdaştırıcıda sabit koordinat yoktur)
    en_buyuk, en_buyuk_kure = 0.0, 0.0
    for x in (-150, -130.89, -50, 0, 69.11, 150):
        for y in (-150, -135.67, 0, 135.67, 150):
            lat, lon = pa.enu_ofsetini_uygula(lat0, lon0, x, y)
            e, n = pa.enu_ofseti(lat0, lon0, lat, lon)
            en_buyuk = max(en_buyuk, math.hypot(e - x, n - y))
            r = 6371008.8
            ke = math.radians(lon - lon0) * r * math.cos(math.radians(lat0))
            kn = math.radians(lat - lat0) * r
            en_buyuk_kure = max(en_buyuk_kure, math.hypot(ke - x, kn - y))
    sonuc(en_buyuk < 1e-6, "donusum_gidis_donus", f"en büyük gidiş-dönüş hatası {en_buyuk:.2e} m (±150 m aralığı)")
    sonuc(en_buyuk_kure < 0.5, "donusum_kure_karsilastirma", f"WGS84 yerel doğrusal ile küre yaklaşımı farkı ≤ {en_buyuk_kure:.3f} m (sağlama: ölçek doğru)")
    noktalar, bolge = rota_al(int(ENV["UAV_SYS_IDS"].split()[0]))
    sonuc(len(noktalar) >= 2, "rota_okuma", f"araç 1 rotası {len(noktalar)} nokta, bölge {bolge}")
    sonuc("rclpy" not in sys.modules, "rclpy_yok", "px4_adapter ve rota rclpy içe aktarmadan yüklendi")
    modul_mavsdk = sorted(m for m in sys.modules if m == "mavsdk" or m.startswith("mavsdk."))
    sonuc(bool(modul_mavsdk), "mavsdk_yuklu", "mavsdk yalnız px4_adapter üzerinden yüklendi (rota.py içe aktarmaz)")


# ---------------------------------------------------------------------------------------------------------------------------------
def kimlik():
    gz = GzPoz()
    noktalar, bolge = rota_al(int(ENV["UAV_SYS_IDS"].split()[0]))
    # (a) yanlış beklenen kimlik: bağlanır, hiçbir yazma komutu gitmez
    yanlis = int(ENV["UAV_SYS_IDS"].split()[1])
    a = pa.Px4Adapter(1, beklenen_kimlik=yanlis)
    try:
        dogru = a.baglan()
        sonuc(not dogru and not a.kimlik_dogrulandi, "kimlik_a_baglanti",
              f"araç 1 portuna kimlik {yanlis} beklentisiyle bağlandı; kimlik doğrulanmadı (MAV_SYS_ID={a._kimlik_gercek}); sunucu pid {a.sunucu_pid}")
        for ad, islev in (("gorev_yukle", lambda: a.gorev_yukle(noktalar)), ("gorev_baslat", a.gorev_baslat), ("gorev_temizle", a.gorev_temizle)):
            try:
                islev()
                sonuc(False, f"kimlik_a_{ad}", "yanlış kimlikle komut KABUL EDİLDİ")
            except pa.KimlikHatasi as e:
                sonuc(True, f"kimlik_a_{ad}", f"reddedildi (KimlikHatasi): {e}")
        sonuc(a.komut_sayaci == 0, "kimlik_a_komut_sayaci", f"PX4'e giden yazma komutu sayısı = {a.komut_sayaci}")
    finally:
        a.kapat()
    sonuc(not sunucu_yasiyor(a.sunucu_pid), "kimlik_a_sunucu_kapandi", f"mavsdk_server pid {a.sunucu_pid} kapandı")
    # ayrı, doğru kimlikli bağlantıda PX4'teki görev boş
    b = pa.Px4Adapter(1)
    try:
        sonuc(b.baglan(), "kimlik_a_dogru_baglanti", f"doğru kimlikli ayrı bağlantı (kimlik {b.arac_kimligi}) doğrulandı; sunucu pid {b.sunucu_pid}")
        inen = b.gorev_indir()
        sonuc(len(inen) == 0, "kimlik_a_gorev_bos", f"PX4'teki görev öğesi sayısı = {len(inen)} (salt okuma)")
        # (b) görev yüklenmeden başlatma
        try:
            b.gorev_baslat()
            sonuc(False, "kimlik_b_baslat", "görev yüklenmeden gorev_baslat KABUL EDİLDİ")
        except pa.Px4Hatasi as e:
            sonuc(True, "kimlik_b_baslat", f"reddedildi (Px4Hatasi): {e}")
        time.sleep(3)
        d = b.durum()
        p = gz.bekle(model_adi(0))
        sonuc(b.komut_sayaci == 0 and d.get("silahli") is False and not d.get("havada") and p[2] < 1.0, "kimlik_b_arm_yok",
              f"komut sayısı {b.komut_sayaci}, silahli={d.get('silahli')}, havada={d.get('havada')}, Gazebo z={p[2]:.2f} m")
        # (c) görev yüklü ama hazırlık yapılmadı (araç yerde): görev başlatma reddedilir, arm/kalkış yok
        b.gorev_yukle(noktalar)
        sayac = b.komut_sayaci
        try:
            b.gorev_baslat()
            sonuc(False, "kimlik_c_yerde_baslat", "yerdeyken gorev_baslat KABUL EDİLDİ")
        except pa.Px4Hatasi as e:
            time.sleep(2)
            d = b.durum()
            p = gz.al(model_adi(0))[0]
            sonuc(b.komut_sayaci == sayac and d.get("silahli") is False and p[2] < 1.0, "kimlik_c_yerde_baslat",
                  f"görev yüklüyken yerde reddedildi (Px4Hatasi): {e}; komut sayısı {b.komut_sayaci} (yükleme sonrası {sayac}), silahli={d.get('silahli')}, Gazebo z={p[2]:.2f} m")
    finally:
        b.kapat()
    sonuc(not sunucu_yasiyor(b.sunucu_pid), "kimlik_b_sunucu_kapandi", f"mavsdk_server pid {b.sunucu_pid} kapandı")


# ---------------------------------------------------------------------------------------------------------------------------------
def tam():
    gz = GzPoz()
    kimlik0 = int(ENV["UAV_SYS_IDS"].split()[0])
    noktalar, bolge = rota_al(kimlik0)
    uzunluk = sum(math.dist(a, b) for a, b in zip(noktalar, noktalar[1:]))
    model = model_adi(0)
    olaylar = []

    def son_nokta(bilgi):
        p, s = gz.al(model)       # geri çağrı anındaki Gazebo pozu
        olaylar.append({"bilgi": bilgi, "poz": p, "sim_sn": s, "duvar": time.monotonic()})

    a = pa.Px4Adapter(1, son_nokta_geri_cagrisi=son_nokta)
    try:
        t0 = time.monotonic()
        sonuc(a.baglan(), "tam_baglan_kimlik", f"araç {a.arac_kimligi} bağlandı ve kimlik doğrulandı: MAV_SYS_ID={a._kimlik_gercek}, "
              f"UDP {a.udp_port}, gRPC {a.grpc_port}, sunucu pid {a.sunucu_pid} (dinleyen: {sunucu_dinleyen_port(a.sunucu_pid)}); {time.monotonic() - t0:.2f} sn")
        y = a.gorev_yukle(noktalar)
        sonuc(y["oge_sayisi"] == len(noktalar) and y["en_buyuk_sapma_m"] < 0.05, "tam_yukle",
              f"{bolge} rotası {y['oge_sayisi']} öğe yüklendi ve geri indirilip karşılaştırıldı: en büyük sapma {y['en_buyuk_sapma_m'] * 100:.2f} cm; "
              f"yükleme süresi {y['sure_s']:.2f} sn; komut sayısı {a.komut_sayaci}")
        p0 = gz.bekle(model)
        sonuc(p0[2] < 1.0, "tam_kalkis_oncesi", f"yüklemede araç yerde (Gazebo z={p0[2]:.2f} m): rota kalkıştan önce yüklendi")
        try:
            a.gorev_baslat()
            sonuc(False, "tam_yerde_baslat_reddi", "hazırlıksız (yerde) gorev_baslat KABUL EDİLDİ")
        except pa.Px4Hatasi as e:
            sonuc(a.komut_sayaci == 1, "tam_yerde_baslat_reddi", f"yerdeyken reddedildi: {e}; komut sayısı {a.komut_sayaci} (yalnız yükleme)")
        h = a.hazirlik()
        ph = gz.al(model)[0]
        hata_h = yatay(ph, noktalar[0])
        sonuc(hata_h <= YAKLASMA_M and abs(ph[2] - IRTIFA) <= 2.0, "tam_hazirlik",
              f"hazırlık: kalkış {h['kalkis_sure_s']:.1f} sn, ilk noktaya gidiş {h['gidis_sure_s']:.1f} sn, toplam {h['sure_s']:.1f} sn (gerçek); Gazebo pozu: ilk noktaya yatay {hata_h:.2f} m (≤ {YAKLASMA_M:g}), "
              f"yükseklik {ph[2]:.2f} m ({IRTIFA:g} ± 2); komut sayısı {a.komut_sayaci}")
        _, sim0 = gz.al(model)
        b = a.gorev_baslat()
        olcum("tam_baslat", f"görev başlatma (havada, ilk noktada) {b['sure_s']:.2f} sn; komut sayısı {a.komut_sayaci}")
        en_yakin = [1e9] * len(noktalar)
        ilk_varis_sim = None
        ara_varis = set()
        z_enuyuksek = 0.0
        sinir = time.monotonic() + uzunluk / HIZ * 3 + 180
        while not olaylar and time.monotonic() < sinir:
            p, s = gz.al(model)
            if p is not None:
                z_enuyuksek = max(z_enuyuksek, p[2])
                for k, n in enumerate(noktalar):
                    d = yatay(p, n)
                    en_yakin[k] = min(en_yakin[k], d)
                    if d <= YAKLASMA_M and abs(p[2] - IRTIFA) <= 2.0:
                        if k == 0 and ilk_varis_sim is None:
                            ilk_varis_sim = s
                        elif k > 0 and ilk_varis_sim is not None and k < len(noktalar) - 1:
                            ara_varis.add(k)
            time.sleep(0.25)
        sonuc(bool(olaylar), "tam_son_nokta_geldi", f"son nokta bildirimi {'geldi' if olaylar else 'GELMEDİ'} (zaman aşımı {uzunluk / HIZ * 3 + 180:.0f} sn)")
        if olaylar:
            o = olaylar[0]
            hata = yatay(o["poz"], noktalar[-1])
            sure = o["sim_sn"] - sim0
            sonuc(hata <= YAKLASMA_M and abs(o["poz"][2] - IRTIFA) <= 2.0, "tam_son_nokta_gazebo",
                  f"Gazebo pozu: son noktaya yatay hata {hata:.2f} m (≤ {YAKLASMA_M:g}), yükseklik {o['poz'][2]:.2f} m ({IRTIFA:g} ± 2); "
                  f"görev süresi {sure:.1f} sim sn (başlatmadan bildirime); rota uzunluğu {uzunluk:.0f} m; bildirimdeki ilerleme {o['bilgi']['ilerleme']}")
        sonuc(ilk_varis_sim is not None, "tam_ilk_nokta", f"ilk rota noktasında (≤ {YAKLASMA_M:g} m, yükseklik {IRTIFA:g} ± 2) görev başlangıcında: "
              f"{'sim ' + format(ilk_varis_sim - sim0, '.1f') + ' sn sonra tarama noktası 0 görüldü' if ilk_varis_sim is not None else 'GÖRÜLMEDİ'}")
        sonuc(len(ara_varis) >= 1, "tam_ara_nokta", f"ilk varıştan sonra yaklaşılan ara rota noktaları: {sorted(ara_varis)}; her noktaya en yakın yatay uzaklık (m): "
              + ", ".join(f"{k}:{d:.1f}" for k, d in enumerate(en_yakin)))
        time.sleep(10)
        sonuc(a.son_nokta_sayisi == 1 and len(olaylar) == 1, "tam_son_nokta_bir_kez", f"10 sn sonra bildirim sayısı = {len(olaylar)} (bağdaştırıcı sayacı {a.son_nokta_sayisi})")
        # önbellek ile Gazebo'nun karşılaştırması (bilgi; ölçüt değil)
        d = a.durum()
        p, _ = gz.al(model)
        if d.get("konum_enu_m") and p:
            e = d["konum_enu_m"]
            olcum("tam_onbellek_bilgi", f"önbellek konum ENU=({e[0]:.1f}, {e[1]:.1f}, {e[2]:.1f}) PX4 damgası {d['px4_zaman_us']} µs, Gazebo=({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f}); "
                  f"yatay fark {yatay(e, p):.2f} m; ilerleme {d['gorev_ilerleme']}")
        # havadayken yükleme reddi
        sayac = a.komut_sayaci
        try:
            a.gorev_yukle(noktalar)
            sonuc(False, "tam_havada_yukleme_reddi", "araç havadayken yükleme KABUL EDİLDİ")
        except pa.Px4Hatasi as e:
            sonuc(a.komut_sayaci == sayac, "tam_havada_yukleme_reddi", f"reddedildi: {e}; komut sayısı değişmedi ({a.komut_sayaci})")
        pid = a.sunucu_pid
    finally:
        a.kapat()
    sonuc(not sunucu_yasiyor(pid), "tam_kapat", f"kapat() sonrası mavsdk_server pid {pid} yok")


# ---------------------------------------------------------------------------------------------------------------------------------
def uc():
    gz = GzPoz()
    kimlikler = [int(x) for x in ENV["UAV_SYS_IDS"].split()]
    n = len(kimlikler)
    adaptorler = []
    try:
        for i in range(n):
            a = pa.Px4Adapter(i + 1)
            adaptorler.append(a)
            ok = a.baglan()
            sonuc(ok, f"uc_baglan_{i + 1}", f"araç {a.arac_kimligi}: kimlik doğrulandı (MAV_SYS_ID={a._kimlik_gercek}), UDP {a.udp_port}, gRPC {a.grpc_port}, sunucu pid {a.sunucu_pid}")
        pidler = [a.sunucu_pid for a in adaptorler]
        for a in adaptorler:
            dinleyen = sunucu_dinleyen_port(a.sunucu_pid)
            sonuc(any(s.endswith(f":{a.grpc_port}") for s in dinleyen), f"uc_grpc_{a.arac_kimligi}",
                  f"mavsdk_server pid {a.sunucu_pid} kendi gRPC portunda dinliyor: {dinleyen} (beklenen {a.grpc_port})")
        sonuc(len(set(pidler)) == n and len({a.grpc_port for a in adaptorler}) == n, "uc_ayri_sunucu", f"{n} ayrı mavsdk_server: pid {pidler}, gRPC {[a.grpc_port for a in adaptorler]}")
        rotalar = {}
        for a in adaptorler:
            noktalar, bolge = rota_al(a.arac_kimligi)
            y = a.gorev_yukle(noktalar)
            rotalar[a.arac_kimligi] = noktalar
            sonuc(y["oge_sayisi"] == len(noktalar) and y["en_buyuk_sapma_m"] < 0.05, f"uc_yukle_{a.arac_kimligi}",
                  f"{bolge} rotası {y['oge_sayisi']} öğe yüklendi, geri indirilip doğrulandı (en büyük sapma {y['en_buyuk_sapma_m'] * 100:.2f} cm, {y['sure_s']:.2f} sn)")
        modeller = [model_adi(i) for i in range(n)]
        for m in modeller:
            gz.bekle(m)
        # hazırlık evresi: üç araç eş zamanlı (her biri kendi iş parçacığından); en küçük araçlar arası uzaklık izlenir
        sonuclar, hatalar = {}, {}
        en_az_ayrim = 1e9

        def hazirla(a):
            try:
                sonuclar[a.arac_kimligi] = a.hazirlik()
            except Exception as e:  # noqa: BLE001
                hatalar[a.arac_kimligi] = e
        izler = [threading.Thread(target=hazirla, args=(a,)) for a in adaptorler]
        for t in izler:
            t.start()
        while any(t.is_alive() for t in izler):
            pozlar = [gz.al(m)[0] for m in modeller]
            for i in range(n):
                for j in range(i + 1, n):
                    if pozlar[i] and pozlar[j]:
                        en_az_ayrim = min(en_az_ayrim, math.dist(pozlar[i], pozlar[j]))
            time.sleep(0.25)
        for t in izler:
            t.join()
        for i, a in enumerate(adaptorler):
            ph = gz.al(modeller[i])[0]
            h = sonuclar.get(a.arac_kimligi)
            hata = yatay(ph, rotalar[a.arac_kimligi][0])
            sonuc(h is not None and hata <= YAKLASMA_M and abs(ph[2] - IRTIFA) <= 2.0, f"uc_hazirlik_{a.arac_kimligi}",
                  (f"hazırlık {h['sure_s']:.1f} sn (kalkış {h['kalkis_sure_s']:.1f}, gidiş {h['gidis_sure_s']:.1f}); Gazebo: ilk noktaya yatay {hata:.2f} m, yükseklik {ph[2]:.2f} m"
                   if h else f"hazırlık HATA: {hatalar.get(a.arac_kimligi)!r}"))
        sonuc(en_az_ayrim > 1.0, "uc_hazirlik_carpisma_yok", f"hazırlık evresinde araçlar arası en küçük 3B uzaklık {en_az_ayrim:.1f} m (> 1 m)")
        _, sim0 = gz.al(modeller[0])
        for a in adaptorler:
            b = a.gorev_baslat()
            olcum(f"uc_baslat_{a.arac_kimligi}", f"başlatıldı (havada, ilk noktada; {b['sure_s']:.2f} sn)")
        en_yakin = {a.arac_kimligi: 1e9 for a in adaptorler}
        varis = {}
        yere_indi = []
        yukseklik_goruldu = set()
        sinir = time.monotonic() + 300
        while len(varis) < n and time.monotonic() < sinir:
            pozlar = [gz.al(m)[0] for m in modeller]
            _, s = gz.al(modeller[0])
            for i, a in enumerate(adaptorler):
                p = pozlar[i]
                if p is None:
                    continue
                d = yatay(p, rotalar[a.arac_kimligi][1])           # görev akıyor mu: ikinci rota noktası
                en_yakin[a.arac_kimligi] = min(en_yakin[a.arac_kimligi], d)
                if p[2] > IRTIFA - 5:
                    yukseklik_goruldu.add(a.arac_kimligi)
                elif a.arac_kimligi in yukseklik_goruldu and a.arac_kimligi not in yere_indi:
                    yere_indi.append(a.arac_kimligi)
                if d <= YAKLASMA_M and abs(p[2] - IRTIFA) <= 2.0 and a.arac_kimligi not in varis:
                    varis[a.arac_kimligi] = (s - sim0, d, p[2])
            for i in range(n):
                for j in range(i + 1, n):
                    if pozlar[i] and pozlar[j]:
                        en_az_ayrim = min(en_az_ayrim, math.dist(pozlar[i], pozlar[j]))
            time.sleep(0.25)
        for a in adaptorler:
            v = varis.get(a.arac_kimligi)
            sonuc(v is not None, f"uc_ikinci_nokta_{a.arac_kimligi}",
                  (f"görev başlangıcından {v[0]:.1f} sim sn sonra ikinci rota noktasına varış: yatay {v[1]:.2f} m, yükseklik {v[2]:.1f} m (Gazebo)" if v else
                   f"ikinci noktaya varılamadı (en yakın yatay uzaklık {en_yakin[a.arac_kimligi]:.1f} m)"))
        # başlangıç konumları 3 m arayla (UAV_START_POSES); çarpışma ölçütü: hiçbir an iki araç 1 m'den (gövde + pervane açıklığı) yakın olmamalı
        sonuc(en_az_ayrim > 1.0, "uc_carpisma_yok", f"araçlar arası en küçük 3B uzaklık {en_az_ayrim:.1f} m (> 1 m; başlangıç aralığı 3 m, yani yaklaşma olmadı)")
        sonuc(not yere_indi, "uc_beklenmeyen_inis_yok", f"görev sırasında beklenmeyen iniş: {yere_indi or 'yok'}")
    finally:
        for a in adaptorler:
            a.kapat()
    for a in adaptorler:
        sonuc(not sunucu_yasiyor(a.sunucu_pid), f"uc_kapat_{a.arac_kimligi}", f"kapat() sonrası mavsdk_server pid {a.sunucu_pid} yok")


# ---------------------------------------------------------------------------------------------------------------------------------
def yetim():
    a = pa.Px4Adapter(1)
    a.baglan()
    print(f"HAZIR {a.sunucu_pid}", flush=True)
    time.sleep(600)


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else ""
    islev = {"donusum": donusum, "kimlik": kimlik, "tam": tam, "uc": uc, "yetim": yetim}.get(mod)
    if islev is None:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        islev()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sonuc(False, f"{mod}_istisna", f"{type(e).__name__}: {e}")
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(main())
