import errno
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from cli_anything.scriptnow.utils.session import Session, ScriptNowError, _extract_detail


def test_extract_detail_prefers_actionable_agent_detail() -> None:
    response = Mock()
    response.json.return_value = {
        "detail": "本次操作暂未完成，请稍后重试。",
        "agent_detail": "Novel StoryMap version conflict",
    }

    assert _extract_detail(response) == "Novel StoryMap version conflict"


def test_extract_detail_unpacks_structured_dict_detail() -> None:
    """Platform structured errors ({code, message, guide}) surface the human
    message, same source the frontend uses — not a raw JSON dump."""
    response = Mock()
    response.json.return_value = {
        "detail": {
            "code": "skill_gate_required",
            "message": "开始剧本创作前，需要先配置写作方法论。",
            "guide": "…",
        }
    }
    assert _extract_detail(response) == "开始剧本创作前，需要先配置写作方法论。"

    response.json.return_value = {"detail": {"code": "x", "note": "无 message 字段"}}
    assert "无 message 字段" in _extract_detail(response)


def test_request_preserves_custom_headers_and_adds_csrf() -> None:
    response = Mock(status_code=204, cookies=[], headers={})
    http = Mock()
    http.request.return_value = response
    session = Session(base_url="https://example.test", csrf="csrf-token", _http=http)

    session.request(
        "POST",
        "/decision",
        write=True,
        headers={"X-Decision-Token": "decision-token"},
    )

    sent = http.request.call_args.kwargs["headers"]
    assert sent["X-CSRF-Token"] == "csrf-token"
    assert sent["X-Decision-Token"] == "decision-token"
    assert sent["X-ScriptNow-Client"] == "scriptnow-cli"


def test_request_rejects_cli_below_server_minimum() -> None:
    response = Mock(
        status_code=200,
        cookies=[],
        headers={
            "X-ScriptNow-Minimum-CLI-Version": "9.0.0",
            "X-ScriptNow-API-Contract": "future-contract",
        },
    )
    http = Mock()
    http.request.return_value = response
    session = Session(base_url="https://example.test", _http=http)

    with pytest.raises(ScriptNowError, match="最低需要 9.0.0"):
        session.request("GET", "/projects")


def test_refresh_survives_session_save_failure(tmp_path, monkeypatch) -> None:
    """配置目录不可写时，refresh 旋转不应因 save() 失败而崩溃整个请求。"""
    first = Mock(status_code=401, cookies=[], headers={})
    second = Mock(status_code=200, cookies=[], headers={})
    refresh_cookie = SimpleNamespace(name="sf_csrf", value="csrf-rotated")
    refresh = Mock(status_code=200, cookies=[refresh_cookie], headers={})
    http = Mock()
    http.request.side_effect = [first, second]
    http.post.return_value = refresh
    session = Session(
        base_url="https://example.test",
        csrf="csrf-token",
        cookies={"sf_refresh": "refresh-token"},
        _http=http,
    )
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    Session(
        base_url="https://example.test",
        csrf="csrf-token",
        cookies={"sf_refresh": "refresh-token"},
    ).save(config_path)

    def _broken_save(path) -> None:
        del path
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(session, "save", _broken_save)
    result = session.request("GET", "/projects")
    assert result is not None
    assert session.csrf == "csrf-rotated"


def test_multipart_file_is_rewound_before_refresh_retry(tmp_path, monkeypatch) -> None:
    first = Mock(status_code=401, cookies=[], headers={})
    second = Mock(status_code=200, cookies=[], headers={})
    refresh_cookie = SimpleNamespace(name="sf_csrf", value="csrf-rotated")
    refresh = Mock(status_code=200, cookies=[refresh_cookie], headers={})
    http = Mock()
    sent_contents: list[bytes] = []
    responses = iter([first, second])

    def request(*args, **kwargs):
        del args
        sent_contents.append(kwargs["files"]["file"][1].read())
        return next(responses)

    http.request.side_effect = request
    http.post.return_value = refresh
    session = Session(
        base_url="https://example.test",
        csrf="csrf-token",
        cookies={"sf_refresh": "refresh-token"},
        _http=http,
    )
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    Session(
        base_url="https://example.test",
        csrf="csrf-token",
        cookies={"sf_refresh": "refresh-token"},
    ).save(config_path)
    handle = BytesIO(b"planning-board-bytes")
    result = session.request(
        "POST",
        "/storyboard/projects/p/scenes/s/planning-boards",
        form_data={"layout_key": "3x3"},
        files={"file": ("board.png", handle, "application/octet-stream")},
        write=True,
    )
    assert result is not None
    assert sent_contents == [b"planning-board-bytes", b"planning-board-bytes"]


