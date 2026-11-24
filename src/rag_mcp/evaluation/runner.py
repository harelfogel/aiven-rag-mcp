"""Run every golden question through every search variant and score the ranks.

The rank of the first hit from an expected page is the question's rank; recall@5 is the share of
questions ranked 5 or better, MRR is the mean of 1 / rank. Latency is measured around the whole
`search` call, model included, after one untimed warm-up per variant.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from psycopg_pool import ConnectionPool

from rag_mcp.embedding import Embedder
from rag_mcp.evaluation.golden import GoldenQuestion
from rag_mcp.search import SearchConfig, SearchHit, SearchMode, search

RECALL_AT = 5


@dataclass(frozen=True)
class Variant:
    label: str
    mode: SearchMode


@dataclass(frozen=True)
class Outcome:
    question: GoldenQuestion
    rank: int | None  # None: the page was not in the candidates at all
    latencies_ms: tuple[float, ...]


@dataclass(frozen=True)
class Report:
    variant: Variant
    outcomes: tuple[Outcome, ...]

    @property
    def recall_at_1(self) -> float:
        return _share(self.outcomes, 1)

    @property
    def recall_at_5(self) -> float:
        return _share(self.outcomes, RECALL_AT)

    @property
    def mrr(self) -> float:
        return sum(1 / o.rank for o in self.outcomes if o.rank) / len(self.outcomes)

    @property
    def p50_ms(self) -> float:
        return percentile(self._all_latencies(), 50)

    @property
    def p95_ms(self) -> float:
        return percentile(self._all_latencies(), 95)

    def recall_at_5_by_kind(self) -> dict[str, float]:
        kinds = sorted({o.question.kind for o in self.outcomes})
        return {
            kind: _share([o for o in self.outcomes if o.question.kind == kind], RECALL_AT)
            for kind in kinds
        }

    def _all_latencies(self) -> list[float]:
        return [ms for o in self.outcomes for ms in o.latencies_ms]


DEFAULT_VARIANTS = (
    Variant("vector", SearchMode.VECTOR),
    Variant("keyword", SearchMode.KEYWORD),
    Variant("hybrid", SearchMode.HYBRID),
)


def evaluate(
    pool: ConnectionPool,
    embedder: Embedder,
    golden: Sequence[GoldenQuestion],
    config: SearchConfig,
    *,
    variants: Sequence[Variant] = DEFAULT_VARIANTS,
    repeats: int = 1,
) -> list[Report]:
    """Run every question through every variant; timing repeats give the latency percentiles."""
    reports = []
    for variant in variants:
        if golden:  # one untimed call so the first variant does not pay for cold caches
            search(pool, embedder, golden[0].question, top_k=1, mode=variant.mode, config=config)
        outcomes = tuple(
            _run_question(pool, embedder, question, variant, config, repeats) for question in golden
        )
        reports.append(Report(variant, outcomes))
    return reports


def _run_question(
    pool: ConnectionPool,
    embedder: Embedder,
    question: GoldenQuestion,
    variant: Variant,
    config: SearchConfig,
    repeats: int,
) -> Outcome:
    latencies: list[float] = []
    hits: tuple[SearchHit, ...] = ()
    for _ in range(max(1, repeats)):
        started = time.perf_counter()
        hits = search(
            pool,
            embedder,
            question.question,
            top_k=config.max_top_k,
            mode=variant.mode,
            config=config,
        ).hits
        latencies.append((time.perf_counter() - started) * 1000)
    return Outcome(question, rank_of(question.expected_uris, hits), tuple(latencies))


def rank_of(expected_uris: Sequence[str], hits: Sequence[SearchHit]) -> int | None:
    return next((hit.rank for hit in hits if hit.source in expected_uris), None)


def percentile(values: Sequence[float], pct: int) -> float:
    """Nearest-rank percentile; p95 of 34 samples is the 33rd of the sorted values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def _share(outcomes: Sequence[Outcome], at: int) -> float:
    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if o.rank is not None and o.rank <= at) / len(outcomes)
