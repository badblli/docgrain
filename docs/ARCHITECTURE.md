# Docgrain mimarisi — M1 canonical foundation

## Hedef yön

Docgrain domain-agnostic bir document-to-knowledge engine'dir. Canonical structured knowledge kabul edilmiş bilginin kaynak doğrusu olacak; Markdown, chunks, embeddings ve consumer-specific JSON görünümleri türetilmiş projections olacaktır. Orijinal belge ve ham extraction kanıt olarak korunur. Core schema ile kullanıcı/domain schema ayrı kalır; LUWI yalnızca gelecekteki consumer'lardan biridir.

Canonical v0.1 contract ve opt-in persistence M1'de eklendi. Yeni pipeline, live mapping veya canonical publication henüz implement edilmedi.

## M1 contract sınırı

`packages/domain/docgrain_domain/canonical/` structural tree, entity/relation/domain record, source evidence, fine-grained field/cell annotations, review/provenance/validation ve temporal contract'larını içerir. Core JSON Schema Pydantic'ten üretilir; domain schema ayrı pinned ref ve explicit validator'dır. Container `children` sırası reading order'dır; node listesi sırası değildir. PDF bbox top-left normalized 0..1, TXT offset'leri decoded Unicode code point `[start,end)`, spreadsheet aralıkları normalized A1'dir. Bu locator'ların runtime Docling/Gemini dönüşümü henüz yoktur.

`apps/api/docgrain_api/canonical_repository.py` yalnızca açıkça çağrılabilen additive PostgreSQL foundation'dır: `source_versions`, `knowledge_revisions`, `document_knowledge_heads`. API lifespan, route ve worker bunu kullanmaz. Immutable source/revision row, ayrı latest/approved pointer ve CAS append/approval sağlar. Mevcut upload object key'leri overwrite edilebildiğinden source checksum ve değişmez object identity doğrulaması olmadan live upload yeni `SourceVersion`'a bağlanmaz. `document.json`, `document.md`, `pages.json`, PNG ve Vision JSON yolları aynıdır. `canonical.json` path contract tanımlı olsa da publication M4'e kalır.

## Mevcut executable mimari

```text
web → FastAPI → PostgreSQL: document/version/job
              → MinIO: uploads/{document}/{version}/original
confirmation → Redis LPUSH
worker BRPOP → SQL queued-to-running claim → download source.pdf
             → PyMuPDF render → Gemini (key varsa) veya Docling (OCR kapalı)
             → MinIO: pages.json, pages/*.png, document.json, document.md
             → PostgreSQL: done/partial/failed
```

Gemini sayfa çağrıları dört thread ve en fazla üç attempt ile çalışır. Başarılı sayfalar aggregate edilir; reconciliation yapılmaz. Docling ve Gemini aynı run içinde birleştirilmez. `quality` yalnızca temel sayfa/response kontrollerini ifade eder; completeness veya confidence ölçümü değildir.

PostgreSQL üç metadata tablosuna sahiptir. MinIO binary/artifact deposudur. Redis yalnızca job-ID list dispatch için kullanılır; acknowledgment ve crash recovery yoktur. Qdrant yapılandırılmış ancak uygulamaya bağlanmamıştır.

API/worker ayrımı, FastAPI, PostgreSQL, MinIO, Redis, PyMuPDF, Docling, Gemini ve Pydantic M0'da korunur. Yeni framework/abstraction yoktur.

## Mode sınırı

Live varsayılandır ve PostgreSQL okumalarında fixture fallback yoktur. Demo `USE_FIXTURES=true` ile açıkça seçilir; salt okunurdur, storage/queue işlemi yapmaz. API response'ları `X-Docgrain-Mode` ile etiketlenir. Frontend veri üretmez veya boş/error sonuçlarını demo ile doldurmaz.

Retry her modda `501`; live chunk/similarity henüz `501`. Live table/asset/chunk listeleri boş olabilir. Demo-only similarity ve diff sentetiktir. Live diff sadece aynı logical document'ın version sayaçlarını karşılaştırır.

`Page.confidence` ve `ProviderHealth.healthy` ölçülmeyen değerler için `null` kabul eder. Bu M0 contract düzeltmesidir; canonical model eklenmesi değildir.

## Hedef sınırlar — sonraki milestone'lar

1. Source identity ve immutable source version.
2. Docling structural evidence ve format-specific source locations.
3. Quality signals, selective rendering/Vision enrichment.
4. Reconciliation/normalization ve schema validation.
5. Accepted canonical knowledge revision.
6. Deterministic Markdown/assets/chunk projections.
7. Optional embedding/Qdrant projection.
8. Schema-aware Structured Knowledge Patch ve review policy.

İlk format scope'u PDF, DOCX, TXT, XLSX; bugünkü ingestion PDF-only. Core provider sınırları hedefte `DocumentParser`, `VisionProvider`, `EmbeddingProvider`, `VectorStore`; henüz olmayan adapter'lar varmış gibi sunulmaz.

Structured Knowledge Patch; old/new values, source evidence, confidence, extraction metadata ve schema version taşıyacak. Partial extraction'da eksik alanlar otomatik silme olarak yorumlanmayacak. Bu yalnızca gelecekteki tasarım kısıtıdır.

## Operasyonel sınırlar

Job `done` mevcut extraction'ın bittiğini gösterir. Normalization/chunk/enrich/embed uygulanmadı; ayrı Vision enrichment aşaması yoktur. `publish` yalnızca extraction dosyalarının kaydını ifade eder. Processing manifest, atomic publication, stage resume ve tam stage timing yoktur. Tarihsel job kayıtları yeniden yazılmaz.

Tenant ID alanları authorization sağlamaz. Upload/source immutability ve content deduplication henüz enforce edilmez. Shared deployment öncesinde bunlar ayrıca ele alınmalıdır.

## Deferred

Jev; LangChain/LangGraph; çoklu provider/vector store; hybrid retrieval, keyword index ve reranking; connectors; chat/agent UI; schema discovery; cross-document matching; operational overrides; büyük dashboard/platform işleri.

Karar tarihçesi için [ADR 0004](adr/0004-canonical-first-scope-freeze.md) ve [ADR 0005](adr/0005-canonical-knowledge-foundation.md). Önceki ADR'ler tarihsel bağlamdır; uygulanmış özellik listesi değildir.
