"""In-memory fakes keeping the MCP test suite offline and fast."""

from __future__ import annotations

from openstax_llm.chunker import DocumentChunker, PedagogicalChunk
from openstax_llm.dataset import TextBookDataset
from openstax_llm_mcp.store import TextbookStore

SLUG = "calculus-volume-1"
TITLE = "Calculus Volume 1"


def make_dataset() -> TextBookDataset:
    """Two sections of a fake textbook, including one worked example."""
    chunks = [
        PedagogicalChunk(
            chunk_id="1.1-c001",
            text="A function $f(x)=x^2$ maps reals to reals.",
            book_slug=SLUG,
            book_title=TITLE,
            chapter="1",
            section="1.1",
            section_title="Review of Functions",
            chunk_type="prose",
            word_count=8,
            token_est=10,
        ),
        PedagogicalChunk(
            chunk_id="1.1-c002",
            text="**Example 1.1** Differentiate $x^2$.\n\nSolution: The derivative is $2x$.",
            book_slug=SLUG,
            book_title=TITLE,
            chapter="1",
            section="1.1",
            section_title="Review of Functions",
            chunk_type="example",
            word_count=9,
            token_est=11,
        ),
        PedagogicalChunk(
            chunk_id="1.2-c001",
            text="A limit describes the value a function approaches.",
            book_slug=SLUG,
            book_title=TITLE,
            chapter="1",
            section="1.2",
            section_title="Limits",
            chunk_type="prose",
            word_count=8,
            token_est=10,
        ),
    ]
    return TextBookDataset(book_slug=SLUG, book_title=TITLE, chunks=chunks)


class FakeStore(TextbookStore):
    """Serves one fixed dataset and records the chunker configuration it was asked for."""

    def __init__(self, dataset: TextBookDataset) -> None:
        super().__init__(max_entries=1)
        self.dataset = dataset
        self.requests: list[tuple[str, DocumentChunker]] = []

    def get(self, target: str, *, chunker: DocumentChunker | None = None) -> TextBookDataset:
        self.requests.append((target, chunker or DocumentChunker()))
        return self.dataset
