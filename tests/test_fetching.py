import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from rag_mcp.errors import Code
from rag_mcp.fetching import (
    FetchError,
    FetchLimits,
    HttpResponse,
    Opener,
    Resolver,
    assert_public_url,
    fetch_url,
    open_with_urllib,
)

LIMITS = FetchLimits(max_bytes=50, timeout_s=2, max_redirects=2)
PUBLIC = {
    "example.com": ["93.184.216.34"],
    "v6.example.com": ["2606:2800:220:1:248:1893:25c8:1946"],
}


def resolver(table: dict[str, list[str]]) -> Resolver:
    def resolve(host: str) -> list[str]:
        if host not in table:
            raise FetchError(Code.UNREACHABLE, f"cannot resolve {host}")
        return table[host]

    return resolve


# SSRF guard


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "0.0.0.0",
     "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1", "100.64.0.1"],
)  # fmt: skip
def test_assert_public_url_rejects_non_public_addresses(address: str) -> None:
    with pytest.raises(FetchError, match="not public") as error:
        assert_public_url("http://internal.example/", resolver({"internal.example": [address]}))
    assert error.value.code is Code.BAD_REQUEST


def test_assert_public_url_rejects_if_any_address_is_private() -> None:
    table = {"mixed.example": ["93.184.216.34", "10.0.0.1"]}
    with pytest.raises(FetchError, match="10.0.0.1"):
        assert_public_url("https://mixed.example/x", resolver(table))


def test_assert_public_url_accepts_public_v4_and_v6() -> None:
    assert_public_url("https://example.com/", resolver(PUBLIC))
    assert_public_url("https://v6.example.com/", resolver(PUBLIC))


@pytest.mark.parametrize(
    "url", ["ftp://example.com/x", "file:///etc/passwd", "http:///nohost", "example.com"]
)
def test_assert_public_url_rejects_bad_scheme_or_missing_host(url: str) -> None:
    with pytest.raises(FetchError) as error:
        assert_public_url(url, resolver(PUBLIC))
    assert error.value.code is Code.BAD_REQUEST


# redirects (opener stubbed)


def script(responses: dict[str, HttpResponse]) -> Opener:
    def open_once(url: str, _limits: FetchLimits) -> HttpResponse:
        return responses[url]

    return open_once


def redirect(to: str) -> HttpResponse:
    return HttpResponse(302, "", to, b"")


def test_fetch_url_follows_redirects_and_checks_every_hop() -> None:
    table = {**PUBLIC, "evil.example": ["169.254.169.254"]}
    ok = HttpResponse(200, "text/plain", None, b"hi")
    responses = {
        "https://example.com/a": redirect("/b"),
        "https://example.com/b": ok,
        "https://example.com/c": redirect("http://evil.example/meta"),
    }
    assert (
        fetch_url(
            "https://example.com/a", LIMITS, resolve=resolver(table), open_once=script(responses)
        )
        == ok
    )
    with pytest.raises(FetchError, match="169.254.169.254"):
        fetch_url(
            "https://example.com/c", LIMITS, resolve=resolver(table), open_once=script(responses)
        )


def test_fetch_url_bounds_redirect_count_and_requires_location() -> None:
    loop = {f"https://example.com/{i}": redirect(f"/{i + 1}") for i in range(5)}
    with pytest.raises(FetchError, match="more than 2 redirects"):
        fetch_url("https://example.com/0", LIMITS, resolve=resolver(PUBLIC), open_once=script(loop))
    no_location = {"https://example.com/x": HttpResponse(301, "", None, b"")}
    with pytest.raises(FetchError, match="without a Location"):
        fetch_url(
            "https://example.com/x", LIMITS, resolve=resolver(PUBLIC), open_once=script(no_location)
        )


def test_fetch_url_maps_status_codes() -> None:
    responses = {
        "https://example.com/404": HttpResponse(404, "", None, b""),
        "https://example.com/500": HttpResponse(500, "", None, b""),
    }
    with pytest.raises(FetchError) as missing:
        fetch_url(
            "https://example.com/404", LIMITS, resolve=resolver(PUBLIC), open_once=script(responses)
        )
    assert missing.value.code is Code.NOT_FOUND
    with pytest.raises(FetchError) as broken:
        fetch_url(
            "https://example.com/500", LIMITS, resolve=resolver(PUBLIC), open_once=script(responses)
        )
    assert broken.value.code is Code.UNREACHABLE


# the real urllib opener against a local server (bypasses the SSRF guard on purpose)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802  (http.server API)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
            return
        body = b"x" * 60 if self.path == "/big" else b"hello"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        if self.path != "/nolength":
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return  # keep pytest output clean


@pytest.fixture(scope="module")
def local_server() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_open_with_urllib_reads_body_and_headers(local_server: str) -> None:
    response = open_with_urllib(f"{local_server}/final", LIMITS)
    assert (response.status, response.body) == (200, b"hello")
    assert response.content_type.startswith("text/plain")


def test_open_with_urllib_does_not_follow_redirects(local_server: str) -> None:
    response = open_with_urllib(f"{local_server}/redirect", LIMITS)
    assert (response.status, response.location) == (302, "/final")


def test_open_with_urllib_enforces_size_cap_with_and_without_content_length(
    local_server: str,
) -> None:
    with pytest.raises(FetchError) as declared:
        open_with_urllib(f"{local_server}/big", LIMITS)
    assert declared.value.code is Code.TOO_LARGE
    with pytest.raises(FetchError) as streamed:
        open_with_urllib(
            f"{local_server}/nolength", FetchLimits(max_bytes=3, timeout_s=2, max_redirects=0)
        )
    assert streamed.value.code is Code.TOO_LARGE


def test_open_with_urllib_connection_refused_is_unreachable() -> None:
    with pytest.raises(FetchError) as error:
        open_with_urllib("http://127.0.0.1:9/", LIMITS)
    assert error.value.code is Code.UNREACHABLE
