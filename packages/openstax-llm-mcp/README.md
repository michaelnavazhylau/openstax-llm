# openstax-llm-mcp

**Model Context Protocol server for [openstax-llm](https://github.com/michaelnavazhylau/openstax-llm).**

Exposes pedagogical textbook chunking to any MCP client over stdio or streamable HTTP.

## Install

```bash
uvx openstax-llm-mcp          # stdio, one-shot
uv tool install openstax-llm-mcp
```

## Register with an MCP client

```bash
# Pi
pi mcp add openstax-llm -- uvx openstax-llm-mcp

# Claude Code
claude mcp add openstax-llm -- uvx openstax-llm-mcp
```

Or write the entry directly:

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

## Run over streamable HTTP

```bash
openstax-llm-mcp --http --host 0.0.0.0 --port 8765
```

In a container the request `Host` header will not be loopback, and the SDK's DNS-rebinding
protection rejects unknown hosts. Allow the hostnames you actually serve:

```bash
openstax-llm-mcp --http --host 0.0.0.0 --allow-host localhost:8765 --allow-host textbooks.internal
```

## Tools

| Tool | Description |
|---|---|
| `search_catalog(query, limit=10)` | Search the OpenStax catalog by slug, title, or category |
| `inspect_textbook(target)` | Chunk statistics plus a per-section index, without writing anything |
| `prepare_textbook(target, out, ...)` | Compile, chunk, and export a textbook to JSONL |

`target` accepts a catalog slug (`calculus-volume-1`) or a path to a local bundle.

## Resources

| URI | Content |
|---|---|
| `textbook://{slug}` | Overview: title, totals, chunk-type breakdown, section index |
| `textbook://{slug}/{section}` | Every chunk for one section, with intact LaTeX |

## Options

```
--http                  Serve streamable HTTP instead of stdio
--host HOST             Bind host for --http (default: 127.0.0.1)
--port PORT             Bind port for --http (default: 8765)
--allow-host HOST       Repeatable; allowed Host header value for --http
--output-dir DIR        Root that prepare_textbook may write into (default: cwd)
--max-cached-books N    Compiled textbooks kept in memory (default: 2)
--log-level LEVEL       Logging level for the stderr logger (default: INFO)
```

## Design notes

- **stdio is the default** and keeps stdout clean for JSON-RPC; all logging goes to stderr.
- **`prepare_textbook` cannot escape `--output-dir`.** Absolute paths and `..` traversal are rejected
  before anything is written.
- **Compiled textbooks are cached** in a small LRU. Compiling a book renders every module, so
  `inspect_textbook` followed by `prepare_textbook` reuses one compile.
- **This distribution has no direct URL dependency.** `openstax-llm` is referenced as an abstract
  range so the wheel stays publishable to PyPI.

## Development

From the repository root:

```bash
uv sync
uv run pytest packages/openstax-llm-mcp -v
uv run mypy
```

## License

MIT
