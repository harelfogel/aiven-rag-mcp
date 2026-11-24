# 002: Structure-aware chunking instead of fixed windows

## Context
The devportal is 97% RST made of step lists, ~1,500 code blocks, ~330 tables and config
parameters written as one tiny section each (name, type, one-line description). The questions
the server must answer target exactly those: a parameter, a limit, a step. The embedding model
sees 512 tokens.

## Options
1. Fixed windows (e.g. 500 tokens, 50 overlap) over the raw text: trivial, format-agnostic, but
   cuts tables, code and step lists wherever the counter lands.
2. Parse headings, code, tables and paragraphs; chunk per section; pack blocks up to a target.

## Decision
Option 2. A light line-based parser (not a Sphinx build) produces sections with a heading path.
The chunker packs each section's blocks to ~400 tokens, splits only between blocks with one short
paragraph of overlap, and merges tiny neighbouring sections under their shared heading so a
chunk holds several related parameters with their names inline. A single block wider than the
window (two metrics pages are one 2,000-line table each) is split by lines with the table header
repeated in every piece, so each row stays reachable by vector search instead of only the first
512 tokens. The heading path is stored once as a column and prepended only at embed and index time.

## Consequences
- Measured on the corpus with the model's own tokenizer: 788 pages, 3,807 chunks, 712k tokens,
  median 151 tokens, 90th percentile 374, maximum 510, none over the 512 window.
- Table border lines (`+----+`, `=====`) are dropped at parse time: a row of 80 dashes is 75
  tokens of nothing, and left in place it pushed a grid table's header alone to ~500 tokens.
- Cost: ~450 lines of parser and chunker with their own edge cases; malformed RST degrades to
  paragraphs rather than failing. For a plain-prose corpus fixed windows would have been enough.
