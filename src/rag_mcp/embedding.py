"""Embedding provider: the only module that imports fastembed.

`Embedder` is the seam PLAN.md decision 1 names on purpose: a hosted provider would be a second
class with the same four members.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import cached_property
from typing import TYPE_CHECKING, Protocol

from rag_mcp.errors import Code, RagError
from rag_mcp.settings import Settings

if TYPE_CHECKING:  # fastembed and tokenizers ship no stubs; only the names are needed here
    from fastembed import TextEmbedding
    from tokenizers import Tokenizer

log = logging.getLogger(__name__)


class EmbeddingError(RagError):
    """The model could not be loaded or did not produce vectors."""


class Embedder(Protocol):
    @property
    def dim(self) -> int: ...

    def count_tokens(self, text: str) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """bge-style models through fastembed's ONNX runtime, CPU only, loaded on first use."""

    def __init__(self, model_name: str, dim: int, cache_dir: str | None, batch_size: int) -> None:
        self._model_name = model_name
        self._dim = dim
        self._cache_dir = cache_dir
        self._batch_size = batch_size

    @classmethod
    def from_settings(cls, settings: Settings) -> FastEmbedEmbedder:
        return cls(
            settings.embedding_model,
            settings.embedding_dim,
            settings.embedding_cache_dir or None,
            settings.embed_batch_size,
        )

    @property
    def dim(self) -> int:
        return self._dim

    def count_tokens(self, text: str) -> int:
        """Real token count, including the model's special tokens, never truncated."""
        return len(self._counter.encode(text).ids)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = list(self._model.embed(list(texts), batch_size=self._batch_size))
        except Exception as error:  # onnxruntime raises its own hierarchy
            raise EmbeddingError(Code.EMBEDDING_FAILED, f"embedding failed: {error}") from error
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Queries longer than the window are truncated by the model's tokenizer, never rejected."""
        try:
            (vector,) = list(self._model.query_embed(text))
        except Exception as error:
            raise EmbeddingError(
                Code.EMBEDDING_FAILED, f"query embedding failed: {error}"
            ) from error
        return [float(value) for value in vector.tolist()]

    @cached_property
    def _model(self) -> TextEmbedding:
        from fastembed import TextEmbedding

        log.info("loading embedding model %s", self._model_name)
        try:
            model = TextEmbedding(self._model_name, cache_dir=self._cache_dir)
        except Exception as error:
            message = f"cannot load embedding model {self._model_name!r}: {error}"
            raise EmbeddingError(Code.EMBEDDING_FAILED, message) from error
        actual = TextEmbedding.get_embedding_size(self._model_name)
        if actual != self._dim:
            raise EmbeddingError(
                Code.EMBEDDING_FAILED,
                f"{self._model_name} produces {actual} dims but EMBEDDING_DIM is {self._dim}",
            )
        return model

    @cached_property
    def _counter(self) -> Tokenizer:
        """A private copy of the model's tokenizer with truncation off, so counts are exact."""
        from tokenizers import Tokenizer

        # The concrete OnnxTextEmbedding has a tokenizer; its declared base type does not.
        tokenizer = self._model.model.tokenizer  # type: ignore[attr-defined]
        counter = Tokenizer.from_str(tokenizer.to_str())
        counter.no_truncation()
        return counter
