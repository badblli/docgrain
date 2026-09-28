# API

FastAPI registration/upload/confirmation, job metadata ve extraction artifact okumalarını sağlar. Extraction API process'inde çalışmaz.

Varsayılan live: PostgreSQL/MinIO/Redis. `USE_FIXTURES=true`: açık salt okunur demo. Response'larda `X-Docgrain-Mode`; `/healthz` liveness ve mode verir, dependency readiness ölçmez.

Mevcut upload PDF-only; her registration yeni document/revision 1 oluşturur. Proxy upload ardından confirmation queue'ya job ID ekler. Source-URI ingestion, deduplication ve revision append yoktur.

Demo yazmaları `409`; retry tüm modlarda `501`. Live chunks/neighbors/boundaries henüz desteklenmez. Live tables/assets/chunks listeleri boş; diff yalnızca count delta'dır. `document.md/json` canonical model değil extraction çıktısıdır.

`Page.confidence` ve `ProviderHealth.healthy` unknown için null olabilir. Auth/workspace enforcement, migrations ve crash recovery sonraki çalışmalardır. Ayrıntılar: [M0 ADR](../../docs/adr/0004-canonical-first-scope-freeze.md).

M1'de `canonical_repository.py` ayrı, opt-in PostgreSQL foundation olarak eklendi. Mevcut API route/lifespan veya worker bunu çağırmaz; yeni tablolar otomatik açılmaz. Immutable source/revision ve latest/approved head contract'ı için [M1 ADR](../../docs/adr/0005-canonical-knowledge-foundation.md). Live upload'ları checksum + object identity doğrulaması olmadan canonical source saymayın.
