"""Command-level tests for `storymap append-volume` / `append-chapters`.

Covers the CLI contract without touching the network: the session layer is
mocked, and we assert request payloads, error mapping, JSON input shapes and
the `--adopt` second request.
"""

from __future__ import annotations

import json
import re
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main


REVIEW_ARGS = ["--review-token", "review-1"]


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


@pytest.mark.parametrize("medium", ["novel", "script"])
def test_project_direction_inspiration_uses_project_medium(monkeypatch, medium):
    session = Mock()

    def request(method, path, **kwargs):
        if method == "GET" and path == "/projects":
            return [{"id": "project-1", "medium": medium, "direction": {}}]
        if method == "POST" and path == "/creative-inspiration":
            assert kwargs["json_body"]["medium"] == medium
            return {
                "title": "方向",
                "premise": "一个完整设想",
                "tone": "克制",
                "world_setting": "城市规则",
                "genre_suggestions": ["悬疑"],
                "model_key": "test-model",
            }
        if method == "PATCH" and path == "/projects/project-1/direction":
            return {"direction": kwargs["json_body"]["direction"]}
        raise AssertionError((method, path))

    session.request = Mock(side_effect=request)
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda ctx: session)
    result = CliRunner().invoke(
        main,
        ["project", "direction", "project-1", "--inspire", "城市每天缩小一米", "--json"],
    )
    assert result.exit_code == 0, result.output


def test_story_core_help_examples_use_concrete_angles():
    novel_help = CliRunner().invoke(main, ["novel", "propose", "--help"]).output
    script_help = CliRunner().invoke(main, ["script", "propose", "--help"]).output
    expected_order = ("主角欲望", "对抗阻力", "情感承诺", "道德困境", "结局代价")
    for output in (novel_help, script_help):
        normalized = "".join(output.split())
        match = re.search(r'"angles":\[(.*?)\]', normalized)
        assert match is not None
        angles = re.findall(r'"([^"]+)"', match.group(1))
        assert len(angles) == 5
        assert all(8 <= len(angle.strip()) <= 60 for angle in angles)
        assert tuple(angle.split("：", 1)[0] for angle in angles) == expected_order


def test_append_volume_object_input_payload(fake_session, runner, tmp_path):
    """对象输入 {"volumes": [...]} → 请求体 volumes 数组原样传递。"""
    file_arg = _write(
        tmp_path,
        "vols.json",
        '{"volumes": [{"id": "volume-2", "ordinal": 1, "title": "第二卷", "chapters": [{"id": "chapter-2-1", "ordinal": 1, "title": "新章", "target_words": 3000, "beats": [], "outline": {"summary": "主角踏入旧仓库", "active_goal": "找回药方", "conflict": "仓库被封锁", "turn": "药方被调包", "state_changes": {"information": "未知变为已知"}, "anchor_ids": ["event:medicine"]}}]}]}',
    )
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg, *REVIEW_ARGS])
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
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg, *REVIEW_ARGS])
    assert result.exit_code == 0
    body = fake_session.request.call_args.kwargs["json_body"]
    assert body["volumes"][0]["id"] == "volume-3"


def test_append_chapters_requires_volume_id(fake_session, runner, tmp_path):
    file_arg = _write(
        tmp_path,
        "chs.json",
        '[{"id": "chapter-9-1", "ordinal": 1, "title": "新章", "target_words": 3000, "beats": [], "outline": {"summary": "主角踏入旧仓库", "active_goal": "找回药方", "conflict": "仓库被封锁", "turn": "药方被调包", "state_changes": {"information": "未知变为已知"}, "anchor_ids": ["event:medicine"]}}]',
    )
    result = runner.invoke(main, ["storymap", "append-chapters", "pid-1", "volume-1", file_arg, *REVIEW_ARGS])
    assert result.exit_code == 0
    args, kwargs = fake_session.request.call_args
    assert args[1] == "/novel/projects/pid-1/story-map/append-propose"
    body = kwargs["json_body"]
    assert body["volume_id"] == "volume-1"
    assert body["chapters"][0]["id"] == "chapter-9-1"


