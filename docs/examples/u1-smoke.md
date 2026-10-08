# U1 tekrar edilebilir yürüyüş (WP101)

Betik yalnız sentetik `tests/fixtures/u1-company/` belgelerini yükler. `golden.json` ve README
yüklenmez. Gerçek `ingest_folder` kullanılır; dosya özetleri doğruluk anahtarıyla karşılaştırılır.
Model kapalıyken iki işlemin 409 dönmesi, kayıt işinin yayına ulaşması, tek 32/36 m² çelişkisi,
soruların 32 seçilerek çözülmesi ve onaylı yayındaki beş kritik alanın değerleri/kaynakları ölçülür.
Oda sorusu kaynaklı 32 ve 2 yanıtını gerektirir. Helikopter pisti ve doğruluk anahtarındaki 2035
fiyatı soruları `Bilmiyorum.`, `abstained: true` ve boş kaynak listesi gerektirir.
Belgedeki talimat benzeri satır da değiştirilmeden yüklenir; doğru oda büyüklüğü 32 kalmalıdır.

Varsayılan çalışma ağsızdır. Sahte API `httpx.MockTransport`, gerçek istek şemaları ve gerçek
özet/soru/yanıt/yayın işlevlerini kullanır; belge ayrıştırıcısının veya modelin doğruluğunu ölçmez.
Kaynak konumları gerçek ayrıştırıcının verdiği `locator` ile gösterilir. TXT anahtarındaki satır
konumlarıyla bire bir eşitlik aranmaz; alıntının doğru kaynak dosyada gerçekten bulunması aranır.
Keşfin alan adları değişebildiği için beş alan, beklenen değerleri ve kaynak alıntılarıyla eşleştirilir.

```powershell
& C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -X utf8 docs/examples/u1_smoke.py --fake --out storage/u1-smoke-fake
```

## Lider için canlı komut

Canlı API, worker, PostgreSQL, MinIO ve sunucuda hazır bir bağlantı profili gerekir.
`DOCGRAIN_U1_CREDENTIAL_ID`, `/v1/workspaces/{ws}/model/profiles` yanıtındaki hazır profilin
kimliğidir. `DOCGRAIN_U1_BASE_URL` seçilen OpenAI uyumlu adres, `DOCGRAIN_U1_MODEL` model adıdır.
Bu değişkenler anahtar içermez; betik anahtar okumaz. Anahtar yönetimi sunucudadır.
Canlı çalışma yeni bir sentetik çalışma alanı oluşturur ve model açıkken sentetik içerik gönderir.

Depo kökünde, bu üç değişken seçilmişken liderin çalıştıracağı tam komut:

```powershell
& C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -X utf8 docs/examples/u1_smoke.py --live --api http://localhost:8000 --credential-id "$env:DOCGRAIN_U1_CREDENTIAL_ID" --base-url "$env:DOCGRAIN_U1_BASE_URL" --model "$env:DOCGRAIN_U1_MODEL" --timeout 600 --poll-interval 1 --out storage/u1-smoke-live
```

Her adım için Türkçe geçer/kalır/engellendi satırı ve süre yazılır. `--out` altında
`report.json`, `report.md` ve yükleme ayrıntıları için `ingest-report.json` oluşur.
Bir adım kalırsa sonraki adımlar engellendi olarak raporlanır; rapor basıldıktan sonra çıkış kodu
1 olur. `failed`, `needs_review` veya zaman aşımı başarı sayılmaz. Doğru çalışmada çıkış kodu 0'dır.
`--timeout` yüklemede dosya başına, kayıt işinde işin tamamı için geçerlidir.

Canlı pytest testi yalnız `DOCGRAIN_U1_SMOKE_LIVE=1` ile açılır. Diğer dört ayar da zorunludur:

```powershell
$env:DOCGRAIN_U1_SMOKE_LIVE = "1"
$env:DOCGRAIN_U1_API = "http://localhost:8000"
& C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m pytest -q tests/integration/test_u1_smoke_live.py
```

Normal `pytest` çalışmasında canlı test atlanır. Canlı ölçüm, Docker içindeki gerçek ayrıştırıcı ve
servisler ile ayrıca çalıştırılmalıdır; ağsız testin geçmesi canlı akışın geçtiğini göstermez.
