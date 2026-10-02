"""MCP resources exposing compiled textbook content by URI."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

from openstax_llm_mcp.store import TextbookStore

#: Human-readable label used when `prepare_textbook` produced a sectionless chunk.
_NO_SECTION = "(none)"


def register_resources(server: MCPServer[Any], store: TextbookStore) -> None:
    """Attach the `textbook://` resource templates to ``server``."""

    @server.resource(
        "textbook://{slug}",
        name="textbook-overview",
        title="Textbook overview",
        description=(
            "Chunk totals, pedagogical breakdown, and the per-section index for one "
            "OpenStax textbook. Read this before requesting a section."
        ),
        mime_type="application/json",
    )
    def textbook_overview(slug: str) -> str:
        dataset = store.get(slug)
        payload: dict[str, Any] = {
            "book_slug": dataset.book_slug,
            "book_title": dataset.book_title,
            "total_chunks": len(dataset.chunks),
            "total_words": dataset.total_words,
            "total_tokens_est": dataset.total_tokens_est,
            "sections": dataset.section_index(),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @server.resource(
        "textbook://{slug}/{section}",
        name="textbook-section",
        title="Textbook section chunks",
        description=(
            "Every chunk for one section of a textbook, including intact LaTeX math and "
            "full citation metadata."
        ),
        mime_type="application/json",
    )
    def textbook_section(slug: str, section: str) -> str:
        dataset = store.get(slug)
        grouped = dataset.by_section()
        chunks = grouped.get(section)
        if chunks is None:
            available = ", ".join(sorted(grouped)) or _NO_SECTION
            raise ResourceNotFoundError(
                f"Section '{section}' not found in '{dataset.book_slug}'. Available: {available}"
            )
        payload = {
            "book_slug": dataset.book_slug,
            "book_title": dataset.book_title,
            "section": chunks[0].section,
            "section_title": chunks[0].section_title,
            "chunks": [chunk.to_dict() for chunk in chunks],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
