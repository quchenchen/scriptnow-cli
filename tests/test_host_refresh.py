"""宿主代持模式下的续期（W5）：`sf_refresh` 不在实例里，续期要回宿主。

为什么单独测：这条路径的存在理由是"实例里不该有能复活会话的凭据"，所以判据不只是
"能续期成功"，还包括**本地文件里绝不能出现 `sf_refresh`** —— 那才是这个改动本身。
"""

import base64
import json
from unittest.mock import Mock

import pytest

from cli_anything.scriptnow.utils import session as module
from cli_anything.scriptnow.utils.session import Session, instance_secret

SECRET = "instance-secret-value"


def access_token(subject: str = "user-1") -> str:
    """造一个带 `sub` 的假 access token（不需要签名：CLI 只读 claim）。"""
    payload = base64.urlsafe_b64encode(json.dumps({"sub": subject}).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


def hosted_session(tmp_path, monkeypatch, cookies=None):
    """造一个"宿主代持"形态的会话对象（文件里没有 sf_refresh）。

    必须把 `SCRIPTNOW_CLI_CONFIG` 指到临时文件：`_refresh()` 走的是 `_config_path()`，
    而不是调用方手上的路径 —— 这一点踩过一次（测试里保存到 tmp 却去读默认路径，
    于是 `_refresh` 在"文件不存在"上直接返回 False，看起来像功能没生效）。
    """
    path = tmp_path / "session.json"
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(path))
    session = Session(
        base_url="https://platform.test",
        cookies=cookies or {"sf_access": access_token(), "sf_csrf": "csrf-1"},
        csrf="csrf-1",
    )
    session.save(path)
    return session, path


def response(status, payload=None, cookies=None):
    result = Mock(status_code=status)
    result.json.return_value = payload if payload is not None else {}
    result.cookies = cookies or []
    return result


def test_instance_secret_is_read_from_the_environment(monkeypatch):
    monkeypatch.delenv(module.INSTANCE_SECRET_ENV, raising=False)
    assert instance_secret() == ""
    monkeypatch.setenv(module.INSTANCE_SECRET_ENV, "  abc  ")
    assert instance_secret() == "abc"


def test_without_a_secret_the_host_path_is_not_used(monkeypatch, tmp_path):
    """没有密钥 ⇒ 不是宿主代持模式 ⇒ 不偷偷去打一个不存在的端点。"""
    monkeypatch.delenv(module.INSTANCE_SECRET_ENV, raising=False)
    session, _ = hosted_session(tmp_path, monkeypatch)
    session._http = Mock()
    assert session._refresh() is False
    session._http.post.assert_not_called()


def test_renews_through_the_host_and_never_persists_a_refresh(monkeypatch, tmp_path):
    """核心判据：续期成功，且**本地文件里没有 `sf_refresh`**。"""
    monkeypatch.setenv(module.INSTANCE_SECRET_ENV, SECRET)
    session, path = hosted_session(tmp_path, monkeypatch)
    session._http = Mock()
    session._http.post.return_value = response(200, {
        "ok": True,
        "cookies": {"sf_access": access_token(), "sf_csrf": "csrf-2"},
        "csrf": "csrf-2",
    })

    assert session._refresh() is True

    call = session._http.post.call_args
    assert call.args[0] == "https://platform.test/-/agent-session/refresh"
    # 身份用 `<userId>:<secret>`：宿主据此定位"给谁续"，并校验密钥。
    assert call.kwargs["headers"]["x-scriptnow-instance"] == f"user-1:{SECRET}"
    assert session.csrf == "csrf-2"

    saved = json.loads(path.read_text())
    assert sorted(saved["cookies"]) == ["sf_access", "sf_csrf"]
    assert "sf_refresh" not in saved["cookies"]


def test_a_refresh_returned_by_the_host_is_not_written_locally(monkeypatch, tmp_path):
    """宿主本该只回 access+csrf。就算它回了 refresh，也不许落到实例里 —— 那等于 W5 白做。"""
    monkeypatch.setenv(module.INSTANCE_SECRET_ENV, SECRET)
    session, path = hosted_session(tmp_path, monkeypatch)
    session._http = Mock()
    session._http.post.return_value = response(200, {
        "ok": True,
        "cookies": {"sf_access": access_token(), "sf_csrf": "csrf-2", "sf_refresh": "leaked-refresh"},
        "csrf": "csrf-2",
    })

    assert session._refresh() is True

    saved = json.loads(path.read_text())
    assert "sf_refresh" not in saved["cookies"]
    assert "leaked-refresh" not in path.read_text()


