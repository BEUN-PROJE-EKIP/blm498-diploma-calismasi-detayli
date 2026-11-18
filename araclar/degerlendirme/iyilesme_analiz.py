#!/usr/bin/env python3
"""İyileşme analiz betiği (E2a; FR-29): eşleştirilmiş sahne çiftlerinde D, B ve T için yüzde iyileşmeyi, L için ortanca ve 95. yüzdelik
farklarını hesaplar; koşu, sahne, özet ve dışlanan sahne tablolarını yazar.

Kullanım:
  python3 -I araclar/degerlendirme/iyilesme_analiz.py --cikti <klasör> <kosu_olcum.json> [<kosu_olcum.json> ...] [--yapilandirma config/deney.env]
Girdi:
  <kosu_olcum.json>    koşu başına koşu ölçüm özeti (sözleşmeler §11.2); sahne ve mod dosyanın içinden okunur. Aynı sahne ve modda iki özet hatadır.
Çıktı (--cikti klasörüne; her tablo CSV ve Markdown, aynı veriden; sütun sırası sabit) [kararlar 2026-11-14]:
  iyilesme_kosu      koşu başına: T, D, B, L özeti (örnek sayısı, ortanca, p95), kare sayıları, sonuç üreten kare oranı, kare alınamadı oranı
  iyilesme_sahne     tamamlanan sahne çifti başına: D, B, T için iki modun değeri ve yüzde iyileşme; L ortanca ve p95 için iki modun değeri ve fark
  iyilesme_ozet      ölçüt başına, tamamlanan çiftler üzerinden: çift sayısı, tanımlı/tanımsız sayısı, ortalama, medyan, en küçük, en büyük
  iyilesme_dislanan  çift kurulamayan sahneler ve nedeni (`<mod>: kosu_olcum_yok` | `<mod>: tamamlanamadi`)
Sayı biçimi: CSV nokta ondalık, 6 basamak, tanımsız boş hücre, mantıksal 1/0; Markdown virgül ondalık, 2 basamak, tanımsız "tanımsız", evet/hayır.
Çıkış: 0 başarılı, 1 girdi geçersiz (sözleşme hatası, yinelenen koşu), 2 kullanım/okuma hatası.

Tanımlar [belge, el kitabı "İstatistiksel Yöntemler"]: her eşleştirilmiş sahnede D, B ve T için I_X = 100 × (X(merkez) − X(uç)) / X(merkez);
L için iyileşme sahne düzeyindeki ortanca ve 95. yüzdelik farklarıdır (merkez eksi uç, saniye), L için yüzde iyileşme hesaplanmaz; her iki durumda
pozitif değer uçta mod lehinedir. Tahmin, sahne başına iyileşmelerin aritmetik ortalamasıdır; her ölçütün sahne dağılımı, ortalaması ve medyanı
verilir (%95 güven aralığı E3a). Modlar arası kare eşleştirmesi yapılmaz; L özetleri koşu ölçüm özetinden (§11.2 `l`) alınır. [belge, FR-27]
Tamamlanamayan koşunun çifti ortalamaya katılmaz (sansürlü gösterim ve kısmi trafik E5a'nındır). Kare sayıları ve oranları gecikme tablolarıyla
birlikte verilir [belge].
[varsayım] X(merkez) = 0 ise I_X tanımsızdır (sıfır yazılmaz); bir modda L örneği yoksa (`l.ornek_sayisi` = 0) o L farkı tanımsızdır. Özet
tablosunda ortalama, medyan, en küçük ve en büyük yalnız tanımlı değerlerden alınır; tanımsız değer sayısı ayrı sütundadır.
"""
import json
import os
import sys

BURASI = os.path.dirname(os.path.abspath(__file__))   # araclar/degerlendirme
ARACLAR = os.path.dirname(BURASI)
KOK = os.path.dirname(ARACLAR)
sys.path.insert(0, BURASI)
sys.path.insert(0, ARACLAR)

import sozlesme_dogrula as sd  # noqa: E402
import tablo  # noqa: E402

