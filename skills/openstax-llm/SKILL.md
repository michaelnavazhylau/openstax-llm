---
name: openstax-llm
description: Turn OpenStax college textbooks into citation-aware, formula-safe RAG and fine-tuning datasets. Use when preparing textbook content for vector search, embeddings, or LLM fine-tuning; when text must be chunked along pedagogical boundaries so worked examples stay with their solutions and definitions stay with their terms; when LaTeX math ($...$ and $$...$$) must never be split across chunks; when exporting JSONL chunk datasets from OpenStax books; or when searching the OpenStax catalog and inspecting a book's chunk statistics. Also covers configuring and troubleshooting the openstax-llm MCP server and CLI.
license: MIT
compatibility: Requires Python 3.10+ and either the `openstax-llm` CLI or the `openstax-llm-mcp` MCP server. Compiling a textbook clones it from GitHub on first use, so network access and a few minutes are needed the first time.
metadata:
  min_library_version: "0.1.0"
  chunk_schema: assets/chunk.schema.json
  upstream: https://github.com/michaelnavazhylau/openstax-llm
---

# OpenStax LLM

Chunk OpenStax college textbooks into structured, citation-aware, formula-safe datasets
for vector search (RAG) and model fine-tuning.

## The one rule

**Never write your own chunker for OpenStax content.**

Generic splitters slice display equations in half, orphan worked examples from their
solutions, and drop the section hierarchy that citations depend on. Every one of those
failures is silent — you get plausible-looking chunks and a broken retrieval set. Use the
library, the CLI, or the MCP tools. If they cannot do what you need, fix the library.

## Choose a surface

Prefer whichever is already available; they expose the same three operations.

| Situation | Use |
|---|---|
| The `openstax-llm` MCP server is connected | MCP tools (see `references/mcp-tools.md`) |
| You need JSONL on disk and shell access works | CLI: `openstax-llm prepare` |
| You are writing Python that imports the library | `TextBookDataset.from_textbook` |
| No CLI, no MCP, no library installed | Run `scripts/ensure-cli.sh` first |

Do not install, upgrade, or reconfigure the MCP server unless the user asked. If MCP tools
are unavailable, the CLI is the drop-in alternative.

## Workflow

### 1. Resolve a subject to a canonical slug

Never guess a slug. Titles are not slugs — `College Physics` is `college-physics-2e`.

```
search_catalog("college physics")            # MCP
openstax-llm search "college physics"        # CLI
```

Take the `slug` from the result. Slugs follow `<name>-<edition>e` conventions and are
case-sensitive lowercase.

### 2. Inspect before you export

Compilation is the expensive step, so look before you leap.

```
inspect_textbook("college-physics-2e")       # MCP: totals + per-section index
openstax-llm info college-physics-2e         # CLI
```

This returns `total_chunks`, `total_words`, `total_tokens_est`, a `chunk_types`
breakdown, and a `sections` index. Use `sections` to confirm the book covers what the user
asked for before spending time on a full export, and to check whether chunk counts are
sane for the intended context window.

### 3. Export a dataset

```
prepare_textbook("college-physics-2e", "datasets/college-physics-2e.jsonl")
openstax-llm prepare college-physics-2e -o datasets/college-physics-2e.jsonl
```

Tune only when the defaults are wrong. The defaults (`target_words=400`, `max_words=600`,
`overlap=50`) suit most embedding models.

- Raising `max_words` past ~800 starts hurting retrieval precision; prefer more chunks.
  The ceiling is enforced by splitting long paragraphs at sentence boundaries that sit
  outside math, so lowering it is safe.
- Increase `overlap` (100–150) only for prose-dense narrative books. Overlap is dropped
  when carrying it would push a chunk past `max_words`; the ceiling wins over overlap.
- Shorten for small-context models by lowering `target_words`; `max_words` must stay
  greater than or equal to `target_words`.

### 4. Verify before handing anything downstream

Treat the export as unverified until you check it:

```bash
openstax-llm validate datasets/college-physics-2e.jsonl
```

This checks formula integrity, `chunk_id` uniqueness, and provenance, and exits non-zero on
structural errors. Do not reimplement those checks inline: the delimiter scan is subtle
(`\$962.50` is an escaped currency amount, not math), and a hand-rolled
`text.count("$") % 2` reports false positives until nobody trusts the output.

Use `--strict` to also fail on warnings such as front matter that has no section number.

Then confirm the field-level contract against `assets/chunk.schema.json`.

## Chunk metadata contract

Every record carries `chunk_id`, `text`, `book_slug`, `book_title`, `chapter`, `section`,
`section_title`, `chunk_type`, `word_count`, `token_est`, and `metadata`. `chunk_type` is
one of `prose`, `example`, `exercise`, `definition`, `summary`. Full field semantics are in
`references/chunk-schema.md`; the machine-readable form is `assets/chunk.schema.json`.

Front matter (prefaces, formula tables, chapter introductions) has no section number, so
its `section` is empty and its `chunk_id` is prefixed with the module id instead. Cite
those chunks using `metadata.module_id`.

Retain `book_slug`, `section`, and `section_title` in whatever index you build. They are
what make a retrieved chunk citable back to a page a student can open.

See [`assets/chunk.schema.json`](assets/chunk.schema.json) for the machine-readable form.

## References

Read these only when the task needs them.

| File | Read when |
|---|---|
| [`references/chunk-schema.md`](references/chunk-schema.md) | Mapping chunks into a vector store, or debugging a metadata field |
| [`references/mcp-tools.md`](references/mcp-tools.md) | Wiring up or troubleshooting the MCP server, or writing tool calls |
| [`references/rag-recipes.md`](references/rag-recipes.md) | Loading the JSONL into Chroma, Qdrant, Pinecone, or Hugging Face |

## Scripts

Run these from the skill directory; they resolve their own paths.

| Script | Purpose |
|---|---|
| [`scripts/ensure-cli.sh`](scripts/ensure-cli.sh) | Verify the CLI exists and meets `min_library_version`; install if missing |
| [`scripts/install-mcp.sh`](scripts/install-mcp.sh) | Register the MCP server with a supported agent |
| [`scripts/prepare-textbook.sh`](scripts/prepare-textbook.sh) | Resolve a slug, export JSONL, then verify the result |

## Cost and time

The first compile of a book clones its repository (tens to hundreds of MB) and renders
every module; expect a few minutes. Later runs reuse the clone cache and are fast. Do not
kick off a full-book export to answer a question a section-level lookup can answer — read
`textbook://<slug>/<section>` or `inspect_textbook` instead.
