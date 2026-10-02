"""Enforce the contract between the agent skill, the chunk schema, and the packages.

The skill is distributed by copying a directory and hashing it, so it can silently drift
from the library it documents. These tests are the drift detector: they fail when the
documented schema, the referenced files, the declared versions, or the PyPI-safety of the
packaging metadata stop matching reality.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import jsonschema
import pytest

try:  # tomllib is stdlib from 3.11; the CI matrix still covers 3.10.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

import openstax_llm
import openstax_llm_mcp
from openstax_llm.chunker import PedagogicalChunk

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "openstax-llm"
SKILL_MD = SKILL_DIR / "SKILL.md"
SCHEMA_PATH = SKILL_DIR / "assets" / "chunk.schema.json"

CORE_PYPROJECT = REPO_ROOT / "packages" / "openstax-llm" / "pyproject.toml"
MCP_PYPROJECT = REPO_ROOT / "packages" / "openstax-llm-mcp" / "pyproject.toml"

#: A PEP 508 direct URL reference, e.g. `openstax-md @ git+https://...`.
DIRECT_REFERENCE = re.compile(r"@\s*(git\+|https?://|file://)")


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def scalar(value: str) -> str:
    return value.strip().strip('"').strip("'")


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse the flat-plus-one-nested-map frontmatter the skill uses, without PyYAML."""
    assert text.startswith("---"), "SKILL.md must open with a --- frontmatter block"
    end = text.index("\n---", 3)
    data: dict[str, Any] = {}
    nested: dict[str, Any] | None = None

    for raw in text[4:end].splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0] in " \t":
            assert nested is not None, f"indented key without a parent map: {raw!r}"
            key, _, value = raw.strip().partition(":")
            nested[key.strip()] = scalar(value)
            continue
        key, _, value = raw.partition(":")
        if not value.strip():
            nested = {}
            data[key.strip()] = nested
            continue
        nested = None
        data[key.strip()] = scalar(value)

    return data


@pytest.fixture(scope="module")
def frontmatter() -> dict[str, Any]:
    return parse_frontmatter(SKILL_MD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def major_minor(version: str) -> tuple[int, int]:
    parts = version.split(".")
    return int(parts[0]), int(parts[1])


# ------------------------------------------------------------------- skill packaging


def test_skill_directory_matches_frontmatter_name(frontmatter: dict[str, Any]) -> None:
    assert frontmatter["name"] == SKILL_DIR.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", frontmatter["name"])
    assert len(frontmatter["name"]) <= 64


def test_description_is_within_spec_and_routes(frontmatter: dict[str, Any]) -> None:
    description = frontmatter["description"]
    assert len(description) <= 1024, "Agent Skills spec caps descriptions at 1024 chars"
    # A description that only says what the skill is will not be selected at the right
    # moment; it has to name the triggers.
    for trigger in ("RAG", "fine-tuning", "chunk", "LaTeX"):
        assert trigger.lower() in description.lower(), f"description never mentions {trigger!r}"


def test_skill_lives_where_the_skills_cli_looks() -> None:
    """`prioritySearchDirs` includes `<repo>/skills`, walked three levels deep."""
    assert SKILL_MD.is_file()
    assert SKILL_MD.parent.parent == REPO_ROOT / "skills"


# --------------------------------------------------------------- referenced discovery


def test_every_reference_file_is_listed_in_skill_md(frontmatter: dict[str, Any]) -> None:
    body = SKILL_MD.read_text(encoding="utf-8")
    on_disk = {path.name for path in (SKILL_DIR / "references").glob("*.md")}
    # Wrapper-agnostic: matches a bare path and a markdown link alike.
    listed = set(re.findall(r"references/([\w.-]+\.md)", body))
    assert listed == on_disk, "SKILL.md's reference table and references/ disagree"


def test_every_script_is_listed_and_executable(frontmatter: dict[str, Any]) -> None:
    body = SKILL_MD.read_text(encoding="utf-8")
    on_disk = {path.name for path in (SKILL_DIR / "scripts").glob("*.sh")}
    listed = set(re.findall(r"scripts/([\w.-]+\.sh)", body))
    assert listed == on_disk, "SKILL.md's script table and scripts/ disagree"

    for name in sorted(on_disk):
        path = SKILL_DIR / "scripts" / name
        assert path.stat().st_mode & 0o111, f"{name} is not executable"


@pytest.mark.parametrize(
    "script",
    sorted((SKILL_DIR / "scripts").glob("*.sh")),
    ids=lambda path: path.name,
)
def test_scripts_pass_bash_syntax_check(script: Path) -> None:
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_relative_links_in_skill_md_resolve() -> None:
    """Every relative link must point at something that ships with the skill."""
    body = SKILL_MD.read_text(encoding="utf-8")
    targets = re.findall(r"\]\((?!#)([^)]+)\)", body)
    assert targets, "expected the reference and script tables to use relative links"
    for target in targets:
        assert not target.startswith(("http://", "https://")), "use inline prose for URLs"
        assert (SKILL_DIR / target).exists(), f"dangling link: {target}"


# ------------------------------------------------------------------- schema contract


def test_schema_fields_match_the_chunk_dataclass(schema: dict[str, Any]) -> None:
    produced = set(PedagogicalChunk(chunk_id="x", text="y").to_dict())
    assert set(schema["properties"]) == produced
    assert set(schema["required"]) == produced
    assert schema["additionalProperties"] is False


def test_schema_chunk_type_enum_matches_the_chunker(schema: dict[str, Any]) -> None:
    documented = set(schema["properties"]["chunk_type"]["enum"])
    source = (REPO_ROOT / "packages/openstax-llm/src/openstax_llm/chunker.py").read_text()
    declared = set(re.findall(r"#\s*prose, ([\w, ]+)", source)[0].replace(" ", "").split(","))
    assert documented == declared | {"prose"}


def test_schema_is_a_valid_json_schema(schema: dict[str, Any]) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)


