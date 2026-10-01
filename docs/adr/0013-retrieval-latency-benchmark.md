# ADR 0013 — Measured latency matrix and bounded revision cache

Date: 2026-10-01. Status: local implementation; review/merge pending.

M2e/M2f supply query and quality contracts. Notion Adaptive Knowledge Access ADR gives design
budgets, not measured SLOs. Measure tiny/small/medium/large synthetic canonical profiles over
real PostgreSQL + loopback HTTP with complete response serialization, cold/warm revision cache,
structured/direct/lexical/vector/hybrid/rerank paths and concurrency. Record p50/p95/p99,
throughput, component timings, evidence bytes, exact-match/label quality and environment.

Cache decoded immutable views by database identity/schema/workspace/document/canonical revision/
generation/index name. Resolve heads in a repeatable-read transaction on every request; never
cache a mutable document head or query result without its revision. Byte-bound LRU and lock;
copies prevent caller mutation. Cache miss reads stored context/index, never derives or embeds.

Benchmark preparation uses explicit synthetic vectors before measurement. Provider network,
real embedding/reranker costs and production ANN scaling are not measured. Cold means process
view-cache miss (not OS/database cache flush). Distinguish first miss from warm/concurrent runs.
Latency targets are shown as comparison columns, never promoted to SLO from this local sample.
No quality/evidence reduction to make timings pass. Document the reference adapter's measured
limits and retain the same consumer retrieval contract.