def test_concurrent_refresh_reuses_rotated_session_from_disk(tmp_path, monkeypatch) -> None:
    """Two CLI invocations sharing a config cause exactly one refresh request."""
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    initial = {"sf_access": "access-old", "sf_refresh": "refresh-old", "sf_csrf": "csrf-old"}
    Session(
        base_url="https://example.test", cookies=initial.copy(), csrf="csrf-old"
    ).save(config_path)

    first_401 = Mock(status_code=401, cookies=[], headers={})
    first_success = Mock(status_code=200, cookies=[], headers={})
    first_success.json.return_value = {"ok": "first"}
    first_http = Mock()
    first_http.request.side_effect = [first_401, first_success]
    first_http.post.return_value = Mock(
        status_code=200,
        cookies=[
            SimpleNamespace(name="sf_access", value="access-new"),
            SimpleNamespace(name="sf_refresh", value="refresh-new"),
            SimpleNamespace(name="sf_csrf", value="csrf-new"),
        ],
        headers={},
    )
    first = Session(
        base_url="https://example.test", cookies=initial.copy(), csrf="csrf-old", _http=first_http
    )

    second_401 = Mock(status_code=401, cookies=[], headers={})
    second_success = Mock(status_code=200, cookies=[], headers={})
    second_success.json.return_value = {"ok": "second"}
    second_http = Mock()
    second_http.request.side_effect = [second_401, second_success]
    second = Session(
        base_url="https://example.test", cookies=initial.copy(), csrf="csrf-old", _http=second_http
    )

    assert first.request("GET", "/novel/projects") == {"ok": "first"}
    assert second.request("GET", "/script/projects") == {"ok": "second"}
    assert first_http.post.call_count == 1
    assert second_http.post.call_count == 0
    assert second_http.request.call_args_list[-1].kwargs["cookies"]["sf_refresh"] == "refresh-new"


def test_refresh_reports_lock_timeout_without_refreshing(tmp_path, monkeypatch) -> None:
    import cli_anything.scriptnow.utils.session as session_module

    monkeypatch.setattr(session_module, "_config_path", lambda: tmp_path / "session.json")

    class TimedOutLock:
        def __init__(self, path) -> None:
            del path

        def __enter__(self):
            raise session_module._SessionLockTimeout()

        def __exit__(self, *args) -> None:
            return None

    monkeypatch.setattr(session_module, "_SessionFileLock", TimedOutLock)
    http = Mock()
    http.request.return_value = Mock(status_code=401, cookies=[], headers={})
    session = Session(
        base_url="https://example.test",
        csrf="csrf-token",
        cookies={"sf_refresh": "refresh-token"},
        _http=http,
    )

    with pytest.raises(ScriptNowError, match="登录续期超时"):
        session.request("GET", "/projects")
    assert http.post.call_count == 0


def test_session_lock_uses_windows_msvcrt_when_fcntl_is_unavailable(
    tmp_path, monkeypatch
) -> None:
    import cli_anything.scriptnow.utils.session as session_module

    calls: list[tuple[int, int]] = []

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(_fd: int, mode: int, length: int) -> None:
            calls.append((mode, length))

    monkeypatch.setattr(session_module, "_fcntl", None)
    monkeypatch.setattr(session_module, "_msvcrt", FakeMsvcrt)

    with session_module._SessionFileLock(tmp_path / "session.json", timeout=0.1):
        pass

    assert calls == [(FakeMsvcrt.LK_NBLCK, 1), (FakeMsvcrt.LK_UNLCK, 1)]
    assert (tmp_path / "session.json.refresh.lock").read_bytes() == b"\0"


