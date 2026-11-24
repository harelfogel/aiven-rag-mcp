from pathlib import Path

import pytest

from rag_mcp.chunking import ChunkConfig

DEVPORTAL = Path(__file__).resolve().parent.parent / "data" / "devportal"


def word_count(text: str) -> int:
    """Stand-in token counter for unit tests; the real tokenizer arrives with the embedder."""
    return len(text.split())


@pytest.fixture
def config() -> ChunkConfig:
    return ChunkConfig(target_tokens=40, max_tokens=50, min_tokens=6)


@pytest.fixture
def devportal() -> Path:
    if not DEVPORTAL.is_dir():
        pytest.skip("devportal clone missing; see README for the clone command")
    return DEVPORTAL
