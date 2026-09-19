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

### Pending: `0.3.98` is on the platform source and the GitHub mirror; PyPI awaits review

`0.3.98` is live on the platform download source
(`https://sn.igeewa.com/downloads/scriptnow-cli/version.txt` returns `0.3.98`) and
on the GitHub mirror (commit `986e502a95e44c739f6f85210903ba7ec6eaa8ea`, tag
`v0.3.98`). Its PyPI workflow, run
[35183960449](https://github.com/quchenchen/scriptnow-cli/actions/runs/35183960449),
has a green `build` job and a `publish` job **waiting on the `pypi` environment
review** — the helper never approves that review itself, so the release is not
complete until a maintainer does. That is why the snapshot above still says
`0.3.96`.

Resume after approving (no production writes are repeated):

```bash
python3 scripts/publish-cli-pypi.py --version 0.3.98 \
  --commit 986e502a95e44c739f6f85210903ba7ec6eaa8ea --resume 35183960449
```

`0.3.97` never reached PyPI or the mirror — it lived only on the platform source
for a few hours before `0.3.98` superseded it. Because the mirror is a
normalized `rsync --delete` copy of this directory, `0.3.98` carries everything
`0.3.97` had (the hosted-instance login semantics from `utils/hosted.py`) plus its
own changes; there is no reason to publish `0.3.97` now, and its
platform-only wheel remains downloadable for anyone pinned to it.

Registered for that run:

| Artifact | SHA256 |
|---|---|
| platform-served `scriptnow_cli-0.3.98-py3-none-any.whl` | `6ddd29eadc8cb0236ed0b5d225e705dfde63022e317f64ec741c6d9d68a2df7e` |
| `dsh-integration/vendor/scriptnow-cli/wheels/scriptnow_cli-0.3.98-py3-none-any.whl` (that day's generation; superseded) | `3b2d6e568d930ca822c28c1bcca0538565427753b5233a660233611abda8406e` |

Note these hashes are **per build** — the wheel embeds build timestamps, so a
rebuild changes them. The platform wheel is built by this release script and the
vendored one by `dsh-integration` for the gateway image, so the two files of one
version are never byte-identical.

### ⚠ One version number = one content (2026-09-17 用户定规)

Earlier this file said two builds of the same version "legitimately differ". That
is no longer accepted: the version number is the only identity any human or tool
reads (`scriptnow --version`, the image build's `verify-installed-cli.py
--expect-version`, the platform's minimum-version gate) and **none of them compare
content**. `0.3.98` was rebuilt in place **six times in one day** (R1 `8fc6d39e…`
… R6 `da7fa89a…`, each a real fix) and there was no way to tell which one an image
carried. So:

1. **Any content change bumps `__version__`** (`cli_anything/scriptnow/__init__.py`);
   never re-release a version number that has shipped.
2. The vendored wheel's identity is pinned by the **version ledger** in
   `dsh-integration/vendor/scriptnow-cli/PROVENANCE.txt`
   (`LEDGER-BEGIN`/`LEDGER-END`, append-only); `check-vendored-cli.py` fails if the
   wheel's sha256 differs from the ledger line for its version.
3. `0.3.99` is the W5 batch (device-code login + `SCRIPTNOW_WEB_PREFIX` link fix +
   host-held refresh). It is **not published yet**: publishing it needs the same
   three-target flow as `0.3.98` (GitHub mirror + platform download source + PyPI).
   `scripts/sync-cli-release.sh` now publishes **the vendored wheel itself**
   (`dsh-integration/vendor/scriptnow-cli/wheels/scriptnow_cli-0.3.99-py3-none-any.whl`
   = `3ffdf6f26d4649cfdee8d6b9ceb0f9fcf27a0ce2709cf4b745a3ff60fada74d8`) instead of
   building a second one, so the gateway image, the platform download source and
   the GitHub mirror all carry the same bytes for this version. PyPI still rebuilds
   from the mirrored source in CI, so its wheel differs in timestamps only -- same
   source, same content, one generation.
4. `0.4.0` is the automatic-batch-creation batch: the new `chapter batch` command
   (with `scene batch` moved onto the same four preconditions -- novice period
   over, methodology skill mounted, 2-3 units per batch, candidates only) plus the
   agent+CLI serial orchestration contract. Also **not published yet**, and it
   needs the same three-target flow.
   `dsh-integration/vendor/scriptnow-cli/wheels/scriptnow_cli-0.4.0-py3-none-any.whl`
   = `64443f7860308889a72eb57a276414ce00651f0ef185949847f8c800ba6c32ef`.
5. `0.4.1` adds the quantified dashboard: `script analytics` (`--json`, `--top N`)
   reports beat density, conflict components, character screen time and the
   key-node coverage matrix. Every number comes from the platform's read-only
   endpoint, so the CLI never recomputes anything. Also **not published yet**;
   it needs the same three-target flow.
   `dsh-integration/vendor/scriptnow-cli/wheels/scriptnow_cli-0.4.1-py3-none-any.whl`
   = `a578e701ab281c06dd1907afcca8231a8fb7a182bad863773e6814a1bf1c641e`.
6. `0.4.2` is a **documentation catch-up, not a new feature**: it changes no
   command and no flag. `0.4.1`'s two agent-facing docs (`cli_anything/scriptnow/README.md`'s
   `script` row gaining `analytics`, and `skills/references/planning.md` gaining the
   three episode-outline hard rules) were committed in `cec79e17` but the wheel was
   built before them, so the vendored wheel kept shipping without those two sections --
   and `check-vendored-cli.py` stayed red from that commit onward. Also **not published
   yet**; it needs the same three-target flow.
   `dsh-integration/vendor/scriptnow-cli/wheels/scriptnow_cli-0.4.2-py3-none-any.whl`
   = `9e7c1a4ef1d5a457fbb120b903766a238a355bbbcdc506a6598f2088189c297c`.

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
