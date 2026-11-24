"""Hybrid retrieval: nearest vectors and keyword matches, fused by reciprocal rank fusion."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from psycopg_pool import ConnectionPool

from rag_mcp import repository
from rag_mcp.embedding import Embedder
from rag_mcp.errors import Code, RagError
from rag_mcp.repository import ChunkHit
from rag_mcp.settings import Settings


class SearchError(RagError):
    """The request itself is invalid; nothing was searched."""


class SearchMode(StrEnum):
    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class SearchConfig:
    candidates: int
    rrf_k: int
    ef_search: int
    text_chars: int
    max_top_k: int
    max_query_chars: int
    url_base: str
    path_prefix: str

    @classmethod
    def from_settings(cls, settings: Settings) -> SearchConfig:
        return cls(
            settings.search_candidates,
            settings.rrf_k,
            settings.hnsw_ef_search,
            settings.search_text_chars,
            settings.search_max_top_k,
            settings.query_max_chars,
            settings.source_url_base,
            settings.source_path_prefix,
        )


@dataclass(frozen=True)
class SearchHit:
    rank: int
    score: float  # the RRF score; only meaningful relative to the other hits of this response
    title: str
    heading_path: str
    text: str
    source: str  # the stored uri, e.g. file:devportal/docs/products/kafka/howto/x.rst
    url: str | None  # where a person can read the page, when we can build one


@dataclass(frozen=True)
class SearchResponse:
    query: str
    mode: SearchMode
    hits: tuple[SearchHit, ...]


def search(
    pool: ConnectionPool,
    embedder: Embedder,
    query: str,
    *,
    top_k: int,
    mode: SearchMode,
    config: SearchConfig,
) -> SearchResponse:
    query = validate_request(query, top_k, config)
    if not any(char.isalnum() for char in query):
        return SearchResponse(query, mode, ())  # punctuation only: nothing can match, not an error
    # Embed before borrowing a connection so a pooled connection never waits on the model.
    embedding = embedder.embed_query(query) if mode is not SearchMode.KEYWORD else None
    rankings = _candidate_lists(pool, query, embedding, mode, config)
    fused = fuse(rankings, config.rrf_k)[:top_k]
    hits = tuple(_to_hit(rank, hit, score, config) for rank, (hit, score) in enumerate(fused, 1))
    return SearchResponse(query, mode, hits)


def _candidate_lists(
    pool: ConnectionPool,
    query: str,
    embedding: Sequence[float] | None,
    mode: SearchMode,
    config: SearchConfig,
) -> list[list[ChunkHit]]:
    """One ranked list per retriever the mode asks for, read on a single pooled connection."""
    rankings: list[list[ChunkHit]] = []
    with pool.connection() as conn:
        if embedding is not None:
            rankings.append(
                repository.vector_candidates(
                    conn,
                    embedding,
                    limit=config.candidates,
                    text_chars=config.text_chars,
                    ef_search=config.ef_search,
                )
            )
        if mode is not SearchMode.VECTOR:
            rankings.append(
                repository.keyword_candidates(
                    conn,
                    query,
                    limit=config.candidates,
                    text_chars=config.text_chars,
                )
            )
    return rankings


def validate_request(query: str, top_k: int, config: SearchConfig) -> str:
    """Reject, never clamp: a client that asked for 50 results must know it did not get 50."""
    query = query.strip()
    if not query:
        raise SearchError(Code.BAD_REQUEST, "query is empty")
    if "\x00" in query:  # Postgres text cannot hold NUL; refuse here, not as a database error
        raise SearchError(Code.BAD_REQUEST, "query contains a NUL character")
    if len(query) > config.max_query_chars:
        raise SearchError(
            Code.TOO_LARGE,
            f"query is {len(query)} characters, the limit is {config.max_query_chars}",
        )
    if not 1 <= top_k <= config.max_top_k:
        raise SearchError(Code.BAD_REQUEST, f"top_k must be 1 to {config.max_top_k}, got {top_k}")
    return query


def fuse(rankings: Sequence[Sequence[ChunkHit]], k: int) -> list[tuple[ChunkHit, float]]:
    """Reciprocal rank fusion: a chunk scores the sum of 1 / (k + rank) over every list it is in.

    Only ranks are used, so a cosine distance and a keyword score never have to share a scale.
    Ties break on the best rank any list gave the chunk, then on id, so output is deterministic.
    Weighting the keyword list (0.5, 0.3) was measured and changed nothing: ADR 006.
    """
    scores: dict[int, float] = {}
    best_rank: dict[int, int] = {}
    hits: dict[int, ChunkHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, 1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            best_rank[hit.chunk_id] = min(best_rank.get(hit.chunk_id, rank), rank)
            hits.setdefault(hit.chunk_id, hit)
    order = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], best_rank[chunk_id], chunk_id))
    return [(hits[chunk_id], scores[chunk_id]) for chunk_id in order]


def citation_url(uri: str, config: SearchConfig) -> str | None:
    """A readable link for a stored uri: URLs are their own link, files map onto the GitHub repo."""
    if uri.startswith(("http://", "https://")):
        return uri
    if uri.startswith("file:") and uri[len("file:") :].startswith(config.path_prefix):
        return config.url_base + uri[len("file:") + len(config.path_prefix) :]
    return None


def _to_hit(rank: int, hit: ChunkHit, score: float, config: SearchConfig) -> SearchHit:
    return SearchHit(
        rank=rank,
        score=round(score, 5),
        title=hit.source_title,
        heading_path=hit.heading_path,
        text=hit.text,
        source=hit.source_uri,
        url=citation_url(hit.source_uri, config),
    )
