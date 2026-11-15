#!/usr/bin/env python3
"""Sözleşme dosyası doğrulayıcı: sahne, bölge/rota, kamera kalibrasyonu, hedef listesi, koşu üst verisi (JSON), kare olay kaydı, araç durum kaydı, kare sonucu ve işçi kaynak kaydı (JSON Lines).

Kullanım:
  sozlesme_dogrula.py [--yapilandirma config/deney.env] <dosya.json> [--sahne sahne.json]
  sozlesme_dogrula.py [--yapilandirma ...] --hedef-listesi-uret <sahne.json>
Dosya türü dosyadaki "tur" alanından anlaşılır (sahne | bolge_rota | kamera_kalibrasyon | hedef_listesi | kosu_ustveri | nihai_rapor | kosu_olcum | sayac_kaydi).
Uzantısı .jsonl olan dosya JSON Lines'tır (satır başına bir JSON nesnesi): tur: kare_olay (öntanımlı), arac_durum_kaydi, kare_sonuc, isci_kaynak, gorev_olay, telemetri ya da kare_poz (ilk dolu satırdan anlaşılır).
--sahne yalnız hedef_listesi için: listenin verilen sahnedeki hedeflerle birebir aynı olduğu da denetlenir.
Çıkış: 0 geçerli, 1 geçersiz (Türkçe, alan yoluyla "nokta nokta" hata listesi), 2 kullanım/okuma hatası.
Yalnız standart kitaplık kullanılır. Eşikler ve aralıklar config/deney.env'den okunur (tek kaynak); biçimler planlama/sozlesmeler.md'dedir.
"""
import json
import math
import re
import sys

