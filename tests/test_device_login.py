"""设备码登录的 CLI 侧：轮询状态机、限速跟随、错误分类、以及"绝不打印凭据"。

为什么单独测：这条路径是托管实例里**唯一**能走通的登录方式，而它的失败方式很容易
退化成"一直转圈"或"报一句看不出来该干什么的错" —— 2026-09-17 的事故正是从这个
形状开始的（agent 撞上死路后自行发挥）。所以这里把每个状态都钉住。
"""

from unittest.mock import Mock

import pytest

from cli_anything.scriptnow.utils import device_login as module
from cli_anything.scriptnow.utils.session import ScriptNowError

CODE_PAYLOAD = {
    "device_code": "device-secret-code",
    "user_code": "RK-7F2Q",
    "verification_path": "/device",
    "expires_in": 600,
    "interval": 5,
}

TOKEN_PAYLOAD = {
    "cookies": {
        "sf_access": "secret-access",
        "sf_refresh": "secret-refresh",
        "sf_csrf": "secret-csrf",
    },
    "csrf": "secret-csrf",
    "access_expires_at": "2026-09-17T12:00:00Z",
    "tenant_id": "t-1",
    "user_id": "u-1",
}


class FakeClock:
    """把 sleep 变成记账、把 monotonic 变成每调用一次就走 1 秒。

    不真等，也不让循环空转：测试要验的是**状态机**，不是等待本身。
    """

    def __init__(self) -> None:
        self.value = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        self.value += 1.0
        return self.value

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


def response(status: int, payload=None) -> Mock:
    """造一个 requests 风格的响应替身。"""
    result = Mock(status_code=status)
    result.content = b"{}" if payload is not None else b""
    result.json.return_value = payload
    return result


def install(monkeypatch, responses, clock=None):
    """装好 Session 替身与时钟，返回 `(session, messages)`。"""
    clock = clock or FakeClock()
    monkeypatch.setattr(module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(module.time, "sleep", clock.sleep)
    session = Mock()
    session.api_root = "https://platform.test/api"
    session.cookies = {}
    session._http.post.side_effect = responses
    monkeypatch.setattr(module, "Session", lambda **kwargs: session)
    messages: list[str] = []
    return session, messages, clock


def test_happy_path_saves_the_session_and_never_prints_credentials(monkeypatch):
    """领码 → 还没确认 → 已确认 → 落盘；且确认码/凭据的暴露面被钉住。"""
    session, messages, clock = install(monkeypatch, [
        response(200, CODE_PAYLOAD),
        response(400, {"detail": "authorization_pending"}),
        response(200, TOKEN_PAYLOAD),
    ])

    result = module.device_login("https://platform.test", timeout=60, notify=messages.append)

    assert result is session
    assert session.cookies == TOKEN_PAYLOAD["cookies"]
    assert session.csrf == "secret-csrf"
    session.save.assert_called_once()

    printed = "\n".join(messages)
    # 确认码**必须**打印（用户要拿它跟浏览器上显示的串比对），
    # 而 device_code 与三件套**绝不能**出现在输出里。
    assert "RK-7F2Q" in printed
    for secret in ["device-secret-code", "secret-access", "secret-refresh", "secret-csrf"]:
        assert secret not in printed
    # 链接必须带网页前缀（整合形态下 Creator 在 /platform/）
    assert "https://platform.test/device?code=RK-7F2Q" in printed
    assert clock.slept, "轮询之间必须等待，不能空转打平台"


def test_verification_link_honours_the_web_prefix(monkeypatch):
    """`/cli/authorize` 曾经因为漏了网页前缀而把用户送进另一个应用 —— 同一个坑不能再踩。"""
    monkeypatch.setenv("SCRIPTNOW_WEB_PREFIX", "/platform")
    session, messages, _ = install(monkeypatch, [
        response(200, CODE_PAYLOAD),
        response(200, TOKEN_PAYLOAD),
    ])
    module.device_login("https://platform.test", timeout=60, notify=messages.append)
    assert "https://platform.test/platform/device?code=RK-7F2Q" in "\n".join(messages)


def test_slow_down_makes_the_client_wait_longer(monkeypatch):
    """服务端要求放慢时，客户端必须**跟上** —— 否则下一次照样被挡，表现为"一直失败"。"""
    session, messages, clock = install(monkeypatch, [
        response(200, CODE_PAYLOAD),
        response(400, {"detail": "slow_down"}),
        response(200, TOKEN_PAYLOAD),
    ])
    module.device_login("https://platform.test", timeout=60, notify=messages.append)
    first, second = clock.slept[0], clock.slept[1]
    assert second == first + module.SLOW_DOWN_STEP_SECONDS, clock.slept


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("device authorization rejected", "拒绝"),
        ("device code expired", "过期"),
        ("device code already used", "被使用过"),
    ],
)
def test_terminal_states_report_what_to_do_next(monkeypatch, detail, expected):
    """拒绝/过期/已用必须**各自**说清楚，且都指向"重新运行 login --device"。"""
    _, messages, _ = install(monkeypatch, [
        response(200, CODE_PAYLOAD),
        response(400, {"detail": detail}),
    ])
    with pytest.raises(ScriptNowError) as error:
        module.device_login("https://platform.test", timeout=60, notify=messages.append)
    assert expected in str(error.value)


def test_platform_without_device_flow_says_so(monkeypatch):
    """老平台没有这个端点时，要说"平台不支持"，而不是让用户怀疑自己输错了地址。"""
    install(monkeypatch, [response(404, None)])
    with pytest.raises(ScriptNowError) as error:
        module.device_login("https://platform.test", timeout=60, notify=lambda _: None)
    assert "不支持设备码登录" in str(error.value)


def test_incomplete_token_payload_does_not_save_a_broken_session(monkeypatch):
    """响应缺 cookie 时宁可失败也不要存一份坏会话 —— 它会变成"登录了但每个写操作都 403"。"""
    session, _, _ = install(monkeypatch, [
        response(200, CODE_PAYLOAD),
        response(200, {"cookies": {"sf_access": "a", "sf_refresh": "b"}, "csrf": "c"}),
    ])
    with pytest.raises(ScriptNowError):
        module.device_login("https://platform.test", timeout=60, notify=lambda _: None)
    session.save.assert_not_called()


def test_mismatched_csrf_does_not_save_a_broken_session(monkeypatch):
    """csrf 与 cookie 不一致会让后续写操作全 403，必须在落盘前拦住。"""
    session, _, _ = install(monkeypatch, [
        response(200, CODE_PAYLOAD),
        response(200, {**TOKEN_PAYLOAD, "csrf": "something-else"}),
    ])
    with pytest.raises(ScriptNowError):
        module.device_login("https://platform.test", timeout=60, notify=lambda _: None)
    session.save.assert_not_called()


def test_rejects_insecure_or_ambiguous_host():
    """与浏览器登录同一套地址校验（共用 `platform_base`）。"""
    for host in ["http://evil.test", "https://a:b@evil.test", "https://x.test/path"]:
        with pytest.raises(ScriptNowError):
            module.device_login(host, timeout=60, notify=lambda _: None)
