# Glossary

Every RAG, MCP and Postgres term this repo uses, in plain words, with where it actually shows up
here. One meaning per term, repo-wide. `/glossary <term>` looks one up and adds missing ones.

## Retrieval

- **RAG (retrieval-augmented generation)** — instead of hoping the model memorised the docs, you
  search the docs and hand the model the passages it should answer from. This server is the search
  half; Claude is the generation half.
- **Grounding** — answering only from retrieved text, with a citation. The opposite failure is a
  **hallucination**: a fluent answer with nothing behind it.
- **Chunk** — one retrievable piece of a document, small enough to embed and large enough to answer
  something. Here: a `Chunk` is one or more blocks under one heading path (`chunking.py`).
- **Chunking** — deciding where chunks begin and end. Ours is *structure-aware*: boundaries follow
  headings, code blocks and tables, not a fixed character count (PLAN.md decision 3).
- **Heading path** — the trail of headings above a chunk, e.g. `Apache Kafka > HowTo > Manage ACLs`.
  Stored, embedded and indexed with the text so a chunk makes sense on its own.
- **Block** — a paragraph, code block or table inside a section (`parsing/model.py`, `BlockKind`).
- **Token** — the sub-word unit a model actually counts. "max.message.bytes" is one word and many
  tokens, which is why limits are in tokens, not characters.
- **Tokenizer** — the thing that splits text into tokens. Must be the embedding model's own, or the
  512-token budget is a guess (`TokenCounter` in `chunking.py`).
- **Context window** — how much text the model can hold at once. Compact, capped search output is
  how we respect Claude's.

## Vectors and search

- **Embedding (vector)** — a list of numbers that stands for the meaning of a text. Similar meaning,
  nearby vectors. Ours are 384 numbers from `bge-small-en-v1.5`.
- **Embedding model** — what turns text into that vector. Documents and queries must use the same
  one, which is why the model name and width are recorded in the `meta` table.
- **fastembed / ONNX** — the library and the runtime that run the model on CPU without PyTorch,
  keeping the image around 150 MB instead of ~900 MB.
- **Cosine distance** — the angle between two vectors: 0 is identical, 1 is unrelated. In Postgres
  it is the `<=>` operator; cosine *similarity* is `1 - distance`.
- **pgvector** — the Postgres extension that adds the `vector` column type and those operators.
- **ANN (approximate nearest neighbour)** — "close enough, fast", instead of comparing the query to
  every chunk. The trade is a little recall for a lot of speed.
- **HNSW** — the ANN index pgvector builds (a navigable graph). Used only when the query is
  `ORDER BY embedding <=> $1 LIMIT n` with the matching `vector_cosine_ops` opclass.
- **ef_search** — how wide HNSW searches the graph (40 by default). Higher = better recall, slower.
- **Full-text search (FTS)** — classic keyword search. Postgres turns text into a **tsvector** of
  normalised words and matches it with `websearch_to_tsquery`.
- **GIN index** — the inverted index that makes the `tsvector` match fast (word → rows).
- **Keyword vs semantic** — "default value of `kafka.max.message.bytes`" is keyword; "how do I move
  a service to another cloud" is semantic. Each retriever misses the other's questions.
- **Hybrid search** — run both and merge. PLAN.md decision 4.
- **RRF (reciprocal rank fusion)** — the merge: each list contributes `1 / (60 + rank)` per chunk and
  the sums are re-sorted. It uses *ranks*, so a cosine distance and a keyword score never have to be
  put on one scale.
- **Reranker** — a slower cross-encoder that re-scores the top results by reading query and chunk
  together. Deliberately not built; named as the next step.
- **top_k** — how many results to return. Capped at 20 here.

## Database

- **ACID** — a write either happens completely or not at all (atomic), cannot break the schema's
  rules (consistent), is not half-visible to others (isolated), and survives a crash (durable).
  Here: re-ingesting one document is one transaction.
- **Transaction** — the all-or-nothing block (`with connection.transaction():`).
- **Isolation level** — how much concurrent transactions can see of each other. We rely on
  Postgres' default, READ COMMITTED, plus a lock per document.
- **Advisory lock** — a lock on a number you choose rather than on a row; `pg_advisory_xact_lock`
  releases it when the transaction ends. Used for schema setup and per-URI ingest.
- **Idempotent** — running it twice changes nothing the second time. Ingest compares a **content
  hash** (sha256 of the raw text) and reports `unchanged`.
- **Connection pool** — a handful of reused database connections, so no request pays to open one.
- **EXPLAIN** — asks Postgres which plan it will use. How we prove a query hits its index instead of
  scanning every chunk.
- **Sequential scan** — reading every row. On `chunks` it means an index was silently not used: a bug.
- **Generated column** — a column Postgres computes and stores for you; our `tsv` is one.

## MCP and agents

- **MCP (Model Context Protocol)** — the standard way a client like Claude Code discovers and calls
  outside tools. We implement the server side.
- **Tool** — one named, typed function the model may call: `ingest`, `search`, `list_sources`.
  Its description is a prompt: the model picks tools by reading it.
- **stdio transport** — client and server talk over the process' stdin/stdout. Hence: stdout is the
  protocol, logs go to stderr, `print()` is a bug.
- **JSON-RPC** — the message format on that pipe (a request, a response, an id).
- **ToolError** — the MCP SDK's exception for a failure you expected. Raising it returns a result
  marked `is_error=True` with your message, which the model can read; any other exception is treated
  as a crash and the model sees only `Error executing tool <name>`.
- **Agentic AI** — a model that chooses and chains tool calls to reach a goal, rather than answering
  in one shot. Our job is to make each call cheap, typed and honest about failure.
- **Prompt injection** — text in the corpus that tries to give the model instructions
  ("ignore previous..."). Retrieved text is data: quoted for Claude, never executed by us.
- **Stateless** — the server keeps nothing between calls; Postgres is the only memory.

## Evaluation

- **Golden set** — hand-written questions with the passage that should be found. The only way a
  retrieval change can be judged.
- **recall@5** — of the questions, the share whose right passage appears in the top 5.
- **MRR (mean reciprocal rank)** — average of `1 / rank of the first right answer`. Rewards putting
  the right chunk first, not just in the list.
- **p50 / p95 latency** — the typical and the bad-day response time. An average hides the bad day.

## Source format

- **RST (reStructuredText)** — the devportal's markup. Headings are underlined with punctuation,
  which is why the parser tracks adornment characters.
- **Directive** — an RST block instruction, `.. code-block:: bash`. **Role** — inline markup,
  `:doc:`/`:ref:`. Roles are stripped to their text; the link target is noise to a search index.
- **`.. include::`** — pulls another file's text into the page. Aiven's config parameters live only
  in included files, so includes are expanded before parsing.
