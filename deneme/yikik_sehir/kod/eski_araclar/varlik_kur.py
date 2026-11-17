#!/usr/bin/env python3
"""Sahne varlıkları (3B insan modelleri ve dokular) kurulumu ve denetimi (A1).

Kullanım:
  varlik_kur.py kur [--dry-run]   listedeki varlıkları indirir (yoksa), SHA-256 doğrular, açar, yerleştirir; zemin ağını üretir.
                                  Tekrar çalıştırılabilir: doğrulanmış zip yeniden indirilmez, kurulu klasör yeniden açılmaz.
  varlik_kur.py kontrol           indirme yapmadan kurulumu ve listeyi denetler (zip SHA-256, klasörler, doku adı tekilliği, zemin ağı).
  varlik_kur.py geometri          insan ağlarının sınır kutusunu ve yatış kaydırmalarını DAE'den hesaplar, listedekiyle karşılaştırır.

Liste: `SAHNE_VARLIK_LISTESI` (config/deney.env; varsayılan config/sahne_varliklari.json). Kurulum kökü: `SAHNE_VARLIK_KOK`
(varsayılan .generated/varliklar): indir/ (zip), modeller/ (GZ_SIM_RESOURCE_PATH'e eklenecek kök; model:// adresleri buraya çözülür).
Lisans kuralı (kararlar.md, 2026-11-14): yalnız CC0 ya da CC-BY; CC-BY'de atıf metni zorunlu. Varlık dosyaları depoya girmez.
Yalnız standart kitaplık kullanılır. Çıkış: 0 başarılı, 1 hata, 2 kullanım hatası.
"""
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DENEY_ENV = os.path.join(KOK, "config", "deney.env")
LISANSLAR = {"CC0-1.0", "CC-BY-4.0"}
DOKU_KANALLARI = {"renk": "_Color.jpg", "normal": "_NormalGL.jpg", "puruz": "_Roughness.jpg"}
ZEMIN_MODELI = "sahne_zemin"
DOKU_MODELI = "sahne_dokulari"
GEOMETRI_TOLERANS_M = 0.001
KIMLIK_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def bilgi(m):
    print(f"(i) {m}", flush=True)


def basarili(m):
    print(f"(+) {m}", flush=True)


def hata(m):
    print(f"(-) {m}", flush=True)


def uyari(m):
    print(f"(!) {m}", flush=True)


