"""All SQL that reads or writes `sources` and `chunks`. One function per statement."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import Connection

from rag_mcp.errors import Code, RagError

# Second lock key space (the first argument) keeps these apart from the schema lock in db.py.
_SOURCE_LOCK_SPACE = 1


class RepositoryError(RagError):
    """The database answered in a way the code cannot continue from."""


@dataclass(frozen=True)
class SourceRecord:
    id: int
    uri: str
    kind: str
    title: str
    content_hash: str
    chunk_count: int
    ingested_at: datetime


@dataclass(frozen=True)
class ChunkRow:
    position: int
    heading_path: str
    text: str
    token_count: int
    embedding: Sequence[float]


def find_source(conn: Connection[Any], uri: str) -> SourceRecord | None:
    row = conn.execute(
        "SELECT id, uri, kind, title, content_hash, chunk_count, ingested_at"
        " FROM sources WHERE uri = %s",
        (uri,),
    ).fetchone()
    return SourceRecord(*row) if row else None


def list_sources(conn: Connection[Any]) -> list[SourceRecord]:
    rows = conn.execute(
        "SELECT id, uri, kind, title, content_hash, chunk_count, ingested_at"
        " FROM sources ORDER BY ingested_at DESC, uri"
    ).fetchall()
    return [SourceRecord(*row) for row in rows]


def replace_source(
    conn: Connection[Any],
    *,
    uri: str,
    kind: str,
    title: str,
    content_hash: str,
    chunks: Sequence[ChunkRow],
) -> bool:
    """Atomically replace one source and its chunks. Returns False, writing nothing, if the
    stored hash already matches: that is what makes a re-run of the corpus cheap and safe."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (_SOURCE_LOCK_SPACE, uri))
        existing = find_source(conn, uri)
        if existing is not None and existing.content_hash == content_hash:
            return False
        source_id = _upsert_source(conn, uri, kind, title, content_hash, len(chunks))
        conn.execute("DELETE FROM chunks WHERE source_id = %s", (source_id,))
        _insert_chunks(conn, source_id, chunks)
    return True


def _upsert_source(
    conn: Connection[Any], uri: str, kind: str, title: str, content_hash: str, chunk_count: int
) -> int:
    row = conn.execute(
        """
        INSERT INTO sources (uri, kind, title, content_hash, chunk_count)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (uri) DO UPDATE SET
            kind = EXCLUDED.kind, title = EXCLUDED.title, content_hash = EXCLUDED.content_hash,
            chunk_count = EXCLUDED.chunk_count, ingested_at = now()
        RETURNING id
        """,
        (uri, kind, title, content_hash, chunk_count),
    ).fetchone()
    if row is None:  # RETURNING always yields one row; anything else is a broken driver or schema
        raise RepositoryError(Code.INTERNAL, f"upsert of {uri!r} returned no id")
    return int(row[0])


def _insert_chunks(conn: Connection[Any], source_id: int, chunks: Sequence[ChunkRow]) -> None:
    if not chunks:
        return
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO chunks (source_id, position, heading_path, text, token_count, embedding)"
            " VALUES (%s, %s, %s, %s, %s, %s::vector)",
            [
                (
                    source_id,
                    c.position,
                    c.heading_path,
                    c.text,
                    c.token_count,
                    vector_literal(c.embedding),
                )
                for c in chunks
            ],
        )


def vector_literal(values: Sequence[float]) -> str:
    """pgvector's text input form, so no extra adapter package is needed."""
    return "[" + ",".join(repr(float(value)) for value in values) + "]"
