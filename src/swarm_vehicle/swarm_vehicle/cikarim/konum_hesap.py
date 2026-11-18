"""Konum hesaplayıcı (FR-17, FR-18): görüntü kutusunun merkezinden çıkan ışını, kare üretim anındaki enterpolasyonlu PX4 pozuyla ortak yerel ENU'daki düz zemin düzlemiyle kesiştirir.
Yalnız standart kitaplık (rclpy, MAVSDK ve gz içe aktarılmaz); uçta modda araç süreci, merkezi modda yer istasyonu AYNI kodu kullanır [belge: iki mod aynı kural].

Zincir (tek yerde; her adım bir fonksiyon ya da tek ifade):
  1. kutu merkezi (piksel; orijin sol üst piksel köşesi, x sağa, y aşağı: sozlesmeler.md §4)
  2. normalize ışın, OpenCV kamera çerçevesi: d_kam = ((u − cx)/fx, (v − cy)/fy, 1)
  3. gövde FLU: d_flu = R · d_kam (R kalibrasyon dosyasında, kamera → gövde); kamera konumu t_m gövde FLU çerçevesindedir
  4. gövde FRD: (x, −y, −z)
  5. NED: PX4 kuaterniyonu (wxyz, gövde FRD → NED) ile döndürme; kamera konumu = poz konumu + döndürülmüş t
  6. AÇIK NED → ENU (`ned_den_enu`): x = x0 + doğu, y = y0 + kuzey, z = z0 − aşağı; (x0, y0, z0) = o aracın başlangıç konumu (UAV_START_POSES), adaptördeki çevirmeyle aynı kural
  7. ENU'da düz zemin düzlemi z = ZEMIN_Z_M ile kesişim; kesişim noktasının (x, y) çifti = (doğu, kuzey)
Konumsuz kalma nedenleri [belge FR-18]: `poz_yok` (kare için geçerli poz yok), `kesisim_yok` (ışın zemine doğru değil ya da paralel, kesişim kameranın arkasında ya da
kutu/ışın sonlu değil). Kesişim için mesafe sınırı YOKTUR (belgede yok); kesişim mesafesi `KonumSonucu.mesafe_m`'de raporlanır.
Test hedeflerinin gerçek koordinatı ve sınıf kimliği bu modüle verilmez.
"""
import json
import math
import os

from ..ucus import rota as _rota

NEDEN_POZ_YOK, NEDEN_KESISIM_YOK = "poz_yok", "kesisim_yok"
NEDENLER = (NEDEN_POZ_YOK, NEDEN_KESISIM_YOK)
_EPS = 1e-12


class KalibrasyonHatasi(ValueError):
    """Kalibrasyon dosyası okunamıyor ya da bozuk: açık hata (sessiz varsayılan yok)."""


class KonumSonucu:
    """`konum`: (doğu_m, kuzey_m) ya da None; `neden`: None | poz_yok | kesisim_yok; `mesafe_m`: kamera–kesişim uzaklığı (yalnız konum doluysa)."""
    __slots__ = ("konum", "neden", "mesafe_m")

    def __init__(self, konum, neden, mesafe_m=None):
        self.konum, self.neden, self.mesafe_m = konum, neden, mesafe_m

    def __repr__(self):
        return f"KonumSonucu(konum={self.konum}, neden={self.neden}, mesafe_m={self.mesafe_m})"


class Kalibrasyon:
    """`config/kamera_kalibrasyon.json` (sozlesmeler.md §4): iç parametreler ve kamera → gövde (FLU) dönüşümü dosyadan okunur; kodda sabit yok."""
    __slots__ = ("kimlik", "fx", "fy", "cx", "cy", "R", "t", "genislik", "yukseklik")

    def __init__(self, kimlik, fx, fy, cx, cy, R, t, genislik, yukseklik):
        self.kimlik, self.fx, self.fy, self.cx, self.cy, self.R, self.t = kimlik, fx, fy, cx, cy, R, t
        self.genislik, self.yukseklik = genislik, yukseklik


def _sonlu_liste(v, n, ad):
    try:
        x = tuple(float(a) for a in v)
    except (TypeError, ValueError):
        raise KalibrasyonHatasi(f"{ad}: sayı listesi olmalı") from None
    if len(x) != n or not all(math.isfinite(a) for a in x):
        raise KalibrasyonHatasi(f"{ad}: {n} sonlu sayı olmalı")
    return x


