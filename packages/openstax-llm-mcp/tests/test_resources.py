from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from _fakes import SLUG
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError


def read_resource(server: MCPServer[Any], uri: str) -> str:
    contents = asyncio.run(server.read_resource(uri))
    return "".join(
        item.content if isinstance(item.content, str) else item.content.decode()
        for item in contents  # type: ignore[union-attr]
    )


def test_overview_resource_lists_sections(server: MCPServer[Any]) -> None:
    payload = json.loads(read_resource(server, f"textbook://{SLUG}"))
    assert payload["book_slug"] == SLUG
    assert payload["total_chunks"] == 3
    assert [entry["section"] for entry in payload["sections"]] == ["1.1", "1.2"]
    assert payload["sections"][0]["chunks"] == 2
    assert payload["sections"][0]["section_title"] == "Review of Functions"


def test_section_resource_returns_every_chunk(server: MCPServer[Any]) -> None:
    payload = json.loads(read_resource(server, f"textbook://{SLUG}/1.1"))
    assert payload["section"] == "1.1"
    assert payload["section_title"] == "Review of Functions"
    assert [chunk["chunk_id"] for chunk in payload["chunks"]] == ["1.1-c001", "1.1-c002"]
    # Formula integrity survives the round trip out of the resource.
    assert payload["chunks"][1]["text"].count("$") % 2 == 0


def test_section_resource_reports_available_sections(server: MCPServer[Any]) -> None:
    with pytest.raises(ResourceNotFoundError, match="not found"):
        read_resource(server, f"textbook://{SLUG}/9.9")


def test_resource_templates_are_registered(server: MCPServer[Any]) -> None:
    templates = asyncio.run(server.list_resource_templates())
    uris = {template.uri_template for template in templates}
    assert uris == {"textbook://{slug}", "textbook://{slug}/{section}"}
