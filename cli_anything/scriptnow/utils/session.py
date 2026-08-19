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
    ) -> Any:
        headers: dict[str, str] = {}
        if write:
            if not self.csrf:
                raise ScriptNowError("session is missing CSRF token; run 'scriptnow login'")
            headers["X-CSRF-Token"] = self.csrf
        try:
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
        except requests.RequestException as error:
            raise ScriptNowError(f"network error: {error}") from error
        # Absorb cookies set by the response (login / refresh).
        for cookie in response.cookies:
            self.cookies[cookie.name] = cookie.value
            if cookie.name == "sf_csrf":
                self.csrf = cookie.value
        if response.status_code == 401:
            raise ScriptNowError("登录状态已失效，请重新运行 scriptnow login")
        if response.status_code >= 400:
            detail = _extract_detail(response)
            raise ScriptNowError(f"HTTP {response.status_code}: {detail}")
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

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
            "没有已保存的会话。请先运行: scriptnow login --base-url <url> --email <e> --password <p>"
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
