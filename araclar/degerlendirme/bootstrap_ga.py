#!/usr/bin/env python3
"""Bootstrap betiği (E3a; FR-29): E1a ve E2a'nın sahne tablolarındaki her ölçütün sahne başına ortalaması için %95 percentile bootstrap güven
aralığını hesaplar; yeniden örnekleme sahne (çift) düzeyindedir, eşleştirme bozulmaz.

Kullanım:
  python3 -I araclar/degerlendirme/bootstrap_ga.py --cikti <klasör> [--eslestirme-sahne <eslestirme_sahne.csv>] [--iyilesme-sahne <iyilesme_sahne.csv>]
                                                   [--yapilandirma config/deney.env]
Girdi (en az biri):
  --eslestirme-sahne   E1a çıktısı `eslestirme_sahne.csv` (sözleşmeler §11.4); başlık satırı beklenen sütunlarla birebir aynı olmalı.
  --iyilesme-sahne     E2a çıktısı `iyilesme_sahne.csv` (sözleşmeler §11.4); başlık satırı beklenen sütunlarla birebir aynı olmalı.
Yapılandırma: BOOTSTRAP_YENIDEN_ORNEKLEME (10.000 [belge]), BOOTSTRAP_TOHUM ([varsayım]; sabit ve kayıtlı, C13'te dondurulur).
Çıktı (--cikti klasörüne; CSV ve Markdown, aynı veriden; sütun sırası sabit) [kararlar 2026-11-14]:
  bootstrap_ga   ölçüt başına: kaynak tablo, ölçüt, çift sayısı, tanımlı/tanımsız sayısı, ortalama, %95 GA alt ve üst sınırı, yeniden örnekleme, tohum
Çıkış: 0 başarılı, 1 girdi geçersiz (başlık uyuşmuyor, sayı olmayan hücre, yinelenen sahne), 2 kullanım/okuma/yapılandırma hatası.

Yöntem [belge, el kitabı "İstatistiksel Yöntemler"; FR-29]: güven aralıkları 10.000 kez sahne/çift düzeyinde yeniden örnekleme yapılan percentile
bootstrap ile hesaplanır; eşleştirme bozulmaz. Bir sahne satırı iki modun değerini ve farkını birlikte taşıdığından satırlar (sahneler) yerine
koyarak çekilir: bir çiftin uçta ve merkezi değeri hep birlikte seçilir. Tahmin, sahne başına değerlerin aritmetik ortalamasıdır; GA, bootstrap
ortalamalarının 2,5. ve 97,5. yüzdelikleridir.
[varsayım] (1) Tanımsız değer (boş hücre) taşıyan sahne o ölçütün hesabından çıkarılır ve yeniden örnekleme yalnız tanımlı sahneler arasında
yapılır; çıkarılan sahne sayısı `tanimsiz_sayisi` sütunundadır. (2) Tanımlı sahne sayısı 2'den azsa GA tanımsızdır (tek değerden aralık kurulmaz).
(3) Yüzdelik yöntemi numpy'nin varsayılanıdır (doğrusal ara değer, Hyndman–Fan tip 7). (4) Her ölçüt aynı tohumla başlayan ayrı bir üreteç
kullanır: sonuç sütun sırasından bağımsızdır ve tanımlı sahne sayısı aynı olan ölçütler aynı yeniden örnekleri (aynı sahne seçimlerini) paylaşır.
"""
import csv
import os
import sys

BURASI = os.path.dirname(os.path.abspath(__file__))   # araclar/degerlendirme
sys.path.insert(0, BURASI)
sys.path.insert(0, os.path.dirname(BURASI))

import numpy as np  # noqa: E402

import eslestirme as es  # noqa: E402
import eslestirme_analiz as ea  # noqa: E402
import iyilesme_analiz as ia  # noqa: E402
import sozlesme_dogrula as sd  # noqa: E402
import tablo  # noqa: E402

