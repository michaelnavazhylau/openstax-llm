# Publishing

How to release `openstax-llm` and `openstax-llm-mcp` to PyPI.

## Status: ready to publish

The blocker is cleared. `openstax-md` is on PyPI at **0.2.0**, so `openstax-llm` now depends
on it by abstract version range (`openstax-md>=0.2.0`) instead of a git URL, and both wheels
pass the metadata gate:

```
openstax_llm-0.1.0-py3-none-any.whl: openstax-llm (1 requirement(s))
  openstax-md>=0.2.0
openstax_llm_mcp-0.1.0-py3-none-any.whl: openstax-llm-mcp (2 requirement(s))
  mcp<3,>=2.0.0
  openstax-llm>=0.1.0
```

### Why this mattered

PyPI rejects any distribution whose `Requires-Dist` holds a PEP 508 direct URL, server-side
and without recourse:

```
400 Invalid value for requires_dist. Error: Can't have direct dependency:
'openstax-md @ git+https://github.com/michaelnavazhylau/openstax-md.git'
```

`twine check` does **not** detect it — it validates only the README and long description — so
the failure appeared after the tag was cut. PEP 508 states that public index servers SHOULD
NOT allow direct references, so this is a permanent constraint, not a bug to wait out.
`openstax-llm-mcp` was clean all along but transitively blocked: publishing it alone would
have shipped a package that could not be installed.

Reproduce the gate at any time:

```bash
uv build --package openstax-llm --out-dir dist/openstax-llm
uv build --package openstax-llm-mcp --out-dir dist/openstax-llm-mcp
uv run python scripts/check_wheel_metadata.py dist/openstax-llm/*.whl dist/openstax-llm-mcp/*.whl
```

`--allow <dist>` exists for deliberately-unofficial artifacts (GitHub-release-only builds).
No member is on that list.

## Confirm the names are free

Both were unregistered at the time of writing.

| Name | PyPI | TestPyPI |
|---|---|---|
| `openstax-llm` | free | free |
| `openstax-llm-mcp` | free | free |

Re-check before registering, because of the caveat below.

## Choose a publishing path

### Option A — Trusted Publishing from GitHub (recommended)

No stored secret. GitHub mints an OIDC identity, PyPI exchanges it for a short-lived,
scoped token. `release.yml` is already wired for this.

**Register a pending publisher per project** at <https://pypi.org/manage/account/publishing/>.
That is the **account** sidebar, not a project sidebar, because the projects do not exist yet.
| Field | `openstax-llm` | `openstax-llm-mcp` |
|---|---|---|
| PyPI project name | `openstax-llm` | `openstax-llm-mcp` |
| Owner | `michaelnavazhylau` | `michaelnavazhylau` |
| Repository | `openstax-llm` | `openstax-llm` |
| Workflow filename | `release.yml` | `release.yml` |
| Environment | `pypi-openstax-llm` | `pypi-openstax-llm-mcp` |

Two caveats shape that table:

- **A pending publisher does not reserve the name.** PyPI's docs: it "does not create a
  project or reserve a project's name until it is actually used to publish. If another user
  registers the project name before you publish, your pending publisher will be
  invalidated." Publish soon after registering.
