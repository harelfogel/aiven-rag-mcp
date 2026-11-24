"""Sanity checks on the real corpus; skipped when the clone is missing."""

from pathlib import Path

import pytest

from rag_mcp.chunking import ChunkConfig, chunk_document
from rag_mcp.parsing import Format, parse
from rag_mcp.parsing.includes import expand_includes, file_include_resolver
from rag_mcp.parsing.model import BlockKind
from tests.conftest import word_count

CONFIG = ChunkConfig(target_tokens=300, max_tokens=380, min_tokens=25)  # words, not tokens


def load(root: Path, relative: str) -> str:
    path = root / relative
    return expand_includes(path.read_text(), file_include_resolver(root, path))


def test_config_params_come_through_the_include(devportal: Path) -> None:
    doc = parse(load(devportal, "docs/products/kafka/reference/advanced-params.rst"), Format.RST)
    paths = [s.heading_path for s in doc.sections]
    assert (
        "Advanced parameters for Aiven for Apache Kafka®",
        "private_access",
        "kafka_connect",
    ) in paths
    chunks = chunk_document(doc, word_count, CONFIG)
    hits = [c for c in chunks if "kafka_connect" in c.text]
    assert hits and all(c.heading_path[0].startswith("Advanced parameters") for c in hits)


def test_howto_code_block_stays_whole(devportal: Path) -> None:
    text = load(devportal, "docs/products/kafka/howto/configure-with-kafka-cli.rst")
    chunks = chunk_document(parse(text, Format.RST), word_count, CONFIG)
    containing = [c for c in chunks if "--config retention.ms=180000" in c.text]
    assert len(containing) == 1
    assert "--bootstrap-server <KAFKA_SERVICE_URI>  \\\n" in containing[0].text


@pytest.mark.slow
def test_whole_corpus_parses(devportal: Path) -> None:
    files = sorted((devportal / "docs").rglob("*.rst"))
    assert len(files) > 700
    total_chunks = 0
    for path in files:
        doc = parse(load(devportal, str(path.relative_to(devportal))), Format.RST)
        chunks = chunk_document(doc, word_count, CONFIG)
        total_chunks += len(chunks)
        for chunk in chunks:
            assert chunk.text.strip()
            for block_kind in (BlockKind.CODE, BlockKind.TABLE):
                assert block_kind  # placeholder to keep the loop explicit
    assert total_chunks > 3000
