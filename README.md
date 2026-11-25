# aiven-rag-mcp

An MCP server that lets Claude ingest documents and answer questions over them with retrieval.
The knowledge base is the whole [aiven/devportal](https://github.com/aiven/devportal) repository
(817 RST and 28 Markdown files). Three tools over stdio: `ingest`, `search`, `list_sources`.
Local embeddings (bge-small, ONNX, CPU), PostgreSQL 17 with pgvector, one `docker compose up`.

## Quickstart

You need Docker with Compose, and `git`. Nothing else: Python, the model and the database all live
in the containers.

**1. Get the code and the knowledge base** (15 s):

```bash
git clone https://github.com/harelfogel/aiven-rag-mcp.git
cd aiven-rag-mcp
git clone --depth 1 https://github.com/aiven/devportal data/devportal   # ~20 MB of RST and Markdown
```

**2. Build and start the database and the server** (about 3 minutes the first time):

```bash
docker compose up -d --build --wait
```

It returns when both containers report `Healthy`. The build installs the Python dependencies and
bakes the embedding model into the image, so nothing is downloaded at run time. On start the server
applies the database schema itself (`src/rag_mcp/storage/schema.sql`, idempotent, under an advisory
lock), loads the model and waits for Claude. `docker compose logs server` ends with a
`ready; idle until ...` line.

**3. Ingest one product** (3 to 5 minutes), so you can ask questions right away:

```bash
docker compose exec server rag-mcp ingest devportal/docs/products/kafka
```

```
ingest done: 171 ingested, 0 unchanged, 0 failed, 954 new chunks in ...
```

**4. [Add it to Claude](#add-it-to-claude)** and ask a question, for example the one in the
[example session](#example-session).

**5. Ingest the rest** (optional, 9 to 12 minutes). Pages already indexed are skipped, and every
page is searchable as soon as it is written:

```bash
docker compose exec server rag-mcp ingest devportal/docs
```

```
ingest done: 617 ingested, 171 unchanged, 0 failed, 2853 new chunks in ...
```

The full ingest keeps every CPU core busy, so open new Claude sessions before or after it, not
during it (see [Troubleshooting](#troubleshooting)).

Measured on a 4-core Intel laptop, Docker Desktop with 8 GB, from an empty folder with the build
cache cleared (2026-11-24):

| Step | Time |
|---|---|
| `git clone` of this repo and of devportal | 15 s |
| `docker compose up -d --build --wait`, first time | 2 min 50 s (134 s build incl. model download, 36 s start) |
| ingest of one product, `devportal/docs/products/kafka` (171 pages, 954 chunks) | 5 min |
| full ingest of `devportal/docs` (788 pages, 3,807 chunks) | 12 min (736 s) |
| second ingest run, nothing changed | 3 s |
| server launch by Claude Code | 4 to 6 s |

A re-run on the development stack on 2026-11-25, with other work competing for the CPU, took 3 min
for Kafka and 12 min 15 s (734.7 s) for the remaining 617 pages: expect 12 to 16 minutes for the
whole corpus on a busy laptop.

So the server is running in Claude about 3 minutes after the clone and answers questions about
Kafka at about 8 minutes; the rest of the corpus fills in while you ask.

## Add it to Claude

**Claude Code**, from any folder:

```bash
claude mcp add aiven-docs-rag -- docker exec -i rag-mcp rag-mcp serve
```

Or open Claude Code inside this repository: `.mcp.json` already declares the server and Claude Code
asks once whether to trust it. **Claude Desktop** takes the same block in its
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aiven-docs-rag": {
      "command": "docker",
      "args": ["exec", "-i", "rag-mcp", "rag-mcp", "serve"]
    }
  }
}
```

`docker exec -i` starts one MCP process per Claude session inside the already running container,
which keeps stdout clean for the protocol (`docker compose run` would print its own lines there).

Check that it is connected: `/mcp` in Claude Code lists `aiven-docs-rag` as connected, and asking
Claude to "list the sources" returns the totals (171 sources and 954 chunks after step 3, 788 and
3,807 after step 5).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Claude Code says the server timed out on connect | the server took longer than Claude Code's 30 s startup limit, almost always because a full ingest is using every CPU core (measured during one: 15.5 s for `rag-mcp serve` to start and answer `initialize` instead of 4 to 6 s, and one Claude Code session timed out) | wait for the ingest to finish, then `/mcp` and reconnect; or start Claude Code with `MCP_TIMEOUT=60000 claude` |
| `Error: No such container: rag-mcp` | the containers are not running | `docker compose up -d --wait` |
| tools stop answering after `docker compose up` or a rebuild | the old MCP process belonged to the old container | `/mcp` in Claude Code and reconnect |
| Claude's first `search` fails with `query: Field required`, then works | Claude Code loads tool schemas lazily and sometimes calls before reading them | nothing to do; the server rejects the empty call and the retry is correct |
| answers about one product are fine, others come back off topic | that product is not ingested yet | ask Claude to list the sources, then ingest the folder you need |
| `ingest` says `PATH must exist under the data root` | the path is relative to `./data`, which the container mounts as `/data` | use `devportal/docs/...`, not `data/devportal/...` |

## Example session

A real `claude -p` run against this server (Claude Sonnet, three turns, about 8 cents):

> **User:** What is the kafka_connect setting under private_access on Aiven for Apache Kafka, and what does it do? Cite the source.
>
> **Tool call:** `search` `{"query": "kafka_connect setting under private_access Aiven for Apache Kafka"}`
>
> **Claude:** `private_access.kafka_connect` is a boolean setting on Aiven for Apache Kafka. When enabled,
> clients can connect to Kafka Connect using a DNS name that always resolves to the service's private
> IP addresses. The docs say it is "only available in certain network locations", so it won't work
> everywhere. [...]
> **Source:** "Advanced parameters for Aiven for Apache Kafka®", section `private_access > kafka_connect`:
> https://github.com/aiven/devportal/blob/main/docs/products/kafka/reference/advanced-params.rst

Other questions that worked in testing: "Using the Aiven CLI, how do I create a Kafka topic with a
30 minute retention?" (Claude found `avn service topic-create --retention` and said honestly that
the flag is in hours), and "What is the maximum number of connections for an Aiven for PostgreSQL
service on a 4 GB plan?" (100, with the page link).

What a `search` result looks like to Claude, text trimmed:

```json
{
  "query": "maximum number of connections for PostgreSQL on a 4 GB plan",
  "mode": "hybrid",
  "hits": [
    {
      "rank": 1,
      "score": 0.03028,
      "title": "Manage connection pooling",
      "heading_path": "Manage connection pooling > Manage connection pools",
      "text": "To manage the connection pools, take the following steps:\n\n1. Log in to Aiven Console and select your Aiven for PostgreSQL service.\n\n2. In your service's page, [...]",
      "source": "file:devportal/docs/products/postgresql/howto/manage-pool.rst",
      "url": "https://github.com/aiven/devportal/blob/main/docs/products/postgresql/howto/manage-pool.rst"
    }
  ]
}
```

The tools:

| Tool | Arguments | Returns |
|---|---|---|
| `search` | `query`, `top_k` 1 to 20 (default 5), `mode` hybrid, vector or keyword | ranked chunks with title, heading path, text, source and a citation link |
| `ingest` | `source`, `kind` text, file or url, optional `title` | source id, chunk count, `ingested` or `unchanged` |
| `list_sources` | `limit`, `offset` | totals and one page of sources, newest first |

Refusals come back as tool errors with a code the model can act on, for example
`bad_request: path must stay under /data` or `too_large: file is 6291456 bytes, cap is 5000000`.

## Environment variables

Every knob is an environment variable with a validated default; `.env.example` lists them all with
comments, and `docker compose` reads a `.env` file next to it. None are required: the defaults run the
full stack, and there is no API key anywhere. The ones you might change:

| Variable | Default | Why you would change it |
|---|---|---|
| `POSTGRES_PASSWORD` | `rag` | anything other than a laptop; the port is bound to 127.0.0.1 only |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM` | `BAAI/bge-small-en-v1.5`, `384` | another fastembed model; needs `docker compose build` and a fresh volume (`docker compose down -v`), because the server refuses to mix vectors from two models |
| `CHUNK_TARGET_TOKENS` | `400` | smaller chunks, more of them; re-run the eval before keeping it |
| `HNSW_EF_SEARCH` | `100` | vector recall against latency at a larger corpus |
| `INGEST_MAX_BYTES` | `5000000` | the cap on one text, file or URL |
| `LOG_LEVEL` | `INFO` | `DEBUG` to see every query; logs go to stderr |

## Architecture

```
Claude Code ──stdio──► docker exec -i rag-mcp rag-mcp serve ──► MCP server (Python 3.12, mcp 2.3)
                                                                   │
            ┌──────────────────────────────────────────────────────┼───────────────────────────┐
            │ ingest                                               │ search                    │ list_sources
            ▼                                                      ▼                           ▼
   loading/  text | file (under /data) | url (SSRF-guarded)   embed query (bge-small)     count + page
            │                                                      │
   parsing/  RST, Markdown → sections with heading paths     vector top 20 ─┐
            │                                                               ├─ RRF ─► top_k, cited
   chunking  ≤512 tokens, code and tables kept whole          keyword top 20 ┘
            │
   embedding fastembed (ONNX, CPU), batched
            │
   storage/  Postgres 17 + pgvector: sources(uri, hash) ── chunks(text, heading_path, embedding, tsv)
             HNSW (cosine) + GIN (full text), one transaction per source, named volume
```

The source tree follows that order: `src/rag_mcp/loading`, `parsing`, `chunking.py`,
`embedding.py`, `storage`, `ingest.py`, `search.py`, `server` (the three tools, every model-facing
string in `prompts.py`, one error boundary) and `evaluation`. `cli.py` has `up` (apply schema, warm
the model, idle), `serve` (the MCP process), `ingest` and `eval`.

A chunk is a retrievable answer, not a slice of bytes. The RST parser produces sections with their
heading path ("Advanced parameters for Aiven for Apache Kafka® > private_access > kafka_connect");
the chunker packs a section's blocks up to 400 tokens, never cuts inside a code block or a table,
merges tiny neighbouring sections, and splits only a block wider than the window by lines with the
table header repeated. The heading path is stored once and prepended at embedding time, so a
three-line parameter chunk that never says "Kafka" is still found for a Kafka question.

## Decisions and trade-offs

Each one has a longer record in `docs/decisions/`.

| Decision | Why | What it cost |
|---|---|---|
| Python, fastembed (ONNX), psycopg 3, uv lockfile | embedding ecosystem; 499 MB image instead of ~1 GB with torch; exact versions on every machine | model choice limited to fastembed's list; the provider is an interface |
| bge-small-en-v1.5, baked into the image | 512-token window keeps a step list or a table row whole; 384 dims; no network on first start | bge-base quality; an image rebuild to change models |
| Structure-aware chunking, not fixed windows | the corpus is 1,505 code blocks and 331 tables; a blind cut lands inside the command you need | 450 lines of parser and chunker with their own edge cases (ADR 002) |
| Includes expanded before parsing, hash over the expanded text | the config parameters live only in included files; an edited include must re-ingest its pages | found on the first real run, not in a unit test (ADR 004) |
| Hybrid search, fused by reciprocal rank fusion | exact error strings and identifiers are keyword questions, how-tos are meaning questions; RRF needs no score normalization | a slightly slower search than vector alone (ADR 005) |
| Schema applied at startup under an advisory lock | no manual step, no migration tool for three tables | a schema change means a fresh volume (ADR 001) |
| Idempotent ingest, one transaction per source | re-running the corpus costs 3 seconds; a crash leaves the old version intact | a one-character edit re-embeds the whole page |
| Standard-library HTTP with an SSRF guard on every hop | zero dependencies to justify | DNS rebinding between check and connect is not caught (ADR 003) |
| `docker exec -i` as the launcher | stdout stays pure JSON-RPC | the container must be running first |
| No memory beyond retrieval | the server is long-term retrieval memory; Claude owns the conversation | no query log for later analysis |

Why not Sphinx or docutils to parse the RST: `ingest` must accept a pasted string, one file or a URL,
and a Sphinx build wants a whole project with a `conf.py`; plain docutils fails on the Sphinx roles
used about 2,000 times in the corpus and on the absolute includes. If the evaluation had blamed the
parser, swapping it behind `parse()` leaves everything downstream untouched. Why no Alembic: it would
bring SQLAlchemy along to version a schema whose data re-ingests in minutes.

## Evaluation

`eval/golden_set/` holds 50 questions written against specific devportal pages: 8 configuration
parameters, 8 limits, 18 how-to steps, 10 bare identifiers such as `retention.ms`, and 6 exact error
strings copied from page bodies. `rag-mcp eval` runs each through each mode with `top_k` 20 and
records the rank of the first hit from the expected page. Recall@5 is the share of questions whose
page is among the five chunks Claude reads; MRR averages 1 / rank. Latency is around the whole search
call, model included, three timed runs after a warm-up. Last run, in the container, 2026-11-24:

| Mode | Recall@1 | Recall@5 | MRR | p50 ms | p95 ms |
|---|---|---|---|---|---|
| vector | 0.74 | 0.92 | 0.82 | 115 | 421 |
| keyword | 0.48 | 0.52 | 0.50 | 3 | 7 |
| hybrid (default) | 0.74 | 0.92 | 0.83 | 111 | 232 |

By kind, hybrid: errors 1.00, identifiers 1.00, how-to 0.89, limits 0.88, parameters 0.88. The four
misses are named in `eval/results.md`, with every question's rank per mode.

What the numbers decided: the first run, with natural-language questions only, had vector ahead of
hybrid. Adding identifiers and error strings showed why the keyword half earns its place: for two of
the six error strings vector alone ranked the page 11th and 5th, hybrid ranked both first. An
OR-style keyword query and weighted fusion were measured and removed (ADR 006). With 50 questions one
question is two points, so these numbers rank the variants on this corpus; they are not an absolute
benchmark.

Reproduce: `docker compose exec server rag-mcp eval` prints the same report.

## Assumptions

- "The whole repo" means every `.rst` and `.md` under `devportal/docs`, with `.. include::` files
  resolved into the pages that use them. Images, build files and the repository's own README are not
  indexed. devportal is archived (last commit January 2024); the same pipeline ingests any folder of
  RST or Markdown under `./data`, including [aiven/aiven-docs](https://github.com/aiven/aiven-docs).
- A "file path" given to `ingest` is a path under the mounted `./data` folder; anything else is
  refused. A URL must be public http(s) and serve text, Markdown, RST or HTML.
- RST is parsed lightly (headings, directives, code, tables, roles stripped), not built with Sphinx.
- A citation is the repo-relative path, the heading path and a GitHub URL built from the path.
  Pasted text is identified by a hash of its content; the same paste twice is one source.
- The default database password is fine for a laptop: the port is bound to localhost only and the
  image contains no credentials.
- One Postgres container and one server process, as the assignment allows.

## Limits, and what I would do next

- **No reranker.** All but one of the evaluation misses are inside the top 20; a cross-encoder
  rescoring those 20 is the next quality step. fastembed ships one; the cost is about 200 MB and 100
  to 300 ms per query on CPU, so it is a measured decision, not a default.
- **Keyword search requires every query word to match.** Long questions mostly rely on the vector
  half. The OR variant measured worse; a `simple` text-search configuration for dotted identifiers
  is the untested alternative.
- **No similarity cut-off.** An off-topic question still gets its nearest neighbours; the tool
  description tells Claude to say so when nothing relevant comes back. A distance threshold tuned on
  the golden set is a small follow-up.
- **Ingest is single-process CPU inference**, 12 minutes for the corpus. It is a one-time cost: a
  re-run with nothing changed takes 3 seconds and a changed page re-embeds only that page. The
  per-source lock already makes parallel workers safe; see the scaling section.
- **Ingest and search share the CPU.** The model has no thread cap, so ONNX Runtime uses every core
  during a full ingest: `rag-mcp serve` then took 15.5 s to start and answer `initialize` instead of
  4 to 6 s, and one Claude Code session timed out at its 30 s limit. They are already separate processes; a thread would share the
  same cores. Fix: an `EMBEDDING_THREADS` setting passed to the model so ingest leaves cores free,
  and at scale a separate ingest worker.
- **RST substitutions are not expanded.** A placeholder such as `|mysql_connections_per_<4G|`
  reaches the index as raw text, so the numbers it stands for are missing from that MySQL page.
  The corpus defines 18 of them, mostly in tables. Fix: expand them before parsing, like includes.
- **At this size the vector query does not use its HNSW index.** With `HNSW_EF_SEARCH=100`, the
  value the server sets, Postgres estimates the index as dearer than reading all 3,807 rows and
  picks the full scan: 16 to 21 ms. With the default of 40 it picks the index: 1.3 to 1.6 ms
  (`EXPLAIN ANALYZE`, three runs each, 2026-11-25; a real `search` call through the server raised
  the table's sequential-scan count, not the index's). The scan is exact, so quality does not
  suffer, and it is a small part of a 111 ms search. It also means the evaluation's recall was
  measured on exact search; at 40 the search becomes approximate and recall must be re-measured. It does grow with the corpus, so before 10x: re-run
  the eval with `HNSW_EF_SEARCH=40` and keep the lower value if recall holds. The `EXPLAIN` tests
  prove the index can serve the query, not that the planner picks it. No index is missing: the
  keyword query uses its GIN index in 0.5 ms.
- **A parser or chunker change re-ingests everything** once `PIPELINE_VERSION` is bumped; there is
  no per-chunk diffing.
- **DNS rebinding** between the SSRF check and the connect is not pinned. Fix: a custom connection
  that connects to the checked IP, or an HTTP library with that hook.
- **Claude Code loads MCP tool schemas lazily.** Occasionally Claude's first `search` call arrives
  with no arguments, gets `query: field required`, and retries correctly. That is the client's
  behaviour; the server's part is to reject clearly and keep answering.
- **The golden set was written by the author.** More questions and a second annotator would make the
  numbers stronger.

## Scaling to 10x

Numbers from this machine; the arithmetic is shown so it can be redone for another one.

- **10x knowledge base** (about 38,000 chunks, 7 million tokens). Ingest is the bottleneck: 736 s
  today, so about 2 hours single-process. The fix is N embedding workers, one source each; the
  per-URI advisory lock already makes that safe, and Postgres writes are a few percent of the time.
  Storage is trivial: 23 MB of chunks and 9 MB of indexes today, so about 320 MB. HNSW keeps the
  vector query sub-linear once the planner chooses it, which today depends on `HNSW_EF_SEARCH` (see
  Limits); that is the recall knob to re-tune with the eval, and `m` at build time.
  A reranker becomes more valuable as the candidate pool gets noisier.
- **10x request volume.** The server is stateless; everything durable is in Postgres. Today one
  process answers a hybrid search in 111 ms median, of which the query embedding is most. Replicas
  behind the Streamable HTTP transport instead of stdio, a connection pool per replica, a cache for
  repeated query embeddings, read replicas of Postgres, and ingest separated from serving.
- **Frequently changing content.** Re-ingest is already incremental by content hash: an unchanged
  corpus costs 3 seconds, a changed page is one transaction that replaces its chunks. Trigger it from
  CI on the docs repository. During a re-index the old version keeps serving until its transaction
  commits: slightly stale results over a blocked search is the right trade for documentation.

## Development

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -q -m "not integration"      # 125 unit tests, no Docker
docker compose up -d db
uv run pytest -q -m integration            # 42 tests against Postgres, a throwaway database each session
uv run pytest -q                           # everything, including the real model and the stdio process
```

`tests/unit` needs nothing installed beyond `uv sync`; `tests/integration` needs the database
container and, for the model tests, one download of the 67 MB model. `docs/decisions/` holds the
decision records and `docs/glossary.md` the terms.
