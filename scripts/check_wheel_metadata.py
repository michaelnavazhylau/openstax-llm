#!/usr/bin/env python3
"""Fail if any built wheel declares a PEP 508 direct URL dependency.

PyPI rejects such uploads server-side with::

    400 Invalid value for requires_dist. Error: Can't have direct dependency: ...

and ``twine check`` does not catch it, so the failure otherwise surfaces only at publish
time, after the release has been tagged. Run this against ``dist/*.whl`` before uploading.

Usage::

    python scripts/check_wheel_metadata.py dist/*.whl
    python scripts/check_wheel_metadata.py --allow openstax-llm dist/*.whl

``--allow`` names distributions that are permitted to carry a direct URL dependency, for
packages with a known blocker that are being released anyway (GitHub-release artifacts,
private indexes). Anything not listed is a hard failure.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from email.parser import Parser
from pathlib import Path


def requires_dist(wheel: Path) -> tuple[str, list[str]]:
    """Return ``(distribution_name, requires_dist)`` for a wheel."""
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(
            (name for name in archive.namelist() if name.endswith(".dist-info/METADATA")),
            None,
        )
        if metadata_path is None:
            raise ValueError(f"{wheel} has no .dist-info/METADATA entry")
        metadata = Parser().parsestr(archive.read(metadata_path).decode("utf-8"))

    name = metadata.get("Name")
    if not name:
        raise ValueError(f"{wheel} has no Name in its metadata")
    return name, list(metadata.get_all("Requires-Dist") or [])


def is_direct_reference(requirement: str) -> bool:
    """True for `pkg @ git+https://...` and friends; False for `pkg>=1.0`."""
    if " @ " not in requirement:
        return False
    _, _, target = requirement.partition(" @ ")
    return "://" in target or target.startswith(("git+", "file:"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wheels", nargs="+", type=Path)
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="DIST",
        help="Distribution name permitted to declare a direct URL dependency (repeatable)",
    )
    args = parser.parse_args(argv)

    allowed = {name.lower().replace("_", "-") for name in args.allow}
    failed = False

    for wheel in args.wheels:
        name, requires = requires_dist(wheel)
        normalized = name.lower().replace("_", "-")
        direct = [req for req in requires if is_direct_reference(req)]

        print(f"{wheel.name}: {name} ({len(requires)} requirement(s))")
        for requirement in requires:
            marker = "  <-- DIRECT URL" if is_direct_reference(requirement) else ""
            print(f"  {requirement}{marker}")

        if direct and normalized not in allowed:
            print(f"  ERROR: {name} declares direct URL dependencies; PyPI would reject it:")
            for requirement in direct:
                print(f"    {requirement}")
            failed = True
        elif direct:
            print(f"  NOTICE: {name} is explicitly allowed to carry a direct URL dependency")

    if failed:
        print(
            "\nFix it by publishing the referenced project to PyPI and depending on it by "
            "an abstract version range, or add the distribution to --allow if it is "
            "intentionally not released to PyPI."
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
