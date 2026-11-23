#!/usr/bin/env bash
# Claude Code PreToolUse hook: when the Bash command is a git commit, run lint and unit tests first.
# Exit 2 blocks the tool call and shows stderr to Claude.
set -u
payload="$(cat)"
cmd="$(printf '%s' "$payload" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)"
case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac
cd "$(dirname "$0")/../.." || exit 2
if ! uv run ruff check . >&2; then echo "ruff failed; fix before committing" >&2; exit 2; fi
if ! uv run pytest -q -m "not integration" >&2; then echo "unit tests failed; fix before committing" >&2; exit 2; fi
exit 0
