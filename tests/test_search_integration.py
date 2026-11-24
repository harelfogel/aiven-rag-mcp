"""Hybrid search against real Postgres (full-text and pgvector) with the fake embedder."""

from dataclasses import replace
from pathlib import Path

import pytest
from psycopg_pool import ConnectionPool

from rag_mcp import repository
from rag_mcp.chunking import embed_text
from rag_mcp.ingest import IngestPipeline
from rag_mcp.loaders import SourceKind
from rag_mcp.search import SearchConfig, SearchMode, SearchResponse, search
from rag_mcp.settings import Settings
from tests.conftest import FakeEmbedder

pytestmark = pytest.mark.integration

PAGES = {
    "docs/kafka-retention.rst": (
        "Topic retention\n===============\n\n"
        "Set ``retention.ms`` to control how long Apache Kafka keeps messages in a topic.\n"
    ),
    "docs/connect.rst": (
        "Kafka Connect\n=============\n\nPrivate access\n--------------\n\n"
        "``kafka_connect``\n~~~~~~~~~~~~~~~~~\n*boolean*\n\n"
        "Allow clients to reach kafka_connect through the private network address.\n"
    ),
    "docs/postgres.rst": (
        "PostgreSQL extensions\n=====================\n\n"
        "Install pg_stat_statements to see which queries are slow on a service.\n"
    ),
}


@pytest.fixture
def config(test_settings: Settings) -> SearchConfig:
    return SearchConfig.from_settings(test_settings)


@pytest.fixture
def loaded(
    test_settings: Settings, pool: ConnectionPool, fake_embedder: FakeEmbedder, tmp_path: Path
) -> ConnectionPool:
    pipeline = IngestPipeline.from_settings(test_settings, pool, fake_embedder)
    for relative, text in PAGES.items():
        (tmp_path / relative).parent.mkdir(exist_ok=True)
        (tmp_path / relative).write_text(text)
        pipeline.ingest(SourceKind.FILE, relative)
    return pool


def run(
    pool: ConnectionPool,
    embedder: FakeEmbedder,
    config: SearchConfig,
    query: str,
    mode: SearchMode = SearchMode.HYBRID,
    top_k: int = 5,
) -> SearchResponse:
    return search(pool, embedder, query, top_k=top_k, mode=mode, config=config)


def titles(response: SearchResponse) -> list[str]:
    return [hit.title for hit in response.hits]


def test_keyword_mode_finds_dotted_and_snake_case_identifiers(
    loaded: ConnectionPool, fake_embedder: FakeEmbedder, config: SearchConfig
) -> None:
    dotted = run(loaded, fake_embedder, config, "retention.ms", SearchMode.KEYWORD)
    assert titles(dotted) == ["Topic retention"]
    snake = run(loaded, fake_embedder, config, "kafka_connect", SearchMode.KEYWORD)
    assert titles(snake) == ["Kafka Connect"]  # kafka_connect is the phrase "kafka connect"
    stats = run(loaded, fake_embedder, config, "pg_stat_statements", SearchMode.KEYWORD)
    assert titles(stats) == ["PostgreSQL extensions"]


def test_keyword_mode_with_no_match_returns_an_empty_list_not_an_error(
    loaded: ConnectionPool, fake_embedder: FakeEmbedder, config: SearchConfig
) -> None:
    response = run(loaded, fake_embedder, config, "zzzzqqqq", SearchMode.KEYWORD)
    assert response.hits == () and response.query == "zzzzqqqq"


def test_vector_mode_ranks_the_identical_text_first(
    loaded: ConnectionPool, fake_embedder: FakeEmbedder, config: SearchConfig
) -> None:
    with loaded.connection() as conn:
        stored = repository.keyword_candidates(conn, "pg_stat_statements", limit=1, text_chars=999)
    query = embed_text(tuple(stored[0].heading_path.split(" > ")), stored[0].text)
    response = run(loaded, fake_embedder, config, query, SearchMode.VECTOR, top_k=3)
    assert response.hits[0].title == "PostgreSQL extensions"
    assert response.hits[0].score == round(1 / 61, 5)  # first in the only list
    assert len(response.hits) == 3  # nearest neighbours always exist; ranks are 1, 2, 3
    assert [hit.rank for hit in response.hits] == [1, 2, 3]


