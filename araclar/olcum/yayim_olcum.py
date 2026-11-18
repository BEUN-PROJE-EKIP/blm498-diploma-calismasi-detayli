#!/usr/bin/env python3
"""Kare yayımlanma anı keşfi (FR-23): sahne üretimi, saat eşliği denetimi ve kayıt analizi.

Kullanım:
  yayim_olcum.py dunya <cikti.sdf> <kamera_sayisi> <cikti_dizini> <yontem>   kamera_olcum.py sahnesine YayimDamga eklentisini ekler
  yayim_olcum.py saat <saat_kontrol_ikilisi>                                  CLOCK_MONOTONIC ile time.monotonic_ns() eşliğini sınar
  yayim_olcum.py analiz <alici.csv> <yayim_damga.csv> <ad>                    alıcı kaydıyla bileşen kaydını damga üzerinden birleştirir
  yayim_olcum.py kapanis <alici.csv> <yayim_damga.csv> <ad> <sinyal>          sunucuya sinyal verildikten sonra bileşen kaydının sonu
Alıcı tarafı (kamera_olcum.py kare ...) mevcut kayıt biçimini yazar: konu,sira,damga_ns,alici_monotonik_ns.
Değerler ortam değişkenlerinden okunur (setup/yayim_olcum_testi.sh, config/deney.env'den verir); kamera_olcum.py ile aynı CAM_* değişkenleri.
Yorum yoktur: ölçülen sayılar yazılır.
"""
import csv
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # araclar kökü (sozlesme_dogrula, koordinator_kayit)
import kamera_olcum as ko  # noqa: E402


def yuzdelik(v, p):
    v = sorted(v)
    if not v:
        return float("nan")
    k = (len(v) - 1) * p / 100.0
    a = int(k)
    b = min(a + 1, len(v) - 1)
    return v[a] + (v[b] - v[a]) * (k - a)


def dunya(cikti, n, cikti_dizini, yontem):
    ko.sdf_uret(cikti, n)
    hz = os.environ["CAM_RATE_HZ"]
    # Dünya SDF'inde <plugin> varsa sunucu yapılandırmasındaki (GZ_SIM_SERVER_CONFIG_PATH) eklentiler yüklenmez; K9 sahnesiyle aynı
    # sistemleri (fizik, algılayıcılar vb.) korumak için sunucu yapılandırmasındaki eklentiler dünyaya aynen kopyalanır.
    yol = os.environ.get("GZ_SIM_SERVER_CONFIG_PATH", "")
    if not os.path.isfile(yol):
        print("SONUC kaldi dunya | GZ_SIM_SERVER_CONFIG_PATH bir dosya göstermiyor (gz_env.sh kaynaklanmadı)", flush=True)
        return 1
    with open(yol, encoding="utf-8") as f:
        konfig = re.sub(r"<!--.*?-->", "", f.read(), flags=re.S)
    konfig = re.sub(r'\s+entity_(?:name|type)="[^"]*"', "", konfig)   # bu iki öznitelik yalnız sunucu yapılandırmasında geçerlidir
    sistemler = "".join("    " + m.group(0) + "\n" for m in re.finditer(r"<plugin\b.*?(?:/>|</plugin>)", konfig, flags=re.S))
    ek = sistemler
    if yontem != "hicbiri":   # "hicbiri": karşılaştırma için aynı sistemler, damga bileşeni yok
        ek += (f'    <plugin filename="YayimDamga" name="yayim::YayimDamga"><yontem>{yontem}</yontem>'
               f'<cikti_dizini>{cikti_dizini}</cikti_dizini><hz>{hz}</hz></plugin>\n')
    with open(cikti, encoding="utf-8") as f:
        s = f.read()
    assert s.count("  </world>") == 1
    s = s.replace("  </world>", ek + "  </world>")
    with open(cikti, "w", encoding="utf-8") as f:
        f.write(s)
    return 0


def saat(ikili):
    sonuc = []
    for _ in range(20):
        a = time.monotonic_ns()
        cikti = subprocess.run([ikili], capture_output=True, text=True, check=True).stdout.split()
        b = time.monotonic_ns()
        ca, cs, cb = (int(x) for x in cikti)
        sonuc.append((a, ca, cs, cb, b))
    # Her turda: a ≤ C++ MonotonikNs() ≤ b ve a ≤ steady_clock ≤ b (Python monotonic_ns okumaları arasında)
    ihlal = sum(1 for (a, ca, cs, cb, b) in sonuc if not (a <= ca <= cb <= b and a <= cs <= b))
    en_genis = max(b - a for (a, ca, cs, cb, b) in sonuc)
    en_dar_fark = min(min(ca - a, b - cb) for (a, ca, cs, cb, b) in sonuc)
    print(f"SAAT tur=20 ihlal={ihlal} en_genis_aralik={en_genis}ns en_kucuk_kenar_payi={en_dar_fark}ns "
          f"python_saat={time.get_clock_info('monotonic').implementation}", flush=True)
    if ihlal:
        print("SONUC kaldi saat | C++ CLOCK_MONOTONIC/steady_clock okuması Python monotonic_ns okumalarının dışında kaldı", flush=True)
        return 1
    print("SONUC gecti saat | 20/20 turda C++ CLOCK_MONOTONIC ve steady_clock, iki Python time.monotonic_ns() okuması arasında", flush=True)
    return 0


