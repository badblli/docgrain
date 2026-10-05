# Retrieval latency benchmark

`benchmarks/retrieval_latency.py` creates a disposable PostgreSQL schema and loopback TCP HTTP
server. It prepares canonical/entity/chunk/vector fixtures before measuring; provider fixtures
are explicitly nonsemantic. All requests use the real consumer endpoint and full serialization.
The script drops only its generated schema and shuts down its server on completion/failure.

```sh
PYTHONPATH=.:apps/api:apps/worker:packages/domain \
DOCGRAIN_M1_TEST_DATABASE_URL=postgresql://... \
python benchmarks/retrieval_latency.py report.json --runs 12 --concurrency 4
```

Matrix: tiny/small/medium/large (1/16/64/256 accepted entities and corresponding text chunks);
structured, direct, lexical, vector, hybrid and conditional rerank; cold/warm/concurrent.
Reports p50/p95/p99, throughput, backend/query/embed/rerank/service/serialization/transport-client
timing, response/evidence bytes, pinned fixture counts and exact predicate/context/target-hit
checks alongside latency. Dense quality uses controlled vectors, not production semantic labels.
Small sample percentiles are diagnostic, not statistically established SLOs.

Cold means decoded revision-cache miss; OS/PostgreSQL caches are not flushed. The bounded LRU
uses serialized-byte estimates, database/schema/user/workspace/revision/generation keys and
defensive copies. Heads are always fetched under repeatable-read; cache hit cannot hide a new
revision. Oversized views bypass the cache. Queries never compute context/chunks/doc embeddings.

## Local measured result — 2026-10-01

72 matrix rows, 8 warm/concurrent samples per cell, 3 process-cold samples, concurrency 4,
Linux Docker / Python 3.12 / real PostgreSQL / loopback HTTP. All exact/target-hit fixture checks
passed. Maximum observed p95 across the matrix: **1062 ms**. Warm p95 examples:

| Profile | Structured | Direct | Lexical | Vector | Hybrid | Rerank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Tiny | 10.46 ms | 12.69 ms | 11.32 ms | 11.20 ms | 13.39 ms | 11.58 ms |
| Small | 48.22 ms | 13.27 ms | 20.40 ms | 19.66 ms | 51.41 ms | 53.37 ms |
| Medium | 22.62 ms | 19.75 ms | 89.46 ms | 93.88 ms | 98.67 ms | 112.83 ms |
| Large | 104.77 ms | 83.02 ms | 276.32 ms | 255.52 ms | 267.02 ms | 268.07 ms |

Artifact `data/reviews/retrieval-latency.json` includes all p50/p95/p99, component and concurrency
rows. This exposes the reference Python/deep-copy/full-payload adapter's tail-latency limits.
No candidate/evidence reduction was made to meet a target. Prefer bounded direct context for
small knowledge and structured filters for exact questions; large/high-concurrency deployment
needs a measured optimized backend and representative semantic corpus. The Notion latency
budgets remain design targets; **production SLO is null** in the measured report.

`X-Docgrain-Serialization-Ms` measures the single actual server JSON serialization;
`X-Docgrain-Service-Ms` includes it. Client transport/decoding is a residual measured separately.
[ADR 0013](adr/0013-retrieval-latency-benchmark.md).

## Final M2g visibility-guard regression — 2026-10-01

After adding the deletion visibility check (one extra metadata SQL read), repeated the same
72-cell / 8-sample / concurrency-4 matrix. All controlled quality checks remained 1.0; maximum
matrix p95 **1114 ms**. Artifact `data/reviews/retrieval-latency-m2g.json` supersedes the baseline
above for the final stacked branch. Warm p95:

| Profile | Structured | Direct | Lexical | Vector | Hybrid | Rerank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Tiny | 11.61 ms | 12.20 ms | 13.94 ms | 13.25 ms | 13.90 ms | 12.86 ms |
| Small | 16.43 ms | 15.02 ms | 20.26 ms | 23.13 ms | 50.80 ms | 55.77 ms |
| Medium | 24.31 ms | 24.79 ms | 123.53 ms | 105.88 ms | 116.49 ms | 96.58 ms |
| Large | 122.77 ms | 105.41 ms | 247.88 ms | 309.71 ms | 264.80 ms | 347.80 ms |

Run-to-run variation and this small synthetic sample prevent any claim of a causal performance
improvement/regression. Large direct/dense paths can exceed design budgets; production SLO
remains null. Evidence/candidate sizes and correctness criteria were retained.
