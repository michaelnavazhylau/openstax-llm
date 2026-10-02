# Publishing

How to release `openstax-llm` and `openstax-llm-mcp`, and what currently blocks doing so on
PyPI.

## Status: blocked on one thing

**`openstax-llm` cannot be uploaded to PyPI today**, because it declares a dependency by
Git URL:

```
Requires-Dist: openstax-md @ git+https://github.com/michaelnavazhylau/openstax-md.git
```

PyPI rejects this **server-side**:

```
400 Invalid value for requires_dist. Error: Can't have direct dependency:
'openstax-md @ git+https://github.com/michaelnavazhylau/openstax-md.git'
```

Three things make this sharper than it looks:

1. `twine check` does **not** detect it. It only validates the README and long description,
   so the failure appears after the tag is cut, at upload time.
2. PEP 508 says public indexes SHOULD NOT allow direct references, so PyPI will not be
   adding this. It is not a bug to wait out.
3. `openstax-md` is **not on PyPI** — `https://pypi.org/pypi/openstax-md/json` returns 404 —
   so the dependency cannot simply be switched to an abstract range yet.

`openstax-llm-mcp` is itself clean (`openstax-llm>=0.1.0`, `mcp>=2.0.0,<3`), but its
dependency on `openstax-llm` means it is transitively blocked too: publishing it alone
would ship a package that cannot be installed.

Reproduce the check at any time:

```bash
uv build --package openstax-llm --out-dir dist/openstax-llm
uv build --package openstax-llm-mcp --out-dir dist/openstax-llm-mcp
python scripts/check_wheel_metadata.py dist/openstax-llm/*.whl dist/openstax-llm-mcp/*.whl
```

```
openstax_llm-0.1.0-py3-none-any.whl: openstax-llm (1 requirement(s))
  openstax-md @ git+https://github.com/michaelnavazhylau/openstax-md.git  <-- DIRECT URL
  ERROR: openstax-llm declares direct URL dependencies; PyPI would reject it
```

## What it takes

### 1. Publish `openstax-md` to PyPI (the unblocking step)

That is the upstream sibling project and the same account, so it is the natural fix.
`openstax-md` depends on `lxml`, `py.typed`, and a bundled `catalog.json` — all PyPI-safe.
Once it is up:

- In `packages/openstax-llm/pyproject.toml`, change
  `"openstax-md @ git+https://github.com/michaelnavazhylau/openstax-md.git"` to
  `"openstax-md>=0.2.0"`.
- Remove `[tool.hatch.metadata] allow-direct-references = true` from that file; it exists
  only to permit the git URL.
- Drop `openstax-md` from `packages/openstax-llm/tests`-adjacent expectations: the
  `test_core_direct_dependency_is_the_known_pypi_blocker` test in
  `tests/test_skill_contract.py` asserts the *current* set, so update it to assert the empty
  set in the same commit.
- Remove `--allow openstax-llm` from the metadata gate in `.github/workflows/ci.yml`.

CI then turns green on the gate by itself, and the release workflow's publish jobs become
eligible.

### 2. Confirm the names are free

All four relevant names returned 404 (unregistered) at the time of writing:

| Name | PyPI | TestPyPI |
|---|---|---|
| `openstax-llm` | free | free |
| `openstax-llm-mcp` | free | free |
| `openstax-md` | free | — |

Re-check before registering a pending publisher, because of the caveat in step 3.

### 3. Register a pending publisher per project

At <https://pypi.org/manage/account/publishing/> — the **account** sidebar, not a project
sidebar, because the projects do not exist yet.

| Field | `openstax-llm` | `openstax-llm-mcp` |
|---|---|---|
| PyPI project name | `openstax-llm` | `openstax-llm-mcp` |
| Owner | `michaelnavazhylau` | `michaelnavazhylau` |
| Repository | `openstax-llm` | `openstax-llm` |
| Workflow filename | `release.yml` | `release.yml` |
| Environment | `pypi-openstax-llm` | `pypi-openstax-llm-mcp` |

Two caveats that shape the table:

- **A pending publisher does not reserve the name.** PyPI's own docs: it "does not create a
  project or reserve a project's name until it is actually used to publish. If another user
  registers the project name before you publish, your pending publisher will be
  invalidated." So publish reasonably soon after registering.
