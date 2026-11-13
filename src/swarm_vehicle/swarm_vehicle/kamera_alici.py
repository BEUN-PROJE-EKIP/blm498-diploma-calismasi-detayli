"""Kamera alıcısının saf mantığı (B8, FR-9..FR-11): kare numaralandırma, görev karesi kabulü, "kare alınamadı" ve "geç geldi" kuralları.
ROS 2, MAVSDK ve gz-transport içe aktarılmaz (birim testi için). El kitabı ("görev girdisi olarak kabul" paragrafı):
- Kare numarası kaynakta, simülasyon damgasından n = hz · t_sim ile (ızgara yolu) türetilir. Damga ızgaraya (1/hz s) tam oturmuyorsa numara TÜRETİLMEZ ("ızgara dışı"; yuvarlama yok);
  ızgara dışı kare görev karesi sayılmaz (K9).
- Tarama başlatma mesajı alındığındaki simülasyon saati t_s: n_ilk = ceil(hz·t_s). Tarama bitişinin simülasyon zamanı t_b: n_son = floor(hz·t_b). Damgası t_s'ye ya da t_b'ye
  eşit olan kare görev karesidir. Beklenen görev kareleri [n_ilk, n_son] aralığındaki bütün numaralardır (uçlar dahil).
- Alıcı, aralıkta numarası daha büyük bir kare aldığında alınmamış her numara için bir "kare alınamadı" kaydı üretir. Sondaki kayıplar, n_son'dan büyük ilk karenin gelmesiyle
  kapanır; bu kare görev girdisi sayılmaz.
- Kayıp kaydı KESİNDİR: kayıttan sonra aynı numarayla gelen kare işlenmez (iç kuyruğa verilmez, ağa gönderilmez), yalnız yerel kayda "geç geldi" olarak yazılır.
Yedek yol (alıcı numarası k) K9 kararıyla uygulanmaz; seçilirse açık hata verilir.
Kayıtlar planlama/sozlesmeler.md §8.3 `kare_olay` şemasındadır; kaynak "kamera_alicisi". Zamanlar tam sayı ns (CLOCK_MONOTONIC / simülasyon).
Alıcının yerel kayıt türleri: olay `kuyruga_giris` (görev karesi iç kuyruğa verildi), olay `kullanilabilir` + sonuc_durumu `kare_alinamadi` (kayıp kaydı üretildi),
olay `gec_geldi` (kayıp kaydından sonra gelen kare; yalnız yerel), olay `yok_sayildi` + neden (görev girdisi değil: gorev_oncesi | kapanis_sonrasi | izgara_disi | tekrar).
"""

_NS = 10 ** 9
KAYNAK = "kamera_alicisi"


class YedekYolHatasi(RuntimeError):
    """Yedek yol (alıcı numarası k) K9 kararıyla uygulanmaz."""


def kipi_dogrula(kip):
    if kip != "izgara":
        raise YedekYolHatasi(f"kare numaralandırma kipi '{kip}' desteklenmiyor: yalnız 'izgara' (yedek yol K9 kararıyla uygulanmaz)")


def n_hesapla(damga_ns, hz):
    """Izgara numarası: damga hz·t_sim'e tam oturuyorsa n, oturmuyorsa None (yuvarlama yok)."""
    if (damga_ns * hz) % _NS != 0:
        return None
    return damga_ns * hz // _NS


