from textwrap import dedent

from rag_mcp.parsing.markdown import parse_markdown
from rag_mcp.parsing.model import Block, BlockKind


def test_front_matter_title_headings_code_table_links() -> None:
    doc = parse_markdown(
        dedent(
            """
            ---
            title: "Getting started"
            ---
            <!-- hidden -->
            Intro with a [link](http://x) and ![img](p.png).

            ## Install

            ```bash
            npm i
            # not a heading
            ```

            | a | b |
            |---|---|
            | 1 | 2 |

            Setext
            ------
            tail
            """
        )
    )
    assert doc.title == "Getting started"
    assert [s.heading_path for s in doc.sections] == [
        ("Getting started",),
        ("Getting started", "Install"),
        ("Getting started", "Setext"),
    ]
    intro, install = doc.sections[0].blocks, doc.sections[1].blocks
    assert intro[0].text == "Intro with a link and ."
    assert install[0] == Block(BlockKind.CODE, "npm i\n# not a heading")
    assert install[1].kind is BlockKind.TABLE
    assert install[1].text.splitlines()[0] == "| a | b |"


def test_title_falls_back_to_first_h1_and_unterminated_fence_is_code() -> None:
    doc = parse_markdown("# Only title\n\ntext\n\n```\nopen fence")
    assert doc.title == "Only title"
    assert doc.sections[0].blocks[1] == Block(BlockKind.CODE, "open fence")


def test_empty_markdown() -> None:
    assert parse_markdown("\n\n").sections == ()
