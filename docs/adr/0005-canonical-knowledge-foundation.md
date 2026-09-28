# ADR 0005 — M1 canonical knowledge foundation

- Durum: kabul edildi; M1 tasarımı kullanıcı tarafından onaylandı, review düzeltmeleri bağlayıcıdır.
- Tarih: 2026-09-28
- Önceki karar: [ADR 0004](0004-canonical-first-scope-freeze.md)

## Karar

Canonical v0.1, legacy `DocumentVersion` ve extraction artifact'lerinden ayrı bir core contract'tır. `CanonicalKnowledgeSnapshot` tek document/workspace/source/revision scope'unda structural tree, entities, relations, domain records, evidence, artifact references ve producer metadata taşır. Core schema `CanonicalKnowledgeSnapshot` Pydantic modelinden Draft 2020-12 olarak üretilir; sürümlü dosya yalnızca generated artifact'tır. Domain/user schema, pinned `DomainSchemaRef` ve explicit validator ile ayrı kalır. Schema discovery ve network `$ref` resolution yoktur.

`review_status` yalnızca unreviewed/proposed/approved/rejected/overridden değerlerinden biridir. Parser/model/vision/manual üretim yöntemi provenance'dadır; schema validation review approval değildir. Confidence ölçülmemişse `null` kalır. Item, field ve table-cell düzeyi annotation kanıt taşır; aggregate evidence child değerlerin kanıtı sayılmaz. Temporal validity date/datetime aralıklarını `[from,until)` olarak ayırır; yokluğu sonsuz geçerlilik iddiası değildir.

Structural node'lar discriminated union'dır. Document root tam bir tanedir; child refs, parent tekilliği, cycle/reachability, relation/entity, evidence, producer, artifact, domain schema ve scope referansları semantic validation'dan geçer. Core-invalid snapshot persistence'a alınmaz. `children` sırası reading order'dır. PDF bbox normalized top-left, TXT span decoded Unicode code point, XLSX A1 range, DOCX part/path ve artifact object locator contract'tır. Gerçek parser/vision bbox dönüşümü M2/M3 kapsamıdır.

Identity policy `0.1.0`: document ID + item kind + explicit stable identity key üzerinden deterministic ID. Revision, completion order, parser array index ve mutable text/label tek başına identity girdisi değildir. Cross-source automatic matching ve cross-document resolution yoktur. New source/revision ID'leri 128-bit random olabilir. JSON serialization sorted-key UTF-8 canonical encoding kullanır.

Additive PostgreSQL tabloları `source_versions`, `knowledge_revisions`, `document_knowledge_heads` olarak ayrılır. Source ve revision row'ları trigger ile update/delete'e kapalıdır; revision append-only'dir. Same revision ID + same hash idempotent, farklı snapshot conflict'tir. Latest ve approved pointer ayrıdır; CAS ve row lock kullanır. Approval yalnızca explicit çağrıyla yapılır, invalid domain record içeren revision approved head olamaz. Bu M1 foundation otomatik initialize edilmez, worker/API ingestion akışına bağlı değildir; mevcut tablolar ve response'lar korunur. DDL migration framework'ü değildir; üretim migration/rollback tasarımı sonraya kalır.

## Güven sınırı ve sonuçlar

Mevcut MinIO `uploads/{document}/{legacy_version}/original` key'i overwrite edilebilir. `SourceVersion` metadata ve DB row immutable olsa bile gerçek kaynak byte'larının immutable olduğu bundan çıkmaz. Üretimde bağlamak için gerçek byte'lar üzerinden doğrulanmış content checksum ve versioned object ID / immutable key / write protection gerekir. M1 live upload'u otomatik source olarak kaydetmez. İki sentetik fixture gerçek ingestion çıktısı değildir.

Legacy `document.json`, `document.md`, `pages.json`, page PNG ve Vision JSON path/format'ları değişmez. `documents/{document_id}/knowledge/{knowledge_revision_id}/canonical.json` sadece gelecekteki export path sözleşmesidir; M4'e kadar yazılmaz. M2 structural mapping, M3 Vision/reconciliation, M4 publication, sonraki projections/patch ve approval UI bu kararda implement edilmez.
