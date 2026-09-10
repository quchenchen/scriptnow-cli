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
3. Synchronize only reviewed CLI files into the release mirror. The general
   `sync-cli-release.sh` also writes to production; do not invoke it solely for
   PyPI publication without authorization for those additional actions.
4. Run the mirror's **Publish to PyPI** workflow on `main` with the exact version.
   Approve the `pypi` environment after its build checks pass.
5. Verify the PyPI project/release and install that exact version from
   `https://pypi.org/simple` in a new environment. Check version and help output.
6. Only after verification, advertise the PyPI install command in user-facing
   documentation. The platform distribution remains the default update source.

References: [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/)
and [PyPA publishing guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).
