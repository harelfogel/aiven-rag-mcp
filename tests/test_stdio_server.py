"""The real server process over stdio: what Claude Code will actually launch.

Uses the real embedding model and a throwaway database, so it is marked slow.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from tests.conftest import throwaway_database

pytestmark = [pytest.mark.integration, pytest.mark.slow]

SERVER = str(Path(sys.executable).parent / "rag-mcp")
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "stdout-check", "version": "0"},
    },
}


@pytest.fixture
def server_env(tmp_path: Path) -> Iterator[dict[str, str]]:
    with throwaway_database("stdio") as url:
        yield {**os.environ, "DATABASE_URL": url, "DATA_ROOT": str(tmp_path), "LOG_LEVEL": "INFO"}


def test_stdout_carries_only_json_rpc_frames(server_env: dict[str, str]) -> None:
    process = subprocess.Popen(
        [SERVER, "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=server_env,
    )
    try:
        assert process.stdin and process.stdout
        process.stdin.write(json.dumps(INITIALIZE) + "\n")
        process.stdin.flush()
        first_line = process.stdout.readline()
        process.stdin.close()  # EOF is how Claude Code ends a session
        rest = process.stdout.read()
        stderr = process.stderr.read() if process.stderr else ""
        process.wait(timeout=30)
    finally:
        process.kill()
    lines = [line for line in (first_line + rest).splitlines() if line.strip()]
    assert lines, f"no output; stderr was:\n{stderr}"
    for line in lines:
        assert json.loads(line)["jsonrpc"] == "2.0", f"non-protocol output on stdout: {line!r}"
    assert "MCP server ready on stdio" in stderr  # our logging went to stderr, not stdout


@pytest.mark.anyio
async def test_full_session_over_stdio(server_env: dict[str, str]) -> None:
    parameters = StdioServerParameters(command=SERVER, args=["serve"], env=server_env)
    async with Client(parameters) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        ingested = await client.call_tool(
            "ingest",
            {
                "source": (
                    "Valkey eviction\n===============\n\nSet maxmemory-policy to evict keys.\n"
                ),
                "kind": "text",
            },
        )
        keyword = await client.call_tool("search", {"query": "maxmemory-policy", "mode": "keyword"})
        hybrid = await client.call_tool(
            "search", {"query": "how do I evict keys when memory is full"}
        )
        listing = await client.call_tool("list_sources", {})
    assert names == {"ingest", "search", "list_sources"}
    assert ingested.structured_content["status"] == "ingested"
    assert keyword.structured_content["hits"][0]["title"] == "Valkey eviction"
    assert hybrid.structured_content["hits"][0]["title"] == "Valkey eviction"  # real meaning match
    assert listing.structured_content["total_sources"] == 1
