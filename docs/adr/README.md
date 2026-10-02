# Architecture Decision Records

Güncel yön: [ADR 0004 — canonical-first scope freeze](0004-canonical-first-scope-freeze.md). M1 foundation: [ADR 0005](0005-canonical-knowledge-foundation.md). M1b parsing: [ADR 0006](0006-m1b-structural-parsing.md).

ADR 0001–0003 tarihsel tasarım kararlarıdır; güncel implementasyon özellik listesi değildir. Özellikle primary-Vision hedefi ADR 0004 ile değiştirilmiştir. Mevcut runtime, M0'da henüz yeni extraction yönüne geçirilmez.

Public contract veya mimari sınır değişikliklerinde küçük, açık bir ADR/migration note ekleyin.

M2a: [ADR 0007 — stable identity, revisions and lineage](0007-stable-identity-revisions-lineage.md).
M2b: [ADR 0008 — schema entities and field provenance](0008-schema-entities-field-provenance.md).
M2c: [ADR 0009 — deterministic structure-aware chunks](0009-structure-aware-chunk-derivation.md).
M2d: [ADR 0010 — canonical diff and atomic index generations](0010-canonical-diff-incremental-lifecycle.md).
M2e: [ADR 0011 — explicit retrieval capabilities](0011-retrieval-capabilities.md).
M2f: [ADR 0012 — retrieval evaluation and conditional reranking](0012-retrieval-evaluation-reranking.md).
Latency: [ADR 0013 — measured matrix and revision cache](0013-retrieval-latency-benchmark.md).
M2g: [ADR 0014 — durable source observations and Pathway decision](0014-live-source-change-adapters.md).
Output integration: [ADR 0015 — common pre-embedding output with fidelity gaps](0015-pre-embedding-ai-output.md).
Source acceptance: [ADR 0016 — independent source checks and selective visual proposals](0016-source-fidelity-acceptance.md).
Güncel dependency sırası identity/lineage → entities → chunks → diff/invalidation → retrieval.