SURUM = 1
KIMLIK_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ---------------------------------------------------------------------------------------------------------------------------------
# Yapılandırma (config/deney.env: KEY="değer" satırları)
# ---------------------------------------------------------------------------------------------------------------------------------
def yapilandirma_yukle(yol):
    veri = {}
    with open(yol, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            m = re.match(r'^([A-Z][A-Z0-9_]*)=(?:"([^"]*)"|(\S*))', ln)
            if m:
                veri[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return veri


class Yapilandirma:
    GEREKLI = (
        "ALAN_MERKEZ_X_M ALAN_MERKEZ_Y_M ALAN_GENISLIK_M ALAN_YUKSEKLIK_M ALAN_KENAR_PAYI_M ALAN_BOLGE_SAYISI ROTA_IRTIFA_M ROTA_ORTUSME_MIN_M ROTA_HIZ_MS "
        "SAHNE_BOLUMLER SAHNE_SINIFLAR SAHNE_TEST_INSAN SAHNE_TEST_ENKAZ SAHNE_MERKEZ_MESAFE_TEST_M SAHNE_MERKEZ_MESAFE_DIGER_M SAHNE_DIGER_HEDEF_MAKS "
        "SAHNE_INSAN_VARYANTLARI SAHNE_ENKAZ_VARYANTLARI SAHNE_TEST_OZEL_INSAN SAHNE_TEST_OZEL_ENKAZ SAHNE_ZEMIN_VARYANTLARI "
        "SAHNE_GUNES_YUKSEKLIK_MIN_DERECE SAHNE_GUNES_YUKSEKLIK_MAKS_DERECE KAL_KAMERA_KONUM_Z_M CAM_WIDTH CAM_HEIGHT CAM_HFOV_DEG CAM_HFOV_RAD UAV_SYS_IDS "
        "CAM_RATE_HZ KOSU_MIMARILER MODEL_SINIFLAR INF_CONF INF_MAX_DET BIRLESTIRME_ARALIK_M POZ_ARALIK_SINIR_MS"
    ).split()

    def __init__(self, ham):
        eksik = [k for k in self.GEREKLI if k not in ham]
        if eksik:
            raise ValueError("yapılandırmada eksik anahtar: " + ", ".join(eksik))
        self.h = ham
        f = float
        self.merkez = (f(ham["ALAN_MERKEZ_X_M"]), f(ham["ALAN_MERKEZ_Y_M"]))
        self.genislik, self.yukseklik = f(ham["ALAN_GENISLIK_M"]), f(ham["ALAN_YUKSEKLIK_M"])
        self.kenar_payi = f(ham["ALAN_KENAR_PAYI_M"])
        self.bolge_sayisi = int(ham["ALAN_BOLGE_SAYISI"])
        self.irtifa, self.ortusme_min, self.hiz = f(ham["ROTA_IRTIFA_M"]), f(ham["ROTA_ORTUSME_MIN_M"]), f(ham["ROTA_HIZ_MS"])
        self.bolumler = ham["SAHNE_BOLUMLER"].split()
        self.siniflar = ham["SAHNE_SINIFLAR"].split()
        self.test_sayi = {"insan": int(ham["SAHNE_TEST_INSAN"]), "enkaz": int(ham["SAHNE_TEST_ENKAZ"])}
        self.mesafe_test, self.mesafe_diger = f(ham["SAHNE_MERKEZ_MESAFE_TEST_M"]), f(ham["SAHNE_MERKEZ_MESAFE_DIGER_M"])
        self.diger_maks = int(ham["SAHNE_DIGER_HEDEF_MAKS"])
        self.varyant = {"insan": ham["SAHNE_INSAN_VARYANTLARI"].split(), "enkaz": ham["SAHNE_ENKAZ_VARYANTLARI"].split()}
        self.test_ozel = {"insan": ham["SAHNE_TEST_OZEL_INSAN"].split(), "enkaz": ham["SAHNE_TEST_OZEL_ENKAZ"].split()}
        self.zemin = ham["SAHNE_ZEMIN_VARYANTLARI"].split()
        self.gunes_min, self.gunes_maks = f(ham["SAHNE_GUNES_YUKSEKLIK_MIN_DERECE"]), f(ham["SAHNE_GUNES_YUKSEKLIK_MAKS_DERECE"])
        self.kal_z = f(ham["KAL_KAMERA_KONUM_Z_M"])
        self.w_px, self.h_px = int(ham["CAM_WIDTH"]), int(ham["CAM_HEIGHT"])
        self.hfov_deg, self.hfov_rad = f(ham["CAM_HFOV_DEG"]), f(ham["CAM_HFOV_RAD"])
        self.arac_kimlikleri = [int(x) for x in ham["UAV_SYS_IDS"].split()]
        self.kamera_hz = f(ham["CAM_RATE_HZ"])
        self.mimariler = ham["KOSU_MIMARILER"].split()
        self.model_siniflari = ham["MODEL_SINIFLAR"].split()
        self.guven_esigi, self.max_det = f(ham["INF_CONF"]), int(ham["INF_MAX_DET"])
        self.birlestirme_aralik = f(ham["BIRLESTIRME_ARALIK_M"])
        self.poz_aralik_sinir_ms = f(ham["POZ_ARALIK_SINIR_MS"])

    @property
    def x_aralik(self):
        return self.merkez[0] - self.genislik / 2, self.merkez[0] + self.genislik / 2

    @property
    def y_aralik(self):
        return self.merkez[1] - self.yukseklik / 2, self.merkez[1] + self.yukseklik / 2

    @property
    def iz_genisligi(self):
        return 2 * self.irtifa * math.tan(self.hfov_rad / 2)


# ---------------------------------------------------------------------------------------------------------------------------------
# Hata biriktirici ve tür denetim yardımcıları
# ---------------------------------------------------------------------------------------------------------------------------------
class Hatalar:
    def __init__(self):
        self.liste = []

    def ekle(self, yol, ileti):
        self.liste.append(f"{yol}: {ileti}")


def sayi_mi(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def tam_sayi_mi(v):
    return isinstance(v, int) and not isinstance(v, bool)


def alan_denetle(h, yol, d, zorunlu, istege_bagli=()):
    """Sözlük mü, zorunlu alanlar var mı, bilinmeyen alan yok mu? Sözlük değilse False döner."""
    if not isinstance(d, dict):
        h.ekle(yol, "nesne (sözlük) olmalı")
        return False
    for k in zorunlu:
        if k not in d:
            h.ekle(f"{yol}.{k}" if yol else k, "zorunlu alan eksik")
    for k in d:
        if k not in zorunlu and k not in istege_bagli:
            h.ekle(f"{yol}.{k}" if yol else k, "bilinmeyen alan")
    return True


def alan_sinirlari_denetle(h, c, yol, a):
    """Dosyadaki alan tanımı yapılandırmadaki alanla birebir aynı olmalı (tüm sahnelerde aynı alan)."""
    if not alan_denetle(h, yol, a, ["cerceve", "merkez_m", "genislik_m", "yukseklik_m"]):
        return
    if a.get("cerceve") != "yerel_ENU":
        h.ekle(f"{yol}.cerceve", f"'yerel_ENU' olmalı (bulunan: {a.get('cerceve')!r})")
    m = a.get("merkez_m")
    if not (isinstance(m, list) and len(m) == 2 and all(sayi_mi(x) for x in m)):
        h.ekle(f"{yol}.merkez_m", "[x, y] iki sayı olmalı")
    elif abs(m[0] - c.merkez[0]) > 1e-9 or abs(m[1] - c.merkez[1]) > 1e-9:
        h.ekle(f"{yol}.merkez_m", f"yapılandırmadaki alan merkeziyle ({c.merkez[0]:g}, {c.merkez[1]:g}) aynı olmalı (bulunan: {m})")
    for k, beklenen in (("genislik_m", c.genislik), ("yukseklik_m", c.yukseklik)):
        v = a.get(k)
        if not sayi_mi(v):
            h.ekle(f"{yol}.{k}", "sayı olmalı")
        elif abs(v - beklenen) > 1e-9:
            h.ekle(f"{yol}.{k}", f"yapılandırmadaki alanla ({beklenen:g} m) aynı olmalı (bulunan: {v:g})")


def ust_alanlar(h, d, tur):
    if d.get("surum") != SURUM:
        h.ekle("surum", f"{SURUM} olmalı (bulunan: {d.get('surum')!r})")
    if d.get("tur") != tur:
        h.ekle("tur", f"'{tur}' olmalı (bulunan: {d.get('tur')!r})")


# ---------------------------------------------------------------------------------------------------------------------------------
# Sahne
# ---------------------------------------------------------------------------------------------------------------------------------
def dogrula_sahne(c, d):
    h = Hatalar()
    if not alan_denetle(h, "", d, ["surum", "tur", "sahne_kimligi", "bolum", "tohum", "alan", "isik", "zemin", "hedefler"]):
        return h.liste
    ust_alanlar(h, d, "sahne")
    kimlik = d.get("sahne_kimligi")
    if not (isinstance(kimlik, str) and KIMLIK_RE.match(kimlik)):
        h.ekle("sahne_kimligi", "1-64 karakter, yalnız harf/rakam/_/- olmalı")
    bolum = d.get("bolum")
    if bolum not in c.bolumler:
        h.ekle("bolum", f"{c.bolumler} değerlerinden biri olmalı (bulunan: {bolum!r})")
    if not tam_sayi_mi(d.get("tohum")) or d.get("tohum") < 0:
        h.ekle("tohum", "sıfır veya pozitif tam sayı olmalı")
    alan_sinirlari_denetle(h, c, "alan", d.get("alan"))
    isik = d.get("isik")
    if alan_denetle(h, "isik", isik, ["gunes_azimut_derece", "gunes_yukseklik_derece"]):
        az, yu = isik.get("gunes_azimut_derece"), isik.get("gunes_yukseklik_derece")
        if not sayi_mi(az) or not 0 <= az < 360:
            h.ekle("isik.gunes_azimut_derece", "[0, 360) aralığında sayı olmalı")
        if not sayi_mi(yu) or not c.gunes_min <= yu <= c.gunes_maks:
            h.ekle("isik.gunes_yukseklik_derece", f"[{c.gunes_min:g}, {c.gunes_maks:g}] aralığında sayı olmalı")
    zemin = d.get("zemin")
    if alan_denetle(h, "zemin", zemin, ["gorunum_varyanti"]) and zemin.get("gorunum_varyanti") not in c.zemin:
        h.ekle("zemin.gorunum_varyanti", f"{c.zemin} değerlerinden biri olmalı (bulunan: {zemin.get('gorunum_varyanti')!r})")
    hedefler = d.get("hedefler")
    if not isinstance(hedefler, list):
        h.ekle("hedefler", "liste olmalı")
        return h.liste
    gecerli = []
    gorulen = set()
    xa, ya = c.x_aralik, c.y_aralik
    for i, t in enumerate(hedefler):
        yol = f"hedefler[{i}]"
        if not alan_denetle(h, yol, t, ["kimlik", "sinif", "x", "y", "yonelim_derece", "gorunum_varyanti"]):
            continue
        k = t.get("kimlik")
        if not (isinstance(k, str) and KIMLIK_RE.match(k)):
            h.ekle(f"{yol}.kimlik", "1-64 karakter, yalnız harf/rakam/_/- olmalı")
        elif k in gorulen:
            h.ekle(f"{yol}.kimlik", f"'{k}' yinelenen kimlik")
        else:
            gorulen.add(k)
        s = t.get("sinif")
        if s not in c.siniflar:
            h.ekle(f"{yol}.sinif", f"{c.siniflar} değerlerinden biri olmalı (bulunan: {s!r})")
        ok = True
        for ek, aralik in (("x", xa), ("y", ya)):
            v = t.get(ek)
            if not sayi_mi(v):
                h.ekle(f"{yol}.{ek}", "sayı olmalı"); ok = False
            elif not aralik[0] + c.kenar_payi <= v <= aralik[1] - c.kenar_payi:
                h.ekle(f"{yol}.{ek}", f"{v:g} alan dışında/kenar payı içinde (izinli aralık [{aralik[0] + c.kenar_payi:g}, {aralik[1] - c.kenar_payi:g}] m)")
        yo = t.get("yonelim_derece")
        if not sayi_mi(yo) or not 0 <= yo < 360:
            h.ekle(f"{yol}.yonelim_derece", "[0, 360) aralığında sayı olmalı (yerel ENU: +x (doğu) ekseninden saat yönünün tersine)")
        gv = t.get("gorunum_varyanti")
        if s in c.varyant:
            if gv not in c.varyant[s]:
                h.ekle(f"{yol}.gorunum_varyanti", f"{s} için {c.varyant[s]} değerlerinden biri olmalı (bulunan: {gv!r})")
            elif bolum in c.bolumler and bolum != "test" and gv in c.test_ozel[s]:
                h.ekle(f"{yol}.gorunum_varyanti", f"'{gv}' yalnız test bölümünde kullanılabilir (bölüm: {bolum!r})")
        if ok and s in c.siniflar:
            gecerli.append((k, s, t["x"], t["y"]))
    # sayı kuralları
    sayi = {s: sum(1 for g in gecerli if g[1] == s) for s in c.siniflar}
    if bolum not in c.bolumler:
        esik = None             # bölüm geçersiz: sayı ve uzaklık kuralları uygulanamaz
    elif bolum == "test":
        for s in c.siniflar:
            if sayi[s] != c.test_sayi[s]:
                h.ekle("hedefler", f"test bölümünde {c.test_sayi[s]} {s} olmalı (bulunan: {sayi[s]})")
        esik = c.mesafe_test
    else:
        if len(hedefler) > c.diger_maks:
            h.ekle("hedefler", f"{bolum} bölümünde en çok {c.diger_maks} hedef olabilir (bulunan: {len(hedefler)})")
        for s in c.siniflar:
            if sayi[s] < 1:
                h.ekle("hedefler", f"{bolum} bölümünde en az 1 {s} olmalı")
        esik = c.mesafe_diger
    # merkezler arası uzaklık
    for i in range(len(gecerli) if esik is not None else 0):
        for j in range(i + 1, len(gecerli)):
            a, b = gecerli[i], gecerli[j]
            dist = math.hypot(a[2] - b[2], a[3] - b[3])
            if dist < esik:
                h.ekle("hedefler", f"'{a[0]}' ile '{b[0]}' merkezleri arası {dist:.2f} m (en az {esik:g} m olmalı)")
    return h.liste


def hedef_listesi_uret(d):
    return {"surum": SURUM, "tur": "hedef_listesi", "sahne_kimligi": d["sahne_kimligi"], "bolum": d["bolum"],
            "hedefler": [{"kimlik": t["kimlik"], "sinif": t["sinif"], "x": t["x"], "y": t["y"]} for t in d["hedefler"]]}


def dogrula_hedef_listesi(c, d, sahne=None):
    h = Hatalar()
    if not alan_denetle(h, "", d, ["surum", "tur", "sahne_kimligi", "bolum", "hedefler"]):
        return h.liste
    ust_alanlar(h, d, "hedef_listesi")
    if not (isinstance(d.get("sahne_kimligi"), str) and KIMLIK_RE.match(d["sahne_kimligi"])):
        h.ekle("sahne_kimligi", "1-64 karakter, yalnız harf/rakam/_/- olmalı")
    if d.get("bolum") not in c.bolumler:
        h.ekle("bolum", f"{c.bolumler} değerlerinden biri olmalı (bulunan: {d.get('bolum')!r})")
    hed = d.get("hedefler")
    if not isinstance(hed, list):
        h.ekle("hedefler", "liste olmalı")
        return h.liste
    gorulen = set()
    for i, t in enumerate(hed):
        yol = f"hedefler[{i}]"
        if not alan_denetle(h, yol, t, ["kimlik", "sinif", "x", "y"]):
            continue
        if not (isinstance(t.get("kimlik"), str) and KIMLIK_RE.match(t["kimlik"])):
            h.ekle(f"{yol}.kimlik", "1-64 karakter, yalnız harf/rakam/_/- olmalı")
        elif t["kimlik"] in gorulen:
            h.ekle(f"{yol}.kimlik", f"'{t['kimlik']}' yinelenen kimlik")
        else:
            gorulen.add(t["kimlik"])
        if t.get("sinif") not in c.siniflar:
            h.ekle(f"{yol}.sinif", f"{c.siniflar} değerlerinden biri olmalı (bulunan: {t.get('sinif')!r})")
        for ek in ("x", "y"):
            if not sayi_mi(t.get(ek)):
                h.ekle(f"{yol}.{ek}", "sayı olmalı")
    if sahne is not None and not h.liste:
        beklenen = hedef_listesi_uret(sahne)
        if d != beklenen:
            h.ekle("hedefler", "sahne dosyasındaki hedeflerden türetilen listeyle birebir aynı değil (kimlik, sınıf, x, y, sahne_kimligi, bolum)")
    return h.liste


# ---------------------------------------------------------------------------------------------------------------------------------
# Bölge ve rota
# ---------------------------------------------------------------------------------------------------------------------------------
def dogrula_bolge_rota(c, d):
    h = Hatalar()
    if not alan_denetle(h, "", d, ["surum", "tur", "alan", "irtifa_m", "hiz_ms", "serit", "bolgeler", "rotalar"]):
        return h.liste
    ust_alanlar(h, d, "bolge_rota")
    alan_sinirlari_denetle(h, c, "alan", d.get("alan"))
    ir = d.get("irtifa_m")
    if not sayi_mi(ir) or abs(ir - c.irtifa) > 1e-9:
        h.ekle("irtifa_m", f"sabit irtifa {c.irtifa:g} m olmalı (bulunan: {ir!r})")
    hz = d.get("hiz_ms")
    if not sayi_mi(hz) or hz <= 0 or abs(hz - c.hiz) > 1e-9:
        h.ekle("hiz_ms", f"yapılandırmadaki ROTA_HIZ_MS ({c.hiz:g} m/s) ile aynı pozitif sayı olmalı (bulunan: {hz!r})")
    w = c.iz_genisligi
    s = d.get("serit")
    if alan_denetle(h, "serit", s, ["hfov_derece", "iz_genisligi_m", "ortusme_min_m"]):
        if not sayi_mi(s.get("hfov_derece")) or abs(s["hfov_derece"] - c.hfov_deg) > 1e-6:
            h.ekle("serit.hfov_derece", f"kilitli HFOV {c.hfov_deg:g}° olmalı (bulunan: {s.get('hfov_derece')!r})")
        if not sayi_mi(s.get("iz_genisligi_m")) or abs(s["iz_genisligi_m"] - w) > 0.01:
            h.ekle("serit.iz_genisligi_m", f"w = 2·{c.irtifa:g}·tan(HFOV/2) = {w:.3f} m olmalı (bulunan: {s.get('iz_genisligi_m')!r})")
        if not sayi_mi(s.get("ortusme_min_m")) or s["ortusme_min_m"] < c.ortusme_min:
            h.ekle("serit.ortusme_min_m", f"en az {c.ortusme_min:g} m olmalı (bulunan: {s.get('ortusme_min_m')!r})")
    xa, ya = c.x_aralik, c.y_aralik
    bolgeler = d.get("bolgeler")
    gecerli = {}
    if not isinstance(bolgeler, list):
        h.ekle("bolgeler", "liste olmalı")
        bolgeler = []
    elif len(bolgeler) != c.bolge_sayisi:
        h.ekle("bolgeler", f"{c.bolge_sayisi} bölge olmalı (bulunan: {len(bolgeler)})")
    gorulen_arac, gorulen_bolge, dikdortgenler = set(), set(), []
    for i, b in enumerate(bolgeler):
        yol = f"bolgeler[{i}]"
        if not alan_denetle(h, yol, b, ["bolge_kimligi", "arac_kimligi", "x_min", "x_max", "y_min", "y_max"]):
            continue
        bk = b.get("bolge_kimligi")
        if not (isinstance(bk, str) and KIMLIK_RE.match(bk)):
            h.ekle(f"{yol}.bolge_kimligi", "1-64 karakter, yalnız harf/rakam/_/- olmalı")
        elif bk in gorulen_bolge:
            h.ekle(f"{yol}.bolge_kimligi", f"'{bk}' yinelenen bölge kimliği")
        else:
            gorulen_bolge.add(bk)
        ak = b.get("arac_kimligi")
        if ak not in c.arac_kimlikleri:
            h.ekle(f"{yol}.arac_kimligi", f"{c.arac_kimlikleri} değerlerinden biri olmalı (bulunan: {ak!r})")
        elif ak in gorulen_arac:
            h.ekle(f"{yol}.arac_kimligi", f"araç {ak} birden çok bölgeye atanmış")
        else:
            gorulen_arac.add(ak)
        v = [b.get(k) for k in ("x_min", "x_max", "y_min", "y_max")]
        if not all(sayi_mi(x) for x in v):
            h.ekle(yol, "x_min, x_max, y_min, y_max sayı olmalı")
            continue
        x0, x1, y0, y1 = v
        if not (x0 < x1 and y0 < y1):
            h.ekle(yol, "x_min < x_max ve y_min < y_max olmalı")
            continue
        if x0 < xa[0] - 1e-9 or x1 > xa[1] + 1e-9 or y0 < ya[0] - 1e-9 or y1 > ya[1] + 1e-9:
            h.ekle(yol, f"bölge alan dışına taşıyor (alan x [{xa[0]:g}, {xa[1]:g}], y [{ya[0]:g}, {ya[1]:g}])")
            continue
        dikdortgenler.append((bk, x0, x1, y0, y1))
        if ak in c.arac_kimlikleri:
            gecerli[ak] = (bk, x0, x1, y0, y1)
    for i in range(len(dikdortgenler)):
        for j in range(i + 1, len(dikdortgenler)):
            a, b = dikdortgenler[i], dikdortgenler[j]
            ox = min(a[2], b[2]) - max(a[1], b[1])
            oy = min(a[4], b[4]) - max(a[3], b[3])
            if ox > 1e-9 and oy > 1e-9:
                h.ekle("bolgeler", f"'{a[0]}' ile '{b[0]}' bölgeleri çakışıyor (örtüşme {ox:g} m × {oy:g} m)")
    toplam = sum((r[2] - r[1]) * (r[4] - r[3]) for r in dikdortgenler)
    alan_toplam = c.genislik * c.yukseklik
    if len(dikdortgenler) == len(bolgeler) and abs(toplam - alan_toplam) > 1e-6:
        h.ekle("bolgeler", f"bölgeler alanın tamamını kapsamıyor (toplam {toplam:g} m², alan {alan_toplam:g} m²; çakışma varsa yukarıdaki hataya bakın)")
    # rotalar
    rotalar = d.get("rotalar")
    if not isinstance(rotalar, list):
        h.ekle("rotalar", "liste olmalı")
        return h.liste
    rota_arac = set()
    yarim_boy = (w / 2) * c.h_px / c.w_px          # iz boyunca yarı kamera ayak izi (m)
    for i, r in enumerate(rotalar):
        yol = f"rotalar[{i}]"
        if not alan_denetle(h, yol, r, ["arac_kimligi", "noktalar"]):
            continue
        ak = r.get("arac_kimligi")
        if ak in rota_arac:
            h.ekle(f"{yol}.arac_kimligi", f"araç {ak} için birden çok rota")
        rota_arac.add(ak)
        if ak not in gecerli:
            h.ekle(f"{yol}.arac_kimligi", f"araç {ak} için tanımlı geçerli bölge yok")
            continue
        _, x0, x1, y0, y1 = gecerli[ak]
        nk = r.get("noktalar")
        if not (isinstance(nk, list) and len(nk) >= 2 and all(isinstance(p, list) and len(p) == 2 and all(sayi_mi(q) for q in p) for p in nk)):
            h.ekle(f"{yol}.noktalar", "en az 2 noktalı [x, y] listesi olmalı")
            continue
        dis = [k for k, p in enumerate(nk) if not (x0 - 1e-9 <= p[0] <= x1 + 1e-9 and y0 - 1e-9 <= p[1] <= y1 + 1e-9)]
        for k in dis[:5]:
            h.ekle(f"{yol}.noktalar[{k}]", f"{nk[k]} araç {ak} bölgesinin dışında (x [{x0:g}, {x1:g}], y [{y0:g}, {y1:g}])")
        # tarama doğruları: x'i sabit, y boyunca giden ardışık nokta çiftleri
        izler = [(a[0], min(a[1], b[1]), max(a[1], b[1])) for a, b in zip(nk, nk[1:]) if abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) > 1e-9]
        if not izler:
            h.ekle(f"{yol}.noktalar", "y yönünde (x sabit) hiç tarama doğrusu yok")
            continue
        izler.sort()
        merkezler = sorted({round(t[0], 6) for t in izler})
        if merkezler[0] - w / 2 > x0 + 1e-6:
            h.ekle(f"{yol}.noktalar", f"ilk izin sol kenarı {merkezler[0] - w / 2:.2f} m, bölge x_min {x0:g} m'yi kapsamıyor")
        if merkezler[-1] + w / 2 < x1 - 1e-6:
            h.ekle(f"{yol}.noktalar", f"son izin sağ kenarı {merkezler[-1] + w / 2:.2f} m, bölge x_max {x1:g} m'yi kapsamıyor")
        for a, b in zip(merkezler, merkezler[1:]):
            ort = w - (b - a)
            if ort < c.ortusme_min - 1e-6:
                h.ekle(f"{yol}.noktalar", f"x={a:g} ve x={b:g} komşu izlerinin örtüşmesi {ort:.2f} m (en az {c.ortusme_min:g} m olmalı)")
        ymin_iz = min(t[1] for t in izler)
        ymax_iz = max(t[2] for t in izler)
        if ymin_iz - yarim_boy > y0 + 1e-6:
            h.ekle(f"{yol}.noktalar", f"iz başlangıcı y={ymin_iz:g} m, ayak izi yarı boyu {yarim_boy:.2f} m ile bölge y_min {y0:g} m'yi kapsamıyor")
        if ymax_iz + yarim_boy < y1 - 1e-6:
            h.ekle(f"{yol}.noktalar", f"iz sonu y={ymax_iz:g} m, ayak izi yarı boyu {yarim_boy:.2f} m ile bölge y_max {y1:g} m'yi kapsamıyor")
    for ak in gecerli:
        if ak not in rota_arac:
            h.ekle("rotalar", f"araç {ak} için rota yok")
    return h.liste


# ---------------------------------------------------------------------------------------------------------------------------------
# Kamera kalibrasyonu
# ---------------------------------------------------------------------------------------------------------------------------------
ARAC_DURUMLARI = ("HAZIR", "BARIYER_BEKLE", "TARAMA", "WAIT", "TAMAMLANDI")    # swarm_msgs/VehicleState.STATE_* adları (GŞÖA 7.4)
BEKLENEN_R = [[0, -1, 0], [-1, 0, 0], [0, 0, -1]]      # kamera (OpenCV: x sağ, y aşağı, z ileri) → gövde (FLU: x ileri, y sol, z yukarı); aşağı bakan


def dogrula_kalibrasyon(c, d):
    h = Hatalar()
    if not alan_denetle(h, "", d, ["surum", "tur", "kalibrasyon_kimligi", "kamera_kimligi", "cozunurluk", "hfov_derece", "ic_parametreler", "bozulma", "arac_kamera"]):
        return h.liste
    ust_alanlar(h, d, "kamera_kalibrasyon")
    for k in ("kalibrasyon_kimligi", "kamera_kimligi"):
        if not (isinstance(d.get(k), str) and KIMLIK_RE.match(d[k])):
            h.ekle(k, "1-64 karakter, yalnız harf/rakam/_/- olmalı")
    co = d.get("cozunurluk")
    if alan_denetle(h, "cozunurluk", co, ["genislik_px", "yukseklik_px"]):
        if co.get("genislik_px") != c.w_px:
            h.ekle("cozunurluk.genislik_px", f"{c.w_px} olmalı (bulunan: {co.get('genislik_px')!r})")
        if co.get("yukseklik_px") != c.h_px:
            h.ekle("cozunurluk.yukseklik_px", f"{c.h_px} olmalı (bulunan: {co.get('yukseklik_px')!r})")
    hd = d.get("hfov_derece")
    if not sayi_mi(hd) or abs(hd - c.hfov_deg) > 1e-6:
        h.ekle("hfov_derece", f"kilitli HFOV {c.hfov_deg:g}° olmalı (bulunan: {hd!r})")
    ic = d.get("ic_parametreler")
    if alan_denetle(h, "ic_parametreler", ic, ["fx", "fy", "cx", "cy"]):
        fx_b = (c.w_px / 2) / math.tan(c.hfov_rad / 2)
        for k, beklenen, tol, aciklama in (("fx", fx_b, 1e-4 * fx_b, "fx = (genişlik/2)/tan(HFOV/2)"), ("fy", fx_b, 1e-4 * fx_b, "fy = fx (kare piksel)"),
                                           ("cx", c.w_px / 2, 1e-6, "cx = genişlik/2"), ("cy", c.h_px / 2, 1e-6, "cy = yükseklik/2")):
            v = ic.get(k)
            if not sayi_mi(v) or abs(v - beklenen) > tol:
                h.ekle(f"ic_parametreler.{k}", f"HFOV ve çözünürlükten türetilen {beklenen:.4f} olmalı ({aciklama}); bulunan: {v!r}")
    if d.get("bozulma") != "yok":
        h.ekle("bozulma", "ideal iğne deliği modeli: 'yok' olmalı")
    ak = d.get("arac_kamera")
    if alan_denetle(h, "arac_kamera", ak, ["arac_cercevesi", "kamera_cercevesi", "R", "t_m"]):
        if ak.get("arac_cercevesi") != "FLU":
            h.ekle("arac_kamera.arac_cercevesi", "'FLU' (x ileri, y sol, z yukarı) olmalı")
        if ak.get("kamera_cercevesi") != "OpenCV":
            h.ekle("arac_kamera.kamera_cercevesi", "'OpenCV' (x sağ, y aşağı, z optik eksen ileri) olmalı")
        R = ak.get("R")
        gecerli_R = isinstance(R, list) and len(R) == 3 and all(isinstance(s, list) and len(s) == 3 and all(sayi_mi(x) for x in s) for s in R)
        if not gecerli_R:
            h.ekle("arac_kamera.R", "3 × 3 sayı matrisi olmalı")
        else:
            rtr = [[sum(R[k][i] * R[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
            if any(abs(rtr[i][j] - (1.0 if i == j else 0.0)) > 1e-6 for i in range(3) for j in range(3)):
                h.ekle("arac_kamera.R", "dik-normal (Rᵀ·R = I) olmalı")
            det = (R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1]) - R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0])
                   + R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0]))
            if abs(det - 1.0) > 1e-6:
                h.ekle("arac_kamera.R", f"determinant +1 olmalı (bulunan: {det:.3f})")
            if any(abs(R[i][j] - BEKLENEN_R[i][j]) > 1e-6 for i in range(3) for j in range(3)):
                h.ekle("arac_kamera.R", f"gövdeye sabit, aşağı bakan kamera için {BEKLENEN_R} olmalı (optik eksen gövde −z; görüntünün yatay ekseni uçuş yönüne dik)")
        t = ak.get("t_m")
        if not (isinstance(t, list) and len(t) == 3 and all(sayi_mi(x) for x in t)):
            h.ekle("arac_kamera.t_m", "[x, y, z] üç sayı olmalı")
        elif abs(t[0]) > 1e-9 or abs(t[1]) > 1e-9 or abs(t[2] - c.kal_z) > 1e-9:
            h.ekle("arac_kamera.t_m", f"[0, 0, {c.kal_z:g}] olmalı (gövde çerçevesinde; bulunan: {t})")
    return h.liste


