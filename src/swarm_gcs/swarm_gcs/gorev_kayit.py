"""Görev olay kaydı yazıcısı (`kayit/yer_istasyonu_gorev.jsonl`, `tur: "gorev_olay"`, planlama/sozlesmeler.md §8.9): olay adı ve zorunlu alanlar yazmadan önce denetlenir; mono_ns geriye gitmez
(yazıcı kendi kilidi altında artan zaman verir). `sim_ns` bilinmiyorsa null. Hiçbir kaydın yazılmaması (yol yoksa) hata değildir (birim test)."""
import json
import threading
import time

OLAYLAR = ("gorev_atandi", "hazir", "eslesme", "t0", "tarama_bitisi", "son_sonuc", "t1", "tamamlandi", "zaman_asimi", "birlestirme_tamam", "yok_sayildi", "hata")
IZINLI = ("arac_kimligi", "mission_id", "n_ilk", "n_son", "t_s_ns", "t_b_ns", "yayimci", "t1_eksi_son_bitis_ns", "rapor_sayisi", "konumsuz_rapor_sayisi", "girdi_tespit_sayisi", "sure_ms", "neden", "ayrinti")


class GorevKaydi:
    def __init__(self, yol):
        self.yol, self._k, self._son_mono = yol, threading.Lock(), 0
        self.satirlar = []                       # bellekteki kopya (test/rapor)

    def yaz(self, olay, sim_ns=None, mono_ns=None, **kv):
        if olay not in OLAYLAR:
            raise ValueError(f"bilinmeyen görev olayı: {olay!r}")
        for k in kv:
            if k not in IZINLI:
                raise ValueError(f"görev olayında izinsiz alan: {k!r}")
        with self._k:
            mono = int(mono_ns) if mono_ns is not None else time.monotonic_ns()
            mono = max(mono, self._son_mono)     # kayıt sırası monotonik kalır
            self._son_mono = mono
            d = {"surum": 1, "tur": "gorev_olay", "olay": olay, "mono_ns": mono, "sim_ns": None if sim_ns is None else int(sim_ns), **kv}
            self.satirlar.append(d)
            if self.yol:
                with open(self.yol, "a", encoding="utf-8") as f:
                    f.write(json.dumps(d, ensure_ascii=False) + "\n")
        return d
