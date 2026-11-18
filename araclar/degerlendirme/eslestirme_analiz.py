#!/usr/bin/env python3
"""Eşleştirme analiz betiği (E1a; FR-24, FR-28): bütün koşulara hedef eşleştirmesini (B18, eslestirme.py) uygular; iki mod için mutlak ve sınıf
bazlı R, sahne başına R(uç) − R(merkez) farkı, görev düzeyinde precision ve görev başına FP tablolarını yazar.

Kullanım:
  python3 -I araclar/degerlendirme/eslestirme_analiz.py --hedef-listeleri <klasör> --cikti <klasör> <nihai_rapor.json> [<nihai_rapor.json> ...]
                                                        [--kosu-olcum <kosu_olcum.json> ...] [--yapilandirma config/deney.env]
Girdi:
  <nihai_rapor.json>   koşu başına nihai hedef raporu (sözleşmeler §11.1); sahne ve mod dosyanın içinden okunur.
  --hedef-listeleri    hedef listesi dosyalarının (§5, `tur: "hedef_listesi"`) bulunduğu klasör; `*.json`, sahne kimliğine göre eşlenir.
  --kosu-olcum         (isteğe bağlı, yinelenebilir) koşu ölçüm özeti (§11.2). Verilirse her nihai rapor için aynı sahne ve modda bir özet bulunmalı
                       ve `kosu_kimligi` uyuşmalıdır; `tamamlandi = false` olan koşunun çifti analizden dışlanır [belge, FR-27: ortalamaya
                       katılmaz]. Verilmezse bütün koşular tamamlanmış sayılır. Tamamlanamayan koşuların kendi analizi E5a'nındır.
Çıktı (--cikti klasörüne; her tablo CSV ve Markdown, aynı veriden; sütun sırası sabit) [kararlar 2026-11-14]:
  eslestirme_kosu      koşu başına: N, TP, FP, FN, R, precision, konumsuz rapor; sınıf başına aynıları; çifte dahil olup olmadığı
  eslestirme_sahne     tamamlanan sahne çifti başına: R(uç), R(merkez), R(uç) − R(merkez); sınıf bazında aynıları; iki modun FP ve precision'ı
  eslestirme_ozet      ölçüt başına, tamamlanan çiftler üzerinden: çift sayısı, tanımlı/tanımsız sayısı, ortalama, medyan, en küçük, en büyük
  eslestirme_dislanan  çift kurulamayan sahneler ve nedeni (`<mod>: nihai_rapor_yok` | `<mod>: tamamlanamadi`)
Sayı biçimi: CSV nokta ondalık, 6 basamak, tanımsız boş hücre, mantıksal 1/0; Markdown virgül ondalık, 2 basamak, tanımsız "tanımsız", evet/hayır.
Çıkış: 0 başarılı, 1 girdi geçersiz (sözleşme hatası, eksik hedef listesi, yinelenen koşu, uyuşmayan ölçüm özeti), 2 kullanım/okuma hatası.

Tanımlar [belge, el kitabı "İstatistiksel Yöntemler"]: R için iki modun sahne başına oranlarının ortalaması mutlak olarak ve sınıf bazında
raporlanır; ayrıca sahne başına R(uç) − R(merkez) farkının ortalaması hesaplanır; her ölçütün sahne dağılımı, ortalaması ve medyanı verilir
(%95 güven aralığı E3a). Precision görev (koşu) düzeyindedir; hiç rapor üretilmeyen koşuda R = 0, FP = 0, precision tanımsız.
[varsayım] Özet tablosunda ortalama, medyan, en küçük ve en büyük yalnız tanımlı değerlerden alınır; tanımsız değer sayısı ayrı sütundadır.
"""
import json
import os
import sys

BURASI = os.path.dirname(os.path.abspath(__file__))   # araclar/degerlendirme
sys.path.insert(0, BURASI)
sys.path.insert(0, os.path.dirname(BURASI))

import eslestirme as es  # noqa: E402
import tablo  # noqa: E402
from tablo import csv_deger, csv_metni, md_deger, md_metni, yaz  # noqa: E402,F401  (E1a testleri bu adları kullanır)
import sozlesme_dogrula as sd  # noqa: E402

UC, MERKEZ = "ucta", "merkezi"
GirdiHatasi = es.GirdiHatasi
METRIK = ("n", "tp", "fp", "fn", "r_yuzde", "precision")


def _hatali(onek, hatalar):
    if hatalar:
        raise GirdiHatasi(f"{onek}: " + "; ".join(hatalar))


def _modlar(c):
    if UC not in c.mimariler or MERKEZ not in c.mimariler:
        raise ValueError(f"KOSU_MIMARILER '{UC}' ve '{MERKEZ}' içermeli (bulunan: {c.mimariler})")
    return (UC, MERKEZ)


