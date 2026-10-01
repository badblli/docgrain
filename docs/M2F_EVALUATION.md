# M2f — Retrieval quality and conditional reranking

The offline harness versions golden queries, source/object/evidence labels and fingerprints
corpus + query + strategy + scope + k. It compares recall@k, MRR@k and exponential-gain,
log2-discount nDCG@k, query latency, evidence bytes and no-answer false positives. No-answer
queries are excluded from quality means and reported separately. Duplicate labels cannot
increase relevance gain. For bundled evidence labels, recall uses the evidence union and
nDCG uses strongest fresh label per hit against the label upper bound; use object qrels for
standard document-ranked nDCG. Result generation/answer quality is outside this harness.

`reranking: {"strategy":"phrase-overlap","version":"1"}` explicitly enables a deterministic
local baseline after retrieval over `candidate_limit` candidates and before final `limit`.
Structured/direct bypass reranking. It is not a semantic cross-encoder. Every scorer result
must cover exactly the scoped candidates with finite scores. Content/evidence/identity remain
unchanged; original retrieval scores and rerank component score are inspectable. External
scorers can be injected programmatically; HTTP never selects an unconfigured provider.

```powershell
$env:PYTHONPATH = '.;apps/api;apps/worker;packages/domain'
python docs/examples/evaluate_retrieval.py data/reviews/m2f-evaluation.json
python docs/examples/evaluate_user_lexical.py snapshot.json data/reviews/m2f-real-lexical.json
```

`tests/fixtures/retrieval-golden-1.json` is a checked-in synthetic source-anchor dataset, with
controlled test-only vectors and a no-answer case. Dense metrics validate the comparison
mechanism; they are not production semantic performance. The user XLSX example independently
labels canonical table row occurrences for known terms and compares actual lexical/reranker
results read-only. Prepared vectors/chunks are outside measured queries and never persisted.
Measured provider cost is null when no price/usage measurement exists, rather than fabricated.

Latency/SLO/concurrency measurements are a separate harness, and design targets remain targets
until representative deployment/corpus evidence exists. [ADR 0012](adr/0012-retrieval-evaluation-reranking.md).
