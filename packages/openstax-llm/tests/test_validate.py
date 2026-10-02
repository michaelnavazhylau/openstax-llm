"""Tests for the structural validator.

The delimiter checks are the interesting ones: a naive `$` count is wrong in three
different ways, and each of those ways produced a false positive during development, so
each has a regression test here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstax_llm.chunker import DocumentChunker, PedagogicalChunk
from openstax_llm.dataset import TextBookDataset
from openstax_llm.validate import (
    errors_only,
    find_delimiter_imbalance,
    summarize_problems,
    validate_chunks,
)


def chunk(chunk_id: str, text: str, section: str = "1.1") -> PedagogicalChunk:
    return PedagogicalChunk(
        chunk_id=chunk_id,
        text=text,
        book_slug="calculus-volume-1",
        book_title="Calculus Volume 1",
        section=section,
    )


# ------------------------------------------------------------------- delimiter scanner


@pytest.mark.parametrize(
    "text",
    [
        "Plain prose with no math at all.",
        "Inline $f(x)=x^2$ math.",
        "Two inline $a$ and $b$ delimiters.",
        "$$\nm=\\frac{m_0}{\\sqrt{1-\\frac{v^2}{c^2}}}\n$$",
        "Display $$x$$ and inline $y$ together.",
        # Regression: escaped currency is not a math delimiter. A naive parity check
        # reports every one of these as a split formula.
        "The cost was \\$962.50, \\$1090, and \\$1217.50 in total.",
        "Converted an extra \\$200 when she arrived.",
        # Regression: inside a fence, dollars are prose.
        '```\nprice = f"${amount}"\n```',
        "A fenced block may hide an unpaired dollar from the scanner:\n```\n1 $ 2\n```\n",
    ],
    ids=[
        "no-math",
        "inline-pair",
        "two-inline",
        "display-block",
        "mixed",
        "escaped-currency-list",
        "escaped-currency-prose",
        "fence-with-dollar-sign",
        "fence-hides-imbalance",
    ],
)
def test_balanced_text_reports_no_problem(text: str) -> None:
    assert find_delimiter_imbalance(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\n$$\nm = \\frac{a}{b}\n", "unclosed display math"),
        ("Prose with $x^2 but no closer.", "unclosed inline math"),
        ("```\nunclosed fence\n", "unclosed code fence"),
    ],
)
def test_unbalanced_text_is_reported(text: str, expected: str) -> None:
    reason = find_delimiter_imbalance(text)
    assert reason is not None
    assert expected in reason


def test_naive_dollar_counting_would_have_disagreed() -> None:
    """Documents why the scanner exists, not just that it works."""
    text = "The cost was \\$962.50, \\$1090, and \\$1217.50."
    assert text.count("$") % 2 != 0, "this is the false positive being guarded against"
    assert find_delimiter_imbalance(text) is None


# ---------------------------------------------------------------------- chunk checks


def test_clean_chunks_produce_no_problems() -> None:
    assert validate_chunks([chunk("1.1-c001", "Pair $x$ and $$y$$.")]) == []


def test_split_formula_is_an_error() -> None:
    problems = validate_chunks([chunk("1.1-c001", "Starts $x^2 and never closes.")])
    assert [p.kind for p in problems] == ["unclosed_math"]
    assert problems[0].severity == "error"
    assert "1.1-c001" in str(problems[0])


def test_duplicate_chunk_id_is_an_error() -> None:
    problems = validate_chunks(
        [chunk("1.1-c001", "First."), chunk("1.1-c001", "Second, different content.")]
    )
    assert [p.kind for p in problems] == ["duplicate_id"]
    assert problems[0].severity == "error"


def test_missing_section_is_only_a_warning() -> None:
    """Front matter legitimately has no section number."""
    problems = validate_chunks([chunk("m1234-c001", "Preface content.", section="")])
    assert [p.kind for p in problems] == ["missing_section"]
    assert problems[0].severity == "warning"
    assert errors_only(problems) == []


def test_summarize_counts_by_kind() -> None:
    problems = validate_chunks(
        [
            chunk("1.1-c001", "Open $x"),
            chunk("1.1-c001", "Closed $x$."),
            chunk("m1-c001", "Front matter.", section=""),
        ]
    )
    assert summarize_problems(problems) == {
        "unclosed_math": 1,
        "duplicate_id": 1,
        "missing_section": 1,
    }


# ------------------------------------------------------------------- id uniqueness fix


def test_sectionless_modules_get_distinct_chunk_ids() -> None:
    """Regression: the id fallback used to be `chunk-<n>` for *every* module.

    Ten modules without a section number each emitted `chunk-001`, which is a collision
    when `chunk_id` is a vector-database primary key.
    """
    chunker = DocumentChunker()
    markdown = "# Introduction\n\n" + ("Sentence about limits. " * 40)

    ids = [
        c.chunk_id
        for module_id in ("m1001", "m1002", "m1003")
        for c in chunker.chunk_markdown(markdown, document_id=module_id, section_title="Intro")
    ]
    assert len(ids) == len(set(ids)), f"colliding ids: {ids}"


def test_section_wins_over_document_id() -> None:
    chunks = DocumentChunker().chunk_markdown(
        "## Functions\n\n" + ("Content sentence. " * 20),
        section="1.2",
        document_id="m53224",
    )
    assert chunks[0].chunk_id.startswith("1.2-c")


def test_document_id_prefixes_ids_when_section_is_absent() -> None:
    chunks = DocumentChunker().chunk_markdown(
        "# Preface\n\n" + ("Content sentence. " * 20), document_id="m53224"
    )
    assert chunks[0].chunk_id.startswith("m53224-c")


def test_bare_chunk_ids_still_work_for_standalone_markdown() -> None:
    chunks = DocumentChunker().chunk_markdown("# Notes\n\n" + ("Content sentence. " * 20))
    assert chunks[0].chunk_id.startswith("chunk-c")


def test_metadata_is_copied_per_chunk_not_shared() -> None:
    """A shared dict would let a caller mutate every chunk in one assignment."""
    # Long enough to be split into multiple chunks, so the copy is actually observable.
    chunks = DocumentChunker(max_words=100).chunk_markdown(
        "# Preface\n\n" + ("Content sentence here. " * 200),
        document_id="m1",
        metadata={"module_id": "m1"},
    )
    assert len(chunks) >= 2, "test needs a document that splits into several chunks"
    assert chunks[0].metadata == {"module_id": "m1"}
    chunks[0].metadata["touched"] = True
    assert all(c.metadata == {"module_id": "m1"} for c in chunks[1:])


# ------------------------------------------------------------------------ JSONL loader


def test_from_jsonl_round_trips(tmp_path: Path) -> None:
    original = TextBookDataset(
        book_slug="calculus-volume-1",
        book_title="Calculus Volume 1",
        chunks=[
            chunk("1.1-c001", "Pair $x$ and $y$."),
            chunk("1.1-c002", "A worked example.", section="1.1"),
        ],
    )
    path = tmp_path / "book.jsonl"
    original.to_jsonl(path)

    loaded = TextBookDataset.from_jsonl(path)
    assert loaded.book_slug == original.book_slug
    assert loaded.book_title == original.book_title
    assert loaded.to_records() == original.to_records()


def test_from_jsonl_ignores_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "book.jsonl"
    path.write_text(
        '{"chunk_id": "1.1-c001", "text": "Hi $x$.", "section": "1.1", "custom": 42}\n',
        encoding="utf-8",
    )
    loaded = TextBookDataset.from_jsonl(path)
    assert loaded.chunks[0].chunk_id == "1.1-c001"


def test_from_jsonl_rejects_empty_and_malformed_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no chunk records"):
        TextBookDataset.from_jsonl(empty)

    malformed = tmp_path / "bad.jsonl"
    malformed.write_text('{"chunk_id": "a",\n', encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        TextBookDataset.from_jsonl(malformed)
