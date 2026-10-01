"""Pedagogical semantic chunker for OpenStax textbooks.

Splits textbook content along structural and pedagogical boundaries
(sections, worked examples, definitions, problem sets) while preserving
mathematical formula integrity.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PedagogicalChunk:
    """A semantic chunk of textbook content with pedagogical metadata."""

    chunk_id: str
    text: str
    book_slug: str = ""
    book_title: str = ""
    chapter: str = ""
    section: str = ""
    section_title: str = ""
    chunk_type: str = "prose"  # prose, example, exercise, definition, summary
    word_count: int = 0
    token_est: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DocumentChunker:
    """Chunks textbook markdown into semantically coherent segments for LLM ingestion."""

    def __init__(
        self,
        target_words: int = 400,
        max_words: int = 600,
        min_words: int = 60,
        overlap_words: int = 50,
    ) -> None:
        self.target_words = target_words
        self.max_words = max_words
        self.min_words = min_words
        self.overlap_words = overlap_words

    def chunk_markdown(
        self,
        markdown: str,
        *,
        book_slug: str = "",
        book_title: str = "",
        section: str = "",
        section_title: str = "",
    ) -> list[PedagogicalChunk]:
        """Split a module/section markdown document into semantic chunks."""
        # Strip YAML front matter if present
        text = markdown
        if text.startswith("---"):
            end_fm = text.find("\n---", 3)
            if end_fm != -1:
                text = text[end_fm + 4 :].strip()

        # Split into high-level blocks based on headings or major delimiters
        blocks = self._split_into_blocks(text)
        chunks: list[PedagogicalChunk] = []
        chunk_idx = 1

        current_text_blocks: list[str] = []
        current_words = 0
        current_type = "prose"

        for block in blocks:
            b_text = block.strip()
            if not b_text:
                continue

            b_words = len(b_text.split())
            b_type = self._detect_chunk_type(b_text)

            # Standalone unit (e.g. Worked Example or Problem Set) that is reasonably sized
            if b_type != "prose" and b_words >= self.min_words:
                # Flush previous prose if pending
                if current_text_blocks:
                    combined = "\n\n".join(current_text_blocks)
                    chunks.append(
                        self._create_chunk(
                            f"{section}-c{chunk_idx:03d}" if section else f"chunk-{chunk_idx:03d}",
                            combined,
                            book_slug,
                            book_title,
                            section,
                            section_title,
                            current_type,
                        )
                    )
                    chunk_idx += 1
                    current_text_blocks = []
                    current_words = 0

                # Add the standalone block
                chunks.append(
                    self._create_chunk(
                        f"{section}-c{chunk_idx:03d}" if section else f"chunk-{chunk_idx:03d}",
                        b_text,
                        book_slug,
                        book_title,
                        section,
                        section_title,
                        b_type,
                    )
                )
                chunk_idx += 1
                continue

            # Standard prose flow accumulation
            if current_words + b_words > self.max_words and current_words >= self.min_words:
                combined = "\n\n".join(current_text_blocks)
                chunks.append(
                    self._create_chunk(
                        f"{section}-c{chunk_idx:03d}" if section else f"chunk-{chunk_idx:03d}",
                        combined,
                        book_slug,
                        book_title,
                        section,
                        section_title,
                        current_type,
                    )
                )
                chunk_idx += 1

                # Overlap handling
                if self.overlap_words > 0 and current_text_blocks:
                    last_block = current_text_blocks[-1]
                    current_text_blocks = [last_block, b_text]
                    current_words = len(last_block.split()) + b_words
                else:
                    current_text_blocks = [b_text]
                    current_words = b_words
                current_type = b_type
            else:
                current_text_blocks.append(b_text)
                current_words += b_words
                if b_type != "prose":
                    current_type = b_type

        # Flush trailing content
        if current_text_blocks:
            combined = "\n\n".join(current_text_blocks)
            chunks.append(
                self._create_chunk(
                    f"{section}-c{chunk_idx:03d}" if section else f"chunk-{chunk_idx:03d}",
                    combined,
                    book_slug,
                    book_title,
                    section,
                    section_title,
                    current_type,
                )
            )

        return chunks

    def _split_into_blocks(self, text: str) -> list[str]:
        """Split text along section headings, display equations, and block boundaries."""
        # Protect math blocks from being split
        # We split primarily on paragraph double newlines or heading boundaries
        lines = text.splitlines()
        blocks: list[str] = []
        cur_lines: list[str] = []
        in_display_math = False
        in_code_block = False

        for line in lines:
            trimmed = line.strip()
            if trimmed.startswith("```"):
                in_code_block = not in_code_block
            elif "$$" in trimmed and trimmed.count("$$") % 2 != 0:
                in_display_math = not in_display_math

            is_heading = trimmed.startswith(("# ", "## ", "### ", "#### "))
            is_example_header = trimmed.startswith(("**Example ", "**Problem ", "**Exercise "))

            if not in_display_math and not in_code_block and (is_heading or is_example_header):
                if cur_lines:
                    blocks.append("\n".join(cur_lines))
                    cur_lines = []

            cur_lines.append(line)

            if not in_display_math and not in_code_block and trimmed == "":
                if cur_lines and len("\n".join(cur_lines).split()) > 100:
                    blocks.append("\n".join(cur_lines))
                    cur_lines = []

        if cur_lines:
            blocks.append("\n".join(cur_lines))

        return blocks

    def _detect_chunk_type(self, text: str) -> str:
        """Categorize pedagogical function of text."""
        lower = text.lower()
        if re.search(r"\bexample\s+\d+", lower) or "solution:" in lower:
            return "example"
        if re.search(r"\b(exercise|problem|review question)s?\b", lower):
            return "exercise"
        if "definition" in lower or "key terms" in lower:
            return "definition"
        if "chapter review" in lower or "summary" in lower:
            return "summary"
        return "prose"

    def _create_chunk(
        self,
        chunk_id: str,
        text: str,
        book_slug: str,
        book_title: str,
        section: str,
        section_title: str,
        chunk_type: str,
    ) -> PedagogicalChunk:
        words = len(text.split())
        # Rule of thumb for technical/math text: ~1.3 tokens per word
        token_est = int(words * 1.3)
        return PedagogicalChunk(
            chunk_id=chunk_id,
            text=text,
            book_slug=book_slug,
            book_title=book_title,
            chapter=section.split(".")[0] if "." in section else "",
            section=section,
            section_title=section_title,
            chunk_type=chunk_type,
            word_count=words,
            token_est=token_est,
        )