def test_refresh_leaves_corrupt_session_file_untouched(tmp_path, monkeypatch) -> None:
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    config_path.write_text("{this is not json")
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    http = Mock()
    session = Session(
        base_url="https://example.test",
        csrf="csrf-token",
        cookies={"sf_refresh": "refresh-token"},
        _http=http,
    )

    with pytest.raises(ScriptNowError, match="未覆盖原文件"):
        session._refresh()
    assert config_path.read_text() == "{this is not json"
    assert http.post.call_count == 0


def _read_only_error() -> OSError:
    """The exact errno a sandbox answers with (EROFS, not EACCES) — 2026-09-17."""
    return OSError(errno.EROFS, "Read-only file system")


def test_session_lock_read_only_area_raises_area_error(tmp_path, monkeypatch) -> None:
    """Regression: EROFS creating the refresh lock is a *location* fault.

    dsh's sandbox read-only-binds ``/`` and binds only the agent's workspace
    read-write, so a session kept outside it opens for write with EROFS. The
    lock used to funnel every errno except EPERM/EACCES into
    ``_SessionFileError``, i.e. "the session file is damaged".
    """
    import cli_anything.scriptnow.utils.session as session_module

    monkeypatch.setattr(
        session_module.os,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(_read_only_error()),
    )

    with pytest.raises(session_module._SessionAreaError) as caught:
        session_module._SessionFileLock(tmp_path / "session.json", timeout=0.1).__enter__()

    assert "Read-only file system" in str(caught.value)


def test_refresh_lock_area_fault_never_reads_as_corruption(tmp_path, monkeypatch) -> None:
    """The user-facing half: a lock fault must not say 损坏 nor suggest login.

    Before the fix the same run reported
    "本地登录会话文件损坏或不可读取…请先运行 scriptnow login", so an agent reading
    it went looking for a corrupt file and, failing that, asked the user to hand
    over cookies from devtools.
    """
    import cli_anything.scriptnow.utils.session as session_module

    monkeypatch.setattr(session_module, "_config_path", lambda: tmp_path / "session.json")

    class ReadOnlyLock:
        def __init__(self, path) -> None:
            del path

        def __enter__(self):
            raise session_module._SessionAreaError(
                "无法创建本地登录续期锁（errno=30 Read-only file system）"
            )

        def __exit__(self, *args) -> None:
            return None

    monkeypatch.setattr(session_module, "_SessionFileLock", ReadOnlyLock)
    http = Mock()
    http.request.return_value = Mock(status_code=401, cookies=[], headers={})
    session = Session(
        base_url="https://example.test",
        csrf="csrf-token",
        cookies={"sf_refresh": "refresh-token"},
        _http=http,
    )

    with pytest.raises(ScriptNowError) as caught:
        session.request("GET", "/projects")

    message = str(caught.value)
    assert session_module.AREA_ERROR_MARKER in message
    assert "损坏" not in message
    assert "scriptnow login" not in message and "重新登录" not in message
    # 具体 errno 必须留在文案里：它是「只读文件系统」与「权限不足」的唯一区分。
    assert "Read-only file system" in message
    assert http.post.call_count == 0


def test_load_unreadable_session_path_is_not_reported_as_corruption(tmp_path, monkeypatch) -> None:
    """A session path that exists but cannot be read is a *location* fault.

    Uses a directory at the session path: a real filesystem condition (EISDIR),
    no patching — the point is that the OSError branch, not the content branch,
    answers.
    """
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    config_path.mkdir()
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    monkeypatch.delenv("SCRIPTNOW_HOSTED", raising=False)

    with pytest.raises(ScriptNowError) as caught:
        session_module.load()

    message = str(caught.value)
    assert session_module.AREA_ERROR_MARKER in message
    assert "损坏" not in message


def test_corrupt_session_content_still_reads_as_corruption(tmp_path, monkeypatch) -> None:
    """The other half of the split: bad *content* keeps its own diagnosis."""
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    config_path.write_text("{not json at all")
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    monkeypatch.delenv("SCRIPTNOW_HOSTED", raising=False)

    with pytest.raises(ScriptNowError) as caught:
        session_module.load()

    message = str(caught.value)
    assert "损坏" in message
    assert session_module.AREA_ERROR_MARKER not in message


