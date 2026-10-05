# ADR 0014 — Live observations, durable reconciliation and Pathway decision

Date: 2026-10-01. Status: accepted after executable spike.

## Problem / reference review

M2d has batch-safe canonical/index generations; source polling/events are not implemented.
Primary references: [Pathway filesystem](https://pathway.com/developers/api-docs/pathway-io/fs/),
[Pathway core concepts](https://pathway.com/developers/user-guide/introduction/concepts/),
[Pathway persistence](https://pathway.com/developers/api-docs/pathway-persistence/),
[S3 event notifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-how-to-event-types-and-destinations.html).
Source notifications are hints and may be duplicated/reordered. Content/version-addressed
observations, complete scans and Docgrain publication CAS remain the authority.

## Contract / spike

Implement filesystem and versioned object-store observation adapters. Verify hashes/version
and path boundaries; abort incomplete/unstable scan instead of synthesizing mass deletion.
Reconcile a complete snapshot against a PostgreSQL connector cursor, atomically emitting
deterministic upsert/delete events into an immutable outbox. Cursor generations CAS, retries
dedupe, delete uses an explicit tombstone. Event acknowledgement happens only after the
supplied handler succeeds; replay after crash requires the handler's lifecycle idempotency.
Handlers reread current desired source state so delayed notifications cannot restore stale data.
No watcher autostarts against user directories/buckets or invokes a model on behalf of the user.

Run identical create/update/delete through native polling and optional Pathway 0.33.0 in an
isolated Linux container; collect startup/detection latency, event semantics and dependency
footprint. Pathway signed row updates are a source signal; coalesce complete source state
before publishing, preserving the same Docgrain outbox/revision/CAS invariants. Test duplicate,
failure/retry, restart and incomplete observation against real PostgreSQL and object storage.

Integrate Pathway only if measurements show a useful advantage and fewer invariants/runtime
operations to maintain. Otherwise keep small adapters and an explicit reconciliation layer.

## Measured decision

Pathway 0.33.0 successfully propagated create/update/delete. Startup 1340 ms;
update/delete detection 332/338 ms with 100 ms autocommit. Native scans of the same one-file
states took 0.70/0.56/0.07 ms, excluding scheduling delay. Isolated environment totals 131
distributions / 1.48 GB site-packages. These single-sequence figures are not production SLOs
or equivalent latency definitions. No measured benefit or invariant simplification established.

**Keep own observation adapters and durable outbox; no Pathway runtime dependency.**
Publication still needs Docgrain source verification, canonical/index CAS, idempotency and
current source visibility. Signed Pathway changes need coalescing; a separate runtime and
persistence configuration would add operational ownership. Revisit with representative scale.

The explicit source-sync boundary, PostgreSQL cursor/outbox/ack ledger and retrieval deletion
guard are implemented. Background registration/watchers, webhook auth/receiver, scheduling,
live model/Qdrant wiring and distributed exactly-once are outside this foundation. Full method,
measurements and consistency limits: [M2g](../M2G_LIVE_SOURCES.md).
