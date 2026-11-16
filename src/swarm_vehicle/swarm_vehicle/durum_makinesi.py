"""Araç görev durum makinesi (GŞÖA 7.4): HAZIR → BARIYER_BEKLE → TARAMA → WAIT → TAMAMLANDI.

Saf mantıktır: ROS 2 ve MAVSDK içe aktarılmaz (birim testi için). Durum değerleri swarm_msgs/VehicleState.STATE_* ile aynıdır.
Zaman değerleri simülasyon saatinin tam sayı nanosaniyesidir (ondalık saniye yuvarlama hatası yapmasın diye).
Belgede olmayan durum ya da geçiş YOKTUR (hata durumu, yeniden bölgeleme, görev devralma yok). Geçersiz olay yok sayılır ve günlüğe yazılır.
"""

STATE_UNKNOWN = 0
STATE_HAZIR = 1
STATE_BARIYER_BEKLE = 2
STATE_TARAMA = 3
STATE_WAIT = 4
STATE_TAMAMLANDI = 5

AD = {STATE_HAZIR: "HAZIR", STATE_BARIYER_BEKLE: "BARIYER_BEKLE", STATE_TARAMA: "TARAMA", STATE_WAIT: "WAIT", STATE_TAMAMLANDI: "TAMAMLANDI"}

_NS = 10 ** 9


HZ_ONTANIMLI = 2     # yalnız birim testleri için kolaylık; araç süreci CAM_RATE_HZ'yi (config/deney.env) açıkça geçirir


def hz_dogrula(hz):
    """Kare hızı pozitif tam sayı olmalı (ızgara kuralı); tam sayı olmayan değer sessizce kesilmez, ValueError verilir. Dönen: int."""
    try:
        sayi = float(hz)
    except (TypeError, ValueError):
        raise ValueError(f"kare hızı sayı olmalı: {hz!r}") from None
    if sayi <= 0 or sayi != int(sayi):
        raise ValueError(f"kare hızı pozitif tam sayı olmalı: {hz!r}")
    return int(sayi)


def kare_araligi(t_s_ns, t_b_ns, hz=HZ_ONTANIMLI):
    """Izgara yolu kare aralığı (n = hz·t_sim): n_ilk = ceil(hz·t_s), n_son = floor(hz·t_b). Tam sayı aritmetiğiyle (buçuk saniye sınırları kesin). hz: kare hızı (CAM_RATE_HZ, tam sayı)."""
    hz = hz_dogrula(hz)
    return -((-hz * t_s_ns) // _NS), (hz * t_b_ns) // _NS


class DurumMakinesi:
    def __init__(self, gunluk=None, beklenen_mission_id=None, hz=HZ_ONTANIMLI):
        """gunluk: gunluk(metin) çağrılabilir (öntanımlı: yalnız `olaylar` listesine yazar). beklenen_mission_id: bilinen bir görev kimliği varsa,
        farklı kimlikli tarama başlatma yok sayılır (öntanımlı None: ilk geçerli tarama başlatma kimliği belirler). hz: kare hızı (kare aralığı için)."""
        self.hz = hz_dogrula(hz)
        self.durum = STATE_HAZIR
        self.mission_id = None
        self.beklenen_mission_id = beklenen_mission_id
        self.t_s_ns = None
        self.t_b_ns = None
        self.olaylar = []
        self._gunluk = gunluk

    def _kayit(self, metin):
        self.olaylar.append(metin)
        if self._gunluk is not None:
            self._gunluk(metin)

    def _gecis(self, yeni, neden):
        self._kayit(f"gecis {AD[self.durum]} -> {AD[yeni]}: {neden}")
        self.durum = yeni
        return True

    def _yok_say(self, olay, neden):
        self._kayit(f"yok_sayildi {olay} (durum {AD[self.durum]}): {neden}")
        return False

    def hazir(self):
        """Araç başlangıç konumunda hazır (hazırlık bitti): HAZIR → BARIYER_BEKLE. Bu geçişin yayımı hazır bildirimidir."""
        if self.durum != STATE_HAZIR:
            return self._yok_say("hazir", "yalnız HAZIR durumunda geçerli")
        return self._gecis(STATE_BARIYER_BEKLE, "başlangıç konumunda hazır")

    def tarama_baslat(self, mission_id, t_s_ns):
        """Tarama başlatma mesajı alındı (t_s: alındığı simülasyon saati, ns): yalnız BARIYER_BEKLE'de geçerli → TARAMA."""
        if self.durum != STATE_BARIYER_BEKLE:
            return self._yok_say("tarama_baslat", f"yalnız BARIYER_BEKLE durumunda geçerli (mission_id={mission_id!r})")
        if not mission_id:
            return self._yok_say("tarama_baslat", "boş mission_id")
        if self.beklenen_mission_id is not None and mission_id != self.beklenen_mission_id:
            return self._yok_say("tarama_baslat", f"mission_id eşleşmiyor (alınan {mission_id!r}, beklenen {self.beklenen_mission_id!r})")
        self.mission_id = mission_id
        self.t_s_ns = int(t_s_ns)
        return self._gecis(STATE_TARAMA, f"tarama başlatma alındı (mission_id={mission_id!r}, t_s={self.t_s_ns} ns)")

    def son_nokta(self, t_b_ns):
        """Rotanın son noktasına ulaşıldı: yalnız TARAMA'da ve bir kez → WAIT."""
        if self.durum != STATE_TARAMA:
            return self._yok_say("son_nokta", "yalnız TARAMA durumunda geçerli")
        self.t_b_ns = int(t_b_ns)
        return self._gecis(STATE_WAIT, f"son nokta (t_b={self.t_b_ns} ns)")

    def complete(self, mission_id):
        """Ortak COMPLETE: yalnız WAIT'te ve görev kimliği eşleşirse → TAMAMLANDI."""
        if self.durum != STATE_WAIT:
            return self._yok_say("complete", f"yalnız WAIT durumunda geçerli (mission_id={mission_id!r})")
        if mission_id != self.mission_id:
            return self._yok_say("complete", f"mission_id eşleşmiyor (alınan {mission_id!r}, görev {self.mission_id!r})")
        return self._gecis(STATE_TAMAMLANDI, f"ortak COMPLETE alındı (mission_id={mission_id!r})")

    def kare_araligi(self):
        """(n_ilk, n_son); t_s ve t_b bilinmiyorsa None."""
        if self.t_s_ns is None or self.t_b_ns is None:
            return None
        return kare_araligi(self.t_s_ns, self.t_b_ns, self.hz)