- **The two environments must differ.** PyPI's pending-publisher uniqueness constraint
  covers `(repository_owner, repository_name, workflow_filename, environment)` and *not* the
  project name, so registering both projects against the same environment fails with a
  generic "Sorry, something went wrong" ([pypi/warehouse#20112], closed as a duplicate of
  [#16920]; still unfixed). Distinct environment names are the reliable workaround and are
  what `release.yml` expects.

Create matching GitHub environments (`pypi-openstax-llm`, `pypi-openstax-llm-mcp`) under
**Settings → Environments**. Adding required reviewers there is worthwhile: it turns each
release into an approval gate, and the environment is part of the OIDC claim, so it is the
right place to enforce it.

[pypi/warehouse#20112]: https://github.com/pypi/warehouse/issues/20112
[#16920]: https://github.com/pypi/warehouse/issues/16920

### 4. Enable publishing

```bash
gh variable set PYPI_PUBLISH_ENABLED --body true
```

Publishing is behind two independent switches on purpose:

- `PYPI_PUBLISH_ENABLED` (repository variable), so enabling uploads is a deliberate,
  auditable change and not a side effect of tagging.
- The metadata gate must pass, so a release with a direct URL dependency can never reach
  PyPI even if the variable is set.

`release.yml` uses `id-token: write` and `pypa/gh-action-pypi-publish` with no token or
password: Trusted Publishing exchanges the GitHub OIDC identity for a short-lived, scoped
PyPI token. Nothing long-lived is stored in the repository.

### 5. Rehearse on TestPyPI first

```
Actions → Release → Run workflow → dry-run: false
```

That runs the `testpypi` job, which publishes both projects to TestPyPI and then checks that
`openstax-llm-mcp` installs and its console script starts. Register the matching pending
publishers at <https://test.pypi.org/manage/account/publishing/> first, with environment
`testpypi`.

Publishing to TestPyPI before the real thing is what catches a metadata problem while the
name is still disposable.

### 6. Cut the release

```bash
git tag v0.1.0 && git push origin v0.1.0
gh release create v0.1.0 --generate-notes
```

The `build` job fails fast if the tag does not match both `pyproject.toml` versions — a tag
that disagrees with its own artifacts cannot be undone on PyPI.

## What works today

Nothing in the pipeline is idle while the blocker stands:

- **GitHub Releases** carry fully built wheels and sdists. `build` always attaches them.
- Consumers can install from a release asset or from git today:
  `uvx --from "git+https://github.com/michaelnavazhylau/openstax-llm.git#subdirectory=packages/openstax-llm-mcp" openstax-llm-mcp`
- **Docker** images build and the CI job proves the server answers `initialize` over HTTP.
- The `openstax-llm` wheel is installable by anyone who can reach GitHub, which is the
  audience until PyPI works.

## Alternative if `openstax-md` cannot go to PyPI

Publishing `openstax-md` is by far the cleanest route. If it is genuinely not an option:

1. **Vendor it.** Move the compiler into this workspace as a third member
   (`packages/openstax-md`). `uv build --package` then produces a wheel to upload to PyPI,
   and `openstax-llm` depends on it by an abstract range. Costs the separate release cycle
   that the current split buys.
2. **Ship a private index.** Publish to a self-hosted index (devpi, Artifactory, Google
   Artifact Registry) that permits direct references. PyPI stays unbuildable, but
   `pip install --index-url` works. Adds an index to operate and authenticate.
3. **Drop the dependency.** Reimplement the CNXML-to-markdown compilation inside this
   project. Substantial duplicated work in a mature, separately maintained codebase.

Option 1 is the only one that ends with both packages installable from PyPI by the plain
commands the README promises (`uv add openstax-llm`, `uvx openstax-llm-mcp`).

## Versioning

Both workspace members release in lockstep; `tests/test_skill_contract.py` enforces that
their versions agree, that `openstax-llm-mcp` requires `openstax-llm>=<version>`, and that
the skill's declared `min_library_version` shares a major/minor with the library. Bump
`packages/*/pyproject.toml`, the `__version__` in
`packages/openstax-llm/src/openstax_llm/__init__.py`, and the fallback in
`packages/openstax-llm-mcp/src/openstax_llm_mcp/_version.py` together, or the tests will
fail before the tag does.
