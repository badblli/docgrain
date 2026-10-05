# M2g — complete source observations and durable changes

Local foundation/spike, not an enabled background connector service. Canonical history is
retained; source deletion removes the document from current retrieval, including warm caches.
Historical revision APIs remain available for audit. No source directory/bucket is watched
automatically. No extraction/model/provider is selected by an adapter.

## Explicit usage

```python
from pathlib import Path
from docgrain_api.source_repository import SourceRepository
from docgrain_worker.source_adapters import FilesystemSource, ObjectStoreSource
from docgrain_worker.source_sync import sync_source

ledger = SourceRepository(connect, schema="your_initialized_schema")
ledger.initialize()
adapter = FilesystemSource(Path("your_source_root"))
# Or: ObjectStoreSource(versioned_minio_client, "your_bucket", "your_prefix/")
result = sync_source(ledger, workspace_id, connector_id, adapter, publish_idempotently)
```

`publish_idempotently(SourceChange)` must own document registration, verified durable source
storage, canonical processing and explicit index publication. Its providers/configs are caller
supplied. Delete callback handles external derived cleanup; ledger commits the query visibility
tombstone only after callback success. Restore clears it after successful publication. No source
row or revision is physically deleted. PostgreSQL index history is retained, not physically purged.

Source identity is workspace + connector + natural source key. Bind a connector ID to one
root/bucket/prefix; change it when that configuration changes. Filesystem SHA/version is a
verified content receipt, **not a durable original copy**. Adapter reads reject changed bytes;
publisher must persist immutable bytes before canonical publication. MinIO requires version IDs
and validates actual SHA-256; ETags are not treated as content checksums.

## Consistency, retries and failures

- Capture cursor generation before a complete scan. Reconcile applies CAS under a per-connector
  PostgreSQL advisory lock; a delayed scan with different state conflicts.
- Missing/unreadable roots, symlinks, changed inventories and object errors abort the observation.
  Never pass a partial inventory to reconciliation: absence in a complete scan means deletion.
- Complete observations and immutable upsert/delete events commit in one transaction. IDs include
  scope, source key and cursor generation; returning to old content remains a distinct change.
- Unacknowledged events coalesce per source key to latest desired state. Duplicate or reordered
  external notifications cause a rescan, never blind application of their payload.
- Dispatch serializes against reconciliation and other dispatchers. Acknowledge only after callback
  success. Crash after external publication but before acknowledgement replays the callback;
  lifecycle idempotency is required. There is no distributed exactly-once guarantee.
- Slow callbacks block that connector. Scheduling, retry/backoff, watcher service auth/registration
  and cross-system atomicity are future integration work. The ledger is not ingestion crash recovery.
- Canonical identities remain content/config-derived. Returning to an older source while another
  canonical head is current needs an explicit new processing configuration/occurrence; replay of
  an old successful processing revision deliberately does not rewind the canonical head.
- S3 multi-object listings and filesystem scans are not linearizable snapshots. Double inventory
  detects observed changes, with eventual convergence through repeated scans; it cannot detect
  every ABA mutation between observations. Adapters do not claim atomic filesystem transactions.

## Polling vs notifications / CDC

| Signal | Contract and operating cost |
| --- | --- |
| Periodic polling | Complete rescan, hash cost proportional to bytes; no inbound endpoint. Detection bound is interval + scan/queue time. |
| Filesystem watcher | Low-latency hint; requires platform watcher + periodic rescan for missed events/restart. Same ledger. |
| Object-store webhook | At-least-once hint; requires authenticated durable receiver, retries and rescan. Never trust arrival order as latest state. |
| Database CDC | Needs upstream transaction cursor/snapshot and durable offsets; filesystem/S3 object source has no universal CDC feed. Not implemented here. |
| Pathway | Streaming table with signed removal/addition and its own persistence/runtime. Still needs Docgrain canonical/source/outbox publication guards. |

## Executed Pathway decision — 2026-10-01

Pathway **0.33.0** installed only in isolated Python 3.12 Linux container. Same one-file
create → update → delete sequence executed with native complete scans and Pathway streaming
binary reader, 100 ms autocommit. Modification produces negative old row + positive new row
in the same batch; deletion produces a negative row. These must be coalesced before publication.

| Action | Native scan duration | Pathway change detection |
| --- | ---: | ---: |
| Create | 0.70 ms | 2.74 ms |
| Update | 0.56 ms | 331.94 ms |
| Delete | 0.07 ms | 337.74 ms |

Native initialization 0.08 ms; Pathway process/import/setup **1340 ms**. Isolated installed
environment: 131 distributions, **1.48 GB** site-packages (entire environment, not only Pathway).
Native duration excludes polling wait; these are different measurements, **not a throughput/SLO
or broad performance superiority claim**. One sequence does not establish a meaningful benefit.

**Decision: keep own adapters/outbox; do not add Pathway runtime dependency.** This spike did
not reduce required Docgrain scope/version/CAS/idempotency invariants or prove a useful measured
advantage. Reconsider if a representative large live corpus and durable restart comparison do.
Pathway persistence was not configured in this spike; native durable retry/restart is validated
separately against real PostgreSQL. Script: `benchmarks/live_sources.py`; full ignored artifact:
`data/reviews/live-source-spike.json`. [ADR 0014](adr/0014-live-source-change-adapters.md).

## Regression evidence

Real PostgreSQL tests exercise immutable events/acks, concurrent CAS, duplicate delivery,
publish-before-ack failure/restart, late delete coalescing and source-scope isolation. A real TXT
create/update flows through canonical parser, revision publication, M2d index refresh with an
explicit test embedder and M2e lexical query; deletion blocks all five current retrieval paths
with/without warmed cache, while history remains; same-current-content restore reuses revisions.
Opt-in MinIO test creates/drops a unique versioned bucket; old version bytes remain addressable,
update/delete are detected, unavailable bucket does not advance the cursor. User sources unchanged.
