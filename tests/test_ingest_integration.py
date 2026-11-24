"""End-to-end ingest against Postgres with the fake embedder."""

import logging
from pathlib import Path

import pytest
from psycopg_pool import ConnectionPool

from rag_mcp import repository
from rag_mcp.ingest import IngestPipeline, IngestStatus, ingest_tree
from rag_mcp.loaders import SourceKind
from rag_mcp.settings import Settings
from tests.conftest import FakeEmbedder

pytestmark = pytest.mark.integration

PAGE = (
    "Kafka how-to\n============\n\nStep one words words words.\n\n"
    ".. code::\n\n   kafka-topics.sh --list\n"
)


@pytest.fixture
def pipeline(
    test_settings: Settings, pool: ConnectionPool, fake_embedder: FakeEmbedder
) -> IngestPipeline:
    return IngestPipeline.from_settings(test_settings, pool, fake_embedder)


def test_ingest_file_then_unchanged_then_changed(
    pipeline: IngestPipeline, tmp_path: Path, fake_embedder: FakeEmbedder
) -> None:
    page = tmp_path / "docs" / "howto.rst"
    page.parent.mkdir()
    page.write_text(PAGE)
    first = pipeline.ingest(SourceKind.FILE, "docs/howto.rst")
    assert (first.status, first.title, first.uri) == (
        IngestStatus.INGESTED,
        "Kafka how-to",
        "file:docs/howto.rst",
    )
    assert first.chunk_count >= 1
    calls_after_first = len(fake_embedder.calls)
    second = pipeline.ingest(SourceKind.FILE, "docs/howto.rst")
    assert second.status is IngestStatus.UNCHANGED and second.chunk_count == first.chunk_count
    assert len(fake_embedder.calls) == calls_after_first  # unchanged content is never re-embedded
    page.write_text(
        PAGE + "\nMore\n----\n\nNew section with enough words to be its own chunk here.\n"
    )
    third = pipeline.ingest(SourceKind.FILE, "docs/howto.rst")
    assert third.status is IngestStatus.INGESTED and third.chunk_count > first.chunk_count
    with pipeline.pool.connection() as conn:
        record = repository.find_source(conn, "file:docs/howto.rst")
        stored = conn.execute(
            "SELECT count(*) FROM chunks WHERE source_id = %s", (record.id,)
        ).fetchone()  # type: ignore[union-attr]
    assert stored is not None and stored[0] == third.chunk_count


def test_ingest_text_is_identified_by_content(pipeline: IngestPipeline) -> None:
    one = pipeline.ingest(SourceKind.TEXT, "Hello there, this is pasted text about Valkey.", "Note")
    two = pipeline.ingest(
        SourceKind.TEXT, "Hello there, this is pasted text about Valkey.", "Other title"
    )
    assert one.status is IngestStatus.INGESTED and two.status is IngestStatus.UNCHANGED
    assert one.uri == two.uri and two.title == "Note"


def test_ingest_tree_skips_bad_files_and_reports(
    pipeline: IngestPipeline, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "good.rst").write_text(PAGE)
    (docs / "nav.rst").write_text("Nav\n===\n\n.. tableofcontents::\n")
    (docs / "binary.rst").write_bytes(b"PK\x00\x01junk")
    (docs / "notes.txt").write_text("ignored extension")
    progress: list[tuple[int, int]] = []
    with caplog.at_level(logging.WARNING):
        summary = ingest_tree(
            pipeline,
            docs,
            report=lambda done, total: progress.append((done, total)),
            progress_every=2,
        )
    assert (summary.ingested, summary.unchanged, summary.failed, summary.total) == (2, 0, 1, 3)
    assert summary.chunks >= 1 and summary.seconds > 0
    assert progress == [(2, 3), (3, 3)]
    assert "binary.rst" in caplog.text and "binary" in caplog.text
    rerun = ingest_tree(pipeline, docs, report=lambda *_: None)
    assert (rerun.ingested, rerun.unchanged, rerun.failed) == (0, 2, 1)


def test_changed_include_re_ingests_the_page_that_uses_it(
    pipeline: IngestPipeline, tmp_path: Path
) -> None:
    (tmp_path / "includes").mkdir()
    include = tmp_path / "includes" / "params.rst"
    include.write_text("``ip_filter``\n-------------\n*array* words words words words words.\n")
    page = tmp_path / "params.rst"
    page.write_text("Params\n======\n\n.. include:: /includes/params.rst\n")
    first = pipeline.ingest(SourceKind.FILE, "params.rst")
    include.write_text("``ip_filter``\n-------------\n*array* changed words words words words.\n")
    second = pipeline.ingest(SourceKind.FILE, "params.rst")
    assert (first.status, second.status) == (IngestStatus.INGESTED, IngestStatus.INGESTED)