# ---------------------------------------------------------------------------------------------------------------------------------
# Koşu kaydı: koşu üst verisi (kosu.json) ve kare olay kaydı (JSON Lines)
# ---------------------------------------------------------------------------------------------------------------------------------
BITIS_DURUMLARI = ("tamamlandi", "zorla_kapatildi", "yarida_kaldi")
OLAY_TURLERI = ("uretim", "kuyruga_giris", "aktarim_tamam", "cikarim_basi", "cikarim_sonu", "kullanilabilir", "gonderim", "kayip_tespit", "gec_geldi", "yok_sayildi")
YEREL_OLAYLAR = ("kayip_tespit", "gec_geldi", "yok_sayildi")   # kamera alıcısının YEREL kayıtları (zaman aşaması değil): kayıp tespiti (yer istasyonundaki "kullanılabilir" kaydı değildir), geç gelen kare, görev girdisi olmayan kare
YOK_SAYILMA_NEDENLERI = ("gorev_oncesi", "kapanis_sonrasi", "izgara_disi", "tekrar")
UYGULANMAZ_OLABILEN = ("kuyruga_giris", "aktarim_tamam")   # [belge] yalnız aktarım aşamaları "uygulanmaz" olabilir
KAYNAKLAR = ("gazebo_damga", "kamera_alicisi", "arac_sureci", "cikarim_iscisi", "yer_istasyonu")
SONUC_DURUMLARI = ("sonuc", "tespit_yok", "kare_alinamadi", "islem_hatasi")     # "geç geldi" burada YOKTUR: ağa gönderilmez, yalnız alıcının yerel kaydıdır (olay: gec_geldi)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def mutlak_yol_tara(h, yol, v):
    """Kullanıcı adı / makine adı / mutlak yol sızmasın: hiçbir metin değeri '/' ile (mutlak yol) başlayamaz."""
    if isinstance(v, str):
        if v.startswith("/"):
            h.ekle(yol, f"mutlak yol yazılamaz (depo köküne göreli olmalı): {v!r}")
    elif isinstance(v, dict):
        for k, x in v.items():
            mutlak_yol_tara(h, f"{yol}.{k}" if yol else k, x)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            mutlak_yol_tara(h, f"{yol}[{i}]", x)


def zaman_nesnesi_denetle(h, yol, z):
    if not alan_denetle(h, yol, z, ["duvar_iso", "monotonik_ns"]):
        return
    if not (isinstance(z.get("duvar_iso"), str) and ISO_RE.match(z["duvar_iso"])):
        h.ekle(f"{yol}.duvar_iso", "saat dilimli ISO 8601 zamanı olmalı (örn. 2026-11-13T12:00:00+00:00)")
    if not (tam_sayi_mi(z.get("monotonik_ns")) and z["monotonik_ns"] > 0):
        h.ekle(f"{yol}.monotonik_ns", "pozitif tam sayı (CLOCK_MONOTONIC, ns) olmalı")


def dogrula_kosu_ustveri(c, d):
    h = Hatalar()
    zorunlu = ["surum", "tur", "kosu_kimligi", "baslangic", "bitis", "depo", "yapilandirma_sha256", "ortam_kilidi_sha256", "rota_sha256", "kaynak_sha256", "arac_sayisi",
               "arac_kimlikleri", "mimari_modu", "sahne_kimligi", "dunya", "model", "gz_partition", "surecler", "bitis_durumu"]
    if not alan_denetle(h, "", d, zorunlu, ["zorla_kapatilan"]):
        return h.liste
    ust_alanlar(h, d, "kosu_ustveri")
    mutlak_yol_tara(h, "", d)
    if not (isinstance(d.get("kosu_kimligi"), str) and KIMLIK_RE.match(d["kosu_kimligi"])):
        h.ekle("kosu_kimligi", "1-64 karakter, yalnız harf/rakam/_/- olmalı")
    zaman_nesnesi_denetle(h, "baslangic", d.get("baslangic"))
    if d.get("bitis") is not None:
        zaman_nesnesi_denetle(h, "bitis", d["bitis"])
        b, e = d.get("baslangic"), d["bitis"]
        if isinstance(b, dict) and isinstance(e, dict) and tam_sayi_mi(b.get("monotonik_ns")) and tam_sayi_mi(e.get("monotonik_ns")) \
                and e["monotonik_ns"] < b["monotonik_ns"]:
            h.ekle("bitis.monotonik_ns", "başlangıçtan önce olamaz")
    dep = d.get("depo")
    if alan_denetle(h, "depo", dep, ["commit", "calisma_agaci_temiz"]):
        if not (isinstance(dep.get("commit"), str) and COMMIT_RE.match(dep["commit"])):
            h.ekle("depo.commit", "40 karakterlik küçük harf onaltılık commit özeti olmalı")
        if not isinstance(dep.get("calisma_agaci_temiz"), bool):
            h.ekle("depo.calisma_agaci_temiz", "true/false olmalı")
    for k in ("yapilandirma_sha256", "ortam_kilidi_sha256", "rota_sha256", "kaynak_sha256"):
        if not (isinstance(d.get(k), str) and SHA_RE.match(d[k])):
            h.ekle(k, "64 karakterlik küçük harf onaltılık SHA-256 olmalı")
    n = d.get("arac_sayisi")
    kim = d.get("arac_kimlikleri")
    if not (tam_sayi_mi(n) and 1 <= n <= len(c.arac_kimlikleri)):
        h.ekle("arac_sayisi", f"1..{len(c.arac_kimlikleri)} arasında tam sayı olmalı (bulunan: {n!r})")
    if not (isinstance(kim, list) and all(tam_sayi_mi(x) for x in kim)):
        h.ekle("arac_kimlikleri", "tam sayı listesi olmalı")
    else:
        if tam_sayi_mi(n) and len(kim) != n:
            h.ekle("arac_kimlikleri", f"arac_sayisi ({n}) ile aynı uzunlukta olmalı (bulunan: {len(kim)})")
        if len(set(kim)) != len(kim):
            h.ekle("arac_kimlikleri", "yinelenen kimlik")
        for x in kim:
            if x not in c.arac_kimlikleri:
                h.ekle("arac_kimlikleri", f"{x} yapılandırmadaki UAV_SYS_IDS içinde yok ({c.arac_kimlikleri})")
    if d.get("mimari_modu") != "yok" and d.get("mimari_modu") not in c.mimariler:
        h.ekle("mimari_modu", f"'yok' ya da {c.mimariler} değerlerinden biri olmalı (bulunan: {d.get('mimari_modu')!r})")
    if d.get("sahne_kimligi") is not None and not (isinstance(d["sahne_kimligi"], str) and KIMLIK_RE.match(d["sahne_kimligi"])):
        h.ekle("sahne_kimligi", "null ya da 1-64 karakterlik kimlik olmalı")
    for k in ("dunya", "model", "gz_partition"):
        if not (isinstance(d.get(k), str) and d[k]):
            h.ekle(k, "boş olmayan metin olmalı")
    sur = d.get("surecler")
    adlar = []
    if not isinstance(sur, list) or not sur:
        h.ekle("surecler", "boş olmayan liste olmalı")
    else:
        for i, s in enumerate(sur):
            yol = f"surecler[{i}]"
            if not alan_denetle(h, yol, s, ["ad", "pid", "grup"]):
                continue
            if not (isinstance(s.get("ad"), str) and KIMLIK_RE.match(s["ad"])):
                h.ekle(f"{yol}.ad", "1-64 karakterlik ad olmalı")
            else:
                adlar.append(s["ad"])
            for k in ("pid", "grup"):
                if not (tam_sayi_mi(s.get(k)) and s[k] > 0):
                    h.ekle(f"{yol}.{k}", "pozitif tam sayı olmalı")
        if len(set(adlar)) != len(adlar):
            h.ekle("surecler", "yinelenen süreç adı")
    bd = d.get("bitis_durumu")
    if bd is not None and bd not in BITIS_DURUMLARI:
        h.ekle("bitis_durumu", f"null ya da {list(BITIS_DURUMLARI)} değerlerinden biri olmalı (bulunan: {bd!r})")
    if (bd is None) != (d.get("bitis") is None):
        h.ekle("bitis_durumu", "bitis ile birlikte dolu ya da birlikte null olmalı (koşu sürerken ikisi de null)")
    zk = d.get("zorla_kapatilan")
    if bd == "zorla_kapatildi":
        if not (isinstance(zk, list) and zk and all(isinstance(x, str) for x in zk)):
            h.ekle("zorla_kapatilan", "bitis_durumu 'zorla_kapatildi' iken zorla kapatılan süreç adlarının boş olmayan listesi olmalı")
        elif any(x not in adlar for x in zk):
            h.ekle("zorla_kapatilan", "süreç listesinde olmayan ad var")
    elif zk is not None:
        h.ekle("zorla_kapatilan", "yalnız bitis_durumu 'zorla_kapatildi' iken bulunabilir")
    return h.liste


