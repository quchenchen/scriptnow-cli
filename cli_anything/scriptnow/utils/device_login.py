"""设备码登录（RFC 8628）：托管/无头环境里**唯一**能走通的浏览器授权。

为什么需要它
------------
`scriptnow login`（浏览器 PKCE）在托管实例里必然失败：它会在**实例自己的**
``http://127.0.0.1:<port>/callback`` 上等浏览器回调，而那个 loopback 属于实例，
用户的浏览器到不了。2026-09-17 线上实测的后果不是"报个错就完了"——agent 撞上死路后
开始自行发挥（试换发端点、`cat` 会话文件、最后引导用户从 devtools 复制 Cookie）。

设备流把那一跳拆掉：CLI 领一个短码 → 用户在自己**已登录**的浏览器里确认 →
CLI 轮询取会话。凭据一步都不经过命令行，也不经过 agent 的上下文。

与 `browser_login` 的关系
-------------------------
产物**完全相同**（`Session` + 同一份 `session.json`），差别只在"会话怎么拿到"。
所以落盘、续期、stale 标记那些逻辑一个字都不用改 —— 这也是平台侧刻意让
`/auth/device/token` 的响应形状与 `/auth/cli/session` 一致的原因。
"""

from __future__ import annotations

import time
from urllib.parse import quote

from .session import ScriptNowError, Session, _config_path, platform_base, web_url

#: 收到 `slow_down` 时把轮询间隔往上加的步长。
#:
#: 与平台侧 `device_auth.SLOW_DOWN_STEP_SECONDS` **必须一致**：服务端说"慢 5 秒"，
#: 客户端却只慢 1 秒，会立刻再吃一次 `slow_down`，表现为"轮询一直失败"。
SLOW_DOWN_STEP_SECONDS = 5

#: 轮询间隔上限。与平台侧 `MAX_POLL_INTERVAL_SECONDS` 对齐。
MAX_POLL_INTERVAL_SECONDS = 60

#: 单次 HTTP 请求超时（轮询是短请求，不需要长窗口）。
_REQUEST_TIMEOUT_SECONDS = 30


def _error_detail(response) -> str:
    """从平台的错误响应里取出稳定字面量。

    平台用 ``HTTPException(400, "authorization_pending")`` 表达"还没确认"，
    FastAPI 会把它渲染成 ``{"detail": "authorization_pending"}``。这里**不做**任何
    人类文案映射 —— 状态机判定必须基于稳定字面量，而不是会被翻译的句子。
    """
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - 非 JSON 错误体（网关 HTML 等）也要能处理
        return ""
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
    return ""


