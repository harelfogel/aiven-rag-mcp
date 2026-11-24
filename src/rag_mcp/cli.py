"""Command-line entrypoints.

`up` is the container's main process: apply the schema, then idle. Claude Code starts the
MCP server itself with `docker exec -i rag-mcp rag-mcp serve`.
`ingest PATH` walks a folder under the data root and reports what changed.
`serve` runs the MCP server on stdio; stdout is the protocol, so everything else logs to stderr.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from rag_mcp.embedding import FastEmbedEmbedder
from rag_mcp.errors import RagError
from rag_mcp.evaluation.golden import load_golden
from rag_mcp.evaluation.report import render_markdown
from rag_mcp.evaluation.runner import evaluate
from rag_mcp.ingest import IngestPipeline, ingest_tree
from rag_mcp.search import SearchConfig
from rag_mcp.server.tools import build_server
from rag_mcp.settings import Settings, SettingsError
from rag_mcp.storage import db, repository

log = logging.getLogger("rag_mcp")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rag-mcp")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up", help="apply the schema, then idle for `docker exec`")
    sub.add_parser("init-db", help="apply the schema and exit")
    sub.add_parser("serve", help="run the MCP server on stdio (launched by Claude Code)")
    evaluation = sub.add_parser("eval", help="score retrieval on a golden set; markdown to stdout")
    evaluation.add_argument("golden", type=Path, nargs="?", default=Path("eval/golden"))
    evaluation.add_argument("--repeats", type=int, default=3, help="timing runs per question")
    ingest = sub.add_parser(
        "ingest", help="ingest every .rst/.md under PATH (inside the data root)"
    )
    ingest.add_argument("path", type=Path)
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

    exit_code = 0
    if args.command == "up":
        exit_code = _up(settings)
    elif args.command == "ingest":
        exit_code = _ingest(settings, pool, args.path)
    elif args.command == "serve":
        exit_code = _serve(settings, pool)
    elif args.command == "eval":
        exit_code = _eval(settings, pool, args.golden, args.repeats)
    pool.close()
    return exit_code


def _up(settings: Settings) -> int:
    """Warm the model so the first `docker exec ... serve` is fast, then signal readiness."""
    ready_file = Path(settings.ready_file)
    ready_file.unlink(missing_ok=True)  # a restarted container must not look ready before it is
    try:
        FastEmbedEmbedder.from_settings(settings).embed_query("warm up")
    except RagError as error:
        log.error("%s", error)
        return 1
    ready_file.touch()
    _idle()
    return 0


def _serve(settings: Settings, pool: ConnectionPool) -> int:
    embedder = FastEmbedEmbedder.from_settings(settings)
    try:
        embedder.embed_query("warm up")  # load the model now, not during the first question
    except RagError as error:
        log.error("%s", error)
        return 1
    log.info("MCP server ready on stdio")
    build_server(settings, pool, embedder).run()
    return 0


def _eval(settings: Settings, pool: ConnectionPool, golden_path: Path, repeats: int) -> int:
    try:
        golden = load_golden(golden_path, f"file:{settings.source_path_prefix}")
        embedder = FastEmbedEmbedder.from_settings(settings)
        reports = evaluate(
            pool, embedder, golden, SearchConfig.from_settings(settings), repeats=repeats
        )
    except RagError as error:
        log.error("%s", error)
        return 1
    with pool.connection() as conn:
        _, chunk_count = repository.count_sources(conn)
    for report in reports:
        log.info(
            "%s: recall@5 %.2f, mrr %.2f", report.variant.label, report.recall_at_5, report.mrr
        )
    # This is a report for a person, not the MCP channel: `eval` never runs under `serve`.
    sys.stdout.write(render_markdown(reports, chunk_count=chunk_count, repeats=repeats))
    return 0


def _ingest(settings: Settings, pool: ConnectionPool, path: Path) -> int:
    embedder = FastEmbedEmbedder.from_settings(settings)
    pipeline = IngestPipeline.from_settings(settings, pool, embedder)
    data_root = pipeline.limits.data_root
    root = (path if path.is_absolute() else data_root / path).resolve()
    if not root.is_relative_to(data_root) or not root.exists():
        log.error("PATH must exist under the data root %s, got %s", data_root, path)
        return 2

    def report(done: int, total: int) -> None:
        log.info("ingest progress %d/%d", done, total)

    try:
        summary = ingest_tree(pipeline, root, report=report)
    except RagError as error:
        log.error("%s", error)
        return 1
    except psycopg.Error as error:  # the database went away mid-run; the last source rolled back
        log.error("database error, ingest stopped: %s", error)
        return 1
    log.info(
        "ingest done: %d ingested, %d unchanged, %d failed, %d new chunks in %.1fs (%.1f chunks/s)",
        summary.ingested,
        summary.unchanged,
        summary.failed,
        summary.chunks,
        summary.seconds,
        summary.chunks / summary.seconds if summary.seconds else 0.0,
    )
    return 0 if summary.total and summary.failed < summary.total else 1


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
