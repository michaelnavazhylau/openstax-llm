# Chunk schema

Reference for every field in a chunk record. The machine-readable form lives at
`../assets/chunk.schema.json`; this document explains intent and the traps.

## Record shape

Each line of a JSONL export is one JSON object:

```json
{
  "chunk_id": "1.2-c003",
  "text": "**Example 1.2** Differentiate $f(x)=x^3$.\n\nSolution: $f'(x)=3x^2$.",
  "book_slug": "calculus-volume-1",
  "book_title": "Calculus Volume 1",
  "chapter": "1",
  "section": "1.2",
  "section_title": "Review of Functions",
  "chunk_type": "example",
  "word_count": 9,
  "token_est": 11,
  "metadata": {}
}
```

## Fields

### `chunk_id` (string)

`<section>-c<index>` with a three-digit zero-padded index, unique within a book:
`1.2-c003`. When the source module has no section number the prefix is the module id
(`m60027-c001`), and with neither it falls back to `chunk-c001`.

Uniqueness matters more than it looks: `chunk_id` is the natural primary key for a vector
store. Earlier versions emitted `chunk-001` for *every* sectionless module, so ten modules
collided and an upsert silently discarded nine of them. `openstax-llm validate` now fails
on a duplicate id.

The index is assigned in document order, so `1.2-c003` sorts correctly within a section.
Across sections, sort by `section` then `chunk_id` — do not sort by `chunk_id` alone,
because `1.10-c001` sorts before `1.2-c001` lexicographically.

### `text` (string)

Markdown with LaTeX intact. Two delimiters appear:

- `$...$` for inline math.
- `$$...$$` for display math, which may span multiple lines.

A chunk boundary is never placed inside an unclosed `$` or `$$` block. **Consider this an
invariant you can assert on**, but assert it correctly: `\$` is an escaped literal dollar
and `$$` is a display toggle, so a naive `text.count("$") % 2` reports split formulas where
there are none. Use `openstax-llm validate`, which implements the scan once.

Fenced code blocks (` ``` `) are likewise never split.

### `book_slug` and `book_title` (string)

`book_slug` is the canonical OpenStax catalog slug (`calculus-volume-1`,
`college-physics-2e`). `book_title` is the display title. Both are copied onto every chunk
so a retrieved chunk is self-describing — you never need a join to render a citation.

### `chapter` (string)

The portion of `section` before the first dot: `1.2` yields `"1"`. It is `""` when the
section has no dot. It is a *string*, not an integer, because OpenStax also uses
non-numeric chapter prefixes; do not cast it blindly.

### `section` and `section_title` (string)

`section` is the module number (`1.2`). `section_title` is the module title
(`Review of Functions`). Both are `""` when content was chunked without a section context,
which happens for front matter (prefaces, formula tables, chapter introductions) and when
calling `chunk_markdown` directly on loose markdown.

Front matter is legitimate content worth indexing, but it cannot be cited by section. Its
chunks carry `metadata.module_id`, and the module id is what prefixes their `chunk_id`.
Note that `section_title` alone does not identify front matter: a real textbook has many
modules all titled `Introduction`. `openstax-llm validate` reports sectionless chunks as
warnings, not errors, and `--strict` turns them into failures when you need full
attribution.

### `chunk_type` (string enum)

The pedagogical role, detected from the block's content:

| Value | Detected from | Typical content |
|---|---|---|
| `example` | `Example <n>` heading, or a `Solution:` label | Worked examples with step-by-step solutions |
| `exercise` | `exercise`, `problem`, or `review question` | Problem sets and review questions |
| `definition` | `definition`, or `key terms` | Term/definition pairs and glossaries |
| `summary` | `chapter review`, or `summary` | Section and chapter summaries |
| `prose` | fallback | Explanatory body text |

Detection is heuristic and content-based, not authoritative. A block that merely mentions
"problem" inherits `exercise`. If you need pedagogical routing that is exact, filter with
your own rules on top of the value rather than replacing it.

Worked examples and other non-prose blocks are emitted as standalone chunks whenever they
meet `min_words` (default 60), so an example is never merged into surrounding prose. That
is what keeps a solution with its problem.

### `word_count` (integer)

Whitespace-delimited count of `text`. Computed with `len(text.split())`, so Markdown and
LaTeX markup inflate it relative to the rendered word count.

`max_words` (default 600) is enforced, not merely targeted. It is applied two ways: an
oversized paragraph is split at sentence boundaries that lie outside math, and overlap is
dropped rather than allowed to push a chunk over the ceiling. The one remaining exception
is a single unbreakable unit — one sentence, or a display-math block — larger than
`max_words`; those are emitted intact rather than cut, because cutting them would break the
formula invariant.

### `token_est` (integer)

`floor(word_count * 1.3)`. The 1.3 coefficient is a rule of thumb for technical and
mathematical prose. It is deliberately conservative for LaTeX-heavy content, where real
tokenization can run noticeably higher. Use it for capacity planning, not for enforcing a
hard context limit.

### `metadata` (object)

A key-value bag. `openstax-llm` writes exactly one key, `module_id`, the OpenStax module
identifier the chunk came from. It is the only unambiguous way to attribute front matter,
which has no section number.

Everything else in `metadata` is reserved for downstream use. Because records are written
once at export time, prefer adding your own fields in a post-processing pass rather than
mutating the export.

## Loading into a vector store

Minimum useful payload for an embedding record:

```python
{
    "id": chunk["chunk_id"],
    "document": chunk["text"],
    "metadata": {
        "book_slug": chunk["book_slug"],
        "book_title": chunk["book_title"],
        "section": chunk["section"],
        "section_title": chunk["section_title"],
        "chunk_type": chunk["chunk_type"],
        "chapter": chunk["chapter"],
        "module_id": chunk["metadata"].get("module_id", ""),
    },
}
```

Keep `text` as the embedded document. Embedding a concatenation of metadata and text tends
to hurt retrieval, because citation boilerplate is nearly identical across chunks.

## Dataset-level summary

CLI `info --json` and the MCP `inspect_textbook` tool return a summary rather than records:

```json
{
  "book_slug": "calculus-volume-1",
  "book_title": "Calculus Volume 1",
  "total_chunks": 812,
  "total_words": 291004,
  "total_tokens_est": 378305,
  "chunk_types": {"prose": 540, "example": 180, "exercise": 80, "definition": 12},
  "sections": [
    {"section": "1.1", "section_title": "Review of Functions", "chapter": "1",
     "chunks": 14, "words": 5102}
  ]
}
```

`sections` is present from `inspect_textbook` and absent from CLI `info --json`. A
`chunk_types` total below `total_chunks` means some chunks fell outside the five known
types; the difference is exactly the `prose` count you would expect, since `prose` is the
fallback.
