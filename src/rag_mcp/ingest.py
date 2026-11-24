"""The ingest pipeline: load, expand includes, parse, chunk, embed, store. One source at a time."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from psycopg_pool import ConnectionPool

from rag_mcp.chunking import Chunk, ChunkConfig, chunk_document, embed_text
from rag_mcp.embedding import Embedder
from rag_mcp.errors import RagError
from rag_mcp.loading.loaders import LoadedSource, LoadLimits, SourceKind, load
from rag_mcp.parsing import Format, parse
from rag_mcp.parsing.includes import expand_includes, file_include_resolver
from rag_mcp.settings import Settings
from rag_mcp.storage import repository
from rag_mcp.storage.repository import ChunkRow

log = logging.getLogger(__name__)
HEADING_JOIN = " > "
_DOCUMENT_SUFFIXES = frozenset({".rst", ".md", ".markdown"})
# Bump on any change to parsing or chunking output; stored sources then count as changed.
PIPELINE_VERSION = "2"


class IngestStatus(StrEnum):
    INGESTED = "ingested"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class IngestResult:
    uri: str
    title: str
    status: IngestStatus
    chunk_count: int


@dataclass(frozen=True)
class PreparedSource:
    """Everything the database write needs, computed before any transaction opens."""

    title: str
    content_hash: str
    rows: tuple[ChunkRow, ...]


@dataclass(frozen=True)
class IngestPipeline:
    pool: ConnectionPool
    embedder: Embedder
    limits: LoadLimits
    chunking: ChunkConfig

    @classmethod
    def from_settings(
        cls, settings: Settings, pool: ConnectionPool, embedder: Embedder
    ) -> IngestPipeline:
        chunking = ChunkConfig(
            settings.chunk_target_tokens, settings.chunk_max_tokens, settings.chunk_min_tokens
        )
        return cls(pool, embedder, LoadLimits.from_settings(settings), chunking)

    def ingest(self, kind: SourceKind, source: str, title: str | None = None) -> IngestResult:
        loaded = load(kind, source, title, self.limits)
        text = expand_file_includes(loaded, self.limits)
        content_hash = index_hash(text)
        with self.pool.connection() as conn:
            existing = repository.find_source(conn, loaded.uri)
        if existing is not None and existing.content_hash == content_hash:
            return IngestResult(
                loaded.uri, existing.title, IngestStatus.UNCHANGED, existing.chunk_count
            )
        prepared = prepare_source(loaded, text, title, content_hash, self.embedder, self.chunking)
        with self.pool.connection() as conn:
            written = repository.replace_source(
                conn,
                uri=loaded.uri,
                kind=kind.value,
                title=prepared.title,
                content_hash=content_hash,
                chunks=prepared.rows,
            )
        status = IngestStatus.INGESTED if written else IngestStatus.UNCHANGED
        return IngestResult(loaded.uri, prepared.title, status, len(prepared.rows))


def index_hash(text: str) -> str:
    """What `unchanged` means: same expanded text, same parser and chunker. Hash the text after
    includes are expanded, so an edited include re-ingests the pages using it, and mix in
    PIPELINE_VERSION, so bumping it re-ingests everything after a parsing or chunking change."""
    return hashlib.sha256(f"{PIPELINE_VERSION}\n{text}".encode()).hexdigest()


def prepare_source(
    loaded: LoadedSource,
    text: str,
    title: str | None,
    content_hash: str,
    embedder: Embedder,
    chunking: ChunkConfig,
) -> PreparedSource:
    """Parse, chunk and embed the expanded text. No database involved."""
    document = parse(text, loaded.fmt, fallback_title=loaded.title)
    chunks = chunk_document(document, embedder.count_tokens, chunking)
    texts = [embed_text(chunk.heading_path, chunk.text) for chunk in chunks]
    # A nav-only page has no chunks and must not touch the model.
    vectors = embedder.embed_documents(texts) if texts else []
    rows = tuple(
        _row(position, chunk, vector)
        for position, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
    )
    return PreparedSource(title or document.title or loaded.title, content_hash, rows)


def expand_file_includes(loaded: LoadedSource, limits: LoadLimits) -> str:
    """RST files get their `.. include::` targets inlined; everything else is returned as is."""
    if loaded.fmt is not Format.RST or loaded.local_path is None:
        return loaded.text
    project_root = sphinx_project_root(loaded.local_path, limits.data_root)
    resolver = file_include_resolver(
        limits.data_root, loaded.local_path, limits.max_bytes, project_root=project_root
    )
    return expand_includes(loaded.text, resolver)


def sphinx_project_root(source: Path, data_root: Path) -> Path:
    """The nearest ancestor holding `conf.py`, which is what `/absolute` includes are relative to
    in Sphinx; the data root when there is none (a loose file, or a non-Sphinx tree)."""
    for directory in source.parents:
        if (directory / "conf.py").is_file():
            return directory
        if directory == data_root:
            break
    return data_root


def _row(position: int, chunk: Chunk, vector: list[float]) -> ChunkRow:
    return ChunkRow(
        position, HEADING_JOIN.join(chunk.heading_path), chunk.text, chunk.token_count, vector
    )


# --- bulk ingest of a folder under the data root (the CLI entry point)


@dataclass(frozen=True)
class IngestSummary:
    ingested: int
    unchanged: int
    failed: int
    chunks: int
    seconds: float

    @property
    def total(self) -> int:
        return self.ingested + self.unchanged + self.failed


ProgressReporter = Callable[[int, int], None]
"""Called with (done, total) every `progress_every` files."""


def ingest_tree(
    pipeline: IngestPipeline, root: Path, *, report: ProgressReporter, progress_every: int = 50
) -> IngestSummary:
    """Ingest every .rst/.md under `root`, or the single file. A bad file is logged and skipped."""
    files = _documents_under(root)
    started = time.perf_counter()
    counts = {status: 0 for status in IngestStatus}
    failed = chunks = 0
    for done, path in enumerate(files, start=1):
        try:
            result = pipeline.ingest(SourceKind.FILE, str(path))
        except RagError as error:
            failed += 1
            log.warning("skipped %s: %s", path, error)
        else:
            counts[result.status] += 1
            chunks += result.chunk_count if result.status is IngestStatus.INGESTED else 0
        if done % progress_every == 0 or done == len(files):
            report(done, len(files))
    seconds = time.perf_counter() - started
    return IngestSummary(
        counts[IngestStatus.INGESTED], counts[IngestStatus.UNCHANGED], failed, chunks, seconds
    )


def _documents_under(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(path for path in root.rglob("*") if path.suffix.lower() in _DOCUMENT_SUFFIXES)