# ---------------------------------------------------------------------------------------------------------------------------------
# Yapılandırma ve liste
# ---------------------------------------------------------------------------------------------------------------------------------
def env_oku(yol=DENEY_ENV):
    veri = {}
    with open(yol, encoding="utf-8") as f:
        for ln in f:
            m = re.match(r'^([A-Z][A-Z0-9_]*)=(?:"([^"]*)"|(\S*))', ln.strip())
            if m:
                veri[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return veri


def yollar(env=None):
    env = env if env is not None else env_oku()
    liste = os.path.join(KOK, env.get("SAHNE_VARLIK_LISTESI", "config/sahne_varliklari.json"))
    kok = os.path.join(KOK, env.get("SAHNE_VARLIK_KOK", ".generated/varliklar"))
    return liste, kok, os.path.join(kok, "indir"), os.path.join(kok, "modeller")


def zemin_ag_adi(boy_m, doku_m):
    """Ağ boyu ve doku boyu dosya adına girer (ör. zemin_500m_doku_2p5m.obj): değer değişirse eski dosya yanlışlıkla kullanılmaz."""
    def ad(v):
        return f"{v:g}".replace(".", "p")
    return f"zemin_{ad(boy_m)}m_doku_{ad(doku_m)}m.obj"


def liste_yukle(yol=None, env=None):
    """Listeyi okur ve biçimini denetler; hatalar ValueError olarak (tek iletide, satır satır) döner."""
    env = env if env is not None else env_oku()
    yol = yol or yollar(env)[0]
    with open(yol, encoding="utf-8") as f:
        d = json.load(f)
    h = []
    if d.get("surum") != 1 or d.get("tur") != "sahne_varliklari":
        h.append("surum/tur: surum 1, tur 'sahne_varliklari' olmalı")
    bekl = {"surum", "tur", "aciklama", "varliklar", "zemin", "insan", "enkaz"}
    if set(d) != bekl:
        h.append(f"üst alanlar {sorted(bekl)} olmalı (bulunan: {sorted(d)})")
        raise ValueError("\n".join(h))
    varlik_alan = {"kimlik", "tur", "kaynak", "ad", "surum", "url", "sayfa", "lisans", "lisans_url", "atif", "indirme_tarihi",
                   "dosya", "boyut_bayt", "sha256", "klasor"}
    kimlikler, klasorler, dosyalar = {}, set(), set()
    for i, v in enumerate(d["varliklar"]):
        y = f"varliklar[{i}]"
        if set(v) != varlik_alan:
            h.append(f"{y}: alanlar {sorted(varlik_alan)} olmalı (eksik {sorted(varlik_alan - set(v))}, fazla {sorted(set(v) - varlik_alan)})")
            continue
        if not KIMLIK_RE.match(v["kimlik"]) or v["kimlik"] in kimlikler:
            h.append(f"{y}.kimlik: geçersiz ya da yinelenen ({v['kimlik']!r})")
        kimlikler[v["kimlik"]] = v
        if v["tur"] not in ("model", "doku"):
            h.append(f"{y}.tur: 'model' ya da 'doku' olmalı")
        if v["lisans"] not in LISANSLAR:
            h.append(f"{y}.lisans: yalnız {sorted(LISANSLAR)} (kararlar.md, lisans kuralı); bulunan {v['lisans']!r}")
        if v["lisans"].startswith("CC-BY") and not v["atif"]:
            h.append(f"{y}.atif: CC-BY varlıkta atıf metni zorunlu")
        if not re.fullmatch(r"[0-9a-f]{64}", v["sha256"]):
            h.append(f"{y}.sha256: 64 onaltılık karakter olmalı")
        if not v["url"].startswith("https://"):
            h.append(f"{y}.url: https olmalı")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.zip", v["dosya"]) or v["dosya"] in dosyalar:
            h.append(f"{y}.dosya: geçersiz ya da yinelenen ad")
        dosyalar.add(v["dosya"])
        if not KIMLIK_RE.match(v["klasor"]) or v["klasor"] in klasorler or v["klasor"] in (ZEMIN_MODELI, DOKU_MODELI):
            h.append(f"{y}.klasor: geçersiz, yinelenen ya da ayrılmış ad ({v['klasor']!r})")
        klasorler.add(v["klasor"])
    dokular = {v["klasor"] for v in d["varliklar"] if v.get("tur") == "doku"}
    modeller = {v["kimlik"]: v for v in d["varliklar"] if v.get("tur") == "model"}
    z = d["zemin"]
    if set(z) != {"ag_boyu_m", "doku_boyu_m", "varyantlar"} or not (z["ag_boyu_m"] > 0 and z["doku_boyu_m"] > 0):
        h.append("zemin: ag_boyu_m, doku_boyu_m (pozitif), varyantlar olmalı")
    zv = env["SAHNE_ZEMIN_VARYANTLARI"].split()
    if sorted(z.get("varyantlar", {})) != sorted(zv):
        h.append(f"zemin.varyantlar: anahtarlar SAHNE_ZEMIN_VARYANTLARI ile aynı olmalı ({zv})")
    for k, dk in z.get("varyantlar", {}).items():
        if dk not in dokular:
            h.append(f"zemin.varyantlar.{k}: '{dk}' listede doku olarak yok")
    iv = env["SAHNE_INSAN_VARYANTLARI"].split()
    if sorted(d["insan"].get("varyantlar", {})) != sorted(iv) or set(d["insan"]) != {"temas", "varyantlar"}:
        h.append(f"insan: temas ve varyantlar olmalı; varyant anahtarları SAHNE_INSAN_VARYANTLARI ile aynı ({iv})")
    tm = d["insan"].get("temas", {})
    if not (isinstance(tm, dict) and set(tm) == {"hucre_m", "gomulme_yuzdesi"} and tm["hucre_m"] > 0 and 0 <= tm["gomulme_yuzdesi"] < 50):
        h.append("insan.temas: hucre_m (> 0) ve gomulme_yuzdesi ([0, 50)) olmalı")
    for k, iv_ in d["insan"].get("varyantlar", {}).items():
        if set(iv_) != {"varlik", "ag", "malzeme", "on_donus_derece", "sinir_kutusu_m", "yatis_kalkma_m"}:
            h.append(f"insan.varyantlar.{k}: alanlar varlik, ag, malzeme, on_donus_derece, sinir_kutusu_m, yatis_kalkma_m olmalı")
            continue
        if iv_["on_donus_derece"] not in (0, 90, 180, 270):
            h.append(f"insan.varyantlar.{k}.on_donus_derece: 0, 90, 180 ya da 270 olmalı")
        yk = iv_["yatis_kalkma_m"]
        if not (isinstance(yk, dict) and set(yk) == {"roll+90", "roll-90"} and all(isinstance(v, (int, float)) for v in yk.values())):
            h.append(f"insan.varyantlar.{k}.yatis_kalkma_m: {{'roll+90': m, 'roll-90': m}} olmalı")
        if iv_["varlik"] not in modeller:
            h.append(f"insan.varyantlar.{k}.varlik: '{iv_['varlik']}' listede model olarak yok")
        elif not iv_["ag"].startswith(f"model://{modeller[iv_['varlik']]['klasor']}/"):
            h.append(f"insan.varyantlar.{k}.ag: model://{modeller[iv_['varlik']]['klasor']}/ ile başlamalı")
        sk = iv_["sinir_kutusu_m"]
        if not (isinstance(sk, list) and len(sk) == 2 and all(len(p) == 3 for p in sk) and all(sk[0][j] < sk[1][j] for j in range(3))):
            h.append(f"insan.varyantlar.{k}.sinir_kutusu_m: [[xmin,ymin,zmin],[xmax,ymax,zmax]] olmalı")
        if iv_["malzeme"] is not None and not (isinstance(iv_["malzeme"], dict)
                                               and set(iv_["malzeme"]) <= {"albedo_map", "normal_map", "metalness_map", "roughness_map"}):
            h.append(f"insan.varyantlar.{k}.malzeme: null ya da PBR doku haritaları sözlüğü olmalı")
    ev = env["SAHNE_ENKAZ_VARYANTLARI"].split()
    if sorted(d["enkaz"].get("varyantlar", {})) != sorted(ev) or set(d["enkaz"]) != {"varyantlar", "levha_orani"}:
        h.append(f"enkaz: varyantlar (anahtarlar SAHNE_ENKAZ_VARYANTLARI: {ev}) ve levha_orani olmalı")
    else:
        if not 0 <= d["enkaz"]["levha_orani"] <= 1:
            h.append("enkaz.levha_orani: [0, 1] olmalı")
        for k, dl in d["enkaz"]["varyantlar"].items():
            if not dl or any(x not in dokular for x in dl):
                h.append(f"enkaz.varyantlar.{k}: listedeki dokulardan en az biri olmalı ({dl})")
        # test'e özel enkaz varyantının dokuları eğitim varyantlarında bulunmaz (U17: test görünümü eğitimden ayrık)
        test_ozel = set(env["SAHNE_TEST_OZEL_ENKAZ"].split())
        egitim_doku = {x for k, dl in d["enkaz"]["varyantlar"].items() if k not in test_ozel for x in dl}
        for k in test_ozel:
            ortak = set(d["enkaz"]["varyantlar"].get(k, [])) & egitim_doku
            if ortak:
                h.append(f"enkaz.varyantlar.{k}: test'e özel varyant eğitim varyantlarıyla doku paylaşıyor ({sorted(ortak)})")
    test_ozel_insan = set(env["SAHNE_TEST_OZEL_INSAN"].split())
    egitim_insan = {v["varlik"] for k, v in d["insan"].get("varyantlar", {}).items() if k not in test_ozel_insan and isinstance(v, dict)}
    for k in test_ozel_insan:
        v = d["insan"].get("varyantlar", {}).get(k)
        if isinstance(v, dict) and v.get("varlik") in egitim_insan:
            h.append(f"insan.varyantlar.{k}: test'e özel varyant eğitim varyantlarıyla aynı modeli kullanıyor")
    if h:
        raise ValueError("\n".join(h))
    return d


# ---------------------------------------------------------------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------------------------------------------------------------
def sha256_dosya(yol):
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for p in iter(lambda: f.read(1 << 20), b""):
            h.update(p)
    return h.hexdigest()


def guvenli_ac(zip_yolu, hedef, uyelik=None):
    """Zip'i hedef klasöre açar; mutlak yol, '..' ve sembolik bağlantı reddedilir. uyelik(ad) -> yeni göreli ad ya da None (atla)."""
    with zipfile.ZipFile(zip_yolu) as z:
        for u in z.infolist():
            ad = u.filename
            if ad.endswith("/"):
                continue
            if ad.startswith("/") or ".." in ad.split("/") or (u.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"güvensiz zip üyesi: {ad!r}")
            yeni = uyelik(ad) if uyelik else ad
            if yeni is None:
                continue
            cik = os.path.join(hedef, yeni)
            if not os.path.realpath(cik).startswith(os.path.realpath(hedef) + os.sep):
                raise ValueError(f"güvensiz zip üyesi: {ad!r}")
            os.makedirs(os.path.dirname(cik), exist_ok=True)
            with z.open(u) as kaynak, open(cik, "wb") as hedef_f:
                shutil.copyfileobj(kaynak, hedef_f)


def indir(url, yol):
    gecici = yol + ".indiriliyor"
    istek = urllib.request.Request(url, headers={"User-Agent": "sahne-varlik-kurulum/1"})
    with urllib.request.urlopen(istek, timeout=300) as r, open(gecici, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(gecici, yol)


def zemin_ag_metni(boy_m, doku_m):
    """Tek dörtgen (iki üçgen), merkez orijinde, z = 0, normal +z; UV her doku_m metrede bir tekrar eder (doku sarmalanır)."""
    h = boy_m / 2
    n = boy_m / doku_m
    return ("# Otomatik üretildi (araclar/varlik_kur.py): döşemeli sahne zemini\n"
            f"v {-h:.6f} {-h:.6f} 0\nv {h:.6f} {-h:.6f} 0\nv {h:.6f} {h:.6f} 0\nv {-h:.6f} {h:.6f} 0\n"
            f"vt 0 0\nvt {n:.6f} 0\nvt {n:.6f} {n:.6f}\nvt 0 {n:.6f}\nvn 0 0 1\n"
            "f 1/1/1 2/2/1 3/3/1\nf 1/1/1 3/3/1 4/4/1\n")


def zemin_ag_yolu(modeller, z):
    return os.path.join(modeller, ZEMIN_MODELI, "meshes", zemin_ag_adi(z["ag_boyu_m"], z["doku_boyu_m"]))


def doku_dosya_adi(klasor, kanal):
    """Ogre2 doku önbelleği dosya adına göre paylaşır (prototip bulgusu): her doku dosyasının adı varlık kimliğiyle tekil olmalı."""
    return f"{klasor}_{kanal}.jpg"


# ---------------------------------------------------------------------------------------------------------------------------------
# DAE sınır kutusu (düğüm matrisleri ve birim ölçeğiyle)
# ---------------------------------------------------------------------------------------------------------------------------------
def _matris_carp(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _birim():
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def ag_noktalari(yol):
    """Ağın köşe noktaları (Z-up, metre): DAE (düğüm matrisleri, birim ve up_axis uygulanmış) ya da OBJ (olduğu gibi; Gazebo
    OBJ'yi dönüştürmeden yükler)."""
    if yol.lower().endswith(".obj"):
        pts = []
        with open(yol, encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.startswith("v "):
                    pts.append([float(v) for v in ln.split()[1:4]])
        if not pts:
            raise ValueError(f"OBJ içinde köşe yok ({yol})")
        return pts
    return dae_noktalari(yol)


def on_donuk_noktalar(yol, on_donus_derece):
    """Ağ noktaları, ağın z ekseni çevresinde `on_donus_derece` döndürülmüş (göğüs–sırt ekseni y'ye gelsin diye; listede varyant başına)."""
    a = math.radians(on_donus_derece)
    c, s = math.cos(a), math.sin(a)
    return [[c * x - s * y, s * x + c * y, z] for x, y, z in ag_noktalari(yol)]


def dae_sinir_kutusu(yol, on_donus_derece=0):
    pts = on_donuk_noktalar(yol, on_donus_derece)
    mn = [min(p[j] for p in pts) for j in range(3)]
    mx = [max(p[j] for p in pts) for j in range(3)]
    return [[round(v, 4) for v in mn], [round(v, 4) for v in mx]]


def yatis_kalkmalari(yol, hucre_m, gomulme_yuzdesi, on_donus_derece=0):
    """Yatırılmış ağın zemine oturması için dikey kaydırma (m), yatış başına.
    Modeller ayakta modellenmiştir; bütün olarak yatırılınca en uç çıkıntı (saç, el, topuk) gövdeyi havada bırakır. Bu yüzden alt
    yüzey (yatay ızgarada hücre başına en alçak nokta) çıkarılır ve hücrelerin `gomulme_yuzdesi` kadarı zemin altında kalacak
    biçimde ağ indirilir. roll +90°: yeni z = ağ y; roll −90°: yeni z = −ağ y; yatay eksenler ağ x ve z."""
    pts = on_donuk_noktalar(yol, on_donus_derece)
    sonuc = {}
    for ad, isaret in (("roll+90", 1.0), ("roll-90", -1.0)):
        alt = {}
        for x, y, z in pts:
            k = (math.floor(x / hucre_m), math.floor(z / hucre_m))
            h = isaret * y
            if h < alt.get(k, math.inf):
                alt[k] = h
        hs = sorted(alt.values())
        sonuc[ad] = round(-hs[min(len(hs) - 1, int(len(hs) * gomulme_yuzdesi / 100.0))], 4)
    return sonuc


def dae_noktalari(yol):
    """DAE ağının bütün köşe noktaları (Z-up, metre; düğüm matrisleri ve birim ölçeği uygulanmış)."""
    kok = ET.parse(yol).getroot()
    ns = kok.tag.split("}")[0] + "}" if kok.tag.startswith("{") else ""
    up = (kok.findtext(f".//{ns}asset/{ns}up_axis") or "Y_UP").strip()
    birim_e = kok.find(f".//{ns}asset/{ns}unit")
    olcek = float(birim_e.get("meter")) if birim_e is not None else 1.0
    geo = {}
    for g in kok.findall(f".//{ns}library_geometries/{ns}geometry"):
        v = g.find(f".//{ns}vertices")
        if v is None:
            continue
        kaynak = v.find(f"{ns}input[@semantic='POSITION']").get("source")[1:]
        fa = g.find(f".//{ns}source[@id='{kaynak}']/{ns}float_array")
        s = [float(x) for x in fa.text.split()]
        geo[g.get("id")] = [s[i:i + 3] for i in range(0, len(s), 3)]
    pts = []

    def dugum(n, m):
        for c in n:
            t = c.tag[len(ns):]
            if t == "matrix":
                s = [float(x) for x in c.text.split()]
                m = _matris_carp(m, [s[0:4], s[4:8], s[8:12], s[12:16]])
            elif t in ("translate", "rotate", "scale"):
                raise ValueError(f"desteklenmeyen düğüm dönüşümü: {t} ({yol})")
        for ig in n.findall(f"{ns}instance_geometry"):
            for p in geo[ig.get("url")[1:]]:
                pts.append([sum(m[i][k] * p[k] for k in range(3)) + m[i][3] for i in range(3)])
        if n.findall(f"{ns}instance_controller"):
            raise ValueError(f"iskeletli ağ desteklenmiyor ({yol})")
        for c in n.findall(f"{ns}node"):
            dugum(c, m)

    for vs in kok.findall(f".//{ns}visual_scene"):
        for n in vs.findall(f"{ns}node"):
            dugum(n, _birim())
    if up == "Y_UP":            # Gazebo (assimp) Y-up'ı Z-up'a çevirir: (x, y, z) -> (x, -z, y)
        pts = [[x, -z, y] for x, y, z in pts]
    elif up != "Z_UP":
        raise ValueError(f"desteklenmeyen up_axis: {up} ({yol})")
    return [[v * olcek for v in p] for p in pts]


def model_yolu(modeller, uri):
    assert uri.startswith("model://")
    return os.path.join(modeller, uri[len("model://"):])


# ---------------------------------------------------------------------------------------------------------------------------------
# Komutlar
# ---------------------------------------------------------------------------------------------------------------------------------
def kur(dry_run):
    env = env_oku()
    liste_yol, kok, indir_d, modeller = yollar(env)
    d = liste_yukle(liste_yol, env)
    basarili(f"Varlık listesi geçerli: {os.path.relpath(liste_yol, KOK)} ({len(d['varliklar'])} varlık)")
    if dry_run:
        for v in d["varliklar"]:
            bilgi(f"[dry-run] {v['kimlik']}: {v['url']} -> {os.path.relpath(os.path.join(indir_d, v['dosya']), KOK)} "
                  f"(SHA-256 {v['sha256'][:12]}…, {v['lisans']}) -> modeller/{DOKU_MODELI + '/' if v['tur'] == 'doku' else ''}{v['klasor']}")
        bilgi(f"[dry-run] zemin ağı: modeller/{ZEMIN_MODELI}/meshes/{zemin_ag_adi(d['zemin']['ag_boyu_m'], d['zemin']['doku_boyu_m'])}")
        return 0
    os.makedirs(indir_d, exist_ok=True)
    os.makedirs(modeller, exist_ok=True)
    hatali = 0
    for v in d["varliklar"]:
        zy = os.path.join(indir_d, v["dosya"])
        if not (os.path.isfile(zy) and sha256_dosya(zy) == v["sha256"]):
            bilgi(f"{v['kimlik']}: indiriliyor ({v['url']})")
            try:
                indir(v["url"], zy)
            except OSError as e:
                hata(f"{v['kimlik']}: indirilemedi: {e}")
                hatali += 1
                continue
        s = sha256_dosya(zy)
        if s != v["sha256"]:
            hata(f"{v['kimlik']}: SHA-256 uyuşmuyor (beklenen {v['sha256'][:12]}…, bulunan {s[:12]}…); dosya kullanılmadı")
            hatali += 1
            continue
        basarili(f"{v['kimlik']}: SHA-256 doğrulandı ({v['lisans']})")
        hedef = os.path.join(modeller, DOKU_MODELI, v["klasor"]) if v["tur"] == "doku" else os.path.join(modeller, v["klasor"])
        isaret = os.path.join(hedef, ".kurulu_sha256")
        if os.path.isfile(isaret) and open(isaret).read().strip() == v["sha256"]:
            continue
        gecici = tempfile.mkdtemp(prefix=".kurulum_", dir=modeller)
        try:
            if v["tur"] == "doku":
                def secim(ad, k=v["klasor"]):
                    for kanal, son in DOKU_KANALLARI.items():
                        if ad == f"{k}_1K-JPG{son}":
                            return doku_dosya_adi(k, kanal)
                    return None
                guvenli_ac(zy, gecici, secim)
                eksik = [kn for kn in DOKU_KANALLARI if not os.path.isfile(os.path.join(gecici, doku_dosya_adi(v["klasor"], kn)))]
                if eksik:
                    raise ValueError(f"zip içinde beklenen doku kanalları yok: {eksik}")
            else:
                guvenli_ac(zy, gecici)
            with open(os.path.join(gecici, ".kurulu_sha256"), "w") as f:
                f.write(v["sha256"] + "\n")
            if os.path.isdir(hedef):
                shutil.rmtree(hedef)
            os.makedirs(os.path.dirname(hedef), exist_ok=True)
            os.replace(gecici, hedef)
            basarili(f"{v['kimlik']}: kuruldu -> {os.path.relpath(hedef, KOK)}")
        except (ValueError, zipfile.BadZipFile, OSError) as e:
            hata(f"{v['kimlik']}: açılamadı: {e}")
            hatali += 1
        finally:
            if os.path.isdir(gecici):
                shutil.rmtree(gecici)
    zy = zemin_ag_yolu(modeller, d["zemin"])
    os.makedirs(os.path.dirname(zy), exist_ok=True)
    metin = zemin_ag_metni(d["zemin"]["ag_boyu_m"], d["zemin"]["doku_boyu_m"])
    if not (os.path.isfile(zy) and open(zy, encoding="utf-8").read() == metin):
        with open(zy, "w", encoding="utf-8") as f:
            f.write(metin)
    basarili(f"Zemin ağı: {os.path.relpath(zy, KOK)}")
    if hatali:
        hata(f"Varlık kurulumu: {hatali} hata")
        return 1
    return kontrol()


def kontrol():
    env = env_oku()
    liste_yol, kok, indir_d, modeller = yollar(env)
    try:
        d = liste_yukle(liste_yol, env)
    except (ValueError, OSError, KeyError) as e:
        hata(f"Varlık listesi geçersiz: {e}")
        return 1
    basarili(f"Varlık listesi geçerli ({len(d['varliklar'])} varlık; lisanslar: "
             f"{', '.join(sorted({v['lisans'] for v in d['varliklar']}))})")
    sayac = {"ok": 0, "hata": 0}

    def denet(kosul, ok_ileti, hata_ileti):
        (basarili if kosul else hata)(ok_ileti if kosul else hata_ileti)
        sayac["ok" if kosul else "hata"] += 1

    for v in d["varliklar"]:
        zy = os.path.join(indir_d, v["dosya"])
        var = os.path.isfile(zy)
        denet(var and sha256_dosya(zy) == v["sha256"], f"{v['kimlik']}: zip SHA-256 uyuşuyor",
              f"{v['kimlik']}: zip yok ya da SHA-256 uyuşmuyor ({os.path.relpath(zy, KOK)}); `araclar/varlik_kur.py kur`")
        hedef = os.path.join(modeller, DOKU_MODELI, v["klasor"]) if v["tur"] == "doku" else os.path.join(modeller, v["klasor"])
        isaret = os.path.join(hedef, ".kurulu_sha256")
        denet(os.path.isfile(isaret) and open(isaret).read().strip() == v["sha256"], f"{v['kimlik']}: kurulu",
              f"{v['kimlik']}: kurulu değil ya da eski ({os.path.relpath(hedef, KOK)})")
    for k, iv in d["insan"]["varyantlar"].items():
        denet(os.path.isfile(model_yolu(modeller, iv["ag"])), f"{k}: ağ dosyası var", f"{k}: ağ dosyası yok ({iv['ag']})")
        for harita in (iv["malzeme"] or {}).values():
            denet(os.path.isfile(model_yolu(modeller, harita)), f"{k}: doku haritası var ({os.path.basename(harita)})",
                  f"{k}: doku haritası yok ({harita})")
    # Ogre2 dosya adına göre önbellekler: aynı adlı iki dokunun içeriği aynı olmalı
    adlar = {}
    for kok_d, alt, dosyalar in os.walk(modeller):
        alt[:] = [a for a in alt if a != "thumbnails"]      # Fuel küçük resimleri render edilmez
        for f in dosyalar:
            if f.lower().endswith((".png", ".jpg", ".jpeg")):
                adlar.setdefault(f, set()).add(sha256_dosya(os.path.join(kok_d, f)))
    cakisan = sorted(a for a, s in adlar.items() if len(s) > 1)
    denet(not cakisan, f"Doku dosya adları tekil ya da aynı içerikli ({len(adlar)} ad)",
          f"Aynı adlı farklı içerikli doku dosyaları (Ogre2 önbelleği karıştırır): {cakisan}")
    zy = zemin_ag_yolu(modeller, d["zemin"])
    denet(os.path.isfile(zy) and open(zy, encoding="utf-8").read() == zemin_ag_metni(d["zemin"]["ag_boyu_m"], d["zemin"]["doku_boyu_m"]),
          "Zemin ağı güncel", f"Zemin ağı yok ya da eski ({os.path.relpath(zy, KOK)})")
    print(f"Özet: {sayac['ok']} başarılı, {sayac['hata']} başarısız, 0 uyarı")
    if sayac["hata"]:
        hata("Sahne varlıkları denetimi BAŞARISIZ")
        return 1
    basarili("Sahne varlıkları denetimi geçti")
    return 0


def geometri():
    env = env_oku()
    liste_yol, _, _, modeller = yollar(env)
    d = liste_yukle(liste_yol, env)
    rc = 0
    tm = d["insan"]["temas"]
    for k, iv in sorted(d["insan"]["varyantlar"].items()):
        yol = model_yolu(modeller, iv["ag"])
        hesap = dae_sinir_kutusu(yol, iv["on_donus_derece"])
        fark = max(abs(a - b) for p, q in zip(hesap, iv["sinir_kutusu_m"]) for a, b in zip(p, q))
        boy = [round(hesap[1][j] - hesap[0][j], 3) for j in range(3)]
        if fark <= GEOMETRI_TOLERANS_M:
            basarili(f"{k}: sınır kutusu listeyle aynı {hesap} (boyut x×y×z = {boy[0]}×{boy[1]}×{boy[2]} m)")
        else:
            hata(f"{k}: sınır kutusu listeden farklı (en büyük fark {fark:.4f} m): hesaplanan {json.dumps(hesap)}")
            rc = 1
        kalk = yatis_kalkmalari(yol, tm["hucre_m"], tm["gomulme_yuzdesi"], iv["on_donus_derece"])
        fark = max(abs(kalk[y] - iv["yatis_kalkma_m"][y]) for y in kalk)
        if fark <= GEOMETRI_TOLERANS_M:
            basarili(f"{k}: yatış kaydırmaları listeyle aynı {kalk}")
        else:
            hata(f"{k}: yatış kaydırmaları listeden farklı (en büyük fark {fark:.4f} m): hesaplanan {json.dumps(kalk)}")
            rc = 1
    return rc


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    komut, ek = argv[0], argv[1:]
    try:
        if komut == "kur" and ek in ([], ["--dry-run"]):
            return kur(ek == ["--dry-run"])
        if komut == "kontrol" and not ek:
            return kontrol()
        if komut == "geometri" and not ek:
            return geometri()
    except (ValueError, OSError, KeyError) as e:
        hata(str(e))
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
