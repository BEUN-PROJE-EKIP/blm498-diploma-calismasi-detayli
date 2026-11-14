#!/usr/bin/env python3
"""Ağırlıklı ilerleme hesabı: planlama/gelistirme_agaci.md dosyasını okur, README.md içindeki
ILERLEME bölümünü günceller. Yalnız Python standart kitaplığı kullanır (venv gerekmez).

Kullanım:
  python3 araclar/ilerleme.py            sonucu ekrana yazar (hiçbir dosyayı değiştirmez)
  python3 araclar/ilerleme.py --yaz      README.md içindeki ILERLEME bölümünü günceller
  python3 araclar/ilerleme.py --kontrol  ağaç alanlarını denetler ve README.md güncel mi diye bakar (hata/eski ise çıkış kodu 1)

Ağaç biçimi: maddeler kilometre taşı başlıkları altında (`## M2 · Üç araç`) iş sırasıyla dizilir; madde satırı
  - [x] **B5** · w3 · M2 · geliştirme · Kısa ad · açıklama · ilgili gereksinim · Bitti: ...
Kilometre taşları tablosu (`## Kilometre taşları`): M, Ad, Sorumlu, Makine, Bekler. Paket ağırlıkları tablosu (`## Paket ağırlıkları`): Paket, Tarih, Ad, Ağırlık;
bir maddenin paketi kimliğinin harfinden (K, A, B, C, D, E) okunur. Eksik ya da yanlış alan açık hatayla (satır numarası) reddedilir. Madde düzeyinde bağımlılık izlenmez.

Hesap: bir maddenin katkısı = paket ağırlığı × w ÷ paketin tüm maddelerinin w toplamı.
  Genel tamamlanma    = biten maddelerin katkı toplamı (bütün maddeler, makine işi dahil; paket ağırlıkları toplamı 100).
  Geliştirme oranı    = biten `geliştirme` maddelerinin katkısı ÷ bütün `geliştirme` maddelerinin katkısı.
  Kilometre taşı oranı = aynı formül, yalnız o M'nin maddeleri üzerinden. `w0` (isteğe bağlı) maddeler hiçbir orana girmez.
"""
import pathlib
import re
import sys

KOK = pathlib.Path(__file__).resolve().parent.parent
AGAC = KOK / "planlama" / "gelistirme_agaci.md"
README = KOK / "README.md"
BASLA = "<!-- ILERLEME:BASLA -->"
BITIS = "<!-- ILERLEME:BITIS -->"

TURLER = ("geliştirme", "çalıştırma")
MADDE_ISARET_RE = re.compile(r"^- \[[ x]\] ")
MADDE_RE = re.compile(r"^- \[( |x)\] \*\*(\w+)\*\* · w(\d+) · (\w+) · ([^·]+?) · ([^·]+?) · (.*)$")
KIMLIK_RE = re.compile(r"^([A-Z])\d+[a-z]?$")
TABLO_BASLIK = "## Kilometre taşları"
PAKET_TABLO_BASLIK = "## Paket ağırlıkları"
M_RE = re.compile(r"^(K|M\d+[a-z]?)$")
BASLIK_RE = re.compile(r"^## (K|M\d+[a-z]?) · (.+?)\s*$")


class AgacHatasi(Exception):
    pass


