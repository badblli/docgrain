# Büyük görseller ve yarım kalan belge işleri

WP105, kaynak dosyayı değiştirmeden okuma girdisini sınırlar. PNG/JPEG, EXIF
dönüşümünden ve beyaz zemin birleştirmesinden önce Lanczos ile küçültülür; JPEG
için azaltılmış çözünürlüklü decode kullanılır. Özgün baytlar ayrı tutulur.
`image_preparation` özgün/kullanılan boyutları, eksen ölçeklerini ve özeti saklar.
`image_downscaled` okuma raporunda görünür. Normalize kutular özgün kodlanmış
görseli adresler; küçültme, yuvarlama ve EXIF dönüşümü birlikte geri eşlenir.

Docling'in OCR modeli her sayfa için kendi render ölçeğiyle sınırlandırılır. PNG/JPEG
girdide bu sınır, Docling'in 3 kat OCR büyütmesini kaynağın piksel sayısının altına
indirmediği sürece okuma raporuna `image_downscaled` yazmaz (ör. 12 MP telefon
fotoğrafı); kayıt yalnızca `raster_preparation` metadata'sında kalır.
Render ve Docling'in kutu geri dönüşümü aynı ölçeği kullanır. Üretilen sayfa ve
resim görsellerinin ölçeği de dönüşümden önce sınırlandırılır. Fiziksel boyutu
çok büyük PDF sayfaları ayrıca geçici PDF içinde küçültülür; metin ve vektörler
korunur. Bu sayfaların kanonik metin, tablo hücresi ve OCR kutuları özgün PDF'nin
görünür sayfa alanına geri eşlenir. Geçici PDF'den üretilen ham Docling JSON'u
kendi girdi koordinatlarını korur; `pdf_preparation` eşlemesi kanonik metadata
ve işleme seçeneklerinde saklanır.

Parçalara bölme uygulanmadı. Örtüşen parçalarda yinelenen metin ve bölünen
tabloların birleştirilmesi ayrıca doğruluk ölçümü gerektirir. Küçültme yetersiz
kalırsa iş sınırlandırılmış süreçte başarısız olur; ana worker devam eder.
Bilinen sınır: Docling'in tablo modeli tablo bulunan sayfayı kendi 2 kat ölçeğiyle
render eder (6.000 px girdide yaklaşık 77 MP); bu bellek alt süreç sınırı içinde kalır.

## Ayarlar

| Ortam değişkeni | Varsayılan | Anlamı |
| --- | --- | --- |
| `DOCGRAIN_IMAGE_MAX_SIDE` | `6000` | En uzun raster kenarı, piksel |
| `DOCGRAIN_IMAGE_MAX_PIXELS` | `40000000` | Raster başına toplam piksel |
| `DOCGRAIN_CONVERSION_MEMORY_MB` | `4096` | Alt süreç bellek sınırı |
| `DOCGRAIN_CONVERSION_TIMEOUT_SECONDS` | `600` | Doğrulama ve dönüşüm süresi |
| `DOCGRAIN_JOB_STALE_SECONDS` | `900` | İlerlemesiz işin kurtarma eşiği |
| `DOCGRAIN_JOB_RECOVERY_INTERVAL_SECONDS` | `60` | Kurtarma taraması aralığı |

Compose worker `env_file` üzerinden bu ayarları alır. Yeni ağ/model çağrısı yoktur.
Linux'ta `RLIMIT_DATA`, Windows'ta Job Object kullanılır. `RLIMIT_AS` seçilmedi:
Torch/ONNX/OpenMP büyük sanal adres alanı ayırır ve sıradan dönüşümleri de
durdururdu. Linux'ta alt süreç ayrıca `oom_score_adj=1000` alır; makinenin belleği
yine biterse çekirdek ana worker'ı değil bu alt süreci kapatır. Linux'ta sınırlı
cgroup belleğinin mevcut kullanımı düşüldükten sonra worker için ayrıca 256 MiB
ayrılır. Linux dönüşümü ayrı süreç grubundadır; zaman aşımında OCR alt süreçleri
de kapatılır. Windows Job Object OCR alt süreçlerini de kapsar.

Belge doğrulama/decode ve Docling dönüşümü her iş için yeni `spawn` sürecindedir.
Ana sürece taşınan sonuç alt süreç sınırının dörtte biriyle sınırlıdır (varsayılan
1 GiB); çok sayfalı dev sonuçlar ana worker'ı şişiremez. Çıkış/çökme/bellek veya
süre sınırı `failed` + `worker_crash` üretir. Alt süreçteki sıradan hatalar (biçim
uyuşmazlığı, bozuk dosya, ayrıştırıcı hatası) çökme sayılmaz: önceki gibi kendi
mesajıyla `failed` olur. Çalışan dönüşüm sırasında deneme kimliği en fazla 30
saniyede bir denetlenir. `DOCGRAIN_CONVERSION_TIMEOUT_SECONDS`,
`DOCGRAIN_JOB_STALE_SECONDS` değerinden küçük kalmalıdır; değilse worker
başlangıçta uyarı yazar. Depolama ve
kanonik yayın ana worker'da kalır. Bu işlemlerde beklenmedik worker ölümü takılı iş
kurtarma yoluyla ele alınır. İlerleme, kaynak doğrulaması öncesinde/sonrasında ve
yayına geçişte kaydedilir; yalnızca sürecin yaşaması ilerleme sayılmaz.

Başlangıçta ve periyodik olarak eski `running` işleri satır kilidiyle taranır:
ilkinde aynı iş yeniden kuyruğa alınır, ikincisinde `failed` + `worker_stale` olur.
Eski worker kayıtları `started_at`/`queued_at` ile değerlendirilir. Redis gönderimi
başarısız olursa kurtarılan `queued` iş sonraki taramada tekrar gönderilir. Henüz
yükleme onayı verilmemiş yeni kayıtlar otomatik kuyruğa eklenmez. Deneme kimliği
eski sürecin ilerleme veya sonuç durumunu yeni denemenin üzerine yazmasını önler.
Veritabanındaki ek kolonlar API/worker başlangıcında idempotent olarak eklenir.

## Lead canlı kontrol komutları

Host, depo venv'i:

```powershell
$env:TMP = Join-Path (Get-Location) '.pytest_cache/runtime'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force $env:TMP | Out-Null
& C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m pytest -q --basetemp .pytest_cache/wp105-suite
& C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m ruff check apps packages tests benchmarks docs/examples
```

Gerçek Docling/OCR, büyük görsel ve izole PostgreSQL kontrolleri worker image içinde:

```sh
docker compose build worker
docker compose run --rm -v "$PWD/tests:/srv/tests:ro" -v "$PWD/pytest.ini:/srv/pytest.ini:ro" -e DOCGRAIN_M1_TEST_DATABASE_URL -e GEMINI_API_KEY= -e DOCGRAIN_REMOTE_VISION_ENABLED=false worker sh -c 'python -m pip install "pytest>=8" && python -m pytest -q tests/integration/test_worker_resilience_live.py'
```

PostgreSQL testi yalnızca kendisinin oluşturduğu rastgele şemayı kullanır ve
temizler; mevcut geliştirme işleri üzerinde yazma yapmaz. Test görselleri çalışma
sırasında üretilir, depoya ikili dosya eklenmez. Başarılı iş veya geçerli JSON,
OCR anlam doğruluğunun kanıtı değildir; gerçek görsel testi bilinen yazıyı ve
bağımsız konum aralığını da doğrular.
