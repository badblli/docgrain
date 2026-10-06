# Şirket klasörünü tek seferde yükleme

Bir şirket bir çalışma alanıdır. Komut alt klasörlerdeki PDF, DOCX, XLSX, TXT,
PNG, JPG ve JPEG dosyalarını mevcut API üzerinden kaydeder, yükler, onaylar ve
işlem bitene kadar bekler. Diğer uzantıları ve sembolik bağlantıları nedenleriyle
raporlar. Kaynak metni talimat olarak çalıştırmaz; komut hiçbir modele çağrı yapmaz.

Kurulum (depo kökünde; mevcut bağımlılıkları kullanır):

```powershell
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m pip install --no-deps -e packages/ingestion
```

Çalışma alanı kimliği harf veya rakamla başlamalı; harf, rakam, `_` ve `-`
içerebilir. Dosya SHA-256 değeri aynı çalışma alanında mevcutsa belge ve dosya
sürümü yeniden kullanılır; farklı adlar da aynı belgeye gider. Başka çalışma
alanındaki aynı içerik ayrı belge oluşturur. Eşzamanlı kayıt istekleri PostgreSQL
kilidiyle sıralanır. Kayıttan/yüklemeden sonra kesilen komut aynı belge üzerinden
devam eder; başarısız iş otomatik yeniden işlenmez.

Yeni kaynaklar `uploads/<workspace>/<document>/<version>/original` altında
tutulur; eski kaynak yolları okunmaya devam eder. İşleyici kayıtlı kaynak yolunu
kullanır. Türetilmiş dosyalar mevcut benzersiz belge/sürüm yollarını korur.
Listeleme: `GET /v1/documents?workspace_id=ws_company_a` (filtre sayfalamadan önce
uygulanır). Bu çalışma alanı desteğidir; kimlik doğrulama veya yetkilendirme değildir.

Dört şirketi dört çalışma alanına yüklemek için aşağıdaki komutları kullanın.
`C:/company-bundles/company-a` … `company-d` gerçek şirket klasörlerinin yerine
kullanılan nötr örnek yollardır; bunları yerel klasör yollarıyla değiştirin.

```powershell
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/docgrain.exe ingest-folder C:/company-bundles/company-a --workspace ws_company_a --api http://localhost:8000 --report .lead/bundles/company-a.json
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/docgrain.exe ingest-folder C:/company-bundles/company-b --workspace ws_company_b --api http://localhost:8000 --report .lead/bundles/company-b.json
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/docgrain.exe ingest-folder C:/company-bundles/company-c --workspace ws_company_c --api http://localhost:8000 --report .lead/bundles/company-c.json
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/docgrain.exe ingest-folder C:/company-bundles/company-d --workspace ws_company_d --api http://localhost:8000 --report .lead/bundles/company-d.json
```

Kurulum yapmadan çalıştırmak için:

```powershell
$env:PYTHONPATH = 'packages/ingestion;packages/domain'
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m docgrain_ingest ingest-folder C:/company-bundles/company-a --workspace ws_company_a --api http://localhost:8000 --report .lead/bundles/company-a.json
```

Varsayılan API `http://localhost:8000`; rapor `bundle-<workspace>.json` olarak
geçerli dizine yazılır. `--report` ile Git dışında veya `.lead/` altında tutun;
rapor dosya adlarını ve işleyicinin sorun açıklamalarını içerebilir. Rapor her
dosyadan sonra güncellenir ve seçilen rapor dosyası klasör taramasına alınmaz.
Her satır göreli dosya yolu, SHA-256, belge/sürüm/iş kimlikleri, tekrar kullanım,
durum, sayfa sayısı ve sorunları içerir. `pages: null`, sayfa sayısının alınamadığı
anlamına gelir. DOCX/XLSX/TXT için sayı işleyicinin kaynak konumlarıdır; basılı
sayfa doğruluğu iddiası değildir. `done` içeriğin anlamının doğrulandığını göstermez.

`--timeout 600` her dosya için en fazla 600 saniye işlem bekler;
`--poll-interval 1` durum kontrol aralığıdır. Ağ isteği sınırı 60 saniyedir.
`partial`, `failed`, `timeout` veya yükleme hatası varsa çıkış kodu 1 olur; kalan
dosyalar denenir. Sadece tamamlanan ve atlanan dosyalar varsa çıkış kodu 0 olur.
Zaman aşımı işi iptal etmez; aynı komutla mevcut iş yeniden gözlenebilir.

## Sentetik uçtan uca doğrulama

Gerçek şirket dosyası kullanmadan API, PostgreSQL, MinIO ve Docker işleyicisini
doğrular. Docker ortamının standart yerel ayarlarla hazırlanmış olması gerekir.
Bulut model çağrıları kapalı, canonical persistence açık olmalıdır.

```powershell
$env:USE_FIXTURES = 'false'
$env:CANONICAL_PERSISTENCE_ENABLED = 'true'
$env:DOCGRAIN_REMOTE_VISION_ENABLED = 'false'
$env:GEMINI_API_KEY = ''
docker compose up -d --build api worker
$env:DOCGRAIN_BUNDLE_API_URL = 'http://localhost:8000'
C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m pytest -q tests/integration/test_bundle_ingest_api.py --basetemp=.pytest_cache/wp50-live
Remove-Item Env:DOCGRAIN_BUNDLE_API_URL
```

Test iki aynı sentetik TXT dosyasını iki kez yükler; tek belge, aynı kimlikler,
doğru çalışma alanı, kaynak yolu, tamamlanan işlem ve en az bir kaynak konumu
arar. Her çalışmada benzersiz `ws_bundle_test_*` alanı oluşturur ve yerel test
veritabanında bırakır. `DOCGRAIN_BUNDLE_API_URL` verilmezse ağ çağrısı yapmadan
atlanır. Docling/EasyOCR bağımlılıkları Docker işleyici imajındadır.
