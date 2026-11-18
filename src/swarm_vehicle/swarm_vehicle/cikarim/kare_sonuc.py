"""Kare sonucu (B10, FR-12): dört durumun ayrı kodlanması, tespit eşlemesi, her görev numarası için TAM BİR sonuç defteri, yerel kayıt ve `swarm_msgs/FrameResult` iletisi.
Yalnız standart kitaplık (rclpy ve swarm_msgs içe aktarılmaz; ileti sınıfları `mesaj_olustur`'a verilir).

Dört durum birbirine KODLANMAZ [belge: kare sonucu iletisi]:
  tespit         çıkarım bitti, proje sınıfında en az bir tespit var                  → FrameResult.STATUS_DETECTIONS
  tespit_yok     çıkarım BAŞARIYLA bitti ve proje sınıfında tespit bulunmadı (açık)   → STATUS_NO_DETECTION
  islem_hatasi   kare alındı ama işlenemedi (işçi hatası/ölümü/zaman aşımı/bozuk görüntü); "tespit yok" DEĞİLDİR → STATUS_PROCESSING_ERROR
  kare_alinamadi alıcıya ulaşmayan görev karesi (alıcının `kayip_tespit` kaydı)       → STATUS_FRAME_NOT_RECEIVED
Yerel kayıt (`kayit/kare_sonuc_<araç>.jsonl`, planlama/sozlesmeler.md §8.6): satır başına bir `kare_sonuc`; kayıt yerel kancaya da verilir (uçta modda kanca DDS'e yayımlar).
Tespitin yatay konumu (`konum` = [doğu_m, kuzey_m] ya da null, `konum_neden`) konum hesaplayıcının (`konum_hesap`) işidir; `candidate` (birleştirme adayı, B15) her tespitte False'tur.
"""
import json
import threading

TESPIT, TESPIT_YOK, ISLEM_HATASI, KARE_ALINAMADI = "tespit", "tespit_yok", "islem_hatasi", "kare_alinamadi"
DURUMLAR = (TESPIT, TESPIT_YOK, ISLEM_HATASI, KARE_ALINAMADI)
# swarm_msgs/FrameResult.msg STATUS_* değerleri (birim testi .msg dosyasından doğrular)
DURUM_KODU = {TESPIT: 1, TESPIT_YOK: 2, ISLEM_HATASI: 3, KARE_ALINAMADI: 4}
NUMARALAMA_IZGARA = 1


def durum_belirle(isci_yaniti, esleme):
    """Çıkarım işçisi yanıtından (sözlük) kare sonucu kaydı alanları: (durum, tespitler, atilan, hata).
    İşçi yanıtı: {"durum": "tamam"|"hata", "tespitler": [{"sinif_adi", "guven", "kutu": [x1, y1, x2, y2]}], "hata": metin}.
    Proje sınıfına eşlenmeyen tespitler atılır ve sayılır (`atilan`); atılanlar "tespit var" yapmaz. Yanıtı bozuk ya da "hata" ise durum `islem_hatasi` (boş tespit ≠ "tespit yok")."""
    if not isinstance(isci_yaniti, dict) or isci_yaniti.get("durum") not in ("tamam", "hata"):
        return ISLEM_HATASI, [], 0, "işçi yanıtı bozuk"
    if isci_yaniti["durum"] == "hata":
        return ISLEM_HATASI, [], 0, str(isci_yaniti.get("hata") or "işçi hatası (ayrıntı yok)")
    tespitler, atilan = [], 0
    try:
        for t in isci_yaniti.get("tespitler", []):
            e = esleme.esle(t["sinif_adi"])
            if e is None:
                atilan += 1
                continue
            x1, y1, x2, y2 = (float(v) for v in t["kutu"])
            tespitler.append({"sinif": e[0], "sinif_no": e[1], "guven": float(t["guven"]), "kutu": [x1, y1, x2, y2], "konum": None, "konum_neden": None, "aday": False})
    except (KeyError, TypeError, ValueError) as ex:
        return ISLEM_HATASI, [], 0, f"işçi yanıtı çözülemedi: {ex!r}"
    return (TESPIT if tespitler else TESPIT_YOK), tespitler, atilan, None


