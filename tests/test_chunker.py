from __future__ import annotations

from openstax_llm.chunker import DocumentChunker


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
