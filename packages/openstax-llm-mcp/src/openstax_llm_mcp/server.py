"""Server wiring for the openstax-llm MCP server.

Hosts the compiled-textbook cache and attaches the tools and resources. Kept free of
argparse and transport concerns so it can be built directly in tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from openstax_llm_mcp._version import __version__
from openstax_llm_mcp.resources import register_resources
from openstax_llm_mcp.store import TextbookStore
from openstax_llm_mcp.tools import register_tools

#: Shown to the client on initialize; the model uses it to decide when to reach for these tools.
INSTRUCTIONS = """\
Turn OpenStax college textbooks into citation-aware, formula-safe RAG and fine-tuning datasets.

Workflow:
1. `search_catalog` to resolve a subject into a canonical slug.
2. `inspect_textbook` to see chunk totals and the per-section index.
3. `prepare_textbook` to export JSONL, or read `textbook://<slug>/<section>` to pull one
   section into context.

Chunk boundaries always respect pedagogical units: worked examples stay with their
solutions, and inline `$...$` or display `$$...$$` math is never split.
"""


def build_server(
    *,
    store: TextbookStore,
    output_root: Path,
    version: str = __version__,
) -> MCPServer[Any]:
    """Attach every tool and resource to a fresh server bound to ``store``."""
    server: MCPServer[Any] = MCPServer(
        name="openstax-llm",
        title="OpenStax LLM",
        version=version,
        instructions=INSTRUCTIONS,
    )
    register_tools(server, store, output_root)
    register_resources(server, store)
    return server


def create_server(
    *,
    output_root: Path | None = None,
    max_cached_books: int = 2,
    version: str = __version__,
) -> MCPServer[Any]:
    """Build a server with its own textbook cache.

    ``output_root`` bounds every path `prepare_textbook` may write to and doubles as the
    base for the builder's scratch directory, so link resolution does not depend on the
    process working directory.
    """
    root = (output_root or Path.cwd()).resolve()
    store = TextbookStore(max_entries=max_cached_books, out_dir=root / ".scratch_build")
    return build_server(store=store, output_root=root, version=version)