GA_DUZEYI = 0.95   # [belge] %95
SAYI_ANAHTARI, TOHUM_ANAHTARI = "BOOTSTRAP_YENIDEN_ORNEKLEME", "BOOTSTRAP_TOHUM"
SUTUNLAR = ["tablo", "olcut", "cift_sayisi", "tanimli_sayisi", "tanimsiz_sayisi", "ortalama", "ga_alt", "ga_ust", "yeniden_ornekleme", "tohum"]


class GirdiHatasi(ValueError):
    """Girdi tablosu beklenen biçimde değil (çıkış 1)."""


def yapilandirma_yukle(yol=None):
    """(Yapilandirma, eşleştirme eşiği, yeniden örnekleme sayısı, tohum). Eksik ya da geçersiz anahtar ValueError'dur."""
    yol = yol or os.path.join(es.KOK, "config", "deney.env")
    c, esik = es.yapilandirma_yukle(yol)
    ia._modlar(c)
    ham = sd.yapilandirma_yukle(yol)
    degerler = []
    for anahtar, en_kucuk in ((SAYI_ANAHTARI, 1), (TOHUM_ANAHTARI, 0)):
        if anahtar not in ham:
            raise ValueError(f"yapılandırmada eksik anahtar: {anahtar}")
        try:
            v = int(ham[anahtar])
        except ValueError:
            raise ValueError(f"{anahtar} tam sayı olmalı (bulunan: {ham[anahtar]!r})") from None
        if v < en_kucuk:
            raise ValueError(f"{anahtar} en az {en_kucuk} olmalı (bulunan: {v})")
        degerler.append(v)
    return c, esik, degerler[0], degerler[1]


def beklenen_sutunlar(c, esik):
    """Girdi tablolarının sabit sütunları; E1a ve E2a'nın boş girdiyle ürettiği başlıktan alınır (tek kaynak)."""
    return {"eslestirme_sahne": ea.analiz(c, esik, [], [])["eslestirme_sahne"][0], "iyilesme_sahne": ia.analiz(c, [])["iyilesme_sahne"][0]}


def ortalama_ga(degerler, yeniden_ornekleme, tohum):
    """Sahne değerleri (None = tanımsız) için (tanımlı sayısı, ortalama, GA alt, GA üst). Tanımsızlar çıkarılır [varsayım 1]; tanımlı < 2 ise GA
    None [varsayım 2]; yüzdelik numpy varsayılanı [varsayım 3]; her çağrı aynı tohumla yeni üreteç [varsayım 4]."""
    x = np.asarray([v for v in degerler if v is not None], dtype=float)
    n = len(x)
    if n == 0:
        return 0, None, None, None
    ortalama = float(x.mean())
    if n < 2:
        return n, ortalama, None, None
    secim = np.random.default_rng(tohum).integers(0, n, size=(yeniden_ornekleme, n))   # satır = bir bootstrap örneği (sahne sıraları)
    ornek_ortalamalari = x[secim].mean(axis=1)
    alt, ust = np.percentile(ornek_ortalamalari, [100 * (1 - GA_DUZEYI) / 2, 100 * (1 + GA_DUZEYI) / 2])
    return n, ortalama, float(alt), float(ust)


