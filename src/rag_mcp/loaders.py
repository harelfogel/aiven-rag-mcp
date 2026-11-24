"""Turn an ingest input (pasted text, a file under the data root, or a URL) into text plus a URI.

Every refusal is a LoaderError with a code; nothing here reads outside the data root or talks to a
non-public host.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from rag_mcp.errors import Code, RagError
from rag_mcp.fetching import FetchLimits, HttpResponse, fetch_url
from rag_mcp.html_text import html_to_text
from rag_mcp.parsing import Format, format_for_path
from rag_mcp.settings import Settings

_TITLE_CHARS = 80
_TEXT_URI_HASH_CHARS = 12


class LoaderError(RagError):
    """The input was refused before any parsing happened."""


class SourceKind(StrEnum):
    TEXT = "text"
    FILE = "file"
    URL = "url"


@dataclass(frozen=True)
class LoadLimits:
    max_bytes: int
    data_root: Path
    fetch: FetchLimits

    @classmethod
    def from_settings(cls, settings: Settings) -> LoadLimits:
        fetch = FetchLimits(
            settings.ingest_max_bytes, settings.url_timeout_s, settings.url_max_redirects
        )
        return cls(settings.ingest_max_bytes, Path(settings.data_root).resolve(), fetch)


@dataclass(frozen=True)
class LoadedSource:
    uri: str  # stable identity for idempotent re-ingest: text:<hash>, file:<relative>, or the URL
    title: str
    text: str
    fmt: Format
    local_path: Path | None = None  # set for files; include targets resolve relative to it


Fetcher = Callable[[str, FetchLimits], HttpResponse]


def load(kind: SourceKind, source: str, title: str | None, limits: LoadLimits) -> LoadedSource:
    if title is not None and "\x00" in title:  # Postgres text cannot hold NUL
        raise LoaderError(Code.BAD_REQUEST, "title contains a NUL character")
    match kind:
        case SourceKind.TEXT:
            return load_text(source, title, limits)
        case SourceKind.FILE:
            return load_file(source, title, limits)
        case SourceKind.URL:
            return load_url(source, title, limits)


def load_text(text: str, title: str | None, limits: LoadLimits) -> LoadedSource:
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise LoaderError(Code.BAD_REQUEST, "text contains invalid characters") from error
    _check_size(len(raw), "text", limits.max_bytes)
    body = _decode(raw, "text")
    digest = hashlib.sha256(raw).hexdigest()[:_TEXT_URI_HASH_CHARS]
    return LoadedSource(f"text:{digest}", title or _first_line(body), body, Format.TEXT)


def load_file(path_text: str, title: str | None, limits: LoadLimits) -> LoadedSource:
    path = _resolve_under_root(path_text, limits.data_root)
    if not path.exists():
        raise LoaderError(Code.NOT_FOUND, f"no such file under the data root: {path_text!r}")
    if path.is_dir():
        raise LoaderError(Code.BAD_REQUEST, f"{path_text!r} is a directory; give one file")
    if (fmt := format_for_path(path)) is Format.TEXT:
        raise LoaderError(
            Code.BAD_REQUEST, f"unsupported extension {path.suffix!r}; use .rst or .md"
        )
    _check_size(path.stat().st_size, path_text, limits.max_bytes)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise LoaderError(
            Code.BAD_REQUEST, f"cannot read {path_text!r}: {error.strerror}"
        ) from error
    relative = PurePosixPath(path.relative_to(limits.data_root))
    return LoadedSource(f"file:{relative}", title or path.stem, _decode(raw, path_text), fmt, path)


def load_url(
    url: str, title: str | None, limits: LoadLimits, fetch: Fetcher = fetch_url
) -> LoadedSource:
    url = urlsplit(url)._replace(fragment="").geturl()  # #section is not a different source
    response = fetch(url, limits.fetch)
    media_type, charset = _split_content_type(response.content_type)
    if media_type and not media_type.startswith("text/"):
        raise LoaderError(Code.BAD_REQUEST, f"{url} is {media_type}, only text content is ingested")
    text = _decode(response.body, url, charset)
    path = urlsplit(url).path
    if media_type == "text/html":
        page = html_to_text(text)
        if not page.text:
            raise LoaderError(Code.BAD_REQUEST, f"{url} has no readable text")
        return LoadedSource(url, title or page.title or _name_from_url(url), page.text, Format.TEXT)
    return LoadedSource(url, title or _name_from_url(url), text, format_for_path(path))


def _resolve_under_root(path_text: str, root: Path) -> Path:
    candidate = Path(path_text)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not path.is_relative_to(root):
        raise LoaderError(Code.BAD_REQUEST, f"path must stay under {root}: {path_text!r}")
    return path


def _check_size(size: int, what: str, max_bytes: int) -> None:
    if size > max_bytes:
        raise LoaderError(Code.TOO_LARGE, f"{what} is {size} bytes, cap is {max_bytes}")


def _decode(raw: bytes, what: str, charset: str | None = None) -> str:
    if b"\x00" in raw:
        raise LoaderError(Code.BAD_REQUEST, f"{what} looks binary (contains NUL bytes)")
    try:
        text = raw.decode(charset or "utf-8-sig")
    except (UnicodeDecodeError, LookupError) as error:
        raise LoaderError(Code.BAD_REQUEST, f"{what} is not {charset or 'UTF-8'} text") from error
    if not text.strip():
        raise LoaderError(Code.BAD_REQUEST, f"{what} is empty")
    return text


def _split_content_type(header: str) -> tuple[str, str | None]:
    media_type, _, rest = header.partition(";")
    charset = next(
        (part.split("=", 1)[1].strip(" \"'") for part in rest.split(";") if "charset=" in part),
        None,
    )
    return media_type.strip().lower(), charset


def _first_line(text: str) -> str:
    line = next(line.strip() for line in text.splitlines() if line.strip())
    return line[:_TITLE_CHARS]


def _name_from_url(url: str) -> str:
    parts = urlsplit(url)
    return PurePosixPath(parts.path).stem or parts.hostname or url
