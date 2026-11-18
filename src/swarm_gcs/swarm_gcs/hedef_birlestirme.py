"""Nihai hedef birleştirme (FR-19, FR-5, B15): saf mantık (rclpy yok; birim testli). İki mimari mod (uçta, merkezi) AYNI fonksiyonu çağırır.

Kural [belge FR-19]: tespitler üretim zamanı, araç ve kare numarası sırasıyla işlenir; aynı sınıftaki konumlu bir tespit mevcut adayın SABİT İLK konumuna en çok `aralik_m`
(BIRLESTIRME_ARALIK_M; "≤", sınır dahil; yatay Öklid uzaklığı) uzaklıktaysa o adaya eklenir, değilse yeni aday açılır; birden fazla aday uygunsa en yakın, eşit uzaklıkta en eski aday seçilir;
adayın nihai konumu en yüksek güvenli tespitin konumudur. Gerçek hedef kimliği kullanılmaz. Konumsuz tespit konumsal birleştirmeye alınmaz: her biri ayrı konumsuz rapor olur [belge FR-18].
[varsayım] Belgede olmayan eşitlikler: (a) adaydaki en yüksek güven eşitliğinde en eski tespit; (b) "en eski aday" = ilk tespiti en önce işlenen aday.
Sıralama anahtarı `(sim_damga_ns, arac, n)`: kare sonucunun simülasyon (ızgara) damgası; tek Gazebo saatinde üretim zamanı sırası sim damgası sırasıdır [varsayım]. Birleştirme Gazebo damga
dosyasını HİÇ okumaz (dosya ≤ 1 sn gecikmeli yazılır; beklemek ölçülen süreye yapay süre katardı). Sim damgası eksik ya da geçersiz tespit açık hatadır (`BirlestirmeHatasi`); sessiz atlama yoktur.
"""
import json
import math
import os
from collections import namedtuple

# arac: araç kimliği; n: kare numarası; sim_damga_ns: karenin ızgara simülasyon damgası (ns); sinif: sınıf adı; guven: güven puanı; konum: (x_m, y_m) ENU ya da None (konumsuz)
Tespit = namedtuple("Tespit", "arac n sim_damga_ns sinif guven konum")


class BirlestirmeHatasi(Exception):
    """Girdi geçersiz (ör. sayı olmayan güven/konum): sessizce düzeltilmez."""


def tespitleri_hazirla(kayitlar):
    """Kare kayıtlarından (`{"arac", "n", "sim_damga_ns", "tespitler": [{"sinif", "guven", "konum": [x, y] | None}]}`) `Tespit` listesi. Tespiti olan kayıtta sim damgası tam sayı (≥ 0) değilse `BirlestirmeHatasi`."""
    cikti = []
    for k in kayitlar:
        for t in k.get("tespitler", ()):
            sim = k.get("sim_damga_ns")
            if isinstance(sim, bool) or not isinstance(sim, int) or sim < 0:
                raise BirlestirmeHatasi(f"araç {k.get('arac')} kare {k.get('n')}: sim damgası eksik ya da geçersiz ({sim!r})")
            konum = t.get("konum")
            cikti.append(Tespit(int(k["arac"]), int(k["n"]), sim, str(t["sinif"]), float(t["guven"]), None if konum is None else (float(konum[0]), float(konum[1]))))
    return cikti


def _gecerli(t):
    if not (isinstance(t.guven, (int, float)) and math.isfinite(t.guven)):
        raise BirlestirmeHatasi(f"tespit güveni sayı değil: {t!r}")
    if t.konum is not None and not all(isinstance(v, (int, float)) and math.isfinite(v) for v in t.konum):
        raise BirlestirmeHatasi(f"tespit konumu sonlu sayı çifti değil: {t!r}")


