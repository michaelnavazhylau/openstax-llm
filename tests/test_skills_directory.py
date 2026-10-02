"""Tests for the skills.sh listing check in scripts/check_skills_directory.py.

skills.sh has no submission API, so the only evidence that the skill is listed is an
external, undocumented search endpoint that lags install telemetry. The check therefore
has to be very careful about the difference between "not listed" and "could not ask":
a network blip must never look like a missing directory entry, and a fuzzy search hit must
never look like an exact one.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_skills_directory.py"
SOURCE = "michaelnavazhylau/openstax-llm"
SKILL = "openstax-llm"


def load_module() -> Any:
    spec = importlib.util.spec_from_file_location("check_skills_directory", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_skills_directory"] = module
    spec.loader.exec_module(module)
    return module


check = load_module()


def entry(skill_id: str, installs: int = 42) -> dict[str, Any]:
    return {"id": skill_id, "slug": skill_id.rsplit("/", 1)[-1], "installs": installs}


def fetcher_returning(payload: Any) -> Any:
    def fetch(url: str, timeout: float) -> Any:
        return payload

    return fetch


def fetcher_failing(error: Exception) -> Any:
    def fetch(url: str, timeout: float) -> Any:
        raise error

    return fetch


TARGET = f"{SOURCE}/{SKILL}"


def test_search_url_quotes_the_query_and_tolerates_a_trailing_slash() -> None:
    url = check.search_url("https://www.skills.sh/", SKILL, 200)
    assert url == "https://www.skills.sh/api/search?q=openstax-llm&limit=200"


def test_search_url_encodes_a_query_with_spaces() -> None:
    assert "q=open+stax" in check.search_url("https://www.skills.sh", "open stax", 5)


def test_display_name_avoids_repeating_the_repo_name() -> None:
    assert check.display_name(SOURCE, SKILL) == SOURCE
    assert (
        check.display_name("vercel-labs/skills", "find-skills") == "vercel-labs/skills/find-skills"
    )


def test_find_skill_requires_an_exact_id() -> None:
    """A fuzzy search hit from a similarly named repo must not count as a listing."""
    skills = [entry("someone-else/openstax-llm/openstax-llm"), entry(f"{SOURCE}/other-skill")]
    assert check.find_skill(skills, SOURCE, SKILL) is None
    assert check.find_skill([*skills, entry(TARGET)], SOURCE, SKILL) is not None


def test_parse_payload_drops_entries_that_are_not_objects() -> None:
    assert check.parse_payload({"skills": [entry(TARGET), "junk", 3]}, "url") == [entry(TARGET)]


def test_listed_skill_exits_zero_and_reports_installs(capsys: pytest.CaptureFixture[str]) -> None:
    assert check.main(["--json"], fetch=fetcher_returning({"skills": [entry(TARGET, 7)]})) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "listed"
    assert report["installs"] == 7
    assert report["url"] == f"https://www.skills.sh/{SOURCE}/{SKILL}"


def test_listed_skill_prints_a_human_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert check.main([], fetch=fetcher_returning({"skills": [entry(TARGET, 1234)]})) == 0
    out = capsys.readouterr().out
    assert "listed on skills.sh" in out
    assert "1234" in out
    assert "::warning" not in out


def test_missing_skill_warns_without_failing(capsys: pytest.CaptureFixture[str]) -> None:
    """Warn-only is the default: an unlisted skill is not something CI can fix."""
    payload = {"skills": [entry("expo/skills/react-native")]}
    assert check.main([], fetch=fetcher_returning(payload)) == 0
    out = capsys.readouterr().out
    assert "::warning" in out
    assert f"npx skills add {SOURCE}" in out
    assert f"{SOURCE}/{SKILL}" not in out, "the warning should not print owner/repo/repo"


def test_require_listed_turns_a_missing_skill_into_a_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = check.main(["--require-listed"], fetch=fetcher_returning({"skills": []}))
    assert code == 1
    assert "::error" in capsys.readouterr().out


def test_a_listed_skill_passes_even_with_require_listed() -> None:
    payload = {"skills": [entry(TARGET)]}
    assert check.main(["--require-listed"], fetch=fetcher_returning(payload)) == 0


def test_siblings_in_the_same_repo_are_surfaced(capsys: pytest.CaptureFixture[str]) -> None:
    """Partial indexing is the confusing case; name the slug that is listed."""
    payload = {"skills": [entry(f"{SOURCE}/some-other-skill")]}
    assert check.main([], fetch=fetcher_returning(payload)) == 0
    assert "some-other-skill" in capsys.readouterr().out


def test_sibling_slugs_only_lists_the_same_source() -> None:
    skills = [entry(f"{SOURCE}/a"), entry(f"{SOURCE}/b"), entry("expo/skills/c")]
    assert check.sibling_slugs(skills, SOURCE) == ["a", "b"]


def test_unreadable_directory_is_an_error_not_a_missing_listing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A network failure must not be reported as 'not listed' — that would be a lie."""
    error = check.DirectoryError("boom")
    assert check.main([], fetch=fetcher_failing(error)) == 2
    out = capsys.readouterr().out
    assert "::error" in out
    assert "::warning" not in out


@pytest.mark.parametrize("payload", [[], "not json", {"nope": []}, {"skills": "nope"}])
def test_uninterpretable_payloads_are_errors(
    payload: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check.main([], fetch=fetcher_returning(payload)) == 2
    assert "::error" in capsys.readouterr().out


def test_http_get_json_raises_directory_error_on_unreachable_host() -> None:
    with pytest.raises(check.DirectoryError):
        # A closed local port: fails immediately and needs no network access.
        check.http_get_json("http://127.0.0.1:9/api/search", 1.0)


def test_default_target_matches_the_skill_this_repo_ships() -> None:
    """The nightly job checks a hardcoded name; keep it tied to the real skill."""
    assert check.DEFAULT_SKILL == SKILL
    assert (REPO_ROOT / "skills" / check.DEFAULT_SKILL / "SKILL.md").is_file()
    assert check.DEFAULT_SOURCE.endswith(f"/{check.DEFAULT_SKILL}")


@pytest.mark.skipif(
    not os.environ.get("OPENSTAX_LLM_NETWORK_TESTS"),
    reason="set OPENSTAX_LLM_NETWORK_TESTS=1 to poll the live skills.sh directory",
)
def test_live_directory_is_readable() -> None:
    """The endpoint is undocumented; this fails loudly when it changes shape.

    It asserts readability, not listing: whether skills.sh has ingested our telemetry yet
    is outside this repository's control.
    """
    skills = check.parse_payload(
        check.http_get_json(check.search_url(check.DEFAULT_BASE_URL, SKILL, 200), 20.0),
        "live",
    )
    report = check.build_report(skills, SOURCE, SKILL, check.DEFAULT_BASE_URL)
    assert report["status"] in {"listed", "missing"}
