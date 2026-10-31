#!/usr/bin/env bash
#
# Verify the openstax-llm CLI is available and new enough for this skill.
#
# Exit codes: 0 = ready, 1 = missing or too old (after attempting an install).
#
# Installs come from PyPI by name and nowhere else. There is deliberately no `git+https://`
# fallback: it would resolve the repository's default branch at the moment an agent runs this
# script, so an upstream push — not a release — would decide what the agent installs. A skill
# audit of this repository reported that shape as Snyk W012 ("unverifiable external
# dependency: runtime URL that controls agent").
#
# The skill and the library are versioned independently: `skills add` copies this
# directory and hashes it, so an installed skill can outlive the library it documents.
# SKILL.md frontmatter records `metadata.min_library_version` and this script enforces it.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_MD="${SKILL_DIR}/SKILL.md"

min_version() {
    # Read metadata.min_library_version without requiring a YAML parser.
    # Kept to POSIX BRE (no \?) so it behaves the same under BSD and GNU sed.
    sed -n 's/^[[:space:]]*min_library_version:[[:space:]]*//p' "${SKILL_MD}" \
        | tr -d '"' | tr -d "'" | head -n 1
}

# Print the first three numeric components, so "0.2.1.dev5+g1234" compares as 0.2.1.
normalize_version() {
    printf '%s' "$1" | grep -oE '[0-9]+(\.[0-9]+)*' | head -n 1 | cut -d. -f1-3
}

# Exit 0 when $1 >= $2, comparing dot-separated numeric components.
version_at_least() {
    local have want
    IFS=. read -r -a have <<<"$1"
    IFS=. read -r -a want <<<"$2"
    local i
    for i in 0 1 2; do
        local h="${have[$i]:-0}" w="${want[$i]:-0}"
        if ((10#${h} > 10#${w})); then return 0; fi
        if ((10#${h} < 10#${w})); then return 1; fi
    done
    return 0
}

WANT="$(min_version)"
if [[ -z "${WANT}" ]]; then
    echo "warning: no metadata.min_library_version in ${SKILL_MD}; skipping version check" >&2
    WANT="0.0.0"
fi

installed_version() {
    if command -v openstax-llm >/dev/null 2>&1; then
        openstax-llm --version 2>/dev/null | grep -oE '[0-9]+(\.[0-9]+)+' | head -n 1
    fi
}

install_cli() {
    # Output is left visible on purpose: when the index is unreachable or behind a proxy, the
    # resolver's own message is the only thing that says why the install failed.
    echo "openstax-llm not found. Installing from PyPI." >&2
    if command -v uv >/dev/null 2>&1; then
        if uv tool install openstax-llm; then
            return 0
        fi
    elif command -v pipx >/dev/null 2>&1; then
        if pipx install openstax-llm; then
            return 0
        fi
    else
        echo "error: neither uv nor pipx is available. Install uv: https://docs.astral.sh/uv/" >&2
        return 1
    fi
    echo "error: 'openstax-llm' could not be installed from PyPI. Check network or proxy" >&2
    echo "settings, or run 'uv tool install openstax-llm' by hand to see the index error." >&2
    return 1
}

HAVE="$(installed_version || true)"

if [[ -z "${HAVE}" ]]; then
    install_cli || exit 1
    HAVE="$(installed_version || true)"
fi

if [[ -z "${HAVE}" ]]; then
    echo "error: openstax-llm still unavailable after install attempt." >&2
    exit 1
fi

if version_at_least "$(normalize_version "${HAVE}")" "$(normalize_version "${WANT}")"; then
    echo "ok: openstax-llm ${HAVE} (skill requires >= ${WANT})"
    exit 0
fi

echo "error: openstax-llm ${HAVE} is older than the ${WANT} this skill documents." >&2
echo "Upgrade with: uv tool upgrade openstax-llm" >&2
echo "The chunk schema may have changed; see ${SKILL_DIR}/references/chunk-schema.md" >&2
exit 1
