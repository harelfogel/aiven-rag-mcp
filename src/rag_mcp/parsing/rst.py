"""Light reStructuredText parser: headings, directives, code, tables, paragraphs.

Not a Sphinx build. Anything it does not understand degrades to a paragraph.
"""

from __future__ import annotations

import logging
import re

from rag_mcp.parsing.model import Block, BlockKind, Document, Section
from rag_mcp.parsing.rst_inline import clean_inline, render_list_table, split_options

log = logging.getLogger(__name__)

_ADORNMENT = re.compile(r"^([=\-~^*#`:'\"+_.])\1{2,}\s*$")
_DIRECTIVE = re.compile(r"^(\s*)\.\. ([a-zA-Z][\w-]*)::\s*(.*)$")
_COMMENT_OR_TARGET = re.compile(r"^\s*\.\.(\s|$)")
_SIMPLE_TABLE_BORDER = re.compile(r"^=+(\s+=+)+\s*$")
_GRID_TABLE_START = re.compile(r"^\s*\+-")
_GRID_BORDER = re.compile(r"^\s*\+[-+]*\+?\s*$")
_GRID_HEADER_RULE = re.compile(r"^\s*\+[=+]*\+?\s*$")

_CODE_DIRECTIVES = frozenset({"code", "code-block", "sourcecode"})
_ADMONITIONS = frozenset(
    {"note", "tip", "warning", "important", "seealso", "caution", "attention", "hint", "danger"}
)
# Navigation, media and build-only directives carry nothing worth retrieving.
_DROPPED_DIRECTIVES = frozenset(
    {"toctree", "tableofcontents", "image", "figure", "mermaid", "raw", "literalinclude",
     "only", "contents", "meta", "youtube", "video", "cssclass", "rst-class", "include"}
)  # fmt: skip


def parse_rst(text: str) -> Document:
    lines = text.splitlines()
    title = ""
    styles: list[tuple[str, bool]] = []
    path: list[str] = []
    sections: list[Section] = []
    body: list[str] = []
    index = 0
    while index < len(lines):
        heading = _match_heading(lines, index)
        if heading is None:
            body.append(lines[index])
            index += 1
            continue
        text_, style, consumed = heading
        sections.extend(_section(path, body))
        body = []
        if style not in styles:
            styles.append(style)
        level = styles.index(style)
        path[level:] = [text_]
        title = title or text_
        index += consumed
    sections.extend(_section(path, body))
    return Document(title=title, sections=tuple(sections))


def _match_heading(lines: list[str], index: int) -> tuple[str, tuple[str, bool], int] | None:
    """Return (heading text, adornment style, lines consumed) if a heading starts here."""
    line = lines[index]
    if _ADORNMENT.match(line) and index + 2 < len(lines):  # overline + text + underline
        text, under = lines[index + 1], lines[index + 2]
        if (
            text.strip()
            and _same_adornment(line, under)
            and len(under.rstrip()) >= len(text.rstrip())
        ):
            return _heading_text(text), (under[0], True), 3
    if not line.strip() or line[0].isspace() or index + 1 >= len(lines):
        return None
    under = lines[index + 1]
    if _ADORNMENT.match(under) and len(under.rstrip()) >= len(line.rstrip()):
        return _heading_text(line), (under[0], False), 2
    return None


def _same_adornment(first: str, second: str) -> bool:
    return bool(_ADORNMENT.match(second)) and first[0] == second[0]


def _heading_text(line: str) -> str:
    return clean_inline(line.strip()).strip("`").strip()


def _section(path: list[str], body: list[str]) -> list[Section]:
    blocks = parse_blocks(body)
    return [Section(tuple(path), tuple(blocks))] if blocks else []


