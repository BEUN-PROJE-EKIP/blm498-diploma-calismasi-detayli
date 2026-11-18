"""Merkezi mod görüntü iletisi (FR-14, FR-15): araç başına TCP kanalında akan iletinin kodlanması ve akıştan çözülmesi. Yalnız standart kitaplık (rclpy/MAVSDK/gz içe aktarılmaz).

[belge] Her görüntü iletisinde: ileti türü, araç kimliği, kare numarası, karenin simülasyon zaman damgası, yük uzunluğu, görüntü baytları, kamera kalibrasyon kimliği ve kare üretim anına eşlenmiş
canlı PX4 konum/yönelim tahmini. "Kare alınamadı" iletisi aynı alanları taşır, yük uzunluğu 0'dır ve görüntü baytı taşımaz. Üretimin monotonik zamanı iletide TAŞINMAZ.
[varsayım] Kodlama (belge yalnız alanları söyler): ağ sırası olmayan, sabit uzunluklu küçük-endian başlık + değişken uzunluklu kalibrasyon kimliği + sabit uzunluklu poz bloğu + yük.

  bölüm 1 (33 bayt)  `<4sBBBIqqIH`: sihirli değer `SWGI`, sürüm (1), tür (1 görüntü | 2 kare alınamadı), numaralandırma kipi (1 ızgara), araç kimliği (u32), kare numarası (i64),
                     sim damgası (i64, ns), yük uzunluğu (u32), kalibrasyon kimliği uzunluğu (u16)
  bölüm 2            kalibrasyon kimliği (UTF-8, uzunluk bölüm 1'de)
  bölüm 3 (74 bayt)  `<BB3d4dqq`: poz geçerli (0/1), poz neden kodu (0 yok | 1 aralik_asildi | 2 tampon_disi | 3 bekleme_asildi), konum NED (3 × f64), kuaterniyon wxyz (4 × f64),
                     t1 ns (i64; yoksa −1), t2 ns (i64; yoksa −1). Poz geçersizse konum/kuaterniyon sıfırdır ve çözücü bunları döndürmez.
  bölüm 4            yük (tam `yük uzunluğu` bayt; görüntü iletisinde Gazebo'dan gelen RGB8 baytları değiştirilmeden)
"""
import math
import struct

SIHIR = b"SWGI"
SURUM = 1
TUR_GORUNTU, TUR_KARE_ALINAMADI = 1, 2
KIP_IZGARA = 1
NEDEN_KODU = {None: 0, "aralik_asildi": 1, "tampon_disi": 2, "bekleme_asildi": 3}
KOD_NEDEN = {v: k for k, v in NEDEN_KODU.items()}

_B1 = struct.Struct("<4sBBBIqqIH")
_B3 = struct.Struct("<BB3d4dqq")
B1_BOYUT, B3_BOYUT = _B1.size, _B3.size
KALIBRASYON_MAKS = 256


class IletiHatasi(ValueError):
    """Bozuk ileti: sihirli değer/sürüm/tür/kip/uzunluk uyuşmazlığı. Alıcı bunu açık hata sayar (sessiz değil)."""


class Poz:
    """İletideki poz: `gecerli` False ise `neden` doludur ve konum/q None'dır."""
    __slots__ = ("gecerli", "neden", "konum", "q", "t1_ns", "t2_ns")

    def __init__(self, gecerli, neden=None, konum=None, q=None, t1_ns=None, t2_ns=None):
        self.gecerli, self.neden, self.konum, self.q, self.t1_ns, self.t2_ns = bool(gecerli), neden, konum, q, t1_ns, t2_ns

    def __eq__(self, d):
        return isinstance(d, Poz) and (self.gecerli, self.neden, self.konum, self.q, self.t1_ns, self.t2_ns) == (d.gecerli, d.neden, d.konum, d.q, d.t1_ns, d.t2_ns)

    def __repr__(self):
        return f"Poz(gecerli={self.gecerli}, neden={self.neden}, konum={self.konum}, q={self.q}, t1={self.t1_ns}, t2={self.t2_ns})"

    @classmethod
    def sonuctan(cls, s):
        """`poz_tamponu.PozSonuc` → Poz."""
        return cls(s.gecerli, s.neden, tuple(s.konum) if s.konum is not None else None, tuple(s.q) if s.q is not None else None, s.t1_ns, s.t2_ns)

    def sozluk(self):
        """Kayıt için sözlük (`kare_poz` kaydındaki alan adlarıyla)."""
        ar = None if self.t1_ns is None or self.t2_ns is None else (self.t2_ns - self.t1_ns) / 1e6
        return {"gecerli": self.gecerli, "neden": self.neden, "t1_ns": self.t1_ns, "t2_ns": self.t2_ns, "aralik_ms": ar,
                "konum_ned_m": list(self.konum) if self.konum is not None else None, "q_wxyz": list(self.q) if self.q is not None else None}


