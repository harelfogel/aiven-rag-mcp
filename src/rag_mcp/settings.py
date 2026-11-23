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
    log_level: str = "INFO"

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
