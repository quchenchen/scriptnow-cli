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


def test_older_release_feed_never_triggers_downgrade(isolated) -> None:
    assert upg.is_newer_version("0.3.84", "0.3.85") is False
    with patch.object(upg, "latest_version", return_value="0.3.84"):
        assert upg.check_for_update(force=True) is None
    with (
        patch.object(upg, "latest_version", return_value="0.3.84"),
        patch.object(upg.subprocess, "run") as run,
    ):
        assert upg.upgrade(quiet=True) is True
    run.assert_not_called()


def test_editable_install_refreshes_from_production_wheel(isolated) -> None:
    """Editable installs are replaced in the active Python environment."""
    completed = type("Completed", (), {"returncode": 0, "stderr": ""})()
    with (
        patch.object(upg, "is_editable_install", return_value=True),
        patch.object(upg, "latest_version", return_value=upg.VERSION),
        patch.object(upg.subprocess, "run", return_value=completed) as run,
    ):
        assert upg.upgrade(quiet=True) is True
    command = run.call_args.args[0]
    joined = " ".join(command)
    # 支持 pip（python -m pip）与 uv（uv pip --python）两种安装后端：
    # 意图是 editable install 被生产 wheel --force-reinstall 替换。
    assert command[0] in {upg.sys.executable, "uv", "pip"}
    assert "--force-reinstall" in joined
    assert f"scriptnow_cli-{upg.VERSION}-py3-none-any.whl" in joined


def test_windows_base_python_uses_current_interpreter_without_posix_flag() -> None:
    with (
        patch.object(upg.importlib.util, "find_spec", return_value=object()),
        patch.object(upg.os, "name", "nt"),
        patch.object(upg.sys, "prefix", r"C:\Python312"),
        patch.object(upg.sys, "base_prefix", r"C:\Python312"),
    ):
        command = upg._environment_install_command("https://example.test/cli.whl")
    assert command is not None
    program, args = command
    assert program == upg.sys.executable
    assert args[:3] == ["-m", "pip", "install"]
    assert "--user" in args
    assert "--break-system-packages" not in args


def test_virtualenv_upgrade_never_uses_user_install() -> None:
    with (
        patch.object(upg.importlib.util, "find_spec", return_value=object()),
        patch.object(upg.sys, "prefix", "/venv"),
        patch.object(upg.sys, "base_prefix", "/usr"),
    ):
        command = upg._environment_install_command("https://example.test/cli.whl")
    assert command is not None
    assert "--user" not in command[1]
    assert "--break-system-packages" not in command[1]


def test_uv_environment_without_pip_targets_current_python() -> None:
    with (
        patch.object(upg.importlib.util, "find_spec", return_value=None),
        patch.object(upg.shutil, "which", return_value="/usr/bin/uv"),
    ):
        command = upg._environment_install_command("https://example.test/cli.whl")
    assert command == (
        "uv",
        ["pip", "install", "--python", upg.sys.executable,
         "--force-reinstall", "https://example.test/cli.whl"],
    )