def oku():
    """(kilometre taşları, paketler) döndürür; biçim hatasında AgacHatasi (satır numarasıyla).
    paketler: {kod: {"agirlik", "hafta", "ad", "maddeler": []}}; maddeler dosya sırasıyla her paketin listesine ve `hepsi` sırasına eklenir."""
    kilometre = {}
    paketler = {}
    hepsi = []
    kimlikler = set()
    bolum = ""        # "km" | "paket" | "madde" | ""
    bolum_m = ""
    for no, satir in enumerate(AGAC.read_text(encoding="utf-8").splitlines(), 1):
        if satir.startswith("## "):
            bolum_m = ""
            if satir.strip() == TABLO_BASLIK:
                bolum = "km"
            elif satir.strip() == PAKET_TABLO_BASLIK:
                bolum = "paket"
            else:
                b = BASLIK_RE.match(satir)
                if b:
                    bolum, bolum_m = "madde", b.group(1)
                    if b.group(1) not in kilometre:
                        raise AgacHatasi(f"{AGAC.name}:{no}: başlıktaki kilometre taşı tabloda yok: {b.group(1)}")
                    if kilometre[b.group(1)]["ad"] != b.group(2):
                        raise AgacHatasi(f"{AGAC.name}:{no}: başlıktaki ad tablodakiyle aynı değil: '{b.group(2)}' ≠ '{kilometre[b.group(1)]['ad']}'")
                else:
                    bolum = ""
            continue
        if bolum in ("km", "paket") and satir.startswith("|"):
            h = [x.strip() for x in satir.strip().strip("|").split("|")]
            if bolum == "km" and h and M_RE.match(h[0]):
                if len(h) != 5 or not all(h):
                    raise AgacHatasi(f"{AGAC.name}:{no}: kilometre taşı satırı 5 dolu hücre içermeli (M, Ad, Sorumlu, Makine, Bekler)")
                if h[0] in kilometre:
                    raise AgacHatasi(f"{AGAC.name}:{no}: kilometre taşı tekrarlanıyor: {h[0]}")
                bekler = [] if h[4] in ("—", "-") else [x.strip() for x in h[4].split(",")]
                kilometre[h[0]] = {"ad": h[1], "sorumlu": h[2], "makine": h[3], "bekler": bekler, "satir": no}
            elif bolum == "paket" and re.fullmatch(r"[A-Z]", h[0] if h else ""):
                if len(h) != 4 or not h[3].isdigit():
                    raise AgacHatasi(f"{AGAC.name}:{no}: paket satırı 4 hücre (Paket, Tarih, Ad, Ağırlık sayı) olmalı")
                if h[0] in paketler:
                    raise AgacHatasi(f"{AGAC.name}:{no}: paket tekrarlanıyor: {h[0]}")
                paketler[h[0]] = {"kod": h[0], "hafta": h[1], "ad": h[2], "agirlik": int(h[3]), "maddeler": []}
            continue
        if not MADDE_ISARET_RE.match(satir):
            continue
        if not bolum_m:
            raise AgacHatasi(f"{AGAC.name}:{no}: madde bir kilometre taşı başlığının (## M · ad) altında değil")
        m = MADDE_RE.match(satir)
        if not m:
            raise AgacHatasi(f"{AGAC.name}:{no}: madde biçimi bozuk (beklenen: `- [ ] **ID** · wN · M · tür · kısa ad · açıklama · ...`): {satir[:90]}")
        kimlik = m.group(2)
        if kimlik in kimlikler:
            raise AgacHatasi(f"{AGAC.name}:{no}: kimlik tekrarlanıyor: {kimlik}")
        kimlikler.add(kimlik)
        k = KIMLIK_RE.match(kimlik)
        if not k or k.group(1) not in paketler:
            raise AgacHatasi(f"{AGAC.name}:{no}: {kimlik}: kimliğin harfi bir pakete (Paket ağırlıkları tablosu) karşılık gelmiyor")
        if m.group(4) != bolum_m:
            raise AgacHatasi(f"{AGAC.name}:{no}: {kimlik}: M alanı '{m.group(4)}' ama madde '{bolum_m}' başlığı altında (her madde tam bir M'de olmalı)")
        tur, kisa, kalan = m.group(5).strip(), m.group(6).strip(), m.group(7)
        if tur not in TURLER:
            raise AgacHatasi(f"{AGAC.name}:{no}: {kimlik}: tür '{tur}' geçersiz (geliştirme | çalıştırma)")
        if kalan.startswith("@"):
            raise AgacHatasi(f"{AGAC.name}:{no}: {kimlik}: madde düzeyinde sorumlu alanı yok; her kilometre taşının tek sahibi var")
        parcalar = kalan.split(" · ")
        ilgili = parcalar[1].strip() if len(parcalar) > 2 else ""
        madde = {"bitti": m.group(1) == "x", "kimlik": kimlik, "w": int(m.group(3)), "m": bolum_m, "paket": k.group(1),
                 "tur": tur, "kisa": kisa, "aciklama": parcalar[0].strip(), "ilgili": ilgili, "satir": no}
        paketler[k.group(1)]["maddeler"].append(madde)
        hepsi.append(madde)
    return kilometre, paketler, hepsi


