#!/usr/bin/env python3
"""Ağırlıklı ilerleme hesabı: planlama/gelistirme_agaci.md dosyasını okur, README.md içindeki
ILERLEME bölümünü günceller. Yalnız Python standart kitaplığı kullanır (venv gerekmez).

Kullanım:
  python3 araclar/ilerleme.py            sonucu ekrana yazar (hiçbir dosyayı değiştirmez)
  python3 araclar/ilerleme.py --yaz      README.md içindeki ILERLEME bölümünü günceller
  python3 araclar/ilerleme.py --kontrol  ağaç alanlarını denetler ve README.md güncel mi diye bakar (hata/eski ise çıkış kodu 1)

Ağaç biçimi (madde satırı):
  - [x] **B5** · w3 · M2 · geliştirme · Kısa ad · [@Ad Soyad ·] açıklama · ilgili gereksinim · Bitti: ...
Kilometre taşları tablosu (`## Kilometre taşları`): M, Ad, Sorumlu, Makine. Eksik ya da yanlış alan açık hatayla (satır numarası) reddedilir.

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
PAKET_RE = re.compile(r"^## (\S+) · (.+?) · (.+?) · ağırlık (\d+)\s*$")
MADDE_ISARET_RE = re.compile(r"^- \[[ x]\] ")
MADDE_RE = re.compile(r"^- \[( |x)\] \*\*(\w+)\*\* · w(\d+) · (\w+) · ([^·]+?) · ([^·]+?) · (.*)$")
SORUMLU_RE = re.compile(r"^@[^\W\d_][\w.\-]*( [^\W\d_][\w.\-]*)+$")
TABLO_BASLIK = "## Kilometre taşları"
M_RE = re.compile(r"^(K|M\d+)$")


class AgacHatasi(Exception):
    pass


def oku():
    """(kilometre taşları, paketler) döndürür; biçim hatasında AgacHatasi (satır numarasıyla)."""
    kilometre = {}
    paketler = []
    kimlikler = set()
    tabloda = False
    for no, satir in enumerate(AGAC.read_text(encoding="utf-8").splitlines(), 1):
        if satir.startswith("## "):
            tabloda = satir.strip() == TABLO_BASLIK
        if tabloda and satir.startswith("|"):
            h = [x.strip() for x in satir.strip().strip("|").split("|")]
            if h and M_RE.match(h[0]):
                if len(h) != 4 or not all(h):
                    raise AgacHatasi(f"{AGAC.name}:{no}: kilometre taşı satırı 4 dolu hücre içermeli (M, Ad, Sorumlu, Makine)")
                if h[0] in kilometre:
                    raise AgacHatasi(f"{AGAC.name}:{no}: kilometre taşı tekrarlanıyor: {h[0]}")
                kilometre[h[0]] = {"ad": h[1], "sorumlu": h[2], "makine": h[3]}
            continue
        m = PAKET_RE.match(satir)
        if m:
            paketler.append({"kod": m.group(1), "hafta": m.group(2), "ad": m.group(3),
                             "agirlik": int(m.group(4)), "maddeler": []})
            continue
        if not MADDE_ISARET_RE.match(satir):
            continue
        if not paketler:
            raise AgacHatasi(f"{AGAC.name}:{no}: madde bir paket başlığından önce")
        m = MADDE_RE.match(satir)
        if not m:
            raise AgacHatasi(f"{AGAC.name}:{no}: madde biçimi bozuk (beklenen: `- [ ] **ID** · wN · M · tür · kısa ad · [@sorumlu ·] açıklama · ...`): {satir[:90]}")
        kimlik = m.group(2)
        if kimlik in kimlikler:
            raise AgacHatasi(f"{AGAC.name}:{no}: kimlik tekrarlanıyor: {kimlik}")
        kimlikler.add(kimlik)
        tur, kisa, kalan = m.group(5).strip(), m.group(6).strip(), m.group(7)
        if tur not in TURLER:
            raise AgacHatasi(f"{AGAC.name}:{no}: {kimlik}: tür '{tur}' geçersiz (geliştirme | çalıştırma)")
        # kalan: (isteğe bağlı) "@sorumlu · " ile başlayabilir
        sorumlu = ""
        if kalan.startswith("@"):
            sorumlu, _, kalan = kalan.partition(" · ")
            if not SORUMLU_RE.match(sorumlu):
                raise AgacHatasi(f"{AGAC.name}:{no}: {kimlik}: sorumlu biçimi '@Ad Soyad' olmalı: {sorumlu}")
        parcalar = kalan.split(" · ")
        ilgili = parcalar[1].strip() if len(parcalar) > 2 else ""
        paketler[-1]["maddeler"].append({
            "bitti": m.group(1) == "x", "kimlik": kimlik, "w": int(m.group(3)), "m": m.group(4),
            "tur": tur, "kisa": kisa, "sorumlu": sorumlu[1:] if sorumlu else "",
            "aciklama": parcalar[0].strip(), "ilgili": ilgili, "satir": no})
    return kilometre, paketler


def kontrol_et(kilometre, paketler):
    hatalar = []
    if not kilometre:
        hatalar.append(f"{AGAC.name}: '{TABLO_BASLIK}' tablosu yok ya da boş")
    for p in paketler:
        for m in p["maddeler"]:
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
    for p in paketler:
        toplam = sum(m["w"] for m in p["maddeler"])
        for m in p["maddeler"]:
            m["katki"] = p["agirlik"] * m["w"] / toplam if toplam else 0.0


def oran(maddeler):
    """Verilen maddelerin biten katkısı ÷ toplam katkısı (yüzde değil, 0-1). Katkı yoksa 0."""
    pay = sum(m["katki"] for m in maddeler if m["bitti"])
    payda = sum(m["katki"] for m in maddeler)
    return pay / payda if payda else 0.0


def genel_yuzde(paketler):
    return sum(m["katki"] for p in paketler for m in p["maddeler"] if m["bitti"])


def cubuk(oran_yuzde):
    dolu = round(oran_yuzde / 100 * 20)
    return "█" * dolu + "░" * (20 - dolu)


def durum_simgesi(maddeler):
    zorunlu = [m for m in maddeler if m["w"] > 0]
    biten = sum(1 for m in zorunlu if m["bitti"])
    if zorunlu and biten == len(zorunlu):
        return "✔"
    return "◐" if biten else "☐"


def uret(kilometre, paketler):
    if sum(p["agirlik"] for p in paketler) != 100:
        raise SystemExit("(-) Paket ağırlıklarının toplamı 100 değil")
    katkilar(paketler)
    hepsi = [m for p in paketler for m in p["maddeler"]]
    gelistirme = [m for m in hepsi if m["tur"] == "geliştirme"]
    genel = genel_yuzde(paketler)
    gel = 100 * oran(gelistirme)

    s = []
    s.append(f"**Genel tamamlanma: {yuzde(genel)}** ({sum(1 for m in hepsi if m['bitti'])} / {len(hepsi)} madde; kod ve makine işi dahil)")
    s.append("")
    s.append(f"`{cubuk(genel)}` {yuzde(genel)}")
    s.append("")
    s.append(f"**Geliştirme oranı: {yuzde(gel)}** ({sum(1 for m in gelistirme if m['bitti'])} / {len(gelistirme)} geliştirme maddesi; yalnız kod ve altyapı işi)")
    s.append("")
    s.append(f"`{cubuk(gel)}` {yuzde(gel)}")
    s.append("")
    s.append("Kilometre taşları (✔ bitti, ◐ sürüyor, ☐ başlamadı). Biten kilometre taşları kapalıdır, başlığına tıklayınca açılır.")
    s.append("")
    for kod, k in kilometre.items():
        ms = [m for m in hepsi if m["m"] == kod]
        simge = durum_simgesi(ms)
        acik = "" if simge == "✔" else " open"
        s.append(f"<details{acik}>")
        s.append(f"<summary>{simge} <b>{kod} · {k['ad']}</b> · {k['sorumlu']} · {yuzde(100 * oran(ms))}</summary>")
        s.append("")
        for m in ms:
            etiket = f"{'✔' if m['bitti'] else '☐'} {m['kimlik']} {m['kisa']}"
            if m["sorumlu"] and m["sorumlu"] != k["sorumlu"]:
                etiket += f" ({m['sorumlu']})"
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
        kilometre, paketler = oku()
    except AgacHatasi as e:
        print(f"(-) {e}")
        return 1
    hatalar = kontrol_et(kilometre, paketler)
    if hatalar:
        for h in hatalar:
            print(f"(-) {h}")
        return 1
    blok = uret(kilometre, paketler)
    if arg == "":
        print(blok)
        return 0
    yeni = readme_guncelle(blok)
    if arg == "--yaz":
        README.write_text(yeni, encoding="utf-8")
        print("(+) README.md ilerleme bölümü güncellendi")
        return 0
    if arg == "--kontrol":
        n = sum(len(p["maddeler"]) for p in paketler)
        print(f"(+) Ağaç alanları geçerli ({n} madde, {len(kilometre)} kilometre taşı)")
        if README.read_text(encoding="utf-8") == yeni:
            print("(+) README.md ilerleme bölümü güncel")
            return 0
        print("(-) README.md ilerleme bölümü eski; çalıştır: python3 araclar/ilerleme.py --yaz")
        return 1
    print("(-) Bilinmeyen seçenek:", arg)
    return 2


if __name__ == "__main__":
    sys.exit(main())