def _siniflar(c):
    return list(dict.fromkeys(c.model_siniflari + c.siniflar))


def _fark(a, b):
    return None if a is None or b is None else a - b


def analiz(c, esik_m, nihai_raporlar, hedef_listeleri, kosu_olcumleri=None):
    """Bütün tabloları hesaplar. Dönüş: {tablo_adı: (sütunlar, satırlar)}; satır sütun adıyla anahtarlı sözlüktür. Girdi hatası GirdiHatasi."""
    modlar = _modlar(c)
    siniflar = _siniflar(c)

    listeler = {}
    for hl in hedef_listeleri:
        _hatali("hedef_listesi", sd.dogrula_hedef_listesi(c, hl))
        if hl["sahne_kimligi"] in listeler:
            raise GirdiHatasi(f"yinelenen hedef listesi: sahne '{hl['sahne_kimligi']}'")
        listeler[hl["sahne_kimligi"]] = hl

    olcum = None
    if kosu_olcumleri is not None:
        olcum = {}
        for o in kosu_olcumleri:
            _hatali("kosu_olcum", sd.dogrula_kosu_olcum(c, o))
            anahtar = (o["sahne_kimligi"], o["mod"])
            if anahtar in olcum:
                raise GirdiHatasi(f"yinelenen koşu ölçüm özeti: sahne '{anahtar[0]}', mod '{anahtar[1]}'")
            olcum[anahtar] = o

    kosular = {}
    for r in nihai_raporlar:
        _hatali("nihai_rapor", sd.dogrula_nihai_rapor(c, r))
        anahtar = (r["sahne_kimligi"], r["mod"])
        if anahtar in kosular:
            raise GirdiHatasi(f"yinelenen koşu: sahne '{anahtar[0]}', mod '{anahtar[1]}'")
        if r["sahne_kimligi"] not in listeler:
            raise GirdiHatasi(f"hedef listesi yok: sahne '{r['sahne_kimligi']}' (koşu {r['kosu_kimligi']})")
        tamamlandi = True
        if olcum is not None:
            o = olcum.get(anahtar)
            if o is None:
                raise GirdiHatasi(f"koşu ölçüm özeti yok: sahne '{anahtar[0]}', mod '{anahtar[1]}' (koşu {r['kosu_kimligi']})")
            if o["kosu_kimligi"] != r["kosu_kimligi"]:
                raise GirdiHatasi(f"koşu kimliği uyuşmuyor: sahne '{anahtar[0]}', mod '{anahtar[1]}': nihai rapor {r['kosu_kimligi']}, ölçüm özeti {o['kosu_kimligi']}")
            tamamlandi = o["tamamlandi"]
        kosular[anahtar] = (es.degerlendir(c, esik_m, r, listeler[r["sahne_kimligi"]]), tamamlandi)

    # Sahne çiftleri: iki modda da nihai rapor var ve (ölçüm verildiyse) iki koşu da tamamlandı.
    sahneler = sorted({s for s, _ in kosular} | ({s for s, _ in olcum} if olcum else set()))
    ciftler, dislanan = [], []
    for s in sahneler:
        nedenler = []
        for m in modlar:
            k = kosular.get((s, m))
            if k is None:
                tamamlanmadi = olcum is not None and (s, m) in olcum and not olcum[(s, m)]["tamamlandi"]
                nedenler.append(f"{m}: tamamlanamadi" if tamamlanmadi else f"{m}: nihai_rapor_yok")
            elif not k[1]:
                nedenler.append(f"{m}: tamamlanamadi")
        if nedenler:
            dislanan.append({"sahne_kimligi": s, "neden": "; ".join(nedenler)})
        else:
            ciftler.append(s)
    cift_kumesi = set(ciftler)

    # 1) koşu tablosu
    k_sutun = ["sahne_kimligi", "mod", "kosu_kimligi", "tamamlandi", "ciftte", *METRIK, "konumsuz_rapor"]
    k_sutun += [f"{s}_{m}" for s in siniflar for m in METRIK]
    k_satir = []
    for (s, m) in sorted(kosular, key=lambda a: (a[0], modlar.index(a[1]) if a[1] in modlar else len(modlar), a[1])):
        sonuc, tamamlandi = kosular[(s, m)]
        satir = {"sahne_kimligi": s, "mod": m, "kosu_kimligi": sonuc["kosu_kimligi"], "tamamlandi": tamamlandi, "ciftte": s in cift_kumesi,
                 "konumsuz_rapor": sonuc["konumsuz_rapor"]}
        satir.update({a: sonuc[a] for a in METRIK})
        for sn in siniflar:
            satir.update({f"{sn}_{a}": sonuc["sinif_bazli"][sn][a] for a in METRIK})
        k_satir.append(satir)

    # 2) sahne tablosu (yalnız tamamlanan çiftler)
    r_olcutleri = [("r", lambda x: x["r_yuzde"])] + [(f"{sn}_r", lambda x, sn=sn: x["sinif_bazli"][sn]["r_yuzde"]) for sn in siniflar]
    s_sutun = ["sahne_kimligi"]
    for ad, _ in r_olcutleri:
        s_sutun += [f"{ad}_{UC}", f"{ad}_{MERKEZ}", f"{ad}_fark"]
    s_sutun += [f"fp_{UC}", f"fp_{MERKEZ}", f"precision_{UC}", f"precision_{MERKEZ}"]
    s_satir = []
    for s in ciftler:
        u, mz = kosular[(s, UC)][0], kosular[(s, MERKEZ)][0]
        satir = {"sahne_kimligi": s}
        for ad, al in r_olcutleri:
            satir.update({f"{ad}_{UC}": al(u), f"{ad}_{MERKEZ}": al(mz), f"{ad}_fark": _fark(al(u), al(mz))})
        satir.update({f"fp_{UC}": u["fp"], f"fp_{MERKEZ}": mz["fp"], f"precision_{UC}": u["precision"], f"precision_{MERKEZ}": mz["precision"]})
        s_satir.append(satir)

    # 3) özet tablosu: sahne tablosunun her ölçüt sütunu
    o_sutun = ["olcut", "cift_sayisi", "tanimli_sayisi", "tanimsiz_sayisi", "ortalama", "medyan", "en_kucuk", "en_buyuk"]
    o_satir = [tablo.ozet(ad, [satir[ad] for satir in s_satir]) for ad in s_sutun[1:]]

    return {"eslestirme_kosu": (k_sutun, k_satir), "eslestirme_sahne": (s_sutun, s_satir), "eslestirme_ozet": (o_sutun, o_satir),
            "eslestirme_dislanan": (["sahne_kimligi", "neden"], dislanan)}


