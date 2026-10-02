from __future__ import annotations

import json
from pathlib import Path

from openstax_llm.chunker import PedagogicalChunk
from openstax_llm.dataset import TextBookDataset


def test_dataset_jsonl_export(tmp_path: Path) -> None:
    chunks = [
        PedagogicalChunk(
            chunk_id="chunk-001",
            text="First chunk of text about calculus.",
            book_slug="calculus-volume-1",
            book_title="Calculus Volume 1",
            section="1.1",
            section_title="Functions",
            word_count=6,
            token_est=8,
        ),
        PedagogicalChunk(
            chunk_id="chunk-002",
            text="Second chunk containing an example.",
            book_slug="calculus-volume-1",
            book_title="Calculus Volume 1",
            section="1.1",
            section_title="Functions",
            chunk_type="example",
            word_count=5,
            token_est=6,
        ),
    ]
    ds = TextBookDataset(
        book_slug="calculus-volume-1",
        book_title="Calculus Volume 1",
        chunks=chunks,
    )
    assert ds.total_words == 11
    assert ds.total_tokens_est == 14

    out_file = tmp_path / "dataset.jsonl"
    ds.to_jsonl(out_file)
    assert out_file.is_file()

    lines = [json.loads(line) for line in out_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["chunk_id"] == "chunk-001"
    assert lines[1]["chunk_type"] == "example"

    records = ds.to_records()
    assert len(records) == 2
    assert records[0]["word_count"] == 6

    summary = ds.summary()
    assert summary["total_chunks"] == 2
    assert summary["chunk_types"]["example"] == 1