def parse_blocks(lines: list[str]) -> list[Block]:
    """Parse body lines (no headings) into paragraph, code and table blocks."""
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
        elif directive := _DIRECTIVE.match(line):
            body, index = _take_indented(lines, index + 1, _indent_of(line))
            blocks.extend(_directive_blocks(directive.group(2).lower(), directive.group(3), body))
        elif _COMMENT_OR_TARGET.match(line):
            _, index = _take_indented(lines, index + 1, _indent_of(line))
        elif _SIMPLE_TABLE_BORDER.match(line.strip()) or _GRID_TABLE_START.match(line):
            table, index = _take_until_blank(lines, index)
            blocks.append(Block(BlockKind.TABLE, "\n".join(_strip_table_borders(table))))
        else:
            paragraph, index = _take_until_blank(lines, index)
            blocks.extend(_paragraph_blocks(paragraph))
            if paragraph[-1].rstrip().endswith("::"):
                code, index = _take_indented(lines, index, _indent_of(paragraph[0]))
                if code:
                    blocks.append(Block(BlockKind.CODE, "\n".join(code)))
    return blocks


def _strip_table_borders(lines: list[str]) -> list[str]:
    """Drop grid and simple-table border lines: a row of 80 dashes is 75 tokens of nothing.
    The grid header rule (`+===+`) becomes a pipe-table rule so the header stays detectable."""
    kept: list[str] = []
    for line in lines:
        if _GRID_BORDER.match(line) or _SIMPLE_TABLE_BORDER.match(line.strip()):
            continue
        if _GRID_HEADER_RULE.match(line):
            kept.append(line.strip().replace("+", "|").replace("=", "-"))
        else:
            kept.append(line.strip())
    return kept


def _paragraph_blocks(lines: list[str]) -> list[Block]:
    text = clean_inline("\n".join(line.strip() for line in lines))
    if text.endswith("::"):
        text = text[:-2].rstrip() + (":" if text[:-2].rstrip()[-1:].isalnum() else "")
    return [Block(BlockKind.PARAGRAPH, text)] if text.strip() else []


def _directive_blocks(name: str, argument: str, body: list[str]) -> list[Block]:
    options, content = split_options(body)
    if name in _DROPPED_DIRECTIVES:
        return []
    if name in _CODE_DIRECTIVES:
        return [Block(BlockKind.CODE, "\n".join(content))] if content else []
    if name == "list-table":
        table = render_list_table(content, _int_option(options, "header-rows"))
        return [Block(BlockKind.TABLE, table)] if table else []
    # Admonitions, topics, dropdowns, grids: keep the content, label admonitions.
    blocks = parse_blocks(content)
    label = f"{name.capitalize()}:" if name in _ADMONITIONS else ""
    lead = " ".join(part for part in (label, clean_inline(argument.strip())) if part)
    if lead and blocks and blocks[0].kind is BlockKind.PARAGRAPH:
        return [Block(BlockKind.PARAGRAPH, f"{lead} {blocks[0].text}"), *blocks[1:]]
    if lead:
        return [Block(BlockKind.PARAGRAPH, lead), *blocks]
    return blocks


def _int_option(options: dict[str, str], name: str) -> int:
    """Malformed option values are treated as absent; a bad page must never raise."""
    value = options.get(name, "")
    return int(value) if value.isdigit() else 0


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def _take_until_blank(lines: list[str], start: int) -> tuple[list[str], int]:
    end = start
    while end < len(lines) and lines[end].strip():
        end += 1
    return lines[start:end], end


def _take_indented(lines: list[str], start: int, indent: int) -> tuple[list[str], int]:
    """Collect the block indented deeper than `indent`, dedented, and the index after it."""
    end = start
    while end < len(lines) and (not lines[end].strip() or _indent_of(lines[end]) > indent):
        end += 1
    block = lines[start:end]
    while block and not block[0].strip():
        block.pop(0)
    while block and not block[-1].strip():
        block.pop()
    depth = min((_indent_of(line) for line in block if line.strip()), default=0)
    return [line[depth:] if line.strip() else "" for line in block], end
