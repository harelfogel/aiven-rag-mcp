---
paths:
  - "tests/**/*.py"
---

# Tests

`uv run pytest -q -m "not integration"` must stay green with no Docker. Markers: `integration`
(needs Postgres), `slow` (walks the whole 817-file corpus). Every new branch gets a test; every bug
gets its failing test first.

## Conventions

- Name the behaviour: `test_<unit>_<condition>_<expected>`
  (`test_chunker_keeps_oversized_code_block_whole`). No `test_1`, no `test_it_works`.
- One behaviour per test, assertions on values not on call counts, no mocking of our own code.
- Postgres is real in integration tests (a throwaway database), not mocked. The parser and chunker
  are tested on real devportal files, not only on synthetic strings.
- Fixtures in `conftest.py`, data inline in the test that needs it.

## The edge-case list every change is reviewed against

Input
- empty, whitespace-only, and non-UTF-8/binary input; a file that does not exist or cannot be read
- size caps hit exactly and exceeded; a `top_k` of 0, negative, and above 20
- path traversal (`../`, absolute path, symlink out of the data root); a non-`.rst`/`.md` file
- SSRF: `localhost`, `127.0.0.1`, `169.254.169.254`, a private IP, a redirect to any of them
- a query that is only stopwords or only punctuation

Documents
- heading underline shorter than its title, inconsistent adornment order, a title with no body
- unknown directive, nested `include`, an `include` cycle, a missing `include` target
- a code block and a table larger than the embedding window; a table with no header row
- a section smaller than `chunk_min_tokens`; a document with no headings at all

Database and search
- Postgres not ready at startup, and lost mid-ingest (the transaction must roll back whole)
- duplicate ingest of unchanged content reports `unchanged` and writes nothing
- two concurrent ingests of the same URI; a changed `EMBEDDING_MODEL` against an existing volume
- no results; ties in RRF; a `source` row with zero chunks
- every `chunks` query has an `EXPLAIN` test asserting an index scan (`database.md`)
