# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12

# -----------------------------------------------------------------------------
# Stage 1: Build the workspace virtual environment with uv
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# Install uv binary from the official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# git and ca-certificates are required to fetch the openstax-md git dependency and to
# clone textbooks on demand.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Layer 1: dependency resolution only. The manifests are copied without the sources so a
# source edit does not invalidate the dependency cache. The per-package READMEs have to
# come along because hatchling reads them while building each member's metadata, even
# under --no-install-project.
COPY pyproject.toml uv.lock ./
COPY packages/openstax-llm/pyproject.toml packages/openstax-llm/README.md ./packages/openstax-llm/
COPY packages/openstax-llm-mcp/pyproject.toml packages/openstax-llm-mcp/README.md ./packages/openstax-llm-mcp/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Layer 2: build and install both workspace members as wheels.
COPY README.md LICENSE ./
COPY packages/ ./packages/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# -----------------------------------------------------------------------------
# Stage 2: Minimal runtime image
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="openstax-llm-mcp" \
      org.opencontainers.image.description="MCP server for pedagogical OpenStax textbook chunking and RAG dataset preparation" \
      org.opencontainers.image.licenses="MIT"

# git is needed at runtime: the first use of a book clones its repository.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory "*"

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser \
    && mkdir -p /home/appuser/.cache \
    && chown -R appuser:appuser /home/appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# /data is the writable workspace: the textbook clone cache and exported datasets live
# under it, so mounting a volume there persists both.
WORKDIR /data
RUN mkdir -p /data && chown -R appuser:appuser /data

USER appuser

# The image defaults to the MCP server over streamable HTTP, which is what a container is
# for. Use `--entrypoint openstax-llm` for the CLI:
#   docker run --rm --entrypoint openstax-llm openstax-llm-mcp info astronomy-2e
#
# Clients that address the server by a hostname other than localhost need it allowed, or
# DNS-rebinding protection answers 421:
#   docker run -p 8765:8765 openstax-llm-mcp --http --host 0.0.0.0 \
#     --allow-host textbooks.internal --allow-host textbooks.internal:*
ENTRYPOINT ["openstax-llm-mcp"]
CMD ["--http", "--host", "0.0.0.0", "--port", "8765", "--output-dir", "/data"]
