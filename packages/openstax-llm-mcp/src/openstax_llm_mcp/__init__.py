"""openstax-llm-mcp -- Model Context Protocol server for openstax-llm."""

from __future__ import annotations

from openstax_llm_mcp._version import __version__
from openstax_llm_mcp.server import create_server

__all__ = ["__version__", "create_server"]
