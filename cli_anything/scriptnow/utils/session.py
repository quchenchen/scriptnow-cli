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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from cli_anything.scriptnow import __version__ as _CLIENT_VERSION

# Per-process invocation id so the server can correlate retries and audit
# a logical call across multiple HTTP requests.
import uuid as _uuid

_INVOCATION_ID = str(_uuid.uuid4())


class ScriptNowError(RuntimeError):
    """Raised when the platform returns an error or the session is unusable."""


@dataclass
class Session:
    base_url: str
    cookies: dict[str, str] = field(default_factory=dict)
    csrf: str = ""
    _http: requests.Session = field(default_factory=requests.Session, repr=False)

    @property
    def api_root(self) -> str:
        return f"{self.base_url}/api"

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        write: bool = False,
        timeout: int = 120,
        command: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        def _perform() -> requests.Response:
            headers: dict[str, str] = {
                # 请求元数据：让服务端能够区分 CLI 与网页/自写脚本，并审计到
                # 具体命令与调用（client 类型 + 版本 + 命令 + 调用标识）。
                "X-ScriptNow-Client": "scriptnow-cli",
                "X-ScriptNow-Client-Version": _CLIENT_VERSION,
                "X-ScriptNow-Command": command or "",
                "X-ScriptNow-Invocation": _INVOCATION_ID,
            }
            if headers:
                headers.update(headers)
            if write:
                if not self.csrf:
                    raise ScriptNowError("session is missing CSRF token; run 'scriptnow login'")
                headers["X-CSRF-Token"] = self.csrf
            response = self._http.request(
                method,
                f"{self.api_root}{path}",
                headers=headers,
                json=json_body,
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
        # Access tokens are short-lived (platform default: 60 minutes) while
        # refresh tokens last for days. A long-running agent session would
        # otherwise hit 401 mid-work and stall. On 401, rotate the persisted
        # refresh token once and retry the original request before giving up.
        if response.status_code == 401 and self._refresh():
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
        if rotated:
            self.save(_config_path())
        return rotated

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
        path.write_text(json.dumps(payload, ensure_ascii=False))
        try:
            path.chmod(0o600)
        except OSError:
            pass  # best-effort on platforms without POSIX chmod


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
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "scriptnow-cli" / "session.json"


def login(base_url: str, email: str, password: str) -> Session:
    session = Session(base_url=base_url.rstrip("/"))
    payload = {"email": email, "password": password}
    response = session._http.post(
        f"{session.api_root}/auth/login",
        json=payload,
        timeout=60,
    )
    if response.status_code != 200:
        raise ScriptNowError(f"login failed (HTTP {response.status_code}): {_extract_detail(response)}")
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
    payload = json.loads(path.read_text())
    session = Session(
        base_url=str(payload["base_url"]),
        cookies=dict(payload.get("cookies") or {}),
        csrf=str(payload.get("csrf") or ""),
    )
    return session


def write_json(value: Any) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
