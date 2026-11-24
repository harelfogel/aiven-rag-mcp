import logging
from pathlib import Path

from rag_mcp.parsing.includes import expand_includes, file_include_resolver


def test_absolute_and_relative_includes_resolve_inside_root(tmp_path: Path) -> None:
    (tmp_path / "includes").mkdir()
    (tmp_path / "includes" / "params.rst").write_text("``p``\n-----\n*int*\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "local.rst").write_text("local text\n")
    page = tmp_path / "docs" / "page.rst"
    text = "Title\n=====\n\n.. include:: /includes/params.rst\n\n.. include:: local.rst\n"
    out = expand_includes(text, file_include_resolver(tmp_path, page))
    assert "``p``\n-----\n*int*" in out
    assert "local text" in out


def test_missing_and_escaping_includes_are_skipped_with_warning(
    tmp_path: Path, caplog: "logging.LogCaptureFixture"
) -> None:
    page = tmp_path / "page.rst"
    outside = tmp_path.parent / "secret.rst"
    text = f".. include:: nope.rst\n.. include:: {outside}\n.. include:: ../secret.rst\nok\n"
    with caplog.at_level(logging.WARNING):
        out = expand_includes(text, file_include_resolver(tmp_path, page))
    assert out.strip() == "ok"
    assert sum("skipped" in record.message for record in caplog.records) == 3


def test_include_recursion_is_bounded(caplog: "logging.LogCaptureFixture") -> None:
    with caplog.at_level(logging.WARNING):
        out = expand_includes(".. include:: self", lambda _target: ".. include:: self\nx")
    assert "depth" in caplog.text
    assert out.count("x") == 3


def test_indented_include_keeps_indentation() -> None:
    out = expand_includes(".. note::\n\n   .. include:: a", lambda _t: "line1\n\nline2")
    assert out == ".. note::\n\n   line1\n\n   line2"
