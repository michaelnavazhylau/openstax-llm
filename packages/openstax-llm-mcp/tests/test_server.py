from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from _fakes import make_dataset
from mcp.server.mcpserver import MCPServer

from openstax_llm.chunker import DocumentChunker
from openstax_llm.dataset import TextBookDataset
from openstax_llm_mcp.__main__ import DEFAULT_PORT, build_parser
from openstax_llm_mcp.server import create_server
from openstax_llm_mcp.store import TextbookStore


def tool_names(server: MCPServer[object]) -> set[str]:
    return {tool.name for tool in asyncio.run(server.list_tools())}


# ------------------------------------------------------------------------ CLI parser


def test_parser_defaults_to_stdio() -> None:
    args = build_parser().parse_args([])
    assert args.http is False
    assert args.host == "127.0.0.1"
    assert args.port == DEFAULT_PORT
    assert args.allow_host == []
    assert args.output_dir is None
    assert args.max_cached_books == 2
    assert args.log_level == "INFO"
    assert args.insecure_disable_host_check is False


def test_parser_collects_repeated_allow_host() -> None:
    args = build_parser().parse_args(
        ["--http", "--host", "0.0.0.0", "--allow-host", "a:1", "--allow-host", "b"]
    )
    assert args.http is True
    assert args.host == "0.0.0.0"
    assert args.allow_host == ["a:1", "b"]


def test_parser_version_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert "openstax-llm-mcp" in capsys.readouterr().out


# ---------------------------------------------------------------------------- server


def test_create_server_registers_expected_surface(tmp_path: Path) -> None:
    server = create_server(output_root=tmp_path, version="0.0.0-test")
    assert tool_names(server) == {"search_catalog", "inspect_textbook", "prepare_textbook"}
    templates = asyncio.run(server.list_resource_templates())
    assert {template.uri_template for template in templates} == {
        "textbook://{slug}",
        "textbook://{slug}/{section}",
    }


def test_create_server_defaults_output_root_to_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    server = create_server(version="0.0.0-test")
    # No exception and a usable server; the output root is asserted through tool behaviour
    # in test_tools.py, which bounds writes at build_server level.
    assert server.name == "openstax-llm"


# ----------------------------------------------------------------------------- store


@pytest.fixture
def counting_compiler(monkeypatch) -> list[dict]:
    """Replace the real compiler with a counter that records every keyword argument."""
    calls: list[dict] = []

    def fake_from_textbook(cls, source, **kwargs):  # noqa: ANN001, ANN003
        calls.append({"source": str(source), **kwargs})
        return make_dataset()

    monkeypatch.setattr(TextBookDataset, "from_textbook", classmethod(fake_from_textbook))
    return calls


def test_store_returns_the_cached_dataset(counting_compiler: list[dict]) -> None:
    store = TextbookStore(max_entries=2)
    first = store.get("book-a")
    second = store.get("book-a")
    assert first is second
    assert [call["source"] for call in counting_compiler] == ["book-a"]


def test_store_compiles_quietly(counting_compiler: list[dict]) -> None:
    """Regression guard: stdout is the JSON-RPC channel under the stdio transport."""
    TextbookStore().get("book-a")
    assert counting_compiler[0]["quiet"] is True


def test_store_keys_on_chunker_configuration(counting_compiler: list[dict]) -> None:
    store = TextbookStore(max_entries=4)
    store.get("book-a")
    store.get("book-a", chunker=DocumentChunker(target_words=100))
    store.get("book-a", chunker=DocumentChunker())
    assert len(counting_compiler) == 2


def test_store_evicts_least_recently_used(counting_compiler: list[dict]) -> None:
    store = TextbookStore(max_entries=2)
    store.get("book-a")
    store.get("book-b")
    store.get("book-b")  # refresh book-b's recency
    store.get("book-c")  # must evict book-a, the least recently used
    assert [call["source"] for call in counting_compiler] == ["book-a", "book-b", "book-c"]

    store.get("book-b")  # still cached, so no fourth compile
    assert len(counting_compiler) == 3

    store.get("book-a")  # evicted earlier, so this recompiles
    assert [call["source"] for call in counting_compiler] == [
        "book-a",
        "book-b",
        "book-c",
        "book-a",
    ]


def test_store_clear_forces_recompilation(counting_compiler: list[dict]) -> None:
    store = TextbookStore(max_entries=2)
    store.get("book-a")
    store.clear()
    store.get("book-a")
    assert len(counting_compiler) == 2