# ---------------------------------------------------------------------------------------------------------------------------------
# Komut satırı
# ---------------------------------------------------------------------------------------------------------------------------------
def ana(argv):
    yap_yolu, hl_klasor, cikti, olcum_yollari, rapor_yollari = None, None, None, None, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__)
            return 0
        if a in ("--yapilandirma", "--hedef-listeleri", "--cikti", "--kosu-olcum"):
            if i + 1 >= len(argv):
                print(f"{a} bir değer ister", file=sys.stderr)
                return 2
            v = argv[i + 1]
            if a == "--yapilandirma":
                yap_yolu = v
            elif a == "--hedef-listeleri":
                hl_klasor = v
            elif a == "--cikti":
                cikti = v
            else:
                olcum_yollari = (olcum_yollari or []) + [v]
            i += 2
            continue
        if a.startswith("--"):
            print(f"Bilinmeyen argüman: {a}", file=sys.stderr)
            return 2
        rapor_yollari.append(a)
        i += 1
    if not (hl_klasor and cikti and rapor_yollari):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        c, esik = es.yapilandirma_yukle(yap_yolu)
        _modlar(c)
    except (OSError, ValueError) as e:
        print(f"Yapılandırma okunamadı/geçersiz: {e}", file=sys.stderr)
        return 2
    try:
        listeler = [sd.json_oku(os.path.join(hl_klasor, ad)) for ad in sorted(os.listdir(hl_klasor)) if ad.endswith(".json")]
        raporlar = [sd.json_oku(y) for y in rapor_yollari]
        olcumler = None if olcum_yollari is None else [sd.json_oku(y) for y in olcum_yollari]
    except (OSError, json.JSONDecodeError) as e:
        print(f"Dosya okunamadı/JSON geçersiz: {e}", file=sys.stderr)
        return 2
    try:
        tablolar = analiz(c, esik, raporlar, listeler, olcumler)
    except GirdiHatasi as e:
        print(f"HATA girdi geçersiz: {e}", file=sys.stderr)
        return 1
    try:
        yazilan = yaz(tablolar, cikti)
    except OSError as e:
        print(f"Çıktı yazılamadı: {e}", file=sys.stderr)
        return 2
    _, sahne_satir = tablolar["eslestirme_sahne"]
    print(f"(+) {len(raporlar)} koşu, {len(sahne_satir)} tamamlanan sahne çifti, {len(tablolar['eslestirme_dislanan'][1])} dışlanan sahne")
    for y in yazilan:
        print(f"(i) yazıldı: {y}")
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
