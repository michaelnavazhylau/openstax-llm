# openstax-llm 🧠📚

[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://python.org)
[![PyPI](https://img.shields.io/pypi/v/openstax-llm)](https://pypi.org/project/openstax-llm/)
[![PyPI - MCP](https://img.shields.io/pypi/v/openstax-llm-mcp?label=openstax-llm-mcp)](https://pypi.org/project/openstax-llm-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Powered by openstax-md](https://img.shields.io/badge/compiler-openstax--md-purple)](https://github.com/michaelnavazhylau/openstax-md)
[![skills.sh](https://skills.sh/b/michaelnavazhylau/openstax-llm)](https://skills.sh/michaelnavazhylau/openstax-llm)

**Pedagogical semantic chunking, RAG dataset preparation, and LLM fine-tuning pipelines from OpenStax textbooks.**

Built on top of [`openstax-md`](https://github.com/michaelnavazhylau/openstax-md), `openstax-llm`
transforms OpenStax college textbooks into structured, citation-aware, formula-safe datasets
for vector search (RAG) and model fine-tuning.

This repository ships three things that share one core:

| Artifact | What it is | Entry point |
|---|---|---|
| [`openstax-llm`](packages/openstax-llm) | Python library and CLI | `openstax-llm` |
| [`openstax-llm-mcp`](packages/openstax-llm-mcp) | Model Context Protocol server | `openstax-llm-mcp` |
| [`skills/openstax-llm`](skills/openstax-llm) | Agent skill for coding assistants | `/skill:openstax-llm` |

---

## ⚡ Why openstax-llm?

Generic chunkers (simple character or recursive token splitters) break down on technical
academic textbooks:

- They cut mathematical formulas in half (`$x^2 + \dots$` split from `\dots + y^2$`).
- They separate worked examples from their solutions.
- They lose the chapter and section hierarchy that citations depend on.

`openstax-llm` provides:

1. **Pedagogical boundary awareness** — worked examples (`Example 1.1`), problem sets,
   definitions, and summaries are kept whole.
2. **Formula integrity** — a chunk boundary is never placed inside an unclosed `$...$` or
   `$$...$$` block, or inside a fenced code block.
3. **Enforced size ceiling** — `max_words` is actually honoured; oversized paragraphs are
   split at sentence boundaries that lie outside math.
4. **On-demand compilation** — any textbook in the OpenStax catalog (90 volumes and
   counting) is pulled and chunked without manual data management.
5. **Vector-store-ready output** — JSONL with globally unique `chunk_id`s, compatible with
   Chroma, Qdrant, Pinecone, LanceDB, LlamaIndex, LangChain, and Hugging Face `datasets`.

---

## 🚀 Installation

```bash
# Library + CLI
uv add openstax-llm

# CLI as a standalone tool
uv tool install openstax-llm

# MCP server, one-shot via uvx
uvx openstax-llm-mcp
```

Or run the container:

```bash
docker build -t openstax-llm-mcp .
```

To track an unreleased commit instead, install from git:

```bash
uv add "git+https://github.com/michaelnavazhylau/openstax-llm.git#subdirectory=packages/openstax-llm"
uvx --from "git+https://github.com/michaelnavazhylau/openstax-llm.git#subdirectory=packages/openstax-llm-mcp" openstax-llm-mcp
```

---

## 💻 CLI usage

```bash
# Search the catalog for available textbooks
openstax-llm search physics

# Inspect a textbook's chunk statistics and section index
openstax-llm info astronomy-2e

# Compile and chunk a textbook into a JSONL dataset
openstax-llm prepare astronomy-2e -o datasets/astronomy-2e.jsonl

# Verify an export before using it downstream
openstax-llm validate datasets/astronomy-2e.jsonl
```

`validate` checks formula integrity, `chunk_id` uniqueness, and provenance, and exits
non-zero on structural errors. Add `--strict` to also fail on warnings such as front matter
that has no section number. Always run it before loading a dataset into an index: a split
formula that reaches an embedding store is very hard to detect afterwards.

---

## 🐍 Library usage

```python
from openstax_llm import DocumentChunker, TextBookDataset

chunker = DocumentChunker(target_words=400, max_words=600, overlap_words=50)
dataset = TextBookDataset.from_textbook("calculus-volume-1", chunker=chunker)
dataset.to_jsonl("calculus.jsonl")

print(dataset.summary())
# {'book_slug': 'calculus-volume-1', 'total_chunks': 1445, 'total_words': 262184, ...}
```

`DocumentChunker` also works on arbitrary markdown:

```python
from openstax_llm import DocumentChunker

chunks = DocumentChunker().chunk_markdown(
    "## 1.2 Functions\n\nAn inline formula $f(x)=x^2$ stays intact.\n",
    book_slug="my-notes",
    section="1.2",
    section_title="Functions",
)
```

---

## 🤖 MCP server

Exposes the same three operations to any MCP client over stdio or streamable HTTP.

```bash
# Register with Pi
pi mcp add openstax-llm -- uvx openstax-llm-mcp

# Or serve over HTTP
docker run --rm -p 8765:8765 openstax-llm-mcp
```

| Tool | Purpose |
|---|---|
| `search_catalog(query, limit)` | Resolve a subject to a canonical slug (offline) |
| `inspect_textbook(target)` | Chunk totals plus a per-section index |
| `prepare_textbook(target, out)` | Export JSONL, sandboxed to the server's output directory |

Resources: `textbook://<slug>` for an overview and `textbook://<slug>/<section>` for every
chunk in one section. See [`packages/openstax-llm-mcp/README.md`](packages/openstax-llm-mcp/README.md)
for options, tool schemas, and failure modes.

---

## 🧩 Agent skill

```bash
npx skills add michaelnavazhylau/openstax-llm
```

Also on [skills.sh](https://skills.sh/michaelnavazhylau/openstax-llm) — that directory is populated
from anonymous install telemetry, so the listing appears only after the first
`npx skills add` (the command above is always the canonical path).

The skill teaches an agent *when* and *how* to reach for these tools: resolving slugs
instead of guessing titles, verifying exports before indexing, tuning chunk sizes, and
loading the result into Chroma, Qdrant, Pinecone, or Hugging Face. It deliberately contains
no chunking logic of its own.

---

## 📦 Chunk schema

| Field | Type | Description |
|---|---|---|
| `chunk_id` | `string` | Unique within a book: `<section>-c<index>`, e.g. `1.2-c003` |
| `text` | `string` | Markdown with intact LaTeX math |
| `book_slug` | `string` | Canonical OpenStax slug |
| `book_title` | `string` | Human-readable title |
| `chapter` | `string` | Chapter number from the section hierarchy |
| `section` | `string` | Section number, e.g. `1.2` |
| `section_title` | `string` | Module title |
| `chunk_type` | `string` | `prose`, `example`, `exercise`, `definition`, `summary` |
| `word_count` | `integer` | Whitespace-delimited word count |
| `token_est` | `integer` | Heuristic estimate, `words * 1.3` |
| `metadata` | `object` | Carries `module_id`; free for downstream use |

Front matter — prefaces, formula tables, chapter introductions — has no section number. Its
`chunk_id` is prefixed with the module id and its provenance lives in `metadata.module_id`.
The machine-readable schema is at
[`skills/openstax-llm/assets/chunk.schema.json`](skills/openstax-llm/assets/chunk.schema.json).

---

## 🛠️ Development

```bash
uv sync --all-groups --all-packages

uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy

# Real-textbook integration tests (clones a book, needs network)
OPENSTAX_LLM_NETWORK_TESTS=1 uv run pytest tests/test_integration.py -v
```

The repository is a uv workspace: the root `pyproject.toml` declares members and owns the
shared tool configuration, while each package under `packages/` is independently
distributable. See [AGENTS.md](AGENTS.md) for the architecture and engineering invariants,
and [docs/PUBLISHING.md](docs/PUBLISHING.md) for the release process.

---

## 📄 License

MIT
