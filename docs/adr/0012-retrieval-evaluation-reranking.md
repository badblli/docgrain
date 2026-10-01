# ADR 0012 — Reproducible retrieval evaluation and conditional reranking

Date: 2026-10-01. Status: local implementation; review/merge pending.

## Problem / references

M2e has explicit retrieval strategies but no golden labels or measured comparison.
Primary sources reviewed: [NIST trec_eval](https://github.com/usnistgov/trec_eval),
[scikit-learn nDCG](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.ndcg_score.html),
[Sentence Transformers cross-encoder usage](https://www.sbert.net/docs/cross_encoder/usage/usage.html).
No metric/reranker runtime library is required for the bounded reference harness.

## Decisions

- Version golden datasets, corpus/config/query digests, source revisions and evidence labels.
  Report recall@k, MRR@k and graded nDCG@k, with explicitly exponential gain and log2 discount.
  Duplicate results cannot increase metrics. No-answer queries get separate false-positive
  accounting and do not contaminate recall/MRR/nDCG means.
- Evaluate actual retrieved source/evidence labels, not generated answers. Compare lexical,
  vector, hybrid and reranker off/on per query with timings, evidence bytes and adapter usage.
  Synthetic dense vectors are explicitly test-only; real lexical datasets remain separately labeled.
- Reranking is explicit/conditional. Structured/direct skip it. An injected scorer may only score
  already scoped candidates; finite scores for every supplied candidate are required. Preserve
  hit identity/content/evidence/lineage and original retrieval score. Stable ties remain stable.
- Ship a deterministic phrase/term reranker as a reproducible local baseline, not a semantic
  cross-encoder. Provider adapters are optional; cost is unknown unless measured/supplied, never
  silently $0. Reranker failure is explicit, not an unreported quality-changing fallback.
- Benchmark code is offline and may prepare chunks/vectors before measurement. Online queries
  must use only prepared views; parser, derivation and ordinary embedding are outside timing.

## Gates

Hand-calculated metrics including multi-grade relevance, duplicate and no-answer cases;
reranker injection/NaN/missing-score rejection; candidate expansion before final top-k;
same evidence through reranking; deterministic golden results and config hash changes.
Real user canonical JSON can be used read-only with independently checked source labels.
