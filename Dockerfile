# Stage 1: install dependencies and bake the embedding model. uv and build tools stay here.
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# The model is downloaded at build time so the first `docker compose up` needs no network.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ENV HF_HUB_DISABLE_PROGRESS_BARS=1 TQDM_DISABLE=1
RUN .venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDING_MODEL}', cache_dir='/app/models')"

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Stage 2: runtime only, non-root. Dependencies and model are separate layers from the source, so a
# code change rewrites a few hundred KB instead of the 500 MB that has to stay warm in the page cache.
FROM python:3.12-slim
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv ./.venv
COPY --from=builder --chown=app:app /app/models ./models
COPY --from=builder --chown=app:app /app/src ./src
USER app
ENV PATH="/app/.venv/bin:$PATH" \
    EMBEDDING_CACHE_DIR=/app/models \
    HF_HUB_OFFLINE=1 HF_HUB_DISABLE_PROGRESS_BARS=1 TQDM_DISABLE=1
CMD ["rag-mcp", "up"]
