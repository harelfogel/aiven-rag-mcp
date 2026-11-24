# 003: Input guards for ingest, with the standard library

## Context
`ingest` accepts pasted text, a file path, or a URL. The server runs inside a Docker network next
to Postgres, so a URL loader is a proxy into that network unless it refuses private addresses, and
a file loader is a file reader for the whole container unless it is confined to one folder.

## Options
1. httpx or requests for HTTP, with a redirect hook for the address check: nicer API, one more
   dependency to justify, and httpx is only present today as a renamed transitive dependency of mcp.
2. The standard library: `urllib` with redirect following disabled, `ipaddress` for the address
   classification, `html.parser` to strip HTML.

## Decision
Option 2. Each redirect hop is resolved and checked before we connect; `ip.is_global` plus a
multicast check covers loopback, private, link-local, cloud metadata, CGNAT and unspecified
ranges without a hand-kept list. File paths are resolved (symlinks included) and must stay under
`DATA_ROOT`; only `.rst` and `.md` are accepted. One size cap (`INGEST_MAX_BYTES`) applies to
all three inputs and is checked before the body is read where a server declares it.

## Consequences
- Zero new dependencies; 40 lines of HTML stripping instead of a library.
- Known limit: the address is checked and urllib then resolves the name again to connect, so a
  DNS answer that changes in between (rebinding) is not caught. Pinning the IP needs a custom
  connection class or an HTTP library with that feature; stated in the README.
- Text pasted through `ingest` is identified by a content hash, so the same text is one source
  and edited text is a new one.
