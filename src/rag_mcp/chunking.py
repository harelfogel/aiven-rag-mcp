"""Pack parsed sections into chunks that fit the embedding window.

Rules: one chunk per section when it fits; longer sections split between blocks with a short
paragraph of overlap; code and tables are never cut unless a single one exceeds the window, in
which case it is split by lines (tables keep their header); tiny neighbouring sections merge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import takewhile

from rag_mcp.parsing.model import Block, BlockKind, Document, Section

TokenCounter = Callable[[str], int]
HEADING_SEPARATOR = " > "
# A repeated lead-in paragraph may use at most this share of a chunk's budget.
OVERLAP_SHARE = 4


@dataclass(frozen=True)
class ChunkConfig:
    target_tokens: int  # stop adding blocks once a chunk reaches this
    max_tokens: int  # the model window; a single block wider than this is split by lines
    min_tokens: int  # chunks below this merge into a neighbour


@dataclass(frozen=True)
class Chunk:
    heading_path: tuple[str, ...]
    text: str
    token_count: int  # of embed_text(heading_path, text)


def embed_text(heading_path: tuple[str, ...], text: str) -> str:
    """The string that gets embedded and indexed: heading path for context, then the body."""
    heading = HEADING_SEPARATOR.join(heading_path)
    return f"{heading}\n\n{text}" if heading else text


def chunk_document(
    document: Document, count_tokens: TokenCounter, config: ChunkConfig
) -> list[Chunk]:
    pieces = [
        piece
        for section in document.sections
        for piece in split_section(section, count_tokens, config)
    ]
    return merge_small(pieces, count_tokens, config)


def split_section(section: Section, count_tokens: TokenCounter, config: ChunkConfig) -> list[Chunk]:
    heading_tokens = count_tokens(HEADING_SEPARATOR.join(section.heading_path))
    budget = config.target_tokens - heading_tokens
    blocks = [
        piece
        for block in section.blocks
        if block.text.strip()
        for piece in split_oversized(block, count_tokens, config.max_tokens - heading_tokens)
    ]
    if not blocks:
        return []
    sizes = [count_tokens(block.text) for block in blocks]
    groups: list[list[Block]] = []
    current: list[Block] = []
    used = last_size = 0
    for block, size in zip(blocks, sizes, strict=True):
        if current and used + size > budget:
            groups.append(current)
            current = [current[-1]] if _overlaps(current[-1], last_size, size, budget) else []
            used = last_size if current else 0
        current.append(block)
        used += size
        last_size = size
    groups.append(current)
    return [_make_chunk(section.heading_path, group, count_tokens) for group in groups]


def split_oversized(block: Block, count_tokens: TokenCounter, limit: int) -> list[Block]:
    """A block wider than the window is split by lines; table pieces repeat the header rows."""
    if count_tokens(block.text) <= limit:
        return [block]
    lines = block.text.splitlines()
    header = lines[: _table_header_rows(lines)] if block.kind is BlockKind.TABLE else []
    header_tokens = count_tokens("\n".join(header))
    pieces: list[Block] = []
    current: list[str] = []
    used = header_tokens
    for line in lines[len(header) :]:
        size = count_tokens(line)
        if current and used + size > limit:
            pieces.append(Block(block.kind, "\n".join(header + current)))
            current, used = [], header_tokens
        current.append(line)
        used += size
    pieces.append(Block(block.kind, "\n".join(header + current)))
    return pieces


def _table_header_rows(lines: list[str]) -> int:
    """Header lines of a pipe, grid or simple table, or 0 when it has none."""
    first = lines[0].lstrip()
    if first.startswith("|"):
        has_rule = len(lines) > 1 and lines[1].lstrip().startswith("|") and "---" in lines[1]
        return 2 if has_rule else 0
    if first.startswith("+"):
        return next((i + 1 for i, line in enumerate(lines) if line.lstrip().startswith("+=")), 0)
    borders = [i for i, line in enumerate(lines) if line.strip().startswith("=")]
    return borders[1] + 1 if len(borders) >= 3 else 0


def _overlaps(last: Block, last_size: int, next_size: int, budget: int) -> bool:
    """Repeat the previous short paragraph so the next piece keeps its lead-in."""
    fits = last_size <= budget // OVERLAP_SHARE and last_size + next_size <= budget
    return last.kind is BlockKind.PARAGRAPH and fits


def _make_chunk(path: tuple[str, ...], blocks: list[Block], count_tokens: TokenCounter) -> Chunk:
    text = "\n\n".join(block.text for block in blocks)
    return Chunk(path, text, count_tokens(embed_text(path, text)))


def merge_small(
    chunks: list[Chunk], count_tokens: TokenCounter, config: ChunkConfig
) -> list[Chunk]:
    merged: list[Chunk] = []
    for chunk in chunks:
        if merged and _should_merge(merged[-1], chunk, count_tokens, config):
            merged[-1] = _join(merged[-1], chunk, count_tokens)
        else:
            merged.append(chunk)
    return merged


def _should_merge(
    previous: Chunk, chunk: Chunk, count_tokens: TokenCounter, config: ChunkConfig
) -> bool:
    """Tiny means a small body; the heading path does not count against a section."""
    body_sizes = (count_tokens(previous.text), count_tokens(chunk.text))
    return (
        min(body_sizes) < config.min_tokens
        and previous.token_count + body_sizes[1] <= config.target_tokens
    )


def _join(previous: Chunk, chunk: Chunk, count_tokens: TokenCounter) -> Chunk:
    """Merge under the shared heading prefix; each part keeps its own heading as a text line."""
    shared = tuple(
        a
        for a, _ in takewhile(
            lambda pair: pair[0] == pair[1],
            zip(previous.heading_path, chunk.heading_path, strict=False),
        )
    )
    text = f"{_with_heading(previous, shared)}\n\n{_with_heading(chunk, shared)}"
    return Chunk(shared, text, count_tokens(embed_text(shared, text)))


def _with_heading(chunk: Chunk, shared: tuple[str, ...]) -> str:
    own = chunk.heading_path[len(shared) :]
    return f"{HEADING_SEPARATOR.join(own)}\n{chunk.text}" if own else chunk.text
