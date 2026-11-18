"""Yer istasyonu izleme mantığı (saf; birim testli): ortak durum konusundan üç aracın görev durumunu izler (FR-2: her araç durumunu 2 Hz yayımlar; yer istasyonu aynı durumu gösterir).

Kayıt seçimi: 2 Hz'lik her ileti diske YAZILMAZ (üç araç × 2 Hz × ~300 sn ≈ 1800 satır, bilgi içermeyen tekrar); durum DEĞİŞİMİ (durum adı) ve görev ilerlemesi değişimi yazılır,
ayrıca `IZLEME_OZET_SN` aralığıyla tüm araçların son durumu özet satırı olarak yazılır. Bayat durum: bir araçtan `IZLEME_BAYAT_SN` boyunca durum gelmezse tek bir uyarı (her bayatlık dönemi için bir kez);
ilk durum gelmeden uyarı verilmez (araç Mission'ı bekler/HAZIR'a hazırlanır, bu sırada yayım yoktur). Uyarı yalnız kayıttır: deney akışını (bariyer, COMPLETE) değiştirmez.
"""
AD = {1: "HAZIR", 2: "BARIYER_BEKLE", 3: "TARAMA", 4: "WAIT", 5: "TAMAMLANDI"}
_NS = 10 ** 9


class DurumIzleyici:
    def __init__(self, arac_kimlikleri, bayat_sn, ozet_sn):
        self.arac_kimlikleri = [int(a) for a in arac_kimlikleri]
        self.bayat_ns, self.ozet_ns = int(float(bayat_sn) * _NS), int(float(ozet_sn) * _NS)
        self.son = {}            # araç → dict(durum, ilerleme, son_kare, mono_ns)
        self.bayat = set()       # şu an bayat olan araçlar
        self.bayat_sayisi = {a: 0 for a in self.arac_kimlikleri}
        self._son_ozet = None

    def durum_geldi(self, arac, durum, ilerleme, son_kare, mono_ns):
        """Dönen: olay listesi (durum_degisti / bayat_bitti)."""
        arac = int(arac)
        if arac not in self.arac_kimlikleri:
            return []
        olaylar = []
        onceki = self.son.get(arac)
        ad = AD.get(int(durum), f"BILINMEYEN_{int(durum)}")
        if arac in self.bayat:
            self.bayat.discard(arac)
            olaylar.append({"olay": "bayat_bitti", "arac_kimligi": arac})
        if onceki is None or onceki["durum"] != ad or onceki["ilerleme"] != tuple(ilerleme):
            olaylar.append({"olay": "durum_degisti", "arac_kimligi": arac, "onceki": None if onceki is None else onceki["durum"], "durum": ad,
                            "ilerleme": list(ilerleme), "son_kare": int(son_kare)})
        self.son[arac] = {"durum": ad, "ilerleme": tuple(ilerleme), "son_kare": int(son_kare), "mono_ns": int(mono_ns)}
        return olaylar

    def kontrol(self, mono_ns, yalniz_ozet=False):
        """Periyodik: bayat uyarıları ve (aralık dolduysa) özet. yalnız_ozet: bayat denetimi yapmadan özeti hemen ver (kapanışta son özet). Dönen: olay listesi (bayat_uyari / ozet)."""
        olaylar = []
        for a in ([] if yalniz_ozet else self.arac_kimlikleri):
            s = self.son.get(a)
            if s is not None and a not in self.bayat and mono_ns - s["mono_ns"] > self.bayat_ns:
                self.bayat.add(a)
                self.bayat_sayisi[a] += 1
                olaylar.append({"olay": "bayat_uyari", "arac_kimligi": a, "sessiz_sn": round((mono_ns - s["mono_ns"]) / _NS, 1), "son_durum": s["durum"]})
        if yalniz_ozet or self._son_ozet is None or mono_ns - self._son_ozet >= self.ozet_ns:
            if self.son:
                self._son_ozet = mono_ns
                olaylar.append({"olay": "ozet", "araclar": {str(a): {"durum": s["durum"], "ilerleme": list(s["ilerleme"]), "son_kare": s["son_kare"],
                                                                   "yas_sn": round((mono_ns - s["mono_ns"]) / _NS, 1)} for a, s in sorted(self.son.items())}})
        return olaylar

    @staticmethod
    def satir(o):
        """Konsol/günlük için kısa durum satırı (araç, durum, görev ilerlemesi, son kare numarası)."""
        if o["olay"] == "durum_degisti":
            return f"araç {o['arac_kimligi']}: {o['durum']} (görev {o['ilerleme'][0]}/{o['ilerleme'][1]}, son kare {o['son_kare']})"
        if o["olay"] == "bayat_uyari":
            return f"UYARI araç {o['arac_kimligi']}: {o['sessiz_sn']} sn durum gelmedi (son durum {o['son_durum']})"
        if o["olay"] == "bayat_bitti":
            return f"araç {o['arac_kimligi']}: durum yeniden geliyor"
        return "özet: " + ", ".join(f"{a}={v['durum']}" for a, v in o["araclar"].items())
