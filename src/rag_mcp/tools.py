"""The MCP tools: a table of specs and one registrar.

Each tool is a plain synchronous function with an explicit, typed signature, because the SDK builds
the JSON schema from those annotations and the bounds come from settings at runtime. `register`
does what is the same for every tool: run it in a worker thread so the event loop keeps answering
pings, route its errors through the boundary, and hand it to the SDK with its text from prompts.

Deliberately no `from __future__ import annotations`: the SDK needs real annotation objects.
"""

import functools
from collections.abc import Awaitable, Callable
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
from rag_mcp.prompts import ToolName
from rag_mcp.search import SearchConfig, SearchMode, SearchResponse, search
from rag_mcp.settings import Settings

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
# ingest replaces an earlier version of the same source; it never deletes unrelated data.
REPLACES_OWN_DATA = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True
)

ToolFunction = Callable[..., object]


@dataclass(frozen=True)
class Runtime:
    """What the tools share for the life of the server."""

    settings: Settings
    pool: ConnectionPool
    embedder: Embedder
    pipeline: IngestPipeline
    search_config: SearchConfig

    @classmethod
    def create(cls, settings: Settings, pool: ConnectionPool, embedder: Embedder) -> "Runtime":
        pipeline = IngestPipeline.from_settings(settings, pool, embedder)
        return cls(settings, pool, embedder, pipeline, SearchConfig.from_settings(settings))


@dataclass(frozen=True)
class ToolSpec:
    name: ToolName
    annotations: ToolAnnotations
    build: Callable[[Runtime], ToolFunction]  # returns the typed function for this runtime


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
    runtime = Runtime.create(settings, pool, embedder)
    for spec in TOOL_SPECS:
        register(server, spec, runtime)
    return server


def register(server: MCPServer, spec: ToolSpec, runtime: Runtime) -> None:
    """Expose one spec on the server. The wrapper keeps the function's signature and annotations,
    which is where the SDK reads the input and output schemas from."""
    tool = guarded(spec.name.value)(_in_worker_thread(spec.build(runtime)))
    text = prompts.TOOL_TEXT[spec.name]
    server.tool(
        name=spec.name.value,
        title=text.title,
        description=text.description,
        annotations=spec.annotations,
    )(tool)


def _in_worker_thread[**P, R](function: Callable[P, R]) -> Callable[P, Awaitable[R]]:
    """Blocking database and model work must not stall the event loop that answers pings."""

    @functools.wraps(function)
    async def run(*args: P.args, **kwargs: P.kwargs) -> R:
        return await anyio.to_thread.run_sync(functools.partial(function, *args, **kwargs))

    return run


def _search(runtime: Runtime) -> ToolFunction:
    settings = runtime.settings

    def search_tool(
        query: Annotated[str, Field(description=prompts.QUERY_DOC)],
        top_k: Annotated[
            int, Field(ge=1, le=settings.search_max_top_k, description=prompts.TOP_K_DOC)
        ] = settings.search_default_top_k,
        mode: Annotated[SearchMode, Field(description=prompts.MODE_DOC)] = SearchMode.HYBRID,
    ) -> SearchResponse:
        return search(
            runtime.pool,
            runtime.embedder,
            query,
            top_k=top_k,
            mode=mode,
            config=runtime.search_config,
        )

    return search_tool


def _ingest(runtime: Runtime) -> ToolFunction:
    def ingest_tool(
        source: Annotated[str, Field(description=prompts.SOURCE_DOC)],
        kind: Annotated[SourceKind, Field(description=prompts.KIND_DOC)],
        title: Annotated[str | None, Field(description=prompts.TITLE_DOC)] = None,
    ) -> IngestResult:
        return runtime.pipeline.ingest(kind, source, title)

    return ingest_tool


def _list_sources(runtime: Runtime) -> ToolFunction:
    settings = runtime.settings

    def list_sources_tool(
        limit: Annotated[
            int, Field(ge=1, le=settings.list_sources_max, description=prompts.LIMIT_DOC)
        ] = settings.list_sources_default,
        offset: Annotated[int, Field(ge=0, description=prompts.OFFSET_DOC)] = 0,
    ) -> SourceList:
        with runtime.pool.connection() as conn:
            total_sources, total_chunks = repository.count_sources(conn)
            records = repository.list_sources(conn, limit=limit, offset=offset)
        sources = tuple(
            SourceInfo(r.uri, r.title, r.kind, r.chunk_count, r.ingested_at.isoformat())
            for r in records
        )
        return SourceList(total_sources, total_chunks, offset, sources)

    return list_sources_tool


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(ToolName.SEARCH, READ_ONLY, _search),
    ToolSpec(ToolName.INGEST, REPLACES_OWN_DATA, _ingest),
    ToolSpec(ToolName.LIST_SOURCES, READ_ONLY, _list_sources),
)
