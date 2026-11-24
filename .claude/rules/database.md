---
paths:
  - "src/rag_mcp/db.py"
  - "src/rag_mcp/repository.py"
  - "src/rag_mcp/schema.sql"
  - "tests/test_db_integration.py"
  - "tests/test_schema.py"
---

# Database: ACID writes, index-backed reads

All SQL lives in `repository.py` (reads and writes of `sources`/`chunks`) and `db.py` (pool and
schema). One function per query, plain parameterized SQL, no ORM: three tables plus pgvector and
tsvector operators do not justify SQLAlchemy.

## Transactions (the A, C, I and D of it)

- **Atomic unit = one source.** Re-ingesting a document is one `with connection.transaction():`
  block that does all of: upsert the `sources` row, delete that source's old `chunks`, insert the
  new ones, and write `chunk_count` and `content_hash`. A crash anywhere leaves the previous
  version intact. Never two transactions where one would do.
- **Consistency is declared in `schema.sql`, not in Python:** `UNIQUE(uri)`,
  `UNIQUE(source_id, position)`, `CHECK (kind IN (...))`, `NOT NULL`, and
  `REFERENCES sources(id) ON DELETE CASCADE` so no chunk can outlive its source.
  Add the constraint in the schema before you add the check in code.
- **Isolation.** Default READ COMMITTED is enough because one URI is only ever written inside one
  lock. Serialize concurrent ingests of the same document with
  `SELECT pg_advisory_xact_lock(1, hashtext(%s))` on the URI (or `SELECT ... FOR UPDATE` on the
  `sources` row) as the first statement in the transaction — the two-argument form keeps a key space
  of its own, separate from `_SCHEMA_LOCK_KEY` — do not rely on `ON CONFLICT` alone to
  order the delete and insert of chunks.
- **Durability.** Plain commit, no `synchronous_commit = off`. The named volume in
  `docker-compose.yml` is what survives a container rebuild.
- **Embed before you open the transaction.** Model inference takes seconds; a transaction holding
  row locks must not wait on CPU, disk, or the network. Compute hashes and vectors first, write last.
- Idempotency: read `content_hash` inside the transaction, and if it is unchanged, commit nothing and
  report `unchanged`. That is what makes a re-run of the full corpus cheap.
- DDL runs only in `apply_schema` under `pg_advisory_xact_lock(_SCHEMA_LOCK_KEY)`, so parallel
  container starts cannot race. Every statement there stays idempotent (`IF NOT EXISTS`).
- Connections come from the pool via `with pool.connection()`. No module-level connection, no
  `autocommit = True`, no cursor kept across calls.

## Queries: every statement that touches `chunks` uses an index

- **Vector search** must keep the shape the HNSW index can serve — the pgvector README is explicit:
  the query needs `ORDER BY` plus `LIMIT`, and the `ORDER BY` must be the bare distance operator in
  ascending order.

  ```sql
  SELECT id, source_id, heading_path, left(text, %s) AS text, embedding <=> %s::vector AS distance
  FROM chunks
  ORDER BY embedding <=> %s::vector
  LIMIT %s
  ```

  `<=>` is cosine distance and is the only operator that matches our
  `hnsw (embedding vector_cosine_ops)` index. `<->` (L2) or `<#>` (inner product) would silently
  fall back to a sequential scan over every chunk. Never wrap the ordering expression
  (`1 - (embedding <=> ...) DESC` is a seq scan), never `ORDER BY` an alias, never omit `LIMIT`.
- **Keyword search** uses the generated `tsv` column and its GIN index:
  `WHERE tsv @@ websearch_to_tsquery('english', %s) ORDER BY ts_rank_cd(tsv, ...) DESC LIMIT %s`.
  `websearch_to_tsquery` never raises on user punctuation, which `to_tsquery` does.
  The ranking happens after the index filter, so it does not cost an index.
- The two searches are two separate statements fused in Python by RRF (see `rag.md`): the mode flag
  stays trivial and each statement keeps a plan we can explain.
- Recall knob: `SELECT set_config('hnsw.ef_search', %s::text, true)` as the first statement of the
  search transaction (`true` = transaction-local, like `SET LOCAL`). Default is 40; higher means
  better recall and more time. The value comes from settings. The `%s::text` and the `set_config`
  are both needed, measured against our own db: `SET LOCAL hnsw.ef_search = %s` is
  `SyntaxError: syntax error at or near "$1"` (`SET` is a utility statement and takes no bind
  parameters), and an un-cast int gives
  `function set_config(unknown, smallint, boolean) does not exist`.
- If a search ever filters by source, remember HNSW applies the filter *after* the index scan, so a
  narrow filter returns fewer than `top_k` rows; the fix is a partial index or
  `hnsw.iterative_scan`, not a bigger `LIMIT`.
- Name the columns you need. No `SELECT *`. Cap text in SQL with `left(text, %s)` so a long chunk
  never crosses the wire.
- Writes are batched: `executemany` for a source's chunks, `COPY` only if a measurement says
  `executemany` is the bottleneck.
- No index on `chunks(source_id)` alone — `UNIQUE(source_id, position)` already leads with it.
  Every index must have a query that needs it; every query must have an index that serves it.

## Proof, not opinion

- Parameterized SQL only. Values go in `%s`; identifiers and the embedding width go through
  `psycopg.sql` composition (`render_schema`). Never an f-string in SQL.
- Each query in `repository.py` has an integration test that runs `EXPLAIN` on it and asserts the
  plan contains an index scan — that is how "must use an index" stays true after a schema edit.
- The model and dimension are recorded in `meta` and verified at startup (`_check_meta`), so a
  changed `EMBEDDING_MODEL` fails fast instead of mixing incompatible vectors.
