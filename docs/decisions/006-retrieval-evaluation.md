# 006: Measure retrieval on a golden set, and what the numbers decided

## Context
"Measure" is in the assignment's first sentence, and the panel tests with questions whose answers
live in specific pages. Opinions about chunking and fusion are cheap; a table is not.

## Method
`eval/golden/` holds 50 questions, one JSON file per kind, each naming the page or pages that answer it: 8 configuration
parameters, 8 limits, 18 how-to steps, 10 bare identifiers (`retention.ms`, `pg_stat_statements`),
6 exact error strings copied from page bodies. Every expected page was checked to be indexed and
to contain the key term. `rag-mcp eval` runs each question through each variant with `top_k` 20,
records the rank of the first hit from an expected page, and reports Recall@1, Recall@5 (what
Claude reads), MRR, and p50/p95 latency around the whole search call, model inference included,
over three timed runs after one untimed warm-up. `eval/results.md` is the last run.

## Results (in the container, 3,807 chunks, 4-core Intel laptop)

| Variant | Recall@1 | Recall@5 | MRR | p50 ms | p95 ms |
|---|---|---|---|---|---|
| vector | 0.74 | 0.92 | 0.82 | 136 | 333 |
| keyword | 0.48 | 0.52 | 0.50 | 4 | 18 |
| hybrid | 0.74 | 0.92 | 0.83 | 183 | 458 |

Latency varies between runs on this laptop (hybrid p50 was 109 to 183 ms across four runs); the
ranking numbers were identical in every run. Two variants were measured and removed from the code:

| Rejected variant | Recall@5 | MRR | Why rejected |
|---|---|---|---|
| keyword, any word may match (OR tsquery) | 0.40 | 0.27 | matches 90% of chunks; ranking by `ts_rank_cd` alone is poor |
| hybrid with the OR keyword list | 0.92 | 0.66 | the noisy list drags MRR down by 0.17 |
| hybrid, keyword list weighted 0.5 or 0.3 in RRF | 0.92 | 0.83 | identical to weight 1: in RRF, presence in both lists dominates |

## Decision
Hybrid stays the default. On this corpus it ties vector on Recall@5 and edges MRR, but the reason
is in the per-question table: for two of the six exact error strings vector alone ranked the page
11th and 5th, hybrid ranked both 1st. That is the case the keyword half exists for, and it is the
case most likely in documents the panel brings. The cost is a rank or two on six natural-language
questions where a keyword match promoted a neighbouring page. Vector alone is one `mode` away.

## What the misses say
- `howto-clickhouse-cli` (not in the top 20): the page title is "Connect to a ClickHouse cluster
  with CLI" and the corpus has eight other ClickHouse connection pages; the question's
  `clickhouse-client` is not the page's wording. A reranker is the fix, not a bigger candidate list.
- `limit-oom` (rank 15) and `param-pg-idle-in-transaction` (rank 6): generic wording
  ("runs out of memory") matches many pages; `howto-keystore` (rank 10): the keyword list
  promoted the Kafka tools pages. All four are in the top 20, so a cross-encoder rescoring the
  top 20 would see them. That is the next quality step, costed in ADR 005.

## Consequences
- Any later change to chunking, the model or fusion is re-scored with `rag-mcp eval` first.
- 50 questions written by the author are not a benchmark: they say which variant is better on this
  corpus, not how good the system is in absolute terms. More questions and a second annotator are
  the obvious improvements.
