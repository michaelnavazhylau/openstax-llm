#!/usr/bin/env python3
"""Warn or fail when the agent skill is absent from the skills.sh directory.

skills.sh has no submission API. A skill becomes installable the moment the repository is
public, but it is *listed* — with an install count, a detail page, and a security audit —
only after an offline aggregation of anonymous install telemetry from
``npx skills add <owner>/<repo>``. Nothing in this repository can observe that, so this
check polls the same public endpoint the website's own search box uses::

    GET https://www.skills.sh/api/search?q=<skill>&limit=200

(Authenticated ``/api/v1/`` endpoints require a Vercel OIDC token and are deliberately not
used here; CI has no such token and should not need one to answer this question.)

Exit codes::

    0  listed, or absent while ``--require-listed`` was not passed (warning only)
    1  absent and ``--require-listed`` was passed
    2  the directory could not be read (network, HTTP, or malformed payload)

Usage::

    python3 scripts/check_skills_directory.py
    python3 scripts/check_skills_directory.py --require-listed
    python3 scripts/check_skills_directory.py --owner someuser/somerepo --skill some-skill
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

DEFAULT_SOURCE = "michaelnavazhylau/openstax-llm"
DEFAULT_SKILL = "openstax-llm"
DEFAULT_BASE_URL = "https://www.skills.sh"
DEFAULT_LIMIT = 200
DEFAULT_TIMEOUT = 20.0

# A fetcher returns the decoded JSON payload for a URL. Tests pass a fake; production uses
# `http_get_json`. HTTP failures must raise so they cannot be mistaken for "not listed".
Fetcher = Callable[[str, float], Any]


class DirectoryError(RuntimeError):
    """The directory could not be read, so no conclusion about listing is possible."""


def http_get_json(url: str, timeout: float) -> Any:
    """Fetch and decode a JSON document, raising `DirectoryError` on any failure."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "openstax-llm-skills-directory-check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DirectoryError(f"{url}: {error}") from error
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise DirectoryError(f"{url}: response was not JSON ({error})") from error


def search_url(base_url: str, query: str, limit: int) -> str:
    """Build the public search URL, quoting the query so slugs with dots still work."""
    params = urllib.parse.urlencode({"q": query, "limit": limit})
    return f"{base_url.rstrip('/')}/api/search?{params}"


def parse_payload(payload: Any, url: str) -> list[dict[str, Any]]:
    """Extract the skill entries, rejecting payloads we cannot interpret as success."""
    if not isinstance(payload, dict):
        raise DirectoryError(f"{url}: expected a JSON object, got {type(payload).__name__}")
    skills = payload.get("skills")
    if not isinstance(skills, list):
        raise DirectoryError(f"{url}: payload has no 'skills' list")
    return [entry for entry in skills if isinstance(entry, dict)]


def find_skill(skills: Sequence[dict[str, Any]], source: str, skill: str) -> dict[str, Any] | None:
    """Return the entry whose id is exactly `<source>/<skill>`.

    The endpoint is a fuzzy search, so anything short of an exact id match would happily
    accept a similarly named skill from another repository.
    """
    wanted = f"{source}/{skill}"
    for entry in skills:
        if entry.get("id") == wanted:
            return entry
    return None


def sibling_slugs(skills: Sequence[dict[str, Any]], source: str) -> list[str]:
    """Slugs the source repository *is* listed under, for a more useful warning."""
    prefix = f"{source}/"
    return sorted(
        str(entry["id"])[len(prefix) :]
        for entry in skills
        if isinstance(entry.get("id"), str) and str(entry["id"]).startswith(prefix)
    )


def skill_page_url(base_url: str, source: str, skill: str) -> str:
    return f"{base_url.rstrip('/')}/{source}/{skill}"


def display_name(source: str, skill: str) -> str:
    """`owner/repo` when the repo *is* the skill, else `owner/repo/skill`.

    For most repositories the skill lives in a directory named after the repo, and printing
    `owner/repo/repo` in a warning reads like a bug.
    """
    if source.rsplit("/", 1)[-1] == skill:
        return source
    return f"{source}/{skill}"


def build_report(
    skills: Sequence[dict[str, Any]], source: str, skill: str, base_url: str
) -> dict[str, Any]:
    """The single source of truth for both the human and `--json` output."""
    entry = find_skill(skills, source, skill)
    url = skill_page_url(base_url, source, skill)
    if entry is None:
        return {
            "status": "missing",
            "source": source,
            "skill": skill,
            "url": url,
            "installs": None,
            "sourceSlugs": sibling_slugs(skills, source),
        }
    installs = entry.get("installs")
    return {
        "status": "listed",
        "source": source,
        "skill": skill,
        "url": str(entry.get("url") or url),
        "installs": installs if isinstance(installs, int) else 0,
        "sourceSlugs": [],
    }


def render(report: dict[str, Any], install_command: str) -> list[str]:
    """Lines for stdout, using GitHub annotations so the warning is visible in CI."""
    if report["status"] == "listed":
        return [
            f"listed on skills.sh: {display_name(report['source'], report['skill'])}",
            f"  installs: {report['installs']}",
            f"  page:     {report['url']}",
        ]
    lines = [
        f"::warning title=Not listed on skills.sh::"
        f"{display_name(report['source'], report['skill'])} "
        "has no skills.sh directory entry yet. Listing is aggregated from anonymous "
        "install telemetry, so it appears only after a real install "
        f"({install_command}); the skill is installable from GitHub until then."
    ]
    if report["sourceSlugs"]:
        lines.append(f"  {report['source']} is listed under: {', '.join(report['sourceSlugs'])}")
    return lines


def main(argv: Sequence[str] | None = None, *, fetch: Fetcher = http_get_json) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="owner/repo hosting the skill")
    parser.add_argument("--skill", default=DEFAULT_SKILL, help="skill directory name")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--require-listed",
        action="store_true",
        help="exit 1 when the skill is missing, instead of warning",
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    url = search_url(args.base_url, args.skill, args.limit)
    try:
        skills = parse_payload(fetch(url, args.timeout), url)
    except DirectoryError as error:
        print(f"::error title=skills.sh unreachable::could not read the directory: {error}")
        return 2

    report = build_report(skills, args.source, args.skill, args.base_url)
    install_command = f"npx skills add {args.source}"

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for line in render(report, install_command):
            print(line)

    if report["status"] == "listed":
        return 0
    if args.require_listed:
        print(f"::error title=Not listed on skills.sh::run `{install_command}` to trigger listing")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
