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
- All code must pass strict static type analysis (`uv run mypy`).
- All code must pass linting and formatting with zero warnings (`uv run ruff check .` and `uv run ruff format --check .`).
- Line length limit is **100 characters**.

### Rule 4: Test Coverage & Regression Prevention
- Every new chunker feature, dataset export format, or CLI argument must have corresponding unit tests in the owning package's `tests/` directory.
- All tests must pass cleanly under `uv run pytest -v`.
- Changes with observable output must be verified against a **real textbook**, not only synthetic fixtures. Run `OPENSTAX_LLM_NETWORK_TESTS=1 uv run pytest tests/test_integration.py` for anything touching chunk boundaries, ids, or metadata. Three separate defects in this project were invisible to unit tests and obvious against a real book.

### Rule 5: PyPI Metadata Safety
- **No workspace member other than `openstax-llm` may declare a PEP 508 direct URL dependency.** PyPI rejects such uploads server-side with a 400, and `twine check` does not detect it.
- `scripts/check_wheel_metadata.py` enforces this in CI and in the release workflow. `tests/test_skill_contract.py` asserts the exact set of permitted direct dependencies, so adding one is a deliberate, reviewed change.
- `packages/openstax-llm`'s `openstax-md` git dependency is the single known blocker. See `docs/PUBLISHING.md`.

### Rule 6: Schema and Skill Synchronisation
- `skills/openstax-llm/assets/chunk.schema.json` is the published contract for exported records. It must stay in exact agreement with `PedagogicalChunk.to_dict()`.
- The skill and the library are versioned independently once installed (the skill is copied and hashed by the `skills` CLI), so they can drift. `tests/test_skill_contract.py` is the drift detector; it fails on schema, version, reference, or packaging disagreements.
- Never reimplement the delimiter-integrity check outside `openstax_llm/validate.py`. A naive `text.count("$") % 2` reports escaped currency such as `\$962.50` as a split formula.

---

## 3. Architecture & Code Layout

This repository is a **uv workspace** containing two distributable Python packages plus an
agent skill. The root is deliberately not a package (`tool.uv.package = false`); it exists to
declare the workspace, hold one lockfile, and host shared tool configuration. It depends on
both members so that `uv sync` installs them into the shared development environment.

```
openstax-llm/
├── pyproject.toml              # Workspace root: members, dependency-groups, ruff/mypy/pytest
├── uv.lock                     # Single lockfile for both members
├── AGENTS.md  README.md  LICENSE
├── Dockerfile                  # MCP server image; defaults to streamable HTTP on :8765
├── docs/PUBLISHING.md          # Release process and the current PyPI blocker
├── .pi/mcp.json                # Project-scoped MCP server registration (dogfooding)
├── .github/workflows/
│   ├── ci.yml                  # 3.10-3.14 matrix, lint, types, tests, build, two image jobs
│   ├── skills.yml              # Skill contract + `npx skills add . --list` discoverability
│   └── release.yml             # Tag => build => gate => GitHub Release => PyPI
├── scripts/
│   └── check_wheel_metadata.py # Release gate: fails on direct URL dependencies
├── packages/
│   ├── openstax-llm/           # Dist "openstax-llm": library + CLI
│   │   ├── pyproject.toml
│   │   ├── README.md
│   │   ├── src/openstax_llm/
│   │   │   ├── __init__.py     # Public exports
│   │   │   ├── __main__.py     # `python -m openstax_llm`
│   │   │   ├── chunker.py      # DocumentChunker, PedagogicalChunk, math-aware splitting
│   │   │   ├── dataset.py      # TextBookDataset, JSONL export/import, section index
│   │   │   ├── validate.py     # Delimiter integrity + id uniqueness + provenance checks
│   │   │   ├── cli.py          # prepare, info, search, validate
│   │   │   └── py.typed
│   │   └── tests/
│   │       ├── test_chunker.py    # Boundaries, formula safety, max_words ceiling
│   │       ├── test_dataset.py    # Loading, records, JSONL export
│   │       ├── test_cli.py        # Subcommands and error handling
│   │       └── test_validate.py   # Delimiter scanner, id uniqueness, JSONL round trip
│   └── openstax-llm-mcp/       # Dist "openstax-llm-mcp": Model Context Protocol server
│       ├── pyproject.toml      # Depends on openstax-llm and mcp>=2,<3
│       ├── README.md
│       ├── src/openstax_llm_mcp/
│       │   ├── __init__.py  __main__.py  _version.py
│       │   ├── server.py       # MCPServer wiring; stdio default, streamable HTTP optional
│       │   ├── tools.py        # search_catalog, inspect_textbook, prepare_textbook
│       │   ├── resources.py    # textbook://<slug> and textbook://<slug>/<section>
│       │   ├── store.py        # Bounded LRU cache of compiled textbooks
│       │   └── py.typed
│       └── tests/
│           ├── conftest.py  _fakes.py
│           ├── test_server.py     # CLI parsing, registration, cache/LRU behaviour
│           ├── test_tools.py      # Tool contracts, output-path sandboxing
│           └── test_resources.py  # Resource templates and payloads
├── skills/
│   └── openstax-llm/           # Agent skill, discovered by the `skills` CLI
│       ├── SKILL.md            # Routing description + workflow
│       ├── references/         # chunk-schema.md, mcp-tools.md, rag-recipes.md
│       ├── scripts/            # ensure-cli.sh, install-mcp.sh, prepare-textbook.sh
│       └── assets/chunk.schema.json
└── tests/                      # Repo-level tests spanning both packages
    ├── test_skill_contract.py  # Schema/version/reference/packaging agreement
    ├── test_release_tooling.py # Release gate behaviour
    └── test_integration.py     # Real textbook; gated on OPENSTAX_LLM_NETWORK_TESTS=1
```

