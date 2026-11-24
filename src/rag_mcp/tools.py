"""The three MCP tools.

Deliberately no `from __future__ import annotations`: the SDK builds each tool's input schema from
the real annotations, and the bounds below come from settings at runtime.
"""

import functools
from dataclasses import dataclass
from typing import Annotated

import anyio.to_thread
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from psycopg_pool import ConnectionPool
from pydantic import Field

from rag_mcp import prompts, repository
from rag_mcp.boundary import guarded
from rag_mcp.embedding import Embedder
from rag_mcp.ingest import IngestPipeline, IngestResult
from rag_mcp.loaders import SourceKind
from rag_mcp.search import SearchConfig, SearchMode, SearchResponse, search
from rag_mcp.settings import Settings

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
# ingest replaces an earlier version of the same source; it never deletes unrelated data.
INGEST = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)


@dataclass(frozen=True)
class SourceInfo:
    uri: str
    title: str
    kind: str
    chunks: int
    ingested_at: str


@dataclass(frozen=True)
class SourceList:
    total_sources: int
    total_chunks: int
    offset: int
    sources: tuple[SourceInfo, ...]


def build_server(settings: Settings, pool: ConnectionPool, embedder: Embedder) -> MCPServer:
    server = MCPServer(name=prompts.SERVER_NAME, instructions=prompts.SERVER_INSTRUCTIONS)
    _register_search(server, settings, pool, embedder)
    _register_ingest(server, IngestPipeline.from_settings(settings, pool, embedder))
    _register_list_sources(server, settings, pool)
    return server


def _register_search(
    server: MCPServer, settings: Settings, pool: ConnectionPool, embedder: Embedder
) -> None:
    config = SearchConfig.from_settings(settings)

    @server.tool(
        name="search",
        title="Search the documentation",
        description=prompts.SEARCH_DESCRIPTION,
        annotations=READ_ONLY,
    )
    @guarded("search")
    async def search_tool(
        query: Annotated[str, Field(description=prompts.QUERY_DOC)],
        top_k: Annotated[
            int, Field(ge=1, le=settings.search_max_top_k, description=prompts.TOP_K_DOC)
        ] = settings.search_default_top_k,
        mode: Annotated[SearchMode, Field(description=prompts.MODE_DOC)] = SearchMode.HYBRID,
    ) -> SearchResponse:
        run = functools.partial(
            search, pool, embedder, query, top_k=top_k, mode=mode, config=config
        )
        return await anyio.to_thread.run_sync(run)


def _register_ingest(server: MCPServer, pipeline: IngestPipeline) -> None:
    @server.tool(
        name="ingest",
        title="Add a document",
        description=prompts.INGEST_DESCRIPTION,
        annotations=INGEST,
    )
    @guarded("ingest")
    async def ingest_tool(
        source: Annotated[str, Field(description=prompts.SOURCE_DOC)],
        kind: Annotated[SourceKind, Field(description=prompts.KIND_DOC)],
        title: Annotated[str | None, Field(description=prompts.TITLE_DOC)] = None,
    ) -> IngestResult:
        run = functools.partial(pipeline.ingest, kind, source, title)
        return await anyio.to_thread.run_sync(run)


def _register_list_sources(server: MCPServer, settings: Settings, pool: ConnectionPool) -> None:
    @server.tool(
        name="list_sources",
        title="List ingested sources",
        description=prompts.LIST_SOURCES_DESCRIPTION,
        annotations=READ_ONLY,
    )
    @guarded("list_sources")
    async def list_sources_tool(
        limit: Annotated[
            int, Field(ge=1, le=settings.list_sources_max, description=prompts.LIMIT_DOC)
        ] = settings.list_sources_default,
        offset: Annotated[int, Field(ge=0, description=prompts.OFFSET_DOC)] = 0,
    ) -> SourceList:
        return await anyio.to_thread.run_sync(functools.partial(_list_sources, pool, limit, offset))


def _list_sources(pool: ConnectionPool, limit: int, offset: int) -> SourceList:
    with pool.connection() as conn:
        total_sources, total_chunks = repository.count_sources(conn)
        records = repository.list_sources(conn, limit=limit, offset=offset)
    sources = tuple(
        SourceInfo(r.uri, r.title, r.kind, r.chunk_count, r.ingested_at.isoformat())
        for r in records
    )
    return SourceList(total_sources, total_chunks, offset, sources)
