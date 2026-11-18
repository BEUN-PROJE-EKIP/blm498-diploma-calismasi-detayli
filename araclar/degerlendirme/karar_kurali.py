#!/usr/bin/env python3
"""Karar kuralı betiği (E4a; FR-30): E3a'nın bootstrap güven aralıklarına veri toplanmadan kilitlenen karar kuralını ölçüt ölçüt uygular.

Kullanım:
  python3 -I araclar/degerlendirme/karar_kurali.py --cikti <klasör> <bootstrap_ga.csv> [--yapilandirma config/deney.env]
Girdi:
  <bootstrap_ga.csv>   E3a çıktısı (sözleşmeler §11.4); başlık beklenen sütunlarla birebir aynı, `yeniden_ornekleme` ve `tohum` kilitli
                       yapılandırmayla (BOOTSTRAP_YENIDEN_ORNEKLEME, BOOTSTRAP_TOHUM) aynı olmalıdır.
Yapılandırma: KARAR_R_ESIK_HEDEF (2 [belge]), SAHNE_TEST_INSAN + SAHNE_TEST_ENKAZ (N, sahne başına hedef), KOSU_TEST_SAHNE_SAYISI (planlanan çift).
Çıktı (--cikti klasörüne; CSV ve Markdown, aynı veriden; sütun sırası sabit) [kararlar 2026-11-14]:
  karar   karar ölçütü başına bir satır (D, B, T, L ortanca, L p95, R farkı): GA, eşik, karar kodu ve belgedeki karar cümlesi, kalan/planlanan çift,
          koşullu olup olmadığı ve yorum notu. Tek ortak başarı kararı satırı YOKTUR [belge].
Çıkış: 0 başarılı, 1 girdi geçersiz (başlık, sayı, yinelenen ölçüt, kilitli değerden farklı tohum/yeniden örnekleme), 2 kullanım/okuma/yapılandırma hatası.

Kural [belge, el kitabı "İstatistiksel Yöntemler"; FR-30]:
  D, B, T (yüzde iyileşme) ve L (ortanca ve 95. yüzdelik farkı, merkez − uç; ayrı ayrı): pozitif iyileşme uçta mod lehinedir. GA tamamen uçta mod
  lehine (alt > 0) ise "uçta mod lehine fark gösterildi", sıfırı içeriyorsa "fark gösterilemedi", tamamen merkezi mod lehine (üst < 0) ise
  "merkezi mod lehine fark gösterildi". "Fark gösterilemedi" iki modun eşdeğer olduğu anlamına gelmez.
  R (R(uç) − R(merkez) farkı, puan): eşik e = sahne başına 2 hedefe karşılık gelen değer = −100 × 2 / N (N = 30 iken ≈ −6,67). GA alt sınırı e'den
  büyükse "uçta mod tespitte merkezi moddan belirgin biçimde geride değil"; üst sınırı e'den küçükse "uçta mod tespitte merkezi moddan belirgin
  biçimde geride"; hiçbiri sağlanmıyorsa "uçta modun tespitte merkezi moddan belirgin biçimde geride olmadığı gösterilemedi". "Geride değil"
  operasyonel yeterlilik anlamına gelmez; mutlak R değerleri ayrıca raporlanır.
  Ölçütler ayrı ayrı değerlendirilir; tek ortak başarı kararı ve tek ortak p-değeri yoktur. Tamamlanan çift sayısı planlanandan azsa karar yalnız
  tamamlanan çiftlerle sınırlı koşullu sonuçtur ve kalan çift sayısıyla verilir (FR-27).
[varsayım] GA sınırı tam olarak 0'a (ya da R eşiğine) eşitse aralık o değeri içerir sayılır (kesin eşitsizlik: "tamamen" ve "büyükse/küçükse").
GA tanımsızsa (girdi yok ya da tanımlı çift < 2) karar `tanimsiz`. `kalan_cift` ölçütün tanımlı çift sayısıdır (E3a `tanimli_sayisi`).
"""
import csv
import os
import sys

BURASI = os.path.dirname(os.path.abspath(__file__))   # araclar/degerlendirme
sys.path.insert(0, BURASI)
sys.path.insert(0, os.path.dirname(BURASI))

import bootstrap_ga as bg  # noqa: E402
import sozlesme_dogrula as sd  # noqa: E402
import tablo  # noqa: E402

