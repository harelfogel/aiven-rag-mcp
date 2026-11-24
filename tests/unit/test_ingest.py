"""Pipeline pieces that need no database."""

import hashlib
from pathlib import Path

from rag_mcp.chunking import ChunkConfig
from rag_mcp.ingest import (
    PreparedSource,
    _documents_under,
    expand_file_includes,
    index_hash,
    prepare_source,
    sphinx_project_root,
)
from rag_mcp.loading.fetching import FetchLimits
from rag_mcp.loading.loaders import LoadedSource, LoadLimits, load_file
from tests.conftest import FakeEmbedder

CHUNKING = ChunkConfig(target_tokens=40, max_tokens=50, min_tokens=6)


def limits_for(root: Path) -> LoadLimits:
    return LoadLimits(max_bytes=10_000, data_root=root, fetch=FetchLimits(10_000, 1, 0))


def prepare(
    loaded: LoadedSource, root: Path, embedder: FakeEmbedder, title: str | None = None
) -> PreparedSource:
    text = expand_file_includes(loaded, limits_for(root))
    return prepare_source(loaded, text, title, "hash", embedder, CHUNKING)


def test_prepare_source_expands_includes_and_numbers_rows(
    tmp_path: Path, fake_embedder: FakeEmbedder
) -> None:
    (tmp_path / "includes").mkdir()
    (tmp_path / "includes" / "params.rst").write_text(
        "``kafka_connect``\n-----------------\n*boolean*\n\n"
        "**Allow** private access words words words words words.\n"
    )
    page = tmp_path / "page.rst"
    page.write_text(
        "Advanced parameters\n===================\n\nIntro line.\n\n"
        ".. include:: /includes/params.rst\n"
    )
    loaded = load_file("page.rst", None, limits_for(tmp_path))
    prepared = prepare(loaded, tmp_path, fake_embedder, title=None)
    assert prepared.title == "Advanced parameters"
    assert [row.position for row in prepared.rows] == list(range(len(prepared.rows)))
    joined = "\n".join(row.text for row in prepared.rows)
    assert "kafka_connect" in joined and "private access" in joined
    assert all(len(row.embedding) == FakeEmbedder.dim for row in prepared.rows)
    assert fake_embedder.calls and len(fake_embedder.calls) == 1  # one batched call


def test_prepare_source_resolves_absolute_includes_against_the_sphinx_root(
    tmp_path: Path, fake_embedder: FakeEmbedder
) -> None:
    repo = tmp_path / "devportal"  # the data root holds the clone one level down, as in Docker
    (repo / "includes").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "conf.py").write_text("project = 'x'\n")
    (repo / "includes" / "config-kafka.rst").write_text("``ip_filter``\n-------------\n*array*\n")
    (repo / "docs" / "advanced-params.rst").write_text(
        "Advanced parameters\n===================\n\n.. include:: /includes/config-kafka.rst\n"
    )
    loaded = load_file("devportal/docs/advanced-params.rst", None, limits_for(tmp_path))
    prepared = prepare(loaded, tmp_path, fake_embedder, title=None)
    assert any("ip_filter" in row.heading_path for row in prepared.rows)
    assert sphinx_project_root(repo / "docs" / "advanced-params.rst", tmp_path) == repo
    assert sphinx_project_root(tmp_path / "loose.rst", tmp_path) == tmp_path


def test_prepare_source_title_precedence(tmp_path: Path, fake_embedder: FakeEmbedder) -> None:
    (tmp_path / "noheading.md").write_text("just a paragraph\n")
    loaded = load_file("noheading.md", None, limits_for(tmp_path))
    by_filename = prepare(loaded, tmp_path, fake_embedder, title=None)
    explicit = prepare(loaded, tmp_path, fake_embedder, title="Given")
    assert (by_filename.title, explicit.title) == ("noheading", "Given")


def test_prepare_source_with_no_content_blocks_has_zero_rows(
    tmp_path: Path, fake_embedder: FakeEmbedder
) -> None:
    (tmp_path / "nav.rst").write_text("Nav page\n========\n\n.. tableofcontents::\n")
    loaded = load_file("nav.rst", None, limits_for(tmp_path))
    prepared = prepare(loaded, tmp_path, fake_embedder, title=None)
    assert prepared.rows == ()
    assert fake_embedder.calls == []  # nothing to embed, no model call


def test_index_hash_is_stable_and_bound_to_the_pipeline_version() -> None:
    assert index_hash("a") == index_hash("a") != index_hash("b")
    assert index_hash("a") != hashlib.sha256(b"a").hexdigest()  # the version is mixed in


def test_documents_under_filters_and_sorts(tmp_path: Path) -> None:
    for name in ("b.rst", "a.md", "c.txt", "sub/d.RST", "sub/e.png"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("x")
    found = [str(p.relative_to(tmp_path)) for p in _documents_under(tmp_path)]
    assert found == ["a.md", "b.rst", "sub/d.RST"]
    assert _documents_under(tmp_path / "a.md") == [tmp_path / "a.md"]
