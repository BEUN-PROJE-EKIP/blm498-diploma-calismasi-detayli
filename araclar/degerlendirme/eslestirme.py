#!/usr/bin/env python3
"""Değerlendirme yazılımı (B18, FR-28): bir koşunun nihai hedef raporunu sahnenin gerçek hedef listesiyle eşleştirir; TP, FP, FN, R, precision.

Kullanım:  python3 -I araclar/degerlendirme/eslestirme.py <nihai_rapor.json> <hedef_listesi.json> [--yapilandirma config/deney.env]
Girdi:     nihai hedef raporu (sözleşmeler §11.1, `tur: "nihai_rapor"`) ve hedef listesi (§5, `tur: "hedef_listesi"`); ikisi de önce
           sözleşme doğrulayıcısından geçer ve aynı `sahne_kimligi`'ni taşımalıdır.
Çıktı:     tek JSON nesnesi (stdout): üst bilgiler, toplam ve sınıf bazlı TP/FP/FN/R/precision, eşleşmeler ve eşleşmeyenler.
Çıkış:     0 başarılı, 1 girdi geçersiz (sözleşme hatası ya da sahne uyuşmazlığı), 2 kullanım/okuma/yapılandırma hatası.

Tanımlar [belge, el kitabı terimler tablosu]:
  TP  nihai raporlarla doğru eşleştirilen benzersiz gerçek hedef sayısı; doğru sınıf ve en fazla `DEGERLENDIRME_ESLESME_ESIK_M` (5 m)
      yatay konum hatası şartıyla Macar algoritmasıyla bire bir atama yapılır.
  FP  gerçek hedeflerle eşleşmeyen nihai rapor sayısı; gerçek bir hedefin fazladan kopyaları ve konumsuz raporlar dahildir.
  FN  nihai raporlarla eşleşmeyen gerçek hedef sayısı.
  R   = 100 × TP / N (%), N sahnedeki gerçek hedef sayısı.   Precision = TP / (TP + FP).
Tanımsız durumlar sıfır yazılmaz: TP + FP = 0 ise precision `null`; N = 0 ise R `null`.

Atama kuralı [belge, el kitabı "Hedef eşleştirme"; sözleşmeler §11.1 "Eşleştirme"]: yalnız aynı sınıftan ve eşik içindeki rapor–hedef çiftleri
uygundur; önce eşleşme sayısını (TP) en çoklayan, eşitlikte toplam konum hatasını en aza indiren bire bir atama seçilir. Maliyet matrisinde uygun
çiftin maliyeti metre cinsinden yatay uzaklık, uygun olmayanınki `esik · (N + 1)`'den büyük sabittir (N sahnedeki gerçek hedef sayısı); sabit
maliyetle yapılan atamalar eşleşme sayılmaz. Uygun olmayan çiftler sınıflar arasında hiç olmadığından sınıf başına bir
`scipy.optimize.linear_sum_assignment` çağrısı aynı sonucu verir. [varsayım] Belirlenimcilik için raporlar ve hedefler kimliğe göre sıralanır
(dosyadaki sıra sonucu değiştirmez). Gerçek hedef kimliği atama ölçütü değildir; yalnız çıktıda gösterilir.
Kitaplık: kilitli ortamdaki numpy ve scipy (kararlar 2026-11-14).
"""
import json
import math
import os
import sys

BURASI = os.path.dirname(os.path.abspath(__file__))   # araclar/degerlendirme
ARACLAR = os.path.dirname(BURASI)
KOK = os.path.dirname(ARACLAR)
sys.path.insert(0, ARACLAR)   # sozlesme_dogrula bir üst klasörde; -I ile betik klasörü de sys.path'e eklenmez

import numpy as np  # noqa: E402
from scipy.optimize import linear_sum_assignment  # noqa: E402

import sozlesme_dogrula as sd  # noqa: E402

ESIK_ANAHTARI = "DEGERLENDIRME_ESLESME_ESIK_M"


class GirdiHatasi(ValueError):
    """Girdi dosyaları sözleşmeye uymuyor ya da birbiriyle uyuşmuyor (farklı sahne)."""


