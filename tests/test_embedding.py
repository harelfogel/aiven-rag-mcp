"""Loads the real model (67 MB, cached after the first run)."""

import pytest

from rag_mcp.embedding import EmbeddingError, FastEmbedEmbedder
from rag_mcp.settings import Settings

pytestmark = pytest.mark.slow

SETTINGS = Settings.from_env({"DATABASE_URL": "postgresql://x/y"})


@pytest.fixture(scope="module")
def embedder() -> FastEmbedEmbedder:
    return FastEmbedEmbedder.from_settings(SETTINGS)


def test_embedder_dim_matches_settings_and_vectors_are_unit_length(
    embedder: FastEmbedEmbedder,
) -> None:
    vectors = embedder.embed_documents(["Kafka topic retention", "PostgreSQL extensions"])
    assert embedder.dim == SETTINGS.embedding_dim == 384
    assert [len(v) for v in vectors] == [384, 384]
    for vector in vectors:
        assert sum(x * x for x in vector) == pytest.approx(1.0, abs=1e-3)
    assert len(embedder.embed_query("how to set retention")) == 384
    assert embedder.embed_documents([]) == []


def test_count_tokens_is_exact_and_never_truncated(embedder: FastEmbedEmbedder) -> None:
    assert embedder.count_tokens("kafka_connect") > 2  # sub-word pieces plus [CLS]/[SEP]
    assert embedder.count_tokens("word " * 600) > 512  # the counter ignores the 512 truncation


def test_query_longer_than_the_window_is_truncated_not_rejected(
    embedder: FastEmbedEmbedder,
) -> None:
    assert len(embedder.embed_query("kafka " * 2000)) == 384


def test_unknown_model_fails_with_embedding_error() -> None:
    bad = Settings.from_env(
        {"DATABASE_URL": "postgresql://x/y", "EMBEDDING_MODEL": "no/such-model"}
    )
    with pytest.raises(EmbeddingError, match="cannot load"):
        FastEmbedEmbedder.from_settings(bad).count_tokens("x")


def test_dimension_mismatch_fails_fast() -> None:
    wrong = Settings.from_env({"DATABASE_URL": "postgresql://x/y", "EMBEDDING_DIM": "768"})
    with pytest.raises(EmbeddingError, match="EMBEDDING_DIM"):
        FastEmbedEmbedder.from_settings(wrong).embed_query("x")