- **The two environments must differ.** PyPI's pending-publisher uniqueness constraint covers
  `(repository_owner, repository_name, workflow_filename, environment)` and *not* the project
  name, so registering two projects against the same environment fails with a generic
  "Sorry, something went wrong" ([pypi/warehouse#20112], closed as a duplicate of
  [#16920], still unfixed). Distinct environment names are the reliable workaround.

Once the projects exist, a single job *could* publish both: PyPI scopes the token to every
project whose trusted publisher matches the OIDC claims. The workflow keeps them separate
anyway, because that is what makes the bootstrap work and it keeps failures isolated.

Create the matching GitHub environments under **Settings → Environments**. Required reviewers
there turn each release into an approval gate, and the environment is part of the OIDC claim,
so it is the right place to enforce it.

Then enable publishing:

```bash
gh variable set PYPI_PUBLISH_ENABLED --body true
```

The publish jobs require that variable *and* a passing metadata gate, so enabling uploads is
a deliberate, auditable change and a dirty wheel can never reach PyPI.

[pypi/warehouse#20112]: https://github.com/pypi/warehouse/issues/20112
[#16920]: https://github.com/pypi/warehouse/issues/16920

### Option B — Bootstrap with an account-scoped token (no web UI at all)

This is the fastest path and it skips pending-publisher registration entirely, because
uploading with an account-scoped token **creates** the project. PyPI maintainer `di`, on how
to create projects when 2FA is enabled:

> Use an account-scoped API token rather than a project-scoped API token: at
> <https://pypi.org/manage/account/token/>, you can select "Entire account (all projects)" to
> generate an API token that can create new projects.

The account-scoped token is required for the *first* upload of each project, and this is not
avoidable: a project-scoped token cannot exist before the project does.

```bash
set -a && . ./pypi-creds.env && set +a

uv build --package openstax-llm --out-dir dist/openstax-llm
uv build --package openstax-llm-mcp --out-dir dist/openstax-llm-mcp
uv run python scripts/check_wheel_metadata.py dist/openstax-llm/*.whl dist/openstax-llm-mcp/*.whl

# `uv publish` takes paths, NOT `--package`, and defaults to every file in `dist/`
# (uv#8033). Scoping each call to one package's directory keeps a stray artifact out.
uv publish --dry-run dist/openstax-llm/*      # reads UV_PUBLISH_TOKEN; uploads nothing
uv publish dist/openstax-llm/*
uv publish dist/openstax-llm-mcp/*
```

Order matters: publish `openstax-llm` first, or `uv add openstax-llm-mcp` resolves against a
missing dependency in the window between the two uploads.

**Immediately afterwards, reduce the blast radius:** create a *project-scoped* token for each
new project and revoke the account-scoped one. An account-scoped token can publish to every
project on the account, so leaving it in a file on disk is the risk that trusted publishing
exists to remove.

Trade-offs versus Option A, stated plainly:

| | Option A (OIDC) | Option B (token) |
|---|---|---|
| Web UI steps | 2 pending publishers | none |
| Credential at rest | none | long-lived token in `pypi-creds.env` |
| Build provenance attestation | yes | no |
| Tied to a git tag / CI run | yes | no, published from a laptop |
| Reproducible by anyone | yes | only the token holder |

Both paths end at the same place. Option B is the pragmatic first release; add trusted
publishers afterwards (see below) and it becomes the permanent automated path.

#### After a token bootstrap, the environments can be simplified

The four distinct environments exist only to work around the *pending*-publisher uniqueness
constraint. Once the projects exist you are registering normal publishers, and PyPI scopes a
token to every project whose publisher matches the OIDC claims — so both projects may share a
single environment and a single publish job. That is a genuine simplification worth doing
after the first release, not before.

### Option C — Token in CI

Store the token as a repository secret and pass it to `pypa/gh-action-pypi-publish` via
`password:`. This works, but it puts a long-lived credential back into CI — precisely what
Option A removes — so prefer A, or A after a B bootstrap.

## Rehearse on TestPyPI

Worth doing once: it exercises the upload endpoint, the metadata, and a genuine consumer
install before a version is consumed on the real index. **You can rehearse with a token, in
which case you need no pending publishers and no GitHub environment** — TestPyPI accepts an
account-scoped token for a new project exactly as PyPI does.

### Rehearsing with a token (no web UI)

Register at <https://test.pypi.org/account/register/> — TestPyPI accounts are **separate**
from PyPI accounts — then create an account-scoped token at
<https://test.pypi.org/manage/account/token/> and put it in `pypi-creds.env` as
`TEST_PYPI_TOKEN`.

```bash
set -a && . ./pypi-creds.env && set +a

uv build --package openstax-llm --out-dir dist/openstax-llm
uv build --package openstax-llm-mcp --out-dir dist/openstax-llm-mcp

UV_PUBLISH_TOKEN="$TEST_PYPI_TOKEN" uv publish \
  --publish-url https://test.pypi.org/legacy/ --dry-run dist/openstax-llm/*
UV_PUBLISH_TOKEN="$TEST_PYPI_TOKEN" uv publish \
  --publish-url https://test.pypi.org/legacy/ dist/openstax-llm/*
UV_PUBLISH_TOKEN="$TEST_PYPI_TOKEN" uv publish \
  --publish-url https://test.pypi.org/legacy/ dist/openstax-llm-mcp/*
```

Then verify, which is the part that actually proves something:

```bash
for pkg in openstax-llm openstax-llm-mcp; do
  curl -s -o /dev/null -w "$pkg: HTTP %{http_code}\n" "https://test.pypi.org/simple/$pkg/"
done

uv venv /tmp/tp
uv pip install --python /tmp/tp/bin/python \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  openstax-llm-mcp
/tmp/tp/bin/openstax-llm-mcp --version
```

`--extra-index-url` is needed because `openstax-md` lives on the real PyPI, not TestPyPI.

> Be careful probing names on TestPyPI by hand. `test.pypi.org/project/<name>/` sits behind
> bot protection and returns HTTP 200 for *everything*, including names that do not exist.
> Use `/simple/<name>/` or `/pypi/<name>/json` instead; both 404 for a free name and 200 for
> an existing one.

### Rehearsing through GitHub (requires pending publishers)

Register **two** pending publishers at <https://test.pypi.org/manage/account/publishing/>,
using the same owner/repo/workflow and **distinct** environments:

| PyPI project name | Environment |
|---|---|
| `openstax-llm` | `testpypi-openstax-llm` |
| `openstax-llm-mcp` | `testpypi-openstax-llm-mcp` |

TestPyPI runs the same warehouse code, so its pending-publisher uniqueness constraint has
the same shape: one shared environment cannot carry two pending publishers, and the second
registration fails with a generic error.

Then dispatch the rehearsal:

```bash
gh workflow run release.yml -f target=testpypi
gh run watch
```

The rehearsal uploads both projects, verifies each is present on the TestPyPI simple index
at the expected version, then creates a fresh venv, installs `openstax-llm-mcp` from
TestPyPI, and completes a real MCP handshake (`initialize` + `tools/list`, asserting the
server name and `search_catalog`).

The rehearsal uses `skip-existing: true`, so re-running it is safe. Nothing in it can reach
the real PyPI: the `target=pypi` value is required for that, and `PYPI_PUBLISH_ENABLED` on
top of it.

## Cut the release

```bash
git tag v0.1.0 && git push origin v0.1.0
gh release create v0.1.0 --generate-notes
```

The `build` job fails fast if the tag does not match both `pyproject.toml` versions. A tag
that disagrees with its own artifacts cannot be undone on PyPI.

## After the first release

- `uv add openstax-llm` and `uvx openstax-llm-mcp` start working, which is what the README,
  the MCP README, and the skill's `ensure-cli.sh` already assume. They all try PyPI first and
  fall back to git, so nothing needs editing — the fallback just stops being used.
- Add PyPI badges and drop the "from git" instructions from the root README.
- PyPI's **pending publisher becomes a normal publisher** after first use; no further setup.
- Publishing a version is irreversible. Bump, don't overwrite: `skip-existing` is deliberately
  `false` in `release.yml` so a partial or duplicate upload fails loudly rather than silently.

## Versioning

Both members release in lockstep. `tests/test_skill_contract.py` enforces that their versions
agree, that `openstax-llm-mcp` requires `openstax-llm>=<version>`, and that the skill's
declared `min_library_version` shares a major/minor with the library. Bump all of these in one
commit or the tests fail before the tag does:

- `packages/openstax-llm/pyproject.toml`
- `packages/openstax-llm-mcp/pyproject.toml`
- `packages/openstax-llm/src/openstax_llm/__init__.py` (`__version__`)
- `packages/openstax-llm-mcp/src/openstax_llm_mcp/_version.py` (fallback literal)

## Historical note: the old blocker

While `openstax-md` was git-only, `packages/openstax-llm/pyproject.toml` declared
`openstax-md @ git+https://…` and needed `[tool.hatch.metadata] allow-direct-references = true`
to build at all. Both are gone. `tests/test_skill_contract.py` now asserts that
`allow-direct-references` has not been reintroduced, because it would let a direct reference
slip back in while the local build stayed green.
