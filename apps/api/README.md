# API

FastAPI registration/upload/confirmation, job metadata ve extraction artifact okumalarını sağlar. Extraction API process'inde çalışmaz.

Varsayılan live: PostgreSQL/MinIO/Redis. `USE_FIXTURES=true`: açık salt okunur demo. Response'larda `X-Docgrain-Mode`; `/healthz` liveness ve mode verir, dependency readiness ölçmez.

Mevcut upload PDF/DOCX/TXT/XLSX kabul eder; her registration yeni document/revision 1 oluşturur. Proxy upload MIME/extension/byte biçimi ve varsa declared SHA-256 doğrular; confirmation queue'ya job ID ekler. Source-URI ingestion, deduplication ve legacy revision append yoktur.

Demo yazmaları `409`; retry tüm modlarda `501`. Live chunks/neighbors/boundaries henüz desteklenmez. Live tables/assets/chunks listeleri boş; diff yalnızca count delta'dır. `document.md/json` canonical model değil extraction çıktısıdır.

`Page.confidence` ve `ProviderHealth.healthy` unknown için null olabilir. Auth/workspace enforcement, migrations ve crash recovery sonraki çalışmalardır. Ayrıntılar: [M0 ADR](../../docs/adr/0004-canonical-first-scope-freeze.md).

M1a `canonical_repository.py` ayrı PostgreSQL foundation olarak eklendi. M1b'de opt-in API startup DDL ve worker append vardır; worker yalnız doğrulanmış checksum + gerçek MinIO object version ID ile canonical revision yazar. `canonical.json` yayınlanmaz. [M1a ADR](../../docs/adr/0005-canonical-knowledge-foundation.md) ve [M1b ADR](../../docs/adr/0006-m1b-structural-parsing.md) ayrıntıları açıklar.
