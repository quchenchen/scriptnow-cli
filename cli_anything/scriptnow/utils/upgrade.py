"""Version check and self-upgrade for scriptnow-cli.

The CLI checks for a newer version on the public GitHub repo
(quchenchen/scriptnow-cli — the release mirror of this monorepo) at low
frequency (once per 24h, cached locally, silent on failure) and offers
`scriptnow self-upgrade` to apply the update after explicit user consent.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import requests

from cli_anything.scriptnow import __version__ as VERSION

_REMOTE_INIT = (
    "https://raw.githubusercontent.com/quchenchen/scriptnow-cli/main/"
    "cli_anything/scriptnow/__init__.py"
)
_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


def _state_path() -> Path:
    override = os.environ.get("SCRIPTNOW_CLI_CONFIG")
    root = Path(override).parent if override else Path(
        os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    ) / "scriptnow-cli"
    return root / "version-check.json"


def latest_version(timeout: int = 8) -> str | None:
    """Query the GitHub release mirror for the newest __version__.

    Returns None when the network fails or the remote version cannot be
    parsed — the caller treats that as "no information" and stays silent.
    """
    try:
        response = requests.get(_REMOTE_INIT, timeout=timeout)
        if response.status_code != 200:
            return None
        for line in response.text.splitlines():
            line = line.strip()
            if line.startswith("__version__"):
                parts = line.split('"')
                if len(parts) >= 2 and parts[1]:
                    return parts[1]
    except requests.RequestException:
        return None
    return None


def _is_stale() -> bool:
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
        return float(state.get("checked_at") or 0) + _CHECK_INTERVAL_SECONDS < time.time()
    except (OSError, ValueError, KeyError):
        return True


def _record_check() -> None:
    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked_at": int(time.time())}))
    except OSError:
        pass


def check_for_update(force: bool = False) -> str | None:
    """Return the latest version when a newer one exists, else None.

    Non-blocking for the caller: network happens in this function with a
    short timeout; the 24h cache avoids a request on every invocation.
    """
    if not force and not _is_stale():
        return None
    latest = latest_version()
    _record_check()
    if latest is None or latest == VERSION:
        return None
    return latest


def _install_command() -> tuple[str, list[str]] | None:
    """Resolve the upgrade command for the current installation method."""
    try:
        import importlib.metadata as md

        dist = md.distribution("scriptnow-cli")
    except md.PackageNotFoundError:
        return None
    # Editable install (local dev): can't self-upgrade blindly — tell the user.
    for file in dist.files or []:
        if "__editable__" in str(file):
            return None
    import shutil

    if shutil.which("uv"):
        return "uv", ["tool", "upgrade", "scriptnow-cli"]
    return "pip", [
        "install",
        "--user",
        "--break-system-packages",
        "--upgrade",
        "git+https://github.com/quchenchen/scriptnow-cli.git",
    ]


def upgrade(quiet: bool = False) -> bool:
    """Apply the upgrade. Returns True on success."""
    command = _install_command()
    if command is None:
        if not quiet:
            print(
                "检测到本地 editable 安装（开发模式）。请手动升级："
                "pip install -e /path/to/scriptnow-cli 后重新运行。"
            )
        return False
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        if not quiet:
            print(result.stderr[-500:] or "升级失败。")
        return False
    return True


def maybe_warn_in_background() -> None:
    """Spawn a non-blocking background check that prints a one-line hint."""

    def _run() -> None:
        try:
            latest = check_for_update()
            if latest:
                print(
                    f"发现 ScriptNow CLI 新版本 v{latest}（当前 v{VERSION}）。"
                    f"运行 `scriptnow self-upgrade` 自动升级，或 `scriptnow version --check` 查看。",
                    file=__import__("sys").stderr,
                )
        except Exception:
            pass  # never break the main command because of a version hint

    threading.Thread(target=_run, daemon=True).start()