def kalibrasyon_oku(yol=None):
    """Kalibrasyon dosyasını okur ve doğrular; okunamaz ya da bozuksa KalibrasyonHatasi."""
    yol = yol or os.path.join(_rota.KOK, "config", "kamera_kalibrasyon.json")
    try:
        with open(yol, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        raise KalibrasyonHatasi(f"kamera kalibrasyon dosyası okunamadı ({yol}): {e}") from None
    try:
        if d.get("tur") != "kamera_kalibrasyon":
            raise KalibrasyonHatasi("tur 'kamera_kalibrasyon' olmalı")
        kimlik = d["kalibrasyon_kimligi"]
        if not isinstance(kimlik, str) or not kimlik:
            raise KalibrasyonHatasi("kalibrasyon_kimligi boş olmayan metin olmalı")
        ic = d["ic_parametreler"]
        fx, fy, cx, cy = _sonlu_liste([ic["fx"], ic["fy"], ic["cx"], ic["cy"]], 4, "ic_parametreler")
        if fx <= 0 or fy <= 0:
            raise KalibrasyonHatasi("fx ve fy pozitif olmalı")
        ak = d["arac_kamera"]
        if ak.get("arac_cercevesi") != "FLU" or ak.get("kamera_cercevesi") != "OpenCV":
            raise KalibrasyonHatasi("çerçeveler FLU (araç) ve OpenCV (kamera) olmalı")
        if len(ak["R"]) != 3:
            raise KalibrasyonHatasi("R 3 × 3 olmalı")
        R = tuple(_sonlu_liste(s, 3, "R satırı") for s in ak["R"])
        t = _sonlu_liste(ak["t_m"], 3, "t_m")
        cz = d["cozunurluk"]
        w, h = int(cz["genislik_px"]), int(cz["yukseklik_px"])
    except KalibrasyonHatasi as e:
        raise KalibrasyonHatasi(f"kamera kalibrasyon dosyası bozuk ({yol}): {e}") from None
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise KalibrasyonHatasi(f"kamera kalibrasyon dosyası bozuk ({yol}): eksik ya da geçersiz alan: {e!r}") from None
    return Kalibrasyon(kimlik, fx, fy, cx, cy, R, t, w, h)


def ned_den_enu(kuzey, dogu, asagi, x0=0.0, y0=0.0, z0=0.0):
    """AÇIK NED → yerel ENU (tek fonksiyon; adaptör `konum_enu_m` için de bunu çağırır): x = x0 + doğu, y = y0 + kuzey, z = z0 − aşağı.
    Yön vektörleri için başlangıç (x0, y0, z0) sıfır verilir."""
    return (x0 + dogu, y0 + kuzey, z0 - asagi)


def kuaterniyon_matrisi(q):
    """Birim kuaterniyon (wxyz) → 3 × 3 döndürme matrisi (gövde FRD → NED). Normu sıfır ya da sonlu değilse ValueError."""
    w, x, y, z = (float(v) for v in q)
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if not n or not math.isfinite(n):
        raise ValueError("kuaterniyon normu sıfır ya da sonlu değil")
    w, x, y, z = w / n, x / n, y / n, z / n
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def _carp(M, v):
    return tuple(sum(M[i][j] * v[j] for j in range(3)) for i in range(3))


class KonumHesaplayici:
    """Bir araç için konum hesaplayıcı. baslangic = (x0, y0, z0): aracın UAV_START_POSES konumu (ENU); zemin_z_m: düz zemin düzleminin ENU yüksekliği."""

    def __init__(self, kalibrasyon, baslangic, zemin_z_m):
        self.kal = kalibrasyon
        self.baslangic = tuple(float(v) for v in baslangic)
        self.zemin_z_m = float(zemin_z_m)
        if len(self.baslangic) != 3 or not all(math.isfinite(v) for v in self.baslangic) or not math.isfinite(self.zemin_z_m):
            raise ValueError("baslangic üç sonlu sayı, zemin_z_m sonlu sayı olmalı")

    @classmethod
    def yapilandirmadan(cls, ham, arac_kimligi, kalibrasyon_yolu=None):
        """`config/deney.env` sözlüğünden (UAV_SYS_IDS, UAV_START_POSES, ZEMIN_Z_M) ve kalibrasyon dosyasından. Eksik anahtar KeyError, kötü kalibrasyon KalibrasyonHatasi."""
        kimlikler = [int(a) for a in ham["UAV_SYS_IDS"].split()]
        sira = kimlikler.index(int(arac_kimligi))
        x0, y0, z0 = (float(v) for v in ham["UAV_START_POSES"].split()[sira].split(","))
        return cls(kalibrasyon_oku(kalibrasyon_yolu), (x0, y0, z0), float(ham["ZEMIN_Z_M"]))

    def kamera_isini(self, poz, kutu):
        """Kutu merkezinin ışını: (başlangıç noktası ENU, yön ENU) — yön normalize değil (kamera çerçevesinde z = 1). Geçerli poz ve sonlu kutu varsayılır."""
        k = self.kal
        u, v = (kutu[0] + kutu[2]) / 2.0, (kutu[1] + kutu[3]) / 2.0
        d_kam = ((u - k.cx) / k.fx, (v - k.cy) / k.fy, 1.0)
        d_flu = _carp(k.R, d_kam)
        d_frd = (d_flu[0], -d_flu[1], -d_flu[2])
        M = kuaterniyon_matrisi(poz.q)
        d_ned = _carp(M, d_frd)
        t_frd = (k.t[0], -k.t[1], -k.t[2])
        t_ned = _carp(M, t_frd)
        konum = poz.konum
        o_ned = (konum[0] + t_ned[0], konum[1] + t_ned[1], konum[2] + t_ned[2])
        x0, y0, z0 = self.baslangic
        return ned_den_enu(*o_ned, x0, y0, z0), ned_den_enu(*d_ned)

    def hesapla(self, kutu, poz):
        """Kutu ([x_min, y_min, x_maks, y_maks] piksel) ve kare–poz (`gecerli`, `konum` NED, `q` wxyz özniteliklerini taşıyan nesne ya da None) → KonumSonucu."""
        if poz is None or not getattr(poz, "gecerli", False) or poz.konum is None or poz.q is None:
            return KonumSonucu(None, NEDEN_POZ_YOK)
        try:
            kutu = tuple(float(v) for v in kutu)
            sonlu = len(kutu) == 4 and all(math.isfinite(v) for v in kutu)
        except (TypeError, ValueError):
            sonlu = False
        if not sonlu:
            return KonumSonucu(None, NEDEN_KESISIM_YOK)
        try:
            o, d = self.kamera_isini(poz, kutu)
        except ValueError:
            return KonumSonucu(None, NEDEN_POZ_YOK)           # kuaterniyon kullanılamaz: kare için geçerli poz yok
        if not all(math.isfinite(v) for v in o + d):
            return KonumSonucu(None, NEDEN_POZ_YOK)
        if d[2] >= -_EPS:                                     # ışın zemine doğru değil ya da paralel
            return KonumSonucu(None, NEDEN_KESISIM_YOK)
        s = (self.zemin_z_m - o[2]) / d[2]
        if not s > 0.0:                                       # kesişim kameranın arkasında (kamera zeminin altında/üzerinde değil)
            return KonumSonucu(None, NEDEN_KESISIM_YOK)
        e, n = o[0] + s * d[0], o[1] + s * d[1]
        if not (math.isfinite(e) and math.isfinite(n)):
            return KonumSonucu(None, NEDEN_KESISIM_YOK)
        return KonumSonucu((e, n), None, s * math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2))


