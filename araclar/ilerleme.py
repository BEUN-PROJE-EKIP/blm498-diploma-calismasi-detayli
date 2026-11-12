#!/usr/bin/env python3
"""Ağırlıklı ilerleme hesabı: planlama/gelistirme_agaci.md dosyasını okur, README.md içindeki
ILERLEME bölümünü günceller. Yalnız Python standart kitaplığı kullanır (venv gerekmez).

Kullanım:
  python3 araclar/ilerleme.py            sonucu ekrana yazar (hiçbir dosyayı değiştirmez)
  python3 araclar/ilerleme.py --yaz      README.md içindeki ILERLEME bölümünü günceller
  python3 araclar/ilerleme.py --kontrol  README.md güncel mi? (güncel değilse çıkış kodu 1)

Hesap: paket ilerlemesi = biten maddelerin ağırlığı / paketin tüm maddelerinin ağırlığı.
Toplam ilerleme = Σ (paket ağırlığı × paket ilerlemesi). Paket ağırlıkları toplamı 100'dür.
"""
import pathlib
import re
import sys

KOK = pathlib.Path(__file__).resolve().parent.parent
AGAC = KOK / "planlama" / "gelistirme_agaci.md"
README = KOK / "README.md"
BASLA = "<!-- ILERLEME:BASLA -->"
BITIS = "<!-- ILERLEME:BITIS -->"

PAKET_RE = re.compile(r"^## (\S+) · (.+?) · (.+?) · ağırlık (\d+)\s*$")
MADDE_RE = re.compile(r"^- \[( |x)\] \*\*(\w+)\*\* · w(\d+) · (.*)$")


def oku():
    paketler = []
    for satir in AGAC.read_text(encoding="utf-8").splitlines():
        m = PAKET_RE.match(satir)
        if m:
            paketler.append({"kod": m.group(1), "hafta": m.group(2), "ad": m.group(3),
                             "agirlik": int(m.group(4)), "maddeler": []})
            continue
        m = MADDE_RE.match(satir)
        if m and paketler:
            parcalar = m.group(4).split(" · ")
            aciklama = parcalar[0].strip()
            ilgili = parcalar[1].strip() if len(parcalar) > 2 else ""
            paketler[-1]["maddeler"].append({
                "bitti": m.group(1) == "x", "kimlik": m.group(2),
                "w": int(m.group(3)), "aciklama": aciklama, "ilgili": ilgili})
    return paketler


def yuzde(x):
    return f"%{x:.1f}".replace(".", ",")


def paket_orani(p):
    toplam = sum(m["w"] for m in p["maddeler"])
    biten = sum(m["w"] for m in p["maddeler"] if m["bitti"])
    return (biten / toplam) if toplam else 0.0


def uret(paketler):
    if sum(p["agirlik"] for p in paketler) != 100:
        raise SystemExit("(-) Paket ağırlıklarının toplamı 100 değil")
    toplam = sum(p["agirlik"] * paket_orani(p) for p in paketler)
    dolu = round(toplam / 100 * 20)
    cubuk = "█" * dolu + "░" * (20 - dolu)
    n_biten = sum(1 for p in paketler for m in p["maddeler"] if m["bitti"])
    n_toplam = sum(len(p["maddeler"]) for p in paketler)

    s = []
    s.append(f"**Projenin tamamlanma oranı: {yuzde(toplam)}**  ({n_biten} / {n_toplam} madde bitti)")
    s.append("")
    s.append(f"`{cubuk}` {yuzde(toplam)}")
    s.append("")
    s.append("| Paket | Tarih | Ağırlık | Biten madde | Paketin ilerlemesi |")
    s.append("|---|---|---|---|---|")
    for p in paketler:
        biten = sum(1 for m in p["maddeler"] if m["bitti"])
        s.append(f"| {p['kod']}. {p['ad']} | {p['hafta']} | %{p['agirlik']} | {biten} / {len(p['maddeler'])} | {yuzde(100 * paket_orani(p))} |")
    s.append("")
    s.append("Aşağıdaki başlıklara tıklayınca maddeleri görürsün. Biten maddeler işaretli kutu (☑), kalın `[TAMAMLANDI]` etiketi ve italik açıklamayla; bitmeyenler boş kutuyla (☐) gösterilir.")
    s.append("")
    for p in paketler:
        biten = sum(1 for m in p["maddeler"] if m["bitti"])
        s.append("<details>")
        s.append(f"<summary><b>{p['kod']}. {p['ad']}</b> · {p['hafta']} · {biten} / {len(p['maddeler'])} madde · {yuzde(100 * paket_orani(p))}</summary>")
        s.append("")
        for m in p["maddeler"]:
            metin = m["aciklama"].replace("**", "")
            if m["ilgili"]:
                metin += f" ({m['ilgili']})"
            if m["bitti"]:
                s.append(f"- [x] **{m['kimlik']} [TAMAMLANDI]** - *{metin}*")
            else:
                s.append(f"- [ ] {m['kimlik']} - {metin}")
        s.append("")
        s.append("</details>")
        s.append("")
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
    blok = uret(oku())
    if arg == "":
        print(blok)
        return 0
    yeni = readme_guncelle(blok)
    if arg == "--yaz":
        README.write_text(yeni, encoding="utf-8")
        print("(+) README.md ilerleme bölümü güncellendi")
        return 0
    if arg == "--kontrol":
        if README.read_text(encoding="utf-8") == yeni:
            print("(+) README.md ilerleme bölümü güncel")
            return 0
        print("(-) README.md ilerleme bölümü eski; çalıştır: python3 araclar/ilerleme.py --yaz")
        return 1
    print("(-) Bilinmeyen seçenek:", arg)
    return 2


if __name__ == "__main__":
    sys.exit(main())