**Layering.** The skill holds instructions only, the MCP server holds the tool surface, and
`packages/openstax-llm` owns all logic. Neither the skill nor the MCP server may reimplement
chunking, and the skill must never duplicate a check that exists in the library.

**Dependency direction.** `openstax-llm` → `openstax-md`. `openstax-llm-mcp` → `mcp`,
`openstax-llm`. The skill → the CLI or the MCP server. Cycles are not permitted, and
`mcp` must not leak into the core distribution.

---

## 4. Key Workflows & Commands

All development tasks are managed via [Astral uv](https://docs.astral.sh/uv/):

```bash
# Install both workspace members into the shared .venv
uv sync --all-groups --all-packages

# Run tests (network-backed integration tests are skipped unless opted in)
uv run pytest -v
OPENSTAX_LLM_NETWORK_TESTS=1 uv run pytest tests/test_integration.py -v

# Run linting and formatting checks
uv run ruff check .
uv run ruff format --check .

# Run strict type checking (config lives at the root: [tool.mypy] files = [...])
uv run mypy

# Build wheel and sdist for one member, or for all of them
uv build --package openstax-llm --out-dir dist/openstax-llm
uv build --all-packages

# Release gate: fail on PEP 508 direct URL dependencies
python scripts/check_wheel_metadata.py --allow openstax-llm dist/*/*.whl

# Verify the skill is discoverable exactly as a consumer would install it
npx --yes skills add . --list

# Build the MCP server image and smoke-test it
docker build -t openstax-llm-mcp .
docker run --rm -p 8765:8765 openstax-llm-mcp
```

Add a dependency to one member rather than the root: `uv add --package openstax-llm <dep>`.
A root-level dependency would be installed for everyone and is almost never what you want.

---

## 5. Chunk Schema Specification

All RAG datasets exported via `to_jsonl()` conform to this JSON schema:

| Field | Type | Description |
|---|---|---|
| `chunk_id` | `string` | Unique within a book. `<section>-c<index>` (e.g. `1.2-c003`), or `<module_id>-c<index>` for sectionless front matter |
| `text` | `string` | Markdown text with intact LaTeX math formulas |
| `book_slug` | `string` | Canonical OpenStax slug (e.g. `calculus-volume-1`) |
| `book_title` | `string` | Full human-readable textbook title |
| `chapter` | `string` | Chapter number extracted from section hierarchy |
| `section` | `string` | Section number (e.g. `1.2`) |
| `section_title` | `string` | Human-readable title of the module |
| `chunk_type` | `string` | Pedagogical role: `prose`, `example`, `exercise`, `definition`, `summary` |
| `word_count` | `integer` | Count of whitespace-delimited words. Bounded by `max_words` except for a single unbreakable sentence or display-math block |
| `token_est` | `integer` | Heuristic token count estimate (typically `words * 1.3`) |
| `metadata` | `object` | `openstax-llm` writes `module_id`; other keys are free for downstream vector indexes |

A machine-readable copy of this contract ships with the agent skill at
`skills/openstax-llm/assets/chunk.schema.json`, and `tests/test_skill_contract.py` asserts
that the two cannot disagree.