class Ileti:
    __slots__ = ("tur", "arac_kimligi", "kip", "n", "damga_ns", "kalibrasyon_kimligi", "poz", "yuk")

    def __init__(self, tur, arac_kimligi, n, damga_ns, kalibrasyon_kimligi, poz, yuk=b"", kip=KIP_IZGARA):
        self.tur, self.arac_kimligi, self.kip, self.n, self.damga_ns = tur, int(arac_kimligi), kip, int(n), int(damga_ns)
        self.kalibrasyon_kimligi, self.poz, self.yuk = kalibrasyon_kimligi, poz, yuk

    @property
    def goruntu_mu(self):
        return self.tur == TUR_GORUNTU


def kodla(ileti):
    """İletiyi baytlara çevirir (tek `bytes`; başlık + yük). Kare alınamadı iletisinde yük boş olmalıdır."""
    if ileti.tur not in (TUR_GORUNTU, TUR_KARE_ALINAMADI):
        raise IletiHatasi(f"bilinmeyen ileti türü: {ileti.tur}")
    yuk = bytes(ileti.yuk)
    if ileti.tur == TUR_KARE_ALINAMADI and yuk:
        raise IletiHatasi("'kare alınamadı' iletisi görüntü baytı taşıyamaz (yük uzunluğu 0 olmalı)")
    kal = (ileti.kalibrasyon_kimligi or "").encode("utf-8")
    if len(kal) > KALIBRASYON_MAKS:
        raise IletiHatasi(f"kalibrasyon kimliği {KALIBRASYON_MAKS} bayttan uzun")
    p = ileti.poz
    if p.neden not in NEDEN_KODU:
        raise IletiHatasi(f"bilinmeyen poz nedeni: {p.neden!r}")
    if p.gecerli:
        konum, q = tuple(p.konum), tuple(p.q)
        if len(konum) != 3 or len(q) != 4 or not all(math.isfinite(v) for v in konum + q):
            raise IletiHatasi("geçerli poz için 3 konum + 4 kuaterniyon sonlu sayı gerekir")
    else:
        konum, q = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)
    b1 = _B1.pack(SIHIR, SURUM, ileti.tur, ileti.kip, ileti.arac_kimligi, ileti.n, ileti.damga_ns, len(yuk), len(kal))
    b3 = _B3.pack(1 if p.gecerli else 0, NEDEN_KODU[p.neden], *konum, *q, -1 if p.t1_ns is None else p.t1_ns, -1 if p.t2_ns is None else p.t2_ns)
    return b"".join((b1, kal, b3, yuk))


def baslik_boyutu(kalibrasyon_kimligi):
    return B1_BOYUT + len((kalibrasyon_kimligi or "").encode("utf-8")) + B3_BOYUT


