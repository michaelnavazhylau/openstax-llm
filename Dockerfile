# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12

# -----------------------------------------------------------------------------
# Stage 1: Build virtual environment with uv
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# Install uv binary from official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install git and ca-certificates (required to fetch git dependencies like openstax-md)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Configure uv: compile bytecode for faster startup, copy files, use container python
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Cache dependencies: copy lockfile and project definition first
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy project metadata and source code
COPY README.md LICENSE ./
COPY src/ ./src/

# Install the openstax-llm package as non-editable into the virtual environment
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# -----------------------------------------------------------------------------
# Stage 2: Minimal runtime image
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="openstax-llm" \
      org.opencontainers.image.description="Pedagogical semantic chunking and RAG dataset preparation from OpenStax textbooks" \
      org.opencontainers.image.licenses="MIT"

# Install git and ca-certificates (required by openstax-md for on-demand textbook cloning)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory "*"

# Create a non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser && \
    mkdir -p /home/appuser/.cache && \
    chown -R appuser:appuser /home/appuser

# Copy virtual environment from builder stage
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Ensure virtualenv binaries are prioritized on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Prepare workspace directory for data mounts
WORKDIR /data
RUN mkdir -p /data && chown -R appuser:appuser /data && chmod 777 /data

USER appuser

ENTRYPOINT ["openstax-llm"]
CMD ["--help"]
