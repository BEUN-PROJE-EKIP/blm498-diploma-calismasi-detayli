# Katkı rehberi

Bu projeye katkı vermek için aşağıdaki adımları sırayla izle. Amaç, herkesin işinin birbirini bozmadan ana kola (`main`) girmesi.

## Önce

1. [README](README.md)'deki kurulumu bitir (`./setup/verify_all.sh` en sonda `(+) Tüm doğrulamalar geçti` demeli).
2. [`planlama/gelistirme_agaci.md`](planlama/gelistirme_agaci.md) dosyasından üzerinde çalışacağın **maddeyi** seç. Her maddenin altında "Bitti:" ile bir ölçüt yazar. İş, bu ölçüt sağlandığında biter.
3. Aynı maddeye başkası başlamasın diye ekibe haber ver.

## Adım adım

**1. Yeni bir dal aç** (`main` üzerinde çalışma)

```bash
git checkout main
git pull
git checkout -b ad/konu
```

Dal adı örnekleri: `mirac/b9-cikarim-iscisi`, `mikail/a1-sahne-ureticisi`. Başına adını, sonuna madde kimliğini ve kısa konuyu yaz. Türkçe karakter ve boşluk kullanma.

**2. İşi yap, küçük parçalar halinde commit et**

```bash
git add <değiştirdiğin dosyalar>
git commit -m "px4: görev yükleme eklendi (FR-7)"
```

Commit mesajı biçimi: `<alan>: kısa açıklama`. Alan: `setup`, `ağ`, `python`, `px4`, `ros`, `gazebo`, `docs`, `config`, `test`, `araclar`. Gereksinim numarası varsa sonuna `(FR-12)` ekle.

**3. PR'dan önce kontrol et**

```bash
./setup/verify_all.sh
./setup/lock_ozet.sh --check      # setup/ veya config/ değiştiyse önce ./setup/lock_ozet.sh çalıştır
python3 araclar/ilerleme.py --kontrol
```

Bir ağaç maddesini bitirdiysen maddeyi `[x]` yap ve `python3 araclar/ilerleme.py --yaz` çalıştır, değişen README'yi de commit et.

**4. Dalı gönder ve Pull Request aç**

```bash
git push -u origin ad/konu
```

GitHub'da repo sayfasında "Compare & pull request" düğmesine bas. Açılan şablondaki kutuları doldur.

**5. İnceleme ve birleştirme**

İşi proje sahibi inceler (PR'ı açan kişi kendi PR'ını **onaylayamaz**, başka biri onaylamalı). Not bırakırsa düzeltip aynı dala yeni commit at. Onaylanınca "Squash and merge" ile birleştirilir ve dal silinir. Sonra yerelde `git checkout main && git pull` yap.

## Kurallar

- **`main` GitHub'da korumalıdır:** doğrudan push, silme ve zorla push (force push) reddedilir. Her şey PR ile girer ve en az **1 onay** ister.
- **Bir PR = bir madde.** Küçük PR kolay incelenir.
- **Ölçüt sağlanmadan maddeyi işaretleme.** Yüzde, kanıttır.
- **Kilitli değerlere dokunma:** 25 Mbit/s ağ profili, çıkarım ayarları (güven 0,25, `nms=False`, `max_det` 300, FP32, batch=1), karar kuralları. Pilot sonrası kilitlenecek değerleri (ör. kuyruk sınırı) ancak ekipçe karar verilince değiştir.
- **Kilit dosyalarını elle düzenleme.** Python kilidi yalnız `--update-lock` ile güncellenir; ortam özeti `./setup/lock_ozet.sh` ile üretilir.
- **Sürüm numarası yalnız `setup/versions.env` içinde.**
- **Büyük dosya, model ağırlığı, veri kümesi, günlük ve şifre/token depoya girmez.** (`.gitignore` bunları dışarıda tutar.)
- **`docs/` içindeki kaynak belgeler değiştirilemez.**
- Dil Türkçe: yorum, log, commit, PR.

## Yapay zekâ asistanı (Claude Code gibi) ile çalışıyorsan

Depodaki [`CLAUDE.md`](CLAUDE.md) asistanın uyacağı kuralları içerir ve her oturumda kendiliğinden yüklenir. Önemli olanlar: sürücüye ve sisteme dokunmaz, `sudo` ve `git push` çalıştırmaz, kilitli değerleri değiştirmez. Kuruluma dokunan komutları ve `git push`'u sen kendi terminalinde çalıştırırsın. Asistanın yaptığı her değişiklik de aynı PR ve inceleme sürecinden geçer.

Kişisel ayarların (`.claude/settings.local.json`, `CLAUDE.local.md`) depoya girmez; `.gitignore` bunları dışarıda tutar.

## İstersen: yerel koruma (isteğe bağlı)

GitHub zaten `main`'e doğrudan push'u reddeder. Hatayı daha bilgisayarında, GitHub'a gitmeden görmek istersen tek seferlik aç:

```bash
git config core.hooksPath .githooks
```
