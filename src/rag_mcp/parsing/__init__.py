"""Format detection and dispatch: text in, Document out."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePath

from rag_mcp.parsing.markdown import parse_markdown
from rag_mcp.parsing.model import Document
from rag_mcp.parsing.plaintext import parse_plain_text
from rag_mcp.parsing.rst import parse_rst


class Format(StrEnum):
    RST = "rst"
    MARKDOWN = "markdown"
    TEXT = "text"


_EXTENSIONS = {".rst": Format.RST, ".md": Format.MARKDOWN, ".markdown": Format.MARKDOWN}


def format_for_path(path: str | PurePath) -> Format:
    return _EXTENSIONS.get(PurePath(path).suffix.lower(), Format.TEXT)


def parse(text: str, fmt: Format, *, fallback_title: str = "") -> Document:
    """Parse text in the given format. The title falls back to the given one (e.g. a filename)."""
    match fmt:
        case Format.RST:
            document = parse_rst(text)
        case Format.MARKDOWN:
            document = parse_markdown(text)
        case Format.TEXT:
            document = parse_plain_text(text, fallback_title)
    if document.title or not fallback_title:
        return document
    return Document(title=fallback_title, sections=document.sections)