def test_area_message_is_host_aware_and_never_suggests_logging_in(monkeypatch) -> None:
    import cli_anything.scriptnow.utils.session as session_module

    cause = session_module._SessionAreaError(
        "无法创建本地登录续期锁（errno=30 Read-only file system）"
    )

    monkeypatch.setenv("SCRIPTNOW_HOSTED", "1")
    hosted = session_module._area_message(cause)
    assert session_module.is_area_error_text(hosted)
    assert "稍后重试" in hosted and "宿主" in hosted
    assert "scriptnow login" not in hosted

    monkeypatch.delenv("SCRIPTNOW_HOSTED", raising=False)
    self_managed = session_module._area_message(cause)
    assert session_module.is_area_error_text(self_managed)
    assert "SCRIPTNOW_CLI_CONFIG" in self_managed
    assert "scriptnow login" not in self_managed

    # doctor 会截断到 240 字符，可执行建议必须在截断之内。
    assert len(self_managed) < 240 and len(hosted) < 240


def test_diagnostics_classify_read_only_session_dir_as_environment(monkeypatch) -> None:
    """`doctor --json` 与 errors-v2.jsonl 必须能把环境故障与登录失效分开。

    两者都表现为「未登录」，但修法相反：一个去修会话落点，一个去重新登录。
    判据是 session.py 里那句固定措辞 —— 这里把两处焊死，防止文案漂移。
    """
    from cli_anything.scriptnow.utils import diag
    import cli_anything.scriptnow.utils.session as session_module

    monkeypatch.delenv("SCRIPTNOW_HOSTED", raising=False)
    area_text = session_module._area_message(session_module._SessionAreaError("x"))

    assert diag._error_code(area_text) == "CLI_SESSION_DIR_UNWRITABLE"
    assert diag._error_code(area_text) in diag.ERROR_CODE_ALLOWLIST
    assert diag._phase("CLI_SESSION_DIR_UNWRITABLE") == "environment"
    # 别把相邻的两类吞进来。
    assert diag._error_code("登录状态已失效；请先运行: scriptnow login") == "CLI_AUTH_EXPIRED"
    assert diag._error_code("等待另一条 ScriptNow CLI 命令完成登录续期超时") == "CLI_UNKNOWN"


def test_save_uses_private_atomic_replacement(tmp_path) -> None:
    config_path = tmp_path / "session.json"
    session = Session(
        base_url="https://example.test",
        csrf="csrf-token",
        cookies={"sf_refresh": "refresh-token"},
    )

    session.save(config_path)

    assert json.loads(config_path.read_text())["csrf"] == "csrf-token"
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".session.json.*.tmp"))
def test_gateway_placeholder_header_does_not_fail_contract() -> None:
    """非 API 响应只带 Minimum-CLI-Version（如网关默认 9.0.0）而无 API-Contract
    时，不应误触发合同校验（避免把网关占位头当成真实后端要求）。"""
    response = Mock(
        status_code=200,
        cookies=[],
        headers={"X-ScriptNow-Minimum-CLI-Version": "9.0.0"},  # 无 API-Contract
    )
    http = Mock()
    http.request.return_value = response
    session = Session(base_url="https://example.test", _http=http)

    # 不应抛合同错误；非 JSON 响应按 text 返回（此处为 Mock 的 text）。
    result = session.request("GET", "/projects")
    assert result is not None


def test_api_root_defaults_to_the_standalone_mount(monkeypatch) -> None:
    """不设覆盖时保持历史行为：``<base_url>/api``（独立部署的挂载点）。"""
    monkeypatch.delenv("SCRIPTNOW_API_PREFIX", raising=False)
    session = Session(base_url="https://sn.igeewa.com")
    assert session.api_root == "https://sn.igeewa.com/api"


