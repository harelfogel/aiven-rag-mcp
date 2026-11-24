"""Needs Postgres: `docker compose up -d db`. Leaves the database as it found it."""

import os
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection

from rag_mcp.settings import Settings
from rag_mcp.storage.db import SchemaError, apply_schema

pytestmark = pytest.mark.integration

SETTINGS = Settings.from_env(
    {"DATABASE_URL": os.environ.get("DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag")}
)


@pytest.fixture
def conn() -> Iterator[Connection[tuple[object, ...]]]:
    with psycopg.connect(SETTINGS.database_url) as c:
        yield c


def test_apply_schema_twice_is_idempotent(conn: Connection[tuple[object, ...]]) -> None:
    apply_schema(conn, SETTINGS)
    apply_schema(conn, SETTINGS)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    }
    assert {"sources", "chunks", "meta"} <= tables
    assert conn.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'").fetchone()


def test_model_mismatch_is_refused(conn: Connection[tuple[object, ...]]) -> None:
    apply_schema(conn, SETTINGS)
    with conn.transaction(force_rollback=True):
        conn.execute("UPDATE meta SET value = 'some-other-model' WHERE key = 'embedding_model'")
        with pytest.raises(SchemaError, match="embedding_model"):
            apply_schema(conn, SETTINGS)
