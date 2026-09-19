"""Suite-wide isolation: every test runs with **no saved login session**.

Why this file exists (2026-09-19)
---------------------------------

`novel orchestrate` reads the session before it reads any state:

    session = _session(ctx)                     # load() -> raises when no session file
    state = _novel_state(session, project_id)

`tests/test_document_revision_state.py::test_novel_orchestrate_plan_marks_human_final`
stubbed only `_novel_state`. So the test passed on a developer machine (where
`~/.config/scriptnow-cli/session.json` happens to exist) and failed in CI (where it does
not) -- the release gate was green exactly where it mattered least. The published wheel
stopped at build in CI, and the only reason it looked fine locally was ambient state
nobody had written down.

Pinning `SCRIPTNOW_CLI_CONFIG` at a path that cannot exist makes "local == CI" true by
construction: the suite-wide baseline *is* "not logged in", and any test that needs a
session must ask for one explicitly (see `tests/test_session.py`, which points the same
variable at its own fixture).

Deliberately **not** `tmp_path`/`tmpdir`: on a sandboxed workstation those raise
`PermissionError` during fixture setup (whole files then report as ERROR rather than
FAILED, which buries the real signal). A repo-relative path that is never written needs
no writable directory at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

#: Never created. Its only job is to be a path that does not exist, on every machine.
NO_SESSION_CONFIG = Path(__file__).resolve().parent / ".no-session" / "session.json"


@pytest.fixture(autouse=True)
def _no_saved_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the CLI at a session file that does not exist for every test."""
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(NO_SESSION_CONFIG))
