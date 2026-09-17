"""Hosted-instance awareness: who owns this CLI's login session.

Why this module exists
----------------------

A ScriptNow CLI can run in two very different places:

1. **On the author's own machine** — the CLI owns its session: `scriptnow login`
   opens the system browser, the user approves, and the CLI writes
   ``~/.config/scriptnow-cli/session.json``. Telling the user to "run
   ``scriptnow login``" is correct advice.

2. **Inside a host Agent instance** (the deepseek-harness integration) — the
   host mints a per-user session server-side and writes it to the path in
   ``SCRIPTNOW_CLI_CONFIG``; the host sets ``SCRIPTNOW_HOSTED=1``. Here the same
   advice is **wrong and harmful**:

   * ``scriptnow login`` waits for a browser callback on
     ``http://127.0.0.1:<port>/callback`` **inside the instance**. The author's
     browser cannot reach that address, so the flow can only time out.
   * An agent that cannot log in will invent workarounds. On 2026-09-16 a live
     instance's agent asked the author to open devtools and paste
     ``sf_access`` / ``sf_refresh`` / ``sf_csrf`` — a phishing-shaped request
     that must never be necessary, and which hands live credentials to a
     transcript.

   The session genuinely *is* provisioned in that mode, so the only correct
   remedy is "retry / let the host re-issue it", never "log in yourself".

This module is deliberately tiny and dependency-free: both
:mod:`cli_anything.scriptnow.utils.session` (every request path) and
``scriptnow_cli`` (``doctor`` / ``login`` / ``agent-guide``) need it, and an
import cycle between those two would be worse than a 60-line module.
"""

from __future__ import annotations

import os

#: Set by the host application to ``1`` when it owns the CLI's session.
HOSTED_ENV = "SCRIPTNOW_HOSTED"

_FALSY = frozenset({"", "0", "false", "no", "off"})


def hosted_instance() -> bool:
    """Return True when a host application owns this CLI's login session.

    Explicit opt-in via :data:`HOSTED_ENV` only. We deliberately do **not**
    infer it from ``SCRIPTNOW_CLI_CONFIG`` being set: relocating the session
    file is a documented self-service fix for sandboxed/permission-restricted
    setups (see ``_SessionAreaError``), and those users still own their own
    login. Guessing here would tell them not to log in.
    """
    return os.environ.get(HOSTED_ENV, "").strip().lower() not in _FALSY


def login_remedy() -> str:
    """The actionable fix when there is no usable session.

    Drop-in replacement for the old unconditional "run ``scriptnow login``"
    hint. Kept to one sentence so it composes into existing error messages.
    """
    if hosted_instance():
        return (
            "登录会话由宿主 Agent 自动下发，实例内无需也无法运行 scriptnow login"
            "（它要等一个只在你自己电脑上可达的浏览器回调）；请稍后重试，"
            "且不要向任何人索取或粘贴 Cookie"
        )
    return "请先运行: scriptnow login --host <平台地址>（系统浏览器授权）"


def login_remedy_example() -> str:
    """Second line of the "no session" error for a self-managed install.

    Empty in a hosted instance — there is no command to show.
    """
    if hosted_instance():
        return ""
    return "例如: scriptnow login --host https://sn.igeewa.com"


def login_unsupported_message() -> str:
    """Full refusal text for ``scriptnow login`` inside a host instance."""
    return (
        "本 CLI 由宿主 Agent 托管（SCRIPTNOW_HOSTED=1），实例内无法自行登录：\n"
        "  · scriptnow login 会在本实例的 127.0.0.1 上等一个浏览器回调，\n"
        "    而你自己的浏览器到不了这个地址，流程只会超时；\n"
        "  · 登录会话由宿主在你已登录的前提下自动下发到 SCRIPTNOW_CLI_CONFIG，\n"
        "    不需要在这里再登录一次。\n"
        "如果一直提示未登录：请稍后重试，或在对话里请宿主重新下发会话。\n"
        "不要向任何人（包括 Agent）索取或粘贴 Cookie / 密码。\n"
        "（确实要在本机自行登录时，先 unset SCRIPTNOW_HOSTED 再运行。）"
    )