def dogrula_kare_olay(c, d):
    """Tek bir kare olay kaydı (JSON Lines'ın bir satırı)."""
    h = Hatalar()
    if not alan_denetle(h, "", d, ["surum", "tur", "kaynak", "arac_kimligi", "n", "sim_damga_ns", "olay", "mono_ns"], ["sonuc_durumu", "neden"]):
        return h.liste
    ust_alanlar(h, d, "kare_olay")
    if d.get("kaynak") not in KAYNAKLAR:
        h.ekle("kaynak", f"{list(KAYNAKLAR)} değerlerinden biri olmalı (bulunan: {d.get('kaynak')!r})")
    if d.get("arac_kimligi") not in c.arac_kimlikleri or not tam_sayi_mi(d.get("arac_kimligi")):
        h.ekle("arac_kimligi", f"UAV_SYS_IDS değerlerinden biri olmalı ({c.arac_kimlikleri}; bulunan: {d.get('arac_kimligi')!r})")
    sim = d.get("sim_damga_ns")
    n = d.get("n")
    sim_ok = tam_sayi_mi(sim) and sim >= 0
    if not sim_ok:
        h.ekle("sim_damga_ns", "negatif olmayan tam sayı (ns) olmalı; ondalık saniye yazılmaz")
    hz = c.kamera_hz
    if n == "izgara_disi":
        if sim_ok and hz == int(hz) and (sim * int(hz)) % 1_000_000_000 == 0:
            h.ekle("n", "damga 0,5 s ızgarasına tam oturuyor; 'izgara_disi' yazılamaz, n = 2·t_sim türetilmeli")
    elif not (tam_sayi_mi(n) and n >= 0):
        h.ekle("n", "negatif olmayan tam sayı ya da 'izgara_disi' olmalı")
    elif sim_ok:
        if hz != int(hz) or (sim * int(hz)) % 1_000_000_000 != 0:
            h.ekle("n", "damga ızgaraya oturmuyor; numara türetilmez (yuvarlama yok), 'izgara_disi' yazılmalı")
        elif n != sim * int(hz) // 1_000_000_000:
            h.ekle("n", f"n = {int(hz)}·t_sim olmalı (damgadan türeyen: {sim * int(hz) // 1_000_000_000}, bulunan: {n})")
    olay = d.get("olay")
    if olay not in OLAY_TURLERI:
        h.ekle("olay", f"{list(OLAY_TURLERI)} değerlerinden biri olmalı (bulunan: {olay!r})")
    mono = d.get("mono_ns")
    if mono == "uygulanmaz":
        if olay not in UYGULANMAZ_OLABILEN:
            h.ekle("mono_ns", f"'uygulanmaz' yalnız aktarım aşamalarında ({list(UYGULANMAZ_OLABILEN)}) yazılabilir (olay: {olay!r})")
    elif not (tam_sayi_mi(mono) and mono > 0):
        h.ekle("mono_ns", "pozitif tam sayı (CLOCK_MONOTONIC, ns) ya da 'uygulanmaz' olmalı; 0, boş ve ondalık değer yazılamaz")
    sd = d.get("sonuc_durumu")
    if olay == "kullanilabilir":
        if sd not in SONUC_DURUMLARI:
            h.ekle("sonuc_durumu", f"'kullanilabilir' olayında {list(SONUC_DURUMLARI)} değerlerinden biri zorunlu (bulunan: {sd!r})")
    elif olay == "kayip_tespit":
        if d.get("sonuc_durumu") != "kare_alinamadi":
            h.ekle("sonuc_durumu", f"'kayip_tespit' olayında 'kare_alinamadi' zorunlu (bulunan: {d.get('sonuc_durumu')!r})")
    elif "sonuc_durumu" in d:
        h.ekle("sonuc_durumu", "yalnız 'kullanilabilir' ve 'kayip_tespit' olaylarında bulunabilir")
    if olay == "yok_sayildi":
        if d.get("neden") not in YOK_SAYILMA_NEDENLERI:
            h.ekle("neden", f"'yok_sayildi' olayında {list(YOK_SAYILMA_NEDENLERI)} değerlerinden biri zorunlu (bulunan: {d.get('neden')!r})")
        elif (d["neden"] == "izgara_disi") != (d.get("n") == "izgara_disi"):
            h.ekle("neden", "'izgara_disi' nedeni ile n = 'izgara_disi' birlikte olmalı")
    elif "neden" in d:
        h.ekle("neden", "yalnız 'yok_sayildi' olayında bulunabilir")
    if olay == "gonderim" and d.get("kaynak") != "arac_sureci":
        h.ekle("kaynak", f"'gonderim' kaydını yalnız araç süreci yazar (kaynak: 'arac_sureci'; bulunan: {d.get('kaynak')!r})")
    if olay in YEREL_OLAYLAR and d.get("kaynak") != "kamera_alicisi":
        h.ekle("kaynak", f"'{olay}' yerel kaydını yalnız kamera alıcısı yazar (kaynak: 'kamera_alicisi'; bulunan: {d.get('kaynak')!r})")
    return h.liste


def dogrula_kare_olay_dosyasi(c, satirlar):
    """Satır listesi (metin) için hata listesi; her bileşen kendi dosyasına yazar: dosyadaki bütün kayıtların kaynağı aynı olmalı."""
    hatalar = []
    kaynak = None
    gorulen = {}
    dolu = 0
    for no, ham in enumerate(satirlar, 1):
        if not ham.strip():
            hatalar.append(f"satır {no}: boş satır olamaz")
            continue
        try:
            d = json.loads(ham)
        except json.JSONDecodeError as e:
            hatalar.append(f"satır {no}: JSON geçersiz: {e}")
            continue
        dolu += 1
        hs = dogrula_kare_olay(c, d)
        hatalar.extend(f"satır {no}: {x}" for x in hs)
        if hs:
            continue
        if kaynak is None:
            kaynak = d["kaynak"]
        elif d["kaynak"] != kaynak:
            hatalar.append(f"satır {no}: kaynak: dosyadaki kayıtların kaynağı aynı olmalı ('{kaynak}' ile '{d['kaynak']}' karışık; her bileşen kendi dosyasına yazar)")
        anahtar = (d["arac_kimligi"], d["n"], d["sim_damga_ns"], d["olay"]) + ((d["mono_ns"],) if d["olay"] in YEREL_OLAYLAR else ())     # yerel kayıt aynı kare için birden çok olabilir
        if anahtar in gorulen:
            hatalar.append(f"satır {no}: yinelenen kayıt (araç {anahtar[0]}, n {anahtar[1]}, olay {anahtar[3]}); ilk görüldüğü satır: {gorulen[anahtar]}")
        else:
            gorulen[anahtar] = no
    if dolu == 0 and not hatalar:
        hatalar.append("dosya boş: en az bir kayıt olmalı")
    return hatalar


def dogrula_arac_durum_kaydi(c, d):
    """Tek bir araç durum kaydı (JSON Lines'ın bir satırı): bir aracın başka bir aracın ortak durum konusundan aldığı durum iletisi."""
    h = Hatalar()
    if not alan_denetle(h, "", d, ["surum", "tur", "arac_kimligi", "kaynak_arac_kimligi", "durum", "sim_damga_ns", "alinma_mono_ns"]):
        return h.liste
    ust_alanlar(h, d, "arac_durum_kaydi")
    for alan in ("arac_kimligi", "kaynak_arac_kimligi"):
        if not tam_sayi_mi(d.get(alan)) or d.get(alan) not in c.arac_kimlikleri:
            h.ekle(alan, f"UAV_SYS_IDS değerlerinden biri olmalı ({c.arac_kimlikleri}; bulunan: {d.get(alan)!r})")
    if d.get("arac_kimligi") == d.get("kaynak_arac_kimligi") and tam_sayi_mi(d.get("arac_kimligi")):
        h.ekle("kaynak_arac_kimligi", "kayıt yalnız DİĞER araçların durumlarını içerir; kaynak araç kaydı yazan araçla aynı olamaz")
    if d.get("durum") not in ARAC_DURUMLARI:
        h.ekle("durum", f"{list(ARAC_DURUMLARI)} değerlerinden biri olmalı (bulunan: {d.get('durum')!r})")
    if not (tam_sayi_mi(d.get("sim_damga_ns")) and d["sim_damga_ns"] >= 0):
        h.ekle("sim_damga_ns", "negatif olmayan tam sayı (ns) olmalı; ondalık saniye yazılmaz")
    if not (tam_sayi_mi(d.get("alinma_mono_ns")) and d["alinma_mono_ns"] > 0):
        h.ekle("alinma_mono_ns", "pozitif tam sayı (CLOCK_MONOTONIC, ns) olmalı; 0, boş ve ondalık değer yazılamaz")
    return h.liste


def dogrula_arac_durum_dosyasi(c, satirlar):
    """Bir araç sürecinin kayıt dosyası: tek yazar araç, alınma zamanı geriye gitmez, boş satır yok."""
    hatalar = []
    yazar = None
    son_mono = None
    dolu = 0
    for no, ham in enumerate(satirlar, 1):
        if not ham.strip():
            hatalar.append(f"satır {no}: boş satır olamaz")
            continue
        try:
            d = json.loads(ham)
        except json.JSONDecodeError as e:
            hatalar.append(f"satır {no}: JSON geçersiz: {e}")
            continue
        dolu += 1
        hs = dogrula_arac_durum_kaydi(c, d)
        hatalar.extend(f"satır {no}: {x}" for x in hs)
        if hs:
            continue
        if yazar is None:
            yazar = d["arac_kimligi"]
        elif d["arac_kimligi"] != yazar:
            hatalar.append(f"satır {no}: arac_kimligi: dosyadaki kayıtların yazarı aynı olmalı ({yazar} ile {d['arac_kimligi']} karışık; her araç kendi dosyasına yazar)")
        if son_mono is not None and d["alinma_mono_ns"] < son_mono:
            hatalar.append(f"satır {no}: alinma_mono_ns: geriye gidiyor ({d['alinma_mono_ns']} < {son_mono}); alınma sırası monotoniktir")
        son_mono = d["alinma_mono_ns"]
    if dolu == 0 and not hatalar:
        hatalar.append("dosya boş: en az bir kayıt olmalı")
    return hatalar


KARE_SONUC_DURUMLARI = ("tespit", "tespit_yok", "islem_hatasi", "kare_alinamadi")


