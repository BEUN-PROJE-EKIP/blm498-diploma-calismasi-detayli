"""Çıkarım işçisi ile araç süreci arasındaki saf yardımcılar (B9): kanal çerçevelemesi, sınıf eşlemesi, işçi hata enjeksiyonu, CPU topolojisi.
Yalnız standart kitaplık; rclpy, gz, torch, numpy içe aktarılmaz (birim testi için; işçi de bu modülü kullanır).

Kanal (IP KULLANMAZ): araç süreci `socket.socketpair(AF_UNIX)` çiftinin bir ucunu işçi alt sürecine devreder; TCP/UDP, DDS ve ağ adresi yoktur. Çerçeve biçimi:
`!II` (JSON başlığının bayt uzunluğu, yükün bayt uzunluğu) + UTF-8 JSON başlık + ham yük. Görüntü yükü (CAM_WIDTH·CAM_HEIGHT·3 = 921 600 bayt RGB8) alıcıdaki bayt
nesnesinden doğrudan gönderilir (araç tarafında ek kopya yok), işçide tek ön ayrılmış arabelleğe okunur.
"""
import json
import os
import struct

_BASLIK = struct.Struct("!II")
BASLIK_MAKS = 1 << 20          # 1 MiB (bozuk çerçeve koruması)
YUK_MAKS = 1 << 26             # 64 MiB


class KanalKapandi(EOFError):
    """Karşı uç kapandı (işçi öldü ya da araç süreci kapandı)."""


def _tam_oku(s, n, hedef=None):
    tampon = hedef if hedef is not None else bytearray(n)
    gorunum = memoryview(tampon)[:n]
    alinan = 0
    while alinan < n:
        k = s.recv_into(gorunum[alinan:], n - alinan)
        if k == 0:
            raise KanalKapandi("kanal kapandı")
        alinan += k
    return tampon


def cerceve_yaz(s, baslik, yuk=b""):
    """Bir çerçeve gönderir. `yuk` bytes/bytearray/memoryview olabilir (kopyalanmaz)."""
    b = json.dumps(baslik, ensure_ascii=False).encode("utf-8")
    s.sendall(_BASLIK.pack(len(b), len(yuk)) + b)
    if len(yuk):
        s.sendall(yuk)


def cerceve_oku(s, yuk_tamponu=None):
    """Bir çerçeve okur → (başlık sözlüğü, yük bytearray). `yuk_tamponu` yeterince büyükse yeniden kullanılır; dönen yük tam uzunlukta bir `memoryview`'dır.
    Karşı uç kapalıysa KanalKapandi."""
    h = _tam_oku(s, _BASLIK.size)
    bl, yl = _BASLIK.unpack(bytes(h))
    if bl > BASLIK_MAKS or yl > YUK_MAKS:
        raise ValueError(f"bozuk çerçeve: başlık {bl} bayt, yük {yl} bayt")
    baslik = json.loads(bytes(_tam_oku(s, bl)).decode("utf-8"))
    if yl == 0:
        return baslik, memoryview(b"")
    if yuk_tamponu is None or len(yuk_tamponu) < yl:
        yuk_tamponu = bytearray(yl)
    _tam_oku(s, yl, yuk_tamponu)
    return baslik, memoryview(yuk_tamponu)[:yl]


# --- sınıf eşlemesi -----------------------------------------------------------------------------------------------------------------------
class SinifEsleme:
    """Model sınıf adı → proje sınıfı (MODEL_SINIFLAR sırası = Detection.CLASS_* numarası: insan 0, enkaz 1).
    Model sınıf adı zaten proje sınıfıysa birebir eşlenir (M5 modeli). Aksi halde MODEL_ESLEME_COCO tablosuna bakılır; tabloda olmayan sınıf None döner (atılır ve sayılır)."""

    def __init__(self, proje_siniflari, tablo_metni=""):
        self.siniflar = list(proje_siniflari)
        self.tablo = {}
        for parca in (tablo_metni or "").split():
            k, _, v = parca.partition("=")
            if not k or v not in self.siniflar:
                raise ValueError(f"MODEL_ESLEME_COCO: geçersiz eşleme '{parca}' (hedef MODEL_SINIFLAR içinde olmalı: {self.siniflar})")
            self.tablo[k] = v

    @classmethod
    def yapilandirmadan(cls, ham):
        return cls(ham["MODEL_SINIFLAR"].split(), ham.get("MODEL_ESLEME_COCO", ""))

    def esle(self, model_sinif_adi):
        """(proje sınıfı adı, sınıf numarası) ya da None."""
        ad = model_sinif_adi if model_sinif_adi in self.siniflar else self.tablo.get(model_sinif_adi)
        return None if ad is None else (ad, self.siniflar.index(ad))


