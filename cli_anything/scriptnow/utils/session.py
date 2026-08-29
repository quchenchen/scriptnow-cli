"""Authenticated HTTP session for the ScriptNow platform.

The platform authenticates via cookie + CSRF (same-origin web model):
- POST /api/auth/login with email/password sets sf_access / sf_refresh / sf_csrf cookies.
- Mutating requests must send the X-CSRF-Token header matching the sf_csrf cookie.
- The session is persisted locally (base_url, cookies, csrf) so a CLI run does
  not re-login on every invocation; credentials are never stored.

Endpoints are reached under ``<base_url>/api/...`` for platform APIs and
``<base_url>/api/novel/...`` / ``<base_url>/api/script/...`` for domain APIs.
"""

from __future__ import annotations

import json
import os
import sys
import time
import re
import errno
import fcntl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from cli_anything.scriptnow import __version__ as _CLIENT_VERSION

# Per-process invocation id so the server can correlate retries and audit
# a logical call across multiple HTTP requests.
import uuid as _uuid

_INVOCATION_ID = str(_uuid.uuid4())


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    return tuple(int(part) for part in match.groups()) if match else None


class ScriptNowError(RuntimeError):
    """Raised when the platform returns an error or the session is unusable."""


class _SessionFileError(RuntimeError):
    """The local session file cannot safely participate in a refresh."""


class _SessionLockTimeout(RuntimeError):
    """Another CLI process held the session-refresh lock for too long."""


class _SessionFileLock:
    """A small, POSIX-only inter-process lock beside a session file.

    ScriptNow CLI supports macOS and Linux. ``flock`` is deliberately used
    instead of an in-memory lock because a normal CLI invocation is a new
    process. The lock file contains no credentials and is retained as a safe,
    empty coordination point after release.
    """

    def __init__(self, path: Path, *, timeout: float | None = None) -> None:
        self.path = path.with_name(f"{path.name}.refresh.lock")
        self.timeout = _refresh_lock_timeout() if timeout is None else timeout
        self._fd: int | None = None

    def __enter__(self) -> "_SessionFileLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except OSError as error:
            raise _SessionFileError("无法创建本地登录续期锁") from error

        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    self._close()
                    raise _SessionFileError("无法获取本地登录续期锁") from error
                if time.monotonic() >= deadline:
                    self._close()
                    raise _SessionLockTimeout()
                time.sleep(0.05)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                self._close()

    def _close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None


def _refresh_lock_timeout() -> float:
    """Return a bounded, configurable wait for another CLI refresh process."""
    raw = os.environ.get("SCRIPTNOW_CLI_REFRESH_LOCK_TIMEOUT_SECONDS", "15")
    try:
        return max(0.1, min(float(raw), 120.0))
    except ValueError:
        return 15.0


def _state_marker(base_url: str, cookies: dict[str, str], csrf: str) -> str:
    """Credential-state comparison used only in memory; never logged."""
    return json.dumps(
        {"base_url": base_url.rstrip("/"), "cookies": cookies, "csrf": csrf},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_session_payload(path: Path) -> dict[str, Any]:
    """Read and minimally validate a saved session without exposing secrets."""
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _SessionFileError("本地登录会话文件损坏或无法读取") from error
    if not isinstance(value, dict):
        raise _SessionFileError("本地登录会话文件格式无效")
    base_url = value.get("base_url")
    cookies = value.get("cookies")
    csrf = value.get("csrf")
    if not isinstance(base_url, str) or not isinstance(cookies, dict) or not isinstance(csrf, str):
        raise _SessionFileError("本地登录会话文件格式无效")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in cookies.items()):
        raise _SessionFileError("本地登录会话文件格式无效")
    return value


