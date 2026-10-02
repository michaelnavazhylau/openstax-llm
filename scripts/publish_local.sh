#!/usr/bin/env bash
#
# Publish both workspace members with a token from pypi-creds.env.
#
# Defaults to a DRY RUN. Nothing leaves the machine until you pass --execute, because a
# PyPI upload is irreversible and consumes the version permanently.
#
# Usage:
#   scripts/publish_local.sh                       # dry run, PyPI
#   scripts/publish_local.sh --target testpypi     # dry run, TestPyPI
#   scripts/publish_local.sh --execute             # actually upload to PyPI
#   scripts/publish_local.sh --target testpypi --execute
#
# Why this exists rather than a couple of one-liners:
#   * `uv publish` with no arguments uploads every file in `dist/` (uv#8033), so a stray
#     artifact in dist/ would be published. Each call here is scoped to one package.
#   * Package order matters. openstax-llm-mcp depends on openstax-llm, so publishing the
#     MCP package first leaves a window where `uv add openstax-llm-mcp` cannot resolve.
#   * The metadata gate and the post-upload index check are easy to forget under pressure.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/pypi-creds.env"
TARGET="pypi"
EXECUTE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) TARGET="${2:?--target needs a value}"; shift 2 ;;
        --env-file) ENV_FILE="${2:?--env-file needs a value}"; shift 2 ;;
        --execute) EXECUTE=1; shift ;;
        -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "error: unknown argument '$1'" >&2; exit 2 ;;
    esac
done

case "${TARGET}" in
    pypi)
        PUBLISH_URL=""
        TOKEN_CANDIDATES=(UV_PUBLISH_TOKEN PYPI_API_TOKEN PYPI_TOKEN TWINE_PASSWORD)
        INDEX_CHECK="https://pypi.org"
        ;;
    testpypi)
        PUBLISH_URL="https://test.pypi.org/legacy/"
        TOKEN_CANDIDATES=(TEST_PYPI_TOKEN TEST_PYPI_API_TOKEN TESTPYPI_TOKEN UV_PUBLISH_TOKEN_TESTPYPI)
        INDEX_CHECK="https://test.pypi.org"
        ;;
    *) echo "error: --target must be 'pypi' or 'testpypi', got '${TARGET}'" >&2; exit 2 ;;
esac

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "error: ${ENV_FILE} not found." >&2
    echo "Create it from the template comments in that path; it is gitignored on purpose." >&2
    exit 1
fi

# shellcheck disable=SC1090
set -a && . "${ENV_FILE}" && set +a

# First non-empty candidate wins, matched by NAME. The value is never echoed.
# Several names are accepted because the sibling openstax-md repository uses
# PYPI_API_TOKEN / TEST_PI_API_TOKEN, so this script can point straight at that file via
# --env-file rather than duplicating the secret into a second copy on disk.
TOKEN=""
TOKEN_VAR=""
for candidate in "${TOKEN_CANDIDATES[@]}"; do
    if [[ -n "${!candidate:-}" ]]; then
        TOKEN="${!candidate}"
        TOKEN_VAR="${candidate}"
        break
    fi
done

if [[ -z "${TOKEN}" ]]; then
    echo "error: no token found in ${ENV_FILE}." >&2
    echo "Looked for: ${TOKEN_CANDIDATES[*]}" >&2
    if [[ "${TARGET}" == "pypi" ]]; then
        echo "For a FIRST upload it must be scoped to \"Entire account (all projects)\":" >&2
        echo "a project-scoped token cannot exist before the project does." >&2
        echo "Create one at https://pypi.org/manage/account/token/" >&2
    else
        echo "Create one at https://test.pypi.org/manage/account/token/" >&2
        echo "(TestPyPI accounts are separate from PyPI accounts.)" >&2
    fi
    exit 1
fi

# Shape check only, so an obvious paste error surfaces before a 403. Never prints a value.
if [[ "${TOKEN_VAR}" != "TWINE_PASSWORD" && "${TOKEN}" != pypi-* ]]; then
    echo "warning: ${TOKEN_VAR} does not start with 'pypi-', which PyPI tokens normally do." >&2
    echo "         Continuing; check for a stray quote or a truncated paste." >&2
fi

# Exported once so no token ever appears in argv, where `ps` would show it.
export UV_PUBLISH_TOKEN="${TOKEN}"

version_of() {
    python3 -c "
import pathlib, tomllib
print(tomllib.loads(pathlib.Path('${REPO_ROOT}/packages/$1/pyproject.toml').read_text())['project']['version'])
"
}

CORE_VERSION="$(version_of openstax-llm)"
MCP_VERSION="$(version_of openstax-llm-mcp)"
if [[ "${CORE_VERSION}" != "${MCP_VERSION}" ]]; then
    echo "error: version skew: openstax-llm=${CORE_VERSION} openstax-llm-mcp=${MCP_VERSION}" >&2
    echo "Both members release in lockstep; tests/test_skill_contract.py enforces this." >&2
    exit 1
