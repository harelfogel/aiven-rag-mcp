"""Postgres access: one connection pool per process, schema applied at startup.

The pool handles "database not ready yet" (it retries with backoff until the timeout)
and "connection lost" (connections are health-checked when handed out).
"""

from __future__ import annotations

import logging
from importlib import resources
from typing import Any

from psycopg import Connection, sql
from psycopg_pool import ConnectionPool

from rag_mcp.settings import Settings

log = logging.getLogger(__name__)

# Any constant works; every process must use the same one so concurrent starts serialize.
_SCHEMA_LOCK_KEY = 7_425_001


class SchemaError(RuntimeError):
    """The existing database is incompatible with the current settings."""


def connect(settings: Settings) -> ConnectionPool:
    """Open the pool, wait for Postgres, apply the schema. Safe to call on every start."""
    pool = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=settings.db_pool_max,
        open=False,
        check=ConnectionPool.check_connection,
    )
    log.info("connecting to Postgres (timeout %.0fs)", settings.db_connect_timeout_s)
    pool.open(wait=True, timeout=settings.db_connect_timeout_s)
    with pool.connection() as conn:
        apply_schema(conn, settings)
    log.info("schema ready (%s, %d dims)", settings.embedding_model, settings.embedding_dim)
    return pool


def render_schema(dim: int) -> sql.Composed:
    """Fill the embedding width into schema.sql. DDL cannot take bind parameters."""
    text = resources.files("rag_mcp").joinpath("schema.sql").read_text()
    return sql.SQL(text).format(dim=sql.Literal(dim))


def apply_schema(conn: Connection[Any], settings: Settings) -> None:
    """Create extension, tables and indexes if missing, then verify the stored model matches."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
        conn.execute(render_schema(settings.embedding_dim))
        _check_meta(
            conn,
            {
                "embedding_model": settings.embedding_model,
                "embedding_dim": str(settings.embedding_dim),
            },
        )


def _check_meta(conn: Connection[Any], expected: dict[str, str]) -> None:
    """First start records the values; later starts must match them."""
    for key, value in expected.items():
        row = conn.execute("SELECT value FROM meta WHERE key = %s", (key,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO meta (key, value) VALUES (%s, %s)", (key, value))
        elif row[0] != value:
            raise SchemaError(
                f"database has {key}={row[0]!r} but settings say {value!r}; "
                "re-create the volume or restore the setting"
            )