def kontrol_et(kilometre, paketler, hepsi):
    hatalar = []
    if not kilometre:
        hatalar.append(f"{AGAC.name}: '{TABLO_BASLIK}' tablosu yok ya da boş")
    if not paketler:
        hatalar.append(f"{AGAC.name}: '{PAKET_TABLO_BASLIK}' tablosu yok ya da boş")
    for kod, k in kilometre.items():
        yer = f"{AGAC.name}:{k['satir']}: {kod}"
        for b in k["bekler"]:
            if b == kod:
                hatalar.append(f"{yer}: kilometre taşı kendisini bekliyor")
            elif b not in kilometre:
                hatalar.append(f"{yer}: Bekler sütunundaki '{b}' kilometre taşları tablosunda yok")
        if not any(m["m"] == kod for m in hepsi):
            hatalar.append(f"{yer}: kilometre taşının hiç maddesi yok")
    for m in hepsi:
        yer = f"{AGAC.name}:{m['satir']}: {m['kimlik']}"
        if m["m"] not in kilometre:
            hatalar.append(f"{yer}: M '{m['m']}' kilometre taşları tablosunda yok")
        if len(m["kisa"].split()) > 6:
            hatalar.append(f"{yer}: kısa ad en çok 6 kelime olmalı ({len(m['kisa'].split())}): {m['kisa']}")
    return hatalar


def yuzde(x):
    return f"%{x:.1f}".replace(".", ",")


def katkilar(paketler):
    """Her maddeye 'katki' (paket ağırlığı × w ÷ paket toplam w) ekler."""
    for p in paketler.values():
        toplam = sum(m["w"] for m in p["maddeler"])
        for m in p["maddeler"]:
            m["katki"] = p["agirlik"] * m["w"] / toplam if toplam else 0.0


def oran(maddeler):
    """Verilen maddelerin biten katkısı ÷ toplam katkısı (yüzde değil, 0-1). Katkı yoksa 0."""
    pay = sum(m["katki"] for m in maddeler if m["bitti"])
    payda = sum(m["katki"] for m in maddeler)
    return pay / payda if payda else 0.0


def genel_yuzde(hepsi):
    return sum(m["katki"] for m in hepsi if m["bitti"])


def cubuk(oran_yuzde):
    dolu = round(oran_yuzde / 100 * 20)
    return "█" * dolu + "░" * (20 - dolu)


def durum_simgesi(maddeler):
    zorunlu = [m for m in maddeler if m["w"] > 0]
    biten = sum(1 for m in zorunlu if m["bitti"])
    if zorunlu and biten == len(zorunlu):
        return "✔"
    return "◐" if biten else "☐"