# (kaynak tablo, ölçüt, kural türü, birim) — karar ölçütleri, çıktı sırası sabit [belge]
OLCUTLER = (
    ("iyilesme_sahne", "d_iyilesme_yuzde", "yuzde_iyilesme", "%"),
    ("iyilesme_sahne", "b_iyilesme_yuzde", "yuzde_iyilesme", "%"),
    ("iyilesme_sahne", "t_iyilesme_yuzde", "yuzde_iyilesme", "%"),
    ("iyilesme_sahne", "l_ortanca_fark", "gecikme_farki", "s"),
    ("iyilesme_sahne", "l_p95_fark", "gecikme_farki", "s"),
    ("eslestirme_sahne", "r_fark", "r_farki", "puan"),
)
KARAR_METNI = {   # [belge] karar cümleleri
    "uc_lehine": "uçta mod lehine fark gösterildi",
    "fark_gosterilemedi": "fark gösterilemedi",
    "merkezi_lehine": "merkezi mod lehine fark gösterildi",
    "geride_degil": "uçta mod tespitte merkezi moddan belirgin biçimde geride değil",
    "geride": "uçta mod tespitte merkezi moddan belirgin biçimde geride",
    "geride_olmadigi_gosterilemedi": "uçta modun tespitte merkezi moddan belirgin biçimde geride olmadığı gösterilemedi",
    "tanimsiz": "karar verilemedi (güven aralığı tanımsız)",
}
NOT_ESDEGER_DEGIL = "eşdeğerlik anlamına gelmez"
NOT_YETERLILIK_DEGIL = "operasyonel yeterlilik anlamına gelmez; mutlak R ayrıca raporlanır"
SUTUNLAR = ["olcut", "kaynak_tablo", "tur", "birim", "ortalama", "ga_alt", "ga_ust", "esik", "karar", "karar_metni", "kalan_cift", "planlanan_cift",
            "kosullu", "not"]
ESIK_ANAHTARI = "KARAR_R_ESIK_HEDEF"


class GirdiHatasi(ValueError):
    """Girdi tablosu beklenen biçimde değil ya da kilitli değerlerle üretilmemiş (çıkış 1)."""


def _tam_sayi(ham, anahtar, en_kucuk):
    if anahtar not in ham:
        raise ValueError(f"yapılandırmada eksik anahtar: {anahtar}")
    try:
        v = int(ham[anahtar])
    except ValueError:
        raise ValueError(f"{anahtar} tam sayı olmalı (bulunan: {ham[anahtar]!r})") from None
    if v < en_kucuk:
        raise ValueError(f"{anahtar} en az {en_kucuk} olmalı (bulunan: {v})")
    return v


def yapilandirma_yukle(yol=None):
    """Karar için kilitli değerler: {yeniden_ornekleme, tohum, r_esik_puan, n_hedef, planlanan_cift}."""
    yol = yol or os.path.join(bg.es.KOK, "config", "deney.env")
    _, _, yeniden_ornekleme, tohum = bg.yapilandirma_yukle(yol)
    ham = sd.yapilandirma_yukle(yol)
    n = _tam_sayi(ham, "SAHNE_TEST_INSAN", 0) + _tam_sayi(ham, "SAHNE_TEST_ENKAZ", 0)
    if n < 1:
        raise ValueError("SAHNE_TEST_INSAN + SAHNE_TEST_ENKAZ en az 1 olmalı")
    hedef = _tam_sayi(ham, ESIK_ANAHTARI, 0)
    return {"yeniden_ornekleme": yeniden_ornekleme, "tohum": tohum, "r_esik_puan": -100.0 * hedef / n, "n_hedef": n,
            "planlanan_cift": _tam_sayi(ham, "KOSU_TEST_SAHNE_SAYISI", 1)}


def karar_ver(tur, alt, ust, esik):
    """Kural türü ve GA'dan karar kodu [belge]. Sınıra eşitlik aralığın içinde sayılır [varsayım]."""
    if alt is None or ust is None:
        return "tanimsiz"
    if tur == "r_farki":
        if alt > esik:
            return "geride_degil"
        if ust < esik:
            return "geride"
        return "geride_olmadigi_gosterilemedi"
    if alt > 0:
        return "uc_lehine"
    if ust < 0:
        return "merkezi_lehine"
    return "fark_gosterilemedi"


def csv_oku(yol):
    """bootstrap_ga.csv → {(tablo, ölçüt): satır}. Sayısal hücreler float/int, boş hücre None. Biçim hatası GirdiHatasi."""
    with open(yol, encoding="utf-8", newline="") as f:
        satirlar = list(csv.reader(f))
    if not satirlar or satirlar[0] != bg.SUTUNLAR:
        raise GirdiHatasi(f"bootstrap_ga: başlık beklenen sütunlarla aynı değil (beklenen: {','.join(bg.SUTUNLAR)})")
    sonuc = {}
    for no, satir in enumerate(satirlar[1:], start=2):
        if len(satir) != len(bg.SUTUNLAR):
            raise GirdiHatasi(f"bootstrap_ga: satır {no}: {len(bg.SUTUNLAR)} hücre beklenir, {len(satir)} bulundu")
        k = dict(zip(bg.SUTUNLAR, satir))
        anahtar = (k["tablo"], k["olcut"])
        if anahtar in sonuc:
            raise GirdiHatasi(f"bootstrap_ga: satır {no}: yinelenen ölçüt {anahtar[0]}/{anahtar[1]}")
        try:
            for a in ("cift_sayisi", "tanimli_sayisi", "tanimsiz_sayisi", "yeniden_ornekleme", "tohum"):
                k[a] = int(k[a])
            for a in ("ortalama", "ga_alt", "ga_ust"):
                k[a] = None if k[a] == "" else float(k[a])
        except ValueError as e:
            raise GirdiHatasi(f"bootstrap_ga: satır {no}: sayı değil ({e})") from None
        if k["ga_alt"] is not None and k["ga_ust"] is not None and k["ga_alt"] > k["ga_ust"]:
            raise GirdiHatasi(f"bootstrap_ga: satır {no}: ga_alt > ga_ust")
        sonuc[anahtar] = k
    return sonuc


