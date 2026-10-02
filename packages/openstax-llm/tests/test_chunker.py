from __future__ import annotations

import pytest

from openstax_llm.chunker import DocumentChunker
from openstax_llm.validate import find_delimiter_imbalance


def test_chunker_basic() -> None:
    chunker = DocumentChunker(target_words=50, max_words=100, min_words=10)
    sample_text = """
# Chapter 1: Introduction to Functions

Functions are fundamental in calculus. They describe relationships between variables.

## 1.1 Definition

A function is a rule that assigns each element in a set to exactly one element in another set.

**Example 1.1 Finding the Domain**
Consider $f(x) = \\sqrt{x - 2}$. The domain is all $x \\ge 2$.
Solution: Since the square root requires non-negative arguments, we require $x - 2 \\ge 0$.
"""
    chunks = chunker.chunk_markdown(
        sample_text,
        book_slug="calculus-volume-1",
        book_title="Calculus Volume 1",
        section="1.1",
        section_title="Definition",
    )
    assert len(chunks) >= 1
    assert any(c.chunk_type == "example" for c in chunks)
    for c in chunks:
        assert c.book_slug == "calculus-volume-1"
        assert c.section == "1.1"
        assert c.word_count > 0
        assert c.token_est >= c.word_count


def test_chunker_strips_yaml_frontmatter() -> None:
    chunker = DocumentChunker()
    text = """---
title: Test Page
uuid: 12345
---

# Real Content
This is the real prose.
"""
    chunks = chunker.chunk_markdown(text)
    assert len(chunks) == 1
    assert "uuid: 12345" not in chunks[0].text
    assert "Real Content" in chunks[0].text


# ------------------------------------------------------------------ max_words ceiling


def long_paragraph(sentences: int, sentence: str = "The limit describes a value.") -> str:
    """One markdown paragraph (a single line) made of many sentences."""
    return " ".join([sentence] * sentences)


def test_single_long_paragraph_is_split_up_to_the_ceiling() -> None:
    """A paragraph is one line, so it offers no blank-line boundary to split at.

    Regression: such a paragraph used to be emitted whole, producing chunks far above
    ``max_words`` (1018 words against a documented ceiling of 600 in a real book).
    """
    chunker = DocumentChunker(target_words=100, max_words=200, min_words=10)
    chunks = chunker.chunk_markdown(long_paragraph(120), section="1.1")

    assert len(chunks) > 1, "an oversized paragraph must not be emitted as one chunk"
    assert max(c.word_count for c in chunks) <= 200
    # Nothing was dropped or duplicated in the regrouping.
    assert sum(c.word_count for c in chunks) == len(long_paragraph(120).split())


def test_overlap_never_pushes_a_chunk_over_the_ceiling() -> None:
    """Regression: overlap was prepended after the flush check and never re-checked.

    A chunk could therefore start above ``max_words`` and be emitted that way.
    """
    chunker = DocumentChunker(target_words=100, max_words=200, min_words=10, overlap_words=50)
    # Two blocks that each fit, but whose sum exceeds the ceiling.
    text = f"{long_paragraph(30)}\n\n{long_paragraph(30)}\n\n{long_paragraph(30)}"
    chunks = chunker.chunk_markdown(text, section="1.1")

    assert max(c.word_count for c in chunks) <= 200, [c.word_count for c in chunks]


def test_overlap_is_still_applied_when_it_fits() -> None:
    """The ceiling fix must not silently disable overlap altogether."""
    chunker = DocumentChunker(target_words=100, max_words=400, min_words=10, overlap_words=50)
    text = f"{long_paragraph(30)}\n\n{long_paragraph(30)}\n\n{long_paragraph(30)}"
    chunks = chunker.chunk_markdown(text, section="1.1")

    assert len(chunks) >= 2
    # The tail of one chunk reappears at the head of the next.
    tail = chunks[0].text.split(". ")[-2]
    assert tail.split()[0] in chunks[1].text
    assert max(c.word_count for c in chunks) <= 400


def test_sentence_splitting_never_cuts_inside_math() -> None:
    """The whole point of the chunker: a ceiling must not be paid for with split math."""
    chunker = DocumentChunker(target_words=60, max_words=120, min_words=10)
    sentence = "We compute $f(x)=\\frac{x^{2}+1}{x-3}$ and then $$g(x)=x^{2}$$ to compare."
    text = " ".join([sentence] * 60)

    chunks = chunker.chunk_markdown(text, section="1.1")
    assert max(c.word_count for c in chunks) <= 120
    for chunk in chunks:
        assert find_delimiter_imbalance(chunk.text) is None, chunk.chunk_id


def test_display_math_block_is_not_split_across_chunks() -> None:
    chunker = DocumentChunker(target_words=40, max_words=80, min_words=5)
    text = (
        "Intro sentence about a derivation. " * 5
        + "\n\n$$\n"
        + "\n".join(f"a_{{{i}}} &= b_{{{i}}} + c_{{{i}}} \\\\\\" for i in range(30))
        + "\n$$\n\n"
        + "Closing sentence about the result. " * 5
    )
    chunks = chunker.chunk_markdown(text, section="2.1")
    for chunk in chunks:
        assert find_delimiter_imbalance(chunk.text) is None, chunk.chunk_id


def test_fenced_code_block_is_not_split_across_chunks() -> None:
    chunker = DocumentChunker(target_words=40, max_words=80, min_words=5)
    text = (
        "Lead in. " * 20
        + "\n\n```python\n"
        + "\n".join(f"value_{i} = {i}  # $ dollar sign and unpaired $" for i in range(30))
        + "\n```\n\n"
        + "Lead out. " * 20
    )
    chunks = chunker.chunk_markdown(text, section="2.2")
    for chunk in chunks:
        assert "```" not in chunk.text or chunk.text.count("```") % 2 == 0, chunk.chunk_id


@pytest.mark.parametrize("max_words", [80, 200, 600])
@pytest.mark.parametrize("overlap", [0, 50, 150])
def test_ceiling_is_respected_across_configurations(max_words: int, overlap: int) -> None:
    chunker = DocumentChunker(
        target_words=max(10, max_words // 2),
        max_words=max_words,
        min_words=5,
        overlap_words=overlap,
    )
    text = "\n\n".join(long_paragraph(25) for _ in range(12))
    chunks = chunker.chunk_markdown(text, section="3.1")
    assert max(c.word_count for c in chunks) <= max_words
