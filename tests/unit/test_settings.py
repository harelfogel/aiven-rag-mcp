import pytest

from rag_mcp.settings import Settings, SettingsError

BASE = {"DATABASE_URL": "postgresql://u:p@h/db"}


def test_defaults_apply_when_env_is_minimal() -> None:
    s = Settings.from_env(BASE)
    assert s.database_url == BASE["DATABASE_URL"]
    assert s.db_pool_max == 4
    assert s.embedding_dim == 384
    assert s.log_level == "INFO"


def test_database_url_is_required() -> None:
    with pytest.raises(SettingsError, match="DATABASE_URL"):
        Settings.from_env({})
    with pytest.raises(SettingsError, match="DATABASE_URL"):
        Settings.from_env({"DATABASE_URL": "   "})


def test_blank_values_fall_back_to_defaults() -> None:
    s = Settings.from_env({**BASE, "EMBEDDING_DIM": "", "LOG_LEVEL": " "})
    assert s.embedding_dim == 384
    assert s.log_level == "INFO"


@pytest.mark.parametrize("raw", ["abc", "3.5", "-1", "0"])
def test_bad_embedding_dim_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="EMBEDDING_DIM"):
        Settings.from_env({**BASE, "EMBEDDING_DIM": raw})


def test_timeout_accepts_float_and_enforces_minimum() -> None:
    assert Settings.from_env({**BASE, "DB_CONNECT_TIMEOUT_S": "2.5"}).db_connect_timeout_s == 2.5
    with pytest.raises(SettingsError, match="DB_CONNECT_TIMEOUT_S"):
        Settings.from_env({**BASE, "DB_CONNECT_TIMEOUT_S": "0.1"})


def test_log_level_is_normalized_and_validated() -> None:
    assert Settings.from_env({**BASE, "LOG_LEVEL": "debug"}).log_level == "DEBUG"
    with pytest.raises(SettingsError, match="LOG_LEVEL"):
        Settings.from_env({**BASE, "LOG_LEVEL": "loud"})


def test_loader_settings_defaults_and_validation() -> None:
    s = Settings.from_env(BASE)
    assert (s.data_root, s.ingest_max_bytes, s.url_max_redirects) == ("/data", 5_000_000, 3)
    assert Settings.from_env({**BASE, "URL_MAX_REDIRECTS": "0"}).url_max_redirects == 0
    with pytest.raises(SettingsError, match="INGEST_MAX_BYTES"):
        Settings.from_env({**BASE, "INGEST_MAX_BYTES": "0"})
