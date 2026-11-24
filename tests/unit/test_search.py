"""Search logic that needs no database."""

import pytest

from rag_mcp.errors import Code
from rag_mcp.search import SearchConfig, SearchError, citation_url, fuse, validate_request
from rag_mcp.settings import Settings
from rag_mcp.storage.repository import ChunkHit

CONFIG = SearchConfig.from_settings(Settings.from_env({"DATABASE_URL": "postgresql://x/y"}))


def hit(chunk_id: int) -> ChunkHit:
    return ChunkHit(chunk_id, f"file:p{chunk_id}.rst", f"Page {chunk_id}", "Page > Sec", "text")


def test_fuse_worked_example_with_real_numbers() -> None:
    # A is 1st by meaning and absent from keywords: 1/61. B is 2nd in both lists: 2/62.
    meaning = [hit(1), hit(2)]
    keywords = [hit(3), hit(2)]
    fused = fuse([meaning, keywords], k=60)
    scores = {h.chunk_id: round(score, 5) for h, score in fused}
    assert scores == {2: round(2 / 62, 5), 1: round(1 / 61, 5), 3: round(1 / 61, 5)}
    assert [h.chunk_id for h, _ in fused] == [2, 1, 3]  # B first; A and C tie, A wins on id


def test_fuse_single_list_keeps_its_order_and_empty_input_is_empty() -> None:
    assert [h.chunk_id for h, _ in fuse([[hit(5), hit(4), hit(9)]], k=60)] == [5, 4, 9]
    assert fuse([], k=60) == []
    assert fuse([[], []], k=60) == []


def test_fuse_tie_break_prefers_the_better_best_rank() -> None:
    # 1 is 1st in list one only; 2 is 1st in list two only; both score 1/61. 3 is 2nd twice: 2/62.
    fused = fuse([[hit(1), hit(3)], [hit(2), hit(3)]], k=60)
    assert [h.chunk_id for h, _ in fused] == [3, 1, 2]


def test_fuse_is_deterministic_regardless_of_candidate_overlap_order() -> None:
    lists = [[hit(i) for i in (4, 3, 2, 1)], [hit(i) for i in (1, 2, 3, 4)]]
    assert fuse(lists, 60) == fuse(lists, 60)


@pytest.mark.parametrize("top_k", [0, -1, 21, 1000])
def test_validate_request_rejects_top_k_out_of_range(top_k: int) -> None:
    with pytest.raises(SearchError, match="top_k must be 1 to 20") as error:
        validate_request("kafka", top_k, CONFIG)
    assert error.value.code is Code.BAD_REQUEST


def test_validate_request_accepts_the_bounds_and_strips() -> None:
    assert validate_request("  kafka  ", 1, CONFIG) == "kafka"
    assert validate_request("kafka", 20, CONFIG) == "kafka"


def test_validate_request_rejects_nul_bytes() -> None:
    with pytest.raises(SearchError, match="NUL") as error:
        validate_request("kafka\x00", 5, CONFIG)
    assert error.value.code is Code.BAD_REQUEST


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_validate_request_rejects_blank_queries(query: str) -> None:
    with pytest.raises(SearchError, match="empty") as error:
        validate_request(query, 5, CONFIG)
    assert error.value.code is Code.BAD_REQUEST


def test_validate_request_rejects_oversized_queries() -> None:
    with pytest.raises(SearchError) as error:
        validate_request("a" * (CONFIG.max_query_chars + 1), 5, CONFIG)
    assert error.value.code is Code.TOO_LARGE
    assert validate_request("a" * CONFIG.max_query_chars, 5, CONFIG)


def test_citation_url_maps_files_urls_and_unknowns() -> None:
    page = "file:devportal/docs/products/kafka/howto/x.rst"
    assert citation_url(page, CONFIG) == (
        "https://github.com/aiven/devportal/blob/main/docs/products/kafka/howto/x.rst"
    )
    assert citation_url("https://example.com/a", CONFIG) == "https://example.com/a"
    assert citation_url("file:notes/mine.md", CONFIG) is None  # outside the mapped repo
    assert citation_url("text:ab12cd34ef56", CONFIG) is None


def test_settings_search_limits_must_be_consistent() -> None:
    from rag_mcp.settings import SettingsError

    base = {"DATABASE_URL": "postgresql://x/y"}
    with pytest.raises(SettingsError, match="SEARCH_MAX_TOP_K"):
        Settings.from_env({**base, "SEARCH_MAX_TOP_K": "30"})  # more than one list can supply
    with pytest.raises(SettingsError, match="HNSW_EF_SEARCH"):
        Settings.from_env({**base, "HNSW_EF_SEARCH": "10"})  # index returns at most ef_search
    assert Settings.from_env({**base, "SEARCH_CANDIDATES": "30", "SEARCH_MAX_TOP_K": "30"})
