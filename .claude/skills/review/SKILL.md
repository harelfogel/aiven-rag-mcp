---
name: review
description: Clean-code and edge-case review of the current diff (or a given path) against this project's rules in .claude/rules/.
---

Review `git diff` (staged and unstaged), or the path given in the arguments.

The rules are in `.claude/rules/`. Read the ones the diff touches before reviewing:
`clean-code.md`, `errors.md`, `database.md`, `rag.md`, `mcp.md`, `testing.md`.

Check, in this order, and report only real findings with file:line:
1. Correctness and edge cases from the list in `.claude/rules/testing.md`.
2. Transactions and queries against `.claude/rules/database.md`: one source = one transaction,
   embeddings computed outside it, `<=>` with `ORDER BY` + `LIMIT`, no `SELECT *`, parameterized SQL.
3. Errors against `.claude/rules/errors.md`: named exception at the source, one boundary catch,
   `ToolError` with a code, nothing swallowed, logged once.
4. MCP rules from `.claude/rules/mcp.md`: no stdout writes, bounded arguments, descriptions in one module.
5. Clarity against `.claude/rules/clean-code.md`: function and file size, naming, type hints,
   dead code, values that belong in `settings.py`.
6. Tests: is every new branch covered? Name the missing test.
7. Security: parameterized SQL, secrets from env only, non-root container, input guards.

Format: one bullet per finding, severity (bug / should fix / nit), the fix in one sentence.
End with the single most important thing to fix before commit. No praise, no summary of the diff.
