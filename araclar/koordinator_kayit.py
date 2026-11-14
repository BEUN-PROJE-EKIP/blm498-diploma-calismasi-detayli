"""Koordinatör kaydı okuyucusu (test çözümleme yardımcısı): olağan akışı yürüten ASIL yer istasyonu koordinatörünün görev kaydını (`kayit/yer_istasyonu_gorev.jsonl`, §8.9 + `yer_istasyonu_kare.jsonl`),
deneme koordinatörünün kaydıyla (`koordinator_deneme.jsonl`, serbest biçim) AYNI olay sözlüğü biçimine çevirir; böylece çözümleme betikleri (uc_mod_analiz, alan_pilot_analiz) her iki koşu yolunu okuyabilir.
Deneme koordinatörü kaydı varsa olduğu gibi döner. Asıl koordinatörde olmayan alanlar (Gazebo `poz`, `durum` her ileti) üretilmez."""
import json
import os


def _jsonl(yol):
    if not os.path.isfile(yol):
        return []
    with open(yol, encoding="utf-8") as f:
        return [json.loads(s) for s in f if s.strip()]


def koordinator_olaylari(klasor):
    deneme = os.path.join(klasor, "koordinator_deneme.jsonl")
    if os.path.isfile(deneme):
        return _jsonl(deneme)
    gorev = _jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_gorev.jsonl"))
    yer = _jsonl(os.path.join(klasor, "kayit", "yer_istasyonu_kare.jsonl"))
    cikti = []
    bit = {}
    for x in gorev:
        o = x["olay"]
        if o == "t0":
            cikti.append({"mono_ns": x["mono_ns"], "olay": "t0", "mission_id": x["mission_id"], "sim_ns": x["sim_ns"], "t0_mono_ns": x["mono_ns"]})
        elif o == "tarama_bitisi":
            bit[x["arac_kimligi"]] = (x["n_ilk"], x["n_son"])
            cikti.append({"mono_ns": x["mono_ns"], "olay": "tarama_bitis", "arac": x["arac_kimligi"], "n_first": x["n_ilk"], "n_last": x["n_son"], "sim_ns": x["sim_ns"]})
        elif o == "eslesme":
            cikti.append({"mono_ns": x["mono_ns"], "olay": "eslesme", "yayimci": x["yayimci"], "sim_ns": x["sim_ns"]})
        elif o == "birlestirme_yok":
            cikti.append({"mono_ns": x["mono_ns"], "olay": "birlestirme_yok"})
        elif o == "zaman_asimi":
            cikti.append({"mono_ns": x["mono_ns"], "olay": "zaman_asimi", "beklenen": x.get("neden")})
    esl = [(c["mono_ns"], c["yayimci"]) for c in cikti if c["olay"] == "eslesme"]
    n_arac = len(bit) or max((a for a in {r["arac_kimligi"] for r in yer}), default=0)
    ilk = next((m for m, n in esl if n >= max(n_arac, 1)), None)
    if ilk is not None:
        cikti.append({"mono_ns": ilk, "olay": "eslesme_tamam", "yayimci": max(n for _, n in esl), "anlar": [list(e) for e in esl]})
    son = next((x for x in gorev if x["olay"] == "son_sonuc"), None)
    t1 = next((x for x in gorev if x["olay"] == "t1"), None)
    if son is not None:
        sayilar, tekrar = {}, 0
        for a, (n_ilk, n_son) in bit.items():
            ys = [r for r in yer if r["arac_kimligi"] == a]
            say = {}
            for r in ys:
                say[r["n"]] = say.get(r["n"], 0) + 1
            durumlar = {"tespit": 0, "tespit_yok": 0, "islem_hatasi": 0, "kare_alinamadi": 0}
            for r in ys:
                durumlar[{"sonuc": "tespit"}.get(r["sonuc_durumu"], r["sonuc_durumu"])] += 1
            icinde = [n for n in range(n_ilk, n_son + 1)]
            sayilar[str(a)] = {"beklenen": len(icinde), "gelen": sum(1 for n in icinde if n in say), "eksik": sum(1 for n in icinde if n not in say),
                               "tekrar": sum(v - 1 for v in say.values()), "aralik_disi": sum(1 for n in say if not n_ilk <= n <= n_son), "durumlar": durumlar}
            tekrar += sayilar[str(a)]["tekrar"]
        cikti.append({"mono_ns": son["mono_ns"], "olay": "sonuclar_tamam", "sayilar": sayilar, "gecersiz": 0, "tekrar": tekrar, "bilinmeyen_arac": 0})
    if t1 is not None:
        son_sonuc_mono = max((r["mono_ns"] for r in yer), default=t1["mono_ns"])
        son_bitis = t1["mono_ns"] - t1.get("t1_eksi_son_bitis_ns", 0)
        cikti.append({"mono_ns": t1["mono_ns"], "olay": "t1", "mission_id": t1["mission_id"], "sim_ns": t1["sim_ns"], "t1_mono_ns": t1["mono_ns"], "son_tarama_bitis_mono_ns": son_bitis,
                      "son_sonuc_mono_ns": son_sonuc_mono, "t1_eksi_son_bitis_s": (t1["mono_ns"] - son_bitis) / 1e9, "t1_eksi_son_sonuc_s": (t1["mono_ns"] - son_sonuc_mono) / 1e9})
    if any(x["olay"] == "tamamlandi" for x in gorev):
        cikti.append({"mono_ns": max(x["mono_ns"] for x in gorev if x["olay"] == "tamamlandi"), "olay": "bitti"})
    return sorted(cikti, key=lambda c: c["mono_ns"])