def dogrula_kare_sonuc(c, d):
    """Tek bir kare sonucu kaydı (JSON Lines'ın bir satırı): dört durum ayrıdır ve karışmaz [belge]."""
    h = Hatalar()
    zor = ["surum", "tur", "arac_kimligi", "n", "sim_damga_ns", "durum", "tespit_sayisi", "tespitler", "atilan_sinif_disi", "hata", "mono_ns"]
    if not alan_denetle(h, "", d, zor):
        return h.liste
    ust_alanlar(h, d, "kare_sonuc")
    if not tam_sayi_mi(d.get("arac_kimligi")) or d.get("arac_kimligi") not in c.arac_kimlikleri:
        h.ekle("arac_kimligi", f"UAV_SYS_IDS değerlerinden biri olmalı ({c.arac_kimlikleri}; bulunan: {d.get('arac_kimligi')!r})")
    hz = c.kamera_hz
    n, sim = d.get("n"), d.get("sim_damga_ns")
    if not (tam_sayi_mi(n) and n >= 0):
        h.ekle("n", "negatif olmayan tam sayı olmalı (kare sonucu yalnız ızgara numaralı görev karelerine aittir)")
    if not (tam_sayi_mi(sim) and sim >= 0):
        h.ekle("sim_damga_ns", "negatif olmayan tam sayı (ns) olmalı; ondalık saniye yazılmaz")
    elif tam_sayi_mi(n) and hz == int(hz) and sim * int(hz) != n * 1_000_000_000:
        h.ekle("n", f"n = {int(hz)}·t_sim olmalı (damgadan türeyen: {sim * int(hz) / 1_000_000_000:g}, bulunan: {n})")
    durum = d.get("durum")
    if durum not in KARE_SONUC_DURUMLARI:
        h.ekle("durum", f"{list(KARE_SONUC_DURUMLARI)} değerlerinden biri olmalı (bulunan: {durum!r})")
    if not (tam_sayi_mi(d.get("mono_ns")) and d["mono_ns"] > 0):
        h.ekle("mono_ns", "pozitif tam sayı (CLOCK_MONOTONIC, ns) olmalı")
    if not (tam_sayi_mi(d.get("atilan_sinif_disi")) and d["atilan_sinif_disi"] >= 0):
        h.ekle("atilan_sinif_disi", "negatif olmayan tam sayı olmalı")
    t = d.get("tespitler")
    if not isinstance(t, list):
        h.ekle("tespitler", "liste olmalı")
        t = []
    if d.get("tespit_sayisi") != len(t) or not tam_sayi_mi(d.get("tespit_sayisi")):
        h.ekle("tespit_sayisi", f"tespitler listesinin uzunluğuna ({len(t)}) eşit tam sayı olmalı (bulunan: {d.get('tespit_sayisi')!r})")
    if durum == "tespit" and not t:
        h.ekle("tespitler", "'tespit' durumunda en az bir tespit olmalı")
    if durum in ("tespit_yok", "islem_hatasi", "kare_alinamadi") and t:
        h.ekle("tespitler", f"'{durum}' durumunda tespit listesi boş olmalı (bu durumlar tespit taşımaz)")
    hata = d.get("hata")
    if durum == "islem_hatasi":
        if not (isinstance(hata, str) and hata.strip()):
            h.ekle("hata", "'islem_hatasi' durumunda boş olmayan hata metni zorunlu ('tespit yok' ile karıştırılmaz)")
    elif hata is not None:
        h.ekle("hata", "yalnız 'islem_hatasi' durumunda hata metni olabilir (diğer durumlarda null)")
    if durum == "kare_alinamadi" and d.get("atilan_sinif_disi") not in (0, None):
        h.ekle("atilan_sinif_disi", "'kare_alinamadi' durumunda 0 olmalı")
    for i, x in enumerate(t):
        yol = f"tespitler[{i}]"
        if not alan_denetle(h, yol, x, ["sinif", "sinif_no", "guven", "kutu", "konum", "aday"]):
            continue
        if x.get("sinif") not in c.model_siniflari:
            h.ekle(f"{yol}.sinif", f"MODEL_SINIFLAR değerlerinden biri olmalı ({c.model_siniflari}; bulunan: {x.get('sinif')!r})")
        elif x.get("sinif_no") != c.model_siniflari.index(x["sinif"]):
            h.ekle(f"{yol}.sinif_no", f"'{x['sinif']}' için {c.model_siniflari.index(x['sinif'])} olmalı (MODEL_SINIFLAR sırası; bulunan: {x.get('sinif_no')!r})")
        g = x.get("guven")
        if not (sayi_mi(g) and c.guven_esigi <= g <= 1):
            h.ekle(f"{yol}.guven", f"[{c.guven_esigi:g}, 1] aralığında sayı olmalı (INF_CONF eşiği; bulunan: {g!r})")
        k = x.get("kutu")
        if not (isinstance(k, list) and len(k) == 4 and all(sayi_mi(v) for v in k)):
            h.ekle(f"{yol}.kutu", "[x_min, y_min, x_maks, y_maks] (piksel, 4 sayı) olmalı")
        elif not (0 <= k[0] < k[2] <= c.w_px and 0 <= k[1] < k[3] <= c.h_px):
            h.ekle(f"{yol}.kutu", f"görüntü içinde ve x_min < x_maks, y_min < y_maks olmalı ({c.w_px}×{c.h_px}; bulunan: {k})")
        if x.get("konum") is not None:
            h.ekle(f"{yol}.konum", "bu sürümde null olmalı (tahmini konum konum hesaplayıcının işidir)")
        if x.get("aday") is not False:
            h.ekle(f"{yol}.aday", "bu sürümde false olmalı (birleştirme adayı birleştirme modülünün işidir)")
    return h.liste


def dogrula_kare_sonuc_dosyasi(c, satirlar):
    """Bir araç sürecinin kare sonucu dosyası: tek yazar araç, her görev numarası için TAM BİR sonuç (yinelenen numara yok), boş satır yok."""
    hatalar = []
    yazar = None
    gorulen = {}
    dolu = 0
    for no, ham in enumerate(satirlar, 1):
        if not ham.strip():
            hatalar.append(f"satır {no}: boş satır olamaz")
            continue
        try:
            d = json.loads(ham)
        except json.JSONDecodeError as e:
            hatalar.append(f"satır {no}: JSON geçersiz: {e}")
            continue
        dolu += 1
        hs = dogrula_kare_sonuc(c, d)
        hatalar.extend(f"satır {no}: {x}" for x in hs)
        if hs:
            continue
        if yazar is None:
            yazar = d["arac_kimligi"]
        elif d["arac_kimligi"] != yazar:
            hatalar.append(f"satır {no}: arac_kimligi: dosyadaki kayıtların yazarı aynı olmalı ({yazar} ile {d['arac_kimligi']} karışık; her araç kendi dosyasına yazar)")
        if d["n"] in gorulen:
            hatalar.append(f"satır {no}: n: {d['n']} numaralı kare için ikinci sonuç (ilk sonuç satır {gorulen[d['n']]}); her görev numarası için tam bir kare sonucu olmalı")
        else:
            gorulen[d["n"]] = no
    if dolu == 0 and not hatalar:
        hatalar.append("dosya boş: en az bir kayıt olmalı")
    return hatalar


def dogrula_isci_kaynak(c, d):
    """Tek bir işçi kaynak kaydı: periyodik GPU kullanımı/belleği (süreç başına), ana bellek ve CPU. NVML kullanılamıyorsa GPU alanları null olabilir."""
    h = Hatalar()
    if not alan_denetle(h, "", d, ["surum", "tur", "arac_kimligi", "isci_pid", "mono_ns", "gpu_kullanim_yuzde", "gpu_bellek_mib", "ana_bellek_rss_mib", "cpu_yuzde"]):
        return h.liste
    ust_alanlar(h, d, "isci_kaynak")
    if not tam_sayi_mi(d.get("arac_kimligi")) or d.get("arac_kimligi") not in c.arac_kimlikleri:
        h.ekle("arac_kimligi", f"UAV_SYS_IDS değerlerinden biri olmalı ({c.arac_kimlikleri}; bulunan: {d.get('arac_kimligi')!r})")
    if not (tam_sayi_mi(d.get("isci_pid")) and d["isci_pid"] > 0):
        h.ekle("isci_pid", "pozitif tam sayı olmalı")
    if not (tam_sayi_mi(d.get("mono_ns")) and d["mono_ns"] > 0):
        h.ekle("mono_ns", "pozitif tam sayı (CLOCK_MONOTONIC, ns) olmalı")
    g = d.get("gpu_kullanim_yuzde")
    if g is not None and not (tam_sayi_mi(g) and 0 <= g <= 100):
        h.ekle("gpu_kullanim_yuzde", "[0, 100] aralığında tam sayı ya da null olmalı")
    for alan in ("gpu_bellek_mib", "ana_bellek_rss_mib", "cpu_yuzde"):
        v = d.get(alan)
        if v is not None and not (sayi_mi(v) and v >= 0):
            h.ekle(alan, "negatif olmayan sayı ya da null olmalı")
    if d.get("ana_bellek_rss_mib") is None:
        h.ekle("ana_bellek_rss_mib", "null olamaz (ana bellek /proc'tan okunur)")
    return h.liste


def dogrula_isci_kaynak_dosyasi(c, satirlar):
    """İşçi kaynak dosyası: tek yazar araç, zaman geriye gitmez (işçi yeniden başlatılsa da monotonik saat sürer), boş satır yok."""
    hatalar = []
    yazar = None
    son = None
    dolu = 0
    for no, ham in enumerate(satirlar, 1):
        if not ham.strip():
            hatalar.append(f"satır {no}: boş satır olamaz")
            continue
        try:
            d = json.loads(ham)
        except json.JSONDecodeError as e:
            hatalar.append(f"satır {no}: JSON geçersiz: {e}")
            continue
        dolu += 1
        hs = dogrula_isci_kaynak(c, d)
        hatalar.extend(f"satır {no}: {x}" for x in hs)
        if hs:
            continue
        if yazar is None:
            yazar = d["arac_kimligi"]
        elif d["arac_kimligi"] != yazar:
            hatalar.append(f"satır {no}: arac_kimligi: dosyadaki kayıtların yazarı aynı olmalı ({yazar} ile {d['arac_kimligi']} karışık)")
        if son is not None and d["mono_ns"] < son:
            hatalar.append(f"satır {no}: mono_ns: geriye gidiyor ({d['mono_ns']} < {son})")
        son = d["mono_ns"]
    if dolu == 0 and not hatalar:
        hatalar.append("dosya boş: en az bir kayıt olmalı")
    return hatalar


POZ_RED_NEDENLERI = ("geriye_giden", "yinelenen", "gecersiz_deger", "enjeksiyon")
POZ_GECERSIZ_NEDENLERI = ("aralik_asildi", "tampon_disi", "bekleme_asildi")


def _vektor_mu(v, n):
    return isinstance(v, list) and len(v) == n and all(sayi_mi(x) for x in v)


def dogrula_telemetri(c, d):
    """Tek bir telemetri kaydı (planlama/sozlesmeler.md §8.10): px4_adapter'ın aldığı her odometri örneği (kabul edilen ya da reddedilen)."""
    h = Hatalar()
    if not alan_denetle(h, "", d, ["surum", "tur", "arac_kimligi", "kaynak_ns", "alinma_mono_ns", "konum_ned_m", "q_wxyz", "kabul", "red_neden"]):
        return h.liste
    ust_alanlar(h, d, "telemetri")
    if not tam_sayi_mi(d.get("arac_kimligi")) or d.get("arac_kimligi") not in c.arac_kimlikleri:
        h.ekle("arac_kimligi", f"UAV_SYS_IDS değerlerinden biri olmalı ({c.arac_kimlikleri}; bulunan: {d.get('arac_kimligi')!r})")
    if not (tam_sayi_mi(d.get("kaynak_ns")) and d["kaynak_ns"] >= 0):
        h.ekle("kaynak_ns", "negatif olmayan tam sayı (PX4 time_usec → ns) olmalı")
    if not (tam_sayi_mi(d.get("alinma_mono_ns")) and d["alinma_mono_ns"] > 0):
        h.ekle("alinma_mono_ns", "pozitif tam sayı (CLOCK_MONOTONIC, ns) olmalı")
    gecersiz_deger = d.get("kabul") is False and d.get("red_neden") == "gecersiz_deger"   # sonlu olmayan değerler null yazılır; birim norm denetlenmez
    sayi_ya_da_null = lambda v, n: isinstance(v, list) and len(v) == n and all(x is None or sayi_mi(x) for x in v)  # noqa: E731
    if not (sayi_ya_da_null(d.get("konum_ned_m"), 3) if gecersiz_deger else _vektor_mu(d.get("konum_ned_m"), 3)):
        h.ekle("konum_ned_m", "[kuzey, doğu, aşağı] üç sayı (m) olmalı (yalnız 'gecersiz_deger' reddinde sonlu olmayan değer null olabilir)")
    q = d.get("q_wxyz")
    if not (sayi_ya_da_null(q, 4) if gecersiz_deger else _vektor_mu(q, 4)):
        h.ekle("q_wxyz", "[w, x, y, z] dört sayı olmalı (yalnız 'gecersiz_deger' reddinde sonlu olmayan değer null olabilir)")
    elif not gecersiz_deger and abs(math.sqrt(sum(v * v for v in q)) - 1.0) > 1e-3:
        h.ekle("q_wxyz", f"birim kuaterniyon olmalı (norm {math.sqrt(sum(v * v for v in q)):.6f})")
    kabul, red = d.get("kabul"), d.get("red_neden")
    if not isinstance(kabul, bool):
        h.ekle("kabul", "true/false olmalı")
    elif kabul and red is not None:
        h.ekle("red_neden", "kabul edilen örnekte null olmalı")
    elif not kabul and red not in POZ_RED_NEDENLERI:
        h.ekle("red_neden", f"reddedilen örnekte {list(POZ_RED_NEDENLERI)} değerlerinden biri olmalı (bulunan: {red!r})")
    return h.liste


