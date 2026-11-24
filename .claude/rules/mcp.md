---
paths:
  - "src/rag_mcp/server.py"
  - "src/rag_mcp/tools.py"
  - "src/rag_mcp/prompts.py"
  - "src/rag_mcp/cli.py"
---

# MCP server

Three tools over stdio: `ingest(source, kind, title)`, `search(query, top_k, mode)`,
`list_sources()`.

## stdout belongs to the protocol

- stdout carries JSON-RPC frames. One stray byte corrupts the session.
- `print()` is forbidden anywhere in `src/`. Logging goes to stderr via `logging`.
- Third-party chatter counts too: disable fastembed/huggingface progress bars and tqdm, and keep
  `docker exec -i` (not `docker compose run`, which prints to stdout) as the launcher.

## Tools

- Descriptions, argument docs, and prompt text live in one module and nowhere else. They are read by
  a model, so each says what the tool returns and when to use it, in one or two plain sentences.
- Arguments are a typed schema with explicit bounds (`top_k: int` 1–20, `mode` an enum). Validate on
  entry and reject with a code; never clamp silently.
- Errors to the client are `ToolError("<code>: <sentence>")`, the code from the closed set in
  `errors.md`. Anything else the SDK treats as a crash and the model only sees
  `Error executing tool <name>`. Never an error string inside a successful result, never a
  traceback to the client, never a dead server: a tool that raises must still answer the next call.
- Argument validation can also be a `ValueError` inside a pydantic validator; the SDK reports that
  as an argument-validation failure, which is anticipated too.
- Output is compact and citable: path, heading path, URL, capped text, score. No whole pages,
  no echoing the corpus, no fields a client cannot use.
- Tools are stateless between calls. Everything durable is in Postgres.
- Long work reports progress through the MCP progress token rather than log spam.

## Input guards

- `kind="file"`: resolve the path and require it to stay under the configured data root
  (`Path.resolve()` then `is_relative_to`), reject symlinks that escape it, enforce a size cap,
  and accept only the extensions `parsing.format_for_path` knows (`.rst`, `.md`, `.markdown`);
  anything else is rejected rather than silently parsed as plain text.
- `kind="url"`: `https`/`http` only, DNS resolved and private/loopback/link-local ranges rejected
  (including after redirects), redirect count bounded, size cap, timeout from settings.
- `kind="text"`: size cap, reject empty or non-UTF-8 input.
- A rejected input is a `ToolError` with the reason the caller can act on, logged once at warning.
