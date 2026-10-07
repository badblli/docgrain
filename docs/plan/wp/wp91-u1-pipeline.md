# wp91-u1-pipeline — Web'den başlayan kalıcı bilgi çıkarma işi

- Özet: Bilgileri çıkar düğmesi mevcut keşif, çıkarım, birleştirme ve yayın adımlarını arka planda çalıştırsın; ilerleme ve onay bekleyen bilgiler web'de görünsün.
- Model: derin
- Engine: codex
- Phase: U1
- Branch: `codex/wp91-u1-pipeline` (base: `origin/dev`)
- Depends on: wp92-u1-settings runtime sözleşmesi; Docker entegrasyonunda wp94-u1-try
- Role: implementer
- Owner: Porygon (codex) — second attempt; Alakazam's first (agy) attempt was rejected

## Goal

Liderin elle `docgrain-records`/publish komutları çalıştırması yerine kullanıcı tek iş başlatsın.
Tam kaynaklı önizleme yayınlansın; insanın onaylayabileceği sorular oluşsun. U1 A7–A14 kapsamı.

## Scope

- In: aşağıdaki dosyalarda yeni kayıt işi ve mevcut worker/yayın entegrasyonu.
- Out: yeni çıkarıcı, vendor istemcisi, model eşleştirme yargıcı, wp69 hız refaktörü, şema editörü,
  genel kuyruk kurtarma, D3/D6, web, boş şirket/model ayarı implementasyonu.

## File ownership

- `apps/api/docgrain_api/main.py`
- `apps/api/docgrain_api/records_jobs.py`
- `apps/api/docgrain_api/records_jobs_repository.py`
- `apps/api/docgrain_api/routers/record_jobs.py`
- `apps/api/docgrain_api/records_repository.py`
- `apps/api/docgrain_api/routers/records.py`
- `apps/worker/docgrain_worker/main.py`
- `apps/worker/docgrain_worker/records_pipeline.py`
- `apps/api/Dockerfile`
- `apps/worker/Dockerfile`
- `docker-compose.yml`
- `tests/unit/test_u1_pipeline.py`
- `tests/integration/test_u1_pipeline.py`

Başka dosyaya yazma. WP92 `settings.py/repository.py/documents.py`, WP94 `ai.py` sahibidir.
`packages/records/` mevcut fonksiyonları yalnız kullan; ihtiyaç varsa lidere bildir.

## Tasks

1. [U1 sözleşmesini](../U1.md) uygula: record-jobs POST/latest/detail uçları; Postgres'te kalıcı iş,
   altı aşama, zamanlar, kaynak/ayar pinleri ve sır içermeyen hata kodları. `202` yalnız kayıt ve
   kuyruk dispatch yapar. Ayrı `docgrain:records` Redis kuyruğu; mevcut belge işini koru.
2. Aynı şirkete tek etkin iş ve request_id tekrarında aynı iş. Live/demo, boş/hazır olmayan/kısmi
   belge, kapalı/eksik model guard'ları API + worker'da. `resolve_workspace_model` sürümünü sabitle;
   etkinlik sonradan kapatılırsa yeni model çağrısına geçme. Anahtarları global env'e yazma.
3. `discovery_cli/discovery`, `discovery_store.accept_schema`, `extractor`, `match/match_merge/merge`
   fonksiyonlarıyla CLI'nin mevcut sırasını yürüt. Yerel normalize kaynakları sabitle; schema.sources,
   source.json ve context.md sidecar'larını özel runtime deposunda tut. Shell komutu üretme.
4. Şemada her tutulan alanın doğrulanmış tipli örneği/alıntısı, sabit kaynak hash'i ve çelişkisiz tipi
   olsun. Kabul kararını `rule:u1-verified-schema` ve gerekçeyle iş metadata'sına kaydet; mevcut
   accept_schema kontrollerini gevşetme. Alternatif/eksik örnek varsa `needs_review` ile dur,
   şemayı sessizce budayarak veya sabit hospitality şemasına geçerek başarılı gösterme.
5. Eşleştirmede mevcut deterministik `auto-accept strong` **kimlik** kurallarını kullan; model yargıcı
   kapalı. Kimlik kabulü alan kabulü değildir. Merge'deki onaylanmamış tek adayları `needs_review`
   yap ve audit kaydına gerekçesini koy; böylece mevcut Sorular onları sorar. Alanları `accepted`
   yapma. Gerçek çelişkileri, çoklu değer/program/tekrar kayıt kurallarını koru.
6. `RecordsRepository.stage/publish` ve ortak workspace kilidini kullan; preview/approved
   aynı revision'dan üretilsin. İş başlangıcındaki kaynak ve yayın başını publish öncesi tekrar kontrol et.
   Mevcut yayında kabul edilmiş alan varsa yeni çıkarma U1'de `409`: onayları taşıma/silme yapma.
   Henüz onaysız yeniden koşuda da araya giren cevap/yayın CAS ile korunur. Sorular cevap endpointi
   aktif iş sırasında `409` verir; yarış kontrolü aynı kilitte yapılır. Eski revision byte'ları korunur.
7. Kısmi çıkarım/failures, sıfır koleksiyon/kayıt, stage timeout, publish arızası `done` olamaz.
   Sınırlı aşama timeout ve heartbeat/stale algılama ile ölmüş işin terminal hatası görünür olsun;
   normal GET yeni model isteği yapmasın. Hata önceki yayın başını bozmaz. Otomatik replay yok.
