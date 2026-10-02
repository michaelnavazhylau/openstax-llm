"""Dataset builder extracting and indexing OpenStax textbooks for LLMs."""

from __future__ import annotations

import dataclasses
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
        out_dir: Path | str | None = None,
        quiet: bool = False,
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
        out_dir : Path | str, optional
            Scratch directory the builder resolves relative media and module links
            against. Nothing is written here unless media is requested; the default
            keeps the historical ``.scratch_build`` location.
        quiet : bool, default False
            Suppress the upstream compiler's progress output. Set this whenever stdout
            carries protocol data rather than a terminal, such as under an MCP stdio
            transport.
        """
        c = chunker or DocumentChunker()
        bundle = osm.Bundle.discover(source, quiet=quiet)

        col_slug = bundle.default_collection or (
            bundle.collections[0].slug if bundle.collections else bundle.root.name
        )
        col_title = bundle.book_titles.get(col_slug, col_slug)

        scratch = Path(out_dir) if out_dir is not None else Path(".scratch_build")
        builder = osm.Builder(
            bundle,
            out_dir=scratch,
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
                # Several modules have no section number (prefaces, formula tables,
                # chapter introductions). The module id is what keeps their chunk ids
                # unique, and it is also the only way to tell six different
                # 'Introduction' modules apart.
                document_id=module.id,
                metadata={"module_id": module.id},
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

    @classmethod
    def from_jsonl(cls, path: Path | str) -> TextBookDataset:
        """Load a dataset previously written by :meth:`to_jsonl`.

        Unknown fields are ignored so a dataset stamped with extra metadata by a
        downstream tool still loads. Book identity comes from the first record.
        """
        known = {f.name for f in dataclasses.fields(PedagogicalChunk)}
        chunks: list[PedagogicalChunk] = []

        with open(Path(path), encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{number} is not valid JSON: {exc}") from exc
                chunks.append(PedagogicalChunk(**{k: v for k, v in record.items() if k in known}))

        if not chunks:
            raise ValueError(f"{path} contains no chunk records")

        return cls(
            book_slug=chunks[0].book_slug,
            book_title=chunks[0].book_title,
            chunks=chunks,
            metadata={"source": str(path)},
        )

    def by_section(self) -> dict[str, list[PedagogicalChunk]]:
        """Group chunks by section number, preserving encounter order."""
        grouped: dict[str, list[PedagogicalChunk]] = {}
        for chunk in self.chunks:
            grouped.setdefault(chunk.section, []).append(chunk)
        return grouped

    def section_index(self) -> list[dict[str, Any]]:
        """Summarize every section with its title and chunk count."""
        return [
            {
                "section": section,
                "section_title": defs[0].section_title,
                "chapter": defs[0].chapter,
                "chunks": len(defs),
                "words": sum(c.word_count for c in defs),
            }
            for section, defs in self.by_section().items()
        ]

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
