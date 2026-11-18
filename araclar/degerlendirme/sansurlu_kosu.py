#!/usr/bin/env python3
"""Sansürlü koşu betiği (E5a; FR-27): tamamlanamayan koşuları sağdan sansürlü süre ve kısmi trafikle gösterir; sahne çiftlerinin durumunu ve
tamamlanan çiftlerle sınırlı koşullu analizin kapsamını (kaç çift kaldığı) özetler.

Kullanım:
  python3 -I araclar/degerlendirme/sansurlu_kosu.py --cikti <klasör> <kosu_olcum.json> [<kosu_olcum.json> ...] [--yapilandirma config/deney.env]
Girdi:
  <kosu_olcum.json>    koşu başına koşu ölçüm özeti (sözleşmeler §11.2), tamamlanan ve tamamlanamayan BÜTÜN koşular; sahne ve mod dosyanın içinden
                       okunur. Aynı sahne ve modda iki özet hatadır.
Yapılandırma: ZAMAN_ASIMI_H_SN (H; boşsa henüz hesaplanmadı, C12), KOSU_TEST_SAHNE_SAYISI (planlanan çift), KOSU_MIMARILER.
Çıktı (--cikti klasörüne; her tablo CSV ve Markdown, aynı veriden; sütun sırası sabit) [kararlar 2026-11-14]:
  sansurlu_kosu   tamamlanamayan koşu başına: neden, gözlenen süre, H, sağdan sansürlü süre alt sınırı (T ≥ alt sınır), kısmi trafik
  sansurlu_cift   sahne başına iki modun durumu (`tamamlandi` | `tamamlanamadi` | `kosu_olcum_yok`) ve çiftin analize girip girmediği
  sansurlu_ozet   mod başına ve çift düzeyinde: planlanan, kayıtlı, tamamlanan, tamamlanamayan, nedenlere göre sayılar, kaydı olmayan, koşullu mu
Çıkış: 0 başarılı, 1 girdi geçersiz (sözleşme hatası, yinelenen koşu, planlanandan fazla sahne, H'den kısa zaman aşımı), 2 kullanım/okuma/yapılandırma hatası.

Kurallar [belge, el kitabı "İstatistiksel Yöntemler", "Riskler"; FR-27]:
  H dolduğunda COMPLETE yayımlanmamış koşu "tamamlanamadı" olarak kaydedilir; süresi başarılı görev süresi gibi ortalamaya katılmaz, en az zaman
  aşımı kadar olarak sağdan sansürlü gösterilir; o ana kadarki baytlar kısmi trafik olarak tutulur. Mimari kaynaklı zaman aşımı veya taşma seçilerek
  dışlanmaz: bu betik verilen bütün tamamlanamayan koşuları listeler ve sayar. Mimariye bağlı tek bir koşu dahi tamamlanamazsa karar etiketleri
  bütün planlanan koşular için geçerli sayılmaz; tamamlanan çiftlerin analizi koşullu sonuç olarak ve kaç çiftin kaldığı belirtilerek sunulur.
[varsayım] (1) Sansürlü alt sınır = max(gözlenen süre, H); H boşsa gözlenen süre (H tanımsız yazılır). Koşu H dolmadan bittiyse de (süreç ölümü,
taşma) COMPLETE hiç yayımlanmayacağından T ≥ H'dir. (2) Nedeni `zaman_asimi` olan koşunun gözlenen süresi H'den kısa olamaz (1 ms pay). (3) Teknik
geçersizlik (haricî dosya bozulması, kayıt aracının çökmesi) nedeniyle yeniden çalıştırılan çiftin eski koşuları girdiye verilmez; sözleşmede
ayrı bir neden kodu yoktur. (4) Kaydı olmayan çift sayısı = planlanan − kayıtlı sahne; sahne kimlikleri planlanan listeyle denetlenmez.
"""
import json
import os
import sys

BURASI = os.path.dirname(os.path.abspath(__file__))   # araclar/degerlendirme
sys.path.insert(0, BURASI)
sys.path.insert(0, os.path.dirname(BURASI))

import iyilesme_analiz as ia  # noqa: E402
import sozlesme_dogrula as sd  # noqa: E402
import tablo  # noqa: E402

