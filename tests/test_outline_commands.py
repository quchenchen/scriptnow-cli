"""Public CLI tests for episode/chapter outline backfill commands."""

from __future__ import annotations

import json
from unittest.mock import Mock

from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main


def _write(tmp_path, name: str, payload: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return f"@{path}"


def test_episode_outline_backfill_uses_server_storymap_version(monkeypatch, tmp_path):
    session = Mock()
    session.request.side_effect = [
        {"story_map": {"version": 7, "episodes": [{"id": "episode-1"}]}},
        {"id": "candidate-episode-1", "status": "active"},
    ]
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    file_arg = _write(tmp_path, "episode.json", {
        "logline": "主角公开证据",
        "active_goal": "夺回药方",
        "conflict": "对手封锁证据",
        "turn": "身份被曝光",
        "state_changes": ["风险从隐蔽变为公开"],
        "anchor_ids": ["event:medicine"],
    })
    result = CliRunner().invoke(main, ["script", "episode-outline", "p1", "episode-1", file_arg, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == "candidate-episode-1"
    method, path = session.request.call_args_list[1].args[:2]
    assert method == "POST"
    assert path == "/script/projects/p1/story-map/episodes/episode-1/outline/propose"
    body = session.request.call_args_list[1].kwargs["json_body"]
    assert body["expected_version"] == 7
    assert body["logline"] == "主角公开证据"


def test_chapter_outline_backfill_accepts_outline_wrapper(monkeypatch, tmp_path):
    session = Mock()
    session.request.return_value = {"id": "candidate-chapter-1", "status": "active"}
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    file_arg = _write(tmp_path, "chapter.json", {
        "outline": {
            "summary": "主角走进旧仓库",
            "active_goal": "找回药方",
            "conflict": "仓库已经封锁",
            "turn": "发现药方被调包",
            "state_changes": {"information": "未知变为已知"},
            "anchor_ids": ["event:medicine"],
        },
    })
    result = CliRunner().invoke(main, ["chapter", "outline", "p1", "chapter-1", file_arg, "--json"])
    assert result.exit_code == 0, result.output
    body = session.request.call_args.kwargs["json_body"]
    assert body["outline"]["summary"] == "主角走进旧仓库"
    assert session.request.call_args.args[1] == "/novel/projects/p1/chapters/chapter-1/outline/propose"


def test_outline_commands_are_listed_in_help():
    runner = CliRunner()
    assert "episode-outline" in runner.invoke(main, ["script", "--help"]).output
    assert "outline" in runner.invoke(main, ["chapter", "--help"]).output


def test_outline_check_valid_and_invalid(tmp_path):
    runner = CliRunner()
    valid = _write(tmp_path, "ok.json", {
        "summary": "主角踏入旧仓库",
        "active_goal": "找回药方",
        "conflict": "仓库被封锁",
        "turn": "药方被调包",
        "state_changes": {"information": "未知变为已知"},
        "anchor_ids": ["event:medicine"],
    })
    r_ok = runner.invoke(main, ["chapter", "outline-check", valid])
    assert r_ok.exit_code == 0
    assert "自查通过" in r_ok.output

    bad = _write(tmp_path, "bad.json", {"summary": "只有概述"})
    r_bad = runner.invoke(main, ["chapter", "outline-check", bad])
    assert r_bad.exit_code != 0
    assert "行动者目标" in r_bad.output


def test_outline_example_lists_fields():
    runner = CliRunner()
    result = runner.invoke(main, ["chapter", "outline-example"])
    assert result.exit_code == 0
    assert "active_goal" in result.output
    assert "anchor_ids" in result.output


def test_outline_check_accepts_beat_anchors(tmp_path):
    """Server parity: empty outline.anchor_ids is OK when beats carry anchors."""
    runner = CliRunner()
    f = _write(tmp_path, "beat.json", {
        "summary": "主角踏入旧仓库",
        "active_goal": "找回药方",
        "conflict": "仓库被封锁",
        "turn": "药方被调包",
        "state_changes": {"information": "未知变为已知"},
        "anchor_ids": [],
        "beats": [{"id": "b1", "objective": "x", "anchor_ids": ["event:medicine"]}],
    })
    r = runner.invoke(main, ["chapter", "outline-check", f])
    assert r.exit_code == 0, r.output


def test_outline_check_json_invalid_exits_1(tmp_path):
    """--json mode must still exit non-zero when the outline is invalid."""
    runner = CliRunner()
    f = _write(tmp_path, "bad.json", {"summary": "只有概述"})
    r = runner.invoke(main, ["chapter", "outline-check", f, "--json"])
    assert r.exit_code == 1
    assert '"valid": false' in r.output or '"valid":false' in r.output


def test_outline_example_no_project_uses_cli_fallback():
    runner = CliRunner()
    result = runner.invoke(main, ["chapter", "outline-example", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["source"] == "cli-fallback"

