# CLAUDE.md

RAG MCP server over the Aiven devportal: ingest the docs, search them, cite the source.
Python 3.12 · mcp 2.3 · fastembed (ONNX, CPU) · psycopg 3 · Postgres 17 + pgvector.

## Read first

- `PLAN.md` — architecture, the ten decisions, assumptions, milestones. Read before any change.
- `docs/decisions/` — one short ADR per trade-off that could honestly have gone the other way.
- `docs/glossary.md` — every RAG, MCP and Postgres term this repo uses, in plain words. `/glossary`
  looks a term up and adds missing ones.

## Rules

| File in `.claude/rules/` | Covers | Loaded |
|---|---|---|
| `clean-code.md` | names, function and file size, dataclasses at boundaries, config | always |
| `errors.md` | exception taxonomy, where to catch, error codes, logging, retries | editing `src/` |
| `database.md` | ACID ingest, index-backed queries, pgvector operators | `db.py`, `repository.py`, `schema.sql` |
| `rag.md` | parsing, chunking, embedding, hybrid search, citations, injection | the pipeline modules |
| `mcp.md` | stdio hygiene, tool schemas, input guards, compact output | `server.py`, `tools.py`, `cli.py` |
| `testing.md` | the edge cases every change is reviewed against | `tests/` |
| `ops.md` | non-root container, pinned images, no secrets, reproducible build | Dockerfile, compose |

A row without a path is loaded every session; the others load when Claude opens a matching file
with Read, Edit or Write. **Before editing a file, read every rule file whose row matches it** — a
rule only binds if it was read. `/review` checks a diff against the same files.

Each rule file is the authority on its topic. If this file and a rule file disagree, the rule file
wins — fix the contradiction, do not pick a side silently.

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

## Never commit

The assignment PDF, the prep book, the private brief, `.env`, or `.claude/skills/explain-like-harel/`.