def yapilandirma_yukle(yol=None):
    """config/deney.env'i okur; (Yapilandirma, eşleştirme eşiği m) döndürür. Eksik ya da geçersiz eşik ValueError'dur."""
    yol = yol or os.path.join(KOK, "config", "deney.env")
    ham = sd.yapilandirma_yukle(yol)
    c = sd.Yapilandirma(ham)
    if ESIK_ANAHTARI not in ham:
        raise ValueError(f"yapılandırmada eksik anahtar: {ESIK_ANAHTARI}")
    try:
        esik = float(ham[ESIK_ANAHTARI])
    except ValueError:
        raise ValueError(f"{ESIK_ANAHTARI} sayı olmalı (bulunan: {ham[ESIK_ANAHTARI]!r})") from None
    if not (math.isfinite(esik) and esik > 0):
        raise ValueError(f"{ESIK_ANAHTARI} pozitif sonlu sayı olmalı (bulunan: {esik!r})")
    return c, esik


def metrikler(n, tp, fp, fn):
    """Sayılardan R (%) ve precision; tanımsız olan `None` (sıfır yazılmaz)."""
    return {"n": n, "tp": tp, "fp": fp, "fn": fn,
            "r_yuzde": None if n == 0 else 100.0 * tp / n,
            "precision": None if tp + fp == 0 else tp / (tp + fp)}


def uygun_olmayan_maliyet(esik_m, n):
    """[belge] Uygun olmayan çiftin sabit maliyeti: `esik · (N + 1)`'den büyük. Her atama en çok N çift içerir ve uygun çiftlerin uzaklık toplamı
    en çok N·esik'tir; bu yüzden bir uygun çift fazla olan atamanın maliyeti her zaman daha küçüktür (önce TP en çok, sonra toplam uzaklık en az)."""
    return esik_m * (n + 1) + 1.0


def sinif_icinde_ata(rapor_xy, hedef_xy, esik_m, n):
    """Aynı sınıftan raporlar ve hedefler için bire bir atama. Girdi: (k, 2) ve (m, 2) dizileri (x, y; m), n sahnedeki gerçek hedef sayısı (m ≤ n).
    Dönüş: [(rapor_sırası, hedef_sırası, uzaklık_m)], yalnız uzaklığı ≤ esik_m olan çiftler (sabit maliyetli atamalar eşleşme sayılmaz)."""
    if len(rapor_xy) == 0 or len(hedef_xy) == 0:
        return []
    if len(hedef_xy) > n:
        raise ValueError(f"sınıftaki hedef sayısı ({len(hedef_xy)}) sahnedeki hedef sayısını ({n}) aşamaz")
    r = np.asarray(rapor_xy, dtype=float)
    h = np.asarray(hedef_xy, dtype=float)
    uzaklik = np.hypot(r[:, None, 0] - h[None, :, 0], r[:, None, 1] - h[None, :, 1])
    uygun = uzaklik <= esik_m
    if not uygun.any():
        return []
    buyuk = uygun_olmayan_maliyet(esik_m, n)
    satir, sutun = linear_sum_assignment(np.where(uygun, uzaklik, buyuk))
    return [(int(i), int(j), float(uzaklik[i, j])) for i, j in zip(satir, sutun) if uygun[i, j]]


