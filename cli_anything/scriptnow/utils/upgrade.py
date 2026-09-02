"""Version check and self-upgrade for scriptnow-cli.

The CLI checks for a newer version on the public GitHub repo
(quchenchen/scriptnow-cli — the release mirror of this monorepo) at low
frequency (once per 24h, cached locally, silent on failure) and offers
`scriptnow self-upgrade` to apply the update after explicit user consent.
"""

from __future__ import annotations

import json
import importlib.util
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

from cli_anything.scriptnow import __version__ as VERSION

_REMOTE_INIT = (
    "https://raw.githubusercontent.com/quchenchen/scriptnow-cli/main/"
    "cli_anything/scriptnow/__init__.py"
)
# 生产源：sn.igeewa.com 托管 CLI wheel / zip / version.txt，作为自动更新的优先来源
# （直装 wheel，避免 git 部分克隆被网络掐断；GitHub 仅作版本与下载兜底）。
_REMOTE_VERSION_TXT = "https://sn.igeewa.com/downloads/scriptnow-cli/version.txt"
_PROD_WHEEL_TMPL = (
    "https://sn.igeewa.com/downloads/scriptnow-cli/scriptnow_cli-{version}-py3-none-any.whl"
)
_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    parts = value.strip().split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def is_newer_version(candidate: str, current: str = VERSION) -> bool:
    candidate_tuple = _version_tuple(candidate)
    current_tuple = _version_tuple(current)
    return bool(
        candidate_tuple is not None
        and current_tuple is not None
        and candidate_tuple > current_tuple
    )


def _state_path() -> Path:
    override = os.environ.get("SCRIPTNOW_CLI_CONFIG")
    root = Path(override).parent if override else Path(
        os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    ) / "scriptnow-cli"
    return root / "version-check.json"


def _config_path() -> Path:
    override = os.environ.get("SCRIPTNOW_CLI_CONFIG")
    root = Path(override).parent if override else Path(
        os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    ) / "scriptnow-cli"
    return root / "config.json"


def load_config() -> dict[str, object]:
    """Read the CLI config file. Missing/corrupt → defaults."""
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def set_config(**updates: object) -> dict[str, object]:
    """Persist config, preserving unknown keys."""
    config = load_config()
    config.update(updates)
    try:
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    except OSError:
        raise
    return config


def auto_upgrade_enabled() -> bool:
    return bool(load_config().get("autoUpgrade", False))


def _fetch_production_version(timeout: int) -> str | None:
    """Read version.txt hosted on the production download host (preferred)."""
    try:
        response = requests.get(_REMOTE_VERSION_TXT, timeout=timeout)
        if response.status_code != 200:
            return None
        version = response.text.strip()
        if version and all(part.isdigit() for part in version.split(".")[:2]):
            return version
    except requests.RequestException:
        return None
    return None


def _fetch_github_version(timeout: int) -> str | None:
    """Query the GitHub release mirror for the newest __version__ (fallback)."""
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


def latest_version(timeout: int = 8) -> str | None:
    """Return the newest CLI version — production host first, GitHub fallback.

    Returns None when all sources fail or the remote version cannot be parsed;
    the caller treats that as "no information" and stays silent.
    """
    version = _fetch_production_version(timeout)
    if version:
        return version
    return _fetch_github_version(timeout)


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
    if latest is None or not is_newer_version(latest):
        return None
    return latest


def _environment_install_command(
    source: str, *, upgrade_only: bool = False
) -> tuple[str, list[str]] | None:
    """Install into the interpreter that is running this CLI.

    Virtual environments must never receive ``--user``. A base interpreter may
    need a user install; ``--break-system-packages`` is POSIX-only. If a uv-made
    environment has no pip module, target it explicitly through ``uv pip``.
    """
    action = "--upgrade" if upgrade_only else "--force-reinstall"
    if importlib.util.find_spec("pip") is not None:
        flags: list[str] = []
        if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
            flags.append("--user")
            if os.name != "nt":
                flags.append("--break-system-packages")
        return sys.executable, ["-m", "pip", "install", *flags, action, source]
    if shutil.which("uv"):
        return "uv", ["pip", "install", "--python", sys.executable, action, source]
    return None


