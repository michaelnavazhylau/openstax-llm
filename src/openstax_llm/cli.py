"""Command line interface for openstax-llm."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import openstax_md as osm

from openstax_llm import __version__
from openstax_llm.chunker import DocumentChunker
from openstax_llm.dataset import TextBookDataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openstax-llm",
        description="Extract, chunk, and prepare OpenStax textbooks for LLMs and RAG pipelines.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="sub-command help")

    # prepare
    prep = subparsers.add_parser(
        "prepare", help="Compile and chunk an OpenStax textbook into a JSONL dataset"
    )
    prep.add_argument("target", help="Textbook slug (e.g. astronomy-2e) or local bundle path")
    prep.add_argument(
        "-o", "--out", type=Path, required=True, help="Destination JSONL dataset path"
    )
    prep.add_argument(
        "--target-words", type=int, default=400, help="Target words per chunk (default: 400)"
    )
    prep.add_argument(
        "--max-words", type=int, default=600, help="Maximum words per chunk (default: 600)"
    )
    prep.add_argument(
        "--overlap", type=int, default=50, help="Overlap words between chunks (default: 50)"
    )

    # info
    info = subparsers.add_parser("info", help="Inspect chunk statistics for a textbook")
    info.add_argument("target", help="Textbook slug or path")
    info.add_argument("--json", action="store_true", help="Output summary in JSON format")

    # search
    search = subparsers.add_parser("search", help="Search the catalog for available textbooks")
    search.add_argument("query", help="Keyword to search")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "prepare":
        chunker = DocumentChunker(
            target_words=args.target_words,
            max_words=args.max_words,
            overlap_words=args.overlap,
        )
        print(f"Preparing '{args.target}' for LLMs...")
        dataset = TextBookDataset.from_textbook(args.target, chunker=chunker)
        dataset.to_jsonl(args.out)
        s = dataset.summary()
        print(
            f"Ready: {s['total_chunks']} chunks ({s['total_words']:,} words, "
            f"~{s['total_tokens_est']:,} tokens) saved to {args.out}"
        )
        return 0

    if args.command == "info":
        dataset = TextBookDataset.from_textbook(args.target)
        s = dataset.summary()
        if args.json:
            print(json.dumps(s, indent=2))
        else:
            print(f"Book: {s['book_title']} ({s['book_slug']})")
            print(f"Total Chunks: {s['total_chunks']}")
            print(f"Total Words:  {s['total_words']:,}")
            print(f"Tokens (est): ~{s['total_tokens_est']:,}")
            print("Chunk Breakdown:")
            for c_type, count in s["chunk_types"].items():
                print(f"  - {c_type:12}: {count}")
        return 0

    if args.command == "search":
        results = osm.search(args.query)
        if not results:
            print(f"No textbooks found matching '{args.query}'")
            return 0
        print(f"Found {len(results)} matching textbooks:")
        for r in results[:10]:
            print(f"  {r['slug']:32} | {r['title']}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