def n_ilk_hesapla(t_s_ns, hz):
    return -((-hz * t_s_ns) // _NS)         # ceil(hz·t_s)


def n_son_hesapla(t_b_ns, hz):
    return (hz * t_b_ns) // _NS             # floor(hz·t_b)


class KameraAlici:
    def __init__(self, arac_kimligi, hz, olay_yaz=None, kuyruga_ver=None, kip="izgara"):
        """olay_yaz(sözlük): her `kare_olay` kaydı için; kuyruga_ver(n, damga_ns, mono_ns): kabul edilen görev karesi için (kareyi tutmaz)."""
        kipi_dogrula(kip)
        if hz != int(hz) or hz <= 0:
            raise ValueError("CAM_RATE_HZ pozitif tam sayı olmalı (ızgara kuralı)")
        self.arac_kimligi, self.hz = int(arac_kimligi), int(hz)
        self._yaz, self._kuyruk = olay_yaz, kuyruga_ver
        self.n_ilk = None
        self.n_son = None
        self.kapali = False
        self.sonraki = None                  # sıradaki beklenen görev numarası
        self.gorulen = set()                 # görev karesi olarak kabul edilen numaralar
        self.alinamadi = set()               # "kare alınamadı" kaydı yazılmış numaralar
        self.son_gorev_numarasi = -1
        self.sayac = {"gorev": 0, "kare_alinamadi": 0, "gec_geldi": 0, "gorev_oncesi": 0, "kapanis_sonrasi": 0, "izgara_disi": 0, "tekrar": 0, "gorev_siniri_asildi": 0}

    # --- kayıt ---------------------------------------------------------------------------------------------------------------------------
    def _kayit(self, n, damga_ns, olay, mono_ns, **ek):
        if self._yaz is not None:
            d = {"surum": 1, "tur": "kare_olay", "kaynak": KAYNAK, "arac_kimligi": self.arac_kimligi, "n": "izgara_disi" if n is None else n,
                 "sim_damga_ns": damga_ns, "olay": olay, "mono_ns": mono_ns}
            d.update(ek)
            self._yaz(d)

    def _yoksay(self, n, damga_ns, mono_ns, neden):
        self.sayac[neden] += 1
        self._kayit(n, damga_ns, "yok_sayildi", mono_ns, neden=neden)

    def _kare_alinamadi(self, n, mono_ns):
        self.alinamadi.add(n)
        self.sayac["kare_alinamadi"] += 1
        self._kayit(n, n * _NS // self.hz, "kullanilabilir", mono_ns, sonuc_durumu="kare_alinamadi")

    # --- olaylar -------------------------------------------------------------------------------------------------------------------------
    def tarama_basladi(self, t_s_ns):
        """Tarama başlatma mesajı alındı (t_s: o anki simülasyon saati, ns). Yalnız ilk çağrı geçerlidir."""
        if self.n_ilk is not None:
            return False
        self.n_ilk = n_ilk_hesapla(t_s_ns, self.hz)
        self.sonraki = self.n_ilk
        return True

    def tarama_bitti(self, t_b_ns):
        """Rotanın son noktasına ulaşıldı (t_b: o anki simülasyon saati, ns): yeni görev karesi kabulü durur; n_son belirlenir. Dönen: n_son."""
        if self.n_ilk is None or self.n_son is not None:
            return self.n_son
        self.n_son = n_son_hesapla(t_b_ns, self.hz)
        asan = [n for n in self.gorulen if n > self.n_son]
        if asan:   # önlem: n_son bilinmeden kabul edilmiş, damgası t_b'den büyük kare (beklenmez; sayılır)
            self.sayac["gorev_siniri_asildi"] += len(asan)
        return self.n_son

    def kare(self, damga_ns, mono_ns):
        """Bir kamera karesi alındı (damga: header.stamp ns; mono: alım anı, CLOCK_MONOTONIC ns). Dönen: görev karesi olarak iç kuyruğa verildiyse numara, aksi halde None."""
        n = n_hesapla(damga_ns, self.hz)
        if n is None:
            self._yoksay(None, damga_ns, mono_ns, "izgara_disi")
            return None
        if self.n_ilk is None or n < self.n_ilk:
            self._yoksay(n, damga_ns, mono_ns, "gorev_oncesi")
            return None
        if n in self.alinamadi:
            self.sayac["gec_geldi"] += 1
            self._kayit(n, damga_ns, "gec_geldi", mono_ns)       # kayıp kaydı kesindir: işlenmez, yalnız yerel kayıt
            return None
        if n in self.gorulen:
            self._yoksay(n, damga_ns, mono_ns, "tekrar")
            return None
        if self.n_son is not None and n > self.n_son:
            if not self.kapali:                                  # sondaki kayıplar n_son'dan büyük ilk kareyle kapanır
                self.kapali = True
                for m in range(self.sonraki, self.n_son + 1):
                    self._kare_alinamadi(m, mono_ns)
                self.sonraki = self.n_son + 1
            self._yoksay(n, damga_ns, mono_ns, "kapanis_sonrasi")
            return None
        for m in range(self.sonraki, n):                         # aradaki alınmamış her numara için "kare alınamadı"
            self._kare_alinamadi(m, mono_ns)
        self.sonraki = n + 1
        self.gorulen.add(n)
        self.son_gorev_numarasi = n
        self.sayac["gorev"] += 1
        self._kayit(n, damga_ns, "kuyruga_giris", mono_ns)
        if self._kuyruk is not None:
            self._kuyruk(n, damga_ns, mono_ns)
        return n


# --- hata enjeksiyonu (YALNIZ test; varsayılan kapalı) ----------------------------------------------------------------------------------------
class Enjeksiyon:
    """Ortam değişkeni KAMERA_ENJEKSIYON: `bekle=<sn>;dusur=<belirteç,...>;gecik=<belirteç,...>`; belirteç: `+k` (n_ilk + k), `son` (n_son) ya da mutlak numara.
    dusur: o numaralı kare alıcıya HİÇ verilmez. gecik: o numaralı kare, onun için "kare alınamadı" kaydı yazılana dek tutulur, sonra teslim edilir (→ "geç geldi").
    bekle: her kare alıcıya bu kadar saniye gecikmeli verilir (sondaki kareyi n_son bilindikten sonra düşürebilmek için; 0 = gecikme yok)."""

    def __init__(self, metin=""):
        self.bekle_sn, self.dusur, self.gecik = 0.0, [], []
        for parca in [p for p in (metin or "").split(";") if p.strip()]:
            anahtar, _, deger = parca.partition("=")
            anahtar = anahtar.strip()
            if anahtar == "bekle":
                self.bekle_sn = float(deger)
            elif anahtar in ("dusur", "gecik"):
                getattr(self, anahtar).extend(t.strip() for t in deger.split(",") if t.strip())
            else:
                raise ValueError(f"KAMERA_ENJEKSIYON: bilinmeyen anahtar '{anahtar}'")

    @property
    def acik(self):
        return bool(self.bekle_sn or self.dusur or self.gecik)

    @staticmethod
    def _coz(belirtec, alici):
        if belirtec == "son":
            return alici.n_son
        if belirtec.startswith("+"):
            return None if alici.n_ilk is None else alici.n_ilk + int(belirtec[1:])
        return int(belirtec)

    def dusur_mu(self, n, alici):
        return any(self._coz(t, alici) == n for t in self.dusur)

    def gecik_mi(self, n, alici):
        return any(self._coz(t, alici) == n for t in self.gecik)

    def ozet(self):
        return f"bekle={self.bekle_sn:g};dusur={','.join(self.dusur)};gecik={','.join(self.gecik)}" if self.acik else "kapali"