def test_api_prefix_relocates_the_api_root(monkeypatch) -> None:
    """整合形态下平台被挪到 ``/sn-api``（dsh 独占 ``/api``，网关只保护 ``/api``）。

    这条断言就是本次事故的判据：CLI 必须能被打到 ``/sn-api``，而不是永远
    ``/api`` —— 后者是 dsh 的命名空间，网关会回 ``401 platform login required``，
    而那个 401 与「会话过期」无法区分，于是每 60 分钟就报一次「登录状态已失效」。
    """
    monkeypatch.setenv("SCRIPTNOW_API_PREFIX", "/sn-api/")
    session = Session(base_url="https://sn.igeewa.com")
    # 尾斜杠归一化：否则会拼出 `/sn-api//auth/refresh`。
    assert session.api_root == "https://sn.igeewa.com/sn-api"


def test_api_prefix_of_root_means_no_suffix(monkeypatch) -> None:
    """``/`` = API 就挂在站点根（历史上有过这种部署），拼出空后缀而不是双斜杠。"""
    monkeypatch.setenv("SCRIPTNOW_API_PREFIX", "/")
    session = Session(base_url="https://example.test")
    assert session.api_root == "https://example.test"


@pytest.mark.parametrize(
    "value",
    [
        "sn-api",          # 不是绝对路径
        "//evil.test/api",  # 协议相对 = 开放重定向形状
        "/sn-api/../secret",  # 路径穿越
        "/sn api",         # 空白
        "/sn\\api",        # 反斜杠变体
    ],
)
def test_api_prefix_rejects_a_malformed_value(monkeypatch, value: str) -> None:
    """坏值必须**大声**失败，不能静默回落到 ``/api``。

    静默回落正是本次事故的症状本身：CLI 看起来「只是未登录」，真正的原因（挂载点
    对不上）被藏起来，于是 agent 只能靠猜。这里断言它带出变量名，让人一眼能修。
    """
    monkeypatch.setenv("SCRIPTNOW_API_PREFIX", value)
    session = Session(base_url="https://sn.igeewa.com")
    with pytest.raises(ScriptNowError) as error:
        _ = session.api_root
    assert "SCRIPTNOW_API_PREFIX" in str(error.value)


# ── 网关 401 与平台 401 的区分（2026-09-17 线上事故）──────────────────────────
#
# 两个 401 长得一样、含义相反：网关的登录闸门说「你打错了命名空间」，平台的 401
# 说「这条会话过期了」。修法完全不同（改挂载点 vs 重新登录），而 CLI 是唯一能把
# 它们分开的地方 —— 分开之后，任何第三方 agent 都能靠一个环境变量自救，而不是去
# 猜端点、或者向人要 cookie。


#: 网关闸门 401 的**真实**正文（照抄 `gateway/server.mjs:gateUnauthorizedResponse`）。
#: 它不是随手编的字符串，是外部世界唯一的线索，所以测试用真货 —— 编一个"差不多"的
#: 字符串会让这条契约在两侧悄悄分叉。
_GATE_BODY = (
    "platform login required\n"
    "note: this path belongs to the agent runtime; "
    "the ScriptNow platform API is mounted at /sn-api\n"
    "note: for the CLI, set SCRIPTNOW_API_PREFIX=/sn-api\n"
)


def _gate_401(*, with_header: bool = True) -> Mock:
    """整合网关登录闸门的 401（纯文本 + 标记头，`gateway/session-gate.mjs`）。

    `with_header=False` 模拟**比本 CLI 更老**的网关：那时只能靠正文首行识别。
    """
    headers = {"content-type": "text/plain; charset=utf-8"}
    if with_header:
        headers["x-scriptnow-gate"] = "login-required"
    return Mock(status_code=401, cookies=[], headers=headers, text=_GATE_BODY)


def _platform_401() -> Mock:
    """平台自己的 401：JSON 正文，没有网关标记头。"""
    return Mock(
        status_code=401,
        cookies=[],
        headers={"content-type": "application/json"},
        text='{"detail":"登录状态已失效，请重新登录。"}',
    )


