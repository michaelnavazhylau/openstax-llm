"""Tests for the release gate in scripts/check_wheel_metadata.py.

That script is the only thing standing between a tagged release and a 400 from PyPI, and
PyPI has no way to undo a partially-uploaded release. It deserves the same test treatment
as library code.
"""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from email.message import Message
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_wheel_metadata.py"


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
