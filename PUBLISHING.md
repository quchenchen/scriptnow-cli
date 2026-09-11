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

References: [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/)
and [PyPA publishing guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).

## First release verified

Version 0.3.94 was published on 2026-09-11 using
[workflow run 34549198132](https://github.com/quchenchen/scriptnow-cli/actions/runs/34549198132).
The public PyPI JSON API lists wheel and sdist; a fresh installation from
`https://pypi.org/simple` passed version and agent-guide smoke checks.
