# 005: Hybrid search, fused with reciprocal rank fusion

## Context
The test questions are a configuration parameter, a limit, a step in a how-to. A parameter name
such as `retention.ms` is an exact-string question; "how do I move a service to another cloud"
is a question of meaning. A vector index alone blurs the first kind, keyword search alone misses
the second.

## Options
1. Vector search only: simplest, weak on exact identifiers.
2. Weighted sum of cosine similarity and `ts_rank_cd`: the two scores live on different scales, so
   the weights mean nothing without normalization and a labelled set to tune them on.
3. Run both and fuse by rank (RRF): score = sum of 1 / (60 + rank) over the lists a chunk is in.

## Decision
Option 3, two separate statements fused in Python. Vector top 20 uses the bare `<=>` operator with
`ORDER BY ... LIMIT` so the HNSW index serves it; keyword top 20 uses `websearch_to_tsquery` on the
generated `tsv` column and its GIN index. Both shapes have an `EXPLAIN` test that fails if a
schema edit stops them using their index. A `mode` argument (`vector`, `keyword`, `hybrid`) makes
each half demonstrable. Results carry the chunk text cut to a fixed length in SQL, the heading
path, the stored source and a GitHub link, so Claude can cite. `top_k` outside 1 to 20 is
rejected, never clamped.

Worked example: A is 1st by meaning and absent from the keyword list, 1/61 = 0.0164. B is 2nd in
both lists, 1/62 + 1/62 = 0.0323. B wins: two independent methods agreeing beats one method
liking A.

## Consequences
- Measured over `docker exec` on a 4-core Intel Mac, real model, 3,807 chunks: median 194 ms and
  95th percentile 269 ms per search, 38 ms for keyword only.
- `websearch_to_tsquery` requires every word to match, so long natural-language questions often
  get an empty keyword list and lean on the vector half; the top hit then scores exactly 1/61.
  Dotted names such as `retention.ms` are one token, so a query for just `retention` does not
  match them by keyword. M6 measures whether an OR query or a second `simple`-config column earns
  its place.
- No similarity threshold: the vector side always returns its nearest neighbours, so an off-topic
  question still gets results. Claude is told to say so when nothing relevant comes back; a
  distance cut-off is the next step if evaluation shows it matters.
- No reranker (a cross-encoder rescoring the top 20): the best remaining quality lever, about
  200 MB and 100 to 300 ms more per query on CPU, so left as the documented next step.
