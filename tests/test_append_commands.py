"""Command-level tests for `storymap append-volume` / `append-chapters`.

Covers the CLI contract without touching the network: the session layer is
mocked, and we assert request payloads, error mapping, JSON input shapes and
the `--adopt` second request.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def fake_session(monkeypatch, tmp_path):
    """A fake Session whose .request records calls and returns canned data."""
    session = Mock()
    session.request = Mock(
        side_effect=lambda method, path, **kwargs: (
            {"id": "candidate-1", "status": "active"}
            if "append-propose" in path
            else {"id": "candidate-1", "status": "adopted"}
        )
    )
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda ctx: session)
    return session


def _write(tmp_path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return f"@{path}"


def test_append_volume_object_input_payload(fake_session, runner, tmp_path):
    """对象输入 {"volumes": [...]} → 请求体 volumes 数组原样传递。"""
    file_arg = _write(
        tmp_path,
        "vols.json",
        '{"volumes": [{"id": "volume-2", "ordinal": 1, "title": "第二卷", "chapters": [{"id": "chapter-2-1", "ordinal": 1, "title": "新章", "target_words": 3000, "beats": []}]}]}',
    )
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg])
    assert result.exit_code == 0
    args, kwargs = fake_session.request.call_args
    assert args[1] == "/novel/projects/pid-1/story-map/append-propose"
    body = kwargs["json_body"]
    assert body["volumes"][0]["id"] == "volume-2"
    assert body["volumes"][0]["chapters"][0]["id"] == "chapter-2-1"
    assert kwargs["write"] is True


def test_append_volume_array_input(fake_session, runner, tmp_path):
    """数组输入（顶层即 volumes 数组）同样接受。"""
    file_arg = _write(
        tmp_path,
        "vols.json",
        '[{"id": "volume-3", "ordinal": 1, "title": "第三卷", "chapters": []}]',
    )
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg])
    assert result.exit_code == 0
    body = fake_session.request.call_args.kwargs["json_body"]
    assert body["volumes"][0]["id"] == "volume-3"


def test_append_chapters_requires_volume_id(fake_session, runner, tmp_path):
    file_arg = _write(
        tmp_path,
        "chs.json",
        '[{"id": "chapter-9-1", "ordinal": 1, "title": "新章", "target_words": 3000, "beats": []}]',
    )
    result = runner.invoke(main, ["storymap", "append-chapters", "pid-1", "volume-1", file_arg])
    assert result.exit_code == 0
    args, kwargs = fake_session.request.call_args
    assert args[1] == "/novel/projects/pid-1/story-map/append-propose"
    body = kwargs["json_body"]
    assert body["volume_id"] == "volume-1"
    assert body["chapters"][0]["id"] == "chapter-9-1"


def test_missing_file_is_rejected(fake_session, runner, tmp_path):
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", "@nope.json"])
    assert result.exit_code != 0
    assert "No such file" in result.output or "不存在" in result.output
    fake_session.request.assert_not_called()


def test_invalid_json_is_rejected(fake_session, runner, tmp_path):
    file_arg = _write(tmp_path, "bad.json", "{not json")
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg])
    assert result.exit_code != 0
    assert "JSON" in result.output
    fake_session.request.assert_not_called()


def test_empty_array_is_rejected(fake_session, runner, tmp_path):
    file_arg = _write(tmp_path, "empty.json", "[]")
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg])
    assert result.exit_code != 0
    assert "至少 1 个条目" in result.output
    fake_session.request.assert_not_called()


def test_adopt_flag_issues_second_confirm_request(fake_session, runner, tmp_path):
    file_arg = _write(
        tmp_path,
        "vols.json",
        '[{"id": "volume-4", "ordinal": 1, "title": "第四卷", "chapters": []}]',
    )
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg, "--adopt"])
    assert result.exit_code == 0
    paths = [call.args[1] for call in fake_session.request.call_args_list]
    assert paths == [
        "/novel/projects/pid-1/story-map/append-propose",
        "/novel/projects/pid-1/story-map/candidate-1/adopt?confirm=true",
    ]


def test_backend_conflict_is_mapped_to_error(fake_session, runner, tmp_path, monkeypatch):
    from click import ClickException

    def conflict(method, path, **kwargs):
        raise ClickException("duplicate ids within appended content: chapter-2-1")

    fake_session.request.side_effect = conflict
    file_arg = _write(
        tmp_path,
        "vols.json",
        '[{"id": "volume-5", "ordinal": 1, "title": "第五卷", "chapters": []}]',
    )
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg])
    assert result.exit_code != 0
    assert "duplicate ids" in result.output


def test_version_command_shows_current(runner):
    result = runner.invoke(main, ["version"])
    assert result.exit_code == 0
    assert "0.3." in result.output


def test_version_check_force_reports_latest(runner, monkeypatch):
    import cli_anything.scriptnow.utils.upgrade as upgrade_mod
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(upgrade_mod, "latest_version", lambda: "9.9.9")
    # CLI 模块里 version_cmd 引用的是模块级导入的 latest_version —— 需同步 patch
    monkeypatch.setattr(cli, "latest_version", lambda: "9.9.9")
    result = runner.invoke(main, ["version", "--check"])
    assert result.exit_code == 0
    assert "9.9.9" in result.output


def test_self_upgrade_already_latest(runner, monkeypatch):
    import cli_anything.scriptnow.utils.upgrade as upgrade_mod
    import cli_anything.scriptnow.scriptnow_cli as cli

    current = cli.VERSION
    monkeypatch.setattr(upgrade_mod, "latest_version", lambda: current)
    monkeypatch.setattr(cli, "latest_version", lambda: current)
    result = runner.invoke(main, ["self-upgrade", "--yes"])
    assert result.exit_code == 0
    assert "已是最新" in result.output


def test_self_upgrade_unreachable(runner, monkeypatch):
    import cli_anything.scriptnow.utils.upgrade as upgrade_mod
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(upgrade_mod, "latest_version", lambda: None)
    monkeypatch.setattr(cli, "latest_version", lambda: None)
    result = runner.invoke(main, ["self-upgrade", "--yes"])
    assert result.exit_code == 0
    assert "无法连接" in result.output


def test_skill_craft_assembles_structured_draft_and_requires_confirm():
    """skill craft 人机共建：草案必须结构化分节且提交需人工确认（agent 不可绕过）。"""
    from click.testing import CliRunner

    from cli_anything.scriptnow.scriptnow_cli import (
        _craft_answers_to_draft,
        _sanitize_skill_name,
        _skill_craft_questions,
        main,
    )

    # 1) 草案组装：五个维度 + 正反例，满足平台健壮性门禁
    draft = _craft_answers_to_draft(
        "novel",
        {
            "work": "都市悬疑言情",
            "craft": "每章结尾留钩子；对白短促有力",
            "voice": "短句冷冽",
            "continuity": "不丢已埋伏笔",
            "evaluation": "按张力/连贯/角色主动性自检；不达标拒收重写",
            "examples": "正例用动作替代心理描写；反例连续三句解释性旁白",
        },
    )
    for section in ("一、craft", "二、voice", "三、continuity", "四、evaluation", "五、examples"):
        assert section in draft["instructions"]
    assert "正例" in draft["instructions"] and "反例" in draft["instructions"]

    # 2) 名称 sanitize
    assert _sanitize_skill_name("都市悬疑言情") == "都市悬疑言情"
    assert _sanitize_skill_name("!!") == "my-writing-methodology"

    # 3) 提问清单是编辑语言（无技术术语）
    prompts = " ".join(str(q["prompt"]) for q in _skill_craft_questions())
    assert "craft" not in prompts and "skill" not in prompts

    # 4) 交互流程：默认不确认 → 不发起请求（人必须亲自确认）
    runner = CliRunner()
    inputs = "都市悬疑言情\n钩子\n冷冽\n伏笔\n自检\n正反例\nmy-sop\n说明\nn\n"
    r = runner.invoke(main, ["skill", "craft", "--domain", "novel"], input=inputs)
    assert r.exit_code == 0
    assert "已取消" in r.output


def test_login_password_security_paths():
    """登录密码安全传递：--password-stdin 与环境变量，不明文落历史。"""
    from unittest.mock import Mock

    import pytest
    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli_mod
    from cli_anything.scriptnow.scriptnow_cli import main

    captured: list[str] = []

    def fake_login(base_url: str, email: str, password: str):
        captured.append(password)
        s = Mock()
        s.base_url = base_url
        s.cookies = {"sf_access": "a", "sf_refresh": "r", "sf_csrf": "c"}
        s.csrf = "c"
        s.save = Mock()
        return s

    monkeypatch = pytest.MonkeyPatch()
    # login_cmd 引用的是 scriptnow_cli 模块命名空间的 login 绑定
    monkeypatch.setattr(cli_mod, "login", fake_login)
    monkeypatch.setattr(
        cli_mod,
        "_onboarding_done",
        lambda: True,
    )

    runner = CliRunner()
    # 1) --password-stdin 管道传入
    r = runner.invoke(main, ["login", "--host", "https://x.test", "--email", "a@b.c", "--password-stdin"], input="secret-abc\n")
    assert r.exit_code == 0, r.output
    assert captured and captured[-1] == "secret-abc"

    # 2) 环境变量 SCRIPTNOW_PASSWORD
    import os

    os.environ["SCRIPTNOW_PASSWORD"] = "env-secret"
    r = runner.invoke(main, ["login", "--host", "https://x.test", "--email", "a@b.c"])
    assert r.exit_code == 0, r.output
    assert captured[-1] == "env-secret"
    os.environ.pop("SCRIPTNOW_PASSWORD", None)

    # 3) 都不传 → 交互隐藏输入（getpass）——CliRunner 无 tty，getpass 读 stdin
    r = runner.invoke(main, ["login", "--host", "https://x.test", "--email", "a@b.c"], input="interactive-secret\n")
    assert r.exit_code == 0, r.output
    assert captured[-1] == "interactive-secret"

    # 4) 空密码 → 拒绝
    r = runner.invoke(main, ["login", "--host", "https://x.test", "--email", "a@b.c", "--password-stdin"], input="\n")
    assert r.exit_code != 0
    assert "密码不能为空" in r.output
