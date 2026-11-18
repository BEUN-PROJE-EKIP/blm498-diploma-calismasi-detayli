#!/usr/bin/env python3
"""Analiz tablolarının ortak yazımı (M6a: E1a–E5a) [kararlar 2026-11-14; sözleşmeler §11.4]: her tablo aynı veriden iki dosya.
  <ad>.csv  makine okur: nokta ondalık, 6 basamak, tanımsız değer boş hücre, mantıksal 1/0, başlık satırı sütun adları
  <ad>.md   rapora girer: `# <ad>` başlığı ve tablo; virgül ondalık, 2 basamak, tanımsız değer "tanımsız", mantıksal evet/hayır
Tablo biçimi: {ad: (sütunlar, satırlar)}; satır sütun adıyla anahtarlı sözlüktür. Ayrıca ölçüt özeti (ozet) burada durur.
"""
import csv
import io
import os
import statistics


def ozet(ad, degerler):
    """Bir ölçüt sütununun özeti. [varsayım] Ortalama, medyan, en küçük, en büyük yalnız tanımlı değerlerden; tanımsız sayısı ayrı sütunda."""
    tanimli = [float(v) for v in degerler if v is not None]   # sayımlar (FP) de ondalık yazılır: özet sütunlarının biçimi sabit
    return {"olcut": ad, "cift_sayisi": len(degerler), "tanimli_sayisi": len(tanimli), "tanimsiz_sayisi": len(degerler) - len(tanimli),
            "ortalama": statistics.fmean(tanimli) if tanimli else None, "medyan": statistics.median(tanimli) if tanimli else None,
            "en_kucuk": min(tanimli) if tanimli else None, "en_buyuk": max(tanimli) if tanimli else None}


def _isaretsiz_sifir(metin):
    return metin[1:] if metin.startswith("-") and not metin.strip("-0.,") else metin


def csv_deger(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _isaretsiz_sifir(f"{v:.6f}")
    return str(v)


def md_deger(v):
    if v is None:
        return "tanımsız"
    if isinstance(v, bool):
        return "evet" if v else "hayır"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _isaretsiz_sifir(f"{v:.2f}").replace(".", ",")
    return str(v).replace("|", "\\|")


def csv_metni(sutunlar, satirlar):
    tampon = io.StringIO()
    w = csv.writer(tampon, lineterminator="\n")
    w.writerow(sutunlar)
    for s in satirlar:
        w.writerow([csv_deger(s[k]) for k in sutunlar])
    return tampon.getvalue()


def md_metni(ad, sutunlar, satirlar):
    satirlar_md = [f"# {ad}", "", "| " + " | ".join(sutunlar) + " |", "|" + "---|" * len(sutunlar)]
    satirlar_md += ["| " + " | ".join(md_deger(s[k]) for k in sutunlar) + " |" for s in satirlar]
    return "\n".join(satirlar_md) + "\n"


def yaz(tablolar, klasor):
    os.makedirs(klasor, exist_ok=True)
    yazilan = []
    for ad, (sutunlar, satirlar) in tablolar.items():
        for uzanti, metin in (("csv", csv_metni(sutunlar, satirlar)), ("md", md_metni(ad, sutunlar, satirlar))):
            yol = os.path.join(klasor, f"{ad}.{uzanti}")
            with open(yol, "w", encoding="utf-8", newline="") as f:
                f.write(metin)
            yazilan.append(yol)
    return yazilan
