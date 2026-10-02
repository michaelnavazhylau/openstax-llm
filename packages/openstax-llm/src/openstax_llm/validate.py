"""Structural validation of chunked datasets.

The checks here are the ones that catch silent corruption: a formula split across a chunk
boundary, or a duplicated ``chunk_id`` that would make a vector database overwrite one
chunk with another. Both are invisible in a spot check of the output and expensive to
discover after an index has been built.

Markdown is not LaTeX, so "does this chunk contain balanced math delimiters" needs care:

* ``\\$`` is an escaped literal dollar (``\\$962.50``), not a delimiter.
* ``$$`` is a display-math toggle, not two inline delimiters.
* Fenced code blocks contain prose about math, not math.

A naive ``text.count("$") % 2`` gets all three wrong and reports split formulas where there
are none. A validator that cries wolf is worse than no validator, because its output gets
ignored — so this module is the single source of truth for the check, shared by the CLI,
the tests, and the agent skill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from openstax_llm.chunker import PedagogicalChunk

#: Machine-readable category for a detected problem.
ProblemKind = Literal["unclosed_math", "unclosed_code", "duplicate_id", "missing_section"]

#: ``error`` means the dataset is corrupt; ``warning`` means provenance is incomplete but
#: the data is usable. Only errors should fail a build by default.
Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class ChunkProblem:
    """One structural defect, located at a specific chunk where possible."""

    kind: ProblemKind
    detail: str
    chunk_id: str = ""
    severity: Severity = "error"

    def __str__(self) -> str:
        location = f"{self.chunk_id}: " if self.chunk_id else ""
        return f"{location}{self.detail}"


_ERRORS: frozenset[str] = frozenset({"unclosed_math", "unclosed_code", "duplicate_id"})


def severity_of(kind: ProblemKind) -> Severity:
    """Classify a problem kind. Only these kinds indicate actual corruption."""
    return "error" if kind in _ERRORS else "warning"


def find_delimiter_imbalance(text: str) -> str | None:
    """Return a description if ``text`` has unbalanced math or code delimiters.

    Scans left to right, honouring ``\\$`` escapes, ``$$`` display blocks, and fenced
    code. Returns ``None`` when the chunk is balanced.
    """
    index = 0
    length = len(text)
    in_display = False
    in_inline = False
    in_fence = False

    while index < length:
        char = text[index]

        if char == "\\" and index + 1 < length:
            index += 2  # Consume the escape and the escaped character.
            continue

        if text.startswith("```", index):
            in_fence = not in_fence
            index += 3
            continue

        if in_fence:
            index += 1
            continue

        if text.startswith("$$", index) and not in_inline:
            in_display = not in_display
            index += 2
            continue

        if char == "$" and not in_display:
            in_inline = not in_inline
            index += 1
            continue

        index += 1

    if in_display:
        return "unclosed display math: a $$ block opens but never closes"
    if in_inline:
        return "unclosed inline math: an odd number of unescaped $ delimiters"
    if in_fence:
        return "unclosed code fence: a ``` block opens but never closes"
    return None


def validate_chunks(chunks: Sequence[PedagogicalChunk]) -> list[ChunkProblem]:
    """Check delimiter integrity, chunk-id uniqueness, and provenance.

    An empty result means the dataset is structurally sound and fully attributed. Callers
    that only care about corruption can filter on ``severity == "error"``.
    """
    problems: list[ChunkProblem] = []
    seen: set[str] = set()

    for chunk in chunks:
        imbalance = find_delimiter_imbalance(chunk.text)
        if imbalance is not None:
            problems.append(
                ChunkProblem(
                    "unclosed_math", imbalance, chunk.chunk_id, severity_of("unclosed_math")
                )
            )

        if chunk.chunk_id in seen:
            problems.append(
                ChunkProblem(
                    "duplicate_id",
                    "duplicate chunk_id; a vector index keyed on this id would silently "
                    "drop one of the chunks",
                    chunk.chunk_id,
                    severity_of("duplicate_id"),
                )
            )
        seen.add(chunk.chunk_id)

        if not chunk.section:
            problems.append(
                ChunkProblem(
                    "missing_section",
                    # Front matter legitimately has no section number. It is still worth
                    # flagging, because the chunk cannot be cited without one; the fix is
                    # usually to carry `metadata['module_id']` instead.
                    "empty section; cite via metadata.module_id if this is front matter",
                    chunk.chunk_id,
                    severity_of("missing_section"),
                )
            )

    return problems


def errors_only(problems: Iterable[ChunkProblem]) -> list[ChunkProblem]:
    """Filter to the problems that mean the dataset is corrupt."""
    return [problem for problem in problems if problem.severity == "error"]


def summarize_problems(problems: Iterable[ChunkProblem]) -> dict[str, int]:
    """Count problems by kind, for machine-readable reporting."""
    counts: dict[str, int] = {}
    for problem in problems:
        counts[problem.kind] = counts.get(problem.kind, 0) + 1
    return counts
