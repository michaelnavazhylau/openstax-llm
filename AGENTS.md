# AGENTS.md — Developer & Agent Directives for openstax-llm

Welcome to **openstax-llm**. This document serves as the operational handbook, architectural guide, and engineering standard for AI agents and human contributors working within this codebase.

---

## 1. Project Identity & Purpose

**openstax-llm** is a specialized framework for **pedagogical semantic chunking, RAG dataset preparation, and LLM fine-tuning data curation** built on top of OpenStax college textbooks.

### Core Objectives
1. **Pedagogical Structure Awareness**: Traditional chunking tools split text blindly by token or character count. `openstax-llm` chunks along pedagogical units: preserving worked examples with their step-by-step solutions, definitions with their terms, and problem sets with their exercise numbering.
2. **Mathematical Formula Safety**: Inline math (`$...$`) and multiline display equations (`$$...$$`) must never be sliced across chunk boundaries.
3. **Citation & Provenance Tracking**: Every chunk retains strict metadata linking back to its source textbook (`book_slug`), title, chapter, section number (e.g. `1.2`), and pedagogical category.
4. **Frictionless On-Demand Compilation**: Deeply integrated with [`openstax-md`](https://github.com/michaelnavazhylau/openstax-md) so any textbook in the 89-volume catalog can be pulled and chunked on-the-fly without manual data management.

---

## 2. Invariants & Engineering Directives (Non-Negotiable)

When authoring or modifying code in this repository, you **MUST** adhere to the following invariants:

### Rule 1: Mathematical Formula Integrity
- Mathematical expressions in OpenStax Markdown are delimited with LaTeX `$...$` (inline) and `$$...$$` (display).
- **In-flight check**: A chunk boundary must **never** be placed inside an unclosed `$` or `$$` block. The parser must track delimiter parity and postpone splits until equations close.

### Rule 2: Pedagogical Block Preservation
- Blocks starting with `**Example X.Y**` or containing `Solution:` represent cohesive learning units. They must be kept together whenever their word count falls within `max_words`.
- Admonitions (Notes, Warnings, Chemistry/Biology feature boxes) should not be orphaned from their immediate context.

### Rule 3: Strict Static Typing & Code Standards
- All code must pass strict static type analysis (`uv run mypy src`).
- All code must pass linting and formatting with zero warnings (`uv run ruff check .` and `uv run ruff format --check .`).
- Line length limit is **100 characters**.

### Rule 4: Test Coverage & Regression Prevention
- Every new chunker feature, dataset export format, or CLI argument must have corresponding unit tests in `tests/`.
- All tests must pass cleanly under `uv run pytest -v`.

---

## 3. Architecture & Code Layout

```
openstax-llm/
├── .github/workflows/ci.yml # Multi-version CI matrix (Python 3.10 - 3.14)
├── pyproject.toml           # Project metadata and direct dependency on openstax-md
├── src/
│   └── openstax_llm/
│       ├── __init__.py      # Public exports: DocumentChunker, PedagogicalChunk, TextBookDataset
│       ├── __main__.py      # Package execution entry point
│       ├── chunker.py       # Structure-aware tokenizer and semantic chunker
│       ├── dataset.py       # Textbook ingestion, chunk indexing, JSONL export
│       ├── cli.py           # Command-line frontend: prepare, info, search
│       └── py.typed         # PEP 561 typing marker
└── tests/
    ├── test_chunker.py      # Semantic chunking, formula safety, and boundary tests
    ├── test_dataset.py      # Dataset loading, records, and JSONL export tests
    └── test_cli.py          # CLI subcommands and error handling tests
```

---

## 4. Key Workflows & Commands

All development tasks are managed via [Astral uv](https://docs.astral.sh/uv/):

```bash
# Install dependencies into local .venv
uv sync

# Run tests
uv run pytest -v

# Run linting and formatting checks
uv run ruff check .
uv run ruff format --check .

# Run strict type checking
uv run mypy src

# Build package distributions (wheel and sdist)
uv build
```

---

## 5. Chunk Schema Specification

All RAG datasets exported via `to_jsonl()` conform to this JSON schema:

| Field | Type | Description |
|---|---|---|
| `chunk_id` | `string` | Unique identifier formatted as `<section>-c<index>` (e.g. `1.2-c003`) |
| `text` | `string` | Markdown text with intact LaTeX math formulas |
| `book_slug` | `string` | Canonical OpenStax slug (e.g. `calculus-volume-1`) |
| `book_title` | `string` | Full human-readable textbook title |
| `chapter` | `string` | Chapter number extracted from section hierarchy |
| `section` | `string` | Section number (e.g. `1.2`) |
| `section_title` | `string` | Human-readable title of the module |
| `chunk_type` | `string` | Pedagogical role: `prose`, `example`, `exercise`, `definition`, `summary` |
| `word_count` | `integer` | Count of whitespace-delimited words |
| `token_est` | `integer` | Heuristic token count estimate (typically `words * 1.3`) |
| `metadata` | `object` | Extensible key-value metadata for downstream vector indexes |
