# PyPI publishing

The monorepo directory `cli/scriptnow-cli/` is the source of truth. Its GitHub
release mirror is `quchenchen/scriptnow-cli`; this directory's `.github/`
workflow becomes the mirror repository's root workflow on synchronization.
No production server deployment is needed for a PyPI release.

## One-time setup

1. Verify the owner's PyPI email and enable two-factor authentication.
2. In GitHub repository settings, create environment `pypi`, restrict deployment
   to `main`, and require a maintainer review for deployments.
3. In PyPI account publishing settings, add a pending GitHub publisher:
   project `scriptnow-cli`, owner `quchenchen`, repository `scriptnow-cli`,
   workflow `publish-pypi.yml`, environment `pypi`.

The first successful upload creates the PyPI project. No API token is stored in
GitHub. A missing public project page is not proof that a name can be claimed;
PyPI checks eligibility on upload.

## Each release

1. Use the CLI version in `cli_anything/scriptnow/__init__.py`. Do not overwrite
   an existing PyPI version. Keep the backend/application release independent.
2. Build wheel and sdist with `python -m build` in a clean release copy. Run
   `python -m twine check --strict dist/*`, inspect archive contents, and install
   the wheel in an isolated environment. Run the full CLI suite in the monorepo;
   five Creator/root-document sync tests cannot run in the standalone mirror
   and are explicitly excluded there. Check `--version`, `--help`, and
   `agent-guide --json`, then run CLI tests.
3. Run monorepo `scripts/sync-cli-release.sh` after authorization for its GitHub
   and production-distribution writes. It preflights GitHub auth and the reviewed
   main-only `pypi` environment, synchronizes the mirror, verifies production
   distribution, then invokes `scripts/publish-cli-pypi.py` automatically.
   Unchanged mirror files no longer cause an early exit that skips PyPI.
4. The helper dispatches **Publish to PyPI** for the exact source commit/version,
   reuses an active matching run, and checks the run and public PyPI release.
   It does not auto-approve environment reviews. Exit code 3 means review or
   execution is pending, not success; follow the printed workflow URL and resume
   command after approval. Failed builds/uploads and network errors exit 1.
5. For a PyPI-only release or resuming after approval (no production writes):
   `python3 scripts/publish-cli-pypi.py --version X.Y.Z --commit <full-sha>`.
   Use the emitted `--resume <run-id>` when resuming an existing run. The helper
   verifies the workflow, commit, version, wheel and sdist; it never overwrites an
   already-published version. Preflight only: add `--check-only`.
6. A complete release requires wheel and sdist to be publicly available on PyPI.
   Verify installation of the exact version from `https://pypi.org/simple` in a
   fresh environment. The default auto-upgrade source remains the platform host.
   Do not put local proxies, API tokens or session files into release materials.
7. Refresh **Latest verified release** below with the version, workflow run and
   artifact hashes, then commit it. That snapshot is what keeps this runbook
   tracking the newest release; a stale snapshot is a real defect.

References: [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/)
and [PyPA publishing guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).

## Latest verified release

**`0.3.96`** — published 2026-09-11 via
[workflow run 34612135389](https://github.com/quchenchen/scriptnow-cli/actions/runs/34612135389).

| Artifact | SHA256 |
|---|---|
| `scriptnow_cli-0.3.96-py3-none-any.whl` | `c602eacf784fbfa90df375c4727b92ee8100b1c3033468fec3d850dc1ffe0843` |
| `scriptnow_cli-0.3.96.tar.gz` | `ebe09669c4f9702524562ad4c870ebd9bff51e93093aefc37b6e0faadd5f2dea` |

Both distributions are listed, unyanked, on the public index; a fresh Python 3.12
installation from `https://pypi.org/simple` passed `--version` and Skill-bundle
smoke checks.

### Pending: `0.3.97` is on the platform source only

`0.3.97` (hosted-instance login semantics, see
`cli_anything/scriptnow/utils/hosted.py`) is **already live on the platform
download source** — `https://sn.igeewa.com/downloads/scriptnow-cli/version.txt`
returns `0.3.97`, and the versioned wheel / `latest` alias / source zip are all
served. It is **not** on PyPI or the GitHub mirror yet, so the snapshot above
deliberately still says `0.3.96`.

That split is the normal intermediate state of `scripts/sync-cli-release.sh`,
whose stages run GitHub → platform → PyPI: a run that stops after the platform
stage leaves the platform source ahead. To finish the release, run the script
with authorization for its GitHub and PyPI writes (steps 3 and 5 above); it is
idempotent, so the already-published platform files are simply re-verified.

Registered for that run:

| Artifact | SHA256 |
|---|---|
| `scriptnow_cli-0.3.97-py3-none-any.whl` | `175d1b16e58a11b61a32609b7b3a10cd537a40d819ca6b6b516621c8315fd0a0` |

Note this hash is **per build** — the wheel embeds build timestamps, so a
rebuild changes it. The value that matters is what the platform is serving now
(`shasum -a 256` the downloaded file), not this line.

PyPI and the workflow run stay the authoritative live record — read the current
published version straight from the index pip installs from, instead of trusting
this snapshot:

```bash
python3 -m pip index versions scriptnow-cli
# equivalent without pip: https://pypi.org/simple/scriptnow-cli/
```

The `/pypi/<project>/json` endpoint can lag a few minutes behind a fresh upload;
the simple index above reflects a new release immediately.

First release: `0.3.94`, 2026-09-11,
[workflow run 34549198132](https://github.com/quchenchen/scriptnow-cli/actions/runs/34549198132).