@pytest.mark.parametrize("status", [401, 409, 500])
def test_host_failures_report_no_fresh_session(monkeypatch, tmp_path, status):
    """401（密钥不对/被拒）、409（宿主手上没有）、5xx 都不该被当成续期成功。"""
    monkeypatch.setenv(module.INSTANCE_SECRET_ENV, SECRET)
    session, _ = hosted_session(tmp_path, monkeypatch)
    session._http = Mock()
    session._http.post.return_value = response(status, {"ok": False, "error": "x"})
    assert session._refresh() is False


def test_host_failure_does_not_leave_a_stale_marker(monkeypatch, tmp_path):
    """宿主自己做的那次刷新，它自己知道结果 —— CLI 再留标记只会让它白换一条会话。"""
    monkeypatch.setenv(module.INSTANCE_SECRET_ENV, SECRET)
    session, path = hosted_session(tmp_path, monkeypatch)
    session._http = Mock()
    session._http.post.return_value = response(401, {"ok": False, "error": "rejected"})

    assert session._refresh() is False
    assert session._refresh_rejection is None
    assert not (path.with_suffix(".stale.json")).exists()


def test_incomplete_host_answer_is_rejected(monkeypatch, tmp_path):
    """宿主 200 但没给齐 access/csrf：宁可报"这次没换成"，也不要写半套会话下去。"""
    monkeypatch.setenv(module.INSTANCE_SECRET_ENV, SECRET)
    session, _ = hosted_session(tmp_path, monkeypatch)
    session._http = Mock()
    session._http.post.return_value = response(200, {"ok": True, "cookies": {"sf_access": "a"}, "csrf": ""})
    assert session._refresh() is False


def test_platform_path_is_untouched_when_a_refresh_is_present(monkeypatch, tmp_path):
    """反方向：文件里**有** refresh（自助部署/存量）时，仍然走平台那条老路。"""
    monkeypatch.setenv(module.INSTANCE_SECRET_ENV, SECRET)
    session, _ = hosted_session(tmp_path, monkeypatch, cookies={
        "sf_access": access_token(), "sf_refresh": "r-1", "sf_csrf": "csrf-1",
    })
    session._http = Mock()
    rotated = Mock()
    rotated.name, rotated.value = "sf_csrf", "csrf-2"
    session._http.post.return_value = response(200, cookies=[rotated])

    assert session._refresh() is True
    assert session._http.post.call_args.args[0] == "https://platform.test/api/auth/refresh"


def rotated_by_another_process(tmp_path, monkeypatch):
    """在"另一个进程"里把同一份文件换成一条新会话（模拟并发续期）。"""
    other = Session(
        base_url="https://platform.test",
        cookies={"sf_access": access_token(), "sf_csrf": "csrf-2"},
        csrf="csrf-2",
    )
    other.save(tmp_path / "session.json")
    return "csrf-2"


def test_a_rotation_by_another_process_counts_as_usable_in_hosted_mode(monkeypatch, tmp_path):
    """并发下后拿到锁的那条必须认这条新鲜会话 —— 托管形态里它**没有** refresh。

    判据若写成"文件里得有 sf_refresh"（W5 之前两种形态相同，所以恰好等价），托管实例里
    后到者会读到新鲜 access 却回一句「登录状态已失效」：一次**假**失败，且它手上的会话
    其实是好的。用户看到的是"随机地报没登录"，最难查的那一类。
    """
    monkeypatch.setenv(module.INSTANCE_SECRET_ENV, SECRET)
    session, _ = hosted_session(tmp_path, monkeypatch)
    rotated_by_another_process(tmp_path, monkeypatch)
    session._http = Mock()

    assert session._refresh() is True
    # 已经拿到新鲜会话，不该再打一次宿主（每次换发都是一条独立会话）。
    session._http.post.assert_not_called()
    assert session.csrf == "csrf-2"


def test_a_rotation_without_refresh_and_without_a_host_is_not_usable(monkeypatch, tmp_path):
    """反向对照：没有宿主密钥时，缺 refresh 的会话确实不可用（判据不是被放松了）。"""
    monkeypatch.delenv(module.INSTANCE_SECRET_ENV, raising=False)
    session, _ = hosted_session(tmp_path, monkeypatch)
    rotated_by_another_process(tmp_path, monkeypatch)
    session._http = Mock()

    assert session._refresh() is False
    session._http.post.assert_not_called()

