"""Fetch a URL for ingest: public hosts only, bounded redirects, bounded size, bounded time.

The SSRF guard runs before every connection, including each redirect hop, so the server cannot be
used as a proxy into the private network it runs in. Known limit: the address is checked and then
urllib resolves the name again to connect, so a DNS answer that changes in between is not caught.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPResponse as _UrllibResponse
from urllib.parse import urljoin, urlsplit

from rag_mcp.errors import Code, RagError

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_USER_AGENT = "rag-mcp/0.1"


class FetchError(RagError):
    """A URL was refused or could not be fetched."""


@dataclass(frozen=True)
class FetchLimits:
    max_bytes: int
    timeout_s: float
    max_redirects: int


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str  # full header value, e.g. "text/html; charset=utf-8"
    location: str | None
    body: bytes


Resolver = Callable[[str], list[str]]
"""Host name to the IP addresses it resolves to."""
Opener = Callable[[str, FetchLimits], HttpResponse]
"""One HTTP request without following redirects."""


def fetch_url(
    url: str,
    limits: FetchLimits,
    *,
    resolve: Resolver | None = None,
    open_once: Opener | None = None,
) -> HttpResponse:
    """GET `url`, following at most `max_redirects` hops, each checked by the SSRF guard."""
    resolve = resolve or resolve_host
    open_once = open_once or open_with_urllib
    for _ in range(limits.max_redirects + 1):
        assert_public_url(url, resolve)
        response = open_once(url, limits)
        if response.status not in _REDIRECT_STATUSES:
            return _checked(response, url)
        if not response.location:
            raise FetchError(Code.UNREACHABLE, f"{url} redirected without a Location header")
        url = urljoin(url, response.location)
    raise FetchError(Code.UNREACHABLE, f"more than {limits.max_redirects} redirects from {url}")


def assert_public_url(url: str, resolve: Resolver) -> None:
    """Refuse anything that is not http(s) to a host whose every address is public."""
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise FetchError(Code.BAD_REQUEST, f"only http and https URLs are accepted, got {url!r}")
    if not parts.hostname:
        raise FetchError(Code.BAD_REQUEST, f"URL has no host: {url!r}")
    for address in resolve(parts.hostname):
        if not _is_public(address):
            raise FetchError(
                Code.BAD_REQUEST, f"{parts.hostname} resolves to {address}, which is not public"
            )


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    mapped = getattr(ip, "ipv4_mapped", None)  # ::ffff:127.0.0.1 must count as 127.0.0.1
    if mapped is not None:
        ip = mapped
    return ip.is_global and not ip.is_multicast


def resolve_host(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise FetchError(Code.UNREACHABLE, f"cannot resolve {host}") from error
    return sorted({str(info[4][0]) for info in infos})


def _checked(response: HttpResponse, url: str) -> HttpResponse:
    if response.status == 200:
        return response
    if response.status == 404:
        raise FetchError(Code.NOT_FOUND, f"{url} returned 404")
    raise FetchError(Code.UNREACHABLE, f"{url} returned HTTP {response.status}")


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None  # urllib then raises HTTPError with the 3xx status, which we handle ourselves


def open_with_urllib(url: str, limits: FetchLimits) -> HttpResponse:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "text/*"})
    opener = urllib.request.build_opener(_NoRedirects)
    try:
        with opener.open(request, timeout=limits.timeout_s) as response:
            return _read(response, url, limits.max_bytes)
    except urllib.error.HTTPError as error:
        headers = error.headers
        return HttpResponse(
            error.code, headers.get("Content-Type", ""), headers.get("Location"), b""
        )
    except (OSError, http.client.HTTPException) as error:  # URLError is an OSError
        raise FetchError(Code.UNREACHABLE, f"could not fetch {url}: {error}") from error


def _read(response: _UrllibResponse, url: str, max_bytes: int) -> HttpResponse:
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise FetchError(Code.TOO_LARGE, f"{url} is {declared} bytes, cap is {max_bytes}")
    body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise FetchError(Code.TOO_LARGE, f"{url} exceeds the {max_bytes}-byte cap")
    headers = response.headers
    return HttpResponse(response.status, headers.get("Content-Type", ""), None, body)
