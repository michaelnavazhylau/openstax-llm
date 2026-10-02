"""End-to-end tests against a real OpenStax textbook.

Compiling a book clones its repository and renders every module, which takes minutes and
needs network access. These tests therefore do not run by default:

    OPENSTAX_LLM_NETWORK_TESTS=1 uv run pytest -v tests/test_integration.py

Override the book with ``OPENSTAX_LLM_TEST_BOOK=<slug>``. What they buy over the unit
tests is real coverage of the compile path and validation of genuine exported records
against the schema published in the skill.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from openstax_llm.dataset import TextBookDataset
from openstax_llm.validate import errors_only, summarize_problems, validate_chunks
from openstax_llm_mcp.server import create_server

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENSTAX_LLM_NETWORK_TESTS") != "1",
    reason="set OPENSTAX_LLM_NETWORK_TESTS=1 to run network-backed integration tests",
)

SLUG = os.environ.get("OPENSTAX_LLM_TEST_BOOK", "calculus-volume-1")
REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (REPO_ROOT / "skills/openstax-llm/assets/chunk.schema.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def output_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("integration")


@pytest.fixture(scope="module")
def server(output_root: Path):
    # One server for the whole module so the textbook cache is exercised across tests.
    return create_server(output_root=output_root, max_cached_books=1, version="0.0.0-test")


def call(server, name: str, arguments: dict[str, Any]) -> Any:
    result = asyncio.run(server.call_tool(name, arguments))
    assert result.is_error is not True, result.content
    return result.structured_content


def test_catalog_search_is_offline_and_finds_the_book(server) -> None:
    payload = call(server, "search_catalog", {"query": SLUG})
    assert SLUG in [entry["slug"] for entry in payload["result"]]


def test_inspect_and_prepare_agree(server, output_root: Path) -> None:
    inspected = call(server, "inspect_textbook", {"target": SLUG})
    assert inspected["book_slug"] == SLUG
    assert inspected["total_chunks"] > 0
    assert inspected["sections"], "a real textbook must report sections"

    prepared = call(server, "prepare_textbook", {"target": SLUG, "out": "book.jsonl"})
    # Same compiled dataset, so the totals must match exactly.
    assert prepared["summary"]["total_chunks"] == inspected["total_chunks"]
    assert prepared["summary"]["total_words"] == inspected["total_words"]

    records = [
        json.loads(line)
        for line in Path(prepared["path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == inspected["total_chunks"]

    sections = [entry["section"] for entry in inspected["sections"]]
    assert [record["section"] for record in records].count(sections[0]) == next(
        entry["chunks"] for entry in inspected["sections"] if entry["section"] == sections[0]
    )


def test_every_exported_record_matches_the_published_schema(server, output_root: Path) -> None:
    path = output_root / "book.jsonl"
    if not path.exists():
        call(server, "prepare_textbook", {"target": SLUG, "out": "book.jsonl"})

    validator = jsonschema.Draft202012Validator(SCHEMA)
    failures: list[str] = []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        records.append(record)
        for error in validator.iter_errors(record):
            failures.append(f"line {number} ({record.get('chunk_id')}): {error.message}")
            if len(failures) > 5:
                break

    assert not failures, "\n".join(failures)


def test_formulas_are_never_split_across_boundaries(server, output_root: Path) -> None:
    """The invariant this project exists to protect, checked against a real book.

    Uses the library validator rather than a local `$` count: escaped currency such as
    `\\$962.50` is not a math delimiter, and a naive parity check reports it as a split
    formula.
    """
    path = output_root / "book.jsonl"
    if not path.exists():
        call(server, "prepare_textbook", {"target": SLUG, "out": "book.jsonl"})

    dataset = TextBookDataset.from_jsonl(path)
    problems = errors_only(validate_chunks(dataset.chunks))
    assert problems == [], "\n".join(str(problem) for problem in problems[:10])


def test_chunk_ids_are_unique_and_provenance_is_complete(server, output_root: Path) -> None:
    path = output_root / "book.jsonl"
    if not path.exists():
        call(server, "prepare_textbook", {"target": SLUG, "out": "book.jsonl"})

    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    ids = [record["chunk_id"] for record in records]
    duplicates = [chunk_id for chunk_id, count in Counter(ids).items() if count > 1]
    assert not duplicates, f"duplicate chunk_id: {duplicates[:5]}"

    # Front matter has no section number, so it must carry module_id instead or it
    # cannot be cited at all.
    for record in records:
        if not record["section"]:
            assert record["metadata"].get("module_id"), (
                f"{record['chunk_id']} has neither section nor metadata.module_id"
            )
    assert all(record["book_slug"] == SLUG for record in records)


def test_max_words_is_actually_enforced(server, output_root: Path) -> None:
    """Regression: chunks above the ceiling used to ship (max 1018 against a 600 limit)."""
    path = output_root / "book.jsonl"
    if not path.exists():
        call(server, "prepare_textbook", {"target": SLUG, "out": "book.jsonl"})

    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    over = [record for record in records if record["word_count"] > 600]
    assert not over, f"{len(over)} chunks exceed max_words=600: " + ", ".join(
        f"{record['chunk_id']}={record['word_count']}w" for record in over[:5]
    )


def test_validation_summary_is_clean(server, output_root: Path) -> None:
    path = output_root / "book.jsonl"
    if not path.exists():
        call(server, "prepare_textbook", {"target": SLUG, "out": "book.jsonl"})

    counts = summarize_problems(validate_chunks(TextBookDataset.from_jsonl(path).chunks))
    # Sectionless front matter is expected; anything structural is not.
    assert set(counts) <= {"missing_section"}, counts


def test_section_resource_matches_the_exported_records(server, output_root: Path) -> None:
    inspected = call(server, "inspect_textbook", {"target": SLUG})
    section = inspected["sections"][0]["section"]

    contents = asyncio.run(server.read_resource(f"textbook://{SLUG}/{section}"))
    payload = json.loads("".join(item.content for item in contents))

    assert payload["section"] == section
    assert len(payload["chunks"]) == inspected["sections"][0]["chunks"]

    path = output_root / "book.jsonl"
    exported = {
        json.loads(line)["chunk_id"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["section"] == section
    }
    assert {chunk["chunk_id"] for chunk in payload["chunks"]} == exported
