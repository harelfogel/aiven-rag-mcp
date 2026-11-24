# 004: Idempotent ingest keyed by a hash of what is indexed

## Context
Re-ingesting the devportal must be cheap and safe: the README tells people to run it, CI could
run it on every docs commit, and two ingests of the same page may overlap. A naive "insert
again" duplicates chunks; a naive "delete then insert" leaves a page missing if the process dies
in between.

## Options
1. Per-chunk diffing: hash every chunk, insert new ones, delete missing ones. Minimal writes,
   but position bookkeeping and a second code path for the partial case.
2. Per-source replace: hash the source, skip if unchanged, otherwise replace all its chunks in one
   transaction.

## Decision
Option 2. The hash covers the text after `.. include::` expansion plus a `PIPELINE_VERSION`
constant: an edited include re-ingests the pages that use it, and a parser or chunker change
re-ingests everything once the version is bumped. Both were real defects found on the first
full run, not hypotheticals. The pipeline checks the hash with one cheap read before loading
the model, embeds outside any transaction, then opens one transaction per source that takes
`pg_advisory_xact_lock(1, hashtext(uri))`, re-reads the hash, upserts the source row, deletes
the old chunks and inserts the new ones. A crash leaves the previous version intact; two
concurrent ingests of one URI serialize (tested with six threads).

## Consequences
- Second full run of 788 pages: under 10 seconds, no model call, no write.
- A one-character edit re-embeds the whole page (median 5 chunks), which is the cost of not
  diffing chunks. Acceptable at this corpus size; per-chunk diffing is the next step if pages
  were large and changed often.
- Text pasted through the tool is identified by its own content hash, so the same paste twice is
  one source and an edited paste is a new one.
