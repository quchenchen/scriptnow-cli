import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
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
