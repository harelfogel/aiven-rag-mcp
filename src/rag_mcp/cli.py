"""Command-line entrypoints.

`up` is the container's main process: apply the schema, then idle. Claude Code starts the
MCP server itself with `docker exec -i rag-mcp rag-mcp serve` (arrives in M5).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from psycopg_pool import PoolTimeout

from rag_mcp import db
from rag_mcp.settings import Settings, SettingsError

log = logging.getLogger("rag_mcp")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rag-mcp")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up", help="apply the schema, then idle for `docker exec`")
    sub.add_parser("init-db", help="apply the schema and exit")
    args = parser.parse_args(argv)

    _configure_logging("INFO")
    try:
        settings = Settings.from_env()
    except SettingsError as exc:
        log.error("bad configuration: %s", exc)
        return 2
    _configure_logging(settings.log_level)

    try:
        pool = db.connect(settings)
    except PoolTimeout:
        log.error("Postgres did not become reachable within %.0fs", settings.db_connect_timeout_s)
        return 1
    except db.SchemaError as exc:
        log.error("%s", exc)
        return 1

    if args.command == "up":
        _idle()
    pool.close()
    return 0


def _configure_logging(level: str) -> None:
    # stderr only: stdout is the MCP channel.
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _idle() -> None:
    """Block until SIGTERM/SIGINT. As PID 1 the process must handle SIGTERM itself,
    otherwise `docker stop` waits 10 s and kills it."""

    def stop(signum: int, _frame: object) -> None:
        log.info("received signal %d, exiting", signum)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("ready; idle until `docker exec -i rag-mcp rag-mcp serve`")
    while True:
        signal.pause()
