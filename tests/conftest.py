import hashlib
import os
from collections.abc import Iterator, Sequence
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg_pool import ConnectionPool

from rag_mcp import db
from rag_mcp.chunking import ChunkConfig
from rag_mcp.settings import Settings

DEVPORTAL = Path(__file__).resolve().parent.parent / "data" / "devportal"


def word_count(text: str) -> int:
    """Stand-in token counter for unit tests; the real tokenizer arrives with the embedder."""
    return len(text.split())


@pytest.fixture
def config() -> ChunkConfig:
    return ChunkConfig(target_tokens=40, max_tokens=50, min_tokens=6)


@pytest.fixture
def devportal() -> Path:
    if not DEVPORTAL.is_dir():
        pytest.skip("devportal clone missing; see README for the clone command")
    return DEVPORTAL


# --- shared fakes and fixtures for the ingest layer


class FakeEmbedder:
    """Deterministic stand-in: same text, same vector; no model, no network."""

    dim = 8

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        raw = [byte / 255 for byte in digest[: self.dim]]
        norm = sum(value * value for value in raw) ** 0.5 or 1.0
        return [value / norm for value in raw]


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture(scope="session")
def temp_database_url() -> Iterator[str]:
    """A throwaway database next to the configured one, dropped at the end of the session."""
    base_url = os.environ.get("DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag")
    name = f"rag_test_{os.getpid()}"
    with psycopg.connect(base_url, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = base_url.rsplit("/", 1)[0] + "/" + name
    yield url
    with psycopg.connect(base_url, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def test_settings(temp_database_url: str, tmp_path: Path) -> Settings:
    return Settings.from_env(
        {
            "DATABASE_URL": temp_database_url,
            "EMBEDDING_DIM": str(FakeEmbedder.dim),
            "EMBEDDING_MODEL": "fake",
            "DATA_ROOT": str(tmp_path),
            "CHUNK_TARGET_TOKENS": "40",
            "CHUNK_MAX_TOKENS": "50",
            "CHUNK_MIN_TOKENS": "6",
        }
    )


@pytest.fixture
def pool(test_settings: Settings) -> Iterator[ConnectionPool]:
    pool = db.connect(test_settings)
    with pool.connection() as conn:
        conn.execute("TRUNCATE sources CASCADE")
    yield pool
    pool.close()