def test_hybrid_scores_a_chunk_found_by_both_lists_twice(
    loaded: ConnectionPool, fake_embedder: FakeEmbedder, config: SearchConfig
) -> None:
    with loaded.connection() as conn:
        stored = repository.keyword_candidates(conn, "pg_stat_statements", limit=1, text_chars=999)
    query = embed_text(tuple(stored[0].heading_path.split(" > ")), stored[0].text)
    response = run(loaded, fake_embedder, config, query, SearchMode.HYBRID)
    top, runner_up = response.hits[0], response.hits[1]
    assert top.title == "PostgreSQL extensions"
    assert top.score == round(2 / 61, 5)  # rank 1 in the vector list and in the keyword list
    assert runner_up.score < top.score


def test_results_carry_citations_and_never_exceed_top_k_or_the_text_cap(
    loaded: ConnectionPool, fake_embedder: FakeEmbedder, test_settings: Settings
) -> None:
    capped = replace(SearchConfig.from_settings(test_settings), text_chars=60)
    response = run(loaded, fake_embedder, capped, "kafka", SearchMode.HYBRID, top_k=2)
    assert len(response.hits) <= 2
    for hit in response.hits:
        assert hit.source.startswith("file:docs/") and hit.heading_path
        assert len(hit.text) <= 60
        assert hit.url is None  # these test files sit outside the mapped devportal prefix


@pytest.mark.parametrize("query", ["?!...", "---", "   .  "])
def test_punctuation_only_queries_return_nothing_without_touching_the_model(
    query: str, loaded: ConnectionPool, config: SearchConfig
) -> None:
    for mode in SearchMode:
        response = search(loaded, ExplodingEmbedder(), query, top_k=5, mode=mode, config=config)
        assert response.hits == ()


def test_stopword_only_keyword_query_is_empty_not_an_error(
    loaded: ConnectionPool, fake_embedder: FakeEmbedder, config: SearchConfig
) -> None:
    assert run(loaded, fake_embedder, config, "the of and", SearchMode.KEYWORD).hits == ()


def test_search_on_an_empty_database_is_empty(
    pool: ConnectionPool, fake_embedder: FakeEmbedder, config: SearchConfig
) -> None:
    for mode in SearchMode:
        assert run(pool, fake_embedder, config, "kafka", mode).hits == ()


class ExplodingEmbedder(FakeEmbedder):
    """Proves a code path never calls the model."""

    def embed_query(self, text: str) -> list[float]:
        raise AssertionError("the model must not be called")


# --- the index proofs required by database.md: the query shapes can be served by an index.
# The tables here are tiny, so the planner would prefer a sequential scan on cost alone;
# turning that off shows the query *can* use the index, which is what a schema edit could break.


def explain(pool: ConnectionPool, statement: str, params: tuple[object, ...]) -> str:
    with pool.connection() as conn, conn.transaction(force_rollback=True):
        conn.execute("SET LOCAL enable_seqscan = off")
        rows = conn.execute("EXPLAIN " + statement, params).fetchall()  # constant + constant
    return "\n".join(row[0] for row in rows)


def test_vector_query_can_use_the_hnsw_index(loaded: ConnectionPool) -> None:
    vector = repository.vector_literal([0.1] * 8)
    plan = explain(loaded, repository.VECTOR_SQL, (50, vector, vector, 20))
    assert "chunks_embedding_hnsw" in plan, plan


def test_keyword_query_can_use_the_gin_index(loaded: ConnectionPool) -> None:
    plan = explain(loaded, repository.KEYWORD_SQL, (50, "kafka", "kafka", 20))
    assert "chunks_tsv_gin" in plan, plan
