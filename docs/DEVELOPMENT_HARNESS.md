# Geliştirme planı ve kalite kapıları

## Güncel milestone sırası

M2a identity/revisions/lineage, M2b external-schema entities/field provenance, M2c structure-aware
chunks, M2d incremental index lifecycle, M2e scoped retrieval, M2f evaluation/conditional reranking,
latency harness ve M2g source adapters/Pathway karar spike'ı yerel review için uygulandı. Güncel dependency sırası
identity/lineage → entities → chunks → diff/invalidation → retrieval → evaluation → live sources; selective Vision ayrı capability
track'tir. Aşağıdaki M0–M8 tablo ilk planın tarihsel kaydıdır. Güncel contract ve kullanım:
[ADR 0007](adr/0007-stable-identity-revisions-lineage.md),
[ADR 0008](adr/0008-schema-entities-field-provenance.md), [M2b API](M2B_ENTITIES.md),
[ADR 0009](adr/0009-structure-aware-chunk-derivation.md), [M2c API](M2C_CHUNKS.md),
[ADR 0010](adr/0010-canonical-diff-incremental-lifecycle.md), [M2d lifecycle](M2D_LIFECYCLE.md),
[M2e retrieval](M2E_RETRIEVAL.md), [M2f evaluation](M2F_EVALUATION.md),
[latency benchmark](RETRIEVAL_BENCHMARK.md), [M2g source adapters](M2G_LIVE_SOURCES.md).

Sıradaki ürün entegrasyonu: gerçek embedding/Qdrant seçimi ve ölçümü, ingestion job stage/recovery
wiring, selective enrichment ve consumer kabulü. Foundations tamamlanması v1 release kabulü değildir.

## M0 sınırı

M0 live/demo ayrımını, doğru capability reporting'i, test collection'ı ve ürün scope'unu sabitler. Canonical Knowledge Model, yeni format parser'ları, retry/recovery altyapısı veya embedding implement etmez. Sonraki milestone için ayrı onay gerekir.

## Milestone sırası

| Milestone | Kapsam |
| --- | --- |
| M0 | Scope freeze / cleanup: açık salt okunur demo, live fixture isolation, gerçek capability reporting, CI |
| M1a | Canonical Knowledge Model foundation: core/domain schema ayrımı, evidence ve knowledge revision sözleşmeleri |
| M1b | Multi-format structural parsing: Docling-first PDF/DOCX/XLSX, deterministic TXT ve canonical mapping |
| M2 | Selective multimodal enrichment + reconciliation |
| M3 | Vision enrichment + reconciliation: selective routing, evidence ve conflict handling |
| M4 | Canonical JSON/Markdown/assets outputs ve processing manifest |
| M5 | Canonical structure üzerinden semantic chunking |
| M6 | Embeddings + optional Qdrant projection |
| M7 | Structured Knowledge Patch ve review policy |
| M8 | Evaluation/benchmarking ve release kabulü |

Reliability/provenance testleri her milestone'a eşlik eder; M8'e ertelenmez. Yukarıdaki M0–M8 tablo tarihsel yönü korur; bugün M2a–M2g contract/derivation/retrieval foundations uygulanmıştır. Selective Vision/reconciliation ve tam otomatik ingestion/index/recovery halen ürün entegrasyonu işidir.

## Format ve deferred scope

İlk ürün formatları **PDF, DOCX, TXT, XLSX**; structural ingestion bu dört formatı işler. PPTX/HTML ve bağımsız image ingestion sonraya bırakılır.

Jev, LangChain/LangGraph, çoklu provider, production FTS/ANN backend, registered background connectors, chat/agent UI, schema discovery ve platform abstractions deferred. Hybrid ranking/conditional reranking ve explicit source adapters mevcut foundations'dır; live semantic provider/production service değildir. LUWI entegrasyonu core business schema'sını belirlemez.

## Yerel kontroller

```sh
python -m pip install -e 'packages/domain[validation]' -e 'apps/api[dev]'
python -m pytest -q
ruff check apps packages tests benchmarks docs/examples
cd apps/web
npm ci
npm run build
```

`pytest.ini` worker dahil source path'lerini tanımlar; manuel `PYTHONPATH` gerekmez. Make kuruluysa `make quality` aynı kapıları çalıştırır. CI aynı Python test yolunu kullanır.

Varsayılan testler açık demo veya izole live repository stub'ları kullanır; Redis, MinIO veya provider'a erişmez. M1 canonical repository integration testleri `DOCGRAIN_M1_TEST_DATABASE_URL` verilirse gerçek PostgreSQL'de, benzersiz geçici schema üzerinde çalışır ve yalnızca o schema'yı kaldırır. Bunlar gerçek ingestion integration testi değildir.

## M0 kabul ölçütleri

- Live list/detail/asset/chunk endpoint'lerinde demo fallback yok.
- Demo API açık mode header'ı taşır, salt okunurdur ve storage/queue'ya erişmez.
- Console API hatasını ve boş sonuçları demo verisiyle doldurmaz.
- Retry yapılmıyorsa `202`/başarı mesajı yok.
- Fake similarity/diff yalnızca etiketli demo fixture'larında bulunabilir; console sabit sonuç üretmez.
- Unsupported stages `done` görünmez; manifest/index/recovery yapılmış gibi anlatılmaz.
- Confidence ve provider health ölçülmediyse unknown/null.
- Dokümanlar hedef mimariyi mevcut davranıştan ayırır.
- Test collection, Python lint ve web build geçer.

## Runtime smoke ve bilinen test boşlukları

Demo UI: banner, disabled upload, sentetik chunks; API kapalı: görünür hata; live API boş: boş liste; live version'da boş artifacts: boş görünüm. Gerçek servislerle ayrıca PDF upload → processing → extraction artifacts doğrulanmalıdır.

`tests/fixtures/structural/generate.py` sentetik PDF/DOCX/TXT/XLSX corpus'u üretir; `tests/integration/test_m1b_docling.py` gerçek Docling worker container'ında çalışır. Geniş kalite benchmark'ı, crash injection ve cost ölçümü henüz yoktur. `tests/fixtures/canonical/` M1a contract örneklerini içerir.

Mevcut worker aşama özetlerini sonda yazar. Eski job stage kayıtları M0 sırasında migrate edilmez. Veri modeli ve retry/recovery kapsamı sonraki çalışmada açıkça tasarlanacaktır.

## Değişiklik ilkeleri

Küçük vertical slice'lar; vendor-neutral Pydantic contracts; korunmuş source evidence; public contract değişikliği için ADR/migration note; secrets ve gerçek müşteri belgeleri Git dışında. Mevcut altyapıyı yeniden yazma; yeni framework veya erken abstraction ekleme.
