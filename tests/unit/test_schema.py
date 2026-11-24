from rag_mcp.storage.db import render_schema


def test_schema_renders_embedding_dim() -> None:
    text = render_schema(768).as_string()
    assert "vector(768)" in text
    assert "{dim}" not in text
    assert "CREATE EXTENSION IF NOT EXISTS vector" in text


def test_schema_only_contains_idempotent_statements() -> None:
    text = render_schema(384).as_string()
    creates = [line for line in text.splitlines() if line.startswith("CREATE")]
    assert creates
    assert all("IF NOT EXISTS" in line for line in creates)
