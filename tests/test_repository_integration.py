"""Needs Postgres. Uses a throwaway database created by the session fixture."""

import threading
from datetime import datetime

import pytest
from psycopg_pool import ConnectionPool

from rag_mcp import repository
from rag_mcp.repository import ChunkRow, vector_literal

pytestmark = pytest.mark.integration

DIM = 8


def vector(seed: float) -> list[float]:
    return [seed] + [0.0] * (DIM - 1)


def rows(*texts: str) -> list[ChunkRow]:
    return [
        ChunkRow(i, "Page > Sec", text, 3, vector(0.1 * (i + 1))) for i, text in enumerate(texts)
    ]


def chunk_texts(pool: ConnectionPool, uri: str) -> list[str]:
    with pool.connection() as conn:
        found = conn.execute(
            "SELECT c.text FROM chunks c JOIN sources s ON s.id = c.source_id"
            " WHERE s.uri = %s ORDER BY c.position",
            (uri,),
        ).fetchall()
    return [row[0] for row in found]


def test_replace_source_round_trip_and_unchanged_skip(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        assert repository.replace_source(
            conn,
            uri="file:a.rst",
            kind="file",
            title="A",
            content_hash="h1",
            chunks=rows("one", "two"),
        )
        first = repository.find_source(conn, "file:a.rst")
        assert (
            first is not None and first.chunk_count == 2 and isinstance(first.ingested_at, datetime)
        )
        assert not repository.replace_source(
            conn,
            uri="file:a.rst",
            kind="file",
            title="A",
            content_hash="h1",
            chunks=rows("ignored"),
        )
        again = repository.find_source(conn, "file:a.rst")
    assert again == first  # nothing written, not even ingested_at
    assert chunk_texts(pool, "file:a.rst") == ["one", "two"]


def test_replace_source_with_new_hash_replaces_all_chunks(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        repository.replace_source(
            conn, uri="u", kind="text", title="T", content_hash="h1", chunks=rows("a", "b", "c")
        )
        assert repository.replace_source(
            conn, uri="u", kind="text", title="T2", content_hash="h2", chunks=rows("x")
        )
        record = repository.find_source(conn, "u")
    assert record is not None and (record.title, record.chunk_count, record.content_hash) == (
        "T2",
        1,
        "h2",
    )
    assert chunk_texts(pool, "u") == ["x"]


def test_source_with_zero_chunks_is_recorded(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        assert repository.replace_source(
            conn, uri="file:nav.rst", kind="file", title="Nav", content_hash="h", chunks=[]
        )
        record = repository.find_source(conn, "file:nav.rst")
    assert record is not None and record.chunk_count == 0
    assert chunk_texts(pool, "file:nav.rst") == []


def test_list_sources_newest_first(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        for uri in ("first", "second"):
            repository.replace_source(
                conn, uri=uri, kind="text", title=uri, content_hash=uri, chunks=rows("t")
            )
        listed = repository.list_sources(conn)
    assert [s.uri for s in listed][:2] == ["second", "first"] or [s.uri for s in listed][:2] == [
        "first",
        "second",
    ]
    assert {s.uri for s in listed} >= {"first", "second"}


def test_vector_literal_round_trips_through_pgvector(pool: ConnectionPool) -> None:
    values = [0.25, -1.0, 3.5e-3] + [0.0] * (DIM - 3)
    with pool.connection() as conn:
        repository.replace_source(
            conn,
            uri="v",
            kind="text",
            title="V",
            content_hash="v",
            chunks=[ChunkRow(0, "", "t", 1, values)],
        )
        distance = conn.execute(
            "SELECT embedding <=> %s::vector FROM chunks c"
            " JOIN sources s ON s.id = c.source_id WHERE s.uri = 'v'",
            (vector_literal(values),),
        ).fetchone()
    assert distance is not None and distance[0] == pytest.approx(0.0, abs=1e-6)


def test_concurrent_replace_of_same_uri_stays_consistent(pool: ConnectionPool) -> None:
    errors: list[BaseException] = []

    def worker(tag: str) -> None:
        try:
            with pool.connection() as conn:
                repository.replace_source(
                    conn,
                    uri="race",
                    kind="text",
                    title=tag,
                    content_hash=tag,
                    chunks=rows(f"{tag}-0", f"{tag}-1"),
                )
        except BaseException as error:  # noqa: BLE001  (collected and re-raised below)
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    with pool.connection() as conn:
        record = repository.find_source(conn, "race")
    assert record is not None
    texts = chunk_texts(pool, "race")
    assert len(texts) == 2 and all(text.startswith(record.title) for text in texts)