def enu_flu_den_ned_frd(konum_enu, q_enu_flu, baslangic):
    """YALNIZ analiz: Gazebo gerçek pozu (ENU konum, gövde FLU → ENU kuaterniyonu wxyz) → hesaplayıcının girdisi (NED konum, gövde FRD → NED kuaterniyonu wxyz).
    Gerçek poz ile hesaplayıcı hatasını poz hatasından ayırmak için; uçuş koduna girmez."""
    x0, y0, z0 = baslangic
    konum_ned = (konum_enu[1] - y0, konum_enu[0] - x0, -(konum_enu[2] - z0))
    A = kuaterniyon_matrisi(q_enu_flu)                                    # FLU → ENU
    ned_enu = ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0))        # ENU → NED
    flu_frd = (1.0, -1.0, -1.0)                                           # FRD → FLU (köşegen)
    B = [[sum(ned_enu[i][k] * A[k][j] for k in range(3)) * flu_frd[j] for j in range(3)] for i in range(3)]
    return konum_ned, _matristen_kuaterniyon(B)


def _matristen_kuaterniyon(M):
    t = M[0][0] + M[1][1] + M[2][2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = (0.25 * s, (M[2][1] - M[1][2]) / s, (M[0][2] - M[2][0]) / s, (M[1][0] - M[0][1]) / s)
    elif M[0][0] > M[1][1] and M[0][0] > M[2][2]:
        s = math.sqrt(1.0 + M[0][0] - M[1][1] - M[2][2]) * 2
        q = ((M[2][1] - M[1][2]) / s, 0.25 * s, (M[0][1] + M[1][0]) / s, (M[0][2] + M[2][0]) / s)
    elif M[1][1] > M[2][2]:
        s = math.sqrt(1.0 + M[1][1] - M[0][0] - M[2][2]) * 2
        q = ((M[0][2] - M[2][0]) / s, (M[0][1] + M[1][0]) / s, 0.25 * s, (M[1][2] + M[2][1]) / s)
    else:
        s = math.sqrt(1.0 + M[2][2] - M[0][0] - M[1][1]) * 2
        q = ((M[1][0] - M[0][1]) / s, (M[0][2] + M[2][0]) / s, (M[1][2] + M[2][1]) / s, 0.25 * s)
    return q