fi

if [[ ${EXECUTE} -eq 1 ]]; then
    MODE="UPLOAD"
else
    MODE="DRY RUN (pass --execute to upload)"
fi

echo "Env file: ${ENV_FILE}"
echo "Token:    \$${TOKEN_VAR} (value never printed)"
echo "Target:   ${TARGET}${PUBLISH_URL:+ (${PUBLISH_URL})}"
echo "Version:  ${CORE_VERSION}"
echo "Mode:     ${MODE}"
echo

# A published version cannot be replaced, so check before spending time building.
# The package must be visible at least once. Re-runs on TestPyPI are expected, so this
# reports rather than refuses there.
release_listed() {
    # The JSON API reflects an upload immediately, whereas /simple/ can lag ~45s on
    # TestPyPI. A single-shot /simple/ check therefore produces false negatives -- which
    # is exactly what happened on the first rehearsal of this project.
    curl -sf "${INDEX_CHECK}/pypi/$1/json" 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
releases = data.get('releases') or {}
info = data.get('info') or {}
version = '$2'
raise SystemExit(0 if (version in releases or info.get('version') == version) else 1)
"
}

echo "== Checking whether ${CORE_VERSION} is already published =="
for pkg in openstax-llm openstax-llm-mcp; do
    if [[ "${TARGET}" == "testpypi" ]]; then
        if release_listed "${pkg}" "${CORE_VERSION}"; then
            echo "  ${pkg} ${CORE_VERSION}: already on TestPyPI (rehearsal re-run)"
        else
            echo "  ${pkg} ${CORE_VERSION}: not present"
        fi
    elif release_listed "${pkg}" "${CORE_VERSION}"; then
        echo "  ${pkg} ${CORE_VERSION} ALREADY EXISTS on PyPI." >&2
        echo "  The upload will be rejected. Bump the version in both pyproject.toml files," >&2
        echo "  their __version__ literals, and the skill's min_library_version." >&2
        exit 1
    else
        echo "  ${pkg} ${CORE_VERSION}: not present, safe to publish"
    fi
done
echo

echo "== Building =="
cd "${REPO_ROOT}"
rm -rf dist
uv build --package openstax-llm --out-dir dist/openstax-llm
uv build --package openstax-llm-mcp --out-dir dist/openstax-llm-mcp
echo

echo "== Metadata gate (no direct URL dependencies) =="
uv run python scripts/check_wheel_metadata.py dist/openstax-llm/*.whl dist/openstax-llm-mcp/*.whl
echo

publish_package() {
    local pkg="$1"
    shift
    local -a files=(dist/"${pkg}"/*)
    if [[ ! -e "${files[0]}" ]]; then
        echo "error: no distributions found in dist/${pkg}/" >&2
        return 1
    fi

    # Args before files, so `uv publish` never falls back to its `dist/*` default.
    local -a cmd=(uv publish)
    if [[ -n "${PUBLISH_URL}" ]]; then
        cmd+=(--publish-url "${PUBLISH_URL}")
    fi
    cmd+=("$@" "${files[@]}")
    "${cmd[@]}"
}

echo "== Dry run =="
publish_package openstax-llm --dry-run
publish_package openstax-llm-mcp --dry-run
echo

if [[ ${EXECUTE} -ne 1 ]]; then
    echo "Dry run complete. Nothing was uploaded."
    echo "Re-run with --execute to publish ${CORE_VERSION} to ${TARGET}."
    exit 0
fi

# openstax-llm first: the MCP package depends on it.
echo "== Uploading openstax-llm ${CORE_VERSION} =="
publish_package openstax-llm
echo
echo "== Uploading openstax-llm-mcp ${CORE_VERSION} =="
publish_package openstax-llm-mcp
echo

echo "== Verifying against the index =="
for pkg in openstax-llm openstax-llm-mcp; do
    confirmed=0
    for attempt in $(seq 1 24); do
        if release_listed "${pkg}" "${CORE_VERSION}"; then
            confirmed=1
            echo "  ${pkg} ${CORE_VERSION}: confirmed (after ${attempt} check(s))"
            break
        fi
        sleep 5
    done
    if [[ ${confirmed} -eq 0 ]]; then
        echo "  ${pkg} ${CORE_VERSION}: NOT VISIBLE after 120s." >&2
        echo "  The upload reported success, so check the project page before re-uploading:" >&2
        echo "  ${INDEX_CHECK}/project/${pkg}/" >&2
    fi
done

if [[ "${TARGET}" == "pypi" ]]; then
    echo
    echo "Reduce the blast radius now:"
    echo "  1. Create a project-scoped token per project at"
    echo "     https://pypi.org/manage/account/token/ and put it in UV_PUBLISH_TOKEN."
    echo "  2. Revoke the account-scoped token."
    echo "  3. Add normal Trusted Publishers so CI needs no token at all;"
    echo "     see docs/PUBLISHING.md. Both projects may then share one environment."
fi
