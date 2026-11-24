from rag_mcp.chunking import (
    Chunk,
    ChunkConfig,
    chunk_document,
    embed_text,
    split_oversized,
    split_section,
)
from rag_mcp.parsing.model import Block, BlockKind, Document, Section
from tests.conftest import word_count


def words(n: int, tag: str = "w") -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


def paragraph(n: int, tag: str = "w") -> Block:
    return Block(BlockKind.PARAGRAPH, words(n, tag))


def test_section_that_fits_is_one_chunk(config: ChunkConfig) -> None:
    section = Section(("Page", "Sec"), (paragraph(10), paragraph(10)))
    (chunk,) = split_section(section, word_count, config)
    assert chunk.heading_path == ("Page", "Sec")
    assert chunk.token_count == word_count(embed_text(chunk.heading_path, chunk.text))
    assert chunk.token_count <= config.target_tokens


def test_long_section_splits_between_blocks_with_overlap(config: ChunkConfig) -> None:
    section = Section(("P",), (paragraph(20, "a"), paragraph(5, "b"), paragraph(20, "c")))
    chunks = split_section(section, word_count, config)
    assert [c.text.split("\n\n")[0][:2] for c in chunks] == ["a0", "b0"]
    assert chunks[1].text.startswith(words(5, "b"))  # short lead-in paragraph repeated
    assert all(c.token_count <= config.max_tokens for c in chunks)


def test_long_lead_in_paragraph_is_not_repeated(config: ChunkConfig) -> None:
    section = Section(("P",), (paragraph(20, "a"), paragraph(20, "b"), paragraph(20, "c")))
    chunks = split_section(section, word_count, config)
    assert [c.text[:2] for c in chunks] == ["a0", "b0", "c0"]


def test_code_that_fits_the_window_is_never_split(config: ChunkConfig) -> None:
    code = Block(BlockKind.CODE, "\n".join(f"line{i}" for i in range(45)))
    section = Section(("P",), (paragraph(10), code, paragraph(10)))
    chunks = split_section(section, word_count, config)
    assert [c.text for c in chunks][1] == code.text  # moved whole into its own chunk
    assert len(chunks) == 3


def test_code_wider_than_the_window_splits_by_lines(config: ChunkConfig) -> None:
    code = Block(BlockKind.CODE, "\n".join(f"line{i}" for i in range(120)))
    pieces = split_oversized(code, word_count, config.max_tokens)
    assert [p.kind for p in pieces] == [BlockKind.CODE] * 3
    assert "\n".join(p.text for p in pieces) == code.text


def test_giant_table_pieces_repeat_the_header() -> None:
    pipe = ["| a | b |", "|---|---|"] + [f"| {i} | y |" for i in range(6)]
    pieces = split_oversized(Block(BlockKind.TABLE, "\n".join(pipe)), word_count, 12)
    assert len(pieces) > 1
    assert all(p.text.startswith("| a | b |\n|---|---|\n| ") for p in pieces)
    headerless = [f"| {i} | y |" for i in range(6)]
    pieces = split_oversized(Block(BlockKind.TABLE, "\n".join(headerless)), word_count, 6)
    assert "\n".join(p.text for p in pieces) == "\n".join(headerless)


def test_tiny_sections_merge_under_shared_prefix(config: ChunkConfig) -> None:
    doc = Document(
        "P",
        (
            Section(("P", "params", "a"), (paragraph(3, "a"),)),
            Section(("P", "params", "b"), (paragraph(3, "b"),)),
            Section(("P", "other"), (paragraph(30, "o"),)),
        ),
    )
    chunks = chunk_document(doc, word_count, config)
    assert [c.heading_path for c in chunks] == [("P", "params"), ("P", "other")]
    assert chunks[0].text == f"a\n{words(3, 'a')}\n\nb\n{words(3, 'b')}"


def test_merge_respects_target(config: ChunkConfig) -> None:
    doc = Document(
        "P", (Section(("P", "x"), (paragraph(3),)), Section(("P", "y"), (paragraph(38),)))
    )
    chunks = chunk_document(doc, word_count, config)
    assert len(chunks) == 2


def test_empty_document_and_blank_blocks_give_no_chunks(config: ChunkConfig) -> None:
    assert chunk_document(Document("", ()), word_count, config) == []
    doc = Document("P", (Section(("P",), (Block(BlockKind.PARAGRAPH, "   "),)),))
    assert chunk_document(doc, word_count, config) == []


def test_embed_text_without_heading() -> None:
    assert embed_text((), "body") == "body"
    assert Chunk((), "body", 1).text == "body"
