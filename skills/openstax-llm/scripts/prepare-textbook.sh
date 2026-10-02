#!/usr/bin/env bash
#
# Resolve a subject to a catalog slug, export a JSONL dataset, and verify it.
#
# Usage: prepare-textbook.sh <slug-or-search-term> <output.jsonl>
#                            [--target-words N] [--max-words N] [--overlap N]
#                            [--strict] [--json]
#
# Example:
#   prepare-textbook.sh "college physics" datasets/physics.jsonl --target-words 350
#
# Compiling a book the first time clones it from GitHub and can take minutes.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -lt 2 ]]; then
    sed -n '3,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
fi

TARGET="$1"
OUT="$2"
shift 2

# Split the remaining arguments: chunker flags belong to `prepare`, reporting flags
# belong to `validate`. Forwarding --strict to `prepare` would be an argparse error.
PREPARE_ARGS=()
VALIDATE_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --strict|--json) VALIDATE_ARGS+=("$1"); shift ;;
        --target-words|--max-words|--overlap)
            PREPARE_ARGS+=("$1" "${2:?$1 needs a value}")
            shift 2
            ;;
        *) PREPARE_ARGS+=("$1"); shift ;;
    esac
done

# Fail fast with an actionable message rather than a traceback mid-export.
"${SKILL_DIR}/scripts/ensure-cli.sh"

# `prepare` accepts a slug or a local path. A human-supplied title is neither, so
# resolve it through the bundled catalog first. This stays offline and instant — running
# `info` here would compile the whole book just to check that the slug exists.
first_slug() {
    openstax-llm search "$1" 2>/dev/null | awk '/^  [^ ]/ {print $1}'
}

if [[ ! -e "${TARGET}" ]] && ! first_slug "${TARGET}" | grep -qxF "${TARGET}"; then
    echo "'${TARGET}' is not an exact slug or a local path. Searching the catalog..." >&2
    MATCH="$(first_slug "${TARGET}" | head -n 1)"
    if [[ -z "${MATCH}" ]]; then
        echo "error: no catalog match for '${TARGET}'." >&2
        echo "Browse everything with: openstax-llm search ''" >&2
        exit 1
    fi
    echo "Using slug '${MATCH}'." >&2
    TARGET="${MATCH}"
fi

echo "Exporting ${TARGET} -> ${OUT}"
if [[ ${#PREPARE_ARGS[@]} -gt 0 ]]; then
    openstax-llm prepare "${TARGET}" -o "${OUT}" "${PREPARE_ARGS[@]}"
else
    openstax-llm prepare "${TARGET}" -o "${OUT}"
fi

# Delegate verification to `openstax-llm validate` instead of reimplementing it here.
# Duplicated checks drift: a naive `text.count("$") % 2` reports escaped currency such as
# `\$962.50` as a split formula, and a validator that cries wolf gets ignored.
#
# Warnings (front matter legitimately has no section number) do not fail the run.
# Pass --strict when they should.
echo
echo "Verifying ${OUT}"
if [[ ${#VALIDATE_ARGS[@]} -gt 0 ]]; then
    openstax-llm validate "${OUT}" "${VALIDATE_ARGS[@]}"
else
    openstax-llm validate "${OUT}"
fi
