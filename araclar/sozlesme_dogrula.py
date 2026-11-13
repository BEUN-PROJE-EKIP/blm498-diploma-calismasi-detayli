#!/usr/bin/env python3
"""Sözleşme dosyası doğrulayıcı: sahne, bölge/rota, kamera kalibrasyonu, hedef listesi, koşu üst verisi (JSON), kare olay kaydı ve araç durum kaydı (JSON Lines).

Kullanım:
  sozlesme_dogrula.py [--yapilandirma config/deney.env] <dosya.json> [--sahne sahne.json]
  sozlesme_dogrula.py [--yapilandirma ...] --hedef-listesi-uret <sahne.json>
Dosya türü dosyadaki "tur" alanından anlaşılır (sahne | bolge_rota | kamera_kalibrasyon | hedef_listesi | kosu_ustveri).
Uzantısı .jsonl olan dosya JSON Lines'tır (satır başına bir JSON nesnesi): tur: kare_olay (öntanımlı) ya da tur: arac_durum_kaydi (ilk dolu satırdan anlaşılır).
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
        "CAM_RATE_HZ KOSU_MIMARILER"
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
OLAY_TURLERI = ("uretim", "kuyruga_giris", "aktarim_tamam", "cikarim_basi", "cikarim_sonu", "kullanilabilir")
UYGULANMAZ_OLABILEN = ("kuyruga_giris", "aktarim_tamam")   # [belge] yalnız aktarım aşamaları "uygulanmaz" olabilir
KAYNAKLAR = ("gazebo_damga", "kamera_alicisi", "arac_sureci", "cikarim_iscisi", "yer_istasyonu")
SONUC_DURUMLARI = ("sonuc", "tespit_yok", "kare_alinamadi", "gec_geldi")
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
    zorunlu = ["surum", "tur", "kosu_kimligi", "baslangic", "bitis", "depo", "yapilandirma_sha256", "ortam_kilidi_sha256", "arac_sayisi",
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
    for k in ("yapilandirma_sha256", "ortam_kilidi_sha256"):
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
    if not alan_denetle(h, "", d, ["surum", "tur", "kaynak", "arac_kimligi", "n", "sim_damga_ns", "olay", "mono_ns"], ["sonuc_durumu"]):
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
    elif "sonuc_durumu" in d:
        h.ekle("sonuc_durumu", "yalnız 'kullanilabilir' olayında bulunabilir")
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
        anahtar = (d["arac_kimligi"], d["n"], d["sim_damga_ns"], d["olay"])
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


# ---------------------------------------------------------------------------------------------------------------------------------
TURLER = {"sahne": dogrula_sahne, "bolge_rota": dogrula_bolge_rota, "kamera_kalibrasyon": dogrula_kalibrasyon, "hedef_listesi": dogrula_hedef_listesi,
          "kosu_ustveri": dogrula_kosu_ustveri}


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
                        if isinstance(ilk, dict) and ilk.get("tur") == "arac_durum_kaydi":
                            tur_ad = "arac_durum_kaydi"
                    except json.JSONDecodeError:
                        pass
                    break
            hatalar = dogrula_arac_durum_dosyasi(c, satirlar) if tur_ad == "arac_durum_kaydi" else dogrula_kare_olay_dosyasi(c, satirlar)
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