def dogrula_telemetri_dosyasi(c, satirlar):
    """Telemetri dosyası: tek yazar araç, alınma zamanı geriye gitmez, KABUL edilen örneklerin kaynak zamanı kesin artar, boş satır yok."""
    hatalar = []
    yazar = son_alinma = son_kaynak = None
    dolu = 0
    for no, ham in enumerate(satirlar, 1):
        if not ham.strip():
            hatalar.append(f"satır {no}: boş satır olamaz")
            continue
        try:
            d = json.loads(ham)
        except json.JSONDecodeError as e:
            hatalar.append(f"satır {no}: JSON geçersiz: {e}")
            continue
        dolu += 1
        hs = dogrula_telemetri(c, d)
        hatalar.extend(f"satır {no}: {x}" for x in hs)
        if hs:
            continue
        if yazar is None:
            yazar = d["arac_kimligi"]
        elif d["arac_kimligi"] != yazar:
            hatalar.append(f"satır {no}: arac_kimligi: dosyadaki kayıtların yazarı aynı olmalı ({yazar} ile {d['arac_kimligi']} karışık)")
        if son_alinma is not None and d["alinma_mono_ns"] < son_alinma:
            hatalar.append(f"satır {no}: alinma_mono_ns: geriye gidiyor ({d['alinma_mono_ns']} < {son_alinma})")
        son_alinma = d["alinma_mono_ns"]
        if d["kabul"]:
            if son_kaynak is not None and d["kaynak_ns"] <= son_kaynak:
                hatalar.append(f"satır {no}: kaynak_ns: kabul edilen örneklerde kesin artmalı ({d['kaynak_ns']} <= {son_kaynak})")
            son_kaynak = d["kaynak_ns"]
    if dolu == 0 and not hatalar:
        hatalar.append("dosya boş: en az bir kayıt olmalı")
    return hatalar


def dogrula_kare_poz(c, d):
    """Tek bir kare–poz kaydı (§8.11): kare üretim anındaki enterpolasyonlu PX4 pozu ya da geçersizlik nedeni. Geçerli poz yokken konum/yönelim null'dır (yedek poz yoktur)."""
    h = Hatalar()
    zor = ["surum", "tur", "arac_kimligi", "n", "kare_ns", "gecerli", "neden", "t1_ns", "t2_ns", "aralik_ms", "bekleme_ms", "konum_ned_m", "q_wxyz"]
    if not alan_denetle(h, "", d, zor):
        return h.liste
    ust_alanlar(h, d, "kare_poz")
    if not tam_sayi_mi(d.get("arac_kimligi")) or d.get("arac_kimligi") not in c.arac_kimlikleri:
        h.ekle("arac_kimligi", f"UAV_SYS_IDS değerlerinden biri olmalı ({c.arac_kimlikleri}; bulunan: {d.get('arac_kimligi')!r})")
    n, kare = d.get("n"), d.get("kare_ns")
    hz = c.kamera_hz
    if not (tam_sayi_mi(n) and n >= 0):
        h.ekle("n", "negatif olmayan tam sayı olmalı")
    if not (tam_sayi_mi(kare) and kare >= 0):
        h.ekle("kare_ns", "negatif olmayan tam sayı (ns) olmalı")
    elif tam_sayi_mi(n) and hz == int(hz) and kare * int(hz) != n * 1_000_000_000:
        h.ekle("kare_ns", f"n · 10⁹ / CAM_RATE_HZ olmalı (n={n}, bulunan: {kare})")
    bek = d.get("bekleme_ms")
    if not (sayi_mi(bek) and bek >= 0):
        h.ekle("bekleme_ms", "negatif olmayan sayı (ms) olmalı (bekleme ölçüme dahildir; her kayıtta yazılır)")
    gecerli, neden = d.get("gecerli"), d.get("neden")
    t1, t2, ar = d.get("t1_ns"), d.get("t2_ns"), d.get("aralik_ms")
    konum, q = d.get("konum_ned_m"), d.get("q_wxyz")
    if not isinstance(gecerli, bool):
        h.ekle("gecerli", "true/false olmalı")
        return h.liste
    if gecerli:
        if neden is not None:
            h.ekle("neden", "geçerli poz kaydında null olmalı")
        if not (tam_sayi_mi(t1) and tam_sayi_mi(t2) and t1 <= t2):
            h.ekle("t1_ns", "geçerli pozda t1_ns <= t2_ns tam sayı çifti olmalı")
        elif tam_sayi_mi(kare) and not (t1 <= kare <= t2):
            h.ekle("t1_ns", f"t1 <= kare_ns <= t2 olmalı (t1={t1}, kare_ns={kare}, t2={t2})")
        if tam_sayi_mi(t1) and tam_sayi_mi(t2):
            if not (sayi_mi(ar) and abs(ar - (t2 - t1) / 1e6) < 1e-6):
                h.ekle("aralik_ms", f"(t2 - t1) / 10⁶ olmalı (bulunan: {ar!r})")
            elif ar > c.poz_aralik_sinir_ms:
                h.ekle("aralik_ms", f"geçerli pozda POZ_ARALIK_SINIR_MS ({c.poz_aralik_sinir_ms:g}) değerini aşamaz (bulunan: {ar:g})")
        if not _vektor_mu(konum, 3):
            h.ekle("konum_ned_m", "geçerli pozda üç sayı olmalı")
        if not _vektor_mu(q, 4):
            h.ekle("q_wxyz", "geçerli pozda dört sayı olmalı")
        elif abs(math.sqrt(sum(v * v for v in q)) - 1.0) > 1e-3:
            h.ekle("q_wxyz", "birim kuaterniyon olmalı")
        return h.liste
    if neden not in POZ_GECERSIZ_NEDENLERI:
        h.ekle("neden", f"geçersiz pozda {list(POZ_GECERSIZ_NEDENLERI)} değerlerinden biri olmalı (bulunan: {neden!r})")
    if konum is not None:
        h.ekle("konum_ned_m", "geçerli poz yokken null olmalı (son örnek ya da durum mesajı yedek olarak kullanılmaz)")
    if q is not None:
        h.ekle("q_wxyz", "geçerli poz yokken null olmalı")
    if neden == "aralik_asildi":
        if not (tam_sayi_mi(t1) and tam_sayi_mi(t2) and t1 < t2 and sayi_mi(ar) and abs(ar - (t2 - t1) / 1e6) < 1e-6):
            h.ekle("t1_ns", "'aralik_asildi' için t1_ns < t2_ns ve aralik_ms = (t2 - t1) / 10⁶ olmalı")
        elif ar <= c.poz_aralik_sinir_ms:
            h.ekle("aralik_ms", f"'aralik_asildi' için POZ_ARALIK_SINIR_MS ({c.poz_aralik_sinir_ms:g}) değerini aşmalı (bulunan: {ar:g})")
    elif neden in POZ_GECERSIZ_NEDENLERI:
        if t1 is not None or t2 is not None or ar is not None:
            h.ekle("t1_ns", f"'{neden}' için t1_ns, t2_ns ve aralik_ms null olmalı")
    return h.liste


def dogrula_kare_poz_dosyasi(c, satirlar):
    """Kare–poz dosyası: tek yazar araç, her görev numarası için TAM BİR kayıt, boş satır yok."""
    hatalar = []
    yazar = None
    gorulen = {}
    dolu = 0
    for no, ham in enumerate(satirlar, 1):
        if not ham.strip():
            hatalar.append(f"satır {no}: boş satır olamaz")
            continue
        try:
            d = json.loads(ham)
        except json.JSONDecodeError as e:
            hatalar.append(f"satır {no}: JSON geçersiz: {e}")
            continue
        dolu += 1
        hs = dogrula_kare_poz(c, d)
        hatalar.extend(f"satır {no}: {x}" for x in hs)
        if hs:
            continue
        if yazar is None:
            yazar = d["arac_kimligi"]
        elif d["arac_kimligi"] != yazar:
            hatalar.append(f"satır {no}: arac_kimligi: dosyadaki kayıtların yazarı aynı olmalı ({yazar} ile {d['arac_kimligi']} karışık)")
        if d["n"] in gorulen:
            hatalar.append(f"satır {no}: n: {d['n']} numaralı kare için ikinci kayıt (ilki satır {gorulen[d['n']]}); her görev numarası için tam bir kayıt olmalı")
        else:
            gorulen[d["n"]] = no
    if dolu == 0 and not hatalar:
        hatalar.append("dosya boş: en az bir kayıt olmalı")
    return hatalar


GOREV_OLAYLARI = ("gorev_atandi", "hazir", "eslesme", "t0", "tarama_bitisi", "son_sonuc", "t1", "tamamlandi", "zaman_asimi", "birlestirme_yok", "yok_sayildi", "hata")
GOREV_ARAC_ZORUNLU = ("gorev_atandi", "hazir", "tarama_bitisi", "tamamlandi")
GOREV_MISSION_ZORUNLU = ("gorev_atandi", "t0", "t1")


def dogrula_gorev_olay(c, d):
    """Yer istasyonu görev koordinatörünün görev olay kaydı (JSON Lines'ın bir satırı; taslak sürüm)."""
    h = Hatalar()
    if not alan_denetle(h, "", d, ["surum", "tur", "olay", "mono_ns", "sim_ns"],
                        ["arac_kimligi", "mission_id", "n_ilk", "n_son", "t_s_ns", "t_b_ns", "yayimci", "t1_eksi_son_bitis_ns", "neden", "ayrinti"]):
        return h.liste
    ust_alanlar(h, d, "gorev_olay")
    olay = d.get("olay")
    if olay not in GOREV_OLAYLARI:
        h.ekle("olay", f"{list(GOREV_OLAYLARI)} değerlerinden biri olmalı (bulunan: {olay!r})")
    if not (tam_sayi_mi(d.get("mono_ns")) and d["mono_ns"] > 0):
        h.ekle("mono_ns", "pozitif tam sayı (CLOCK_MONOTONIC, ns) olmalı")
    sim = d.get("sim_ns")
    if sim is not None and not (tam_sayi_mi(sim) and sim >= 0):
        h.ekle("sim_ns", "negatif olmayan tam sayı (ns) ya da null (simülasyon saati henüz bilinmiyor) olmalı")
    if "arac_kimligi" in d and not (tam_sayi_mi(d["arac_kimligi"]) and d["arac_kimligi"] in c.arac_kimlikleri):
        h.ekle("arac_kimligi", f"UAV_SYS_IDS değerlerinden biri olmalı ({c.arac_kimlikleri}; bulunan: {d['arac_kimligi']!r})")
    if olay in GOREV_ARAC_ZORUNLU and "arac_kimligi" not in d:
        h.ekle("arac_kimligi", f"'{olay}' olayında zorunlu")
    if olay in GOREV_MISSION_ZORUNLU and not (isinstance(d.get("mission_id"), str) and d["mission_id"]):
        h.ekle("mission_id", f"'{olay}' olayında boş olmayan metin olarak zorunlu")
    if olay == "tarama_bitisi":
        n1, n2 = d.get("n_ilk"), d.get("n_son")
        if not (tam_sayi_mi(n1) and tam_sayi_mi(n2) and 0 <= n1 <= n2):
            h.ekle("n_ilk", f"'tarama_bitisi' olayında 0 <= n_ilk <= n_son tam sayıları zorunlu (bulunan: {n1!r}, {n2!r})")
    elif "n_ilk" in d or "n_son" in d:
        h.ekle("n_ilk", "yalnız 'tarama_bitisi' olayında bulunabilir")
    for k in ("t_s_ns", "t_b_ns"):
        if k in d and d[k] is not None and not (tam_sayi_mi(d[k]) and d[k] >= 0):
            h.ekle(k, "negatif olmayan tam sayı (ns) ya da null olmalı")
    if olay == "eslesme" and not (tam_sayi_mi(d.get("yayimci")) and d["yayimci"] >= 0):
        h.ekle("yayimci", "'eslesme' olayında negatif olmayan tam sayı zorunlu")
    elif olay != "eslesme" and "yayimci" in d:
        h.ekle("yayimci", "yalnız 'eslesme' olayında bulunabilir")
    if "t1_eksi_son_bitis_ns" in d and (olay != "t1" or not tam_sayi_mi(d["t1_eksi_son_bitis_ns"])):
        h.ekle("t1_eksi_son_bitis_ns", "yalnız 't1' olayında ve tam sayı (ns) olarak bulunabilir")
    for k in ("neden", "ayrinti"):
        if k in d and not (isinstance(d[k], str) and d[k]):
            h.ekle(k, "boş olmayan metin olmalı")
    if olay in ("yok_sayildi", "hata", "zaman_asimi") and not isinstance(d.get("neden"), str):
        h.ekle("neden", f"'{olay}' olayında zorunlu")
    return h.liste