def analiz(ga, kilit):
    """ga: csv_oku çıktısı; kilit: yapilandirma_yukle çıktısı. Dönüş: {"karar": (sütunlar, satırlar)}. Kilitli değerden farklı tohum ya da
    yeniden örnekleme sayısıyla üretilmiş satır GirdiHatasi'dır (karar kuralı kilitli değerlerle uygulanır [FR-30])."""
    for (t, o), k in ga.items():
        if (k["yeniden_ornekleme"], k["tohum"]) != (kilit["yeniden_ornekleme"], kilit["tohum"]):
            raise GirdiHatasi(f"bootstrap_ga: {t}/{o}: yeniden örnekleme {k['yeniden_ornekleme']}, tohum {k['tohum']}; kilitli değerler "
                              f"{kilit['yeniden_ornekleme']}, {kilit['tohum']}")
    satirlar = []
    for kaynak, olcut, tur, birim in OLCUTLER:
        k = ga.get((kaynak, olcut))
        alt, ust, ortalama, kalan = (None, None, None, 0) if k is None else (k["ga_alt"], k["ga_ust"], k["ortalama"], k["tanimli_sayisi"])
        esik = kilit["r_esik_puan"] if tur == "r_farki" else 0.0
        karar = karar_ver(tur, alt, ust, esik)
        kosullu = kalan < kilit["planlanan_cift"]
        notlar = []
        if k is None:
            notlar.append("girdide ölçüt yok")
        if karar in ("fark_gosterilemedi", "geride_olmadigi_gosterilemedi"):
            notlar.append(NOT_ESDEGER_DEGIL)
        if karar == "geride_degil":
            notlar.append(NOT_YETERLILIK_DEGIL)
        if kosullu:
            notlar.append(f"koşullu: yalnız tamamlanan {kalan} çiftle sınırlı, planlanan {kilit['planlanan_cift']} çiftin tümü için geçerli değil")
        satirlar.append({"olcut": olcut, "kaynak_tablo": kaynak, "tur": tur, "birim": birim, "ortalama": ortalama, "ga_alt": alt, "ga_ust": ust,
                         "esik": esik, "karar": karar, "karar_metni": KARAR_METNI[karar], "kalan_cift": kalan,
                         "planlanan_cift": kilit["planlanan_cift"], "kosullu": kosullu, "not": "; ".join(notlar)})
    return {"karar": (list(SUTUNLAR), satirlar)}


# ---------------------------------------------------------------------------------------------------------------------------------
# Komut satırı
# ---------------------------------------------------------------------------------------------------------------------------------
def ana(argv):
    yap_yolu, cikti, dosyalar = None, None, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__)
            return 0
        if a in ("--yapilandirma", "--cikti"):
            if i + 1 >= len(argv):
                print(f"{a} bir değer ister", file=sys.stderr)
                return 2
            if a == "--yapilandirma":
                yap_yolu = argv[i + 1]
            else:
                cikti = argv[i + 1]
            i += 2
            continue
        if a.startswith("--"):
            print(f"Bilinmeyen argüman: {a}", file=sys.stderr)
            return 2
        dosyalar.append(a)
        i += 1
    if not cikti or len(dosyalar) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        kilit = yapilandirma_yukle(yap_yolu)
    except (OSError, ValueError) as e:
        print(f"Yapılandırma okunamadı/geçersiz: {e}", file=sys.stderr)
        return 2
    try:
        tablolar = analiz(csv_oku(dosyalar[0]), kilit)
    except GirdiHatasi as e:
        print(f"HATA girdi geçersiz: {e}", file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        print(f"Dosya okunamadı: {e}", file=sys.stderr)
        return 2
    try:
        yazilan = tablo.yaz(tablolar, cikti)
    except OSError as e:
        print(f"Çıktı yazılamadı: {e}", file=sys.stderr)
        return 2
    for s in tablolar["karar"][1]:
        print(f"(i) {s['olcut']}: {s['karar_metni']}" + (" (koşullu)" if s["kosullu"] else ""))
    for y in yazilan:
        print(f"(i) yazıldı: {y}")
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
