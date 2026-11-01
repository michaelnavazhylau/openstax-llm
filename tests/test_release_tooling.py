"""Tests for the release gate in scripts/check_wheel_metadata.py.

That script is the only thing standing between a tagged release and a 400 from PyPI, and
PyPI has no way to undo a partially-uploaded release. It deserves the same test treatment
as library code.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import zipfile
from email.message import Message
from pathlib import Path

import pytest

import openstax_llm

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_wheel_metadata.py"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
README = REPO_ROOT / "README.md"

#: The one registry the container is published to, and the image a consumer pulls.
IMAGE = "ghcr.io/michaelnavazhylau/openstax-llm-mcp"


def load_module():
    spec = importlib.util.spec_from_file_location("check_wheel_metadata", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_wheel_metadata"] = module
    spec.loader.exec_module(module)
    return module


check = load_module()


def make_wheel(path: Path, name: str, requires: list[str]) -> Path:
    """Write a minimal but structurally real wheel with the given Requires-Dist."""
    metadata = Message()
    metadata["Metadata-Version"] = "2.1"
    metadata["Name"] = name
    metadata["Version"] = "0.1.0"
    for requirement in requires:
        metadata["Requires-Dist"] = requirement

    dist_info = f"{name.replace('-', '_')}-0.1.0.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata.as_string())
        archive.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\n")
    return path


@pytest.mark.parametrize(
    "requirement",
    [
        "openstax-md @ git+https://github.com/michaelnavazhylau/openstax-md.git",
        "pkg @ https://example.com/pkg.whl",
        "pkg @ file:///tmp/pkg",
        "pkg[extra] @ git+ssh://git@example.com/x/y.git",
    ],
)
def test_direct_references_are_detected(requirement: str) -> None:
    assert check.is_direct_reference(requirement) is True


@pytest.mark.parametrize(
    "requirement",
    ["openstax-llm>=0.1.0", "mcp>=2.0.0,<3", "openstax-llm==0.1.0", 'pkg; python_version < "3.11"'],
)
def test_abstract_requirements_are_not_flagged(requirement: str) -> None:
    assert check.is_direct_reference(requirement) is False


def test_clean_wheel_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wheel = make_wheel(tmp_path / "clean.whl", "openstax-llm-mcp", ["mcp>=2.0.0,<3"])
    assert check.main([str(wheel)]) == 0
    assert "DIRECT URL" not in capsys.readouterr().out


def test_dirty_wheel_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wheel = make_wheel(
        tmp_path / "dirty.whl", "openstax-llm", ["openstax-md @ git+https://example.com/md.git"]
    )
    assert check.main([str(wheel)]) == 1
    assert "ERROR" in capsys.readouterr().out


def test_allow_list_admits_an_explicitly_permitted_package(tmp_path: Path) -> None:
    """`--allow` stays available for GitHub-release-only artifacts."""
    wheel = make_wheel(
        tmp_path / "dirty.whl", "openstax-llm", ["openstax-md @ git+https://example.com/md.git"]
    )
    assert check.main(["--allow", "openstax-llm", str(wheel)]) == 0


def test_allow_list_matches_underscored_distribution_names(tmp_path: Path) -> None:
    """Wheel filenames use underscores; --allow should not care."""
    wheel = make_wheel(
        tmp_path / "dirty.whl", "openstax-llm", ["openstax-md @ git+https://example.com/md.git"]
    )
    assert check.main(["--allow", "openstax_llm", str(wheel)]) == 0


def test_one_dirty_wheel_fails_the_whole_run(tmp_path: Path) -> None:
    clean = make_wheel(tmp_path / "clean.whl", "openstax-llm-mcp", ["openstax-llm>=0.1.0"])
    dirty = make_wheel(
        tmp_path / "dirty.whl", "openstax-llm", ["openstax-md @ git+https://example.com/md.git"]
    )
    assert check.main([str(clean), str(dirty)]) == 1
    # Allowing only the clean package must not rescue the dirty one.
    assert check.main(["--allow", "openstax-llm-mcp", str(clean), str(dirty)]) == 1


def test_missing_metadata_is_reported(tmp_path: Path) -> None:
    broken = tmp_path / "broken.whl"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("nothing/here.txt", "empty")
    with pytest.raises(ValueError, match="no .dist-info/METADATA"):
        check.requires_dist(broken)


def test_real_built_wheels_are_classified_correctly() -> None:
    """Guards the actual release decision against the real artifacts, when present."""
    dist = REPO_ROOT / "dist"
    wheels = sorted(dist.glob("**/*.whl"))
    if not wheels:
        pytest.skip("run `uv build --package <name> --out-dir dist/<name>` to produce wheels")

    failing = {wheel for wheel in wheels if check.main([str(wheel)]) != 0}
    names = {check.requires_dist(wheel)[0] for wheel in failing}
    # No member may carry a direct URL now that openstax-md is on PyPI. If this fails, the
    # gate genuinely caught something: do not blanket-allow it here.
    assert names == set(), f"PyPI blockers in built wheels: {names}. See docs/PUBLISHING.md"


# ------------------------------------------------------------ container release (GHCR)


def test_container_is_published_only_to_ghcr() -> None:
    """One registry, one credential story.

    Docker Hub needs an account-scoped PAT and caps anonymous pulls; GHCR needs neither. A
    second registry means a second push that can half-succeed across arch manifests, so this
    asserts the choice rather than leaving it to convention.
    """
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "ghcr.io" in workflow
    for forbidden in ("docker.io", "registry.hub.docker.com", "DOCKERHUB"):
        assert forbidden not in workflow, f"release.yml still references {forbidden}"
    assert "registry: ghcr.io" in workflow, "the GHCR login registry changed"


def test_latest_tag_is_release_gated() -> None:
    """`latest` must not be movable by a dispatch from an arbitrary commit."""
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    latest = [line.strip() for line in workflow.splitlines() if "value=latest" in line]
    assert latest, "no `latest` tag rule in the workflow"
    assert all("github.event_name == 'release'" in line for line in latest), latest
    assert all("contains(github.ref_name, '-')" in line for line in latest), (
        "a prerelease tag must not move `latest`"
    )


def test_container_publish_is_gated_on_a_repository_variable() -> None:
    """Pushing an image is deliberate, like pushing to PyPI, not a release side effect."""
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "vars.CONTAINER_PUBLISH_ENABLED == 'true'" in workflow


def test_dockerfile_pins_its_base_images_by_digest() -> None:
    """An image is only as reproducible as its inputs.

    A floating `python:3.12-slim-bookworm` or `uv:latest` means whichever upstream push
    happened last decides what a `v0.1.0` container contains — the same "mutable ref controls
    what ships" problem this repository removed from its install scripts.
    """
    external = re.findall(r"^(?:FROM|COPY --from=)\s*(\S+)", DOCKERFILE.read_text(), re.M)
    assert external, "no external image references found in the Dockerfile"
    unpinned = [
        ref for ref in external if not ref.startswith(("builder", "${")) and "@sha256:" not in ref
    ]
    assert unpinned == [], f"Dockerfile images are not digest-pinned: {unpinned}"


def test_dockerfile_links_the_image_to_this_repository() -> None:
    """Without the `source` label a GHCR package is an orphan nobody can trace to a commit."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert (
        'org.opencontainers.image.source="https://github.com/michaelnavazhylau/openstax-llm"'
        in dockerfile
    )
    assert 'org.opencontainers.image.version="${VERSION}"' in dockerfile
    assert 'org.opencontainers.image.revision="${REVISION}"' in dockerfile


def test_readme_pins_the_published_image_to_the_current_version() -> None:
    """The front page is not regenerated on release, so the tag is drift-checked here."""
    readme = README.read_text(encoding="utf-8")
    assert f"{IMAGE}:{openstax_llm.__version__}" in readme, (
        f"README.md does not reference {IMAGE}:{openstax_llm.__version__}; update the pinned "
        "tag when the version changes"
    )
