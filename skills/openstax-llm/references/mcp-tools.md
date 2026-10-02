# MCP tools and resources

The `openstax-llm-mcp` server exposes three tools and two resource templates. This file
covers wiring, exact call shapes, and failure modes.

## Server details

| Property | Value |
|---|---|
| Server name | `openstax-llm` (tools are addressed as `mcp__openstax-llm__<tool>`) |
| Entry point | `openstax-llm-mcp` |
| Transports | stdio (default), streamable HTTP (`--http`) |
| Package | `openstax-llm-mcp` |
| Requires | Python 3.10+, `mcp>=2.0,<3` |

## Registration

Registering is a user-visible change; do it only when asked. `scripts/install-mcp.sh` does
this for you, or write the entry by hand:

```json
{
  "mcpServers": {
    "openstax-llm": {
      "command": "uvx",
      "args": ["openstax-llm-mcp"],
      "description": "Chunk OpenStax textbooks into citation-aware RAG datasets"
    }
  }
}
```

Project-level registration is `pi mcp add -l openstax-llm -- uvx openstax-llm-mcp`; without
`-l` it is user-level. Run `/reload` (Pi) or restart the agent after editing config by hand.
Verify with `pi mcp list`, which prints connection state, tool count, and any error.

## Tools

### `search_catalog`

```json
{"query": "college physics", "limit": 10}
```

Returns an array of `{slug, title, language, category, repo}` ordered by relevance. Runs
entirely offline against the bundled catalog — it does not hit the network.

An empty `query` lists the catalog from the top, which is how you enumerate available
books. `limit` must be at least 1.

Use this before any other tool. Passing a title instead of a slug to `inspect_textbook` or
`prepare_textbook` fails, because those accept slugs or filesystem paths only.

### `inspect_textbook`

```json
{"target": "college-physics-2e", "target_words": 400, "max_words": 600, "overlap": 50}
```

Returns the dataset summary plus a `sections` array:

```json
{
  "book_slug": "college-physics-2e",
  "book_title": "College Physics 2e",
  "total_chunks": 1642, "total_words": 588310, "total_tokens_est": 764803,
  "chunk_types": {"prose": 1100, "example": 300, "exercise": 200, "definition": 42},
  "sections": [{"section": "1.1", "section_title": "Physics: An Introduction",
                "chapter": "1", "chunks": 6, "words": 2104}]
}
```

Writes nothing to disk. Results are cached in-process, so a subsequent
`prepare_textbook` with the same arguments and chunker configuration reuses this compile
instead of rendering the book twice. Changing any chunker argument is a cache miss and
recompiles.

### `prepare_textbook`

```json
{"target": "college-physics-2e", "out": "datasets/college-physics-2e.jsonl"}
```

Returns `{path, bytes, summary}`, where `path` is the absolute destination. `out` is
resolved relative to the server's `--output-dir` (default: the server's working directory).

**Writes are sandboxed.** Absolute paths and any `..` traversal that escapes the output
root are rejected with `Refusing to write outside the configured output directory`. That is
by design, not a bug: an MCP client supplies `out`, so it is untrusted input. To write
elsewhere, restart the server with `--output-dir` set to a parent of the intended location.

## Resources

Resources are pull-based context, better than a tool call when you want one section in
context rather than a file on disk.

| URI | Returns |
|---|---|
| `textbook://<slug>` | `{book_slug, book_title, total_chunks, total_words, total_tokens_est, sections}` |
| `textbook://<slug>/<section>` | `{book_slug, book_title, section, section_title, chunks}` |

`textbook://<slug>/1.1` returns every chunk in section 1.1 with full metadata and intact
LaTeX. An unknown section raises `ResourceNotFoundError` listing the available sections —
read that message rather than guessing again.

Section reads are the cheapest way to answer a content question. Prefer them over a
full-book export.

## Options

```
--http                       Serve streamable HTTP instead of stdio
--host HOST                  Bind host for --http (default: 127.0.0.1)
--port PORT                  Bind port for --http (default: 8765)
--allow-host HOST            Repeatable. Extra allowed Host header; HOST:* allows any port
--insecure-disable-host-check  Turn off DNS-rebinding protection (trusted networks only)
--output-dir DIR             Root that prepare_textbook may write into (default: cwd)
--max-cached-books N         Compiled textbooks kept in memory (default: 2)
--log-level LEVEL            DEBUG, INFO, WARNING, or ERROR (default: INFO)
```

## Failure modes

| Symptom | Cause and fix |
|---|---|
| `Refusing to write outside the configured output directory` | `out` was absolute or contained `..`. Use a relative path. |
| `max_words (N) must be >= target_words (M)` | Chunker arguments contradict each other. Raise `max_words` or lower `target_words`. |
| `Bundle path does not exist and target 'X' could not be resolved` | Not a valid slug or path. Run `search_catalog` to get the real slug. |
| Server connects, zero tools | The server failed during import. Run `uvx openstax-llm-mcp --version` directly and read the error. |
| HTTP `421 Invalid Host header` | DNS-rebinding protection. Add the hostname with `--allow-host`. |
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | An `mcp` 1.x release is installed but the server needs 2.x, or vice versa. Reinstall so the dependency range is respected. |
| First call is slow, later calls fast | Expected. The first call clones and compiles the book. |

## A note on stdout

Under the stdio transport, stdout is the JSON-RPC channel. The server keeps it clean by
suppressing the upstream compiler's clone progress, which otherwise prints to stdout. If
you ever see non-JSON bytes on stdout, that is the bug class to suspect.
