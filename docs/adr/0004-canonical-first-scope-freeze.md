# ADR 0004 — Canonical-first yön ve M0 scope freeze

- Durum: kabul edildi; kullanıcı audit ve M0 planını onayladı.
- Tarih: 2026-09-28
- Kaynak: [Docgrain Notion](https://app.notion.com/p/3e473464cac581e692a9e73b39be7c90), ardından onaylanan M0 kapsamı.
- Önceki ADR 0001–0003 uygulama taahhütleri güncel davranışın kanıtı değildir. ADR 0003'ün primary-Vision hedef kararı superseded.

## Karar

Docgrain canonical-first, domain-agnostic bir document-to-knowledge engine'dir. Structured canonical knowledge kaynak doğrusu; Markdown/chunks/embeddings/application views projections olacaktır. Core ve domain schema ayrı kalır. Docling structural primary; Gemini enrichment; reconciliation canonical çıktıyı oluşturur. LUWI bir consumer'dır. Bunlar M1 ve sonraki milestone'ların hedefidir.

İlk format scope'u PDF, DOCX, TXT, XLSX. M0 mevcut PDF-only runtime'ı korur; desteklenmeyen formatlar `415`, external source ingestion `501` döndürür. Gemini key varsa tüm sayfa extraction, yoksa OCR kapalı Docling mevcut davranış olarak korunur.

## M0 davranış değişiklikleri

- `USE_FIXTURES=false` varsayılan. Demo açık, salt okunur ve `X-Docgrain-Mode: demo` ile etiketli.
- Demo register/upload/confirm `409`; demo artifact/render istekleri storage'a gitmez.
- Live API/console fixture fallback yapmaz. API hatası kullanıcıya hata olarak gösterilir.
- Retry tüm modlarda `501`; stage replay veya queue dispatch yapılmaz.
- Live chunk/neighbors/boundary analizi `501`; table/asset/chunk listeleri mevcut implementasyon gereği boş olabilir.
- Live diff yalnızca aynı document'ın version count delta'larıdır. Demo semantic diff örneği yalnızca kendi base/head yönünde döner.
- Provider health probe yapılmadığında `healthy: null`; page confidence ölçülmediğinde `confidence: null`. Bu iki alanın nullable olması API contract değişikliğidir; tüketiciler unknown durumunu işlemelidir.
- Worker normalization/chunk/enrich/embed aşamalarını done işaretlemez. `publish` extraction dosyalarının kaydıdır; manifest veya index anlamına gelmez. Stage başlangıç zamanı ve attempt sayısı ölçülmeden üretilmez.
- Source URI yeni kayıtlarda configured bucket ve gerçek upload key ile eşleştirilir. Önceki kayıtlar değişmez.
- Test collection için root `pytest.ini` worker source path'ini içerir; full worker dependency kurulumu unit suite için zorunlu değildir.

## Kapsam dışında

M1 canonical model; yeni parser/multiformat desteği; normalization/reconciliation; manifest; chunking/embedding/index; patch; durable queue redesign; crash recovery; schema migrations ve auth implementasyonu bu değişiklikte yoktur.

Jev, LangChain/LangGraph, çoklu provider/vector DB, hybrid retrieval/FTS/reranking, connectors, chat/agent UI, schema discovery, cross-document matching ve platform özellikleri deferred.

## Korunan altyapı

FastAPI, PostgreSQL, MinIO, Redis, PyMuPDF, Docling, Gemini SDK integration, Pydantic contracts, API/worker ayrımı ve console tasarımı korunur. Yeni framework yoktur. README-only package'lar uygulanmış abstraction gibi sunulmaz.

## Sonuçlar ve geçiş

Demo yazma davranışı ve önceki sahte retry başarısı artık yoktur. Live console daha az içerik gösterebilir; bu eksik implementasyonu doğru yansıtır. Frontend API yokken offline demo sunmaz.

Mevcut DB/job/artifact kayıtları migrate edilmez. Eski stage summary'leri tarihsel ve güvenilirliği sınırlı kayıtlardır. `pages.json` render metadata'sıdır; `document.json` provider-specific extraction'dır. Job `done` tüm hedef mimarinin bittiğini belirtmez.
