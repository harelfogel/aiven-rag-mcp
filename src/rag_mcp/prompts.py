"""Every string a model reads: server instructions, tool descriptions and argument docs.

They are written for Claude, not for people: each says what the tool returns and when to use it.
Nothing else in the code base holds tool-facing prose.
"""

SERVER_NAME = "aiven-docs-rag"

SERVER_INSTRUCTIONS = (
    "Retrieval over the Aiven developer documentation (devportal). Call `search` for any question "
    "about Aiven services, configuration parameters, limits or how-to steps, then answer from the "
    "returned chunks and cite their `url` or `source`. Use `list_sources` to see what is indexed "
    "and `ingest` to add more text, a file or a web page."
)

SEARCH_DESCRIPTION = (
    "Find the documentation chunks most relevant to a question. Returns up to top_k chunks, best "
    "first, each with its page title, heading path, text, source and a link for citation. Use "
    "mode=hybrid (default) for most questions; mode=keyword for an exact parameter name or error "
    "string; mode=vector for a question phrased in different words than the docs. An empty hits "
    "list means nothing matched; say so instead of guessing."
)

INGEST_DESCRIPTION = (
    "Add one document to the knowledge base. kind=text takes the text itself, kind=file takes a "
    "path to a .rst or .md file inside the server's data folder, kind=url takes an http(s) page "
    "that is plain text, Markdown, RST or HTML. Safe to repeat: unchanged content reports "
    "'unchanged' and changed content replaces the earlier version. Returns the source id, how "
    "many chunks it became and whether it was ingested or unchanged."
)

LIST_SOURCES_DESCRIPTION = (
    "List what has been ingested, newest first, with totals. Returns total_sources, total_chunks "
    "and one page of sources (uri, title, kind, chunk count, ingest time). Page with offset when "
    "total_sources is larger than the page."
)

QUERY_DOC = "The question or keywords to look for, in plain language."
TOP_K_DOC = "How many chunks to return."
MODE_DOC = "hybrid (meaning and words, default), vector (meaning only), keyword (exact words)."
SOURCE_DOC = "The text itself, a file path inside the data folder, or an http(s) URL, per `kind`."
KIND_DOC = "text, file or url."
TITLE_DOC = "Optional title; defaults to the document's own title or file name."
LIMIT_DOC = "How many sources to return."
OFFSET_DOC = "How many sources to skip, for paging."
