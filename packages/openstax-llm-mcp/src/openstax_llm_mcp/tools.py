"""MCP tools backed by the openstax-llm library."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import openstax_md as osm
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from openstax_llm.chunker import DocumentChunker
from openstax_llm_mcp.store import TextbookStore

#: Default chunker configuration, mirroring the `openstax-llm prepare` CLI defaults.
DEFAULT_TARGET_WORDS = 400
DEFAULT_MAX_WORDS = 600
DEFAULT_OVERLAP_WORDS = 50

#: Fields surfaced from `openstax_md.search` results, in display order.
_CATALOG_FIELDS = ("slug", "title", "language", "category", "repo")


def resolve_output_path(out: str, output_root: Path) -> Path:
    """Resolve ``out`` beneath ``output_root``, rejecting escapes.

    An MCP client supplies ``out``, so it is untrusted input: absolute paths and any
    ``..`` traversal that would land outside the configured root are refused before a
    file is created.
    """
    root = output_root.resolve()
    requested = Path(out).expanduser()
    candidate = requested if requested.is_absolute() else root / requested
    resolved = candidate.resolve()

    if resolved != root and root not in resolved.parents:
        raise ValueError(
            f"Refusing to write outside the configured output directory.\n"
            f"  requested: {out}\n"
            f"  resolved:  {resolved}\n"
            f"  allowed:   {root}\n"
            f"Pass a relative path, or restart the server with --output-dir set to a parent."
        )
    return resolved


def build_chunker(target_words: int, max_words: int, overlap: int) -> DocumentChunker:
    """Validate and construct a chunker from tool arguments."""
    if target_words < 1:
        raise ValueError(f"target_words must be >= 1, got {target_words}")
    if max_words < target_words:
        raise ValueError(f"max_words ({max_words}) must be >= target_words ({target_words})")
    if overlap < 0:
        raise ValueError(f"overlap must be >= 0, got {overlap}")
    return DocumentChunker(
        target_words=target_words,
        max_words=max_words,
        overlap_words=overlap,
    )


@contextmanager
def anticipated_failures() -> Iterator[None]:
    """Translate expected failures into a readable ``is_error`` tool result.

    A bare ``ValueError``/``FileNotFoundError`` reaching the SDK is treated as a server
    crash: the model sees only "Error executing tool ..." and the useful text is relegated
    to the server log. Bad arguments and unknown textbook slugs are things a model hits
    constantly, so they are reported back verbatim.
    """
    try:
        yield
    except (ValueError, FileNotFoundError) as exc:
        raise ToolError(str(exc)) from exc


def register_tools(
    server: MCPServer[Any],
    store: TextbookStore,
    output_root: Path,
) -> None:
    """Attach the catalog/inspect/prepare tools to ``server``."""

    @server.tool()
    def search_catalog(query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search the OpenStax textbook catalog.

        Use this first to turn a subject ("calculus", "physics") into a canonical slug
        that the other tools accept. An empty query lists the catalog from the top.

        Args:
            query: Keyword matched against slug, title, repository, and category.
            limit: Maximum number of results to return, ordered by relevance.
        """
        if limit < 1:
            raise ToolError(f"limit must be >= 1, got {limit}")
        results = osm.search(query)
        return [
            {field: entry.get(field) for field in _CATALOG_FIELDS if field in entry}
            for entry in results[:limit]
        ]

    @server.tool()
    def inspect_textbook(
        target: str,
        target_words: int = DEFAULT_TARGET_WORDS,
        max_words: int = DEFAULT_MAX_WORDS,
        overlap: int = DEFAULT_OVERLAP_WORDS,
    ) -> dict[str, Any]:
        """Report chunk statistics and a per-section index for a textbook.

        Cheap relative to `prepare_textbook` and writes nothing to disk. Use it to choose
        a section worth retrieving, or to size a dataset before exporting it.

        Args:
            target: Catalog slug (e.g. `calculus-volume-1`) or path to a local bundle.
            target_words: Soft target words per chunk.
            max_words: Hard ceiling on words per chunk.
            overlap: Words of overlap carried between adjacent chunks.
        """
        with anticipated_failures():
            dataset = store.get(target, chunker=build_chunker(target_words, max_words, overlap))
            summary = dataset.summary()
        summary["sections"] = dataset.section_index()
        return summary

    @server.tool()
    def prepare_textbook(
        target: str,
        out: str,
        target_words: int = DEFAULT_TARGET_WORDS,
        max_words: int = DEFAULT_MAX_WORDS,
        overlap: int = DEFAULT_OVERLAP_WORDS,
    ) -> dict[str, Any]:
        """Compile a textbook, chunk it, and export a JSONL dataset for RAG or fine-tuning.

        Each line is one chunk record with intact LaTeX and full citation metadata. The
        destination must resolve inside the server's configured output directory.

        Args:
            target: Catalog slug (e.g. `calculus-volume-1`) or path to a local bundle.
            out: Destination JSONL path, relative to the server output directory.
            target_words: Soft target words per chunk.
            max_words: Hard ceiling on words per chunk.
            overlap: Words of overlap carried between adjacent chunks.
        """
        with anticipated_failures():
            # Validate arguments and the destination *before* compiling. Reversing this costs
            # a full clone-and-render of the textbook before rejecting a bad path, which is
            # minutes of work for an error that needs no data at all.
            chunker = build_chunker(target_words, max_words, overlap)
            destination = resolve_output_path(out, output_root)
            dataset = store.get(target, chunker=chunker)
            dataset.to_jsonl(destination)
        return {
            "path": str(destination),
            "bytes": destination.stat().st_size,
            "summary": dataset.summary(),
        }
