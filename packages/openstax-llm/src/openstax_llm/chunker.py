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
        document_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> list[PedagogicalChunk]:
        """Split a module/section markdown document into semantic chunks.

        Parameters
        ----------
        markdown : str
            Module markdown, with optional YAML front matter.
        book_slug, book_title, section, section_title : str
            Provenance stamped onto every chunk.
        document_id : str
            Stable identifier for this document. Used as the chunk-id prefix whenever
            ``section`` is empty, which is what keeps ids unique across modules that have
            no section number (prefaces, formula tables, chapter introductions). Without
            it, every such module would emit ``chunk-001`` and collide.
        metadata : dict, optional
            Copied into each chunk's ``metadata`` bag.
        """
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
        # A single place decides the id prefix, so the fallback cannot drift between
        # the four emit sites below.
        prefix = section or document_id or "chunk"

        def next_id() -> str:
            nonlocal chunk_idx
            chunk_id = f"{prefix}-c{chunk_idx:03d}"
            chunk_idx += 1
            return chunk_id

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
                    chunks.append(
                        self._create_chunk(
                            next_id(),
                            "\n\n".join(current_text_blocks),
                            book_slug,
                            book_title,
                            section,
                            section_title,
                            current_type,
                            metadata,
                        )
                    )
                    current_text_blocks = []
                    current_words = 0

                # Add the standalone block
                chunks.append(
                    self._create_chunk(
                        next_id(),
                        b_text,
                        book_slug,
                        book_title,
                        section,
                        section_title,
                        b_type,
                        metadata,
                    )
                )
                continue

            # Standard prose flow accumulation
            if current_words + b_words > self.max_words and current_words >= self.min_words:
                chunks.append(
                    self._create_chunk(
                        next_id(),
                        "\n\n".join(current_text_blocks),
                        book_slug,
                        book_title,
                        section,
                        section_title,
                        current_type,
                        metadata,
                    )
                )

                # Overlap handling. Overlap is a retrieval nicety; the word ceiling is a
                # correctness property, so a carried-over block is dropped when it would
                # not fit alongside the incoming one. Prepending unconditionally would
                # start the new chunk already over `max_words`, and nothing re-checks it
                # afterwards -- which is how chunks above the ceiling used to ship.
                if self.overlap_words > 0 and current_text_blocks:
                    last_block = current_text_blocks[-1]
                    last_words = len(last_block.split())
                    if last_words <= self.max_words - b_words:
                        current_text_blocks = [last_block, b_text]
                        current_words = last_words + b_words
                    else:
                        current_text_blocks = [b_text]
                        current_words = b_words
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
            chunks.append(
                self._create_chunk(
                    next_id(),
                    "\n\n".join(current_text_blocks),
                    book_slug,
                    book_title,
                    section,
                    section_title,
                    current_type,
                    metadata,
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

        return self._enforce_max_words(blocks)

    def _enforce_max_words(self, blocks: list[str]) -> list[str]:
        """Break up blocks that still exceed ``max_words`` after paragraph splitting.

        A markdown paragraph is a single line, so a long one offers no line boundary to
        split at: the paragraph-level pass hands it over whole. Real textbooks contain
        such paragraphs (dense prose around figures), and without this step a single
        paragraph could be emitted as a chunk far above the documented ceiling.
        """
        expanded: list[str] = []
        for block in blocks:
            if len(block.split()) > self.max_words:
                expanded.extend(self._split_oversized_block(block))
            else:
                expanded.append(block)
        return expanded

    def _split_oversized_block(self, block: str) -> list[str]:
        """Greedily regroup an oversized block's sentences up to ``max_words``."""
        units = self._sentence_units(block)
        if len(units) <= 1:
            # Nothing safe to split on: one unterminated run, or a single display-math
            # expression. Returning it intact is better than cutting a formula.
            return [block]

        parts: list[str] = []
        current: list[str] = []
        current_words = 0

        for unit in units:
            unit_words = len(unit.split())
            if current and current_words + unit_words > self.max_words:
                parts.append("".join(current))
                current = [unit]
                current_words = unit_words
            else:
                current.append(unit)
                current_words += unit_words

        if current:
            parts.append("".join(current))
        return parts

    @staticmethod
    def _sentence_units(text: str) -> list[str]:
        """Split ``text`` after sentence terminators that sit outside math and code.

        Delimiter state is tracked with the same rules as
        :func:`openstax_llm.validate.find_delimiter_imbalance`, so a period inside
        ``$f(x)=x^2.$`` or inside a fenced block is never treated as a boundary.
        """
        units: list[str] = []
        start = 0
        index = 0
        length = len(text)
        in_display = False
        in_inline = False
        in_fence = False

        while index < length:
            char = text[index]

            if char == "\\" and index + 1 < length:
                index += 2
                continue
            if text.startswith("```", index):
                in_fence = not in_fence
                index += 3
                continue
            if in_fence:
                index += 1
                continue
            if text.startswith("$$", index) and not in_inline:
                in_display = not in_display
                index += 2
                continue
            if char == "$" and not in_display:
                in_inline = not in_inline
                index += 1
                continue

            if char in ".!?" and not in_display and not in_inline:
                after = index + 1
                while after < length and text[after] in " \t\n":
                    after += 1
                if after > index + 1 and after < length:
                    units.append(text[start:after])
                    start = after
                    index = after
                    continue

            index += 1

        if start < length:
            units.append(text[start:])
        return units

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
        metadata: dict[str, Any] | None = None,
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
            # A fresh dict per chunk: sharing one would let a caller mutate every chunk at once.
            metadata=dict(metadata) if metadata else {},
        )