@dataclass
class Session:
    base_url: str
    cookies: dict[str, str] = field(default_factory=dict)
    csrf: str = ""
    _http: requests.Session = field(default_factory=requests.Session, repr=False)
    _persisted_marker: str | None = field(default=None, repr=False)

    @property
    def api_root(self) -> str:
        return f"{self.base_url}/api"

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        form_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        write: bool = False,
        timeout: int = 120,
        command: str | None = None,
        headers: dict[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        file_positions: list[tuple[Any, int]] = []
        for value in (files or {}).values():
            candidate = value
            if isinstance(value, (tuple, list)) and len(value) > 1:
                candidate = value[1]
            if hasattr(candidate, "tell") and hasattr(candidate, "seek"):
                try:
                    file_positions.append((candidate, int(candidate.tell())))
                except (OSError, ValueError):
                    pass

        def _perform() -> requests.Response:
            for handle, position in file_positions:
                try:
                    handle.seek(position)
                except (OSError, ValueError):
                    pass
            request_headers: dict[str, str] = {
                # 请求元数据：让服务端能够区分 CLI 与网页/自写脚本，并审计到
                # 具体命令与调用（client 类型 + 版本 + 命令 + 调用标识）。
                "X-ScriptNow-Client": "scriptnow-cli",
                "X-ScriptNow-Client-Version": _CLIENT_VERSION,
                "X-ScriptNow-Command": command or "",
                "X-ScriptNow-Invocation": _INVOCATION_ID,
            }
            if headers:
                request_headers.update(headers)
            if write:
                if not self.csrf:
                    raise ScriptNowError(
                        "session is missing CSRF token; run 'scriptnow login'"
                    )
                request_headers["X-CSRF-Token"] = self.csrf
            response = self._http.request(
                method,
                f"{self.api_root}{path}",
                headers=request_headers,
                json=json_body,
                data=form_data,
                params=params,
                files=files,
                cookies=self.cookies or None,
                timeout=timeout,
            )
            # Absorb cookies set by the response (login / refresh).
            for cookie in response.cookies:
                self.cookies[cookie.name] = cookie.value
                if cookie.name == "sf_csrf":
                    self.csrf = cookie.value
            return response

        try:
            response = _perform()
        except requests.RequestException as error:
            err = ScriptNowError(f"network error: {error}")
            _record(err, command)
            raise err from error
        minimum_cli = response.headers.get("X-ScriptNow-Minimum-CLI-Version", "")
        api_contract = response.headers.get("X-ScriptNow-API-Contract", "")
        required = _version_tuple(minimum_cli)
        current = _version_tuple(_CLIENT_VERSION)
        # Only enforce the contract when this is a genuine ScriptNow API response
        # (both contract headers present). Non-API endpoints / gateway error
        # pages may inject unrelated headers and would otherwise spuriously fail
        # the check (e.g. a placeholder minimum of "9.0.0").
        if api_contract and minimum_cli and required is not None and current is not None and current < required:
            err = ScriptNowError(
                f"CLI {_CLIENT_VERSION} 与平台合同 {api_contract or 'unknown'} 不兼容；"
                f"最低需要 {minimum_cli}，请运行 scriptnow self-upgrade"
            )
            _record(err, command)
            raise err
        # Access tokens are short-lived (platform default: 60 minutes) while
        # refresh tokens last for days. A long-running agent session would
        # otherwise hit 401 mid-work and stall. On 401, rotate the persisted
        # refresh token once and retry the original request before giving up.
        if response.status_code == 401:
            try:
                refreshed = self._refresh()
            except ScriptNowError as error:
                _record(error, command)
                raise
            if refreshed:
                try:
                    response = _perform()
                except requests.RequestException as error:
                    err = ScriptNowError(f"network error: {error}")
                    _record(err, command)
                    raise err from error
        if response.status_code == 401:
            err = ScriptNowError("登录状态已失效，请重新运行 scriptnow login")
            _record(err, command)
            raise err
        if response.status_code >= 400:
            detail = _extract_detail(response)
            error = ScriptNowError(f"HTTP {response.status_code}: {detail}")
            _record(error, command)
            raise error
        if raw:
            return response
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def _refresh(self) -> bool:
        """Rotate access/refresh/CSRF cookies via POST /api/auth/refresh.

        Returns True when a fresh session is available. The persisted session
        file is updated so the next CLI invocation also benefits from the
        rotation. Never raises; a failed rotation simply reports False so the
        caller can surface the usual "session expired" error.
        """
        path = _config_path()
        try:
            with _SessionFileLock(path):
                # Another process may have already rotated a one-time refresh
                # token while this invocation was waiting. Always reload after
                # acquiring the lock; never let a stale response overwrite it.
                payload = _read_session_payload(path)
                latest_base_url = str(payload["base_url"]).rstrip("/")
                latest_cookies = dict(payload["cookies"])
                latest_csrf = str(payload["csrf"])
                latest_marker = _state_marker(latest_base_url, latest_cookies, latest_csrf)
                baseline = self._persisted_marker or _state_marker(
                    self.base_url, self.cookies, self.csrf
                )
                if latest_marker != baseline:
                    self.base_url = latest_base_url
                    self.cookies = latest_cookies
                    self.csrf = latest_csrf
                    self._persisted_marker = latest_marker
                    return bool(self.cookies.get("sf_refresh") and self.csrf)
                # Refresh with exactly the durable state that was protected by
                # this lock. A 401 response must not leave an incidental
                # Set-Cookie mutation in memory as the input to token rotation.
                self.base_url = latest_base_url
                self.cookies = latest_cookies
                self.csrf = latest_csrf
                self._persisted_marker = latest_marker
                if not self.cookies.get("sf_refresh") or not self.csrf:
                    return False
                try:
                    response = self._http.post(
                        f"{self.api_root}/auth/refresh",
                        headers={"X-CSRF-Token": self.csrf},
                        cookies=self.cookies or None,
                        timeout=60,
                    )
                except requests.RequestException:
                    return False
                if response.status_code != 200:
                    return False
                rotated = False
                for cookie in response.cookies:
                    self.cookies[cookie.name] = cookie.value
                    if cookie.name == "sf_csrf":
                        self.csrf = cookie.value
                        rotated = True
                if not rotated:
                    return False
                # Atomic replacement makes a complete new cookie set visible as
                # one unit to other CLI processes. A failed save must not make
                # this request fail: the freshly rotated in-memory session can
                # still retry its original request.
                try:
                    self.save(path)
                except OSError:
                    pass
                return True
        except _SessionLockTimeout as error:
            raise ScriptNowError(
                "等待另一条 ScriptNow CLI 命令完成登录续期超时；请等待该命令结束后重试"
            ) from error
        except _SessionFileError as error:
            raise ScriptNowError(
                "本地登录会话文件损坏或不可读取，未覆盖原文件；请重新登录后重试"
            ) from error

    def save(self, path: Path) -> None:
        payload = {
            "base_url": self.base_url,
            "cookies": self.cookies,
            "csrf": self.csrf,
            "saved_at": int(time.time()),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        # The session holds live auth cookies: restrict the file (and its
        # directory) to the owner so other local users cannot read them.
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass  # best-effort on platforms without POSIX chmod
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{_uuid.uuid4().hex}.tmp")
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            # Best effort durability for the rename on POSIX filesystems.
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
        try:
            path.chmod(0o600)
        except OSError:
            pass  # best-effort on platforms without POSIX chmod
        self._persisted_marker = _state_marker(self.base_url, self.cookies, self.csrf)


def _record(error: Exception, command: str | None) -> None:
    """记录 CLI 错误到诊断日志（失败不影响主流程）。"""
    try:
        from cli_anything.scriptnow.utils.diag import record_error

        record_error(command=command or "", args=tuple(), detail=str(error))
    except Exception:
        pass


def _extract_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict) and body.get("agent_detail"):
        detail = body["agent_detail"]
        if isinstance(detail, str):
            return detail[:300]
    if isinstance(body, dict) and body.get("detail"):
        detail = body["detail"]
        if isinstance(detail, str):
            return detail[:300]
        if isinstance(detail, list) and detail:
            return json.dumps(detail[0], ensure_ascii=False)[:300]
    return response.text[:300]


def _config_path() -> Path:
    override = os.environ.get("SCRIPTNOW_CLI_CONFIG")
    if override:
        return Path(override)
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "scriptnow-cli"
        / "session.json"
    )


