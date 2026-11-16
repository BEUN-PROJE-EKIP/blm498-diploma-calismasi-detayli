"""Araç süreci kapanış yolu birim testleri (ROS 2, MAVSDK ve gz-transport gerekmez; sahte bileşenlerle). Çalıştırma: python3 src/swarm_vehicle/test/test_arac_kapanis.py"""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from swarm_vehicle import arac as ar  # noqa: E402
from swarm_vehicle import poz_tamponu as pt  # noqa: E402
from swarm_vehicle import rota  # noqa: E402


class Sahte:
    """kapat/bosalt_ve_kapat çağrılarını sayan sahte bileşen; `hata` verilirse çağrıda istisna atar."""

    def __init__(self, hata=None):
        self.cagri, self.hata = 0, hata

    def kapat(self, *a):
        self.cagri += 1
        if self.hata:
            raise self.hata

    bosalt_ve_kapat = destroy_node = shutdown = kapat

    def join(self, *a):
        pass


class KapanisBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a = ar.Arac(1, rota.deney_env_oku())
        self.a.log_yol = os.path.join(self.tmp.name, "arac.log")
        self.a.isleyici = None

    def yazici(self, ad, n=3):
        y = pt.SatirYazici(os.path.join(self.tmp.name, ad + ".jsonl"), self.a.log)
        for k in range(n):
            y.ver({"k": k})
        return y

    def gunluk(self):
        with open(self.a.log_yol, encoding="utf-8") as f:
            return f.read().splitlines()


class Kapanis(KapanisBase):
    def test_adimlar_tek_tek_korunur_kodu_degistirmez_ve_kapandi_sonda(self):
        a = self.a
        a.cikis_kodu = 143
        a.adapter, a.kamera, a.isci, a.kanal = Sahte(RuntimeError("adaptör")), Sahte(), Sahte(), Sahte()
        a._node, a._rclpy = Sahte(), mock.Mock(ok=lambda: True, shutdown=Sahte().shutdown)
        a._yazicilar = [self.yazici("a"), self.yazici("b")]
        a._kapanis()
        self.assertEqual((a.kamera.cagri, a.isci.cagri, a.kanal.cagri, a._node.cagri), (1, 1, 1, 1))     # adaptör hatası sonrakileri durdurmadı
        self.assertEqual(a.cikis_kodu, 143)
        g = self.gunluk()
        self.assertTrue(any(" kapanis_adimi_hatasi adim=adapter " in x for x in g))
        self.assertEqual(sum(" satir_yazici_ozet " in x for x in g), 2)                                    # iki yazıcı da kapandı ve özetlendi
        self.assertIn(" kapandi cikis_kodu=143", g[-1])                                                    # en sonda, koşulsuz
        for y in a._yazicilar:
            o = y.ozet()
            self.assertEqual((o["yazilan"], o["tamam"]), (3, True))

    def test_yazici_kapatma_her_zaman_calisir_ve_ozet_bir_kez(self):
        a = self.a
        a.adapter = Sahte(RuntimeError("a"))
        a.kamera = Sahte(RuntimeError("k"))
        a.kanal = Sahte(RuntimeError("c"))
        a._yazicilar = [self.yazici("a")]
        a._kapanis()
        a._yazicilari_kapat()                                       # ikinci kapanış: özet yeniden yazılmaz
        self.assertEqual(sum(" satir_yazici_ozet " in x for x in self.gunluk()), 1)
        self.assertEqual(sum(" kapanis_adimi_hatasi " in x for x in self.gunluk()), 3)

    def test_kurulum_hatasinda_da_kapanir_ve_hata_yayilir(self):
        """Kurulum (kaynaklar oluşturulduktan sonra, rclpy.init/Node/yayımcı aşamasında) istisna verirse: yazıcılar kapalı, işçi ve adaptör kapatıldı, `kapandi` var, istisna çağırana gider."""
        a = self.a

        def govde():
            a.adapter, a.isci = Sahte(), Sahte()
            a._yazicilar = [self.yazici("poz"), self.yazici("kuyruk")]
            raise RuntimeError("rclpy.init sonrası kurulum hatası")
        with mock.patch.dict(os.environ, {"FASTRTPS_DEFAULT_PROFILES_FILE": "x"}), mock.patch.object(a, "_calistir_govde", govde):
            with self.assertRaises(RuntimeError):
                a.calistir()
        self.assertEqual((a.adapter.cagri, a.isci.cagri), (1, 1))
        self.assertTrue(all(y.ozet()["tamam"] and y.ozet()["yazilan"] == 3 for y in a._yazicilar))
        g = self.gunluk()
        self.assertEqual(sum(" satir_yazici_ozet " in x for x in g), 2)
        self.assertIn(" kapandi cikis_kodu=1", g[-1])
        self.assertEqual(a.cikis_kodu, 1)

    def test_normal_donus_kodu_korunur(self):
        a = self.a
        with mock.patch.dict(os.environ, {"FASTRTPS_DEFAULT_PROFILES_FILE": "x"}), mock.patch.object(a, "_calistir_govde", lambda: 143):
            self.assertEqual(a.calistir(), 143)
        self.assertIn(" kapandi ", self.gunluk()[-1])

    def test_ham_olmayan_uygulamada_hic_kaynak_yokken_kapanis_guvenli(self):
        self.a._kapanis()                                           # hiçbir bileşen oluşturulmadan (erken kurulum hatası)
        self.assertIn(" kapandi ", self.gunluk()[-1])


class SinyalKilidi(KapanisBase):
    def test_log_kilidi_yeniden_girilebilir(self):
        """Sinyal işleyicisi ana iş parçacığı log() içindeyken log() çağırırsa kilitlenmez (aynı iş parçacığı)."""
        bitti = threading.Event()

        def calis():
            with self.a._log_kilit:
                self.a.log("sinyal", numara=15)
            bitti.set()
        t = threading.Thread(target=calis, daemon=True)
        t.start()
        self.assertTrue(bitti.wait(3), "log() kilidi yeniden girilemedi (kilitlenme)")


class Giris(unittest.TestCase):
    def _calistir(self, main):
        cikislar = []
        with mock.patch.object(ar, "main", main), mock.patch.object(ar.os, "_exit", lambda k: cikislar.append(k)), mock.patch.object(ar.sys, "stderr", mock.Mock()):
            ar.giris()
        return cikislar

    def test_kod_korunur_ve_istisna_cikis_1(self):
        def patla():
            raise RuntimeError("beklenmeyen")
        self.assertEqual(self._calistir(lambda: 0), [0])
        self.assertEqual(self._calistir(lambda: 143), [143])
        self.assertEqual(self._calistir(patla), [1])

    def test_ros2_run_giris_noktasi_os_exit_sarmalayicisini_cagirir(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup.py"), encoding="utf-8") as f:
            self.assertIn("swarm_vehicle.arac:giris", f.read())


if __name__ == "__main__":
    unittest.main()
