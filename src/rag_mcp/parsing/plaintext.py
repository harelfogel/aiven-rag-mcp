"""Plain text: paragraphs separated by blank lines, no structure."""

from __future__ import annotations

import re

from rag_mcp.parsing.model import Block, BlockKind, Document, Section

_BLANK_LINES = re.compile(r"\n\s*\n")


def parse_plain_text(text: str, title: str = "") -> Document:
    paragraphs = [part.strip() for part in _BLANK_LINES.split(text) if part.strip()]
    if not paragraphs:
        return Document(title=title, sections=())
    blocks = tuple(Block(BlockKind.PARAGRAPH, paragraph) for paragraph in paragraphs)
    heading_path = (title,) if title else ()
    return Document(title=title, sections=(Section(heading_path, blocks),))
