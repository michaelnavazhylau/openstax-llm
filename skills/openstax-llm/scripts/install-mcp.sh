#!/usr/bin/env bash
#
# Register the openstax-llm MCP server with an available agent.
#
# Registration is a user-visible change, so this script reports what it did and how to
# undo it. It never installs anything on its own beyond the MCP server command itself.
#
# Usage: install-mcp.sh [--agent pi|claude-code|print] [--scope project|user]

set -euo pipefail

GIT_URL="https://github.com/michaelnavazhylau/openstax-llm.git"
SERVER_NAME="openstax-llm"

AGENT=""
SCOPE="user"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent) AGENT="${2:?--agent needs a value}"; shift 2 ;;
        --scope) SCOPE="${2:?--scope needs a value}"; shift 2 ;;
        -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "error: unknown argument '$1'" >&2; exit 2 ;;
    esac
done

if [[ "${SCOPE}" != "project" && "${SCOPE}" != "user" ]]; then
    echo "error: --scope must be 'project' or 'user', got '${SCOPE}'" >&2
    exit 2
fi

# Prefer PyPI; fall back to the workspace member via the `subdirectory` fragment.
# Prints a '|'-separated argv: the command first, then its arguments.
server_argv() {
    if uvx openstax-llm-mcp --version >/dev/null 2>&1; then
        printf 'uvx|openstax-llm-mcp'
    else
        printf 'uvx|--from|git+%s#subdirectory=packages/openstax-llm-mcp|openstax-llm-mcp' "${GIT_URL}"
    fi
}

print_config() {
    local IFS='|'
    local -a argv
    read -r -a argv <<<"$(server_argv)"

    # Generate the JSON with Python rather than string surgery, so the fallback's many
    # arguments stay separate array elements instead of one malformed string.
    python3 -c '
import json, sys

command, *args = sys.argv[1:]
print(json.dumps(
    {"mcpServers": {"openstax-llm": {
        "command": command,
        "args": args,
        "description": "Chunk OpenStax textbooks into citation-aware RAG datasets",
    }}},
    indent=2,
))
' "${argv[@]}"

    echo
    echo "For Pi, write this to .pi/mcp.json (project) or ~/.pi/agent/mcp.json (user),"
    echo "then run /reload. For Claude Code, prefer 'claude mcp add' so credentials and"
    echo "scope are handled for you."
}

register_pi() {
    echo "Registering with Pi (scope: ${SCOPE})"
    # `uvx` fetches and caches the server on first use.
    if ! uvx openstax-llm-mcp --version >/dev/null 2>&1; then
        echo "  Note: 'uvx openstax-llm-mcp' did not resolve just now. If the release is not"
        echo "  on PyPI yet, register the git form printed by 'install-mcp.sh --agent print'."
    fi
    local scope_flag=()
    [[ "${SCOPE}" == "project" ]] && scope_flag=(-l)
    pi mcp add "${scope_flag[@]}" "${SERVER_NAME}" -- uvx openstax-llm-mcp
    echo "  Verify with: pi mcp list"
    echo "  Undo with:   pi mcp remove ${SERVER_NAME}"
}

register_claude() {
    echo "Registering with Claude Code (scope: ${SCOPE})"
    local scope_flag=(--scope user)
    [[ "${SCOPE}" == "project" ]] && scope_flag=(--scope project)
    claude mcp add "${scope_flag[@]}" "${SERVER_NAME}" -- uvx openstax-llm-mcp
    echo "  Verify with: claude mcp list"
    echo "  Undo with:   claude mcp remove ${SERVER_NAME}"
}

if [[ -z "${AGENT}" ]]; then
    if command -v pi >/dev/null 2>&1; then AGENT="pi"
    elif command -v claude >/dev/null 2>&1; then AGENT="claude-code"
    else AGENT="print"
    fi
fi

case "${AGENT}" in
    pi)
        register_pi
        ;;
    claude-code|claude)
        register_claude
        ;;
    print)
        echo "No supported agent CLI detected; printing configuration instead."
        print_config
        ;;
    *)
        echo "error: unsupported --agent '${AGENT}' (expected pi, claude-code, or print)" >&2
        exit 2
        ;;
esac

echo
echo "The server serves stdio by default. For shared or container use, run it directly:"
echo "  openstax-llm-mcp --http --host 0.0.0.0 --allow-host <hostname> --allow-host <hostname>:*"
