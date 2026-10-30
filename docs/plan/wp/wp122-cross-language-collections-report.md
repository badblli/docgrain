# WP122 — Cem uygulama notları

## Çalıştırılan kontroller

Son kodla depo kökünden, CI ile aynı sabitlenmiş sanal ortam kullanıldı:

```powershell
New-Item -ItemType Directory -Force .pytest_cache/wp122-tmp | Out-Null
$env:TEMP = (Resolve-Path .pytest_cache/wp122-tmp).Path
$env:TMP = $env:TEMP
& C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m pytest -q
& C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python -m ruff check .
git diff --check
```

Sonuç: **1674 passed, 159 skipped, 3 warnings** (190,34 saniye); Ruff
**All checks passed!**; diff kontrolü temiz. İlk denemede varsayılan Windows geçici
dizinine erişim reddedildiği için TEMP/TMP çalışma ağacındaki yok sayılan dizine
yönlendirildi. Uyarılar mevcut Starlette kullanımı ve iki büyük sentetik görüntü
testinden geliyor. 42 yeni test dahil ilgili üç modülde ayrıca 62 test geçti.
Docker içindeki Docling/EasyOCR/PostgreSQL/MinIO entegrasyonları ve canlı Markdown
yüklemesi burada doğrulanmadı.

## Neden ve tasarım

`group_units` ham başlıkları karşılaştırıyordu; İngilizce alan/liste anahtarları ancak
`structure_records` aşamasında üretiliyordu. Dolayısıyla aynı alanların çevirileri ve
aynı liste türünün farklı başlıkları hiçbir eşleşme sinyali üretmiyordu. Ayrı listelerde
kalan kayıtlar WP115 tarafından da karşılaştırılamıyordu.

`structure_vocab.py`, mevcut TR/EN sözlüğünü ve aynı kavramların sınırlı DE/RU
karşılıklarını paylaşır. Genel çeviri veya model çağrısı yoktur. Bilinen liste adı
başlığın sonundaysa tür belirlenir; birden fazla tür içeren başlıkta karar verilmez.
Uzun sözlük ifadeleri önceliklidir: `meeting rooms`, ayrıca `rooms` sayılmaz.

Gruplama için kimlik sütunu `name` sayılır; diğer alanlar sözlük anahtarıyla, yoksa
ham normalleştirilmiş etiketiyle karşılaştırılır. Bilinen eşit türler yeterli alan
benzerliği veya WP115 `place_names.name_keys` eşleşmesiyle birleşir. Bilinen farklı
türlerde otomatik birleşme ve yeni soru yoktur. Tür belirsizken yalnız alan benzerliği
varsa ya da bilinen eşit türlerde alan benzerliği zayıfsa mevcut `weak_overlap` sorusu
kullanılır. Eski aynı başlık/aynı öğe kuralları ve `would_bridge_collections` denetimi
korunur. Kaynak etiketleri/değerleri değiştirilmez. Birim ve çift imzaları hâlâ ham
etiketlerden hesaplanır; eski liste yanıtları geçerlidir.

Docling API/çıktısı: mevcut `DoclingDocument.export_to_dict()` çıktısındaki tablo
`table_cells`, `column_header` / `row_header`, öğe başvuruları ve kaynak konumları
kullanılır; ayrıştırıcı eklenmedi. Kurulu ortamda mevcut
`DoclingDocument.model_validate()` / `TableItem.export_to_dataframe()` yolu korunur.

## Mevcut çalışma alanları ve alan anahtarları

Mevcut TR/EN sözlük girdileri değiştirilmedi: özellikle `Mutfak → mutfak`,
`Cuisine → cuisine`, `Açılış saatleri → hours`, `Opening hours → hours` korunur.
DE/RU için aynı kavramın alanları da `hours`, `price` gibi anahtarlara düşer.
Önceden sözlükte olmayan DE/RU etiketlerinin çıktısı değişir: örneğin
`Öffnungszeiten` için `offnungszeiten → hours`, `Цена` için `value → price`.
Almanca `Tag` gibi başka bir dilde de anlamı olan kelimeler bu sınırlı sözlüğün
anlamını alır (`day`). Önceden bu tür etiketlerle kabul edilmiş alanlar için genel
anahtar taşıması/takma adı eklenmedi; eski revizyon korunur, sonraki iş yeni anahtarı üretir.

