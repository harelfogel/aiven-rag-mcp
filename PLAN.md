# Plan: RAG MCP server over the Aiven devportal

Working plan for the home assignment. Decisions here are the ones I would defend;
each real trade-off also gets a short record in `docs/decisions/`.

## What I measured before deciding

- `aiven/devportal` is archived (last commit 2024-01). 817 RST + 28 Markdown files, 3.1 MB.
- ~950k tokens with the BERT tokenizer that MiniLM/bge use (694k with OpenAI's cl100k).
  60% of files exceed a 512-token embedding window, so chunking is the normal case.
- Content that will be asked about: ~1,500 code blocks, ~300 tables, config parameters
  written as one small RST section each, pulled into product pages via `.. include::`.
- Headings are underline-adorned (`=`, `-`, `~`, `^`, `*`, `#`); roles `:doc:`/`:ref:` everywhere.

## Architecture

```
Claude Code ──stdio (JSON-RPC)──► docker exec -i rag-mcp ──► MCP server (Python, mcp 2.3)
                                                                 │
                        ┌────────────────────────────────────────┼──────────────────────┐
                        │ ingest                                 │ search               │ list_sources
                        ▼                                        ▼                      ▼
              loader (text | file | url)                 embed query (bge-small)   SELECT sources
                        │                                        │
              parser → sections (RST / MD)            vector top-20  ┐
                        │                                           ├─ RRF ─► top_k
              chunker (≤512 tok, code/tables intact)   keyword top-20 ┘
                        │
              embed batches (fastembed, ONNX, CPU)
                        │
              Postgres 17 + pgvector  ── sources(hash) ── chunks(text, heading_path, embedding, tsv)
                                         HNSW (cosine) + GIN (tsvector), named volume
```

Two containers from one `docker compose up -d`: `db` (pgvector image, health-checked,
persistent volume) and `server` (this code, model baked in, idle until Claude runs the
MCP process inside it with `docker exec -i`).

## Decisions and trade-offs

| # | Decision | Why | What I gave up |
|---|---|---|---|
| 1 | Python 3.12, mcp 2.3.0, fastembed, psycopg 3, uv | embedding ecosystem; first-party SDK; ONNX keeps image ~150 MB vs ~900 MB with torch; lockfile for first-try builds | model choice limited to fastembed's list (provider is an interface) |
| 2 | `bge-small-en-v1.5`, env-configurable, baked into image | 512-token window keeps a step list or table row whole; 384 dims; ~3 min full ingest on a 4-core CPU; no network on first start | bge-base quality (eval decides if worth 3x ingest time) |
| 3 | Structure-aware chunking | corpus is tables, code and tiny parameter sections; fixed windows cut exactly what gets asked | a parser and its edge cases |
| 4 | Hybrid: pgvector cosine + Postgres FTS, fused with RRF; HNSW + GIN | params/limits are keyword questions, how-tos are meaning questions; RRF needs no score normalization | a reranker (next step), weighted fusion (needs tuning data) |
| 5 | Idempotent ingest by content hash, transactional replace, batched embedding | re-ingest is safe and cheap; incremental updates for free | per-chunk diffing |
| 6 | `schema.sql` applied at startup under an advisory lock | one schema, zero migration tooling; README needs no manual step | Alembic |
| 7 | `docker exec -i` as the stdio launcher | compose CLI prints to stdout and would corrupt the protocol | a one-shot `compose run` (documented as alternative if verified clean) |
| 8 | No memory beyond retrieval | the server is long-term retrieval memory; Claude owns the conversation | query log (next step, useful for eval) |
| 9 | Compact search output, top_k ≤ 20, text capped | keep Claude's context small and citable | returning whole pages |
| 10 | Tools: `ingest(source, kind, title)`, `search(query, top_k, mode)`, `list_sources` | explicit, typed, LLM-readable descriptions; `mode` demos vector vs keyword vs hybrid live | fewer knobs |

## Assumptions (also go in the README)

- "Whole repo" = every `.rst`/`.md` under devportal, includes resolved; images and build files skipped.
- A "file path" is a path under the mounted `./data` folder; anything else is rejected.
- Light RST parsing (headings, directives, code, tables, roles stripped), not a Sphinx build.
- Source citation = repo-relative path + heading path + a GitHub URL built from the path.
- devportal is archived; the same pipeline can ingest `aiven/aiven-docs` (Markdown) if wanted.

## Milestones (each one demoable)

| # | Milestone | Done when |
|---|---|---|
| M1 | Skeleton: pyproject, settings, compose, Dockerfile, schema, DB pool with retry | `docker compose up -d` creates schema; health passes; unit tests run |
| M2 | Parsers + chunker (RST, MD) with tests | code blocks and tables never split; heading paths correct on real devportal files |
| M3 | Loaders (text, file, url) with guards | path traversal and SSRF tests red→green; size caps |
| M4 | Embedding provider + ingest pipeline | full devportal ingest from CLI, idempotent re-run reports "unchanged" |
| M5 | Hybrid search + list_sources + MCP tools over stdio | tools callable from Claude Code; errors are ToolErrors |
| M6 | Evaluation: golden set, recall@5, MRR, p50/p95 latency, variants | results table in README |
| M7 | README, ADRs, fresh-clone run under 10 min, send email | a stranger can do it |

## Time budget

| When | Work |
|---|---|
| Mon night | plan, repo, Claude Code setup, M1 |
| Tue | M2, M3, M4, M5 |
| Wed | M6, M7, send repo link by evening |
| Thu | demo rehearsal only |

## Scale story (talking points, detail in README)

- **10x knowledge base:** ~10x ingest time → parallel embedding workers; HNSW `ef_search`/`m` tuning;
  partition chunks by source set; consider bge-base or a reranker once latency budget allows.
- **10x requests:** server is stateless → replicas behind Streamable HTTP transport; connection pool
  sized per replica; read replicas for Postgres; cache query embeddings; split ingest from serve.
- **Frequently changing content:** hash-based incremental re-ingest triggered by CI on the docs repo;
  stale chunks deleted in the same transaction; serve slightly stale results during re-index rather
  than block (availability over strict consistency, acceptable for docs).
