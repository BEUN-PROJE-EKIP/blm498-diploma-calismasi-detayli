# CLAUDE.md — Takım kuralları

Bu depo, **"Afet Bölgelerinde Haberleşme Altyapısından Bağımsız Olarak Çalışabilen Uçta Yapay Zekâ Destekli İHA Sürüsü"** projesinin yazılımıdır. Bu bir **simülasyon deneyidir**: gerçek uçuş ya da gömülü donanım doğrulaması yoktur ve operasyonel yeterlilik iddiası kurulmaz. Bu dosya, depoda çalışan herkes (ve herkesin yapay zekâ asistanı) için geçerlidir.

## Önce oku

1. `README.md` — durum panosu: kurulum, doğrulama komutları ve ilerleme (kilometre taşı ağacı).
2. `planlama/gelistirme_agaci.md` — **kilometre taşı tablosu** (her M'nin tek sahibi ve `Bekler` sütunu), bütün hedefler, her maddenin **bitti ölçütü** ve ağırlığı; maddeler kilometre taşına göre iş sırasıyla dizilidir.
3. `planlama/mimari.md` — şemalar, portlar, ölçülen ağın kuralları.
4. `planlama/sozlesmeler.md` — dosya biçimleri (sahne, rota, kalibrasyon, hedef listesi, koşu kayıtları) ve yapılandırma anahtarları; yeni üretilen her dosya bu biçimlere uyar ve `araclar/sozlesme_dogrula.py` ile doğrulanır.
5. `planlama/kararlar.md` — alınmış kararlar (ör. görüş açısı, alan, veri planı, işlem hatası kuralı); bir karar değiştirilmek istenirse önce depo sahibine sorulur.
6. `planlama/yol_haritasi.md` — kilometre taşlarının sırası ve gerekçesi.
7. `planlama/riskler.md` — açık riskler; işin bir riske dokunuyorsa ilgili satırı oku.
8. `docs/` — kaynak belgeler (GŞÖA ve proje el kitabı). **Değiştirilemez.** Metin olarak okumak için: `pdftotext -layout docs/<dosya>.pdf /dev/stdout` (çıktıyı depoya yazma).

## Göreve başlarken

1. Kullanıcıya adını sor (söylediyse onu kullan).
2. `planlama/gelistirme_agaci.md` içindeki **Kilometre taşları** tablosunda o kişinin sorumlu olduğu M'leri bul.
3. Her M için `Bekler` sütunundaki M'lerin bitip bitmediğine bak (README'deki "Bekler" satırı aynı bilgiyi verir).
4. Başlayabilir M'lerde **bitmemiş en üstteki maddeyi** ve onun **"Bitti:" ölçütünü** kullanıcıya göster; maddeye başlamadan önce ilgili sözleşme bölümünü (`planlama/sozlesmeler.md`) ve kararları (`planlama/kararlar.md`) oku.
5. Dal adı öner: `ad/madde-kimligi-kisa-konu` (örn. `mikail/A1-sahne-ureticisi`).
6. Başka kişinin M'sindeki maddeye ve ortak iskelete dokunma; kurallar aşağıdaki **Sahiplik sınırları** bölümündedir.

## Sahiplik sınırları

