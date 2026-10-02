"""Command-line entry point for the openstax-llm MCP server.

stdio is the default transport because that is what MCP clients launch. All diagnostics
go to stderr: under stdio, stdout carries JSON-RPC frames and nothing else.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mcp.server.transport_security import TransportSecuritySettings

from openstax_llm_mcp._version import __version__
from openstax_llm_mcp.server import create_server

#: Allowed `Host` header values for `--http` when the operator has not widened them.
#: The `:*` entries are the SDK's wildcard-port form, so `localhost:8765` matches.
DEFAULT_ALLOWED_HOSTS = [
    "localhost",
    "localhost:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "[::1]",
    "[::1]:*",
]

DEFAULT_PORT = 8765
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openstax-llm-mcp",
        description="Model Context Protocol server for pedagogical OpenStax textbook chunking.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve the streamable HTTP transport instead of stdio",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for --http (default: 127.0.0.1; use 0.0.0.0 in a container)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Bind port for --http (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help=(
            "Additional allowed Host header value for --http (repeatable). "
            "Use HOST:* to allow any port."
        ),
    )
    parser.add_argument(
        "--insecure-disable-host-check",
        action="store_true",
        help=(
            "Turn off DNS-rebinding protection for --http. Only for a trusted network or "
            "a tunnel that rewrites the Host header."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Root that prepare_textbook may write into (default: current directory)",
    )
    parser.add_argument(
        "--max-cached-books",
        type=int,
        default=2,
        help="Compiled textbooks kept in memory (default: 2)",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        help="Logging level written to stderr (default: INFO)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # stderr on purpose: stdout is the JSON-RPC channel under the stdio transport.
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        stream=sys.stderr,
        format="%(asctime)s [openstax-llm-mcp] %(levelname)s %(message)s",
    )

    server = create_server(
        output_root=args.output_dir,
        max_cached_books=args.max_cached_books,
    )

    if args.http:
        if args.insecure_disable_host_check:
            security: TransportSecuritySettings | None = None
            logging.warning(
                "DNS-rebinding protection is disabled; any client that can reach %s:%s "
                "may call these tools.",
                args.host,
                args.port,
            )
        else:
            security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[*DEFAULT_ALLOWED_HOSTS, *args.allow_host],
            )
        logging.info("Serving streamable HTTP on %s:%s", args.host, args.port)
        server.run(
            "streamable-http",
            host=args.host,
            port=args.port,
            transport_security=security,
        )
    else:
        logging.info("Serving stdio")
        server.run("stdio")

    return 0


if __name__ == "__main__":
    sys.exit(main())
