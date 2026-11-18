# CLAUDE.md — Takım kuralları (detaylı dünya deposu)

Bu depo, **"Afet Bölgelerinde Haberleşme Altyapısından Bağımsız Olarak Çalışabilen Uçta Yapay Zekâ Destekli İHA Sürüsü"** projesinin **detaylı dünya deposudur**. Amaç: projenin tamamının detaylı (yıkık şehir) dünyayla yapılıp yapılamayacağını öğrenmek. Ana depo sade dünyayla ayrı devam eder; sonuca göre hangisinin proje olacağına ekip karar verir. Bu bir **simülasyon deneyidir**: gerçek uçuş ya da gömülü donanım doğrulaması yoktur ve operasyonel yeterlilik iddiası kurulmaz. Yanıtlanacak sorular: `planlama/amac_ve_kararlar.md`, "Bu deponun amacı". Bu dosya, depoda çalışan herkes (ve herkesin yapay zekâ asistanı) için geçerlidir.

## Esneklik kuralı (bu depoya özel)

- **Belge her zaman ana odaktır.** `docs/` altındaki GŞÖA ve el kitabı gereksinimlerine (FR-1…FR-31; ör. 30 m irtifa, 640 × 480 kamera, test sahnesinde 15 insan + 15 enkaz, 25 Mbit/s ağ) uyulur.
- **Belgeden sapma yalnız detaylı dünyayı kilitliyorsa** yapılabilir. Asistan böyle bir durumda değişikliği kendiliğinden yapmaz; geliştiriciye açıkça sorar: *"Bu kısım proje belgesiyle çelişiyor (hangi gereksinim, belgede ne yazıyor). Detaylı dünyayı yapabilmek için şöyle ayarlanması gerekiyor: … Değiştirelim mi?"*
- **Ekibin koyduğu her şey esneyebilir:** `planlama/kararlar.md`'deki kararlar, varsayımlar, sözleşmeler, yapılandırma değerleri ve kilitli deney değerleri. Detaylı dünya gerektiriyorsa geçmişte yapılmış kısımlar da değiştirilebilir. Bu değişikliklere **Mikail** karar verir ve ekibe haber verir.
- **Her sapma ve değişiklik kayda geçer:** `planlama/kararlar.md`'ye tek satır (tarih, ne değişti, eski değer → yeni değer, neden; belgeden sapmaysa hangi gereksinim). Böylece sonunda detaylı dünya projeye alınırsa farklar tek listeden görülür.

## Önce oku