UC, MERKEZ = "ucta", "merkezi"
YUZDE_OLCUTLERI = (("d", "d_mb"), ("b", "b_mbit_s"), ("t", "t_s"))   # (tablo öneki, §11.2 alanı)
L_OLCUTLERI = (("l_ortanca", "ortanca_s"), ("l_p95", "p95_s"))        # (tablo öneki, §11.2 `l` alanı)
KARE_ALANLARI = ("beklenen", "pozitif", "negatif", "kare_alinamadi", "islem_hatasi", "gec_geldi")


class GirdiHatasi(ValueError):
    """Girdi dosyası sözleşmeye uymuyor ya da tutarsız (çıkış 1)."""


def yapilandirma_yukle(yol=None):
    c = sd.Yapilandirma(sd.yapilandirma_yukle(yol or os.path.join(KOK, "config", "deney.env")))
    _modlar(c)
    return c


def _modlar(c):
    if UC not in c.mimariler or MERKEZ not in c.mimariler:
        raise ValueError(f"KOSU_MIMARILER '{UC}' ve '{MERKEZ}' içermeli (bulunan: {c.mimariler})")
    return (UC, MERKEZ)


def yuzde_iyilesme(merkez, uc):
    """[belge] I_X = 100 × (X(merkez) − X(uç)) / X(merkez); pozitif uçta lehine. [varsayım] Değer yoksa ya da X(merkez) = 0 ise None."""
    if merkez is None or uc is None or merkez == 0:
        return None
    return 100.0 * (merkez - uc) / merkez


def fark(merkez, uc):
    """[belge] L için merkez eksi uç (s); pozitif uçta lehine. Değerlerden biri yoksa None."""
    return None if merkez is None or uc is None else merkez - uc