8. Compose'da API/worker için ortak rw records kökü ve worker'ın `http://api:8000` iç adresini bağla.
   WP92'nin sunucu anahtar profil sözleşmesini iki servise geçir; varsayılan boş/kapalı. WP94'ün
   mevcut `packages/access` paketini gereken API/worker imajlarına COPY ve yerel editable install ile
   ekle; sürüm yükseltme/dependency ekleme yok. İmajlar lider tarafından build edilir.

## Tests

Repo kökünde, kurulum/ağ/model çağrısı olmadan:

```powershell
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m pytest -q tests/unit/test_u1_pipeline.py tests/unit/test_review_api.py tests/unit/test_review_decisions.py tests/unit/test_records_api.py -p no:cacheprovider
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m ruff check apps/api apps/worker tests/unit/test_u1_pipeline.py tests/integration/test_u1_pipeline.py
```

Sahte model/queue/store ile sıra, opt-in, çift başlatma, kaynak/ayar değişimi, review görünürlüğü,
publish failure, approved filtreleri ve stale worker testleri. Lider worker Docker test ortamında
`python -m pytest -q tests/integration/test_u1_pipeline.py` çalıştırır; gerçek Postgres/Redis/MinIO
ile kayıt → worker → publication read ve önceki yayının korunmasını ölçer. Ağ gerekiyorsa ajan koşmaz.

## Acceptance criteria

- [ ] Kapalı/boş/hazırlanmamış/kısmi şirket `409`, fake model sayacı 0; demo yazmaları `409`.
- [ ] Aynı şirkette iki eşzamanlı başlatma tek iş üretir; kalıcı GET aynı job/stage'ı döndürür.
- [ ] Sahte modelle altı aşama sırası doğrulanır; belirsiz şema, eksik çıkarım, boş sonuç başarılı değildir.
- [ ] Tek aday `needs_review` Sorular'da görünür; çelişki kabul edilmez, approved'a sızmaz.
- [ ] Cevap yeni onaylı publication üretir; işi yeniden başlatmak onaylı eski alanları silemez.
- [ ] Kaynak/ayar/publish başı değişimi, timeout/ölü worker ve disk hatası eski yayını korur;
      terminal sade hata görünür, GET model çağırmaz. Sır/log sızıntısı testi geçer.
- [ ] Docker entegrasyonu ortak kökten yayını okur; hangi testlerin çalıştırılamadığı açık raporlanır.

## Notes

Oku: AGENTS.md, ROADMAP, [U1](../U1.md), wp47/wp51/wp52/wp59/wp68,
`packages/records/README.md`, `docs/examples/records-read.md`.
Merge sırası WP92 → WP94 → **WP91** → WP93 → WP95. Ürün kodu dışında ek refaktör yok.

## Lead review of attempt 1 (2026-10-07) — read before you start

Attempt 1 was rejected: `records_pipeline.py` imported names that do not exist (`extract_workspace`,
`WorkspaceMatcher`, `ChatSession`, `merge_collection` with another meaning), kept a stub
`resolve_workspace_model` in `settings.py` that always returned "disabled", invented a
`DOCGRAIN_MODEL_PROFILES_DIR` setting, copied raw exception text into job messages, and its tests asserted
nothing (conditional asserts, an empty integration test). Start from `origin/dev`; do not reuse it.

Facts on dev now:
- WP92 is merged: use `docgrain_api.workspace_settings.resolve_workspace_model(ws, expected_version)`
  (returns `ResolvedWorkspaceModel`, raises `ModelSettingsError` with a public message and `status_code`).
  Credentials come from `DOCGRAIN_MODEL_CREDENTIAL_PROFILES`; pass that variable and the profile key
  variables to the worker in Compose. Never put the key in Redis, the DB, logs or job messages.
- WP94 is merged: `packages/access` already exists; the API image needs it (keep that Dockerfile change).
- The proven step sequence is the CLI in `packages/records/docgrain_records/cli.py` and
  `discovery_cli.py` — reuse those functions (`run_discovery`/`load_workspace_documents`,
  `extract`/`extraction_plan`, the `match` module, `merge_matches`, `export.load_revision`,
  `RecordsRepository.publish`). The lead runs today, per workspace:
  1. `discover` → `schema.proposed.json`; review; `accept-schema --proposal … --out <schema dir>`
  2. per document: `extract --document <id> --schema <schema> --api <api> --out <records>/<doc>`
  3. `match --records <records> --schema <schema> --out <match> --auto-accept strong`
  4. `merge --records <records> --schema <schema> --matches <match>/match_proposals.json --out <merged>
     --workspace <ws> --auto-accept strong`
  5. `RecordsRepository(root).publish(load_revision(<merged>/merge_revision.json))`
  Call the same Python functions in-process (or the module CLI via subprocess) — do not reimplement them.
- Before you import a name, grep that it exists. Job messages are fixed Turkish strings; error details go
  to a server log without secrets.
- Tests must assert real behavior with fake model transports (no network): job states and stages, one job
  per workspace under concurrent starts, model off → 409 with zero model calls, a synthetic two-document
  run that reaches `done` and publishes a revision, a failing step → `failed` with a fixed message.
  Name the integration test `tests/integration/test_u1_pipeline_live.py` (unique basename).
