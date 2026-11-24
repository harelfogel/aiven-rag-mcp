"""The three tools through a real MCP client (in memory), against Postgres with the fake model."""

from dataclasses import replace

import pytest
from mcp.client import Client
from psycopg_pool import ConnectionPool

from rag_mcp.settings import Settings
from rag_mcp.tools import build_server
from tests.conftest import FakeEmbedder

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

PAGE = (
    "Valkey memory\n=============\n\n"
    "Set maxmemory-policy to control eviction when memory is full.\n"
)


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return replace(test_settings, ingest_max_bytes=2_000)


@pytest.fixture
def client(settings: Settings, pool: ConnectionPool, fake_embedder: FakeEmbedder) -> Client:
    return Client(build_server(settings, pool, fake_embedder))


async def test_exactly_three_tools_with_bounded_schemas(client: Client) -> None:
    async with client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert set(tools) == {"ingest", "search", "list_sources"}
    schema = tools["search"].input_schema
    top_k = schema["properties"]["top_k"]
    assert (top_k["minimum"], top_k["maximum"]) == (1, 20)
    assert set(schema["$defs"]["SearchMode"]["enum"]) == {"hybrid", "vector", "keyword"}
    assert tools["ingest"].input_schema["required"] == ["source", "kind"]
    assert all(tool.description for tool in tools.values())


async def test_ingest_search_and_list_round_trip(client: Client) -> None:
    async with client:
        first = await client.call_tool(
            "ingest", {"source": PAGE, "kind": "text", "title": "Valkey"}
        )
        again = await client.call_tool("ingest", {"source": PAGE, "kind": "text"})
        found = await client.call_tool("search", {"query": "maxmemory-policy", "mode": "keyword"})
        listing = await client.call_tool("list_sources", {})
    assert not first.is_error and first.structured_content["status"] == "ingested"
    assert again.structured_content["status"] == "unchanged"
    assert again.structured_content["uri"] == first.structured_content["uri"]
    (hit,) = found.structured_content["hits"]
    assert hit["source"] == first.structured_content["uri"] and "maxmemory-policy" in hit["text"]
    assert listing.structured_content["total_sources"] == 1
    assert listing.structured_content["sources"][0]["title"] == "Valkey"


async def test_list_sources_pages_and_reports_totals(client: Client) -> None:
    async with client:
        for number in range(3):
            await client.call_tool(
                "ingest", {"source": f"Document number {number}", "kind": "text"}
            )
        page = await client.call_tool("list_sources", {"limit": 2, "offset": 2})
        too_big = await client.call_tool("list_sources", {"limit": 1_000_000})
    assert page.structured_content["total_sources"] == 3
    assert len(page.structured_content["sources"]) == 1
    assert too_big.is_error


@pytest.mark.parametrize(
    ("tool", "arguments", "code"),
    [
        ("search", {"query": "   "}, "bad_request"),
        ("ingest", {"source": "../../etc/passwd", "kind": "file"}, "bad_request"),
        ("ingest", {"source": "nope.rst", "kind": "file"}, "not_found"),
        ("ingest", {"source": "http://169.254.169.254/latest", "kind": "url"}, "bad_request"),
        ("ingest", {"source": "ftp://example.com/x", "kind": "url"}, "bad_request"),
        ("ingest", {"source": "x" * 2_001, "kind": "text"}, "too_large"),
        ("ingest", {"source": "   ", "kind": "text"}, "bad_request"),
        ("ingest", {"source": "hello", "kind": "text", "title": "a\x00b"}, "bad_request"),
        ("search", {"query": "kafka\x00"}, "bad_request"),
    ],
)
async def test_refusals_are_tool_errors_with_a_code_the_model_can_read(
    client: Client, tool: str, arguments: dict[str, object], code: str
) -> None:
    async with client:
        result = await client.call_tool(tool, arguments)
        still_works = await client.call_tool("list_sources", {})
    assert result.is_error and f"{code}:" in result.content[0].text
    assert not still_works.is_error  # a failed call never takes the server down


async def test_out_of_range_arguments_are_rejected_not_clamped(client: Client) -> None:
    async with client:
        too_many = await client.call_tool("search", {"query": "valkey", "top_k": 21})
        none = await client.call_tool("search", {"query": "valkey", "top_k": 0})
        bad_mode = await client.call_tool("search", {"query": "valkey", "mode": "fuzzy"})
    assert too_many.is_error and none.is_error and bad_mode.is_error


class BrokenEmbedder(FakeEmbedder):
    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("onnx exploded with /secret/path/inside")


async def test_unexpected_failure_is_internal_hides_details_and_the_server_survives(
    settings: Settings, pool: ConnectionPool
) -> None:
    client = Client(build_server(settings, pool, BrokenEmbedder()))
    async with client:
        broken = await client.call_tool("search", {"query": "valkey"})
        keyword_only = await client.call_tool("search", {"query": "valkey", "mode": "keyword"})
    assert broken.is_error and "internal:" in broken.content[0].text
    assert "/secret/path" not in broken.content[0].text  # no internals leak to the client
    assert not keyword_only.is_error  # the next call, on a path that needs no model, still works


async def test_a_lost_database_is_a_coded_error_and_the_server_keeps_answering(
    settings: Settings, fake_embedder: FakeEmbedder
) -> None:
    from rag_mcp import db

    dying_pool = db.connect(settings)
    client = Client(build_server(settings, dying_pool, fake_embedder))
    async with client:
        dying_pool.close()  # the connection pool disappears mid-session
        lost = await client.call_tool("search", {"query": "valkey", "mode": "keyword"})
        refused = await client.call_tool("search", {"query": "   "})
    assert lost.is_error and "internal:" in lost.content[0].text
    assert "database" in lost.content[0].text
    assert refused.is_error and "bad_request:" in refused.content[0].text  # still answering
