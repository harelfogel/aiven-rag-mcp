"""Resolve `.. include::` before parsing, so included headings join the page's own."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

_INCLUDE = re.compile(r"^([ \t]*)\.\. include::[ \t]*(\S+)[ \t]*$", re.MULTILINE)
# Deeper nesting than this is a loop in practice; devportal uses depth 1.
MAX_INCLUDE_DEPTH = 3

IncludeResolver = Callable[[str], str | None]
"""Maps an include target to its text, or None when it must be skipped."""


def expand_includes(text: str, resolve: IncludeResolver, depth: int = 0) -> str:
    def replace(match: re.Match[str]) -> str:
        indent, target = match.group(1), match.group(2)
        if depth >= MAX_INCLUDE_DEPTH:
            log.warning("include depth %d exceeded at %s; skipped", MAX_INCLUDE_DEPTH, target)
            return ""
        content = resolve(target)
        if content is None:
            return ""
        expanded = expand_includes(content, resolve, depth + 1)
        return "\n".join(indent + line if line else "" for line in expanded.splitlines())

    return _INCLUDE.sub(replace, text)


def file_include_resolver(
    root: Path, source: Path, max_bytes: int | None = None, *, project_root: Path | None = None
) -> IncludeResolver:
    """Resolve relative to `source`, or to `project_root` (the Sphinx source dir, where
    `conf.py` lives) for `/absolute` targets. Nothing outside `root` is ever read."""
    root = root.resolve()
    absolute_base = (project_root or root).resolve()

    def resolve(target: str) -> str | None:
        base = absolute_base if target.startswith("/") else source.parent
        candidate = (base / target.lstrip("/")).resolve()
        if not candidate.is_relative_to(root):
            log.warning("include %s escapes %s; skipped", target, root)
            return None
        if not candidate.is_file():
            log.warning("include %s not found (from %s); skipped", target, source)
            return None
        if max_bytes is not None and candidate.stat().st_size > max_bytes:
            log.warning("include %s exceeds %d bytes; skipped", target, max_bytes)
            return None
        return candidate.read_text(encoding="utf-8", errors="replace")

    return resolve
