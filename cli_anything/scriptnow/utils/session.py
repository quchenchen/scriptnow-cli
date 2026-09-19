"""Authenticated HTTP session for the ScriptNow platform.

The platform authenticates via cookie + CSRF (same-origin web model):
- Browser authorization exchanges a one-time PKCE grant for sf_access / sf_refresh / sf_csrf cookies.
- Mutating requests must send the X-CSRF-Token header matching the sf_csrf cookie.
- The session is persisted locally (base_url, cookies, csrf) so a CLI run does
  not re-login on every invocation; passwords are never stored; session credentials are stored locally.

Endpoints are reached under ``<base_url><api_prefix>/...`` for platform APIs and
``<base_url><api_prefix>/novel/...`` / ``<base_url><api_prefix>/script/...`` for
domain APIs. ``api_prefix`` defaults to ``/api`` and can be relocated by the host
via :data:`API_PREFIX_ENV` — see :func:`api_prefix` for why that matters.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import re
import errno
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:  # POSIX inter-process refresh lock.
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised on Windows.
    _fcntl = None

try:  # Windows inter-process refresh lock.
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX.
    _msvcrt = None

import requests

from cli_anything.scriptnow import __version__ as _CLIENT_VERSION
from cli_anything.scriptnow.utils.hosted import (
    hosted_instance,
    login_remedy,
    login_remedy_example,
)

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
    """The local session file's **content** cannot be used (corrupt / invalid).

    Exclusively about content. Anything that is about *access* — permissions,
    a read-only filesystem, a sandbox that did not bind the directory
    read-write — must use :class:`_SessionAreaError` instead, or the user (and
    any agent reading the message) is told a healthy session is corrupt.
    """


class _SessionAreaError(RuntimeError):
    """The session's directory, file, or refresh lock cannot be accessed.

    Covers read-only filesystems, permission denials, sandboxes that bind the
    directory read-only, and platforms without a usable locking primitive.
    **Never** file corruption: the session itself may be perfectly valid, only
    its location is unusable.

    Why EROFS has to be in here (2026-09-17 field incident)
    ------------------------------------------------------
    dsh's sandbox read-only-binds ``/`` and then binds **only** the agent's
    workspace read-write (``packages/sandbox/sandbox-local/src/profiles.ts``;
    ``writableRoots`` in ``packages/sandbox/sandbox/src/roots.ts`` hardcodes
    ``[workspaceRoot, '/tmp', tmpdir()]`` with no extension point). A session
    file kept *outside* that workspace therefore reads back perfectly while
    ``session.json.refresh.lock`` cannot be created: ``open()`` answers
    ``EROFS("Read-only file system")``, **not** ``EACCES``.

    Before this class existed the lock's ``OSError`` was funnelled into
    :class:`_SessionFileError` (only ``EPERM``/``EACCES`` were special-cased),
    so a live, valid session was reported to the user — and to the agent, which
    then invented devtools workarounds — as
    "本地登录会话文件损坏或不可读取", together with a "log in again" hint that
    cannot work inside a hosted instance. The lesson: *unusable location* and
    *unusable content* must never share a message, and every errno from the
    lock path belongs to the former.
    """


class _SessionLockTimeout(RuntimeError):
    """Another CLI process held the session-refresh lock for too long."""


def _area_error(error: OSError, action: str) -> _SessionAreaError:
    """Turn a session-area :class:`OSError` into an actionable diagnosis.

    The errno and its ``strerror`` text are kept verbatim on purpose: they are
    what tells a read-only filesystem (EROFS) apart from a plain permission
    denial, and they carry no credentials. Without them the only thing a
    support conversation can say is "it failed".

    Deliberately *not* raised as :class:`_SessionFileError`: the file may be
    valid. Only its location is unusable. See :class:`_SessionAreaError`.
    """
    if error.errno is None:
        reason = str(error)
    else:
        reason = f"errno={error.errno} {os.strerror(error.errno)}"
    return _SessionAreaError(f"{action}（{reason}）")


#: 所有「会话目录/锁不可访问」文案里都出现的一句话。它同时是两个消费者的判据：
#: ``doctor`` 用它把「修复：」行从「重新登录」换成目录修法，``utils/diag.py`` 用它
#: 给出 ``CLI_SESSION_DIR_UNWRITABLE`` 错误码。改文案必须一起改这两处。
#:
#: 措辞刻意**不含「损坏」二字**：第三方 agent 读到消息后最可能的动作就是找
#: ``"损坏" in message`` 这类朴素判据，而「这不是会话损坏」恰好会把那个判据点亮。
#: 只陈述正面事实（会话本身完好），既有信息量又不给误判留钩子。
AREA_ERROR_MARKER = "会话本身完好"


def is_area_error_text(text: str) -> bool:
    """True when a user-facing message came from :func:`_area_message`.

    Lets a caller distinguish "the session's *location* is unusable" from
    "the session is dead" without matching on which exception was raised —
    the message is all that survives into ``doctor``'s report.
    """
    return AREA_ERROR_MARKER in text


def area_remedy() -> str:
    """The short ``修复：`` line for a session-area fault.

    Replaces :func:`~cli_anything.scriptnow.utils.hosted.login_remedy` in that
    one case: telling a user to log in when their session is merely in a
    read-only directory sends them down a flow that cannot succeed (and times
    out outright inside a hosted instance).
    """
    if hosted_instance():
        return "稍后重试；若持续出现，请宿主确认会话落点在 agent 工作区内（不要重新登录）"
    return "把 SCRIPTNOW_CLI_CONFIG 指向可写路径后重试（不要重新登录）"


def _area_message(error: Exception) -> str:
    """User- and agent-facing text for a :class:`_SessionAreaError` refresh.

    Three properties, all learned from the 2026-09-17 incident:

    1. It must never say 损坏 / "corrupted" — the session is intact, and an
       agent told otherwise goes hunting for a fault that does not exist.
    2. It must not tell the user to log in. In a hosted instance the session is
       minted by the host and ``scriptnow login`` can only time out there, so
       the only useful advice is "retry" plus, if it persists, "the host placed
       the session outside the agent's writable area".
    3. It must carry the underlying cause verbatim. The errno and its
       ``strerror`` text are the one thing that separates a read-only
       filesystem from a plain permission denial, and they are otherwise
       unreachable: only this ``ScriptNowError`` text is ever displayed or
       logged, never its ``__cause__``.

    Kept short: ``doctor`` truncates ``login_error`` to 240 characters, and the
    actionable part has to survive that cut. Always contains
    :data:`AREA_ERROR_MARKER` and never the word 损坏.
    """
    cause = str(error).strip()
    detail = f"｜{cause}" if cause else ""
    prefix = (
        f"{AREA_ERROR_MARKER}，只是它所在的目录或续期锁不可访问"
        f"（只读文件系统、权限或沙箱拦截）{detail}"
    )
    if hosted_instance():
        return (
            f"{prefix}。会话由宿主下发，请稍后重试；"
            "若持续出现，说明宿主把会话放在了 agent 工作区之外，需要宿主侧修正"
        )
    return (
        f"{prefix}：请将 SCRIPTNOW_CLI_CONFIG 指向可写路径"
        "（如 <工作区>/.scriptnow-cli/session.json，复制现有 session 并 chmod 600）后重试"
    )


class _SessionFileLock:
    """A small cross-platform inter-process lock beside a session file.

    A normal CLI invocation is a new process, so an in-memory lock cannot
    coordinate refresh-token rotation. POSIX uses ``flock`` and Windows uses
    ``msvcrt.locking`` on the first byte. The file contains no credentials.
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
            # **Every** errno here is an access problem, not a content problem —
            # including EROFS ("Read-only file system"), which is what a sandbox
            # answers when the session lives outside the writable area. Never
            # route this into _SessionFileError; see _SessionAreaError.
            raise _area_error(error, "无法创建本地登录续期锁") from error

        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._lock()
                return self
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    self._close()
                    raise _area_error(error, "无法获取本地登录续期锁") from error
                if time.monotonic() >= deadline:
                    self._close()
                    raise _SessionLockTimeout()
                time.sleep(0.05)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        if self._fd is not None:
            try:
                self._unlock()
            finally:
                self._close()

    def _lock(self) -> None:
        if self._fd is None:
            raise _SessionAreaError("本地登录续期锁未初始化（内部状态异常）")
        if _fcntl is not None:
            _fcntl.flock(self._fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            return
        if _msvcrt is not None:
            if os.fstat(self._fd).st_size == 0:
                os.write(self._fd, b"\0")
                os.fsync(self._fd)
            os.lseek(self._fd, 0, os.SEEK_SET)
            _msvcrt.locking(self._fd, _msvcrt.LK_NBLCK, 1)
            return
        raise _SessionAreaError("当前系统既无 fcntl 也无 msvcrt，无法创建本地登录续期锁")

    def _unlock(self) -> None:
        if self._fd is None:
            return
        if _fcntl is not None:
            _fcntl.flock(self._fd, _fcntl.LOCK_UN)
            return
        if _msvcrt is not None:
            os.lseek(self._fd, 0, os.SEEK_SET)
            _msvcrt.locking(self._fd, _msvcrt.LK_UNLCK, 1)

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


def _access_subject(token: str) -> str:
    """Read ``sub`` from an access token **without verifying it**.

    Not a security decision: the host recomputes the expected secret *for that
    user id* and compares, so a forged subject simply fails. We need the subject
    only to tell the host *which* instance is asking.

    Args:
        token: The ``sf_access`` JWT (or anything else).
    Returns:
        The subject claim, or ``""`` when it cannot be read.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return ""
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:  # noqa: BLE001 - 任何畸形输入都只是"读不出来"
        return ""
    subject = claims.get("sub") if isinstance(claims, dict) else None
    return subject if isinstance(subject, str) else ""


#: 平台 API 相对 ``base_url`` 的挂载点（宿主可覆盖，见 :func:`api_prefix`）。
API_PREFIX_ENV = "SCRIPTNOW_API_PREFIX"

#: 独立部署下平台 API 的挂载点，与历史行为一致。
_DEFAULT_API_PREFIX = "/api"


def api_prefix() -> str:
    """Return the platform API mount point, relative to ``base_url``.

    Why this is a setting and not a constant
    ----------------------------------------

    ``base_url`` answers *which* platform; the prefix answers *where* that
    platform's API is mounted. In a standalone deployment they are the same
    thing (``/api``). Behind the dsh integration gateway they are not:
    deepseek-harness hardcodes ``/api`` for its own HTTP carrier, so the
    integrated deployment moves the platform to ``/sn-api`` and the gateway's
    login gate protects everything under ``/api``.

    A CLI that unconditionally appended ``/api`` therefore addressed the *agent*
    namespace, was answered by the gate with ``401 platform login required``, and
    — because a gate 401 is indistinguishable from an expired session — reported
    "登录状态已失效" while its refresh token sat unused. Live evidence
    (2026-09-17): the instance's session file was never rewritten once, i.e. not
    a single refresh had ever succeeded, because none of them reached the
    platform.

    Validated rather than trusted: a malformed value raises here, loudly and
    once, instead of silently falling back to ``/api`` — which would reproduce
    exactly the confusing "logged out" symptom this setting exists to remove.
    """
    raw = os.environ.get(API_PREFIX_ENV, "").strip()
    if raw == "":
        return _DEFAULT_API_PREFIX
    # `/` means "the API is mounted at the root" — the empty suffix is correct.
    return _validate_mount_prefix(raw, API_PREFIX_ENV)


#: 平台**网页**（Creator 前端）相对 ``base_url`` 的挂载点。
#:
#: 与 :data:`API_PREFIX_ENV` 是两个不同的挂载点，不能混用：整合形态下
#: API 在 ``/sn-api``，而网页在 ``/platform/``（站点根 ``/`` 让给了 agent 外壳）。
WEB_PREFIX_ENV = "SCRIPTNOW_WEB_PREFIX"

#: 独立部署下网页就挂在站点根，所以默认是空串（不是 ``/``）。
_DEFAULT_WEB_PREFIX = ""


def web_prefix() -> str:
    """Return the platform **web UI** mount point, relative to ``base_url``.

    Why this exists (the ``/cli/authorize`` link was broken in production)
    ---------------------------------------------------------------------

    ``scriptnow login`` opens ``base_url + "/cli/authorize"``. That was correct
    while the Creator owned the site root. In the integrated deployment the root
    belongs to the agent shell and the Creator moved to ``/platform/``, so the
    link landed in the wrong application entirely — the browser authorization
    page was unreachable on the very deployment that most needed it.

    Same shape as :func:`api_prefix`: a mount point is a *deployment* fact, not a
    constant, so the host states it and the CLI validates rather than guesses.
    """
    raw = os.environ.get(WEB_PREFIX_ENV, "").strip()
    if raw == "":
        return _DEFAULT_WEB_PREFIX
    return _validate_mount_prefix(raw, WEB_PREFIX_ENV)


def _validate_mount_prefix(raw: str, env_name: str) -> str:
    """Validate a mount-point environment variable and normalise its trailing slash.

    Shared by :func:`api_prefix` and :func:`web_prefix` so the two cannot drift
    apart in what they accept — they are the same class of value, and a rule that
    only one of them enforces is a rule that will be wrong for the other.

    Args:
        raw: The raw environment value (already stripped, non-empty).
        env_name: Variable name, used to make the error actionable.
    Returns:
        The value without a trailing slash.
    Raises:
        ScriptNowError: The value is not a single-slash absolute path, or contains
            traversal, whitespace or control characters.
    """
    if not raw.startswith("/") or raw.startswith("//"):
        raise ScriptNowError(
            f"{env_name} 必须是本站绝对路径（以单个 / 开头），收到：{raw!r}"
        )
    if "\\" in raw or ".." in raw.split("/"):
        raise ScriptNowError(f"{env_name} 含非法路径片段，收到：{raw!r}")
    if any(character.isspace() or ord(character) < 0x20 for character in raw):
        raise ScriptNowError(f"{env_name} 含空白或控制字符，收到：{raw!r}")
    return raw.rstrip("/")


def web_url(base_url: str, path: str) -> str:
    """Join a site-relative path into an absolute, openable URL.

    Every user-facing link the CLI prints must go through here. Building one by
    hand is exactly how ``/cli/authorize`` ended up pointing at the wrong
    application in the integrated deployment.

    Args:
        base_url: Platform origin, e.g. ``https://sn.igeewa.com``.
        path: Site-relative path beginning with ``/``, e.g. ``/device``.
    Returns:
        Absolute URL including the configured web prefix.
    Raises:
        ScriptNowError: ``path`` is not site-relative (a caller passing an already
            absolute URL would otherwise get a silently doubled prefix).
    """
    if not path.startswith("/") or path.startswith("//"):
        raise ScriptNowError(f"网页路径必须是站点相对路径（以 / 开头），收到：{path!r}")
    return f"{base_url.rstrip('/')}{web_prefix()}{path}"


def platform_base(host: str) -> str:
    """Validate and normalise a platform address into a ``base_url``.

    Shared by both login flows (browser PKCE and device code) so they cannot
    disagree about what counts as an acceptable platform address. Plain HTTP is
    allowed only for loopback, because the authorization exchange carries a
    session in the clear.

    Args:
        host: User-supplied platform address.
    Returns:
        The address without a trailing slash.
    Raises:
        ScriptNowError: Not HTTPS, or HTTP to a non-loopback host, or carrying
            credentials / query / fragment / a path.
    """
    origin = urlsplit(host)
    if (origin.scheme not in {"http", "https"} or not origin.netloc or origin.username
            or origin.password or origin.query or origin.fragment or origin.path not in {"", "/"}
            or (origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise ScriptNowError("登录地址必须为 HTTPS 平台地址；仅本机开发允许 HTTP")
    return host.rstrip("/")


#: 宿主代持 refresh 模式（W5）下，实例用来续期的**每实例密钥**（由宿主注入）。
#:
#: 为什么它读得到也没关系：它的价值只等于"能刷新**自己**这条实例会话"，换不出别人的
#: （宿主按 userId 派生，密钥与用户一一对应）。详见
#: `docs/DSH-INSTANCE-CREDENTIAL-SCOPING.md`。
INSTANCE_SECRET_ENV = "SCRIPTNOW_INSTANCE_SECRET"


def instance_secret() -> str:
    """Return the host-issued instance credential, or ``""`` when not host-managed.

    Presence of this variable is what tells the CLI that *the host holds the
    refresh token*: the session file then carries only a short-lived access
    token, and renewal has to go back to the host rather than to the platform.
    """
    return os.environ.get(INSTANCE_SECRET_ENV, "").strip()


def _session_usable(cookies: dict[str, str], csrf: str) -> bool:
    """Whether an already-reloaded session can still serve requests.

    Two shapes are usable, and telling them apart is a W5 artifact. A
    self-managed install holds ``sf_refresh`` and renews against the platform
    itself; a host-managed instance deliberately holds **no** refresh and renews
    through the host with the per-instance secret. Judging both by "is there a
    refresh token" made the *loser* of a concurrent rotation report
    「登录状态已失效」 even though it had just reloaded a fresh access token.
    Before W5 the two shapes were identical, which is why this equivalence went
    unnoticed; ``tests/test_host_refresh.py`` pins both directions.
    """
    if csrf == "" or not cookies.get("sf_access"):
        return False
    return bool(cookies.get("sf_refresh")) or instance_secret() != ""


#: 整合形态网关在「未登录 + 非文档请求」时回的标记头（`gateway/session-gate.mjs`）。
_GATE_HEADER = "x-scriptnow-gate"
_GATE_LOGIN_REQUIRED = "login-required"
_GATE_BODY_PREFIX = "platform login required"


def _is_gateway_login_required(response: requests.Response) -> bool:
    """True when this 401 came from the integration gateway's login gate.

    The gate and the platform both answer 401 and look alike to a caller, but
    they mean opposite things: the gate means *you addressed the wrong
    namespace* (it protects dsh's ``/api``; the platform is mounted at
    ``/sn-api``), while the platform's own 401 means *this session is expired*.
    Telling them apart is what lets any third-party agent fix itself with one
    environment variable instead of guessing endpoints or asking a human for
    credentials.

    Matched on the gate's own marker header, degrading to the body text because
    the gateway may be older than this CLI.
    """
    if str(response.headers.get(_GATE_HEADER, "")).strip() == _GATE_LOGIN_REQUIRED:
        return True
    try:
        return response.text.lstrip().startswith(_GATE_BODY_PREFIX)
    except Exception:  # noqa: BLE001 - 正文不可读时按「不是网关」处理
        return False


def stale_marker_path(session_path: Path) -> Path:
    """Sibling file the CLI leaves when a refresh was definitively rejected.

    Name must stay in sync with the gateway's reader
    (``dsh-integration/gateway/cli-session-dispatch.mjs``), which derives the
    same name from ``SCRIPTNOW_CLI_CONFIG``: ``session.json`` →
    ``session.stale.json``.
    """
    return session_path.with_suffix(".stale.json")


def _read_session_payload(path: Path) -> dict[str, Any]:
    """Read and minimally validate a saved session without exposing secrets.

    Failure modes are deliberately kept apart — *inaccessible* is
    :class:`_SessionAreaError`, *unusable content* is :class:`_SessionFileError`.
    Collapsing the two is exactly what let a sandbox denial masquerade as
    "会话文件损坏" (2026-09-17), and it also makes the message say which of the
    two actually happened.
    """
    try:
        raw = path.read_text()
    except OSError as error:
        raise _area_error(error, "无法读取本地登录会话文件") from error
    except UnicodeDecodeError as error:
        raise _SessionFileError("本地登录会话文件损坏（不是有效的 UTF-8 文本）") from error
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise _SessionFileError("本地登录会话文件损坏（不是合法的 JSON）") from error
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
    #: 上一次 `_refresh()` 收到的 HTTP 状态（没拿到响应则为 None）。
    #: 只有 401/403 才算「平台明确拒绝这条 refresh」；网络错误与 5xx 不算。
    _refresh_rejection: int | None = field(default=None, repr=False)

    @property
    def api_root(self) -> str:
        """``base_url`` + the platform's API mount point (see :func:`api_prefix`)."""
        return f"{self.base_url}{api_prefix()}"

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
                        f"session is missing CSRF token；{login_remedy()}"
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
            # 先判「是不是打错了地方」，再判「登录过期」。
            #
            # 整合形态的网关对自己命名空间之外、又未登录的请求回
            # `401 platform login required` —— 它跟「会话过期」都是 401，但修法
            # 完全不同（改 API 挂载点 vs 重新登录）。任何第三方 agent 都没有本
            # 仓库的上下文，把前者读成后者就只能去猜：2026-09-17 线上事故里，
            # agent 因此试遍了猜测的端点，最后请用户从 devtools 里复制 cookie。
            if _is_gateway_login_required(response):
                err = ScriptNowError(
                    f"平台 API 不在 {self.api_root}：网关把它当成自己的路径并回了登录页要求的 401。"
                    f"请把 {API_PREFIX_ENV} 指向平台 API 的真实挂载点"
                    f"（dsh 整合形态是 /sn-api，独立部署是 /api）后重试"
                )
                _record(err, command)
                raise err
            if self._refresh_rejection in (401, 403):
                # 只有平台**明确拒绝**这条 refresh 才说明会话真的没用了，值得让
                # 宿主换发；网络抖动与 5xx 都不算（留标记会白白多造一条会话）。
                self._mark_session_stale()
            err = ScriptNowError(f"登录状态已失效；{login_remedy()}")
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
        rotation.

        A rotation the platform rejected, a network failure, or an unreadable
        file all report ``False`` so the caller can surface the usual "session
        expired" error. Raises only when the *refresh itself* could not be
        attempted — another CLI process holds the lock, or the session's
        directory is not accessible — because those are environment faults, not
        evidence that the session is dead, and they must not be reported as
        "登录状态已失效".
        """
        path = _config_path()
        # 每次刷新都先清空上一次的判定，避免陈旧的拒绝状态误触发「会话已死」。
        self._refresh_rejection = None
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
                    return _session_usable(self.cookies, self.csrf)
                # Refresh with exactly the durable state that was protected by
                # this lock. A 401 response must not leave an incidental
                # Set-Cookie mutation in memory as the input to token rotation.
                self.base_url = latest_base_url
                self.cookies = latest_cookies
                self.csrf = latest_csrf
                self._persisted_marker = latest_marker
                if not self.csrf:
                    return False
                if not self.cookies.get("sf_refresh"):
                    # 宿主代持模式（W5）：实例里**本来就没有** refresh —— 它在宿主进程
                    # 内存里。所以这里不是"会话坏了"，是设计如此；续期要回宿主，不是回平台。
                    # 详见 docs/DSH-INSTANCE-CREDENTIAL-SCOPING.md。
                    return self._refresh_from_host(path)
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
                    # 记下状态，供调用方判断「平台是否**明确拒绝**了这条 refresh」。
                    # 但网关的登录闸门不算平台的回答：那个 401 说明请求打错了挂载
                    # 点，会话本身还好端端的。把它记成拒绝，宿主就会白换一条会话
                    # （每次换发都是一条独立会话，见 `_mark_session_stale` 的说明）。
                    if not _is_gateway_login_required(response):
                        self._refresh_rejection = response.status_code
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
                # 旋转成功 = 这条会话还活着的正面证据，撤掉上一次的标记。
                self._clear_session_stale()
                return True
        except _SessionLockTimeout as error:
            raise ScriptNowError(
                "等待另一条 ScriptNow CLI 命令完成登录续期超时；请等待该命令结束后重试"
            ) from error
        except _SessionAreaError as error:
            # 目录/锁不可访问 —— **不是**会话损坏，也不该建议重新登录
            # （宿主实例里 login 只能超时）。文案见 _area_message。
            raise ScriptNowError(_area_message(error)) from error
        except _SessionFileError as error:
            raise ScriptNowError(
                f"本地登录会话文件损坏或不可读取，未覆盖原文件；{login_remedy()}"
            ) from error

    def _refresh_from_host(self, path: Path) -> bool:
        """Renew the access token through the host that holds the refresh token.

        Reachable only in a host-managed instance whose session file carries no
        ``sf_refresh``. The refresh token lives in the gateway process's memory,
        so a leaked instance file no longer holds anything that can resurrect a
        session: what leaks is a short-lived access token that cannot renew
        itself. See ``docs/DSH-INSTANCE-CREDENTIAL-SCOPING.md``.

        Returns ``True`` when a fresh access token is available and persisted.

        Deliberately does **not** set ``_refresh_rejection`` on failure. That
        flag exists so the *host* learns "the platform rejected this refresh"
        from a note the CLI leaves behind — but here the host performed the
        refresh itself and already knows, dropping its copy on a rejection and
        re-minting on the next page load. Leaving a marker would only make it
        mint a second session for no reason.
        """
        secret = instance_secret()
        if secret == "":
            # 没有密钥 ⇒ 不是宿主代持模式（或宿主太老）⇒ 按"需要重新登录"处理。
            return False
        subject = _access_subject(str(self.cookies.get("sf_access") or ""))
        if subject == "":
            return False
        try:
            response = self._http.post(
                f"{self.base_url}/-/agent-session/refresh",
                headers={"x-scriptnow-instance": f"{subject}:{secret}"},
                timeout=30,
            )
        except requests.RequestException:
            return False
        if response.status_code != 200:
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        if not isinstance(payload, dict):
            return False
        cookies = payload.get("cookies")
        csrf = payload.get("csrf")
        access = cookies.get("sf_access") if isinstance(cookies, dict) else None
        if not isinstance(access, str) or access == "" or not isinstance(csrf, str) or csrf == "":
            return False
        self.cookies["sf_access"] = access
        self.cookies["sf_csrf"] = csrf
        # 宿主**不该**回 refresh；真回了也不写进本地 —— 本地留着它就等于 W5 白做。
        self.cookies.pop("sf_refresh", None)
        self.csrf = csrf
        try:
            self.save(path)
        except OSError:
            # 与平台路径同理：存不下去不该让本次请求失败，内存里的新会话仍然可用。
            pass
        return True

    def _mark_session_stale(self) -> None:
        """Leave a "this session's refresh was rejected" note for the host gateway.

        Why a note, rather than letting the gateway re-issue on a timer:
        ``auth.refresh`` is one-time rotation, and reusing an already-used
        refresh token marks the whole session REVOKED. **Only the CLI may consume
        the refresh token** (it serialises concurrent rotations with a file
        lock); if the gateway rotated as well, the two would race into reuse
        detection and kick the user's browser session out. So the gateway waits
        until the CLI reports that this session is genuinely dead.

        The correlation key is the session file's ``saved_at``: the gateway
        compares it against what it reads and trusts only a matching note, so a
        leftover note from an earlier session is inert — and after a re-issue the
        new file carries a new ``saved_at``, which retires the note by itself.

        Hosted instances only: a self-managed install has no host to re-issue
        anything, so a note there would be litter. Best effort — failing to write
        it must not change the error the user sees.
        """
        if not hosted_instance():
            return
        try:
            path = _config_path()
            saved_at = json.loads(path.read_text()).get("saved_at")
            if not isinstance(saved_at, int):
                # 没有关联键，网关就无从判断标记属于哪条会话 —— 写了也没用。
                return
            stale_marker_path(path).write_text(
                json.dumps(
                    {
                        "saved_at": saved_at,
                        "detected_at": int(time.time()),
                        "reason": "refresh-rejected",
                    },
                    ensure_ascii=False,
                )
            )
        except (OSError, ValueError):
            pass

    def _clear_session_stale(self) -> None:
        """Withdraw the "refresh was rejected" note after a successful rotation.

        A successful rotation is positive evidence that this session is alive, so
        the note must go: otherwise the host would re-issue a session for nothing.
        Raising ``saved_at`` via :meth:`save` is *not* enough on its own — a failed
        ``save`` (swallowed below, deliberately) leaves the key unchanged and the
        note would keep matching. Best effort: the note is advisory.
        """
        try:
            stale_marker_path(_config_path()).unlink(missing_ok=True)
        except OSError:
            pass

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
        if isinstance(detail, dict):
            # Platform structured errors ({code, message, guide, ...}) —
            # surface the human message, same source the frontend uses.
            message = detail.get("message") or detail.get("msg")
            if isinstance(message, str):
                return message[:300]
            return json.dumps(detail, ensure_ascii=False)[:300]
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


def load() -> Session:
    path = _config_path()
    if not path.exists():
        # A hosted instance's session file is written by the host, not by the
        # user — pointing them at `scriptnow login` there sends them (and any
        # agent reading the message) down a flow that cannot complete.
        example = login_remedy_example()
        raise ScriptNowError(
            "没有已保存的会话。" + login_remedy() + (f"\n{example}" if example else "")
        )
    try:
        payload = _read_session_payload(path)
    except _SessionAreaError as error:
        # 存在但读不动（权限/沙箱）——不是「损坏」，更不该建议重新登录。
        raise ScriptNowError(_area_message(error)) from error
    except _SessionFileError as error:
        raise ScriptNowError(
            f"本地登录会话文件损坏或不可读取，未覆盖原文件；{login_remedy()}"
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
