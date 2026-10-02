"""Package version, resolved from installed metadata so `pyproject.toml` stays authoritative."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("openstax-llm-mcp")
except PackageNotFoundError:  # pragma: no cover - only hit from an uninstalled source tree
    __version__ = "0.1.0"