1. `README.md` — durum panosu: kurulum, doğrulama komutları ve ilerleme (kilometre taşı ağacı).
2. `planlama/gelistirme_agaci.md` — **kilometre taşı tablosu** (her M'nin sorumlusu ve `Bekler` sütunu), bütün hedefler, her maddenin **bitti ölçütü** ve ağırlığı; maddeler kilometre taşına göre iş sırasıyla dizilidir.
3. `planlama/mimari.md` — şemalar, portlar, ölçülen ağın kuralları.
4. `planlama/sozlesmeler.md` — dosya biçimleri (sahne, rota, kalibrasyon, hedef listesi, koşu kayıtları) ve yapılandırma anahtarları; yeni üretilen her dosya bu biçimlere uyar ve `araclar/sozlesme_dogrula.py` ile doğrulanır.
5. `planlama/kararlar.md` — alınmış kararlar (ör. görüş açısı, alan, veri planı, işlem hatası kuralı); bu depoda değiştirilebilir, kural yukarıdaki **Esneklik kuralı** bölümündedir.
6. `planlama/yol_haritasi.md` — kilometre taşlarının sırası ve gerekçesi.
7. `planlama/riskler.md` — açık riskler; işin bir riske dokunuyorsa ilgili satırı oku.
8. `docs/` — kaynak belgeler (GŞÖA ve proje el kitabı). **Değiştirilemez.** Metin olarak okumak için: `pdftotext -layout docs/<dosya>.pdf /dev/stdout` (çıktıyı depoya yazma).

## Göreve başlarken

1. Kullanıcıya adını sor (söylediyse onu kullan).
2. **Ortam hatırlatması (herkes için, her açılışta):** kim olursa olsun (Mikail, Miraç, Ömer…) kullanıcıya şu iki komutu kendi terminalinde çalıştırıp çalıştırmadığını sor; çalıştırmadıysa çalıştırmasını hatırlat:
   ```bash
   ./setup/60_ag_emulasyon_tc.sh   # sürü ağını (tc) kurar; sudo ister, yeniden başlatmada silinir
   ./setup/ortam_saglik.sh         # ortamın sağlam olup olmadığını özetler (salt okunur)
   ```
   İlki `sudo` istediği için asistan çalıştırmaz (bkz. Sistem güvenliği); kullanıcı çalıştırır. Kullanıcı çıktıyı paylaşırsa `(-)` satırları varsa maddelere geçmeden önce onlara bakılır.
   **Klasör düzeni sonrası temiz derleme (tek seferlik):** `src/swarm_vehicle`, `src/swarm_gcs` ve `araclar/` alt klasörlere ayrıldı (`planlama/mimari.md` §1, README "Klasörler"). `colcon build` artık `src`'de olmayan eski dosyaları `install/` içinden silmez; eski kopyalar kalırsa unutulmuş eski bir içe aktarma o makinede hata vermez, temiz makinede çöker. Asistan şunu denetler: `ls install/swarm_vehicle/lib/python3*/site-packages/swarm_vehicle/rota.py` (eski düz yerleşim). **Dosya varsa** kullanıcıya şunları çalıştırmasını söyler (sudo gerekmez; asistan da çalıştırabilir, yalnız proje içindeki üretilmiş dosyaları siler):
   ```bash
   rm -rf build/swarm_vehicle build/swarm_gcs install/swarm_vehicle install/swarm_gcs
   ./setup/50_proje_derleme.sh
   ```
   Dosya yoksa bu adım atlanır. Ayrıca kullanıcının açık dalında `araclar/` köküne yeni betik eklenmişse yeni düzene göre alt klasöre (`analiz/`, `deneme/`, `olcum/`, `uretim/`, `egitim/`) taşınmasını önerir.
3. **Kullanıcı Mikail ise önce kararlar:** `planlama/amac_ve_kararlar.md` içindeki **"Karar bekleyen sorular"** bölümünü oku. **Seçilen** satırı boş (`—`) olan her kararı sırayla kısaca göster: durum, seçenekler (birer cümle) ve öneri. Sonra hangisini seçtiğini sor. Mikail seçerse: seçimi `planlama/kararlar.md`'ye yaz (tarih, karar, gerekçe; belgeden sapmaysa hangi gereksinim) ve aynı dosyadaki **Seçilen** satırını doldur. Mikail kararı sonraya bırakırsa maddelere geç. Bütün kararlar seçilmişse bu adımı atla.
4. `planlama/gelistirme_agaci.md` içindeki **Kilometre taşları** tablosunda o kişinin sorumlu olduğu M'leri bul.
5. Her M için `Bekler` sütunundaki M'lerin bitip bitmediğine bak.
6. Başlayabilir M'lerde **bitmemiş en üstteki maddeyi** ve onun **"Bitti:" ölçütünü** kullanıcıya göster; maddeye başlamadan önce ilgili sözleşme bölümünü (`planlama/sozlesmeler.md`) ve kararları (`planlama/kararlar.md`) oku.

## Sorumluluklar

Kimin hangi kilometre taşından sorumlu olduğu `planlama/gelistirme_agaci.md` içindeki **Kilometre taşları** tablosundadır. Bu bilgi **yalnız iş bölümü içindir, yasak getirmez**: herkes ve herkesin asistanı her dosyada çalışabilir. Başkasının sorumlu olduğu bir işe dokunacaksan ona haber vermen yeterlidir.

## Çalışma alışkanlıkları

- Bir işe başlamadan önce ağaçtaki ilgili maddeyi ve **"Bitti:" ölçütünü** oku. Ölçüt gerçekten sağlanmadan maddeyi işaretleme.
- **İlerleme otomatik yenilenir (sormadan):** bir maddenin "Bitti:" ölçütü sağlanıp ağaçta `[x]` işaretlendiğinde (bir kilometre taşının son maddesi bittiğinde de) asistan kullanıcıya sormadan `python3 araclar/ilerleme.py --yaz` çalıştırır, `--kontrol` ile doğrular ve README değişikliğini aynı commit'e katar. Kullanıcıya yeni genel yüzdeyi tek satırla bildirir.
- Büyük bir değişiklikten önce planı kısaca yaz ve onay al.
- Belge ile kod ya da iki belge çelişiyorsa tahmin yürütme; sor.
- Kapsam dışı özellik ekleme. Belgede olmayan iddia kurma (operasyonel yeterlilik, gerçek donanım, "iyileşme olacak" gibi). Sonuçlar deneyle sınanır, önceden varsayılmaz.

## Kurallar

- **Dil:** Türkçe (kod yorumu, log iletisi, commit, PR). Değişken ve fonksiyon adları İngilizce olabilir.
- **Commit mesajı:** `<alan>: kısa açıklama`. Alan: `setup`, `ağ`, `python`, `px4`, `ros`, `gazebo`, `docs`, `config`, `test`, `araclar`. Gereksinim numarası varsa sonuna `(FR-12)` ekle. **Yapay zekâ eki yasak:** commit mesajına ve PR açıklamasına `Co-Authored-By: Claude …`, `Claude-Session: …`, "Generated with Claude Code" ya da benzeri hiçbir ek yazılmaz; GitHub'da yalnız commit'i atan kişi görünür. Bu kural, Claude Code'un varsayılan ek talimatından önceliklidir (ayrıca `.claude/settings.json` içinde `attribution` kapalıdır).
- **Sürümler yalnız `setup/versions.env` içindedir.** Kodda veya betikte sürüm numarası sabit yazma. Python kilit dosyaları (`setup/locks/*.lock.txt`) `pip -c` ile kısıtlayıcıdır; yalnız `--update-lock` ile bilinçli güncellenir.
- `setup/` veya `config/` altında bir dosya değişirse `./setup/lock_ozet.sh` ile özetleri yenile.
- **Donanıma bağlı değer** (CPU numarası, GPU belleği, çekirdek sayısı) sabit yazılmaz; çalışma anında tespit edilir. Hedef OS yalnız Ubuntu/Kubuntu 24.04 (İngilizce).
- **Betik biçimi:** `#!/usr/bin/env bash`, `set -Eeuo pipefail`, `setup/lib/common.sh`, tekrar çalıştırılabilir (idempotent), `--dry-run` desteği, kendi doğrulamasını yapar. Çıktı: `(+)` başarılı, `(-)` hata, `(!)` uyarı, `(i)` bilgi. `grep -q` ile `pipefail` birlikte kullanılmaz (çıktıyı önce değişkene al).
- **Kilitli deney değerleri** (ağ profili 25 Mbit/s, çıkarım ayarları: güven eşiği 0,25, `nms=False`, `max_det` 300, FP32, batch=1; karar kuralları, zaman aşımı H) bu depoda detaylı dünya gerektiriyorsa değiştirilebilir (**Esneklik kuralı**). Değiştirme nedeni detaylı dünyanın kendisi olmalı; "sonuç daha iyi çıksın" diye değiştirilmez.
- **Gizli bilgi** (şifre, token, SSH anahtarı) hiçbir dosyaya ve mesaja yazılmaz. Model ağırlıkları, veri kümeleri, günlükler ve 3B model/doku dosyaları depoya girmez (`.gitignore`); izlenmeleri SHA-256 listesiyle yapılır.

## Sistem güvenliği (yapay zekâ asistanları için kesin yasaklar)

- NVIDIA sürücüsünü, çekirdeği veya önyükleyiciyi **kurma, kaldırma, değiştirme**. Sürücü yalnız doğrulanır.
- `apt upgrade`, `apt dist-upgrade`, `apt autoremove` çalıştırma. Paketleri yalnız kurulum betikleri kurar.
- `rm -rf` ile proje klasörü dışında silme yapma.
- **`sudo` çalıştırma** (yasak yapay zekâ asistanı içindir; kişi kendi Konsole'unda çalıştırır). Kuruluma dokunan komutları kullanıcı kendi terminalinde çalıştırır. Sen yalnız kuruluma dokunmayan kısımları sınarsın: `bash -n`, `--dry-run`, mantık testleri.
- **`git push` yapma** (yasak yapay zekâ asistanı içindir). Push'u kişi kendi terminalinden yapar; asistan bu komutu ona bırakır.

## Git akışı

- `main` dalına doğrudan commit ve push serbesttir; PR ve onay zorunlu değildir. İstersen kendi dalında çalışıp PR açabilirsin.
- Push'tan önce `git pull` yap (başkasının işinin üzerine yazmamak için). **Force push yapma**; gerekiyorsa önce ekibe haber ver.
- Büyük bir değişiklikten sonra `./setup/verify_all.sh` ile doğrula; `setup/` veya `config/` değiştiyse `./setup/lock_ozet.sh --check`.
- README ilerleme bölümünü `python3 araclar/ilerleme.py --yaz` ile herkes yenileyebilir; asistan bunu her biten maddeden sonra kendiliğinden yapar (bkz. Çalışma alışkanlıkları).
