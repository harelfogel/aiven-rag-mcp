# Clean code

Always loaded: this is how every file in `src/` and `tests/` is expected to read.

## Names say what, docstrings say why

- Modules and functions: `snake_case`, a verb for an action (`parse_rst`, `split_section`,
  `fuse_with_rrf`), a noun for a pure accessor (`heading_path`).
- Classes: `CapWords` nouns (`Section`, `Document`, `SearchResult`). No `Manager`, `Helper`,
  `Util`, `Service`, `Handler` — if that is the only honest name, the class does too much.
- Constants: `UPPER_CASE` at module level (`_SCHEMA_LOCK_KEY`, `_LOG_LEVELS`).
- No abbreviations except `db`, `url`, `id`, `uri`, `tsv`, `conn`, `fmt`. Write `settings`,
  not `cfg`; `embedding`, not `emb`; `document`, not `doc`.
- A RAG, MCP or Postgres term in a name means what `docs/glossary.md` says it means, nothing else.
  A new one of those goes in the glossary first (`/glossary`).
- No single letters outside comprehensions and no `data`, `info`, `obj`, `tmp`, `result2`.
- A full-sentence name beats a comment: `is_heading_underline(line, width)` needs no comment.
- A docstring explains why the code exists or what it refuses to do, never what the next line does.
  Example, from `db.py`: "DDL cannot take bind parameters."

## Shape

- One function, one purpose, one level of abstraction. If you cannot name it without "and", split it.
- Functions stay readable on one screen (~30 lines; the longest today is 28) and take ≤ 4
  positional arguments; past that, pass a frozen dataclass or use keyword-only arguments.
- Files stay under ~200 lines. Split by responsibility (parser, chunker, repository, embedder)
  before that, not by size.
- Private helpers are `_prefixed` and sit below the public function that uses them.
- Early returns over nested `if`. Past two levels of nesting, extract a named helper.
  Known exception, open as an M2 finding: `parse_blocks` in `rst.py` nests 7 levels and
  `markdown.py`'s nests 5 — line-by-line state machines. Either accept them as the one documented
  exception or extract the inner loop; they must not grow either way.
- No speculative abstraction: no base class, protocol, or plugin registry until a second real
  implementation exists. The exception is the embedding provider, which PLAN.md decision 1 names
  as an interface on purpose.

## Typing and data

- Type hints on every parameter and return, including `-> None`. `mypy --strict` must pass.
- Data that crosses a module boundary is a frozen dataclass (`Block`, `Section`, `Document`),
  never a dict, tuple, or positional pair. Inside one function, local tuples are fine.
- Prefer immutable containers in those dataclasses (`tuple[...]`, not `list[...]`).
- `StrEnum` for closed sets of strings (`BlockKind`), not bare string literals.
- No `Any` in our own signatures; `Any` only where a third-party stub forces it
  (`Connection[Any]` from psycopg).

## Configuration

- Every knob is an env var with a validated default in `settings.py`, which is the only module that
  reads `os.environ`. No model name, path, size, limit, or timeout literal anywhere else.
- `Settings` is passed in explicitly. No global singleton, no import-time side effects.
- Validation lives in `Settings.__post_init__` and fails loudly at startup, not at first use.

## Comments

- Comment the non-obvious decision, the workaround, and the invariant. See the `cryptography<49`
  note in `pyproject.toml`: it explains a choice a reader would otherwise undo.
- No commented-out code, no `TODO` without a name and a milestone, no decorative banners.
