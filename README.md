# Docgrain

**Belgelerden yapılandırılmış, izlenebilir ve yeniden kullanılabilir bilgi üreten document-to-knowledge engine.**

Docgrain genel amaçlıdır. LUWI gelecekteki tüketicilerinden biridir; core içinde turizm veya LUWI business logic bulunmaz.

## Ürün yönü ve mevcut durum

Hedef mimaride **canonical structured knowledge kaynak doğrusudur**. Markdown, chunks, embeddings ve uygulamaya özel görünümler bu modelden türetilir. Orijinal belgeler ve ham extraction sonuçları kanıt olarak korunur. Core schema ile kullanıcı/domain JSON Schema ayrı kalır.

**Durum: pre-alpha / M2a–M2g foundations (local review).** Canonical identity/entities/chunks ve incremental index lifecycle üzerine scoped structured/direct/lexical/vector/hybrid retrieval, evidence-labeled değerlendirme, koşullu reranking, gerçek HTTP gecikme ölçümü ve durable source observation/outbox eklendi. Canonical 0.4.0 authoritative JSON ve tarihsel hash'ler korunur. İndeks üretimi ve source sync caller-supplied adapter ile explicit çağrıdır; ingestion otomatik üretmez. [M2e API](docs/M2E_RETRIEVAL.md), [M2f eval](docs/M2F_EVALUATION.md), [gecikme ölçümü](docs/RETRIEVAL_BENCHMARK.md), [M2g kaynak takibi](docs/M2G_LIVE_SOURCES.md) ve [ADR dizini](docs/adr/README.md).

| Alan | Bugünkü implementasyon |
| --- | --- |
| Ingestion | PDF/DOCX/TXT/XLSX kaydı → API upload proxy → MinIO → confirmation → Redis → worker |
| Rendering | PyMuPDF ile PDF sayfaları, 200 DPI PNG |
| Extraction | Gemini key varsa tüm sayfalarda Gemini; yoksa OCR kapalı Docling |
| Çıktılar | Provider-specific `document.json`, `document.md`, `pages.json`, page PNG; Gemini yolunda başarılı sayfa JSON dosyaları |
| Metadata | PostgreSQL document/version/job kayıtları |
| Kısmi hata | Bazı extraction hataları page failure olarak kaydedilir; bu recovery garantisi değildir |
| Console | API kayıtları, page render, doküman düzeyinde extraction Markdown; açık demo modu |
| Canonical structure | Docling-first PDF/DOCX/XLSX, deterministik TXT, format-aware evidence ve ayrı canonical PostgreSQL revision; yalnız object version ID varsa |
| Entities | Dış schema kaydı, explicit candidate publication, leaf-level JSON Pointer evidence, extracted → needs_review → accepted/rejected ve ayrı JSON retrieval projection; otomatik semantik extraction henüz yok |
| Canonical chunks | Bölüm/list context, lossless text slices, atomik table rows ve accepted entity JSON; explicit revision-scoped API, karakter bütçesi ve kaynak kanıtları |
| Incremental lifecycle | Exact canonical JSON diff, lineage invalidation candidates, selective embedding checkpoints, immutable PostgreSQL generations ve atomic head/CAS; explicit injected adapter, boş generation ile removal ve full rebuild |
| Retrieval | Tek scoped API; accepted JSON exact filters, precomputed direct context, BM25/cosine/RRF; conditional phrase baseline veya explicit reranker adapter. Vektörler caller-supplied; production semantic model seçilmiş değil |
| Evaluation | Golden source/evidence labels, recall/MRR/nDCG, no-answer checks; tiny/small/medium/large cold/warm/concurrent HTTP p50/p95/p99. Production SLO belirlenmedi |
| Live source foundation | Explicit filesystem/versioned object scan → PostgreSQL cursor/CAS/outbox → idempotent callback/ack; source deletion tüm current retrieval yollarını kapatır, history korunur. Pathway spike sonrası runtime dependency eklenmedi |
| Henüz yok | Canonical artifact publication, Vision reconciliation, processing manifest, otomatik semantic extraction/chunk/index job stage, live model/Qdrant adapter, adaptive router/knowledge profile, registered background connectors/webhook receiver, Structured Knowledge Patch, stage retry, ingestion crash recovery |

`document.json` içeriği kullanılan parser'a bağlıdır; canonical knowledge sözleşmesi değildir. `pages.json` yalnızca render boyutlarını içerir; processing manifest değildir. Job `done`, mevcut extraction yolunun tamamlandığını ifade eder; hedef pipeline'ın tamamlandığı anlamına gelmez.

## Sabitlenen ilk format scope'u

**PDF, DOCX, TXT, XLSX.** API MIME/extension ve upload byte biçimini doğrular. Desteklenmeyen veya uyuşmayan biçimler `415`, bozuk destekli içerik `422` döner. PPTX, HTML ve bağımsız image ingestion ilk scope dışında kalır.

## Hedef pipeline — sonraki aşamalar

```text
source → Docling structural parsing → quality/routing → Vision enrichment
       → reconciliation/normalization → core + optional domain schema validation
       → canonical knowledge → Markdown / assets / chunks / application views
                             → optional embeddings / Qdrant
```

M1b canonical structural yolunda Docling PDF/DOCX/XLSX için ana parser, TXT için deterministik decoder'dır. Mevcut PDF legacy JSON/Markdown akışı Gemini-or-Docling olarak kalır; Gemini sonucu canonical snapshot'a eklenmez. Güncel dependency sırası identity/lineage → entities → chunks → diff/invalidation → retrieval → evaluation → live-source spike tamamlandı; selective Vision/reconciliation ayrı capability track'tir. Bu local branch seti çalışan Inspector/image runtime'ına henüz deploy edilmedi; localhost sonucu bu yeni backend contract'larını temsil etmez.