UC, MERKEZ = ia.UC, ia.MERKEZ
NEDENLER = ("zaman_asimi", "kuyruk_tasmasi", "surec_olumu", "diger")   # sözleşmeler §11.2 `tamamlanamadi.neden`
DURUM_TAMAM, DURUM_TAMAMLANAMADI, DURUM_YOK = "tamamlandi", "tamamlanamadi", "kosu_olcum_yok"
H_PAYI_S = 1e-3
H_ANAHTARI = "ZAMAN_ASIMI_H_SN"


class GirdiHatasi(ValueError):
    """Girdi dosyası sözleşmeye uymuyor ya da tutarsız (çıkış 1)."""


def yapilandirma_yukle(yol=None):
    """(Yapilandirma, H s ya da None, planlanan çift)."""
    yol = yol or os.path.join(ia.KOK, "config", "deney.env")
    c = ia.yapilandirma_yukle(yol)
    ham = sd.yapilandirma_yukle(yol)
    if H_ANAHTARI not in ham:
        raise ValueError(f"yapılandırmada eksik anahtar: {H_ANAHTARI} (henüz hesaplanmadıysa boş bırakılır)")
    h = None
    if ham[H_ANAHTARI] != "":
        try:
            h = float(ham[H_ANAHTARI])
        except ValueError:
            raise ValueError(f"{H_ANAHTARI} sayı ya da boş olmalı (bulunan: {ham[H_ANAHTARI]!r})") from None
        if not (h > 0 and h != float("inf")):
            raise ValueError(f"{H_ANAHTARI} pozitif sonlu sayı olmalı (bulunan: {h!r})")
    try:
        planlanan = int(ham.get("KOSU_TEST_SAHNE_SAYISI", ""))
    except ValueError:
        raise ValueError(f"KOSU_TEST_SAHNE_SAYISI tam sayı olmalı (bulunan: {ham.get('KOSU_TEST_SAHNE_SAYISI')!r})") from None
    if planlanan < 1:
        raise ValueError("KOSU_TEST_SAHNE_SAYISI en az 1 olmalı")
    return c, h, planlanan


def sansur_alt_siniri(gozlenen_s, h_s):
    """[varsayım 1] Sağdan sansürlü süre alt sınırı (T ≥ değer)."""
    return gozlenen_s if h_s is None else max(gozlenen_s, h_s)