İncelenen yol: `records_pipeline.discover()` her işte yapıdan şema üretir;
`_structure_result()` kabul edilen şemanın alan anahtarlarına göre değerleri süzer.
`discovery.FIELD_SYNONYMS` yalnız `opening_hours → service_hours` ve
`max_occupancy → capacity` dönüşümlerini içerir; `mutfak → cuisine` geçişi veya genel
alan takma adı mekanizması yoktur. Böyle bir değişiklik yeni çıktıda eski alanı
başka bir alan yapar; eski alanı tüketen uygulamalar ve alan anahtarına bağlı
kararlar için güvenli bir taşıma sayılmaz. Bu nedenle yeni TR/EN eşanlamlı eklenmedi.
Arşivdeki eski `field_key` ile mevcut uygulama karşılaştırıldı: eski sözlüğün bütün
girdileri ve `Mutfak`, `Cuisine`, `Açılış saatleri`, `i18n`, `2026 Fiyatı` dahil
79 etiketin çıktısı aynı kaldı.
Bu WP ayrıca mevcut kayıt onaylarını çalıştırmalar arasında taşıyan bir mekanizma
eklemez; test edilen hatırlama, mevcut liste birleştirme yanıtlarıdır.

Çalışma zamanı `Key` / `CollectionKey` sözleşmesi ASCII ister. Bu yüzden Unicode
anahtar açmak yerine küçük ve sabit Rusça harf çevrimi seçildi:
`Условия → usloviya_items`, `Услуга → usluga`. Bilinen Rusça başlıklar doğrudan
İngilizce sözlük anahtarlarına gider. Eski revizyon dosyaları değişmez. Önceden ayrı
olan `a_la_carte_restaurants` gibi liste anahtarları sonraki işte `restaurants`
altında üretilebilir; genel eski anahtar göçü bu pakette yoktur.

## Liderin canlı kontrolü

Aşağıdaki komutlar lider içindir; Docker yeniden oluşturma ve gerçek Docling/servis
kontrolü bu çalışma kapsamında çalıştırılmadı. Birleştirme sonrası depo kökünde:

```powershell
docker compose up -d --build api worker web
Get-Content docs/examples/wp122/restaurants-tr.md
Get-Content docs/examples/wp122/restaurants-en.md
```

Yeni, yalnız sentetik belgelerin olduğu bir çalışma alanına bu iki `.md` dosyasını
yükleyin; belge hazırlığının tamamlanmasını bekleyin. Model kapalıyken bilgi işini
başlatın. API üzerinden iş başlatma/okuma örneği (`$workspaceId` kontrol alanının kimliği):

```powershell
$apiBase = 'http://localhost:8000/v1/workspaces/' + $workspaceId
$requestBody = @{ request_id = 'wp122-' + [guid]::NewGuid().ToString('N') } | ConvertTo-Json
$recordJob = Invoke-RestMethod -Method Post -Uri ($apiBase + '/record-jobs') -ContentType 'application/json' -Body $requestBody
Invoke-RestMethod -Uri ($apiBase + '/record-jobs/' + $recordJob.job_id)
Invoke-RestMethod -Uri ($apiBase + '/questions')
```

Beklenti: tek `restaurants` listesi, tek `hours` alanı, `mutfak` korunmuş; liste
birleştirme sorusu yok. `Balık restoran` / `Fish restaurant` tek kayıttır ve iki
belgeyi kaynak gösterir. İkinci kontrolde İngilizce dosyanın bir kopyasında saati
`19:00-23:00` yapıp ayrı temiz çalışma alanında aynı adımları tekrarlayın: yine tek
liste, iki aday kayıt ve tam bir `duplicate` sorusu beklenir. Çıktı anlamını ve iki
kaynağı inceleyin; yalnız işin `done` olması yeterli değildir.
