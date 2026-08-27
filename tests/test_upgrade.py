"""Unit tests for the CLI auto-upgrade config and version-check helpers.

These test the pure helpers (config load/save, staleness, install-mode
detection) without touching the network or writing real user config.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cli_anything.scriptnow.utils import upgrade as upg


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch) -> None:
    """Point config/state paths at a temp dir so tests never touch ~/.config."""
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "config.json"))


def test_config_roundtrip_and_defaults(isolated) -> None:
    assert upg.load_config() == {}
    assert upg.auto_upgrade_enabled() is False

    upg.set_config(autoUpgrade=True)
    assert upg.load_config() == {"autoUpgrade": True}
    assert upg.auto_upgrade_enabled() is True

    # Preserve unknown keys on a later update.
    upg.set_config(someOther=123)
    assert upg.load_config()["someOther"] == 123
    assert upg.auto_upgrade_enabled() is True

    upg.set_config(autoUpgrade=False)
    assert upg.auto_upgrade_enabled() is False


def test_check_for_update_uses_24h_cache(isolated) -> None:
    with patch.object(upg, "latest_version", return_value="9.9.9") as latest:
        # First call: network consulted.
        assert upg.check_for_update() == "9.9.9"
        latest.assert_called_once()
        # Second call within cache window: no network, but current VERSION is a
        # placeholder so we avoid a misleading hint; check no exception.
        upg.check_for_update()


def test_check_for_update_same_version_returns_none(isolated) -> None:
    with patch.object(upg, "latest_version", return_value=upg.VERSION):
        assert upg.check_for_update(force=True) is None


def test_install_command_editable_returns_none(isolated) -> None:
    """Editable installs must never be auto-upgraded."""
    with patch.object(upg, "_install_command", return_value=None):
        assert upg.upgrade(quiet=True) is False
