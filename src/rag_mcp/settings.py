"""Runtime configuration: every knob is an env var with a validated default.

Nothing else in the code base reads os.environ.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass


class SettingsError(ValueError):
    """An env var is missing or has an invalid value. The message names the variable."""


_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})


@dataclass(frozen=True)
class Settings:
    database_url: str
    db_pool_max: int = 4
    db_connect_timeout_s: float = 60.0
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_cache_dir: str = ""  # empty = fastembed's default cache
    embed_batch_size: int = 64
    chunk_target_tokens: int = 400
    chunk_max_tokens: int = 512
    chunk_min_tokens: int = 30
    search_default_top_k: int = 5
    search_max_top_k: int = 20
    search_candidates: int = 20  # per ranked list, before fusion
    rrf_k: int = 60  # the damping constant from the RRF paper
    hnsw_ef_search: int = 100  # recall vs speed; must be >= search_candidates
    search_text_chars: int = 1200  # per result, cut in SQL so long chunks never cross the wire
    query_max_chars: int = 1000
    list_sources_default: int = 25
    list_sources_max: int = 100
    source_url_base: str = "https://github.com/aiven/devportal/blob/main/"
    source_path_prefix: str = "devportal/"  # stripped from a file uri to get the repo path
    data_root: str = "/data"
    ready_file: str = "/tmp/rag-mcp.ready"  # created once the idle process is warm; healthcheck
    ingest_max_bytes: int = 5_000_000
    url_timeout_s: float = 10.0
    url_max_redirects: int = 3
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not self.chunk_min_tokens < self.chunk_target_tokens <= self.chunk_max_tokens:
            raise SettingsError(
                "need CHUNK_MIN_TOKENS < CHUNK_TARGET_TOKENS <= CHUNK_MAX_TOKENS, got "
                f"{self.chunk_min_tokens} / {self.chunk_target_tokens} / {self.chunk_max_tokens}"
            )
        self._check_search_limits()

    def _check_search_limits(self) -> None:
        """Relations that keep search honest: a full page must be fillable from one list, and the
        index must be allowed to return as many rows as we ask it for."""
        if not self.search_default_top_k <= self.search_max_top_k <= self.search_candidates:
            raise SettingsError(
                "need SEARCH_DEFAULT_TOP_K <= SEARCH_MAX_TOP_K <= SEARCH_CANDIDATES, got "
                f"{self.search_default_top_k} / {self.search_max_top_k} / {self.search_candidates}"
            )
        if self.search_candidates > self.hnsw_ef_search:
            raise SettingsError(
                f"HNSW_EF_SEARCH ({self.hnsw_ef_search}) must be >= SEARCH_CANDIDATES "
                f"({self.search_candidates}): the index returns at most ef_search rows"
            )
        if self.list_sources_default > self.list_sources_max:
            raise SettingsError("LIST_SOURCES_DEFAULT must be <= LIST_SOURCES_MAX")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        return cls(
            database_url=_required(env, "DATABASE_URL"),
            db_pool_max=_number(env, "DB_POOL_MAX", cls.db_pool_max, int, minimum=1),
            db_connect_timeout_s=_number(
                env, "DB_CONNECT_TIMEOUT_S", cls.db_connect_timeout_s, float, minimum=1
            ),
            embedding_model=_text(env, "EMBEDDING_MODEL", cls.embedding_model),
            embedding_dim=_number(env, "EMBEDDING_DIM", cls.embedding_dim, int, minimum=1),
            embedding_cache_dir=_text(env, "EMBEDDING_CACHE_DIR", cls.embedding_cache_dir),
            embed_batch_size=_number(env, "EMBED_BATCH_SIZE", cls.embed_batch_size, int, minimum=1),
            chunk_target_tokens=_number(
                env, "CHUNK_TARGET_TOKENS", cls.chunk_target_tokens, int, minimum=1
            ),
            chunk_max_tokens=_number(env, "CHUNK_MAX_TOKENS", cls.chunk_max_tokens, int, minimum=1),
            chunk_min_tokens=_number(env, "CHUNK_MIN_TOKENS", cls.chunk_min_tokens, int, minimum=0),
            search_default_top_k=_number(
                env, "SEARCH_DEFAULT_TOP_K", cls.search_default_top_k, int, minimum=1
            ),
            search_max_top_k=_number(env, "SEARCH_MAX_TOP_K", cls.search_max_top_k, int, minimum=1),
            search_candidates=_number(
                env, "SEARCH_CANDIDATES", cls.search_candidates, int, minimum=1
            ),
            rrf_k=_number(env, "RRF_K", cls.rrf_k, int, minimum=1),
            hnsw_ef_search=_number(env, "HNSW_EF_SEARCH", cls.hnsw_ef_search, int, minimum=1),
            search_text_chars=_number(
                env, "SEARCH_TEXT_CHARS", cls.search_text_chars, int, minimum=50
            ),
            query_max_chars=_number(env, "QUERY_MAX_CHARS", cls.query_max_chars, int, minimum=10),
            list_sources_default=_number(
                env, "LIST_SOURCES_DEFAULT", cls.list_sources_default, int, minimum=1
            ),
            list_sources_max=_number(env, "LIST_SOURCES_MAX", cls.list_sources_max, int, minimum=1),
            source_url_base=_text(env, "SOURCE_URL_BASE", cls.source_url_base),
            source_path_prefix=_text(env, "SOURCE_PATH_PREFIX", cls.source_path_prefix),
            data_root=_text(env, "DATA_ROOT", cls.data_root),
            ready_file=_text(env, "READY_FILE", cls.ready_file),
            ingest_max_bytes=_number(env, "INGEST_MAX_BYTES", cls.ingest_max_bytes, int, minimum=1),
            url_timeout_s=_number(env, "URL_TIMEOUT_S", cls.url_timeout_s, float, minimum=1),
            url_max_redirects=_number(
                env, "URL_MAX_REDIRECTS", cls.url_max_redirects, int, minimum=0
            ),
            log_level=_choice(env, "LOG_LEVEL", cls.log_level, _LOG_LEVELS),
        )


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise SettingsError(f"{key} is required and not set")
    return value


def _text(env: Mapping[str, str], key: str, default: str) -> str:
    raw = env.get(key)
    return default if raw is None or not raw.strip() else raw.strip()


def _number[T: (int, float)](
    env: Mapping[str, str], key: str, default: T, convert: Callable[[str], T], *, minimum: T
) -> T:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = convert(raw.strip())
    except ValueError:
        raise SettingsError(f"{key} must be a {convert.__name__}, got {raw!r}") from None
    if value < minimum:
        raise SettingsError(f"{key} must be >= {minimum}, got {value}")
    return value


def _choice(env: Mapping[str, str], key: str, default: str, allowed: frozenset[str]) -> str:
    value = _text(env, key, default).upper()
    if value not in allowed:
        raise SettingsError(f"{key} must be one of {sorted(allowed)}, got {value!r}")
    return value
