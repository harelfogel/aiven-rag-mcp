---
paths:
  - "src/**/*.py"
---

# Errors

The rule in one line: raise a narrow, named exception where the problem is detected; translate it to
a `ToolError` with a short code at the single MCP boundary; never let a traceback reach the client
and never let the server die.

## Taxonomy

- One exception class per failure domain. Today: `SettingsError(ValueError)` in `settings.py` and
  `SchemaError(RuntimeError)` in `db.py`. **Target (M5):** a `RagError` base carrying a `code`, with
  the rest below added as their modules land. Until then, each new module gets its named exception
  and the boundary maps it by type.

  | Exception | Raised by | Code to the client | Exists |
  |---|---|---|---|
  | `SettingsError` | `settings.py` | startup only, never reaches a client | yes |
  | `SchemaError` | `db.py` | `internal` | yes |
  | `ParseError` | `parsing/` | `bad_document` | M2+ |
  | `LoaderError` | `loaders.py` (path, size, scheme, SSRF) | `bad_request` / `too_large` | M3 |
  | `EmbeddingError` | `embedding.py` | `embedding_failed` | M4 |
  | `RepositoryError` | `repository.py` | `internal` | M4 |

- Codes are a closed set in one module, stable and machine-readable. `mcp`'s `ToolError` carries
  only a message, so the code is its prefix: `ToolError("too_large: file is 12 MB, cap is 2 MB")`.
  The code is what a client can branch on; the sentence is what the model reads.
- No new exception type for a case an existing one covers. No exception used as control flow.

## Raising

- The message names the offending value and the fix, and is safe to show:
  `f"{key} must be >= {minimum}, got {value}"`. Never a secret, a connection string, or a full file.
- Always chain: `raise ParseError(...) from error`. Use `from None` only when the original is pure
  noise (`settings.py` does this for `int()` failures) and say so in a comment or docstring.
- Validate at the edge — settings at startup, tool arguments on entry, loader inputs before reading —
  then trust the values inside. No defensive re-checks in every function.
- `assert` is for test invariants only. Never for runtime validation (`-O` strips it).

## Catching

- Never `except:` and never bare `except Exception` — except in exactly one place, the tool boundary,
  which logs with `log.exception` and re-raises as `ToolError("<code>: <sentence>")`. This matters:
  the SDK returns a `ToolError` to the model as `is_error=True` with our message, and logs it at
  INFO; any other exception becomes a bare `Error executing tool <name>` with a traceback at ERROR,
  so an unmapped error tells the model nothing.
- Catch the narrowest type, around the smallest block, and only when you can add information or
  recover. Otherwise let it propagate.
- Never swallow: no `except ...: pass`, no returning `None`, `[]`, `False`, or an error string to
  mean failure. A failed call raises.
- Resources are released by `with` (`pool.connection()`, `conn.transaction()`, `open()`),
  not by `try/finally` written by hand.

## Logging

- Log once, at the boundary that handles the error. Inner layers raise and stay silent.
- `logging` to stderr only; `print()` is forbidden (stdout is the MCP channel — see `mcp.md`).
- `log.exception` when we handled an unexpected error, `log.warning` for a skipped input we expect
  to see (an unparsable file during a 817-file ingest), `log.info` for lifecycle events.
- Lazy formatting: `log.info("ingested %d chunks", count)`, never an f-string.

## Retries and partial failure

- Retry only transient infrastructure errors: the pool already retries "Postgres not ready" until
  `db_connect_timeout_s`. Nothing else retries by default.
- A retry is bounded, backs off, and logs the final failure. Never retry a validation error,
  a parse error, or anything non-idempotent.
- Batch ingest: one bad file is logged, counted, and skipped; the run continues and the summary
  reports `ingested / unchanged / failed`. One bad *chunk* inside a source fails that whole source,
  because a half-ingested document is worse than a missing one (see `database.md`).
