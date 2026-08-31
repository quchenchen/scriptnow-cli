"""Opt-in, content-free CLI quality diagnostics (schema v2)."""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import suppress
from pathlib import Path

MAX_ERROR_ENTRIES = 50
MAX_ENABLE_MINUTES = 24 * 60
_EVENT_KEYS = {"ts", "command_key", "error_code", "phase"}
COMMAND_KEY_ALLOWLIST = frozenset(
    {
        "unknown", "login", "doctor", "feedback", "project.create", "project.list",
        "chapter.generate", "chapter.propose", "chapter.adopt", "scene.generate",
        "scene.propose", "scene.adopt", "storymap.propose", "storymap.adopt",
        "run.status", "run.events", "export.create",
    }
)
ERROR_CODE_ALLOWLIST = frozenset(
    {
        "CLI_UNKNOWN", "CLI_AUTH_EXPIRED", "CLI_USAGE_UNKNOWN_OPTION",
        "CLI_USAGE_UNKNOWN_COMMAND", "CLI_HTTP_409", "CLI_HTTP_4XX",
        "CLI_HTTP_5XX", "CLI_NETWORK",
    }
)


def _config_dir() -> Path:
    override = os.environ.get("SCRIPTNOW_CLI_CONFIG")
    if override:
        return Path(override).parent
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "scriptnow-cli"


def _errors_path() -> Path:
    return _config_dir() / "errors-v2.jsonl"


def _state_path() -> Path:
    return _config_dir() / "diagnostics-v2.json"


def diagnostics_enabled_until() -> int | None:
    try:
        enabled_until = int(
            json.loads(_state_path().read_text(encoding="utf-8")).get("enabled_until", 0)
        )
        if enabled_until > int(time.time()):
            return enabled_until
        _state_path().unlink(missing_ok=True)
        _errors_path().unlink(missing_ok=True)
        return None
    except (OSError, ValueError, TypeError):
        return None


def enable_diagnostics(minutes: int = 60) -> int:
    if minutes < 1 or minutes > MAX_ENABLE_MINUTES:
        raise ValueError(f"minutes must be between 1 and {MAX_ENABLE_MINUTES}")
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    enabled_until = int(time.time()) + minutes * 60
    path.write_text(json.dumps({"schema_version": 2, "enabled_until": enabled_until}), encoding="utf-8")
    with suppress(OSError):
        path.chmod(0o600)
    return enabled_until


def disable_diagnostics() -> None:
    _state_path().unlink(missing_ok=True)


def _error_code(detail: str) -> str:
    value = str(detail).lower()
    if "401" in value or "登录状态已失效" in str(detail):
        return "CLI_AUTH_EXPIRED"
    if "no such option" in value:
        return "CLI_USAGE_UNKNOWN_OPTION"
    if "no such command" in value:
        return "CLI_USAGE_UNKNOWN_COMMAND"
    if value.startswith("http 409"):
        return "CLI_HTTP_409"
    if value.startswith("http 4"):
        return "CLI_HTTP_4XX"
    if value.startswith("http 5"):
        return "CLI_HTTP_5XX"
    if "network error" in value or "connection" in value:
        return "CLI_NETWORK"
    return "CLI_UNKNOWN"


def _command_key(command: str) -> str:
    value = command.strip().lower()
    if not value or len(value) > 80 or any(marker in value for marker in "/:="):
        return "unknown"
    words = value.split()
    if len(words) > 3 or any(not re.fullmatch(r"[a-z0-9_.-]{1,32}", word) for word in words):
        return "unknown"
    candidate = ".".join(words)
    return candidate if candidate in COMMAND_KEY_ALLOWLIST else "unknown"


def _phase(error_code: str) -> str:
    if error_code.startswith("CLI_AUTH"):
        return "auth"
    if error_code.startswith("CLI_USAGE"):
        return "validation"
    if error_code == "CLI_NETWORK":
        return "transport"
    if error_code.startswith("CLI_HTTP"):
        return "platform"
    return "unknown"


def record_error(*, command: str, args: tuple[str, ...], detail: str) -> str:
    del args
    error_code = _error_code(detail)
    if diagnostics_enabled_until() is None:
        return error_code
    try:
        path = _errors_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": int(time.time()),
            "command_key": _command_key(command),
            "error_code": error_code,
            "phase": _phase(error_code),
        }
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        lines.append(json.dumps(entry, separators=(",", ":")))
        path.write_text("\n".join(lines[-MAX_ERROR_ENTRIES:]) + "\n", encoding="utf-8")
        with suppress(OSError):
            path.chmod(0o600)
    except Exception:
        pass
    return error_code


def recent_errors(limit: int = 20) -> list[dict[str, object]]:
    if diagnostics_enabled_until() is None or not _errors_path().exists():
        return []
    output: list[dict[str, object]] = []
    for line in _errors_path().read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and set(value) == _EVENT_KEYS:
            output.append(value)
    return output


def clear_errors() -> bool:
    try:
        _errors_path().unlink(missing_ok=True)
        (_config_dir() / "errors.jsonl").unlink(missing_ok=True)
        return True
    except OSError:
        return False
