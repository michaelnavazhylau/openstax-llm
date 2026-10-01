"""Dataset builder extracting and indexing OpenStax textbooks for LLMs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openstax_md as osm

from openstax_llm.chunker import DocumentChunker, PedagogicalChunk


@dataclass
class TextBookDataset:
    """A collection of pedagogical chunks compiled from an OpenStax textbook."""

    book_slug: str
    book_title: str
    chunks: list[PedagogicalChunk] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_textbook(
        cls,
        source: str | Path,
        *,
        chunker: DocumentChunker | None = None,
        math_delimiters: str = "dollar",
    ) -> TextBookDataset:
        """Compile an OpenStax textbook (by catalog slug or path) and chunk it.

        Parameters
        ----------
        source : str | Path
            Textbook slug (e.g. 'astronomy-2e', 'calculus-volume-1') or local bundle path.
        chunker : DocumentChunker, optional
            Configured chunker instance.
        math_delimiters : str, default 'dollar'
            Math delimiter format ('dollar', 'bracket', 'none').
        """
        c = chunker or DocumentChunker()
        bundle = osm.Bundle.discover(source)

        col_slug = bundle.default_collection or (
            bundle.collections[0].slug if bundle.collections else bundle.root.name
        )
        col_title = bundle.book_titles.get(col_slug, col_slug)

        builder = osm.Builder(
            bundle,
            out_dir=Path(".scratch_build"),
            options=osm.RenderOptions(math=math_delimiters, front_matter=False),
            layout="flat",
        )

        all_chunks: list[PedagogicalChunk] = []

        # Find target collection or iterate all
        target_collection = next(
            (c for c in bundle.collections if c.slug == col_slug),
            bundle.collections[0] if bundle.collections else None,
        )

        module_ids = (
            target_collection.module_ids if target_collection else list(bundle.modules.keys())
        )

        for mod_id in module_ids:
            module = bundle.modules.get(mod_id)
            if module is None:
                continue

            md_text = builder.render_module(module, front_matter=False)
            sec_num = bundle.numbering.section_number(mod_id, col_slug)

            module_chunks = c.chunk_markdown(
                md_text,
                book_slug=col_slug,
                book_title=col_title,
                section=sec_num,
                section_title=module.title,
            )
            all_chunks.extend(module_chunks)

        return cls(
            book_slug=col_slug,
            book_title=col_title,
            chunks=all_chunks,
            metadata={
                "source": str(source),
                "total_modules": len(module_ids),
                "math_delimiters": math_delimiters,
            },
        )

    @property
    def total_words(self) -> int:
        return sum(c.word_count for c in self.chunks)

    @property
    def total_tokens_est(self) -> int:
        return sum(c.token_est for c in self.chunks)

    def to_jsonl(self, output_path: Path | str) -> None:
        """Write all chunks as newline-delimited JSON for RAG databases."""
        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for chunk in self.chunks:
                f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")

    def to_records(self) -> list[dict[str, Any]]:
        """Return list of dictionary records compatible with Hugging Face datasets."""
        return [c.to_dict() for c in self.chunks]

    def summary(self) -> dict[str, Any]:
        """Return statistical breakdown of dataset."""
        type_counts: dict[str, int] = {}
        for c in self.chunks:
            type_counts[c.chunk_type] = type_counts.get(c.chunk_type, 0) + 1

        return {
            "book_slug": self.book_slug,
            "book_title": self.book_title,
            "total_chunks": len(self.chunks),
            "total_words": self.total_words,
            "total_tokens_est": self.total_tokens_est,
            "chunk_types": type_counts,
        }


def prepare_textbook(
    source: str | Path,
    output_jsonl: Path | str,
    *,
    target_words: int = 400,
) -> TextBookDataset:
    """Convenience helper to load, chunk, and export an OpenStax textbook to JSONL."""
    chunker = DocumentChunker(target_words=target_words)
    ds = TextBookDataset.from_textbook(source, chunker=chunker)
    ds.to_jsonl(output_jsonl)
    return ds