def _hosted_session(config_path, *, cookies=None, csrf="csrf-token") -> Session:
    """A hosted instance's session, persisted so `_refresh` has a `saved_at` to key on."""
    session = Session(
        base_url="https://sn.igeewa.com",
        csrf=csrf,
        cookies=cookies if cookies is not None else {"sf_refresh": "refresh-token"},
    )
    session.save(config_path)
    return session


def test_gate_401_reports_the_mount_point_not_an_expired_session(
    tmp_path, monkeypatch
) -> None:
    """网关闸门的 401 必须说「挂载点不对」，不能说「登录过期」。

    这是给第三方 agent 的承诺：它没有本仓库的上下文，如果拿到「登录状态已失效」，
    就只能去猜端点（2026-09-17 线上事故里，agent 猜到最后请用户从 devtools 复制
    cookie）。所以错误里必须带变量名和两个合法值。
    """
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    monkeypatch.setenv("SCRIPTNOW_HOSTED", "1")
    monkeypatch.setenv("SCRIPTNOW_API_PREFIX", "/api")  # 故意打错：/api 归 dsh

    http = Mock()
    http.request.return_value = _gate_401()
    http.post.return_value = _gate_401()  # refresh 同样被闸门拦住
    session = _hosted_session(config_path)
    session._http = http

    with pytest.raises(ScriptNowError) as error:
        session.request("GET", "/projects")

    message = str(error.value)
    assert "SCRIPTNOW_API_PREFIX" in message, "必须点名那个环境变量"
    assert "/sn-api" in message, "必须给出整合形态的正确值"
    assert "登录状态已失效" not in message, "不能把「打错地方」报成「登录过期」"


def test_gate_401_does_not_mark_the_session_stale(tmp_path, monkeypatch) -> None:
    """打错挂载点不等于会话死了：绝不能留下 stale 标记。

    否则宿主的自愈机制会白换一条会话 —— 每次换发都是一条独立会话，等于按误报的
    频率泄漏会话。
    """
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    monkeypatch.setenv("SCRIPTNOW_HOSTED", "1")

    http = Mock()
    http.request.return_value = _gate_401()
    http.post.return_value = _gate_401()
    session = _hosted_session(config_path)
    session._http = http

    with pytest.raises(ScriptNowError):
        session.request("GET", "/projects")

    assert not (tmp_path / "session.stale.json").exists()


def test_gate_401_is_still_detected_without_the_marker_header(
    tmp_path, monkeypatch
) -> None:
    """老网关没有标记头时靠正文首行兜底。

    否则「CLI 比网关新」的交接期会退化成「登录状态已失效」—— 正是这次事故的形状。
    """
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    monkeypatch.setenv("SCRIPTNOW_HOSTED", "1")

    http = Mock()
    http.request.return_value = _gate_401(with_header=False)
    http.post.return_value = _gate_401(with_header=False)
    session = _hosted_session(config_path)
    session._http = http

    with pytest.raises(ScriptNowError) as error:
        session.request("GET", "/projects")

    message = str(error.value)
    assert "SCRIPTNOW_API_PREFIX" in message
    assert "登录状态已失效" not in message
    assert not (tmp_path / "session.stale.json").exists()


def test_rejected_refresh_leaves_a_stale_marker_for_the_host(
    tmp_path, monkeypatch
) -> None:
    """平台明确拒绝这条 refresh → 留下与当前会话对应的 stale 标记。

    标记是宿主换发会话的唯一信号：`auth.refresh` 是一次性旋转，只有 CLI 能消费
    （它用文件锁串行化并发旋转）；网关自己动手就会撞上「refresh 复用」检测，把
    用户浏览器里的会话一起踢掉。
    """
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    monkeypatch.setenv("SCRIPTNOW_HOSTED", "1")

    http = Mock()
    http.request.return_value = _platform_401()
    http.post.return_value = _platform_401()
    session = _hosted_session(config_path)
    session._http = http
    saved_at = json.loads(config_path.read_text())["saved_at"]

    with pytest.raises(ScriptNowError) as error:
        session.request("GET", "/projects")
    assert "登录状态已失效" in str(error.value)

    marker = json.loads((tmp_path / "session.stale.json").read_text())
    assert marker["saved_at"] == saved_at, "关联键必须是当前会话的 saved_at"
    assert marker["reason"] == "refresh-rejected"
    assert isinstance(marker["detected_at"], int)