def analiz(c, h_s, planlanan, kosu_olcumleri):
    """Bütün tabloları hesaplar. Dönüş: {tablo_adı: (sütunlar, satırlar)}. Girdi hatası GirdiHatasi."""
    modlar = ia._modlar(c)
    olcum = {}
    for o in kosu_olcumleri:
        hatalar = sd.dogrula_kosu_olcum(c, o)
        if hatalar:
            raise GirdiHatasi("kosu_olcum: " + "; ".join(hatalar))
        anahtar = (o["sahne_kimligi"], o["mod"])
        if anahtar in olcum:
            raise GirdiHatasi(f"yinelenen koşu ölçüm özeti: sahne '{anahtar[0]}', mod '{anahtar[1]}'")
        tn = o["tamamlanamadi"]
        if (not o["tamamlandi"] and h_s is not None and tn["neden"] == "zaman_asimi" and tn["gozlenen_sure_s"] < h_s - H_PAYI_S):
            raise GirdiHatasi(f"{o['kosu_kimligi']}: neden zaman_asimi ama gözlenen süre ({tn['gozlenen_sure_s']} s) H'den ({h_s} s) kısa")
        olcum[anahtar] = o
    sahneler = sorted({s for s, _ in olcum})
    if len(sahneler) > planlanan:
        raise GirdiHatasi(f"kayıtlı sahne sayısı ({len(sahneler)}) planlanandan ({planlanan}) fazla")

    def sira(a):
        return (a[0], modlar.index(a[1]) if a[1] in modlar else len(modlar), a[1])

    # 1) tamamlanamayan koşular
    k_sutun = ["sahne_kimligi", "mod", "kosu_kimligi", "neden", "gozlenen_sure_s", "h_s", "t_alt_sinir_s", "kismi_trafik_mb"]
    k_satir = []
    for anahtar in sorted(olcum, key=sira):
        o = olcum[anahtar]
        if o["tamamlandi"]:
            continue
        tn = o["tamamlanamadi"]
        k_satir.append({"sahne_kimligi": anahtar[0], "mod": anahtar[1], "kosu_kimligi": o["kosu_kimligi"], "neden": tn["neden"],
                        "gozlenen_sure_s": float(tn["gozlenen_sure_s"]), "h_s": h_s,
                        "t_alt_sinir_s": float(sansur_alt_siniri(tn["gozlenen_sure_s"], h_s)),
                        "kismi_trafik_mb": None if tn["kismi_trafik_mb"] is None else float(tn["kismi_trafik_mb"])})

    # 2) sahne çiftleri
    def durum(s, m):
        o = olcum.get((s, m))
        return DURUM_YOK if o is None else (DURUM_TAMAM if o["tamamlandi"] else DURUM_TAMAMLANAMADI)

    c_sutun = ["sahne_kimligi", UC, MERKEZ, "ciftte"]
    c_satir = []
    for s in sahneler:
        satir = {"sahne_kimligi": s, UC: durum(s, UC), MERKEZ: durum(s, MERKEZ)}
        satir["ciftte"] = satir[UC] == DURUM_TAMAM and satir[MERKEZ] == DURUM_TAMAM
        c_satir.append(satir)

    # 3) özet: mod başına ve çift düzeyinde
    o_sutun = ["kapsam", "planlanan", "kayitli", "tamamlanan", "tamamlanamayan", *NEDENLER, "kayit_yok", "kosullu"]
    o_satir = []
    for m in (UC, MERKEZ):
        kosular = [o for (s, mm), o in olcum.items() if mm == m]
        tamam = sum(1 for o in kosular if o["tamamlandi"])
        satir = {"kapsam": m, "planlanan": planlanan, "kayitli": len(kosular), "tamamlanan": tamam, "tamamlanamayan": len(kosular) - tamam,
                 "kayit_yok": planlanan - len(kosular), "kosullu": tamam < planlanan}
        satir.update({n: sum(1 for o in kosular if not o["tamamlandi"] and o["tamamlanamadi"]["neden"] == n) for n in NEDENLER})
        o_satir.append(satir)
    cift_tamam = sum(1 for s in c_satir if s["ciftte"])
    cift_eksik = sum(1 for s in c_satir if DURUM_TAMAMLANAMADI in (s[UC], s[MERKEZ]))
    satir = {"kapsam": "cift", "planlanan": planlanan, "kayitli": len(sahneler), "tamamlanan": cift_tamam, "tamamlanamayan": cift_eksik,
             "kayit_yok": planlanan - len(sahneler), "kosullu": cift_tamam < planlanan}
    satir.update({n: sum(1 for (s, _), o in olcum.items() if not o["tamamlandi"] and o["tamamlanamadi"]["neden"] == n) for n in NEDENLER})
    o_satir.append(satir)

    return {"sansurlu_kosu": (k_sutun, k_satir), "sansurlu_cift": (c_sutun, c_satir), "sansurlu_ozet": (o_sutun, o_satir)}


# ---------------------------------------------------------------------------------------------------------------------------------
# Komut satırı
# ---------------------------------------------------------------------------------------------------------------------------------
def ana(argv):
    yap_yolu, cikti, yollar = None, None, []
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
        yollar.append(a)
        i += 1
    if not (cikti and yollar):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        c, h_s, planlanan = yapilandirma_yukle(yap_yolu)
    except (OSError, ValueError) as e:
        print(f"Yapılandırma okunamadı/geçersiz: {e}", file=sys.stderr)
        return 2
    try:
        olcumler = [sd.json_oku(y) for y in yollar]
    except (OSError, json.JSONDecodeError) as e:
        print(f"Dosya okunamadı/JSON geçersiz: {e}", file=sys.stderr)
        return 2
    try:
        tablolar = analiz(c, h_s, planlanan, olcumler)
    except GirdiHatasi as e:
        print(f"HATA girdi geçersiz: {e}", file=sys.stderr)
        return 1
    try:
        yazilan = tablo.yaz(tablolar, cikti)
    except OSError as e:
        print(f"Çıktı yazılamadı: {e}", file=sys.stderr)
        return 2
    cift = tablolar["sansurlu_ozet"][1][-1]
    print(f"(+) {len(olcumler)} koşu, {len(tablolar['sansurlu_kosu'][1])} tamamlanamayan; tamamlanan çift {cift['tamamlanan']}/{cift['planlanan']}"
          + (" (koşullu sonuç)" if cift["kosullu"] else ""))
    if h_s is None:
        print(f"(!) {H_ANAHTARI} boş (H henüz kilitlenmedi, C12): sansürlü alt sınır yalnız gözlenen süredir")
    for y in yazilan:
        print(f"(i) yazıldı: {y}")
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