def test_missing_file_is_rejected(fake_session, runner, tmp_path):
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", "@nope.json", *REVIEW_ARGS])
    assert result.exit_code != 0
    assert "No such file" in result.output or "不存在" in result.output
    fake_session.request.assert_not_called()


def test_invalid_json_is_rejected(fake_session, runner, tmp_path):
    file_arg = _write(tmp_path, "bad.json", "{not json")
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg, *REVIEW_ARGS])
    assert result.exit_code != 0
    assert "JSON" in result.output
    fake_session.request.assert_not_called()


def test_empty_array_is_rejected(fake_session, runner, tmp_path):
    file_arg = _write(tmp_path, "empty.json", "[]")
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg, *REVIEW_ARGS])
    assert result.exit_code != 0
    assert "至少 1 个条目" in result.output
    fake_session.request.assert_not_called()


def test_adopt_flag_is_rejected_to_keep_adoption_as_separate_human_decision(fake_session, runner, tmp_path):
    file_arg = _write(
        tmp_path,
        "vols.json",
        '[{"id": "volume-4", "ordinal": 1, "title": "第四卷", "chapters": []}]',
    )
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg, "--adopt", *REVIEW_ARGS])
    assert result.exit_code == 1
    assert "已取消隐式 --adopt" in result.output
    fake_session.request.assert_not_called()


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
    result = runner.invoke(main, ["storymap", "append-volume", "pid-1", file_arg, *REVIEW_ARGS])
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
    monkeypatch.setattr(cli, "is_editable_install", lambda: False)
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

    script_draft = _craft_answers_to_draft(
        "script",
        {
            "work": "都市悬疑短剧",
            "craft": "每场完成一个行动节拍",
            "voice": "冷硬克制",
            "continuity": "人物与道具跨场连续",
            "evaluation": "逐场审读，不达标重写",
            "examples": "例如以动作开场；反例是解释性对白",
        },
    )
    assert "六、script-quality-anchors" in script_draft["instructions"]
    assert "可见、声音可听、演员可表演" in script_draft["instructions"]
    assert "编剧不维护机器字段" in script_draft["instructions"]

    # 2) 名称 sanitize
    assert _sanitize_skill_name("都市悬疑言情").startswith("work-methodology-")
    assert _sanitize_skill_name("!!").startswith("work-methodology-")

    # 3) 提问清单是编辑语言（无技术术语）
    prompts = " ".join(str(q["prompt"]) for q in _skill_craft_questions())
    assert "craft" not in prompts and "skill" not in prompts

    # 4) 交互流程：默认不确认 → 不发起请求（人必须亲自确认）
    runner = CliRunner()
    inputs = "都市悬疑言情\n钩子\n冷冽\n伏笔\n自检\n正反例\nmy-sop\n说明\nn\n"
    r = runner.invoke(main, ["skill", "craft", "--domain", "novel"], input=inputs)
    assert r.exit_code == 0
    assert "已取消" in r.output

    # 5) Agent 模式先返回共创协议，不得用空答案静默创建 Skill
    schema = runner.invoke(main, ["skill", "craft", "--domain", "script", "--json"])
    assert schema.exit_code == 0
    payload = json.loads(schema.output)
    assert payload["status"] == "needs_user_input"
    assert set(payload["answer_schema"]) == {
        "work", "craft", "voice", "continuity", "evaluation", "examples"
    }

    # 6) Agent 回填仍须显式 --confirm，且缺项会在任何网络写入前失败
    incomplete = runner.invoke(
        main,
        ["skill", "craft", "--answers", '{"work":"短剧"}', "--json"],
    )
    assert incomplete.exit_code != 0
    assert "方法论信息不完整" in incomplete.output