def degerlendir(c, esik_m, nihai_rapor, hedef_listesi):
    """Bir koşunun değerlendirmesi. Girdiler sözleşme doğrulayıcısından geçmezse ya da sahneler farklıysa GirdiHatasi."""
    hatalar = [f"nihai_rapor: {h}" for h in sd.dogrula_nihai_rapor(c, nihai_rapor)]
    hatalar += [f"hedef_listesi: {h}" for h in sd.dogrula_hedef_listesi(c, hedef_listesi)]
    if hatalar:
        raise GirdiHatasi("; ".join(hatalar))
    if nihai_rapor["sahne_kimligi"] != hedef_listesi["sahne_kimligi"]:
        raise GirdiHatasi(f"sahne uyuşmuyor: nihai rapor '{nihai_rapor['sahne_kimligi']}', hedef listesi '{hedef_listesi['sahne_kimligi']}'")

    raporlar = sorted(nihai_rapor["raporlar"], key=lambda x: x["rapor_kimligi"])
    hedefler = sorted(hedef_listesi["hedefler"], key=lambda t: t["kimlik"])
    siniflar = list(dict.fromkeys(c.model_siniflari + c.siniflar))   # yapılandırma sırası; ikisi de `insan enkaz`

    eslesmeler, eslesmeyen_raporlar, eslesmeyen_hedefler = [], [], []
    sinif_bazli = {}
    for s in siniflar:
        s_rap = [x for x in raporlar if x["sinif"] == s]
        konumlu = [x for x in s_rap if x["konum"] is not None]
        s_hed = [t for t in hedefler if t["sinif"] == s]
        atama = sinif_icinde_ata([(x["konum"]["x_m"], x["konum"]["y_m"]) for x in konumlu], [(t["x"], t["y"]) for t in s_hed], esik_m, len(hedefler))
        atanan_r = {i for i, _, _ in atama}
        atanan_h = {j for _, j, _ in atama}
        for i, j, d in atama:
            eslesmeler.append({"rapor_kimligi": konumlu[i]["rapor_kimligi"], "hedef_kimligi": s_hed[j]["kimlik"], "sinif": s, "uzaklik_m": d})
        for x in s_rap:
            if x["konum"] is None:
                eslesmeyen_raporlar.append({"rapor_kimligi": x["rapor_kimligi"], "sinif": s, "neden": "konumsuz"})
        for i, x in enumerate(konumlu):
            if i not in atanan_r:
                eslesmeyen_raporlar.append({"rapor_kimligi": x["rapor_kimligi"], "sinif": s, "neden": "eslesmedi"})
        for j, t in enumerate(s_hed):
            if j not in atanan_h:
                eslesmeyen_hedefler.append({"hedef_kimligi": t["kimlik"], "sinif": s})
        tp = len(atama)
        sinif_bazli[s] = metrikler(len(s_hed), tp, len(s_rap) - tp, len(s_hed) - tp)

    eslesmeler.sort(key=lambda e: e["rapor_kimligi"])
    eslesmeyen_raporlar.sort(key=lambda e: e["rapor_kimligi"])
    eslesmeyen_hedefler.sort(key=lambda e: e["hedef_kimligi"])
    tp = len(eslesmeler)
    sonuc = {"kosu_kimligi": nihai_rapor["kosu_kimligi"], "sahne_kimligi": nihai_rapor["sahne_kimligi"], "mod": nihai_rapor["mod"],
             "esik_m": esik_m}
    sonuc.update(metrikler(len(hedefler), tp, len(raporlar) - tp, len(hedefler) - tp))
    sonuc["konumsuz_rapor"] = sum(1 for x in raporlar if x["konum"] is None)
    sonuc["sinif_bazli"] = sinif_bazli
    sonuc["eslesmeler"] = eslesmeler
    sonuc["eslesmeyen_raporlar"] = eslesmeyen_raporlar
    sonuc["eslesmeyen_hedefler"] = eslesmeyen_hedefler
    return sonuc


def ana(argv):
    yap_yolu, dosyalar = None, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__)
            return 0
        if a == "--yapilandirma":
            if i + 1 >= len(argv):
                print(f"{a} bir değer ister", file=sys.stderr)
                return 2
            yap_yolu = argv[i + 1]
            i += 2
            continue
        if a.startswith("--"):
            print(f"Bilinmeyen argüman: {a}", file=sys.stderr)
            return 2
        dosyalar.append(a)
        i += 1
    if len(dosyalar) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        c, esik = yapilandirma_yukle(yap_yolu)
    except (OSError, ValueError) as e:
        print(f"Yapılandırma okunamadı/geçersiz: {e}", file=sys.stderr)
        return 2
    try:
        rapor, liste = (sd.json_oku(y) for y in dosyalar)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Dosya okunamadı/JSON geçersiz: {e}", file=sys.stderr)
        return 2
    try:
        sonuc = degerlendir(c, esik, rapor, liste)
    except GirdiHatasi as e:
        print(f"HATA girdi geçersiz: {e}", file=sys.stderr)
        return 1
    print(json.dumps(sonuc, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(ana(sys.argv[1:]))
