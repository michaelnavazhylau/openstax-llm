"""Process-wide cache of compiled, chunked OpenStax textbooks.

Compiling a textbook walks every CNXML module in the bundle and renders it to markdown.
That is far too expensive to repeat for each tool call, so ``inspect_textbook`` and
``prepare_textbook`` share one small LRU keyed by target plus chunker configuration.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

from openstax_llm.chunker import DocumentChunker
from openstax_llm.dataset import TextBookDataset

#: Cache key: the source target plus every field that changes the chunk boundaries.
CacheKey = tuple[str, int, int, int]


class TextbookStore:
    """Thread-safe bounded cache of :class:`~openstax_llm.dataset.TextBookDataset`."""

    def __init__(self, *, max_entries: int = 2, out_dir: Path | None = None) -> None:
        self._max_entries = max(1, max_entries)
        self._out_dir = out_dir
        self._entries: OrderedDict[CacheKey, TextBookDataset] = OrderedDict()
        # Guards `_entries` and `_compile_locks`.
        self._lock = threading.Lock()
        # One lock per target, held while that target compiles.
        #
        # Compiling must NOT happen outside a lock. The upstream compiler clones the
        # textbook repository into a shared cache directory, and two concurrent clones of
        # the same repository into the same path make git exit 128. MCP servers run tool
        # bodies in worker threads, and models routinely emit several parallel tool calls
        # in one turn, so this is a routine occurrence rather than a corner case: it was
        # reproduced deterministically with two concurrent `inspect_textbook` calls.
        #
        # Keying the lock by target rather than reusing `_lock` keeps concurrency for
        # distinct books while serialising the risky same-repository case.
        self._compile_locks: dict[str, threading.Lock] = {}

    def _lock_for(self, target: str) -> threading.Lock:
        with self._lock:
            lock = self._compile_locks.get(target)
            if lock is None:
                lock = threading.Lock()
                self._compile_locks[target] = lock
            return lock

    @staticmethod
    def _key(target: str, chunker: DocumentChunker) -> CacheKey:
        return (str(target), chunker.target_words, chunker.max_words, chunker.overlap_words)

    def get(self, target: str, *, chunker: DocumentChunker | None = None) -> TextBookDataset:
        """Return the chunked dataset for ``target``, compiling it on a cache miss."""
        active = chunker or DocumentChunker()
        key = self._key(target, active)

        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached

        with self._lock_for(str(target)):
            # A concurrent caller for the same target may have finished while we waited.
            with self._lock:
                cached = self._entries.get(key)
                if cached is not None:
                    self._entries.move_to_end(key)
                    return cached

            dataset = TextBookDataset.from_textbook(
                target,
                chunker=active,
                out_dir=self._out_dir,
                # The upstream compiler prints clone progress to stdout. Under the stdio
                # transport stdout is the JSON-RPC channel, so it must stay silent.
                quiet=True,
            )

            with self._lock:
                self._entries[key] = dataset
                self._entries.move_to_end(key)
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)

        return dataset

    def clear(self) -> None:
        """Drop every cached textbook."""
        with self._lock:
            self._entries.clear()