# --- işçi hata enjeksiyonu (YALNIZ test; varsayılan kapalı) ---------------------------------------------------------------------------------
class IsciEnjeksiyon:
    """Ortam değişkeni ISCI_ENJEKSIYON: `hata=<belirteç,...>;olum=<belirteç,...>`; belirteç: `+k` (n_ilk + k) ya da mutlak numara.
    hata: işçi o numaralı karede işlem hatası döndürür. olum: işçi o numaralı kareyi aldıktan sonra kendi sürecini sonlandırır (işleme başlamadan, `cikarim_basi` yazıldıktan sonra).
    Her belirteç bir kez tetiklenir (işçi yeniden başlatıldığında aynı kare ikinci kez ölümü tetiklemez)."""

    def __init__(self, metin=""):
        self.hata, self.olum = [], []
        for parca in [p for p in (metin or "").split(";") if p.strip()]:
            anahtar, _, deger = parca.partition("=")
            anahtar = anahtar.strip()
            if anahtar not in ("hata", "olum"):
                raise ValueError(f"ISCI_ENJEKSIYON: bilinmeyen anahtar '{anahtar}'")
            getattr(self, anahtar).extend(t.strip() for t in deger.split(",") if t.strip())
        self._kullanildi = set()

    @property
    def acik(self):
        return bool(self.hata or self.olum)

    @staticmethod
    def _coz(belirtec, n_ilk):
        if belirtec.startswith("+"):
            return None if n_ilk is None else n_ilk + int(belirtec[1:])
        return int(belirtec)

    def karar(self, n, n_ilk):
        """n numaralı kare için `"hata"`, `"olum"` ya da None; her belirteç yalnız bir kez."""
        for tur in ("olum", "hata"):
            for t in getattr(self, tur):
                if (tur, t) not in self._kullanildi and self._coz(t, n_ilk) == n:
                    self._kullanildi.add((tur, t))
                    return tur
        return None

    def ozet(self):
        return f"hata={','.join(self.hata)};olum={','.join(self.olum)}" if self.acik else "kapali"


# --- CPU topolojisi -----------------------------------------------------------------------------------------------------------------------
def cpu_cekirdek_kumeleri(cpu_dizini="/sys/devices/system/cpu"):
    """Aynı fiziksel çekirdeğe ait mantıksal CPU kümeleri (thread_siblings_list), küme içinde ve kümeler arasında artan sırada. Çalışma anında okunur; sabit numara yoktur."""
    kumeler = set()
    for ad in os.listdir(cpu_dizini):
        if not (ad.startswith("cpu") and ad[3:].isdigit()):
            continue
        yol = os.path.join(cpu_dizini, ad, "topology", "thread_siblings_list")
        try:
            with open(yol, encoding="utf-8") as f:
                metin = f.read().strip()
        except OSError:
            continue
        kumeler.add(tuple(cpu_listesi_coz(metin)))
    return sorted(kumeler)


def cpu_listesi_coz(metin):
    """'0,16' ya da '0-1,8-9' → [0, 16] ya da [0, 1, 8, 9]."""
    sonuc = []
    for parca in metin.split(","):
        parca = parca.strip()
        if not parca:
            continue
        a, tire, b = parca.partition("-")
        sonuc.extend(range(int(a), int(b) + 1) if tire else [int(a)])
    return sorted(sonuc)


def cpu_ata(arac_no, kumeler, adet, izinli=None):
    """Araç sırasına (1'den) göre bir çekirdek kümesi seçer ve içinden `adet` mantıksal CPU verir → (CPU listesi, açıklama). Uygun küme yoksa ([], neden).
    `izinli`: sürecin kullanabildiği CPU kümesi (sched_getaffinity); verilirse yalnız tam olarak ona dahil kümeler sayılır. Kümeler artan sırada dizilir; araç k, k. kümeyi alır."""
    uygun = [k for k in kumeler if len(k) >= adet and (izinli is None or set(k) <= set(izinli))]
    if arac_no < 1 or arac_no > len(uygun):
        return [], f"araç {arac_no} için uygun çekirdek kümesi yok (en az {adet} mantıksal CPU'lu {len(uygun)} küme)"
    secilen = list(uygun[arac_no - 1][:adet])
    return secilen, f"çekirdek kümesi {list(uygun[arac_no - 1])} → CPU {secilen}"
