"""Light Markdown parser: front matter, headings, fenced code, pipe tables, paragraphs."""

from __future__ import annotations

import re
from collections.abc import Callable

from rag_mcp.parsing.model import Block, BlockKind, Document, Section

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_ATX_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_SETEXT_UNDERLINE = re.compile(r"^\s{0,3}(=+|-+)\s*$")
_TABLE_LINE = re.compile(r"^\s*\|")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FRONT_MATTER_TITLE = re.compile(r"^title:\s*[\"']?(.*?)[\"']?\s*$", re.MULTILINE)


def parse_markdown(text: str) -> Document:
    front_matter, lines = _split_front_matter(_HTML_COMMENT.sub("", text).splitlines())
    title_match = _FRONT_MATTER_TITLE.search(front_matter)
    title = title_match.group(1) if title_match else ""
    path: list[str] = [title] if title else []
    sections: list[Section] = []
    body: list[str] = []
    index = 0
    while index < len(lines):
        if fence := _FENCE.match(lines[index]):
            _, end = _take_fenced(lines, index + 1, fence.group(1))
            body.extend(lines[index:end])
            index = end
            continue
        heading = _match_heading(lines, index)
        if heading is None:
            body.append(lines[index])
            index += 1
            continue
        text_, level, consumed = heading
        sections.extend(_section(path, body))
        body = []
        if not title and level == 1:
            title = text_
        path[level - 1 :] = [text_]
        index += consumed
    sections.extend(_section(path, body))
    return Document(title=title, sections=tuple(sections))


def _split_front_matter(lines: list[str]) -> tuple[str, list[str]]:
    start = next((i for i, line in enumerate(lines) if line.strip()), len(lines))
    if start == len(lines) or lines[start].strip() != "---":
        return "", lines
    for index in range(start + 1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[start + 1 : index]), lines[index + 1 :]
    return "", lines


def _match_heading(lines: list[str], index: int) -> tuple[str, int, int] | None:
    line = lines[index]
    if match := _ATX_HEADING.match(line):
        return clean_inline(match.group(2)), len(match.group(1)), 1
    if (
        line.strip()
        and index + 1 < len(lines)
        and (under := _SETEXT_UNDERLINE.match(lines[index + 1]))
    ):
        return clean_inline(line.strip()), 1 if under.group(1)[0] == "=" else 2, 2
    return None


def _section(path: list[str], body: list[str]) -> list[Section]:
    blocks = parse_blocks(body)
    return [Section(tuple(path), tuple(blocks))] if blocks else []


def parse_blocks(lines: list[str]) -> list[Block]:
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
        elif fence := _FENCE.match(line):
            code, index = _take_fenced(lines, index + 1, fence.group(1))
            if code:
                blocks.append(Block(BlockKind.CODE, "\n".join(code)))
        elif _TABLE_LINE.match(line):
            table, index = _take_while(lines, index, lambda text: bool(_TABLE_LINE.match(text)))
            blocks.append(Block(BlockKind.TABLE, "\n".join(row.strip() for row in table)))
        else:
            paragraph, index = _take_while(lines, index, _is_paragraph_line)
            text = clean_inline("\n".join(part.strip() for part in paragraph))
            if text:
                blocks.append(Block(BlockKind.PARAGRAPH, text))
    return blocks


def _is_paragraph_line(line: str) -> bool:
    return bool(line.strip()) and not _FENCE.match(line) and not _TABLE_LINE.match(line)


def _take_while(lines: list[str], start: int, keep: Callable[[str], bool]) -> tuple[list[str], int]:
    end = start
    while end < len(lines) and keep(lines[end]):
        end += 1
    return lines[start:end], end


def _take_fenced(lines: list[str], start: int, fence: str) -> tuple[list[str], int]:
    end = start
    while end < len(lines):
        closing = _FENCE.match(lines[end])
        if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence):
            return lines[start:end], end + 1
        end += 1
    return lines[start:end], end  # unterminated fence: keep the rest as code


def clean_inline(text: str) -> str:
    return _LINK.sub(r"\1", _IMAGE.sub("", text))
