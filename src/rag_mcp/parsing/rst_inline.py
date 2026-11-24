"""Inline RST clean-up and list-table rendering, used by the RST parser."""

from __future__ import annotations

import re

# Order matters: roles and links with an explicit <target> go first.
_ROLE_WITH_TARGET = re.compile(r":[\w:+.-]+:`([^`<]*?)\s*<[^>]*>`")
_ROLE = re.compile(r":[\w:+.-]+:`([^`]*)`")
_LINK_WITH_TARGET = re.compile(r"`([^`<]*?)\s*<[^>]*>`_{1,2}")
_NAMED_REFERENCE = re.compile(r"`([^`]*)`_{1,2}")
_LITERAL = re.compile(r"``([^`]+)``")
_ESCAPED_SPACE = re.compile(r"\\ ")
_OPTION_LINE = re.compile(r"^\s*:([\w-]+):\s*(.*)$")


def clean_inline(text: str) -> str:
    """Strip markup that only matters to Sphinx: `:doc:`Title <path>`` becomes `Title`."""
    text = _ROLE_WITH_TARGET.sub(r"\1", text)
    text = _ROLE.sub(r"\1", text)
    text = _LINK_WITH_TARGET.sub(r"\1", text)
    text = _NAMED_REFERENCE.sub(r"\1", text)
    text = _LITERAL.sub(r"`\1`", text)
    return _ESCAPED_SPACE.sub("", text)


def split_options(body: list[str]) -> tuple[dict[str, str], list[str]]:
    """Separate leading `:name: value` option lines of a directive body from its content."""
    options: dict[str, str] = {}
    index = 0
    while index < len(body):
        match = _OPTION_LINE.match(body[index])
        if not match:
            break
        options[match.group(1)] = match.group(2).strip()
        index += 1
    while index < len(body) and not body[index].strip():
        index += 1
    return options, body[index:]


def render_list_table(body: list[str], header_rows: int) -> str:
    """Turn a `.. list-table::` body (`* - cell` / `  - cell`) into a pipe table."""
    rows = _list_table_rows(body)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    lines = ["| " + " | ".join(row + [""] * (width - len(row))) + " |" for row in rows]
    if 0 < header_rows < len(lines):
        lines.insert(header_rows, "|" + " --- |" * width)
    return "\n".join(lines)


def _list_table_rows(body: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in body:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("*"):
            rows.append([])
            line = line[1:].strip()
            if not line:
                continue
        if not rows:
            continue
        if line.startswith("- ") or line == "-":
            rows[-1].append(clean_inline(line[1:].strip()))
        elif rows[-1]:
            rows[-1][-1] = f"{rows[-1][-1]} {clean_inline(line)}".strip()
    return rows