def csv_oku(yol, ad, beklenen):
    """Sahne tablosunu okur: [{sütun: değer}], değer float ya da None (boş hücre). Biçim hatası GirdiHatasi."""
    with open(yol, encoding="utf-8", newline="") as f:
        satirlar = list(csv.reader(f))
    if not satirlar or satirlar[0] != beklenen:
        bulunan = satirlar[0] if satirlar else []
        raise GirdiHatasi(f"{ad}: başlık beklenen sütunlarla aynı değil (beklenen {len(beklenen)} sütun, bulunan {len(bulunan)}; ilk fark: "
                          f"{next((f'{b!r} ≠ {g!r}' for b, g in zip(beklenen, bulunan) if b != g), 'sütun sayısı')})")
    sonuc, gorulen = [], set()
    for no, satir in enumerate(satirlar[1:], start=2):
        if len(satir) != len(beklenen):
            raise GirdiHatasi(f"{ad}: satır {no}: {len(beklenen)} hücre beklenir, {len(satir)} bulundu")
        sahne = satir[0]
        if not sahne or sahne in gorulen:
            raise GirdiHatasi(f"{ad}: satır {no}: boş ya da yinelenen sahne kimliği {sahne!r}")
        gorulen.add(sahne)
        kayit = {"sahne_kimligi": sahne}
        for sutun, hucre in zip(beklenen[1:], satir[1:]):
            if hucre == "":
                kayit[sutun] = None
                continue
            try:
                v = float(hucre)
            except ValueError:
                raise GirdiHatasi(f"{ad}: satır {no}, sütun {sutun}: sayı değil ({hucre!r})") from None
            if not np.isfinite(v):
                raise GirdiHatasi(f"{ad}: satır {no}, sütun {sutun}: sonlu sayı olmalı ({hucre!r})")
            kayit[sutun] = v
        sonuc.append(kayit)
    return sonuc


def analiz(girdiler, yeniden_ornekleme, tohum):
    """girdiler: [(tablo adı, sütunlar, satırlar)] (satırlar csv_oku biçiminde). Dönüş: {"bootstrap_ga": (sütunlar, satırlar)}."""
    cikti = []
    for ad, sutunlar, satirlar in girdiler:
        for olcut in sutunlar[1:]:
            degerler = [s[olcut] for s in satirlar]
            n, ortalama, alt, ust = ortalama_ga(degerler, yeniden_ornekleme, tohum)
            cikti.append({"tablo": ad, "olcut": olcut, "cift_sayisi": len(degerler), "tanimli_sayisi": n, "tanimsiz_sayisi": len(degerler) - n,
                          "ortalama": ortalama, "ga_alt": alt, "ga_ust": ust, "yeniden_ornekleme": yeniden_ornekleme, "tohum": tohum})
    return {"bootstrap_ga": (list(SUTUNLAR), cikti)}


# ---------------------------------------------------------------------------------------------------------------------------------
# Komut satırı
# ---------------------------------------------------------------------------------------------------------------------------------
def ana(argv):
    secenekler = {"--yapilandirma": None, "--cikti": None, "--eslestirme-sahne": None, "--iyilesme-sahne": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__)
            return 0
        if a not in secenekler:
            print(f"Bilinmeyen argüman: {a}", file=sys.stderr)
            return 2
        if i + 1 >= len(argv):
            print(f"{a} bir değer ister", file=sys.stderr)
            return 2
        secenekler[a] = argv[i + 1]
        i += 2
    tablo_yollari = [("eslestirme_sahne", secenekler["--eslestirme-sahne"]), ("iyilesme_sahne", secenekler["--iyilesme-sahne"])]
    tablo_yollari = [(ad, y) for ad, y in tablo_yollari if y]
    if not (secenekler["--cikti"] and tablo_yollari):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        c, esik, yeniden_ornekleme, tohum = yapilandirma_yukle(secenekler["--yapilandirma"])
    except (OSError, ValueError) as e:
        print(f"Yapılandırma okunamadı/geçersiz: {e}", file=sys.stderr)
        return 2
    beklenen = beklenen_sutunlar(c, esik)
    try:
        girdiler = [(ad, beklenen[ad], csv_oku(y, ad, beklenen[ad])) for ad, y in tablo_yollari]
    except GirdiHatasi as e:
        print(f"HATA girdi geçersiz: {e}", file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        print(f"Dosya okunamadı: {e}", file=sys.stderr)
        return 2
    tablolar = analiz(girdiler, yeniden_ornekleme, tohum)
    try:
        yazilan = tablo.yaz(tablolar, secenekler["--cikti"])
    except OSError as e:
        print(f"Çıktı yazılamadı: {e}", file=sys.stderr)
        return 2
    print(f"(+) {len(tablolar['bootstrap_ga'][1])} ölçüt, {yeniden_ornekleme} yeniden örnekleme, tohum {tohum}")
    for y in yazilan:
        print(f"(i) yazıldı: {y}")
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
