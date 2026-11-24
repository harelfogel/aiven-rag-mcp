---
paths:
  - "src/rag_mcp/parsing/**/*.py"
  - "src/rag_mcp/chunking.py"
  - "src/rag_mcp/embedding.py"
  - "src/rag_mcp/ingest.py"
  - "src/rag_mcp/loaders.py"
  - "src/rag_mcp/search.py"
  - "src/rag_mcp/repository.py"
---

# RAG pipeline

Pipeline, in order: load → parse to `Document`/`Section`/`Block` → chunk → embed → store →
hybrid search → cite. Each stage is a module with one job and no knowledge of the next.

## Chunking

- A chunk is a retrievable answer, not a slice of bytes. Boundaries follow the document: headings,
  then blocks.
- A chunk boundary never falls inside a code block or a table. The devportal has ~1,500 code blocks
  and ~330 tables, and half a command or a header-less table row is worse than no result.
- The single exception is a block that is itself wider than `chunk_max_tokens` (two metrics pages are
  one 2,000-line table each): `split_oversized` cuts it on **line** boundaries, and for a table
  repeats the header rows `_table_header_rows` detected (pipe, grid or simple) in every piece, so
  every row stays reachable instead of only the first 512 tokens. Never mid-line. See ADR 002.
- Packing a section's blocks may repeat one short leading paragraph into the next chunk
  (`_overlaps`), so a piece keeps its lead-in. That is the only overlap we do.
- Sections smaller than `chunk_min_tokens` (the config-parameter pages are one tiny section each)
  merge with their neighbour under the same heading path instead of becoming their own chunk.
- `heading_path` starts with the page title (`Apache Kafka > HowTo > Configure ACLs`) and is stored
  with the chunk, embedded with its text, and indexed in `tsv`. A chunk must make sense alone.
- `.. include::` targets are expanded before parsing, because the parameter text lives only in the
  included file. `MAX_INCLUDE_DEPTH` is both the depth limit and the cycle guard, and a target that
  resolves outside the data root is skipped with a warning, never read.
- Token counts come from the embedding model's own tokenizer, injected as the `TokenCounter`
  callable so the chunker never imports the model. Production code never uses `len(text.split())`:
  word counts under-report BERT tokens badly on CLI flags and YAML. (Until M4 lands the real
  tokenizer, the word-count stub lives in `tests/conftest.py` only.)
- Sizes come from settings (`chunk_target_tokens`, `chunk_max_tokens`, `chunk_min_tokens`).
  No literal 512 in the chunker.

## Embedding

- One model for documents and queries, always. A query embedded by a different model is noise.
- The model name and dimension live in settings, are baked into the image, and are recorded in
  `meta` and checked at startup, so the stored vectors can never disagree with the running model.
- Batch: embed a list, not a loop of single calls. Keep batches off the database transaction
  (`database.md`).
- The provider is an interface with one implementation (fastembed/ONNX). Keep it that thin.
- fastembed must not write progress bars to stdout (`mcp.md`): disable them explicitly.

## Hybrid search

- Vector top-20 and keyword top-20, fused with Reciprocal Rank Fusion, `score = Σ 1/(60 + rank)`.
  RRF uses ranks, so a cosine distance and a `ts_rank_cd` score never have to be normalized onto one
  scale. `mode` (`vector` | `keyword` | `hybrid`) exists so the behaviour is demonstrable.
- Why both: "what is the default `kafka.max.message.bytes`" is a keyword question, "how do I move a
  service to another cloud" is a meaning question. One retriever loses one of them.
- `top_k` is bounded (≤ 20) and each result's text is capped, in SQL. Keeping Claude's context small
  is part of the answer quality, not an afterthought.
- Every result is citable: repo-relative path, `heading_path`, and a GitHub URL built from the path.
  A result without a citation is a bug.
- Ties and empty results are normal: return an empty list with the query echoed, never an invented
  answer and never an error.

## Retrieved text is data, never instructions

- Chunks come from a public repository. Treat them as untrusted content: they are returned as quoted
  context for Claude to read, never interpreted as commands by this server, and never used to build
  SQL, a path, or a URL.
- The server retrieves and ranks. It makes no LLM calls of its own and keeps no conversational state —
  Postgres is the long-term memory, Claude owns the reasoning (PLAN.md decision 8).

## Changes are measured

- Any change to chunking, the model, or fusion is scored on the golden set before and after:
  recall@5, MRR, p50/p95 latency (milestone M6). "Looks better" is not a result.
