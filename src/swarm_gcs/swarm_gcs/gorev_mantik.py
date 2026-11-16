"""Görev koordinatörünün saf mantığı (rclpy'siz; birim testli): bariyer, t0, tarama bitişleri, kare koşulu, t1 ve bitiş kararı (FR-3, FR-4, FR-5 [birleştirme hariç]).

Akış (GŞÖA 7.4, 7.5; el kitabı "Haberleşme Mimarisi"): faz `hazir_bekle` → N aracın BARIYER_BEKLE bildirimi VE kare sonucu konusunda N yayımcıyla eşleşme → `scan_start` eylemi (t0 = yayımlama anı) →
faz `tarama` → N tarama bitişi VE sonuç defteri tamam (her aracın [n_ilk, n_son] aralığındaki her numara için tam bir sonuç; dört durumdan biri) → `complete` eylemi (t1 = yayımlama anı) → faz `complete_verildi` →
N aracın TAMAMLANDI durumu → `kapat` → faz `bitti`. Zaman aşımı yalnız üst sınırdır (H değil); aşılırsa COMPLETE yayımlanmaz, faz `hata`.
Erken, yinelenen, yanlış kimlikli ve bilinmeyen araçlı olaylar sayılır ve `yok_sayildi` olayıyla dışarı bildirilir; hiçbiri akışı değiştirmez. Yedek yol (NUMBERING_FALLBACK) açık hatadır (M3/B13).
Her yöntem, dışarıda kaydedilecek olay sözlüklerinin listesini döndürür (`olay`, `arac_kimligi`, ... anahtarlarıyla).
"""

STATE_BARIYER_BEKLE = 2
STATE_TAMAMLANDI = 5

FAZ_HAZIR_BEKLE, FAZ_TARAMA, FAZ_COMPLETE_VERILDI, FAZ_BITTI, FAZ_HATA = "hazir_bekle", "tarama", "complete_verildi", "bitti", "hata"


