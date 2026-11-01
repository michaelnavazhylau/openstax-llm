# syntax=docker/dockerfile:1

# Base images are pinned by digest, not by tag alone. A published image is only as
# reproducible as its inputs, and `python:3.12-slim-bookworm` / `uv:latest` are mutable refs:
# whichever push happened last would silently decide what a `v0.1.0` container contains.
# Refresh both deliberately when bumping, then re-run the CI image jobs:
#   docker buildx imagetools inspect python:3.12-slim-bookworm
#   docker buildx imagetools inspect ghcr.io/astral-sh/uv:latest

# -----------------------------------------------------------------------------
# Stage 1: Build the workspace virtual environment with uv
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS builder

# Install uv binary from the official Astral image (pinned by digest, see above).
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /uvx /bin/

# ca-certificates is required for every HTTPS fetch. git is required at runtime — the first
# use of a book clones its repository — so it is installed here and carried through by the
# runtime stage's own layer; the builder keeps it too, because a dependency that shells out
# to git must still be installable from source.
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
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS runtime

# Provenance labels. `source` is what links the GHCR package back to this repository —
# without it the package is an orphan that nobody can trace to a commit. VERSION and
# REVISION are supplied by release.yml from the tag and the commit it was cut from.
ARG VERSION=0.0.0-dev
ARG REVISION=unknown

LABEL org.opencontainers.image.title="openstax-llm-mcp" \
      org.opencontainers.image.description="MCP server for pedagogical OpenStax textbook chunking and RAG dataset preparation" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/michaelnavazhylau/openstax-llm" \
      org.opencontainers.image.documentation="https://github.com/michaelnavazhylau/openstax-llm#readme" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

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
