---
paths:
  - "Dockerfile"
  - "docker-compose.yml"
  - ".dockerignore"
  - "pyproject.toml"
  - ".env.example"
---

# Container and dependencies

The promise is `git clone` → `docker compose up -d --build` → working MCP server, under ten minutes
on a fresh machine with no manual step.

- The server runs as a **non-root** user, with no build toolchain left in the final image.
- The embedding model is baked into the image at build time, so the first start needs no network.
- Base images are pinned (Python and the pgvector image), and `uv.lock` is committed so a rebuild
  resolves to the same versions. A dependency pin that exists for a reason gets a comment saying
  why, like the `cryptography<49` constraint.
- **No secrets in the image, in `docker-compose.yml`, or in git.** Values come from the environment;
  `.env.example` documents the names with safe placeholders and `.env` is gitignored.
- `db` is health-checked and `server` waits for it; data lives in a named volume so a rebuild keeps
  the ingested corpus.
- The stdio launcher is `docker exec -i`, never `docker compose run`, which writes to stdout and
  would corrupt the protocol (`mcp.md`).
- `.dockerignore` keeps `.venv/`, caches, `data/`, and git out of the build context.
- Anything the container needs at runtime is a declared env var in `settings.py`, never a path
  hardcoded in the Dockerfile.
