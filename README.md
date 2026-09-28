# Docgrain

**Belgelerden yapılandırılmış, izlenebilir ve yeniden kullanılabilir bilgi üreten document-to-knowledge engine.**

Docgrain genel amaçlıdır. LUWI gelecekteki tüketicilerinden biridir; core içinde turizm veya LUWI business logic bulunmaz.

## Ürün yönü ve mevcut durum

Hedef mimaride **canonical structured knowledge kaynak doğrusudur**. Markdown, chunks, embeddings ve uygulamaya özel görünümler bu modelden türetilir. Orijinal belgeler ve ham extraction sonuçları kanıt olarak korunur. Core schema ile kullanıcı/domain JSON Schema ayrı kalır.

**Durum: pre-alpha / M1 canonical foundation.** Canonical v0.1 contract, JSON Schema ve bağımsız persistence repository eklendi; live ingestion bunları henüz üretmez veya kullanmaz.

| Alan | Bugünkü implementasyon |
| --- | --- |
| Ingestion | PDF kaydı → API upload proxy → MinIO → confirmation → Redis → worker |
| Rendering | PyMuPDF ile PDF sayfaları, 200 DPI PNG |
| Extraction | Gemini key varsa tüm sayfalarda Gemini; yoksa OCR kapalı Docling |
| Çıktılar | Provider-specific `document.json`, `document.md`, `pages.json`, page PNG; Gemini yolunda başarılı sayfa JSON dosyaları |
| Metadata | PostgreSQL document/version/job kayıtları |
| Kısmi hata | Bazı extraction hataları page failure olarak kaydedilir; bu recovery garantisi değildir |
| Console | API kayıtları, page render, doküman düzeyinde extraction Markdown; açık demo modu |
| Canonical foundation | Ayrı Pydantic v0.1 model, generated JSON Schema, sentetik örnekler ve opt-in PostgreSQL repository; henüz live pipeline'a bağlı değil |
| Henüz yok | Canonical mapping/publication, reconciliation, normalization, processing manifest, gerçek table/asset catalog, chunking, embedding, indexing, Structured Knowledge Patch, stage retry, crash recovery |

`document.json` içeriği kullanılan parser'a bağlıdır; canonical knowledge sözleşmesi değildir. `pages.json` yalnızca render boyutlarını içerir; processing manifest değildir. Job `done`, mevcut extraction yolunun tamamlandığını ifade eder; hedef pipeline'ın tamamlandığı anlamına gelmez.

## Sabitlenen ilk format scope'u

**PDF, DOCX, TXT, XLSX.** Şu an live ingestion yalnızca PDF kabul eder. DOCX/TXT/XLSX sonraki structural parsing çalışmasına aittir ve API bunları şimdilik `415` ile reddeder. PPTX, HTML ve bağımsız image ingestion ilk scope dışında kalır.

## Hedef pipeline — henüz uygulanmadı

```text
source → Docling structural parsing → quality/routing → Vision enrichment
       → reconciliation/normalization → core + optional domain schema validation
       → canonical knowledge → Markdown / assets / chunks / application views
                             → optional embeddings / Qdrant
```

Docling yapısal extraction'ın ana bileşeni, Gemini görsel/semantik enrichment bileşeni olacak. M0 mevcut Gemini-or-Docling seçimini değiştirmez. All-page Vision ileride değerlendirme modu olarak kalabilir; hedef selective routing'dir.

Hedef artifact seti: `canonical.json`, `canonical.md`, `manifest.json`, `assets/`, `chunks.jsonl`; embeddings ve Qdrant opsiyoneldir. Bu artifact seti bugün üretilmez. Gelecekteki canonical export path sözleşmesi `documents/{document_id}/knowledge/{knowledge_revision_id}/canonical.json`; M1 bu nesneyi yazmaz ve mevcut raw artifact path'lerini değiştirmez.

M1 contract'ı `packages/domain/docgrain_domain/canonical/` altındadır. Core schema ve domain schema ayrı; domain validation yalnızca açıkça sağlanan, checksum'ı eşleşen JSON Schema ile `docgrain-domain[validation]` opsiyonel bağımlılığı kullanır. `SourceVersion` ve `KnowledgeRevision` satırları immutable, revision'lar append-only ve latest/approved head ayrı tutulur. Mevcut MinIO upload key'i overwrite edilebildiği için checksum ve sabit object identity doğrulanmadan canlı upload bu modele güvenilir immutable source olarak bağlanmaz. Karar ayrıntısı [ADR 0005](docs/adr/0005-canonical-knowledge-foundation.md).

## Live ve demo modları