Hedef artifact seti: `canonical.json`, `canonical.md`, `manifest.json`, `assets/`, `chunks.jsonl`; embeddings ve Qdrant opsiyoneldir. Bu artifact seti bugün üretilmez. Gelecekteki canonical export path sözleşmesi `documents/{document_id}/knowledge/{knowledge_revision_id}/canonical.json`; M1 bu nesneyi yazmaz ve mevcut raw artifact path'lerini değiştirmez.

M1 contract'ı `packages/domain/docgrain_domain/canonical/` altındadır. Eski 0.1.0 JSON Schema korunur; M1b `TableCell` genişlemesini 0.2.0 artifact'iyle sürümler. Core ve domain schema ayrıdır. `SourceVersion` ve `KnowledgeRevision` satırları immutable, revision'lar append-only ve latest/approved head ayrıdır. Mevcut upload key'i overwrite edilebilir; worker yalnız SHA-256 doğrulaması ve gerçek MinIO object `versionId` ile canonical persistence yapar. Version ID olmayan eski kaynaklar gate dışında kalır. [ADR 0005](docs/adr/0005-canonical-knowledge-foundation.md) ve [ADR 0006](docs/adr/0006-m1b-structural-parsing.md) ayrıntıları açıklar.

## Live ve demo modları

- Varsayılan `USE_FIXTURES=false`: live PostgreSQL ve MinIO kayıtları. Fixture fallback yoktur.
- `USE_FIXTURES=true`: salt okunur sentetik demo. Upload/register/confirm `409` döndürür; gerçek storage/queue kullanılmaz.
- `/healthz` içindeki `mode` ve HTTP `X-Docgrain-Mode` header'ı `live` veya `demo` değerini taşır.
- Console modu API'den alır; API erişilemiyorsa hata gösterir. Demo verisiyle devam etmez.
- Demo chunk, similarity ve ileri pipeline örnekleri simülasyondur. Gerçek embedding veya extraction sonucu değildir.
- Stage retry her iki modda `501` döndürür; herhangi bir iş planlamaz.
- Legacy live chunk lookup/neighbors ve boundary analysis `501` döndürür. Canonical chunk üretim/okuma için [revision-scoped API](docs/M2C_CHUNKS.md) kullanılır. Legacy live version listeleri bu chunk revision'larını temsil etmez.
- Live version diff yalnızca aynı dokümana ait sürümlerin sayaç farkıdır; semantic diff veya patch değildir.
- Provider envanteri bağlantı testi yapmaz. `healthy: null` kontrol edilmedi, `false` yapılandırılmadı/implement edilmedi anlamındadır. Live page `confidence: null` ölçülmedi demektir.

## Yerel geliştirme

Mevcut live servis profili:

```sh
cp .env.example .env
docker compose up --build
```

[Console](http://localhost:3000), [API/OpenAPI](http://localhost:8000/docs), [MinIO](http://localhost:9001).

Compose; API, worker, web, PostgreSQL, Redis, MinIO ve henüz kullanılmayan Qdrant servisini içerir. MinIO bucket versioning yeni upload'lar için etkinleştirilir. Qdrant container'ının çalışması indexing özelliği sağlamaz.

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

`pytest.ini` API, worker ve domain source path'lerini tanımlar. Unit testleri gerçek Docling modeli çalıştırmaz. M1 persistence integration testleri yalnızca `DOCGRAIN_M1_TEST_DATABASE_URL` ile etkinleşir ve ayrı, geçici PostgreSQL schema kullanır. M1b sentetik corpus generator ve gerçek Docling container integration testleri `tests/fixtures/structural/` ile `tests/integration/test_m1b_docling.py` altındadır.

## Bilinen sınırlar

Redis list dispatch acknowledgment/lease/recovery sağlamaz; worker çökmesi işi kaybettirebilir veya `running` bırakabilir. Stage özetleri işlem sonunda yazılır; ayrıntılı stage timing/progress yoktur. Önceki sürümlerde kaydedilmiş stage metadatası M0 tarafından geriye dönük düzeltilmez.

Deduplication, mevcut dokümana yeni revision yükleme, source/artifact write-once garantisi, checksum doğrulamalı upload, atomic publication ve tenant authorization henüz yoktur. Source URI ingestion `501` ile reddedilir. Yeni kayıtların source URI'si gerçek upload key ve configured bucket ile eşleşir; eski kayıtlar migrate edilmez.

Compose'ta özel S3 credentials ve API public URL için API environment wiring eksikleri, dependency pinning ve migration gereksinimleri devam eder. Bunlar M0'da altyapı rewrite'ı yapılarak çözülmedi.

## Deferred

Jev ve decision-provider framework; LangChain/LangGraph; çoklu Vision/embedding provider; alternatif vector DB; hybrid retrieval/FTS/reranking; connectors ve connector marketplace; chat/agent UI; schema discovery/otomatik schema evolution; cross-document entity resolution; operational overrides; büyük observability dashboard ve platform özellikleri.

## Sonraki çalışma

M1b structural parsing M1 milestone'un ikinci yarısıdır. Resmî M2 selective multimodal enrichment + reconciliation'dır. [Milestone planı](docs/DEVELOPMENT_HARNESS.md), [mimari](docs/ARCHITECTURE.md) ve [M1b kararı](docs/adr/0006-m1b-structural-parsing.md).

## License

MIT; [LICENSE](LICENSE). Gizli belgeler, credential'lar ve generated artifact'lar Git'e eklenmez.