def analiz(c, kosu_olcumleri):
    """Bütün tabloları hesaplar. Dönüş: {tablo_adı: (sütunlar, satırlar)}; satır sütun adıyla anahtarlı sözlüktür. Girdi hatası GirdiHatasi."""
    modlar = _modlar(c)

    olcum = {}
    for o in kosu_olcumleri:
        hatalar = sd.dogrula_kosu_olcum(c, o)
        if hatalar:
            raise GirdiHatasi("kosu_olcum: " + "; ".join(hatalar))
        anahtar = (o["sahne_kimligi"], o["mod"])
        if anahtar in olcum:
            raise GirdiHatasi(f"yinelenen koşu ölçüm özeti: sahne '{anahtar[0]}', mod '{anahtar[1]}'")
        olcum[anahtar] = o

    # Sahne çiftleri: iki modda da ölçüm özeti var ve iki koşu da tamamlandı [belge, FR-27].
    ciftler, dislanan = [], []
    for s in sorted({s for s, _ in olcum}):
        nedenler = []
        for m in modlar:
            o = olcum.get((s, m))
            if o is None:
                nedenler.append(f"{m}: kosu_olcum_yok")
            elif not o["tamamlandi"]:
                nedenler.append(f"{m}: tamamlanamadi")
        if nedenler:
            dislanan.append({"sahne_kimligi": s, "neden": "; ".join(nedenler)})
        else:
            ciftler.append(s)
    cift_kumesi = set(ciftler)

    # 1) koşu tablosu
    k_sutun = ["sahne_kimligi", "mod", "kosu_kimligi", "tamamlandi", "ciftte", "t_s", "d_mb", "b_mbit_s",
               "l_ornek_sayisi", "l_ortanca_s", "l_p95_s", *KARE_ALANLARI, "sonuc_orani", "kare_alinamadi_orani"]
    k_satir = []
    for (s, m) in sorted(olcum, key=lambda a: (a[0], modlar.index(a[1]) if a[1] in modlar else len(modlar), a[1])):
        o = olcum[(s, m)]
        satir = {"sahne_kimligi": s, "mod": m, "kosu_kimligi": o["kosu_kimligi"], "tamamlandi": o["tamamlandi"], "ciftte": s in cift_kumesi,
                 "t_s": o["t_s"], "d_mb": o["d_mb"], "b_mbit_s": o["b_mbit_s"], "l_ornek_sayisi": o["l"]["ornek_sayisi"],
                 "l_ortanca_s": o["l"]["ortanca_s"], "l_p95_s": o["l"]["p95_s"],
                 "sonuc_orani": o["sonuc_orani"], "kare_alinamadi_orani": o["kare_alinamadi_orani"]}
        satir.update({a: o["kare_sayilari"][a] for a in KARE_ALANLARI})
        k_satir.append(satir)

    # 2) sahne tablosu (yalnız tamamlanan çiftler)
    s_sutun = ["sahne_kimligi"]
    for ad, _ in YUZDE_OLCUTLERI:
        s_sutun += [f"{ad}_{UC}", f"{ad}_{MERKEZ}", f"{ad}_iyilesme_yuzde"]
    for ad, _ in L_OLCUTLERI:
        s_sutun += [f"{ad}_{UC}", f"{ad}_{MERKEZ}", f"{ad}_fark"]
    s_satir = []
    for s in ciftler:
        u, mz = olcum[(s, UC)], olcum[(s, MERKEZ)]
        satir = {"sahne_kimligi": s}
        for ad, alan in YUZDE_OLCUTLERI:
            satir.update({f"{ad}_{UC}": u[alan], f"{ad}_{MERKEZ}": mz[alan], f"{ad}_iyilesme_yuzde": yuzde_iyilesme(mz[alan], u[alan])})
        for ad, alan in L_OLCUTLERI:
            satir.update({f"{ad}_{UC}": u["l"][alan], f"{ad}_{MERKEZ}": mz["l"][alan], f"{ad}_fark": fark(mz["l"][alan], u["l"][alan])})
        s_satir.append(satir)

    # 3) özet tablosu: sahne tablosunun her ölçüt sütunu
    o_sutun = ["olcut", "cift_sayisi", "tanimli_sayisi", "tanimsiz_sayisi", "ortalama", "medyan", "en_kucuk", "en_buyuk"]
    o_satir = [tablo.ozet(ad, [satir[ad] for satir in s_satir]) for ad in s_sutun[1:]]

    return {"iyilesme_kosu": (k_sutun, k_satir), "iyilesme_sahne": (s_sutun, s_satir), "iyilesme_ozet": (o_sutun, o_satir),
            "iyilesme_dislanan": (["sahne_kimligi", "neden"], dislanan)}


# ---------------------------------------------------------------------------------------------------------------------------------
# Komut satırı
# ---------------------------------------------------------------------------------------------------------------------------------
def ana(argv):
    yap_yolu, cikti, olcum_yollari = None, None, []
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
        olcum_yollari.append(a)
        i += 1
    if not (cikti and olcum_yollari):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        c = yapilandirma_yukle(yap_yolu)
    except (OSError, ValueError) as e:
        print(f"Yapılandırma okunamadı/geçersiz: {e}", file=sys.stderr)
        return 2
    try:
        olcumler = [sd.json_oku(y) for y in olcum_yollari]
    except (OSError, json.JSONDecodeError) as e:
        print(f"Dosya okunamadı/JSON geçersiz: {e}", file=sys.stderr)
        return 2
    try:
        tablolar = analiz(c, olcumler)
    except GirdiHatasi as e:
        print(f"HATA girdi geçersiz: {e}", file=sys.stderr)
        return 1
    try:
        yazilan = tablo.yaz(tablolar, cikti)
    except OSError as e:
        print(f"Çıktı yazılamadı: {e}", file=sys.stderr)
        return 2
    print(f"(+) {len(olcumler)} koşu, {len(tablolar['iyilesme_sahne'][1])} tamamlanan sahne çifti, "
          f"{len(tablolar['iyilesme_dislanan'][1])} dışlanan sahne")
    for y in yazilan:
        print(f"(i) yazıldı: {y}")
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
