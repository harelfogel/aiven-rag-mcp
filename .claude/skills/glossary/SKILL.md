---
name: glossary
description: Look up a RAG, MCP, Postgres or project term in docs/glossary.md and explain it in plain words with a real example from this repo; verify and add the entry when it is missing. Use whenever a term in the code or docs is unfamiliar, when asked what a term means, and before introducing a new term in code or documentation.
---

The glossary is `docs/glossary.md`: the project's shared vocabulary, one meaning per term, written
for a reader who is new to retrieval.

## Looking a term up

1. `grep -in "<term>" docs/glossary.md`. Try the plural, the acronym and the spelled-out form.
2. If it is there, give the answer in this shape and no longer:
   - **one plain sentence** — no jargon inside the definition; if another term is needed, look that
     one up too.
   - **here** — where it actually appears in this repo, with `file:line` or a real value
     (`384 dims`, `MAX_INCLUDE_DEPTH = 3`). Open the file and read it; never describe code from
     memory.
   - **the trade-off** — what choosing it costs, or "none, it is just a name" when that is true.
3. If the term names a decision, point at the PLAN.md row or the ADR in `docs/decisions/` rather
   than re-arguing it.

## Adding a missing term

1. Verify first. A wrong entry is worse than a missing one: grep `src/`, read the file, or grep the
   corpus under `data/`. Do not guess, and do not paste a definition that does not match what this
   code does.
2. Append it under the right `##` section, alphabetically within that section, in the file's style:
   `- **Term** — one sentence. Where it shows up here.` Three lines maximum.
3. If no section fits, propose the new section before writing it.
4. Then explain it in the shape above and say the entry was added.

## Rules

- Every RAG, MCP or Postgres term used in PLAN.md, `.claude/rules/`, the README or a module
  docstring has an entry. A new term of that kind goes in the glossary before it goes in the code.
- One meaning per term, repo-wide. If the code uses a word two ways, that is the finding: report it
  and propose which meaning wins instead of documenting both.
- Plain words, short sentences, a concrete number instead of an adjective. No "leverages",
  "utilises", "robust".
- Never invent a mechanism to make a definition tidier. Say which part you did not verify.
- `docs/glossary.md` is documentation: definitions only, no instructions to Claude inside it.
