---
name: review
description: Clean-code and edge-case review of the current diff (or a given path) against this project's rules in CLAUDE.md and the edge-case list in PLAN.md.
---

Review `git diff` (staged and unstaged), or the path given in the arguments.

Check, in this order, and report only real findings with file:line:
1. Correctness and edge cases from PLAN.md standards: empty/binary input, size caps, path traversal,
   SSRF, DB not ready, duplicate ingest, no results, top_k bounds, malformed RST, giant code blocks.
2. MCP rules: no stdout writes, errors are `ToolError`, tool descriptions in one place.
3. Clarity: function size, naming, type hints, dead code, hardcoded values that belong in settings.
4. Tests: is every new branch covered? Name the missing test.
5. Security: parameterized SQL, secrets from env only, non-root container.

Format: one bullet per finding, severity (bug / should fix / nit), the fix in one sentence.
End with the single most important thing to fix before commit. No praise, no summary of the diff.