- Varsayılan `USE_FIXTURES=false`: live PostgreSQL ve MinIO kayıtları. Fixture fallback yoktur.
- `USE_FIXTURES=true`: salt okunur sentetik demo. Upload/register/confirm `409` döndürür; gerçek storage/queue kullanılmaz.
- `/healthz` içindeki `mode` ve HTTP `X-Docgrain-Mode` header'ı `live` veya `demo` değerini taşır.
- Console modu API'den alır; API erişilemiyorsa hata gösterir. Demo verisiyle devam etmez.
- Demo chunk, similarity ve ileri pipeline örnekleri simülasyondur. Gerçek embedding veya extraction sonucu değildir.
- Stage retry her iki modda `501` döndürür; herhangi bir iş planlamaz.
- Live chunk lookup/neighbors ve boundary analysis `501` döndürür. Mevcut live version'ın table/asset/chunk listeleri boş döner.
- Live version diff yalnızca aynı dokümana ait sürümlerin sayaç farkıdır; semantic diff veya patch değildir.
- Provider envanteri bağlantı testi yapmaz. `healthy: null` kontrol edilmedi, `false` yapılandırılmadı/implement edilmedi anlamındadır. Live page `confidence: null` ölçülmedi demektir.

## Yerel geliştirme

Mevcut live servis profili:

```sh
cp .env.example .env
docker compose up --build
```

[Console](http://localhost:3000), [API/OpenAPI](http://localhost:8000/docs), [MinIO](http://localhost:9001).

Compose; API, worker, web, PostgreSQL, Redis, MinIO ve henüz kullanılmayan Qdrant servisini içerir. Qdrant container'ının çalışması indexing özelliği sağlamaz. M0 servis mimarisini değiştirmez.

Altyapısız demo API (PowerShell):

```powershell
python -m pip install -e 'packages/domain[validation]' -e 'apps/api[dev]'
$env:USE_FIXTURES = "true"
python -m uvicorn docgrain_api.main:app --port 8000
```

Ayrı terminalde:

```powershell
cd apps/web
npm ci
npm run dev
```

API doğrudan çalıştırıldığında `.env` dosyasını otomatik yüklemez. Live API için gerekli ortam değişkenleri ayrıca sağlanmalıdır. Demo için worker başlatmayın. `NEXT_PUBLIC_API_URL` web bundle oluşturulurken belirlenir; mevcut Docker build varsayılan localhost adresini kullanır.

Hedef `docgrain ingest` / `docgrain index` CLI henüz yoktur. Basit local conversion'ın altyapısız çalışması sonraki milestone'ların hedefidir.

## Doğrulama

```sh
python -m pip install -e 'packages/domain[validation]' -e 'apps/api[dev]'
python -m pytest -q
ruff check apps packages tests
cd apps/web
npm ci
npm run build
```

`pytest.ini` API, worker ve domain source path'lerini tanımlar. Unit testleri gerçek Docling/PyMuPDF/model işlemi çalıştırmaz; tüm worker bağımlılıklarını yüklemeyi gerektirmez. M1 persistence integration testleri yalnızca `DOCGRAIN_M1_TEST_DATABASE_URL` ile etkinleşir ve ayrı, geçici PostgreSQL schema kullanır. Docker/provider integration ve golden document benchmark henüz yoktur.

## Bilinen sınırlar

Redis list dispatch acknowledgment/lease/recovery sağlamaz; worker çökmesi işi kaybettirebilir veya `running` bırakabilir. Stage özetleri işlem sonunda yazılır; ayrıntılı stage timing/progress yoktur. Önceki sürümlerde kaydedilmiş stage metadatası M0 tarafından geriye dönük düzeltilmez.

Deduplication, mevcut dokümana yeni revision yükleme, source/artifact write-once garantisi, checksum doğrulamalı upload, atomic publication ve tenant authorization henüz yoktur. Source URI ingestion `501` ile reddedilir. Yeni kayıtların source URI'si gerçek upload key ve configured bucket ile eşleşir; eski kayıtlar migrate edilmez.

Compose'ta özel S3 credentials ve API public URL için API environment wiring eksikleri, dependency pinning ve migration gereksinimleri devam eder. Bunlar M0'da altyapı rewrite'ı yapılarak çözülmedi.

## Deferred

Jev ve decision-provider framework; LangChain/LangGraph; çoklu Vision/embedding provider; alternatif vector DB; hybrid retrieval/FTS/reranking; connectors ve connector marketplace; chat/agent UI; schema discovery/otomatik schema evolution; cross-document entity resolution; operational overrides; büyük observability dashboard ve platform özellikleri.

## Sonraki çalışma

M1 foundation sonrası M2 structural parsing ayrı onay gerektirir. [Milestone planı](docs/DEVELOPMENT_HARNESS.md), [mimari](docs/ARCHITECTURE.md) ve [M1 kararı](docs/adr/0005-canonical-knowledge-foundation.md).

## License

MIT; [LICENSE](LICENSE). Gizli belgeler, credential'lar ve generated artifact'lar Git'e eklenmez.