@pytest.mark.parametrize("failure", ["network", "server-error"])
def test_a_transient_refresh_failure_does_not_mark_the_session_stale(
    tmp_path, monkeypatch, failure: str
) -> None:
    """网络抖动与 5xx 都不算「平台拒绝」：留标记会白白多造一条会话。

    只有平台**明确回答**了 401/403 才算会话真的没用了。
    """
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    monkeypatch.setenv("SCRIPTNOW_HOSTED", "1")

    http = Mock()
    http.request.return_value = _platform_401()
    if failure == "network":
        http.post.side_effect = requests.RequestException("connection reset")
    else:
        http.post.return_value = Mock(
            status_code=503, cookies=[], headers={}, text="upstream unavailable"
        )
    session = _hosted_session(config_path)
    session._http = http

    with pytest.raises(ScriptNowError):
        session.request("GET", "/projects")

    assert not (tmp_path / "session.stale.json").exists()


def test_a_self_managed_install_never_writes_a_stale_marker(
    tmp_path, monkeypatch
) -> None:
    """自管安装没有宿主可换发，标记只会在磁盘上留垃圾。"""
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    monkeypatch.delenv("SCRIPTNOW_HOSTED", raising=False)

    http = Mock()
    http.request.return_value = _platform_401()
    http.post.return_value = _platform_401()
    session = _hosted_session(config_path)
    session._http = http

    with pytest.raises(ScriptNowError):
        session.request("GET", "/projects")

    assert not (tmp_path / "session.stale.json").exists()


def test_a_marker_carries_the_current_saved_at_so_an_old_one_goes_inert(
    tmp_path, monkeypatch
) -> None:
    """换发之后新会话带新的 ``saved_at``，旧标记自动失效。

    这是标记协议不需要显式清理的原因：宿主只认与当前会话同键的标记。
    """
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    monkeypatch.setenv("SCRIPTNOW_HOSTED", "1")

    # 上一代会话留下的标记。
    (tmp_path / "session.stale.json").write_text(
        json.dumps({"saved_at": 1, "detected_at": 1, "reason": "refresh-rejected"})
    )
    http = Mock()
    http.request.return_value = _platform_401()
    http.post.return_value = _platform_401()
    session = _hosted_session(config_path)
    session._http = http

    with pytest.raises(ScriptNowError):
        session.request("GET", "/projects")

    marker = json.loads((tmp_path / "session.stale.json").read_text())
    assert marker["saved_at"] == json.loads(config_path.read_text())["saved_at"]
    assert marker["saved_at"] != 1, "必须被当前会话的键覆盖"


def test_a_successful_rotation_withdraws_the_stale_marker(tmp_path, monkeypatch) -> None:
    """续期成功 = 会话还活着的正面证据，标记必须撤掉。

    只靠 ``save()`` 抬高 ``saved_at`` 不够：``save()`` 失败是被刻意吞掉的，那时键不
    变、标记继续命中，宿主就会白换一条会话。
    """
    import cli_anything.scriptnow.utils.session as session_module

    config_path = tmp_path / "session.json"
    monkeypatch.setattr(session_module, "_config_path", lambda: config_path)
    monkeypatch.setenv("SCRIPTNOW_HOSTED", "1")

    session = _hosted_session(config_path)
    marker_path = tmp_path / "session.stale.json"
    marker_path.write_text(
        json.dumps(
            {
                "saved_at": json.loads(config_path.read_text())["saved_at"],
                "detected_at": 1,
                "reason": "refresh-rejected",
            }
        )
    )

    http = Mock()
    http.request.side_effect = [
        _platform_401(),
        Mock(status_code=200, cookies=[], headers={}, text="{}"),
    ]
    http.post.return_value = Mock(
        status_code=200,
        cookies=[SimpleNamespace(name="sf_csrf", value="csrf-rotated")],
        headers={},
        text="{}",
    )
    session._http = http

    assert session.request("GET", "/projects") is not None
    assert not marker_path.exists(), "旋转成功后标记必须消失"


