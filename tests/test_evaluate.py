import json
from pathlib import Path

import pytest

from rag_mcp.evaluate import (
    GoldenError,
    GoldenQuestion,
    Outcome,
    Report,
    Variant,
    load_golden,
    percentile,
    rank_of,
    render_markdown,
)
from rag_mcp.search import SearchHit, SearchMode


def hit(rank: int, source: str) -> SearchHit:
    return SearchHit(rank, 0.0, "t", "h", "x", source, None)


def question(id_: str, kind: str = "howto") -> GoldenQuestion:
    return GoldenQuestion(id_, kind, "q", ("file:devportal/docs/a.rst",))


def test_rank_of_takes_the_first_hit_from_any_expected_page() -> None:
    hits = [hit(1, "file:other"), hit(2, "file:b"), hit(3, "file:a"), hit(4, "file:b")]
    assert rank_of(("file:a", "file:b"), hits) == 2
    assert rank_of(("file:zzz",), hits) is None
    assert rank_of(("file:a",), []) is None


def test_percentile_is_nearest_rank() -> None:
    values = [float(v) for v in range(1, 35)]  # 34 samples, like the golden set
    assert percentile(values, 50) == 17.0
    assert percentile(values, 95) == 32.0  # round(0.95 * 34) = 32 -> the 32nd value
    assert percentile([5.0], 95) == 5.0
    assert percentile([], 50) == 0.0


def test_report_metrics_from_ranks() -> None:
    variant = Variant("v", SearchMode.HYBRID)
    outcomes = (
        Outcome(question("a", "param"), 1, (10.0,)),
        Outcome(question("b", "param"), 4, (20.0,)),
        Outcome(question("c", "howto"), 7, (30.0,)),
        Outcome(question("d", "howto"), None, (40.0,)),
    )
    report = Report(variant, outcomes)
    assert report.recall_at_1 == 0.25
    assert report.recall_at_5 == 0.5
    assert report.mrr == pytest.approx((1 + 1 / 4 + 1 / 7 + 0) / 4)
    assert report.recall_at_5_by_kind() == {"howto": 0.0, "param": 1.0}
    assert (report.p50_ms, report.p95_ms) == (20.0, 40.0)


def test_render_markdown_has_the_table_and_names_the_misses() -> None:
    variant = Variant("hybrid", SearchMode.HYBRID)
    report = Report(
        variant, (Outcome(question("good"), 1, (1.0,)), Outcome(question("bad"), None, (2.0,)))
    )
    text = render_markdown([report], chunk_count=3807, repeats=3)
    assert "| hybrid | 0.50 | 0.50 | 0.50 | 1 | 2 |" in text  # p50 of [1, 2] is 1
    misses_section = text.split("Not in the top")[1].split("Rank of the expected")[0]
    assert "- bad: rank none" in misses_section and "good" not in misses_section
    assert "| good | 1 |" in text and "| bad | none |" in text  # the per-question table
    assert "3807 chunks" in text


def test_load_golden_builds_uris_and_rejects_bad_files(tmp_path: Path) -> None:
    path = tmp_path / "g.json"
    path.write_text(
        json.dumps([{"id": "x", "kind": "limit", "question": "q", "expected": ["docs/a.rst"]}])
    )
    (loaded,) = load_golden(path, "file:devportal/")
    assert loaded.expected_uris == ("file:devportal/docs/a.rst",)
    path.write_text(json.dumps([{"id": "x"}]))
    with pytest.raises(GoldenError):
        load_golden(path, "file:devportal/")
    with pytest.raises(GoldenError):
        load_golden(tmp_path / "missing.json", "file:devportal/")


def test_repo_golden_set_is_well_formed() -> None:
    golden = load_golden(Path("eval/golden.json"), "file:devportal/")
    assert len(golden) >= 25
    assert len({g.id for g in golden}) == len(golden)
    assert {g.kind for g in golden} == {"param", "limit", "howto", "identifier", "error"}
    assert all(g.expected_uris and g.question.strip() for g in golden)
