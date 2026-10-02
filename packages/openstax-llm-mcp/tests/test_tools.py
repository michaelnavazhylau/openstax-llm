from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from _fakes import FakeStore
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from openstax_llm_mcp.tools import build_chunker, resolve_output_path


def call_tool(server: MCPServer[Any], name: str, arguments: dict[str, Any]) -> tuple[bool, Any]:
    """Invoke a registered tool, returning ``(is_error, payload)``.

    ``MCPServer.call_tool`` raises ``ToolError`` for anything the model is meant to read;
    the transport layer converts that into an ``is_error`` result. Catching it here keeps
    the assertions about *what the model sees* rather than how the SDK plumbs it.
    """
    try:
        result = asyncio.run(server.call_tool(name, arguments))
    except ToolError as exc:
        return True, str(exc)
    return False, result.structured_content


# --------------------------------------------------------------------------- helpers


def test_resolve_output_path_allows_nested_relative(output_root: Path) -> None:
    resolved = resolve_output_path("datasets/calculus.jsonl", output_root)
    assert resolved == (output_root / "datasets" / "calculus.jsonl").resolve()


def test_resolve_output_path_allows_the_root_itself(output_root: Path) -> None:
    assert resolve_output_path(".", output_root) == output_root.resolve()


@pytest.mark.parametrize("out", ["../escape.jsonl", "a/../../escape.jsonl", "/etc/passwd"])
def test_resolve_output_path_rejects_escapes(out: str, output_root: Path) -> None:
    with pytest.raises(ValueError, match="Refusing to write outside"):
        resolve_output_path(out, output_root)


def test_build_chunker_passes_configuration() -> None:
    chunker = build_chunker(target_words=100, max_words=200, overlap=10)
    assert (chunker.target_words, chunker.max_words, chunker.overlap_words) == (100, 200, 10)


@pytest.mark.parametrize(
    ("target_words", "max_words", "overlap", "match"),
    [
        (0, 600, 50, "target_words"),
        (400, 200, 50, "max_words"),
        (400, 600, -1, "overlap"),
    ],
)
def test_build_chunker_rejects_bad_configuration(
    target_words: int, max_words: int, overlap: int, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        build_chunker(target_words, max_words, overlap)


# ----------------------------------------------------------------------------- tools


def test_search_catalog_finds_calculus(server: MCPServer[Any]) -> None:
    is_error, payload = call_tool(server, "search_catalog", {"query": "calculus"})
    assert not is_error
    slugs = [entry["slug"] for entry in payload["result"]]
    assert "calculus-volume-1" in slugs


def test_search_catalog_respects_limit(server: MCPServer[Any]) -> None:
    is_error, payload = call_tool(server, "search_catalog", {"query": "a", "limit": 1})
    assert not is_error
    assert len(payload["result"]) == 1


def test_inspect_textbook_reports_sections(server: MCPServer[Any], store: FakeStore) -> None:
    is_error, payload = call_tool(server, "inspect_textbook", {"target": "calculus-volume-1"})
    assert not is_error
    assert payload["book_slug"] == "calculus-volume-1"
    assert payload["total_chunks"] == 3
    assert [entry["section"] for entry in payload["sections"]] == ["1.1", "1.2"]
    assert payload["chunk_types"] == {"prose": 2, "example": 1}
    assert store.requests[0][0] == "calculus-volume-1"


def test_inspect_textbook_forwards_chunker_configuration(
    server: MCPServer[Any], store: FakeStore
) -> None:
    call_tool(
        server,
        "inspect_textbook",
        {"target": "calculus-volume-1", "target_words": 111, "max_words": 222, "overlap": 7},
    )
    _, chunker = store.requests[-1]
    assert (chunker.target_words, chunker.max_words, chunker.overlap_words) == (111, 222, 7)


def test_prepare_textbook_writes_jsonl(server: MCPServer[Any], output_root: Path) -> None:
    is_error, payload = call_tool(
        server, "prepare_textbook", {"target": "calculus-volume-1", "out": "calc.jsonl"}
    )
    assert not is_error

    written = Path(payload["path"])
    assert written == output_root / "calc.jsonl"
    assert payload["bytes"] == written.stat().st_size
    assert payload["summary"]["total_chunks"] == 3

    records = [json.loads(line) for line in written.read_text().splitlines() if line.strip()]
    assert len(records) == 3
    # The invariant this library exists to protect: math never splits across a boundary.
    assert all(record["text"].count("$") % 2 == 0 for record in records)


def test_prepare_textbook_refuses_to_escape_output_root(
    server: MCPServer[Any], tmp_path: Path
) -> None:
    is_error, message = call_tool(
        server, "prepare_textbook", {"target": "calculus-volume-1", "out": "../escaped.jsonl"}
    )
    assert is_error
    assert "Refusing to write outside" in message
    assert not (tmp_path / "escaped.jsonl").exists()


def test_prepare_textbook_rejects_invalid_chunk_configuration(server: MCPServer[Any]) -> None:
    is_error, message = call_tool(
        server,
        "prepare_textbook",
        {"target": "calculus-volume-1", "out": "x.jsonl", "target_words": 500, "max_words": 100},
    )
    assert is_error
    assert "max_words" in message
