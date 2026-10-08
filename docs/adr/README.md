# Architecture Decision Records

Document reader: [ADR 0024 — Docling reads documents (decision 18)](0024-docling-reads-documents.md).
It replaces the native reader/default OCR decisions in ADRs 0018–0020; the optional
proposal and human review contracts in ADR 0023 remain.

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
Güncel ürün scope/öncelik: [ADR 0017 — normalization first, embeddings last](0017-normalization-first-scope.md).
N1 uygulaması: [ADR 0018 — original image evidence and local OCR](0018-image-evidence-local-ocr.md).
N2 uygulaması: [ADR 0019 — native source structure and cell evidence](0019-native-source-structure-fidelity.md).
N3 yerel yönü: [ADR 0020 — local-first visual review](0020-local-first-visual-review.md); güncel N3 için ADR 0017'nin harici görsel sağlayıcı seçimini değiştirir.
Güncel dependency sırası N0 scope → N1 OCR/image → N2 source fidelity → N3 visual proposals → N4 reconciliation/review → N5 source acceptance → optional embedding.

End-user manual review: [ADR 0021 — source reading and immutable reviews](0021-end-user-source-review.md). The bounded manual N4 workspace can proceed alongside the open N3 semantic gate; N5 and embedding remain open.

Experimental normalized-data consumer: [ADR 0022 — canonical Gemini Q&A](0022-canonical-gemini-qa-probe.md). Local source normalization and accepted revisions remain independent of the chat provider.

Experimental CPU visual proposals and preserved uncertainty: [ADR 0023](0023-local-cpu-visual-proposals.md). Source-reviewed manual corrections are separate from automatic model acceptance; N3/N5 remain open.
