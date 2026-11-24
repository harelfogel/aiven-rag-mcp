import os
from pathlib import Path

import pytest

from rag_mcp.errors import Code, RagError
from rag_mcp.fetching import FetchLimits, HttpResponse
from rag_mcp.loaders import (
    LoaderError,
    LoadLimits,
    SourceKind,
    load,
    load_file,
    load_text,
    load_url,
)
from rag_mcp.parsing import Format

FETCH = FetchLimits(max_bytes=100, timeout_s=1, max_redirects=2)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.rst").write_text("Title\n=====\n\nbody\n")
    return tmp_path.resolve()


@pytest.fixture
def limits(root: Path) -> LoadLimits:
    return LoadLimits(max_bytes=100, data_root=root, fetch=FETCH)


def code_of(error: pytest.ExceptionInfo[LoaderError]) -> Code:
    return error.value.code


# text


def test_load_text_uri_is_content_hash_and_title_is_first_line(limits: LoadLimits) -> None:
    first = load_text("\n  Hello world\nmore", None, limits)
    assert first.uri.startswith("text:") and len(first.uri) == len("text:") + 12
    assert first.title == "Hello world"
    assert first.fmt is Format.TEXT
    assert load_text("\n  Hello world\nmore", "custom", limits).uri == first.uri


@pytest.mark.parametrize("text", ["", "   \n\t", "﻿"])
def test_load_text_rejects_blank_input(text: str, limits: LoadLimits) -> None:
    with pytest.raises(LoaderError) as error:
        load_text(text, None, limits)
    assert code_of(error) is Code.BAD_REQUEST


def test_load_text_size_cap_is_inclusive(limits: LoadLimits) -> None:
    assert load_text("a" * 100, None, limits).text == "a" * 100
    with pytest.raises(LoaderError) as error:
        load_text("a" * 101, None, limits)
    assert code_of(error) is Code.TOO_LARGE


def test_load_text_rejects_lone_surrogate(limits: LoadLimits) -> None:
    with pytest.raises(LoaderError, match="invalid characters"):
        load_text("bad \ud800 char", None, limits)


def test_load_text_rejects_binary(limits: LoadLimits) -> None:
    with pytest.raises(LoaderError, match="binary"):
        load_text("abc\x00def", None, limits)


# file


def test_load_file_relative_and_absolute_paths_inside_root(root: Path, limits: LoadLimits) -> None:
    relative = load_file("docs/page.rst", None, limits)
    absolute = load_file(str(root / "docs" / "page.rst"), None, limits)
    assert relative == absolute
    assert relative.uri == "file:docs/page.rst"
    assert relative.title == "page"
    assert relative.fmt is Format.RST


@pytest.mark.parametrize("path", ["../outside.rst", "docs/../../x.rst", "/etc/hosts"])
def test_load_file_rejects_path_traversal(path: str, limits: LoadLimits) -> None:
    with pytest.raises(LoaderError, match="must stay under") as error:
        load_file(path, None, limits)
    assert code_of(error) is Code.BAD_REQUEST


def test_load_file_rejects_symlink_escaping_root(
    root: Path, tmp_path: Path, limits: LoadLimits
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-secret.rst"
    outside.write_text("secret")
    (root / "docs" / "link.rst").symlink_to(outside)
    try:
        with pytest.raises(LoaderError, match="must stay under"):
            load_file("docs/link.rst", None, limits)
    finally:
        outside.unlink()


def test_load_file_missing_directory_and_extension(root: Path, limits: LoadLimits) -> None:
    with pytest.raises(LoaderError) as missing:
        load_file("docs/nope.rst", None, limits)
    assert code_of(missing) is Code.NOT_FOUND
    with pytest.raises(LoaderError, match="directory"):
        load_file("docs", None, limits)
    (root / "docs" / "image.png").write_bytes(b"\x89PNG")
    with pytest.raises(LoaderError, match="unsupported extension"):
        load_file("docs/image.png", None, limits)


def test_load_file_size_cap_and_bad_encoding(root: Path, limits: LoadLimits) -> None:
    (root / "docs" / "big.md").write_text("x" * 101)
    with pytest.raises(LoaderError) as error:
        load_file("docs/big.md", None, limits)
    assert code_of(error) is Code.TOO_LARGE
    (root / "docs" / "latin.md").write_bytes("caf\xe9".encode("latin-1"))
    with pytest.raises(LoaderError, match="not UTF-8"):
        load_file("docs/latin.md", None, limits)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_load_file_permission_denied(root: Path, limits: LoadLimits) -> None:
    locked = root / "docs" / "locked.rst"
    locked.write_text("Title\n=====\n")
    locked.chmod(0)
    try:
        with pytest.raises(LoaderError, match="cannot read"):
            load_file("docs/locked.rst", None, limits)
    finally:
        locked.chmod(0o644)


# url (the fetch is stubbed; the real fetcher has its own tests)


def respond(body: bytes, content_type: str = "text/plain") -> HttpResponse:
    return HttpResponse(200, content_type, None, body)


def test_load_url_plain_text_keeps_url_as_uri_and_format_from_path(limits: LoadLimits) -> None:
    url = "https://raw.example.com/docs/page.rst"
    loaded = load_url(url, None, limits, fetch=lambda _u, _l: respond(b"Title\n=====\n"))
    assert (loaded.uri, loaded.title, loaded.fmt) == (url, "page", Format.RST)
    with_fragment = load_url(f"{url}#step-3", None, limits, fetch=lambda _u, _l: respond(b"x"))
    assert with_fragment.uri == url


def test_load_url_html_is_stripped_and_titled(limits: LoadLimits) -> None:
    html = (
        b"<html><head><title> Aiven  docs </title><script>x()</script></head>"
        b"<body><h1>Hi</h1><p>a<br>b</p></body></html>"
    )
    loaded = load_url(
        "https://docs.example.com/",
        None,
        limits,
        fetch=lambda _u, _l: respond(html, "text/html; charset=utf-8"),
    )
    assert loaded.title == "Aiven docs"
    assert loaded.text == "Hi\n\na\nb"
    assert loaded.fmt is Format.TEXT


def test_load_url_rejects_non_text_and_unreadable_html(limits: LoadLimits) -> None:
    with pytest.raises(LoaderError, match="only text"):
        load_url(
            "https://x.example.com/a.pdf",
            None,
            limits,
            fetch=lambda _u, _l: respond(b"%PDF", "application/pdf"),
        )
    with pytest.raises(LoaderError, match="no readable text"):
        load_url(
            "https://x.example.com/",
            None,
            limits,
            fetch=lambda _u, _l: respond(b"<script>1</script>", "text/html"),
        )


def test_load_url_honours_declared_charset(limits: LoadLimits) -> None:
    body = "caf\xe9".encode("latin-1")
    loaded = load_url(
        "https://x.example.com/t.txt",
        None,
        limits,
        fetch=lambda _u, _l: respond(body, "text/plain; charset=iso-8859-1"),
    )
    assert loaded.text == "caf\xe9"


def test_load_dispatches_on_kind(limits: LoadLimits) -> None:
    assert load(SourceKind.TEXT, "hello", None, limits).text == "hello"
    assert load(SourceKind.FILE, "docs/page.rst", "T", limits).title == "T"
    with pytest.raises(RagError, match="only http"):  # the fetcher's own error, same base
        load(SourceKind.URL, "ftp://example.com/x", None, limits)
