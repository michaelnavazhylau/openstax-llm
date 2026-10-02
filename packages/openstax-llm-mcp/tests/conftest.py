"""Shared fixtures for the openstax-llm MCP tests.

Every test runs against an in-memory dataset so the suite never clones a textbook.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _fakes import FakeStore, make_dataset

from openstax_llm_mcp.server import build_server


@pytest.fixture
def store() -> FakeStore:
    return FakeStore(make_dataset())


@pytest.fixture
def output_root(tmp_path: Path) -> Path:
    root = tmp_path / "out"
    root.mkdir()
    return root


@pytest.fixture
def server(store: FakeStore, output_root: Path):
    return build_server(store=store, output_root=output_root, version="0.0.0-test")
