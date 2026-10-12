# WP113 — hız ve doğruluk ölçümü

Gerçek modele bu çalışma ağacında çağrı yapılmadı. Bir gerçek şirketin süre tablosu ve
bağımsız alan anahtarı karşılaştırması lead tarafından çalıştırılacak. Sayılar tahmin edilmedi.

İlk ölçümde mevcut çıkarım planı ve Dene metin yanıtı korunur. Model ayarlarında
`reasoning_effort` ve `max_tokens` boşsa isteğe gönderilmez; sağlayıcının varsayılanı değişmez.
Çalışma alanı API'sinde bu iki alan nullable'dır. Anahtarlar yine yalnızca sunucudaki hazır
bağlantı profilinden çözülür; Ayarlar'a veya iş kuyruğuna yazılmaz.

## Sağlayıcı seçenekleri

[Gemini'nin resmi OpenAI uyumluluk belgesi](https://ai.google.dev/gemini-api/docs/openai)
12 Ekim 2026 tarihinde kontrol edildi. Belgede `minimal`, `low`, `medium`, `high` eşlemesi var;
`none` yalnızca destekleyen Gemini 2.5 modellerinde düşünmeyi kapatır. Gemini 2.5 Pro ve
Gemini 3'te kapatılamaz. Doğrudan Google bağlantısında bu modeller için `none` API tarafından
reddedilir. Diğer uyumlu bağlantılarda seçilen değer olduğu gibi gönderilir; desteklenmezse
başka düzeye sessizce çevrilmez. Betik desteklenmeyen seçenekleri başarısız olarak raporlar.
Modelin adı ve sağlayıcı desteği lead tarafından gerçek bağlantıda doğrulanmalıdır.

## Lead'in gerçek model komutları

PowerShell; gerçek şirket soru anahtarı Git dışında tutulmalı. Soru dosyası WP112 formatında
tekil (`known`), tüm öğeleri isimleriyle belirten liste (`list`) ve bilinmeyen (`unknown`)
soruları içermeli. `SPEED_MODEL_KEY` sunucu ortamında hazırlanmış anahtar değişkeninin
örnek adıdır; değeri komuta veya rapora yazılmaz.

```powershell
$py = 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python'
& $py benchmarks/speed.py --enable-model --api-url http://localhost:8000 `
  --workspace WORKSPACE_ID --revision REVISION_ID `
  --base-url MODEL_BASE_URL --model MODEL_NAME --api-key-env SPEED_MODEL_KEY `
  --questions C:/private/demo-questions.json --repetitions 5 `
  --efforts default none low medium --concurrency 6 > C:/private/speed-report.json
```

`baseline`: düşünme/uzunluk ayarı gönderilmez, eski plan ve metin listesi kullanılır.
`default`: aynı model ayarı, birleşik plan ve sunucuda liste.
`none/low/medium`: birleşik plan ve sunucuda liste, belirtilen düşünme düzeyi.
İsteğe bağlı `--max-tokens 16384` yalnızca adaylara uygulanır. Her soru yeni model geçmişiyle
başlar; bütün seçenekler aynı onaylı yayın sürümüne sabitlenir. Betik kayıtlı modeli veya
ayarları değiştirmez. Anahtarsız yerel profilde `--api-key-env` verilmez.

Rapor p50/p95 süreleri, fiziksel çağrı sürelerini, tokenları, tekrar denemeleri ve eksik kullanım
bildirimi sayılarını verir. Dene WP112 puanlayıcısını kullanır. Sentetik çıkarım anahtarı
betikte sabittir, modelin çıktısından türetilmez: Garden room (2 kişi, 32 m²), Indoor pool
(pool, 08:00–20:00), Pets (Pets are not allowed.). Eksik alan, fazladan alan, yinelenen kayıt,
reddedilen alan ve başarısız bölüm ayrı raporlanır. Başarısız/doğrulanmamış seçenek yeşil
sonuca dönüşmez; çıkış kodu 1'dir. Sentetik kapılar geçse de gerçek bağımsız anahtar durumu
`not_verified` kalır.

## Gerçek şirketin aşama tablosu

Önce mevcut varsayılanlarla “Bilgileri çıkar” çalıştırın. İşin GET yanıtında `speed` bulunur;
aynı ölçümler işin `metadata.speed` alanında saklanır. Model içerikleri, belge metinleri ve
anahtarlar bu ölçümlerde bulunmaz. Sağlayıcı token bildirmediyse toplam `null`, eksik çağrı
sayısı ayrıca kayıtlıdır; bilinmeyen kullanım sıfır sayılmaz. Paralel istek sürelerinin toplamı
gerçek aşama süresi değildir; tabloda aşamanın duvar süresi kullanılır.

```powershell
Invoke-RestMethod 'http://localhost:8000/v1/workspaces/WORKSPACE_ID/record-jobs/JOB_ID' |
  ConvertTo-Json -Depth 30 | Set-Content -Encoding utf8 C:/private/demo-job.json
& $py benchmarks/speed.py --job-report C:/private/demo-job.json > C:/private/demo-stage-table.md
```

| Aşama | Gerçek ölçüm |
| --- | --- |
| Listeleri bul | Lead çalıştıracak |
| Yapıyı kontrol et | Lead çalıştıracak |
| Bilgileri çıkar | Lead çalıştıracak |
| Karşılaştır | Lead çalıştıracak |
| Birleştir | Lead çalıştıracak |
| Yayınla | Lead çalıştıracak |

## Doğruluk kapısı ve devreye alma

`RECORDS_EXTRACTION_CONCURRENCY` varsayılanı 6, aralığı 1–32. 429/5xx çağrıları mevcut
sınırlı üstel beklemeyle tekrar denenir. Kayıt ve çağrı sırası bölüm/plan sırasına göre kalır;
süre ölçümleri doğal olarak her koşuda farklıdır. `RECORDS_EXTRACTION_GROUPED_PASSES=false`
ve `DENE_SERVER_LISTS=false` varsayılanları gerçek doğruluk kıyaslamasını bekler.

Seçilen ayarla bir gerçek şirketi ayrı çalışma alanında yeniden çıkarıp aşağıdaki bağımsız
anahtara karşı hem önceki hem yeni `records.json` dosyalarını puanlayın:

```powershell
& $py -m docgrain_eval.record_golden score --manifest C:/private/company-manifest.json `
  --golden C:/private/independent-record-key.json --questions C:/private/independent-questions.json `
  --records C:/private/chosen/records.json --context DOCUMENT_ID=C:/private/context.md `
  --out C:/private/chosen-field-score.json
```

Yeni sonuçta alan doğruluğu en fazla 1 puan düşebilir; desteklenmeyen alan sıfır olmalı.
Dene'de uydurulan kayıt/kaynak ve bilinmeyene cevap sıfır olmalı; bilinen sorularda doğru,
kaynaklı cevap sayısı düşmemeli. Bu kapılardan sonra lead seçilen çalışma alanının düşünme
ayarını kaydedebilir ve ilgili süreçlerde `RECORDS_EXTRACTION_GROUPED_PASSES=true`,
`DENE_SERVER_LISTS=true` açabilir. Varsayılan değişiklik kararı bu WP'de otomatik verilmez.

Önceki uygulamaların tam kopyaları karar 18 gereği
`apps/worker/docgrain_worker/unused/wp113/` altında tutulur; içe aktarılmaz.