def test_skill_craft_agent_flow_preflights_mounts_and_reads_back(monkeypatch):
    """Agent 共创只用一次 answers 回填；pass 后创建、正确挂载并回读。"""
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()

    def request(method, path, **kwargs):
        if path.endswith("/robustness-check"):
            return {"check": {"overall_status": "pass", "maturity_score": 92}}
        if path == "/skills/personal":
            return {"id": "skill-1", "version_id": "version-1", "name": "work-methodology"}
        if method == "PUT":
            return {"ok": True}
        if path == "/projects/project-1/skills":
            return [{"skill_id": "skill-1", "version_id": "version-1"}]
        raise AssertionError((method, path, kwargs))

    session.request.side_effect = request
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    answers = json.dumps(
        {
            "work": "都市悬疑小说，调查者追查账本真相",
            "craft": "第三人称限知；每章以行动推进并在结尾留钩子；对白短促",
            "voice": "冷冽短句，使用物件意象，避免排比和解释性旁白",
            "continuity": "已采纳正文与人物设定不可改；伏笔必须登记并在约定章节回收",
            "evaluation": "按张力、因果、角色主动性、连续性逐项自检；任一不达标即重写",
            "examples": "正例：她把信折了三折，没有抬头；反例：直接说明她很悲伤并连续解释三句",
        },
        ensure_ascii=False,
    )
    result = CliRunner().invoke(
        main,
        [
            "skill", "craft", "--domain", "novel", "--project-id", "project-1",
            "--answers", answers, "--confirm", "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["verified"] is True
    assert session.request.call_args_list[2].args[:2] == (
        "PUT", "/projects/project-1/skills/skill-1"
    )


def test_skill_unmount_requires_confirmation_and_reads_back(monkeypatch):
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()

    def request(method, path, **kwargs):
        if method == "DELETE":
            assert path == "/projects/project-1/skills/skill-1"
            assert kwargs["write"] is True
            return {"project_id": "project-1", "skill_id": "skill-1", "unmounted": True, "verified": True}
        if method == "GET":
            assert path == "/projects/project-1/skills"
            return [{"skill_id": "skill-1", "enabled": False}]
        raise AssertionError((method, path, kwargs))

    session.request.side_effect = request
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    runner = CliRunner()
    blocked = runner.invoke(main, ["skill", "unmount", "project-1", "skill-1", "--json"])
    assert blocked.exit_code != 0
    assert "--confirm" in blocked.output
    assert not session.request.called

    result = runner.invoke(main, ["skill", "unmount", "project-1", "skill-1", "--confirm", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "project_id": "project-1", "skill_id": "skill-1", "unmounted": True, "verified": True,
    }


def test_novel_ready_check_ignores_disabled_skill_mounts(monkeypatch):
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = [{"skill_id": "skill-1", "name": "bad-method", "enabled": False}]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    monkeypatch.setattr(cli, "_resolve_project_id", lambda _ctx, project_id: project_id)
    monkeypatch.setattr(cli, "_novel_state", lambda _session, _pid: {
        "creation_settings": {"chapter_target_words": 1200}, "story_cores": [{"status": "adopted"}],
        "blueprint": {"anchors": []}, "story_map": {"volumes": []},
    })
    monkeypatch.setattr(cli, "_api_request", lambda _ctx, _method, _path, **_kwargs: {"status": "adopted"})

    result = CliRunner().invoke(main, ["novel", "ready-check", "project-1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    skill_check = next(item for item in payload["checks"] if item["item"] == "方法论 Skill")
    assert skill_check["ok"] is False
    assert payload["skills"] == []


def test_guide_focuses_one_creative_decision_and_adapts_script_path():
    runner = CliRunner()

    focused = runner.invoke(
        main, ["guide", "--step", "4", "--medium", "script", "--json"]
    )
    assert focused.exit_code == 0, focused.output
    payload = json.loads(focused.output)
    assert payload["mode"] == "focused-step"
    assert payload["medium"] == "script"
    assert payload["step"]["step"] == 4
    assert len(payload["step"]["lenses"]) == 3
    assert "script outline" in payload["step"]["command"]
    assert payload["step"]["next_step"]["step"] == 5
    assert "一次只处理一个决定" in payload["step"]["interaction"]["decision"]

    script_map = runner.invoke(main, ["guide", "--steps", "--medium", "script", "--json"])
    assert script_map.exit_code == 0
    map_payload = json.loads(script_map.output)
    assert "script outline" in map_payload["steps"][3]["command"]
    assert "episode-outline" in map_payload["steps"][6]["command"]
    assert "scene quality" in map_payload["steps"][9]["command"]

    # 人类默认入口只展示第一幕，不再输出十二步命令墙。
    human = runner.invoke(main, ["guide", "--medium", "novel"])
    assert human.exit_code == 0, human.output
    assert "第 1 幕 / 12" in human.output
    assert "现在只想一件事" in human.output
    assert "Step 12" not in human.output

    # Agent 无 step 的 --json 仍保留完整机器可读地图，兼容旧调用。
    full = runner.invoke(main, ["guide", "--json"])
    assert full.exit_code == 0
    assert len(json.loads(full.output)["next"]["steps"]) == 12


def test_guide_pulse_preserves_useful_detours_and_softly_returns_from_drift():
    runner = CliRunner()
    useful = json.dumps(
        {
            "rounds_without_progress": 4,
            "decision_advanced": False,
            "captured_material": ["父亲的录音可以成为中段伏笔"],
            "unresolved": ["女主继续调查的代价"],
            "conflicts": [],
            "next_stage_requested": False,
        },
        ensure_ascii=False,
    )
    result = runner.invoke(
        main,
        ["guide", "--step", "4", "--medium", "novel", "--pulse", useful, "--json"],
    )
    assert result.exit_code == 0, result.output
    pulse = json.loads(result.output)["pulse"]
    assert pulse["status"] == "useful_detour"
    assert pulse["should_invite_return"] is False
    assert pulse["captured_material"] == ["父亲的录音可以成为中段伏笔"]

    drifting = json.dumps(
        {
            "rounds_without_progress": 4,
            "decision_advanced": False,
            "captured_material": [],
            "unresolved": ["女主继续调查的代价"],
        },
        ensure_ascii=False,
    )
    result = runner.invoke(
        main,
        ["guide", "--step", "4", "--medium", "novel", "--pulse", drifting, "--json"],
    )
    payload = json.loads(result.output)
    assert payload["pulse"]["status"] == "drifting"
    assert payload["pulse"]["should_invite_return"] is True
    assert payload["resuming"] is True
    assert "强制进入下一步" in payload["step"]["recovery"]["must_not"]

    missing_step = runner.invoke(main, ["guide", "--resume", "--json"])
    assert missing_step.exit_code != 0
    assert "需要同时指定 --step" in missing_step.output


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


def test_self_upgrade_uses_codeload_and_falls_back_to_git():
    """self-upgrade：主路径 codeload tar.gz 直装（无 git 依赖）；失败回退 git+https。"""
    import subprocess

    import pytest

    from cli_anything.scriptnow.utils import upgrade as up_mod

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        from types import SimpleNamespace

        return SimpleNamespace(returncode=0, stderr="", stdout="")

    mp = pytest.MonkeyPatch()
    mp.setattr(subprocess, "run", fake_run)
    mp.setattr(up_mod, "_install_command", lambda: ("pip", ["install", "https://codeload.github.com/x", "--force-reinstall"]))
    mp.setattr(up_mod, "latest_version", lambda: None)
    mp.setattr(up_mod, "is_editable_install", lambda: False)

    assert up_mod.upgrade(quiet=True) is True
    assert len(calls) == 1
    assert "codeload" in " ".join(calls[0])

    # 主路径失败 → 回退 git+https（fallback 成功）
    def fake_run_mixed(cmd, **kwargs):
        calls.append(list(cmd))
        from types import SimpleNamespace

        # 第一次（主路径）失败，第二次（fallback）成功
        if "codeload" in " ".join(cmd):
            return SimpleNamespace(returncode=1, stderr="boom", stdout="")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    mp2 = pytest.MonkeyPatch()
    mp2.setattr(subprocess, "run", fake_run_mixed)
    mp2.setattr(up_mod, "_install_command", lambda: ("pip", ["install", "https://codeload.github.com/x"]))
    mp2.setattr(up_mod, "_upgrade_fallback", lambda: ["pip", "install", "git+https://x"])
    mp2.setattr(up_mod, "latest_version", lambda: None)
    mp2.setattr(up_mod, "is_editable_install", lambda: False)
    calls.clear()
    assert up_mod.upgrade(quiet=True) is True
    assert len(calls) == 2
    assert "git+https://x" in calls[1]


def test_doctor_reports_session_location_and_login_state():
    """doctor：输出 CLI 版本、会话路径、登录状态与账号；未登录也不崩溃。"""
    import pytest
    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli_mod
    from cli_anything.scriptnow.scriptnow_cli import main

    runner = CliRunner()
    # 1) 未登录（无会话文件时 _session 抛错，doctor 应捕获并报告未登录）
    import cli_anything.scriptnow.utils.session as sess_mod

    mp = pytest.MonkeyPatch()
    mp.setattr(
        sess_mod,
        "_config_path",
        lambda: __import__("pathlib").Path("/tmp/.sn-doctor-nonexistent/session.json"),
    )
    r = runner.invoke(main, ["doctor"])
    assert r.exit_code == 0, r.output
    assert "会话文件不存在" in r.output or "未登录" in r.output

    # 2) 已登录路径：fake session 报告账号
    from unittest.mock import Mock

    fake = Mock()
    fake.base_url = "https://sn.test"
    fake.request = Mock(return_value={"user_id": "u1", "email": "a@b.c"})
    mp.setattr(cli_mod, "_session", lambda ctx: fake)
    r2 = runner.invoke(main, ["doctor"])
    assert r2.exit_code == 0, r2.output
    assert "a@b.c" in r2.output
    assert "u1" in r2.output
    assert ".config" in r2.output or "session.json" in r2.output


def test_diag_sanitizes_secrets_and_detail(monkeypatch, tmp_path):
    """v2 默认关闭，启用后仍不落参数、详情、路径或内容。"""
    from cli_anything.scriptnow.utils import diag

    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "session.json"))

    assert diag.record_error(
        command="chapter adopt /private/work/p1",
        args=("--password", "hunter2", "正文内容"),
        detail="token=supersecret HTTP 409 /private/work/p1",
    ) == "CLI_UNKNOWN"
    assert diag.recent_errors() == []
    diag.enable_diagnostics(1)
    diag.record_error(
        command="chapter adopt",
        args=("--password", "hunter2", "正文内容"),
        detail="HTTP 409: token=supersecret /private/work/p1",
    )
    events = diag.recent_errors()
    assert events == [
        {
            "ts": events[0]["ts"],
            "command_key": "chapter.adopt",
            "error_code": "CLI_HTTP_409",
            "phase": "platform",
        }
    ]
    serialized = __import__("json").dumps(events, ensure_ascii=False)
    for forbidden in ("args", "detail", "note", "path", "hunter2", "正文", "supersecret"):
        assert forbidden not in serialized
    enabled_until = diag.diagnostics_enabled_until()
    assert enabled_until is not None
    monkeypatch.setattr(diag.time, "time", lambda: enabled_until + 1)
    assert diag.diagnostics_enabled_until() is None
    assert not diag._state_path().exists()
    assert not diag._errors_path().exists()


def test_feedback_requires_confirmation_and_sends_only_v2_events(
    runner, monkeypatch, tmp_path
):
    from cli_anything.scriptnow import scriptnow_cli as cli_mod
    from cli_anything.scriptnow.utils import diag

    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "session.json"))
    diag.enable_diagnostics(1)
    diag.record_error(
        command="chapter generate",
        args=("secret-project-id", "正文"),
        detail="HTTP 409: private detail",
    )
    fake = Mock()
    fake.request = Mock(return_value={"received": True, "bundle_id": "bundle-1"})
    monkeypatch.setattr(cli_mod, "_session", lambda _ctx: fake)

    cancelled = runner.invoke(main, ["feedback", "--send"], input="n\n")
    assert cancelled.exit_code != 0
    fake.request.assert_not_called()

    sent = runner.invoke(main, ["feedback", "--send", "--yes", "--json"])
    assert sent.exit_code == 0, sent.output
    body = fake.request.call_args.kwargs["json_body"]
    assert body["schema_version"] == "2"
    assert set(body) == {"schema_version", "cli_version", "events"}
    assert set(body["events"][0]) == {"ts", "command_key", "error_code", "phase"}
    assert "secret-project-id" not in json.dumps(body)
    assert "private detail" not in json.dumps(body)
    guide = runner.invoke(main, ["agent-guide", "--json"])
    assert guide.exit_code == 0
    assert any(
        "不得自行执行 doctor --enable-diagnostics" in rule
        for rule in json.loads(guide.output)["rules"]
    )