def uret(kilometre, paketler, hepsi):
    if sum(p["agirlik"] for p in paketler.values()) != 100:
        raise SystemExit("(-) Paket ağırlıklarının toplamı 100 değil")
    katkilar(paketler)
    gelistirme = [m for m in hepsi if m["tur"] == "geliştirme"]
    genel = genel_yuzde(hepsi)
    gel = 100 * oran(gelistirme)
    bitmis = {kod for kod in kilometre if durum_simgesi([m for m in hepsi if m["m"] == kod]) == "✔"}

    s = []
    s.append(f"**Genel tamamlanma: {yuzde(genel)}** ({sum(1 for m in hepsi if m['bitti'])} / {len(hepsi)} madde; kod ve makine işi dahil)")
    s.append("")
    s.append(f"`{cubuk(genel)}` {yuzde(genel)}")
    s.append("")
    s.append(f"**Geliştirme oranı: {yuzde(gel)}** ({sum(1 for m in gelistirme if m['bitti'])} / {len(gelistirme)} geliştirme maddesi; yalnız kod ve altyapı işi)")
    s.append("")
    s.append(f"`{cubuk(gel)}` {yuzde(gel)}")
    s.append("")
    s.append("Kilometre taşları (✔ bitti, ◐ sürüyor, ☐ başlamadı). Maddeler iş sırasıyla dizilidir: sıradaki iş, bitmemiş en üstteki maddedir. Biten kilometre taşları kapalıdır, başlığına tıklayınca açılır.")
    s.append("")
    for kod, k in kilometre.items():
        ms = [m for m in hepsi if m["m"] == kod]
        simge = durum_simgesi(ms)
        s.append("<details>" if simge == "✔" else "<details open>")
        if simge == "✔":
            s.append(f"<summary>{simge} <b>{kod} - {k['ad']}</b> [{yuzde(100 * oran(ms))}]</summary>")
        else:
            s.append(f"<summary>{simge} <b>{kod} - {k['ad']}</b> [{k['sorumlu']}, {yuzde(100 * oran(ms))}]</summary>")
        s.append("")
        if simge != "✔":
            bekledigi = [b for b in k["bekler"] if b not in bitmis]
            s.append("Bekler: " + (", ".join(bekledigi) if bekledigi else "yok, başlayabilir"))
            s.append("")
        for m in ms:
            etiket = f"{'✔' if m['bitti'] else '☐'} {m['kimlik']} - {m['kisa']}"
            if m["w"] == 0:
                etiket += " (isteğe bağlı)"
            s.append(f"- {etiket}")
        s.append("")
        s.append("</details>")
        s.append("")
    s.append("Ayrıntı ve bitti ölçütleri: `planlama/gelistirme_agaci.md`.")
    return "\n".join(s).rstrip() + "\n"


def readme_guncelle(blok):
    metin = README.read_text(encoding="utf-8")
    if BASLA not in metin or BITIS not in metin:
        raise SystemExit("(-) README.md içinde ILERLEME işaretleri yok")
    bas = metin.index(BASLA) + len(BASLA)
    bit = metin.index(BITIS)
    return metin[:bas] + "\n" + blok + metin[bit:]


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ("-h", "--help"):
        print(__doc__)
        return 0
    try:
        kilometre, paketler, hepsi = oku()
    except AgacHatasi as e:
        print(f"(-) {e}")
        return 1
    hatalar = kontrol_et(kilometre, paketler, hepsi)
    if hatalar:
        for h in hatalar:
            print(f"(-) {h}")
        return 1
    blok = uret(kilometre, paketler, hepsi)
    if arg == "":
        print(blok)
        return 0
    yeni = readme_guncelle(blok)
    if arg == "--yaz":
        README.write_text(yeni, encoding="utf-8")
        print("(+) README.md ilerleme bölümü güncellendi")
        return 0
    if arg == "--kontrol":
        print(f"(+) Ağaç alanları geçerli ({len(hepsi)} madde, {len(kilometre)} kilometre taşı)")
        if README.read_text(encoding="utf-8") == yeni:
            print("(+) README.md ilerleme bölümü güncel")
            return 0
        print("(-) README.md ilerleme bölümü eski; çalıştır: python3 araclar/ilerleme.py --yaz")
        return 1
    print("(-) Bilinmeyen seçenek:", arg)
    return 2


if __name__ == "__main__":
    sys.exit(main())
