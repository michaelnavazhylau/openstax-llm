# openstax-llm

**Pedagogical semantic chunking, RAG dataset preparation, and LLM fine-tuning pipelines from OpenStax textbooks.**

This is the core library and CLI of the [openstax-llm](https://github.com/michaelnavazhylau/openstax-llm)
project. It transforms OpenStax college textbooks into structured, citation-aware, formula-safe
datasets for vector search (RAG) and model fine-tuning.

If you want to drive this from an AI coding agent, see the sibling packages:

| Package | Purpose |
|---|---|
| [`openstax-llm`](..) (this package) | Library + `openstax-llm` CLI |
| [`openstax-llm-mcp`](../../openstax-llm-mcp) | Model Context Protocol server |
| `skills/openstax-llm` | Agent skill with workflows and references |

## Install

```bash
uv add openstax-llm
```

## CLI

```bash
# Search the OpenStax catalog
openstax-llm search physics

# Inspect chunk statistics for a textbook
openstax-llm info astronomy-2e

# Compile and chunk a textbook into a JSONL dataset
openstax-llm prepare astronomy-2e -o datasets/astronomy-2e.jsonl
```

## Library

```python
from openstax_llm import DocumentChunker, TextBookDataset

chunker = DocumentChunker(target_words=400, max_words=600, overlap_words=50)
dataset = TextBookDataset.from_textbook("calculus-volume-1", chunker=chunker)
dataset.to_jsonl("calculus.jsonl")

print(dataset.summary())
```

`DocumentChunker` also works on arbitrary markdown, which is useful for tests and for
non-OpenStax sources:

```python
from openstax_llm import DocumentChunker

chunks = DocumentChunker().chunk_markdown(
    "## 1.2 Functions\n\nAn inline formula $f(x)=x^2$ stays intact.\n",
    book_slug="my-notes",
    section="1.2",
    section_title="Functions",
)
```

## Guarantees

1. **Formula integrity** — a chunk boundary is never placed inside an unclosed `$...$` or `$$...$$` block.
2. **Pedagogical cohesion** — worked examples, definitions, problem sets, and summaries are kept whole whenever they fit within `max_words`.
3. **Provenance** — every chunk carries `book_slug`, `book_title`, `chapter`, `section`, `section_title`, and `chunk_type`.

## Chunk schema

| Field | Type | Description |
|---|---|---|
| `chunk_id` | `string` | `<section>-c<index>`, e.g. `1.2-c003` |
| `text` | `string` | Markdown with intact LaTeX math |
| `book_slug` | `string` | Canonical OpenStax slug |
| `book_title` | `string` | Human-readable title |
| `chapter` | `string` | Chapter number from the section hierarchy |
| `section` | `string` | Section number, e.g. `1.2` |
| `section_title` | `string` | Module title |
| `chunk_type` | `string` | `prose`, `example`, `exercise`, `definition`, `summary` |
| `word_count` | `integer` | Whitespace-delimited word count |
| `token_est` | `integer` | Heuristic estimate, `words * 1.3` |
| `metadata` | `object` | Extensible metadata for downstream indexes |

## Development

This package lives in the `openstax-llm` uv workspace. Run every check from the repository root:

```bash
uv sync
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

## License

MIT
