"""Pin the contract the rest of the suite's isolation rests on.

`tests/conftest.py` makes "no saved login session" the baseline for every test.
That only isolates anything while `session.load()` *fails loudly* when the session
file is missing. If it ever starts returning a guest/anonymous session instead,
every session-dependent test would pass without a session, the isolation would
quietly stop isolating, and nothing anywhere would turn red to say so.

`test_config_path_follows_the_isolation_fixture` is a canary for the other
direction: on a machine that *does* have a real session (which is where the
2026-09-19 fake-green happened), it fails if the autouse fixture goes missing.
"""

from __future__ import annotations

import pytest

from cli_anything.scriptnow.utils import session as session_module


def test_config_path_follows_the_isolation_fixture() -> None:
    """The autouse fixture must win over whatever this machine has on disk."""
    assert not session_module._config_path().exists()


def test_missing_session_raises_rather_than_degrading() -> None:
    """No session file must be an error, not a silent anonymous session."""
    with pytest.raises(session_module.ScriptNowError):
        session_module.load()