class AkisCozucu:
    """Bayt akışından ileti çıkarır; veri herhangi bir sınırdan (başlık içinde bile) bölünmüş gelebilir. `besle(bayt)` tamamlanan iletileri liste olarak döndürür.
    Bozuk başlıkta `IletiHatasi` fırlatır ve çözücü kullanılamaz hale gelir (akış senkronu kaybolmuştur; alıcı bağlantıyı açık hata ile kapatır).
    yuk_maks: kabul edilen en büyük yük uzunluğu (bellek koruması). beklenen_arac: verilirse başka araç kimliği açık hatadır."""

    def __init__(self, beklenen_arac=None, yuk_maks=16 * 1024 * 1024):
        self._tampon = bytearray()
        self._beklenen, self._yuk_maks = beklenen_arac, int(yuk_maks)
        self._b1 = None            # çözülmüş bölüm 1 (tuple)
        self.bozuk = None
        self.cozulen = 0
        self.alinan_bayt = 0

    def besle(self, veri):
        if self.bozuk:
            raise IletiHatasi(f"çözücü bozuk akışta durdu: {self.bozuk}")
        self._tampon += veri
        self.alinan_bayt += len(veri)
        cikti = []
        try:
            while True:
                if self._b1 is None:
                    if len(self._tampon) < B1_BOYUT:
                        break
                    sihir, surum, tur, kip, arac, n, damga, yuk_uz, kal_uz = _B1.unpack_from(self._tampon)
                    if sihir != SIHIR:
                        raise IletiHatasi(f"yanlış sihirli değer {bytes(sihir)!r} (beklenen {SIHIR!r})")
                    if surum != SURUM:
                        raise IletiHatasi(f"desteklenmeyen sürüm {surum} (beklenen {SURUM})")
                    if tur not in (TUR_GORUNTU, TUR_KARE_ALINAMADI):
                        raise IletiHatasi(f"bilinmeyen ileti türü {tur}")
                    if kip != KIP_IZGARA:
                        raise IletiHatasi(f"desteklenmeyen numaralandırma kipi {kip}")
                    if self._beklenen is not None and arac != self._beklenen:
                        raise IletiHatasi(f"araç kimliği {arac}; bu kanal için beklenen {self._beklenen}")
                    if kal_uz > KALIBRASYON_MAKS:
                        raise IletiHatasi(f"kalibrasyon kimliği uzunluğu {kal_uz} > {KALIBRASYON_MAKS}")
                    if yuk_uz > self._yuk_maks:
                        raise IletiHatasi(f"yük uzunluğu {yuk_uz} > izin verilen {self._yuk_maks}")
                    if tur == TUR_KARE_ALINAMADI and yuk_uz != 0:
                        raise IletiHatasi(f"'kare alınamadı' iletisinde yük uzunluğu {yuk_uz} (0 olmalı)")
                    if tur == TUR_GORUNTU and yuk_uz == 0:
                        raise IletiHatasi("görüntü iletisinde yük uzunluğu 0")
                    self._b1 = (tur, kip, arac, n, damga, yuk_uz, kal_uz)
                tur, kip, arac, n, damga, yuk_uz, kal_uz = self._b1
                toplam = B1_BOYUT + kal_uz + B3_BOYUT + yuk_uz
                if len(self._tampon) < toplam:
                    break
                kal_son = B1_BOYUT + kal_uz
                try:
                    kal = bytes(self._tampon[B1_BOYUT:kal_son]).decode("utf-8")
                except UnicodeDecodeError as e:
                    raise IletiHatasi(f"kalibrasyon kimliği UTF-8 değil: {e}") from None
                gecerli, neden_kodu, *geri = _B3.unpack_from(self._tampon, kal_son)
                if gecerli not in (0, 1) or neden_kodu not in KOD_NEDEN:
                    raise IletiHatasi(f"poz bayrağı/neden kodu geçersiz ({gecerli}, {neden_kodu})")
                konum, q, t1, t2 = tuple(geri[0:3]), tuple(geri[3:7]), geri[7], geri[8]
                if gecerli:
                    if KOD_NEDEN[neden_kodu] is not None:
                        raise IletiHatasi("geçerli poz neden kodu taşıyamaz")
                    poz = Poz(True, None, konum, q, None if t1 < 0 else t1, None if t2 < 0 else t2)
                else:
                    if KOD_NEDEN[neden_kodu] is None:
                        raise IletiHatasi("geçersiz poz için neden kodu zorunlu")
                    poz = Poz(False, KOD_NEDEN[neden_kodu], None, None, None if t1 < 0 else t1, None if t2 < 0 else t2)
                yuk = bytes(self._tampon[kal_son + B3_BOYUT:toplam])
                del self._tampon[:toplam]
                self._b1 = None
                self.cozulen += 1
                cikti.append(Ileti(tur, arac, n, damga, kal, poz, yuk, kip))
        except IletiHatasi as e:
            self.bozuk = str(e)
            raise
        return cikti

    def bekleyen_bayt(self):
        """Henüz tamamlanmamış iletiye ait tamponlu bayt sayısı (kanal kapanırken > 0 ise yarım ileti var)."""
        return len(self._tampon)
