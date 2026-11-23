# CLAUDE.md

RAG MCP server over the Aiven devportal. Python 3.12, mcp 2.3, fastembed, psycopg 3, pgvector.
Read `PLAN.md` first; decisions live there and in `docs/decisions/`.

## Commands

```
uv sync                                   # install
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest -q -m "not integration"     # unit tests, no Docker
uv run pytest -q -m integration           # needs Postgres (docker compose up -d db)
docker compose up -d --build              # db + server
docker compose exec server rag-mcp ingest /data/devportal
```

## How we work

- Explain before building: for any non-trivial change, state what, why, the alternative rejected,
  and the question an interviewer would ask about it. Then build.
- One milestone at a time (see PLAN.md). Stop after each and report.
- Nothing is committed without Harel's approval of the diff summary and message.
  Commit messages are short and plain. No co-author trailers.
- Token discipline: no speculative abstractions, no boilerplate docs, small diffs.

## Code rules

- Small single-purpose functions, type hints everywhere, `ruff` + `mypy` clean.
- Config only via `settings.py` (env vars with validated defaults). No hardcoded paths, models, sizes.
- Tool descriptions and prompts live in one module, not scattered strings.
- Errors to the client are `ToolError` with a short code; never return error strings; never crash.
- Logging goes to stderr via `logging`; never `print()` (stdout is the MCP channel).
- Parameterized SQL only. Secrets only from env. Container runs as non-root.
- Every edge case in PLAN.md's standards gets a test when its code lands.

## Never commit

The assignment PDF, the prep book, the private brief, `.env`, or `.claude/skills/explain-like-harel/`.
