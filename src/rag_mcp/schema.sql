-- Applied on every container start inside one transaction under an advisory lock.
-- Every statement is idempotent. {dim} is the embedding width, injected from settings.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
    id            BIGSERIAL PRIMARY KEY,
    uri           TEXT        NOT NULL UNIQUE,      -- e.g. file:docs/products/kafka/howto/x.rst
    kind          TEXT        NOT NULL CHECK (kind IN ('text', 'file', 'url')),
    title         TEXT        NOT NULL,
    content_hash  TEXT        NOT NULL,             -- sha256 of the raw content; drives idempotent re-ingest
    chunk_count   INTEGER     NOT NULL DEFAULT 0,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id            BIGSERIAL PRIMARY KEY,
    source_id     BIGINT      NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    position      INTEGER     NOT NULL,             -- order within the source
    heading_path  TEXT        NOT NULL DEFAULT '',  -- "Page > Section > Subsection"
    text          TEXT        NOT NULL,
    token_count   INTEGER     NOT NULL,
    embedding     vector({dim}) NOT NULL,
    tsv           tsvector    GENERATED ALWAYS AS (
                      to_tsvector('english', heading_path || ' ' || text)
                  ) STORED,
    UNIQUE (source_id, position)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin       ON chunks USING gin (tsv);

-- Records which model built the embeddings so a config change cannot silently mix vectors.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