def oku_alici(yol):
    d = {}
    with open(yol, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d.setdefault(r["konu"], {})[int(r["damga_ns"])] = int(r["alici_monotonik_ns"])
    return d


def oku_yayim(yol):
    d = {}
    with open(yol, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d.setdefault((r["yontem"], r["konu"].lstrip("/")), []).append(r)
    return d


def ozet(ad, deltalar):
    if not deltalar:
        return f"{ad}: eşleşen kare yok"
    neg = sum(1 for x in deltalar if x < 0)
    ms = lambda x: x / 1e6  # noqa: E731
    return (f"{ad}: n={len(deltalar)} min={ms(min(deltalar)):.3f}ms ortanca={ms(yuzdelik(deltalar, 50)):.3f}ms "
            f"p99={ms(yuzdelik(deltalar, 99)):.3f}ms maks={ms(max(deltalar)):.3f}ms negatif={neg}")


def analiz(alici_yolu, yayim_yolu, ad):
    alici = oku_alici(alici_yolu)
    yayim = oku_yayim(yayim_yolu)
    yontemler = sorted({y for (y, _) in yayim})
    sayim = {y: sum(len(v) for (yy, _), v in yayim.items() if yy == y) for y in yontemler}
    print(f"YAYIM {ad} satir_sayilari: {sayim}", flush=True)
    # Konu adları baştaki / atılarak karşılaştırılır.
    sapma = 0
    for y in yontemler:
        toplam_b = toplam_a = toplam_b_pencere = 0
        yalniz_b = yalniz_a = 0
        damga_uyumsuz = 0
        delta = []
        izgara_disi = 0
        for konu, a_map in alici.items():
            satirlar = yayim.get((y, konu.lstrip("/")), [])
            b_map = {}
            for r in satirlar:
                b_map.setdefault(int(r["damga_ns"]), []).append(r)
            toplam_b += len(satirlar)
            toplam_a += len(a_map)
            for dm, w_a in a_map.items():
                if dm not in b_map:
                    yalniz_a += 1
                    continue
                w_b = int(b_map[dm][0]["mono_ns"])
                delta.append(w_a - w_b)
            damga_uyumsuz += sum(len(v) - 1 for v in b_map.values() if len(v) > 1)
            izgara_disi += sum(1 for r in satirlar if r["n"] == "izgara_disi")
            if a_map:
                amin, amax = min(a_map), max(a_map)
                yalniz_b += sum(1 for dm in b_map if amin <= dm <= amax and dm not in a_map)
                toplam_b_pencere += sum(1 for dm in b_map if amin <= dm <= amax)
        print(f"YAYIM {ad} {y}: bilesen_satir={toplam_b} alici_satir={toplam_a} bilesen_satir_alici_penceresinde={toplam_b_pencere} "
              f"yalniz_bilesende(pencerede)={yalniz_b} yalniz_alicida={yalniz_a} "
              f"yinelenen_damga={damga_uyumsuz} izgara_disi={izgara_disi}", flush=True)
        print("YAYIM " + ozet(f"{ad} {y} delta=t_alici-t_damga", delta), flush=True)
        if any(x < 0 for x in delta):
            sapma += 1
    # (iii) iki yöntem arasındaki fark ve (v) damga birebirliği
    if len(yontemler) >= 2:
        a_y, b_y = yontemler[0], yontemler[1]
        fark = []
        eslesme = 0
        yalniz = 0
        for konu in alici:
            yol = konu.lstrip("/")
            ma = {int(r["damga_ns"]): int(r["mono_ns"]) for r in yayim.get((a_y, yol), [])}
            mb = {int(r["damga_ns"]): int(r["mono_ns"]) for r in yayim.get((b_y, yol), [])}
            for dm, w in ma.items():
                if dm in mb:
                    fark.append(mb[dm] - w)
                    eslesme += 1
                else:
                    yalniz += 1
        print(f"YAYIM {ad} yontem_farki ({b_y} - {a_y}): ortak_damga={eslesme} yalniz_{a_y}={yalniz}", flush=True)
        print("YAYIM " + ozet(f"{ad} {b_y}-{a_y}", fark), flush=True)
    print(f"SONUC gecti analiz_{ad} | tablolar yazıldı (negatif Δ olan yöntem sayısı: {sapma})", flush=True)
    return 0


def kapanis(alici_yolu, yayim_yolu, ad, sinyal):
    """Sunucuya sinyal gönderildikten sonra bileşen kaydının son satırı, alıcının gördüğü son kareye göre kaç kare geride/ileride."""
    alici = oku_alici(alici_yolu)
    yayim = oku_yayim(yayim_yolu)
    hz = float(os.environ["CAM_RATE_HZ"])
    for konu, a_map in alici.items():
        son_a = max(a_map)
        for (y, k), satirlar in sorted(yayim.items()):
            if k != konu.lstrip("/"):
                continue
            son_b = max(int(r["damga_ns"]) for r in satirlar)
            print(f"YAYIM {ad} kapanis sinyal={sinyal} {y}: bilesen_son={son_b * 1e-9:.3f}s alici_son={son_a * 1e-9:.3f}s "
                  f"fark_kare={(son_b - son_a) * 1e-9 * hz:+.1f} bilesen_satir={len(satirlar)}", flush=True)
    print(f"SONUC gecti kapanis_{ad} | tablo yazıldı", flush=True)
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "dunya" and len(argv) == 6:
        return dunya(argv[2], int(argv[3]), argv[4], argv[5])
    if len(argv) == 3 and argv[1] == "saat":
        return saat(argv[2])
    if len(argv) == 6 and argv[1] == "kapanis":
        return kapanis(argv[2], argv[3], argv[4], argv[5])
    if len(argv) == 5 and argv[1] == "analiz":
        return analiz(argv[2], argv[3], argv[4])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