class _Aday:
    __slots__ = ("sinif", "ilk_konum", "ilk", "en", "sayi")

    def __init__(self, t):
        self.sinif, self.ilk_konum, self.ilk, self.en, self.sayi = t.sinif, t.konum, t, t, 1

    def ekle(self, t):
        self.sayi += 1
        if t.guven > self.en.guven:        # eşitlikte ilk (en eski) kalır
            self.en = t


def birlestir(tespitler, aralik_m):
    """Tespit listesi → §11.1 `raporlar` (sözlük listesi). Girdi sırası önemsizdir: anahtar `(sim_damga_ns, arac, n)` ile sıralanır; aynı anahtarlı çok tespitte girdi sırası korunur (kararlı sıralama).
    Konumlu raporlar ve konumsuz raporlar tek `R001…` kimlik dizisini aday açılış sırasıyla paylaşır. Boş girdi boş liste verir."""
    aralik_m = float(aralik_m)
    liste = list(tespitler)
    for t in liste:
        _gecerli(t)
    liste.sort(key=lambda t: (t.sim_damga_ns, t.arac, t.n))
    adaylar = []                                                  # açılış sırasıyla; konumsuz tespit de bir (yalnız tek tespitli) rapor girdisidir
    for t in liste:
        if t.konum is None:
            adaylar.append(_Aday(t))
            continue
        en_iyi, en_iyi_uz = None, None
        for a in adaylar:                                         # açılış sırası: eşit uzaklıkta ilk bulunan (en eski) kalır
            if a.ilk_konum is None or a.sinif != t.sinif:
                continue
            uz = math.hypot(t.konum[0] - a.ilk_konum[0], t.konum[1] - a.ilk_konum[1])
            if uz <= aralik_m and (en_iyi is None or uz < en_iyi_uz):
                en_iyi, en_iyi_uz = a, uz
        if en_iyi is None:
            adaylar.append(_Aday(t))
        else:
            en_iyi.ekle(t)
    raporlar = []
    for sira, a in enumerate(adaylar, 1):
        yaz = (lambda t: {"arac_kimligi": t.arac, "n": t.n, "sim_damga_ns": t.sim_damga_ns})
        raporlar.append({"rapor_kimligi": f"R{sira:03d}", "sinif": a.sinif,
                         "konum": None if a.en.konum is None else {"x_m": a.en.konum[0], "y_m": a.en.konum[1]},
                         "ilk_konum": None if a.ilk_konum is None else {"x_m": a.ilk_konum[0], "y_m": a.ilk_konum[1]},
                         "guven": a.en.guven, "tespit_sayisi": a.sayi, "ilk_tespit": yaz(a.ilk), "en_yuksek_guven_tespiti": yaz(a.en)})
    return raporlar


def nihai_rapor(kosu_kimligi, sahne_kimligi, mod, raporlar):
    """§11.1 nihai rapor sözlüğü."""
    return {"surum": 1, "tur": "nihai_rapor", "kosu_kimligi": kosu_kimligi, "sahne_kimligi": sahne_kimligi, "mod": mod, "raporlar": raporlar}


def rapor_yaz(yol, rapor):
    """Raporu atomik yazar (geçici dosya + yeniden adlandırma): yarım dosya kalmaz."""
    gecici = yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(rapor, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(gecici, yol)


def birlestir_ve_yaz(kayitlar, aralik_m, rapor_yolu, kosu_kimligi, sahne_kimligi, mod):
    """Koordinatörün tek çağrısı: kayıtlar → birleştirme → dosya (yol verilirse). Dönen: (raporlar, girdi tespit sayısı, konumsuz rapor sayısı)."""
    tespitler = tespitleri_hazirla(kayitlar)
    raporlar = birlestir(tespitler, aralik_m)
    if rapor_yolu:
        rapor_yaz(rapor_yolu, nihai_rapor(kosu_kimligi, sahne_kimligi, mod, raporlar))
    return raporlar, len(tespitler), sum(1 for r in raporlar if r["konum"] is None)
