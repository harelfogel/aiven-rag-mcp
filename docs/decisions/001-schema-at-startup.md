# 001: Apply the schema at container start, not with a migration tool

## Context
The README must get a stranger from `docker compose up` to a working server without a manual
"create the schema" step. The schema is three tables and two indexes, and the embedding column
width depends on the configured model.

## Options
1. Migration tool (Alembic): versioned history, but a dependency, a config file and a command to run.
2. Postgres image `initdb` scripts: run once on an empty volume only, and cannot read the model width.
3. One idempotent `schema.sql` applied by the server on every start under an advisory lock.

## Decision
Option 3. Every statement is `IF NOT EXISTS`; the server runs it inside one transaction after
taking `pg_advisory_xact_lock`, so two processes starting together cannot race. A `meta` table
records the embedding model and width; a later start with different settings is refused with a
clear message instead of mixing incomparable vectors.

## Consequences
- Zero manual steps and zero migration dependencies.
- Changing a column later means editing the SQL and re-creating the volume (acceptable for a
  system whose content is re-ingestable in minutes). With a long-lived production database I
  would switch to versioned migrations.
