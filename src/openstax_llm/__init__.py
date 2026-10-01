"""openstax-llm -- Pedagogical semantic chunking and RAG dataset preparation."""

from __future__ import annotations

from openstax_llm.chunker import DocumentChunker, PedagogicalChunk
from openstax_llm.dataset import TextBookDataset, prepare_textbook

__version__ = "0.1.0"

__all__ = [
    "DocumentChunker",
    "PedagogicalChunk",
    "TextBookDataset",
    "__version__",
    "prepare_textbook",
]
