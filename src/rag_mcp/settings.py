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
    data_root: str = "/data"
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
            data_root=_text(env, "DATA_ROOT", cls.data_root),
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
