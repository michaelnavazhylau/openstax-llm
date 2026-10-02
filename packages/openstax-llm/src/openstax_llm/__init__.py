"""openstax-llm -- Pedagogical semantic chunking and RAG dataset preparation."""

from __future__ import annotations

from openstax_llm.chunker import DocumentChunker, PedagogicalChunk
from openstax_llm.dataset import TextBookDataset, prepare_textbook
from openstax_llm.validate import (
    ChunkProblem,
    errors_only,
    find_delimiter_imbalance,
    summarize_problems,
    validate_chunks,
)

__version__ = "0.1.0"

__all__ = [
    "ChunkProblem",
    "DocumentChunker",
    "PedagogicalChunk",
    "TextBookDataset",
    "__version__",
    "errors_only",
    "find_delimiter_imbalance",
    "prepare_textbook",
    "summarize_problems",
    "validate_chunks",
]