def device_login(host: str, *, timeout: int = 180, notify=print) -> Session:
    """用设备码完成登录。

    Args:
        host: 平台地址。
        timeout: 等待用户在浏览器里确认的总秒数（同时受平台 `expires_in` 约束）。
        notify: 输出回调（默认 stderr 打印，绝不把 device_code 打出去）。
    Returns:
        已保存到 `SCRIPTNOW_CLI_CONFIG` 的会话。
    Raises:
        ScriptNowError: 领码失败、平台不支持、用户拒绝、过期、或等待超时。
    """
    base = platform_base(host)
    session = Session(base_url=base)
    code_url = f"{session.api_root}/auth/device/code"

    try:
        response = session._http.post(code_url, timeout=_REQUEST_TIMEOUT_SECONDS)
    except Exception as error:  # noqa: BLE001 - requests 的异常谱系很宽
        raise ScriptNowError(f"无法连接平台（{base}）：{error}") from error
    if response.status_code == 404:
        # 老平台没有设备流端点。说清楚"该升级平台"，而不是让用户以为是自己输错了地址。
        raise ScriptNowError(
            "该平台不支持设备码登录（/auth/device/code 不存在）；请升级平台，"
            "或在本机使用 `scriptnow login`（需要浏览器能回调到本机）"
        )
    if response.status_code != 200:
        raise ScriptNowError(f"领取设备码失败（HTTP {response.status_code}）")
    payload = response.json() if response.content else {}
    if not isinstance(payload, dict):
        raise ScriptNowError("平台返回的设备码响应格式不正确")

    device_code = payload.get("device_code")
    user_code = payload.get("user_code")
    path = payload.get("verification_path") or "/device"
    if not isinstance(device_code, str) or device_code == "":
        raise ScriptNowError("平台返回的设备码响应缺少 device_code")
    if not isinstance(user_code, str) or user_code == "":
        raise ScriptNowError("平台返回的设备码响应缺少 user_code")
    interval = _as_positive_int(payload.get("interval"), default=5)
    expires_in = _as_positive_int(payload.get("expires_in"), default=600)

    # 短码由**平台生成、CLI 原样展示**，用户要拿它和浏览器上显示的串做肉眼比对 ——
    # 这一步是设备流防钓鱼的全部依据，所以两边显示的必须是同一串字符。
    verify_url = web_url(base, str(path))
    complete_url = f"{verify_url}?code={quote(user_code)}"
    notify("请在浏览器中确认授权（不要在任何地方输入密码）：")
    notify(f"  确认码：{user_code}")
    notify(f"  打开：  {complete_url}")
    notify("若链接打不开，请手动访问上面的地址并输入确认码。")

    deadline = time.monotonic() + min(float(timeout), float(expires_in))
    token_url = f"{session.api_root}/auth/device/token"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ScriptNowError("等待浏览器确认超时；请重新运行 scriptnow login --device")
        # 先睡再问：授权页刚打开时必然还没确认，立刻轮询只是白吃一次 slow_down。
        time.sleep(min(float(interval), max(0.0, remaining)))
        try:
            response = session._http.post(
                token_url, json={"device_code": device_code}, timeout=_REQUEST_TIMEOUT_SECONDS
            )
        except Exception as error:  # noqa: BLE001
            raise ScriptNowError(f"轮询授权结果失败：{error}") from error

        if response.status_code == 200:
            return _save_from_payload(session, response.json() if response.content else {})

        detail = _error_detail(response)
        if detail == "authorization_pending":
            continue
        if detail == "slow_down":
            # 服务端要求放慢：跟上它的步长，否则下一次还是会被挡。
            interval = min(interval + SLOW_DOWN_STEP_SECONDS, MAX_POLL_INTERVAL_SECONDS)
            continue
        if detail == "device authorization rejected":
            raise ScriptNowError("你拒绝了本次授权；没有更改原有登录状态")
        if detail == "device code expired":
            raise ScriptNowError("确认码已过期；请重新运行 scriptnow login --device")
        if detail == "device code already used":
            raise ScriptNowError("这条授权已经被使用过；请重新运行 scriptnow login --device")
        raise ScriptNowError(
            f"授权失败（HTTP {response.status_code}）：{detail or '平台未说明原因'}"
        )


def _save_from_payload(session: Session, payload: object) -> Session:
    """把 `/auth/device/token` 的响应落成会话文件（与浏览器登录同一份落盘逻辑）。

    Args:
        session: 待填充的会话对象。
        payload: 平台响应体。
    Returns:
        已保存的会话。
    Raises:
        ScriptNowError: 响应缺 cookie 或 csrf 与 cookie 不一致。
    """
    if not isinstance(payload, dict):
        raise ScriptNowError("平台返回的授权结果格式不正确")
    cookies = payload.get("cookies")
    if not isinstance(cookies, dict):
        raise ScriptNowError("平台没有返回完整的授权会话；未保存登录状态")
    for name in ("sf_access", "sf_refresh", "sf_csrf"):
        value = cookies.get(name)
        if not isinstance(value, str) or value == "":
            raise ScriptNowError("平台没有返回完整的授权会话；未保存登录状态")
        session.cookies[name] = value
    # csrf 与 cookie 不一致会让后续**写操作**全部 403 —— 宁可现在失败也不要存一份坏会话。
    if payload.get("csrf") != cookies.get("sf_csrf"):
        raise ScriptNowError("平台返回的 CSRF 与 cookie 不一致；未保存登录状态")
    session.csrf = str(cookies["sf_csrf"])
    session.save(_config_path())
    return session


def _as_positive_int(value: object, *, default: int) -> int:
    """把平台给的数值收敛成正整数（平台数据不可信，坏值只回退默认，不抛）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if value <= 0:
        return default
    return int(value)
