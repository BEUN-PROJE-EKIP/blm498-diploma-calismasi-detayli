#!/usr/bin/env python3
"""Koşu üst verisi (kosu.json) yazıcısı; araclar/kosu.sh tarafından çağrılır. Yalnız standart kitaplık.

Kullanım:
  kosu_ustveri.py baslangic <kosu.json> <kosu_kimligi> <arac_sayisi> "<arac_kimlikleri>" <gz_partition> <dunya> <model> [<yapilandirma_dosyasi>]
  kosu_ustveri.py surec-ekle <kosu.json> <ad> <pid> <grup>
  kosu_ustveri.py bitir <kosu.json> <tamamlandi|zorla_kapatildi|yarida_kaldi> [<zorla_kapatilan_ad> ...]
  kosu_ustveri.py surecler <kosu.json>          süreçleri "ad pid grup" satırları olarak yazar
  kosu_ustveri.py durum-alani <kosu.json> <alan>  üst düzey bir alanı yazar (null için boş satır)
Biçim: planlama/sozlesmeler.md "Koşu kaydı". Süre: CLOCK_MONOTONIC (time.monotonic_ns()). Mutlak yol, kullanıcı ve makine adı yazılmaz.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha256(yol):
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for blok in iter(lambda: f.read(1 << 20), b""):
            h.update(blok)
    return h.hexdigest()


def kaynak_ozeti():
    """`src/` altındaki dosyaların içerik özeti (SHA-256): git'in izlediği (`--cached`) ve henüz izlenmeyen ama yok sayılmayan (`--others --exclude-standard`) dosyaların YOL + içerik SHA-256 satırları sıralanıp özetlenir.
    Git commit'inden bağımsızdır: kirli çalışma ağacında (commit edilmemiş değişiklik, yeni dosya) doğru kalır; çalışma ağacında silinmiş dosya atlanır. Derlenen kaynağın kanıtıdır (kosu.sh derlemeyi hemen önce yapar)."""
    cikti = subprocess.run(["git", "-C", KOK, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "src"], capture_output=True, check=True).stdout
    h = hashlib.sha256()
    for yol in sorted({p for p in cikti.split(b"\0") if p}):
        tam = os.path.join(KOK, yol.decode("utf-8"))
        if os.path.isfile(tam):
            h.update(yol + b"\0" + sha256(tam).encode() + b"\n")
    return h.hexdigest()


def zaman():
    return {"duvar_iso": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "monotonik_ns": time.monotonic_ns()}


def git(*arg):
    return subprocess.run(["git", "-C", KOK, *arg], capture_output=True, text=True, check=True).stdout


def oku(yol):
    with open(yol, encoding="utf-8") as f:
        return json.load(f)


def yaz(yol, d):
    gecici = yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(gecici, yol)


def main(a):
    if len(a) >= 2 and a[0] == "baslangic" and len(a) in (8, 9):
        yol, kimlik, n, kimlikler, part, dunya, model = a[1:8]
        yap = a[8] if len(a) == 9 else os.path.join(KOK, "config", "deney.env")
        temiz = git("status", "--porcelain").strip() == ""
        yaz(yol, {
            "surum": 1, "tur": "kosu_ustveri", "kosu_kimligi": kimlik, "baslangic": zaman(), "bitis": None,
            "depo": {"commit": git("rev-parse", "HEAD").strip(), "calisma_agaci_temiz": temiz},
            "yapilandirma_sha256": sha256(yap), "ortam_kilidi_sha256": sha256(os.path.join(KOK, "setup", "locks", "sha256sums.txt")),
            "rota_sha256": sha256(os.path.join(KOK, "config", "bolge_rota.json")), "kaynak_sha256": kaynak_ozeti(),
            "arac_sayisi": int(n), "arac_kimlikleri": [int(x) for x in kimlikler.split()], "mimari_modu": "yok", "sahne_kimligi": None,
            "dunya": dunya, "model": model, "gz_partition": part, "surecler": [], "bitis_durumu": None})
        return 0
    if len(a) == 3 and a[0] == "mimari":
        d = oku(a[1])
        d["mimari_modu"] = a[2]
        yaz(a[1], d)
        return 0
    if len(a) == 5 and a[0] == "surec-ekle":
        d = oku(a[1])
        d["surecler"].append({"ad": a[2], "pid": int(a[3]), "grup": int(a[4])})
        yaz(a[1], d)
        return 0
    if len(a) >= 3 and a[0] == "bitir":
        d = oku(a[1])
        if d.get("bitis_durumu") is not None:
            return 0   # zaten kapanmış: ilk yazılan durum korunur
        d["bitis"] = zaman()
        d["bitis_durumu"] = a[2]
        if a[2] == "zorla_kapatildi":
            d["zorla_kapatilan"] = a[3:]
        yaz(a[1], d)
        return 0
    if len(a) == 2 and a[0] == "surecler":
        for s in oku(a[1])["surecler"]:
            print(s["ad"], s["pid"], s["grup"])
        return 0
    if len(a) == 3 and a[0] == "durum-alani":
        v = oku(a[1]).get(a[2])
        print("" if v is None else v)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
