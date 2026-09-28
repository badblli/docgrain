# Geliştirme planı ve kalite kapıları

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

Reliability/provenance testleri her milestone'a eşlik eder; M8'e ertelenmez. M1a contract ve persistence foundation, M1b multi-format structural parser/mapping katmanı tamamlandı. M2 Vision reconciliation ve sonraki projection'lar mevcut değildir.

## Format ve deferred scope

İlk ürün formatları **PDF, DOCX, TXT, XLSX**. Mevcut executable yol yalnızca PDF işler. PPTX/HTML ve bağımsız image ingestion sonraya bırakılır.

Jev, LangChain/LangGraph, çoklu provider, hybrid retrieval/FTS/reranking, connectors, chat/agent UI, schema discovery ve platform abstractions deferred. LUWI entegrasyonu core business schema'sını belirlemez.

## Yerel kontroller

```sh
python -m pip install -e 'packages/domain[validation]' -e 'apps/api[dev]'
python -m pytest -q
ruff check apps packages tests
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