def kayit_olustur(arac_kimligi, n, sim_damga_ns, durum, tespitler=(), atilan=0, hata=None, mono_ns=0, poz=None):
    """`kare_sonuc` kaydı (sözlük). Durum ile içerik tutarsızsa ValueError. `poz` (yalnız merkezi mod): iletiden alınan kare–poz sözlüğü; verilirse kayda `poz` alanı eklenir (uçta modda alan yoktur)."""
    if durum not in DURUMLAR:
        raise ValueError(f"bilinmeyen kare sonucu durumu: {durum!r}")
    tespitler = list(tespitler)
    if (durum == TESPIT) != bool(tespitler):
        raise ValueError(f"durum '{durum}' ile tespit sayısı ({len(tespitler)}) tutarsız")
    if (durum == ISLEM_HATASI) != bool(hata):
        raise ValueError("işlem hatası durumunda hata metni zorunlu, diğer durumlarda yasak")
    k = {"surum": 1, "tur": "kare_sonuc", "arac_kimligi": int(arac_kimligi), "n": int(n), "sim_damga_ns": int(sim_damga_ns), "durum": durum,
         "tespit_sayisi": len(tespitler), "tespitler": tespitler, "atilan_sinif_disi": int(atilan), "hata": hata, "mono_ns": int(mono_ns)}
    if poz is not None:
        k["poz"] = poz
    return k


def mesaj_olustur(kayit, FrameResult, Detection, zaman_olustur):
    """Kayıt sözlüğünden `FrameResult` iletisi. `zaman_olustur(ns)` builtin_interfaces/Time döndürür. `has_position`/`east`/`north` kayıttaki `konum`dan (konumsuzda false ve 0);
    `candidate` her tespitte False (birleştirme adayı B15'tir)."""
    m = FrameResult()
    m.vehicle_id = kayit["arac_kimligi"]
    m.numbering_mode = FrameResult.NUMBERING_GRID
    m.frame_number = kayit["n"]
    m.sim_stamp = zaman_olustur(kayit["sim_damga_ns"])
    m.status = {TESPIT: FrameResult.STATUS_DETECTIONS, TESPIT_YOK: FrameResult.STATUS_NO_DETECTION,
                ISLEM_HATASI: FrameResult.STATUS_PROCESSING_ERROR, KARE_ALINAMADI: FrameResult.STATUS_FRAME_NOT_RECEIVED}[kayit["durum"]]
    for t in kayit["tespitler"]:
        d = Detection()
        d.class_id = t["sinif_no"]
        d.confidence = t["guven"]
        d.box_x_min, d.box_y_min, d.box_x_max, d.box_y_max = t["kutu"]
        if t.get("konum") is not None:
            d.has_position = True
            d.east, d.north = (float(v) for v in t["konum"])
        else:
            d.has_position = False
            d.east = d.north = 0.0
        d.candidate = False
        m.detections.append(d)
    return m


class SonucDefteri:
    """Her görev numarası için tam bir kare sonucu: ikinci sonuç reddedilir (sayılır), eksikler sorgulanır. İş parçacığı güvenlidir."""

    def __init__(self):
        self._k = threading.Condition()
        self.kayitlar = {}
        self.cift_sayisi = 0

    def ekle(self, kayit):
        """True: kaydedildi. False: bu numara için zaten sonuç var (ikinci sonuç yazılmaz, `cift_sayisi` artar)."""
        with self._k:
            if kayit["n"] in self.kayitlar:
                self.cift_sayisi += 1
                return False
            self.kayitlar[kayit["n"]] = kayit
            self._k.notify_all()
            return True

    def var_mi(self, n):
        with self._k:
            return n in self.kayitlar

    def eksikler(self, n_ilk, n_son):
        with self._k:
            return [n for n in range(n_ilk, n_son + 1) if n not in self.kayitlar]

    def bekle_tamam(self, n_ilk, n_son, sure_sn):
        """[n_ilk, n_son] için bütün sonuçlar gelene dek (en çok sure_sn gerçek sn) bekler. True: tamam."""
        import time
        sinir = time.monotonic() + sure_sn
        with self._k:
            while any(n not in self.kayitlar for n in range(n_ilk, n_son + 1)):
                kalan = sinir - time.monotonic()
                if kalan <= 0:
                    return False
                self._k.wait(min(kalan, 0.2))
            return True

    def durum_sayilari(self):
        with self._k:
            s = {d: 0 for d in DURUMLAR}
            for k in self.kayitlar.values():
                s[k["durum"]] += 1
            return s


class KayitYazici:
    """Kare sonucu kayıtlarını JSON Lines dosyasına ekler (satır başına bir kayıt, her yazıda boşaltılır)."""

    def __init__(self, yol):
        self.yol = yol
        self._k = threading.Lock()

    def yaz(self, kayit):
        if not self.yol:
            return
        with self._k, open(self.yol, "a", encoding="utf-8") as f:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
