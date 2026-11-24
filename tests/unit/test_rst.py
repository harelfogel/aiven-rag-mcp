from textwrap import dedent

from rag_mcp.parsing.model import Block, BlockKind
from rag_mcp.parsing.rst import parse_rst


def parse(text: str):  # noqa: ANN201
    return parse_rst(dedent(text).strip("\n"))


def test_heading_levels_follow_first_appearance() -> None:
    doc = parse(
        """
        Page title
        ==========

        Intro paragraph.

        Section
        -------

        ``kafka_connect``
        ~~~~~~~~~~~~~~~~~

        *boolean*
        """
    )
    assert doc.title == "Page title"
    assert [s.heading_path for s in doc.sections] == [
        ("Page title",),
        ("Page title", "Section", "kafka_connect"),
    ]


def test_overline_heading_and_level_reset() -> None:
    doc = parse(
        """
        ######
        Title
        ######

        Alpha
        =====

        Beta
        ----

        text b

        Gamma
        =====

        text c
        """
    )
    paths = [s.heading_path for s in doc.sections]
    assert paths == [("Title", "Alpha", "Beta"), ("Title", "Gamma")]


def test_code_directive_keeps_body_and_drops_options() -> None:
    doc = parse(
        """
        Top
        ===

        5. Run this, replacing ``<URI>``:

           .. code:: bash
              :caption: list topics

              ./kafka-topics.sh \\
                  --list

           If successful, topics are listed.
        """
    )
    kinds = [(b.kind, b.text) for b in doc.sections[0].blocks]
    assert kinds == [
        (BlockKind.PARAGRAPH, "5. Run this, replacing `<URI>`:"),
        (BlockKind.CODE, "./kafka-topics.sh \\\n    --list"),
        (BlockKind.PARAGRAPH, "If successful, topics are listed."),
    ]


def test_literal_block_after_double_colon() -> None:
    doc = parse(
        """
        Top
        ===

        Run the following command::

            CREATE EXTENSION pg_stat_statements;

        Done.
        """
    )
    blocks = doc.sections[0].blocks
    assert blocks[0].text == "Run the following command:"
    assert blocks[1] == Block(BlockKind.CODE, "CREATE EXTENSION pg_stat_statements;")
    assert blocks[2].text == "Done."


def test_admonition_is_labelled_and_nested_code_survives() -> None:
    doc = parse(
        """
        Top
        ===

        .. Note::

            Topic configs cannot change here.

            .. code::

                kafka-configs.sh --alter
        """
    )
    blocks = doc.sections[0].blocks
    assert blocks[0].text == "Note: Topic configs cannot change here."
    assert blocks[1] == Block(BlockKind.CODE, "kafka-configs.sh --alter")


def test_list_table_becomes_pipe_table() -> None:
    doc = parse(
        """
        Top
        ===

        .. list-table::
          :header-rows: 1

          * - Parameter
            - Information
          * - ``--project``
            - The project for which
              to create a ticket
        """
    )
    (table,) = doc.sections[0].blocks
    assert table.kind is BlockKind.TABLE
    assert table.text.splitlines() == [
        "| Parameter | Information |",
        "| --- | --- |",
        "| `--project` | The project for which to create a ticket |",
    ]


def test_simple_and_grid_tables_are_single_blocks() -> None:
    doc = parse(
        """
        Top
        ===

        ======  =====
        Var     Desc
        ======  =====
        HOST    host
        PORT    port
        ======  =====

        +---+---+
        | a | b |
        +---+---+
        """
    )
    simple, grid = doc.sections[0].blocks
    assert (simple.kind, grid.kind) == (BlockKind.TABLE, BlockKind.TABLE)
    assert simple.text == "Var     Desc\nHOST    host\nPORT    port"  # borders dropped
    assert grid.text == "| a | b |"


def test_inline_markup_is_cleaned() -> None:
    doc = parse(
        """
        Top
        ===

        See :doc:`the CLI <../tools/cli>` and :ref:`creation <avn_topic>` or `Kafka <https://k.io>`_.
        Use ``kafka_connect`` with `docs`_ and a\\ word.
        """
    )
    assert doc.sections[0].blocks[0].text == (
        "See the CLI and creation or Kafka.\nUse `kafka_connect` with docs and aword."
    )


def test_navigation_directives_and_comments_are_dropped() -> None:
    doc = parse(
        """
        Top
        ===

        .. _label-target:

        .. this is a comment
           spanning lines

        .. toctree::
           :maxdepth: 1

           page-a
           page-b

        .. image:: pic.png

        Real text.
        """
    )
    assert [b.text for b in doc.sections[0].blocks] == ["Real text."]


def test_malformed_input_degrades_to_paragraphs() -> None:
    doc = parse("just text\n\n.. code-block:: bash\nno indent so no body\n\n=====\n")
    texts = [b.text for s in doc.sections for b in s.blocks]
    assert texts == ["just text", "no indent so no body", "====="]


def test_empty_and_whitespace_input() -> None:
    assert parse_rst("").sections == ()
    assert parse_rst("  \n\n\t\n").sections == ()


def test_malformed_option_and_substitution_line_do_not_break_parsing() -> None:
    doc = parse(
        """
        Top
        ===

        |aiven| is a line that starts with a substitution.

        .. list-table::
           :header-rows: abc

           * - a
             - b
        """
    )
    kinds = [b.kind for b in doc.sections[0].blocks]
    assert kinds == [BlockKind.PARAGRAPH, BlockKind.TABLE]
    assert doc.sections[0].blocks[1].text == "| a | b |"


def test_grid_table_header_rule_becomes_a_pipe_rule() -> None:
    doc = parse(
        """
        Top
        ===

        +--------+-----------+
        | Backup | Retention |
        +========+===========+
        | daily  | 2 days    |
        +--------+-----------+
        | hourly | 1 day     |
        +--------+-----------+
        """
    )
    (table,) = doc.sections[0].blocks
    assert table.text.splitlines() == [
        "| Backup | Retention |",
        "|--------|-----------|",
        "| daily  | 2 days    |",
        "| hourly | 1 day     |",
    ]
