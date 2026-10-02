# RAG and fine-tuning recipes

How to get a `openstax-llm` JSONL export into downstream tooling. Each recipe assumes the
dataset already exists:

```bash
openstax-llm prepare calculus-volume-1 -o datasets/calculus.jsonl
```

Verify the export before loading it anywhere — see the checklist in `SKILL.md`. A split
formula that reaches an embedding index is very hard to detect later.

## Load and validate

This works with no third-party dependency beyond the standard library, and is worth running
before any downstream import:

```python
import json

records = [json.loads(line) for line in open("datasets/calculus.jsonl", encoding="utf-8")]

for record in records:
    assert record["text"].count("$") % 2 == 0, f"split formula in {record['chunk_id']}"

ids = [r["chunk_id"] for r in records]
assert len(ids) == len(set(ids)), "duplicate chunk_id"

empty = [r["chunk_id"] for r in records if not r["section"]]
assert not empty, f"{len(empty)} chunks lost their section"
```

## Chroma

```python
import json
import chromadb

records = [json.loads(line) for line in open("datasets/calculus.jsonl", encoding="utf-8")]

client = chromadb.PersistentClient(path="./chroma")
collection = client.get_or_create_collection(
    "openstax-calculus",
    metadata={"hnsw:space": "cosine"},
)

collection.add(
    ids=[r["chunk_id"] for r in records],
    documents=[r["text"] for r in records],  # embed the text, not the metadata
    metadatas=[
        {
            "book_slug": r["book_slug"],
            "book_title": r["book_title"],
            "chapter": r["chapter"],
            "section": r["section"],
            "section_title": r["section_title"],
            "chunk_type": r["chunk_type"],
        }
        for r in records
    ],
)
```

Chroma refuses to add the same ID twice. Re-running against an existing collection raises
rather than upserting; use `collection.upsert(...)` for idempotent re-ingestion.

## Qdrant

```python
import json
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

records = [json.loads(line) for line in open("datasets/calculus.jsonl", encoding="utf-8")]

client = QdrantClient(url="http://localhost:6333")
client.recreate_collection(
    collection_name="openstax",
    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
)

client.upsert(
    collection_name="openstax",
    points=[
        PointStruct(
            id=index,
            vector=embed(r["text"]),  # your embedding function
            payload={**r, "text": r["text"]},  # payload keeps citation fields
        )
        for index, r in enumerate(records)
    ],
)
```

Qdrant point IDs must be unsigned integers or UUIDs, so enumerate rather than using
`chunk_id`. Keep `chunk_id` in the payload — you need it to cite results.

## Pinecone

```python
import json
from pinecone import Pinecone, ServerlessSpec

records = [json.loads(line) for line in open("datasets/calculus.jsonl", encoding="utf-8")]

pc = Pinecone(api_key="...")
pc.create_index(
    name="openstax",
    dimension=1536,
    metric="cosine",
    spec=ServerlessSpec(cloud="aws", region="us-east-1"),
)
index = pc.Index("openstax")

index.upsert(
    vectors=[
        {
            "id": r["chunk_id"],
            "values": embed(r["text"]),
            # Pinecone metadata must be flat, and null/empty values are rejected.
            "metadata": {
                "text": r["text"],
                "book_slug": r["book_slug"],
                "section": r["section"] or "unknown",
                "section_title": r["section_title"] or "unknown",
                "chunk_type": r["chunk_type"],
            },
        }
        for r in records
    ],
    namespace="calculus-volume-1",
)
```

Pinecone caps metadata per vector and rejects empty strings, which is why the `or "unknown"`
fallbacks are there. One namespace per book keeps books separable without a filter.

## Hugging Face `datasets`

```python
from datasets import Dataset, load_dataset

dataset = load_dataset("json", data_files="datasets/calculus.jsonl", split="train")
dataset.push_to_hub("your-org/openstax-calculus-chunks")
```

`load_dataset("json", ...)` infers the schema from the first line, so a single malformed
record can silently drop fields for the whole file. Run the validation pass first.

## Fine-tuning formatting

`chunk_type` is what makes a chunk usable as training data. Worked examples give you
problem/solution pairs for free.

```python
import json

records = [json.loads(line) for line in open("datasets/calculus.jsonl", encoding="utf-8")]
examples = [r for r in records if r["chunk_type"] == "example"]

training = [
    {
        "messages": [
            {
                "role": "user",
                "content": f"Solve this problem from {r['book_title']} "
                f"section {r['section']}:\n\n{r['text'].split('Solution:')[0]}",
            },
            {"role": "assistant", "content": r["text"].split("Solution:", 1)[1]},
        ]
    }
    for r in examples
    if "Solution:" in r["text"]
]
```

This split is naive: `"Solution:"` also appears inside some prose, and the prompt may
contain the answer for examples where the statement runs into the solution. Eyeball a
sample before training, and prefer a stricter delimiter when the formatting allows it.

Also consider filtering on length. Very short `prose` chunks make weak training examples;
something like `word_count >= 50` removes most of them.

## Retrieval quality notes

- **One collection per book** keeps slugs filterable and avoids cross-book embedding drift
  when books were compiled at different times.
- **Filter on `chunk_type` when the question is procedural.** "How do I solve...?" is best
  answered from `example` chunks rather than `prose`.
- **Do not re-embed metadata into the document.** Keeping `text` alone as the embedded
  payload consistently retrieves better, since citation fields are near-duplicates across
  chunks.
- **Cite with `book_title` + `section` + `section_title`.** Together those identify a
  location a student can open, which `chunk_id` alone does not.