def test_schema_accepts_and_rejects_as_documented(schema: dict[str, Any]) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    good = PedagogicalChunk(chunk_id="1.2-c001", text="Math $x^2$.", section="1.2").to_dict()
    validator.validate(good)

    with pytest.raises(jsonschema.ValidationError):
        validator.validate({**good, "chunk_type": "not-a-real-type"})
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({**good, "word_count": -1})
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({key: value for key, value in good.items() if key != "section"})


# --------------------------------------------------------------- version consistency


def test_versions_agree_across_packages_and_skill(frontmatter: dict[str, Any]) -> None:
    core = load_toml(CORE_PYPROJECT)["project"]["version"]
    mcp = load_toml(MCP_PYPROJECT)["project"]["version"]
    declared = frontmatter["metadata"]["min_library_version"]

    assert core == openstax_llm.__version__, "core pyproject and __version__ disagree"
    assert mcp == openstax_llm_mcp.__version__, "mcp pyproject and __version__ disagree"
    assert core == mcp, "workspace members release in lockstep"

    assert major_minor(declared) == major_minor(core), (
        f"skill documents {declared} but the library is {core}; a major/minor bump means the "
        "documented schema must be revisited"
    )
    assert major_minor(declared) <= major_minor(core), "skill cannot require an unreleased version"


def test_mcp_package_pins_the_core_version_range() -> None:
    core = load_toml(CORE_PYPROJECT)["project"]["version"]
    dependency = next(
        dep
        for dep in load_toml(MCP_PYPROJECT)["project"]["dependencies"]
        if dep.startswith("openstax-llm")
    )
    assert f">={core}" in dependency, f"mcp should require >= the released core, got {dependency!r}"


def test_mcp_distribution_has_no_direct_url_dependency() -> None:
    """PyPI rejects uploads whose Requires-Dist holds a direct URL.

    This distribution must stay publishable, so an abstract range is required here. The
    known exception is the core package's `openstax-md` git dependency, which is tracked in
    the publishing notes rather than silently reintroduced.
    """
    dependencies = load_toml(MCP_PYPROJECT)["project"]["dependencies"]
    offenders = [dep for dep in dependencies if DIRECT_REFERENCE.search(dep)]
    assert offenders == []


def test_core_direct_dependency_is_the_known_pypi_blocker() -> None:
    """Guards the exception above: adding a *second* direct URL is a new blocker."""
    dependencies = load_toml(CORE_PYPROJECT)["project"]["dependencies"]
    offenders = [dep for dep in dependencies if DIRECT_REFERENCE.search(dep)]
    assert offenders == [
        "openstax-md @ git+https://github.com/michaelnavazhylau/openstax-md.git"
    ], (
        "core's direct URL dependency set changed; PyPI publishing is blocked until "
        "openstax-md is itself on PyPI, so this must be a deliberate change"
    )


def test_uv_sources_are_workspace_local() -> None:
    """`[tool.uv.sources]` must not leak into published metadata."""
    for path in (CORE_PYPROJECT, MCP_PYPROJECT):
        sources = load_toml(path).get("tool", {}).get("uv", {}).get("sources", {})
        for target, spec in sources.items():
            assert spec == {"workspace": True}, f"{path.name}: unexpected source for {target}"