def dogrula_gorev_olay_dosyasi(c, satirlar):
    """Bir koşunun görev kaydı: tek yazar (yer istasyonu), mono_ns geriye gitmez; en çok bir t0 ve bir t1; t0 → son_sonuc → t1 sırası."""
    hatalar = []
    son, dolu = None, 0
    gorulen = {}
    for no, ham in enumerate(satirlar, 1):
        if not ham.strip():
            hatalar.append(f"satır {no}: boş satır olamaz")
            continue
        try:
            d = json.loads(ham)
        except json.JSONDecodeError as e:
            hatalar.append(f"satır {no}: JSON geçersiz: {e}")
            continue
        dolu += 1
        hs = dogrula_gorev_olay(c, d)
        hatalar.extend(f"satır {no}: {x}" for x in hs)
        if hs:
            continue
        if son is not None and d["mono_ns"] < son:
            hatalar.append(f"satır {no}: mono_ns: geriye gidiyor ({d['mono_ns']} < {son})")
        son = d["mono_ns"]
        o = d["olay"]
        if o in ("t0", "t1") and o in gorulen:
            hatalar.append(f"satır {no}: '{o}' olayı ikinci kez yazılamaz (satır {gorulen[o]})")
        if o == "t1" and "t0" not in gorulen:
            hatalar.append(f"satır {no}: 't1' olayı 't0' olayından önce olamaz")
        if o == "t1" and "son_sonuc" not in gorulen:
            hatalar.append(f"satır {no}: 't1' olayından önce 'son_sonuc' olayı yazılmış olmalı (COMPLETE yalnız bütün sonuçlardan sonra)")
        gorulen.setdefault(o, no)
    if dolu == 0 and not hatalar:
        hatalar.append("dosya boş: en az bir kayıt olmalı")
    return hatalar


# ---------------------------------------------------------------------------------------------------------------------------------
# Değerlendirme arayüzleri (taslak sürüm): nihai hedef raporu, koşu ölçüm özeti, sınırlayıcı bayt kaydı (planlama/sozlesmeler.md §11)
# ---------------------------------------------------------------------------------------------------------------------------------
OLCUM_TAMAMLANAMA_NEDENLERI = ("zaman_asimi", "kuyruk_tasmasi", "surec_olumu", "diger")     # [varsayım] adlar; M6b'de kesinleşir
SAYAC_SINIFI = "1:10"                 # [varsayım] ölçülen ağın sınırlayıcı sınıfı (setup/60_ag_emulasyon_tc.sh)
OLCUM_TOL = 1e-6


def _poz_tam(v):
    return tam_sayi_mi(v) and v > 0


def _neg_olmayan_tam(v):
    return tam_sayi_mi(v) and v >= 0


def _neg_olmayan_sayi(v):
    return sayi_mi(v) and v >= 0


def konum_denetle(h, yol, k):
    """Yerel ENU yatay konum {x_m, y_m} (m) ya da null (konumsuz rapor). Dolu ise True döner."""
    if k is None:
        return False
    if not alan_denetle(h, yol, k, ["x_m", "y_m"]):
        return False
    ok = True
    for a in ("x_m", "y_m"):
        if not sayi_mi(k.get(a)):
            h.ekle(f"{yol}.{a}", "sayı (m) olmalı")
            ok = False
    return ok


def tespit_kaynagi_denetle(h, c, yol, t):
    if not alan_denetle(h, yol, t, ["arac_kimligi", "n", "uretim_mono_ns"]):
        return None
    if not tam_sayi_mi(t.get("arac_kimligi")) or t.get("arac_kimligi") not in c.arac_kimlikleri:
        h.ekle(f"{yol}.arac_kimligi", f"UAV_SYS_IDS değerlerinden biri olmalı ({c.arac_kimlikleri}; bulunan: {t.get('arac_kimligi')!r})")
    if not _neg_olmayan_tam(t.get("n")):
        h.ekle(f"{yol}.n", "negatif olmayan tam sayı (kare numarası) olmalı")
    if not _poz_tam(t.get("uretim_mono_ns")):
        h.ekle(f"{yol}.uretim_mono_ns", "pozitif tam sayı (CLOCK_MONOTONIC, ns; karenin üretim anı) olmalı")
        return None
    return t["uretim_mono_ns"]


def kosu_ust_alanlari_denetle(h, c, d):
    for k in ("kosu_kimligi", "sahne_kimligi"):
        if k in d and not (isinstance(d.get(k), str) and KIMLIK_RE.match(d[k])):
            h.ekle(k, "1-64 karakter, yalnız harf/rakam/_/- olmalı")
    if "mod" in d and d.get("mod") not in c.mimariler:
        h.ekle("mod", f"KOSU_MIMARILER değerlerinden biri olmalı ({c.mimariler}; bulunan: {d.get('mod')!r})")


def dogrula_nihai_rapor(c, d):
    """11.1 Nihai hedef raporu: B15 (hedef birleştirme) üretir, B18 (değerlendirme) okur. Gerçek hedef kimliği içermez (birleştirmede kullanılmaz [belge])."""
    h = Hatalar()
    if not alan_denetle(h, "", d, ["surum", "tur", "kosu_kimligi", "sahne_kimligi", "mod", "raporlar"]):
        return h.liste
    ust_alanlar(h, d, "nihai_rapor")
    kosu_ust_alanlari_denetle(h, c, d)
    r = d.get("raporlar")
    if not isinstance(r, list):
        h.ekle("raporlar", "liste olmalı (hiç rapor üretilmeyen koşuda boş liste)")
        return h.liste
    gorulen = set()
    for i, x in enumerate(r):
        yol = f"raporlar[{i}]"
        if not alan_denetle(h, yol, x, ["rapor_kimligi", "sinif", "konum", "ilk_konum", "guven", "tespit_sayisi", "ilk_tespit", "en_yuksek_guven_tespiti"]):
            continue
        rk = x.get("rapor_kimligi")
        if not (isinstance(rk, str) and KIMLIK_RE.match(rk)):
            h.ekle(f"{yol}.rapor_kimligi", "1-64 karakter, yalnız harf/rakam/_/- olmalı")
        elif rk in gorulen:
            h.ekle(f"{yol}.rapor_kimligi", f"yinelenen rapor kimliği: {rk}")
        else:
            gorulen.add(rk)
        if x.get("sinif") not in c.model_siniflari:
            h.ekle(f"{yol}.sinif", f"MODEL_SINIFLAR değerlerinden biri olmalı ({c.model_siniflari}; bulunan: {x.get('sinif')!r})")
        k_dolu = konum_denetle(h, f"{yol}.konum", x.get("konum"))
        ik_dolu = konum_denetle(h, f"{yol}.ilk_konum", x.get("ilk_konum"))
        if (x.get("konum") is None) != (x.get("ilk_konum") is None):
            h.ekle(f"{yol}.ilk_konum", "konum ile birlikte dolu ya da birlikte null olmalı (konumsuz rapor)")
        elif k_dolu and ik_dolu:
            uz = math.hypot(x["konum"]["x_m"] - x["ilk_konum"]["x_m"], x["konum"]["y_m"] - x["ilk_konum"]["y_m"])
            if uz > c.birlestirme_aralik + 1e-9:
                h.ekle(f"{yol}.konum", f"adayın sabit ilk konumuna en çok {c.birlestirme_aralik:g} m uzaklıkta olmalı (BIRLESTIRME_ARALIK_M) (bulunan: {uz:.2f} m)")
        g = x.get("guven")
        if not (sayi_mi(g) and c.guven_esigi <= g <= 1):
            h.ekle(f"{yol}.guven", f"[{c.guven_esigi:g}, 1] aralığında sayı olmalı (en yüksek güvenli tespitin güveni; bulunan: {g!r})")
        ts = x.get("tespit_sayisi")
        if not (tam_sayi_mi(ts) and ts >= 1):
            h.ekle(f"{yol}.tespit_sayisi", "en az 1 olan tam sayı olmalı (adaydaki tespit sayısı)")
        ilk = tespit_kaynagi_denetle(h, c, f"{yol}.ilk_tespit", x.get("ilk_tespit"))
        yuk = tespit_kaynagi_denetle(h, c, f"{yol}.en_yuksek_guven_tespiti", x.get("en_yuksek_guven_tespiti"))
        if ilk is not None and yuk is not None:
            if ilk > yuk:
                h.ekle(f"{yol}.ilk_tespit", "en yüksek güvenli tespitten sonra olamaz (tespitler üretim zamanına göre işlenir)")
            if tam_sayi_mi(ts) and ts == 1 and x["ilk_tespit"] != x["en_yuksek_guven_tespiti"]:
                h.ekle(f"{yol}.en_yuksek_guven_tespiti", "tek tespitli adayda ilk tespitle aynı olmalı")
    return h.liste


def kaynak_yolu_denetle(h, yol, v):
    if not (isinstance(v, str) and v and not v.startswith("/") and ".." not in v.split("/")):
        h.ekle(yol, "koşu klasörüne göreli, boş olmayan yol (metin) olmalı; mutlak yol ve '..' yazılamaz")


def dogrula_kosu_olcum(c, d):
    """11.2 Koşu ölçüm özeti: C8/C9 üretir, E2a-E5a okur. T, D, B, L ve oranlar el kitabı terimler tablosundaki tanımlarla."""
    h = Hatalar()
    zor = ["surum", "tur", "kosu_kimligi", "sahne_kimligi", "mod", "tamamlandi", "tamamlanamadi", "t0_mono_ns", "t1_mono_ns", "t_s", "d_mb", "complete_bayt", "b_mbit_s",
           "l", "kare_sayilari", "sonuc_orani", "kare_alinamadi_orani", "kaynak_kayitlar"]
    if not alan_denetle(h, "", d, zor):
        return h.liste
    ust_alanlar(h, d, "kosu_olcum")
    mutlak_yol_tara(h, "", d)
    kosu_ust_alanlari_denetle(h, c, d)
    tam = d.get("tamamlandi")
    if not isinstance(tam, bool):
        h.ekle("tamamlandi", "true/false olmalı")
        tam = None
    t0, t1 = d.get("t0_mono_ns"), d.get("t1_mono_ns")
    for k, v in (("t0_mono_ns", t0), ("t1_mono_ns", t1)):
        if v is not None and not _poz_tam(v):
            h.ekle(k, "pozitif tam sayı (CLOCK_MONOTONIC, ns) ya da null olmalı")
    if tam_sayi_mi(t0) and tam_sayi_mi(t1) and t1 < t0:
        h.ekle("t1_mono_ns", "t0'dan önce olamaz")
    ts, dmb, b = d.get("t_s"), d.get("d_mb"), d.get("b_mbit_s")
    if tam is True:
        if d.get("tamamlanamadi") is not None:
            h.ekle("tamamlanamadi", "tamamlanan koşuda null olmalı")
        for k in ("t0_mono_ns", "t1_mono_ns", "t_s", "d_mb", "b_mbit_s", "complete_bayt"):
            if d.get(k) is None:
                h.ekle(k, "tamamlanan koşuda dolu olmalı")
        if sayi_mi(ts) and ts <= 0:
            h.ekle("t_s", "pozitif olmalı")
        if not _neg_olmayan_sayi(dmb) and dmb is not None:
            h.ekle("d_mb", "negatif olmayan sayı (MB = 10^6 bayt) olmalı")
        if d.get("complete_bayt") is not None and not _neg_olmayan_tam(d.get("complete_bayt")):
            h.ekle("complete_bayt", "negatif olmayan tam sayı olmalı (COMPLETE baytları D'ye girmez, ayrı kaydedilir)")
        if sayi_mi(ts) and tam_sayi_mi(t0) and tam_sayi_mi(t1) and abs(ts - (t1 - t0) / 1e9) > 1e-3:
            h.ekle("t_s", f"T = t1 - t0 olmalı ({(t1 - t0) / 1e9:.6f} s; bulunan: {ts})")
        if sayi_mi(b) and sayi_mi(ts) and ts > 0 and _neg_olmayan_sayi(dmb) and abs(b - 8 * dmb / ts) > OLCUM_TOL * max(1.0, abs(b)):
            h.ekle("b_mbit_s", f"B = 8·D/T olmalı ({8 * dmb / ts:.6f} Mbit/s; bulunan: {b})")
        elif b is not None and not sayi_mi(b):
            h.ekle("b_mbit_s", "sayı (Mbit/s) olmalı")
    elif tam is False:
        for k in ("t1_mono_ns", "t_s", "d_mb", "b_mbit_s", "complete_bayt"):
            if d.get(k) is not None:
                h.ekle(k, "tamamlanamayan koşuda null olmalı (T, D, B tanımsız; kısmi bilgi 'tamamlanamadi' içinde)")
        tn = d.get("tamamlanamadi")
        if alan_denetle(h, "tamamlanamadi", tn, ["neden", "gozlenen_sure_s", "kismi_trafik_mb"]):
            if tn.get("neden") not in OLCUM_TAMAMLANAMA_NEDENLERI:
                h.ekle("tamamlanamadi.neden", f"{list(OLCUM_TAMAMLANAMA_NEDENLERI)} değerlerinden biri olmalı (bulunan: {tn.get('neden')!r})")
            if not (sayi_mi(tn.get("gozlenen_sure_s")) and tn["gozlenen_sure_s"] > 0):
                h.ekle("tamamlanamadi.gozlenen_sure_s", "pozitif sayı (s; sağdan sansürlü gözlem süresi) olmalı")
            if tn.get("kismi_trafik_mb") is not None and not _neg_olmayan_sayi(tn.get("kismi_trafik_mb")):
                h.ekle("tamamlanamadi.kismi_trafik_mb", "negatif olmayan sayı (MB) ya da null olmalı")
    l = d.get("l")
    if alan_denetle(h, "l", l, ["ornek_sayisi", "ortanca_s", "p95_s"]):
        n = l.get("ornek_sayisi")
        if not _neg_olmayan_tam(n):
            h.ekle("l.ornek_sayisi", "negatif olmayan tam sayı olmalı")
        for k in ("ortanca_s", "p95_s"):
            v = l.get(k)
            if _neg_olmayan_tam(n) and n == 0:
                if v is not None:
                    h.ekle(f"l.{k}", "örnek yokken null olmalı (gecikme sıfır yazılmaz)")
            elif not _neg_olmayan_sayi(v):
                h.ekle(f"l.{k}", "negatif olmayan sayı (s) olmalı")
        if _neg_olmayan_sayi(l.get("ortanca_s")) and _neg_olmayan_sayi(l.get("p95_s")) and l["ortanca_s"] > l["p95_s"]:
            h.ekle("l.p95_s", "ortancadan küçük olamaz")
    ks = d.get("kare_sayilari")
    toplam_ok = False
    if alan_denetle(h, "kare_sayilari", ks, ["beklenen", "pozitif", "negatif", "kare_alinamadi", "islem_hatasi", "gec_geldi"]):
        toplam_ok = True
        for k in ("beklenen", "pozitif", "negatif", "kare_alinamadi", "islem_hatasi", "gec_geldi"):
            if not _neg_olmayan_tam(ks.get(k)):
                h.ekle(f"kare_sayilari.{k}", "negatif olmayan tam sayı olmalı")
                toplam_ok = False
        if toplam_ok:
            top = ks["pozitif"] + ks["negatif"] + ks["kare_alinamadi"] + ks["islem_hatasi"]
            if top > ks["beklenen"]:
                h.ekle("kare_sayilari", f"pozitif + negatif + kare_alinamadi + islem_hatasi ({top}) beklenen kare sayısını ({ks['beklenen']}) aşamaz")
            elif tam is True and top != ks["beklenen"]:
                h.ekle("kare_sayilari", f"tamamlanan koşuda her beklenen kare için sonuç ya da 'kare alınamadı' kaydı vardır: toplam ({top}) = beklenen ({ks['beklenen']}) olmalı")
            if isinstance(l, dict) and _neg_olmayan_tam(l.get("ornek_sayisi")) and l["ornek_sayisi"] > ks["pozitif"] + ks["negatif"]:
                h.ekle("l.ornek_sayisi", "başarılı kare sonucu sayısını (pozitif + negatif) aşamaz")
            if ks["gec_geldi"] > ks["beklenen"]:
                h.ekle("kare_sayilari.gec_geldi", "beklenen kare sayısını aşamaz")
    for k, pay in (("sonuc_orani", lambda s: s["pozitif"] + s["negatif"]), ("kare_alinamadi_orani", lambda s: s["kare_alinamadi"])):
        v = d.get(k)
        if toplam_ok and ks["beklenen"] == 0:
            if v is not None:
                h.ekle(k, "beklenen kare yokken null olmalı")
        elif v is None or not (sayi_mi(v) and 0 <= v <= 1):
            h.ekle(k, "[0, 1] aralığında sayı olmalı (payda: beklenen görev karesi sayısı)")
        elif toplam_ok and abs(v - pay(ks) / ks["beklenen"]) > OLCUM_TOL:
            h.ekle(k, f"kare sayılarından türeyen değerle ({pay(ks) / ks['beklenen']:.6f}) aynı olmalı (bulunan: {v})")
    kk = d.get("kaynak_kayitlar")
    if alan_denetle(h, "kaynak_kayitlar", kk, ["gorev_olay", "kare_olay", "sayac_kaydi"]):
        kaynak_yolu_denetle(h, "kaynak_kayitlar.gorev_olay", kk.get("gorev_olay"))
        kaynak_yolu_denetle(h, "kaynak_kayitlar.sayac_kaydi", kk.get("sayac_kaydi"))
        ko = kk.get("kare_olay")
        if not (isinstance(ko, list) and ko):
            h.ekle("kaynak_kayitlar.kare_olay", "en az bir dosya yolu içeren liste olmalı")
        else:
            for i, v in enumerate(ko):
                kaynak_yolu_denetle(h, f"kaynak_kayitlar.kare_olay[{i}]", v)
    return h.liste


