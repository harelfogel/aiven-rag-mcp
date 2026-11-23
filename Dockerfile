FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Dependencies first so code changes do not re-install them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"

CMD ["rag-mcp", "up"]