def login(base_url: str, email: str, password: str) -> Session:
    session = Session(base_url=base_url.rstrip("/"))
    payload = {"email": email, "password": password}
    response = session._http.post(
        f"{session.api_root}/auth/login",
        json=payload,
        timeout=60,
    )
    if response.status_code != 200:
        raise ScriptNowError(
            f"login failed (HTTP {response.status_code}): {_extract_detail(response)}"
        )
    for cookie in response.cookies:
        session.cookies[cookie.name] = cookie.value
        if cookie.name == "sf_csrf":
            session.csrf = cookie.value
    if not session.csrf:
        raise ScriptNowError("login response did not set CSRF cookie")
    session.save(_config_path())
    return session


def load() -> Session:
    path = _config_path()
    if not path.exists():
        raise ScriptNowError(
            "没有已保存的会话。请先运行: scriptnow login --host <平台地址> --email <账号> --password <密码>\n"
            "例如: scriptnow login --host https://sn.igeewa.com --email you@example.com --password '...'"
        )
    try:
        payload = _read_session_payload(path)
    except _SessionFileError as error:
        raise ScriptNowError(
            "本地登录会话文件损坏或不可读取，未覆盖原文件；请重新运行 scriptnow login"
        ) from error
    base_url = str(payload["base_url"]).rstrip("/")
    cookies = dict(payload.get("cookies") or {})
    csrf = str(payload.get("csrf") or "")
    session = Session(
        base_url=base_url,
        cookies=cookies,
        csrf=csrf,
        _persisted_marker=_state_marker(base_url, cookies, csrf),
    )
    return session


def write_json(value: Any) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