def sayac_okumasi_denetle(h, yol, o):
    if not alan_denetle(h, yol, o, ["mono_ns", "gonderilen_bayt", "gonderilen_paket", "dusen_paket", "bekleyen_talep"]):
        return None
    if not _poz_tam(o.get("mono_ns")):
        h.ekle(f"{yol}.mono_ns", "pozitif tam sayı (CLOCK_MONOTONIC, ns) olmalı")
    ok = True
    for k in ("gonderilen_bayt", "gonderilen_paket", "dusen_paket", "bekleyen_talep"):
        if not _neg_olmayan_tam(o.get(k)):
            h.ekle(f"{yol}.{k}", "negatif olmayan tam sayı olmalı")
            ok = False
    return o if ok and _poz_tam(o.get("mono_ns")) else None


def dogrula_sayac_kaydi(c, d):
    """11.3 Sınırlayıcı bayt kaydı: C8 üretir; 11.2'deki D bu kayıttan hesaplanır (D = t1 - t0 gönderilmiş bayt farkı; COMPLETE baytları D'ye girmez, ayrı kaydedilir [belge])."""
    h = Hatalar()
    zor = ["surum", "tur", "kosu_kimligi", "mod", "sinirlayici", "t0", "t1", "complete_sonrasi", "d_bayt", "complete_bayt"]
    if not alan_denetle(h, "", d, zor):
        return h.liste
    ust_alanlar(h, d, "sayac_kaydi")
    mutlak_yol_tara(h, "", d)
    kosu_ust_alanlari_denetle(h, c, d)
    sn = d.get("sinirlayici")
    if alan_denetle(h, "sinirlayici", sn, ["cihaz", "sinif"]):
        if not (isinstance(sn.get("cihaz"), str) and sn["cihaz"]):
            h.ekle("sinirlayici.cihaz", "boş olmayan metin (ağ aygıtı adı) olmalı")
        if sn.get("sinif") != SAYAC_SINIFI:
            h.ekle("sinirlayici.sinif", f"'{SAYAC_SINIFI}' olmalı (bulunan: {sn.get('sinif')!r})")
    o0 = sayac_okumasi_denetle(h, "t0", d.get("t0"))
    o1 = sayac_okumasi_denetle(h, "t1", d.get("t1"))
    oc = None
    if d.get("complete_sonrasi") is not None:
        oc = sayac_okumasi_denetle(h, "complete_sonrasi", d["complete_sonrasi"])
    sira = [("t0", o0), ("t1", o1)] + ([("complete_sonrasi", oc)] if oc else [])
    for (a_ad, a), (b_ad, b) in zip(sira, sira[1:]):
        if a is None or b is None:
            continue
        if b["mono_ns"] < a["mono_ns"]:
            h.ekle(f"{b_ad}.mono_ns", f"{a_ad} okumasından önce olamaz")
        for k in ("gonderilen_bayt", "gonderilen_paket", "dusen_paket"):
            if b[k] < a[k]:
                h.ekle(f"{b_ad}.{k}", f"sayaç geriye gidemez ({a_ad}: {a[k]}, {b_ad}: {b[k]})")
    if o0 and o1 and tam_sayi_mi(d.get("d_bayt")) and d["d_bayt"] != o1["gonderilen_bayt"] - o0["gonderilen_bayt"]:
        h.ekle("d_bayt", f"t1 - t0 gönderilmiş bayt farkı olmalı ({o1['gonderilen_bayt'] - o0['gonderilen_bayt']}; bulunan: {d['d_bayt']})")
    elif not _neg_olmayan_tam(d.get("d_bayt")):
        h.ekle("d_bayt", "negatif olmayan tam sayı (bayt) olmalı")
    cb = d.get("complete_bayt")
    if d.get("complete_sonrasi") is None:
        if cb is not None:
            h.ekle("complete_bayt", "complete_sonrasi okunmadıysa null olmalı")
    elif o1 and oc and tam_sayi_mi(cb) and cb != oc["gonderilen_bayt"] - o1["gonderilen_bayt"]:
        h.ekle("complete_bayt", f"complete_sonrasi - t1 gönderilmiş bayt farkı olmalı ({oc['gonderilen_bayt'] - o1['gonderilen_bayt']}; bulunan: {cb})")
    elif not _neg_olmayan_tam(cb):
        h.ekle("complete_bayt", "negatif olmayan tam sayı (bayt) olmalı")
    return h.liste


# ---------------------------------------------------------------------------------------------------------------------------------
TURLER = {"sahne": dogrula_sahne, "bolge_rota": dogrula_bolge_rota, "kamera_kalibrasyon": dogrula_kalibrasyon, "hedef_listesi": dogrula_hedef_listesi,
          "kosu_ustveri": dogrula_kosu_ustveri, "nihai_rapor": dogrula_nihai_rapor, "kosu_olcum": dogrula_kosu_olcum, "sayac_kaydi": dogrula_sayac_kaydi}


JSONL_TURLERI = {"arac_durum_kaydi": dogrula_arac_durum_dosyasi, "kare_sonuc": dogrula_kare_sonuc_dosyasi, "isci_kaynak": dogrula_isci_kaynak_dosyasi, "gorev_olay": dogrula_gorev_olay_dosyasi,
                "telemetri": dogrula_telemetri_dosyasi, "kare_poz": dogrula_kare_poz_dosyasi}


def json_oku(yol):
    with open(yol, encoding="utf-8") as f:
        return json.load(f)


def ana(argv):
    yap_yolu = None
    sahne_yolu = None
    uret = None
    dosya = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__)
            return 0
        if a == "--yapilandirma" and i + 1 < len(argv):
            yap_yolu = argv[i + 1]; i += 2; continue
        if a == "--sahne" and i + 1 < len(argv):
            sahne_yolu = argv[i + 1]; i += 2; continue
        if a == "--hedef-listesi-uret" and i + 1 < len(argv):
            uret = argv[i + 1]; i += 2; continue
        if a.startswith("--") or dosya is not None:
            print(f"Bilinmeyen/yinelenen argüman: {a}", file=sys.stderr)
            return 2
        dosya = a
        i += 1
    if yap_yolu is None:
        import os
        yap_yolu = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "deney.env")
    try:
        c = Yapilandirma(yapilandirma_yukle(yap_yolu))
    except (OSError, ValueError) as e:
        print(f"Yapılandırma okunamadı ({yap_yolu}): {e}", file=sys.stderr)
        return 2
    try:
        if uret:
            d = json_oku(uret)
            hatalar = dogrula_sahne(c, d)
            if hatalar:
                for ln in hatalar:
                    print(f"HATA {uret}: {ln}", file=sys.stderr)
                return 1
            print(json.dumps(hedef_listesi_uret(d), ensure_ascii=False, indent=2))
            return 0
        if not dosya:
            print(__doc__, file=sys.stderr)
            return 2
        if dosya.endswith(".jsonl"):
            with open(dosya, encoding="utf-8") as f:
                satirlar = f.read().split("\n")
            if satirlar and satirlar[-1] == "":
                satirlar.pop()   # son satır sonu
            tur_ad = "kare_olay"
            for ham in satirlar:                     # dosya türü ilk dolu satırdaki "tur" alanından anlaşılır (öntanımlı: kare_olay)
                if ham.strip():
                    try:
                        ilk = json.loads(ham)
                        if isinstance(ilk, dict) and ilk.get("tur") in JSONL_TURLERI:
                            tur_ad = ilk["tur"]
                    except json.JSONDecodeError:
                        pass
                    break
            hatalar = JSONL_TURLERI.get(tur_ad, dogrula_kare_olay_dosyasi)(c, satirlar)
            for ln in hatalar:
                print(f"HATA {dosya}: {ln}")
            if hatalar:
                print(f"SONUÇ: GEÇERSİZ ({len(hatalar)} hata)")
                return 1
            print(f"SONUÇ: GEÇERLİ ({tur_ad}, {len(satirlar)} satır, {dosya})")
            return 0
        d = json_oku(dosya)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Dosya okunamadı/JSON geçersiz ({uret or dosya}): {e}", file=sys.stderr)
        return 2
    if not isinstance(d, dict) or d.get("tur") not in TURLER:
        print(f"HATA {dosya}: tur: {sorted(TURLER)} değerlerinden biri olmalı (bulunan: {d.get('tur') if isinstance(d, dict) else None!r})")
        print("SONUÇ: GEÇERSİZ (1 hata)")
        return 1
    if d["tur"] == "hedef_listesi":
        sahne = None
        if sahne_yolu:
            try:
                sahne = json_oku(sahne_yolu)
            except (OSError, json.JSONDecodeError) as e:
                print(f"Sahne dosyası okunamadı ({sahne_yolu}): {e}", file=sys.stderr)
                return 2
            if dogrula_sahne(c, sahne):
                print(f"Sahne dosyası geçersiz ({sahne_yolu}); önce sahneyi doğrulayın", file=sys.stderr)
                return 2
        hatalar = dogrula_hedef_listesi(c, d, sahne)
    else:
        hatalar = TURLER[d["tur"]](c, d)
    for ln in hatalar:
        print(f"HATA {dosya}: {ln}")
    if hatalar:
        print(f"SONUÇ: GEÇERSİZ ({len(hatalar)} hata)")
        return 1
    print(f"SONUÇ: GEÇERLİ ({d['tur']}, {dosya})")
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