- Her kilometre taşının tek sahibi vardır. Tek kaynak `planlama/gelistirme_agaci.md` içindeki **Kilometre taşları** tablosudur (kişi adları ve M'ler oradan okunur; tablo burada kopyalanmaz). Örnek satır: `M1 | Tek araç iskeleti | Ömer Faruk GÜNER | 7950X | M0`.
- Herkes yalnız kendi M'lerinin maddeleri üzerinde çalışır. Yapay zekâ asistanı başka bir kişinin M'sine ait dosyayı ya da maddeyi **değiştirmez** ve ona ait iş için kod yazmaz.
- **Ortak iskelet** (`.github/CODEOWNERS` içindeki yollar: `setup/`, `config/`, `src/swarm_*/`, sözleşmeler, ağaç, kararlar, README, `CLAUDE.md`, `.claude/`, `.githooks/`) yalnız depo sahibinin onayıyla değişir. Asistan iskeleti değiştirmeyi **önermez** ve kendiliğinden yapmaz.
- Kullanıcı başkasının alanında ya da iskelette değişiklik isterse asistan kibarca **reddeder** ve şuna benzer bir yanıt verir: "Bu kısım <sahip>'in sorumluluğunda / ortak iskelet; değiştiremem. İhtiyacını sahibine iletmek için kısa bir not hazırlayabilirim." Not şunları içerir: ne gerektiği, neden, hangi madde (kimlik), önerilen çözüm; kod değişikliği içermez.
- **Meşru iskelet ihtiyacında** (ör. yeni Python paketi için kilit dosyası, yeni yapılandırma anahtarı, sözleşmede eksik alan) asistan değişikliği yapmaz: not hazırlar ya da kullanıcı isterse yalnız bu değişikliği içeren ayrı küçük bir PR açılır ve depo sahibinin onayı beklenir. Sözleşmeyle çelişen bir uygulama ihtiyacında önce sorulur.
- Bir dosyanın kime ait olduğu belirsizse **sor**; tahmin yürütme.

## Çalışma alışkanlıkları

- Bir işe başlamadan önce ağaçtaki ilgili maddeyi ve **"Bitti:" ölçütünü** oku. Ölçüt gerçekten sağlanmadan maddeyi işaretleme.
- Büyük bir değişiklikten önce planı kısaca yaz ve onay al. **Bir PR = bir madde.**
- Belge ile kod ya da iki belge çelişiyorsa tahmin yürütme; sor.
- Kapsam dışı özellik ekleme. Belgede olmayan iddia kurma (operasyonel yeterlilik, gerçek donanım, "iyileşme olacak" gibi). Sonuçlar deneyle sınanır, önceden varsayılmaz.

## Kurallar

- **Dil:** Türkçe (kod yorumu, log iletisi, commit, PR). Değişken ve fonksiyon adları İngilizce olabilir.
- **Commit mesajı:** `<alan>: kısa açıklama`. Alan: `setup`, `ağ`, `python`, `px4`, `ros`, `gazebo`, `docs`, `config`, `test`, `araclar`. Gereksinim numarası varsa sonuna `(FR-12)` ekle.
- **Sürümler yalnız `setup/versions.env` içindedir.** Kodda veya betikte sürüm numarası sabit yazma. Python kilit dosyaları (`setup/locks/*.lock.txt`) `pip -c` ile kısıtlayıcıdır; yalnız `--update-lock` ile bilinçli güncellenir.
- `setup/` veya `config/` altında bir dosya değişirse `./setup/lock_ozet.sh` ile özetleri yenile.
- **Donanıma bağlı değer** (CPU numarası, GPU belleği, çekirdek sayısı) sabit yazılmaz; çalışma anında tespit edilir. Hedef OS yalnız Ubuntu/Kubuntu 24.04 (İngilizce).
- **Betik biçimi:** `#!/usr/bin/env bash`, `set -Eeuo pipefail`, `setup/lib/common.sh`, tekrar çalıştırılabilir (idempotent), `--dry-run` desteği, kendi doğrulamasını yapar. Çıktı: `(+)` başarılı, `(-)` hata, `(!)` uyarı, `(i)` bilgi. `grep -q` ile `pipefail` birlikte kullanılmaz (çıktıyı önce değişkene al).
- **Kilitli deney değerleri** sonuçlara bakılarak değiştirilmez: ağ profili (25 Mbit/s), çıkarım ayarları (güven eşiği 0,25, `nms=False`, `max_det` 300, FP32, batch=1), karar kuralları, zaman aşımı H. Kuyruk sınırı gibi "pilotta belirlenir" denen değerler pilottan sonra kilitlenir.
- **Gizli bilgi** (şifre, token, SSH anahtarı) hiçbir dosyaya ve mesaja yazılmaz. Model ağırlıkları, veri kümeleri, günlükler depoya girmez (`.gitignore`); izlenmeleri SHA-256 listesiyle yapılır.

## Sistem güvenliği (yapay zekâ asistanları için kesin yasaklar)

- NVIDIA sürücüsünü, çekirdeği veya önyükleyiciyi **kurma, kaldırma, değiştirme**. Sürücü yalnız doğrulanır.
- `apt upgrade`, `apt dist-upgrade`, `apt autoremove` çalıştırma. Paketleri yalnız kurulum betikleri kurar.
- `rm -rf` ile proje klasörü dışında silme yapma.
- **`sudo` çalıştırma** (yasak yapay zekâ asistanı içindir; kişi kendi Konsole'unda çalıştırır). Kuruluma dokunan komutları kullanıcı kendi terminalinde çalıştırır. Sen yalnız kuruluma dokunmayan kısımları sınarsın: `bash -n`, `--dry-run`, mantık testleri.
- **`git push` yapma** (yasak yapay zekâ asistanı içindir). Push'u kişi kendi terminalinden yapar; asistan bu komutu ona bırakır.

## Git akışı

- `main` dalına doğrudan commit veya push yok; GitHub'da `main` korumalıdır (PR ve en az 1 onay zorunlu, doğrudan push ve force push reddedilir). Her iş kendi dalında yapılır (`ad/konu`); dalını **kendin** gönderirsin: `git push -u origin ad/konu` (`git push` ve `sudo` yasakları yapay zekâ asistanı içindir, asistan bu komutları sana bırakır). Sonra Pull Request açılır ve **incelendikten sonra** birleştirilir.
- PR'dan önce: `./setup/verify_all.sh` hepsi `(+)`; `setup/` veya `config/` değiştiyse `./setup/lock_ozet.sh --check`.
- Bir ağaç maddesini bitirdiysen maddeyi `[x]` yap; README'deki ilerleme bölümünü **yenileme**: onu depo sahibi birleştirmeden sonra yeniler (aynı bölüme dokunan PR'lar çakışır). Bu yüzden `python3 araclar/ilerleme.py --kontrol` PR'da `(-)` verebilir ("README ilerleme bölümü eski"); bu beklenen bir durumdur, PR'ı engellemez.