def _install_command(version: str | None = None) -> tuple[str, list[str]] | None:
    """Resolve an upgrade command for the current installed environment."""
    try:
        import importlib.metadata as md

        dist = md.distribution("scriptnow-cli")
    except md.PackageNotFoundError:
        return None
    # Editable install (local dev): can't self-upgrade blindly — tell the user.
    for file in dist.files or []:
        if "__editable__" in str(file):
            return None
    source = (
        _PROD_WHEEL_TMPL.format(version=version)
        if version
        else "https://codeload.github.com/quchenchen/scriptnow-cli/tar.gz/refs/heads/main"
    )
    return _environment_install_command(source)


def is_editable_install() -> bool:
    try:
        import importlib.metadata as md

        dist = md.distribution("scriptnow-cli")
    except md.PackageNotFoundError:
        return False
    return any("__editable__" in str(file) for file in (dist.files or []))


def _upgrade_fallback() -> tuple[str, list[str]] | None:
    """备选升级命令：git+https（当 codeload 被拦时）。"""
    return _environment_install_command(
        "git+https://github.com/quchenchen/scriptnow-cli.git", upgrade_only=True
    )


def upgrade(quiet: bool = False) -> bool:
    """Apply the upgrade. Returns True on success.

    Attempts sources in priority order: production wheel (sn.igeewa.com) →
    codeload tar.gz (GitHub) → git+https (last resort)."""
    latest = latest_version()
    if latest is not None and not is_newer_version(latest) and latest != VERSION:
        return True  # Never downgrade a newer local/dev build to an older feed.
    if is_editable_install():
        target = latest or VERSION
        candidate = _environment_install_command(
            _PROD_WHEEL_TMPL.format(version=target)
        )
        if candidate is None:
            if not quiet:
                print("当前 Python 环境无 pip 且未找到 uv，无法自动升级。")
            return False
        result = subprocess.run(
            [candidate[0], *candidate[1]],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            return True
        if not quiet:
            print((result.stderr or "同版本补丁刷新失败。")[-500:])
        return False
    attempts: list[tuple[str, list[str]] | None] = []
    if latest:
        attempts.append(_install_command(latest))  # 生产源 wheel
    attempts.append(_install_command())            # codeload main 兜底
    attempts.append(_upgrade_fallback())           # git+https 最后兜底
    last_stderr = ""
    for candidate in attempts:
        if not candidate:
            continue
        cmd = [candidate[0], *candidate[1]]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return True
        last_stderr = result.stderr or ""
    if not quiet:
        print(last_stderr[-500:] or "升级失败。")
    return False


def maybe_warn_in_background() -> None:
    """Spawn a non-blocking background version check.

    Default behaviour: print a one-line hint when a newer version exists.

    When the user has opted into ``autoUpgrade`` (``scriptnow config
    auto-upgrade on``), the background check instead attempts the upgrade
    automatically and notifies the user before/after — never blocking the
    main command. Editable/dev installs are never auto-upgraded.
    """
    import sys

    def _run() -> None:
        try:
            latest = check_for_update()
            if not latest:
                return
            if auto_upgrade_enabled():
                if _install_command() is None:
                    # Editable/dev install: never auto-upgrade; fall back to a
                    # normal hint so the user knows a newer version exists.
                    print(
                        f"发现 ScriptNow CLI 新版本 v{latest}（当前 v{VERSION}）。"
                        f"本地为开发安装，请手动升级。",
                        file=sys.stderr,
                    )
                    return
                print(
                    f"[scriptnow] 检测到新版本 v{latest}（当前 v{VERSION}），正在自动升级…",
                    file=sys.stderr,
                )
                ok = upgrade(quiet=False)
                if ok:
                    print(
                        f"[scriptnow] 已自动升级到 v{latest}。请重新运行 scriptnow 使新版本生效。",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "[scriptnow] 自动升级未完成，请运行 `scriptnow self-upgrade` 手动升级。",
                        file=sys.stderr,
                    )
                return
            print(
                f"发现 ScriptNow CLI 新版本 v{latest}（当前 v{VERSION}）。"
                f"运行 `scriptnow self-upgrade` 自动升级，或 `scriptnow version --check` 查看。",
                file=sys.stderr,
            )
        except Exception:
            pass  # never break the main command because of a version hint

    threading.Thread(target=_run, daemon=True).start()
