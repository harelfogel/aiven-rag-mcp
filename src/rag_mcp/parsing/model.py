"""What a parsed document looks like, independent of its source format."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    CODE = "code"
    TABLE = "table"


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str


@dataclass(frozen=True)
class Section:
    """The blocks that sit directly under one heading. heading_path includes the page title."""

    heading_path: tuple[str, ...]
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Document:
    title: str
    sections: tuple[Section, ...]