class Koordinasyon:
    def __init__(self, arac_kimlikleri, mission_id):
        self.arac_kimlikleri = [int(a) for a in arac_kimlikleri]
        self.mission_id = mission_id
        self.faz = FAZ_HAZIR_BEKLE
        self.hazir = {}                      # araç → ilk BARIYER_BEKLE alım anı (mono_ns)
        self.bitis = {}                      # araç → (n_ilk, n_son, mono_ns)
        self.tamamlandi = {}                 # araç → TAMAMLANDI alım anı (yalnız COMPLETE'ten sonra sayılır)
        self.eslesen = 0
        self.sonuclar_tamam = False
        self.hata_nedeni = None
        self.t0 = self.t1 = None             # (mono_ns, sim_ns)
        self.yok_sayilan = []                # (neden, ayrıntı)

    # --- olaylar --------------------------------------------------------------------------------------------------------------------------
    def _yok(self, neden, arac_kimligi=None, **ayrinti):
        self.yok_sayilan.append((neden, arac_kimligi, ayrinti))
        o = {"olay": "yok_sayildi", "neden": neden}
        if arac_kimligi is not None:
            o["arac_kimligi"] = arac_kimligi
        if ayrinti:
            o["ayrinti"] = " ".join(f"{k}={v}" for k, v in ayrinti.items())
        return [o]

    def durum_geldi(self, arac, durum, mono_ns):
        """VehicleState alındı (durum: STATE_* tam sayısı)."""
        arac = int(arac)
        if arac not in self.arac_kimlikleri:
            return self._yok("bilinmeyen_arac", arac_kimligi=arac)
        if durum == STATE_BARIYER_BEKLE and arac not in self.hazir and self.faz == FAZ_HAZIR_BEKLE:
            self.hazir[arac] = int(mono_ns)
            return [{"olay": "hazir", "arac_kimligi": arac}]
        if durum == STATE_TAMAMLANDI and self.faz == FAZ_COMPLETE_VERILDI and arac not in self.tamamlandi:
            self.tamamlandi[arac] = int(mono_ns)
            return [{"olay": "tamamlandi", "arac_kimligi": arac}]
        return []

    def eslesme_guncelle(self, sayi):
        """Eşleşen sayısı (uçta mod: kare sonucu konusunda eşleşmiş yayımcı; merkezi mod: kanalı bağlı ve işçisi hazır araç); değişirse (artış ya da azalış) `eslesme` olayı döner."""
        sayi = int(sayi)
        if sayi == self.eslesen:
            return []
        self.eslesen = sayi
        return [{"olay": "eslesme", "yayimci": sayi}]

    def bitis_geldi(self, arac, mission_id, izgara_yolu, n_ilk, n_son, mono_ns):
        """ScanFinished alındı. Yedek yol açık hatadır; yanlış görev kimliği, bilinmeyen araç ve ikinci bildirim yok sayılır."""
        arac = int(arac)
        if arac not in self.arac_kimlikleri:
            return self._yok("bilinmeyen_arac", arac_kimligi=arac)
        if mission_id != self.mission_id:
            return self._yok("mission_id_uyusmuyor", arac_kimligi=arac, alinan=mission_id)
        if self.faz != FAZ_TARAMA:
            return self._yok("tarama_fazinda_degil", arac_kimligi=arac, faz=self.faz)
        if not izgara_yolu:
            self.faz, self.hata_nedeni = FAZ_HATA, "kare numaralandırmanın yedek yolu (NUMBERING_FALLBACK) bu sürümde desteklenmez (M3/B13)"
            return [{"olay": "hata", "neden": "yedek_yol_desteklenmiyor", "arac_kimligi": arac, "ayrinti": self.hata_nedeni}]
        if arac in self.bitis:
            return self._yok("tekrar_bitis", arac_kimligi=arac)
        self.bitis[arac] = (int(n_ilk), int(n_son), int(mono_ns))
        return [{"olay": "tarama_bitisi", "arac_kimligi": arac, "n_ilk": int(n_ilk), "n_son": int(n_son)}]

    def sonuclar_guncelle(self, tamam):
        """Sonuç defteri hepsi_tamam durumu (kare koşulu)."""
        self.sonuclar_tamam = bool(tamam)

    # --- karar -----------------------------------------------------------------------------------------------------------------------------
    def hepsi_hazir(self):
        return all(a in self.hazir for a in self.arac_kimlikleri)

    def hepsi_bitirdi(self):
        return all(a in self.bitis for a in self.arac_kimlikleri)

    def sonraki(self):
        """Yapılması gereken eylem: 'scan_start' | 'complete' | 'kapat' | None."""
        if self.faz == FAZ_HAZIR_BEKLE and self.hepsi_hazir() and self.eslesen >= len(self.arac_kimlikleri):
            return "scan_start"
        if self.faz == FAZ_TARAMA and self.hepsi_bitirdi() and self.sonuclar_tamam:
            return "complete"
        if self.faz == FAZ_COMPLETE_VERILDI and all(a in self.tamamlandi for a in self.arac_kimlikleri):
            return "kapat"
        return None

    def scan_start_yapildi(self, mono_ns, sim_ns):
        assert self.faz == FAZ_HAZIR_BEKLE
        self.faz, self.t0 = FAZ_TARAMA, (int(mono_ns), sim_ns)

    def complete_yapildi(self, mono_ns, sim_ns):
        assert self.faz == FAZ_TARAMA
        self.faz, self.t1 = FAZ_COMPLETE_VERILDI, (int(mono_ns), sim_ns)

    def kapatildi(self):
        self.faz = FAZ_BITTI

    def zaman_asimi(self):
        """Üst süre doldu: COMPLETE yayımlanmaz (faz hata). Dönen: neden metni."""
        if self.faz in (FAZ_BITTI, FAZ_HATA):
            return self.hata_nedeni
        bekleyen = {FAZ_HAZIR_BEKLE: f"hazır bildirimi {sorted(set(self.arac_kimlikleri) - set(self.hazir))}, eşleşen yayımcı {self.eslesen}/{len(self.arac_kimlikleri)}",
                    FAZ_TARAMA: f"tarama bitişi {sorted(set(self.arac_kimlikleri) - set(self.bitis))}, kare sonuçları tamam={self.sonuclar_tamam}",
                    FAZ_COMPLETE_VERILDI: f"TAMAMLANDI {sorted(set(self.arac_kimlikleri) - set(self.tamamlandi))}"}[self.faz]
        self.faz, self.hata_nedeni = FAZ_HATA, f"üst süre doldu; bekleyen: {bekleyen}"
        return self.hata_nedeni
