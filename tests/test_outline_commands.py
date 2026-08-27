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



def test_chapter_outline_adopt_flag_issues_confirm_request(monkeypatch, tmp_path):
    """chapter outline --adopt 回填后自动采纳，无需复制候选 ID。"""
    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.side_effect = [
        {"id": "cand-outline-1", "status": "active"},  # propose
        {"version": 2, "impact": {"added_units": 0, "removed_units": 0, "retained_units": 30}, "status": "adopted"},  # adopt
    ]
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
    runner = CliRunner()
    result = runner.invoke(main, ["chapter", "outline", "p1", "chapter-1", file_arg, "--adopt", "--json"])
    assert result.exit_code == 0, result.output
    paths = [call.args[1] for call in session.request.call_args_list]
    assert paths[0] == "/novel/projects/p1/chapters/chapter-1/outline/propose"
    assert paths[1] == "/novel/projects/p1/story-map/cand-outline-1/adopt?confirm=true"


def test_storymap_adopt_latest_resolves_active_candidate(monkeypatch):
    """storymap adopt --latest 自动采用最新 active 候选（仍需 --confirm）。"""
    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.side_effect = [
        {"story_map_candidates": [
            {"id": "cand-9", "status": "active"},
            {"id": "cand-8", "status": "adopted"},
        ], "story_map": {"version": 1}},
        {"status": "adopted", "version": 2},
    ]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    runner = CliRunner()
    result = runner.invoke(main, ["storymap", "adopt", "p1", "--latest", "--confirm", "--json"])
    assert result.exit_code == 0, result.output
    paths = [call.args[1] for call in session.request.call_args_list]
    assert "/state" in paths[0]
    assert "cand-9" in paths[1]


def test_chapter_generate_help_lists_preview():
    from click.testing import CliRunner

    runner = CliRunner()
    out = runner.invoke(main, ["chapter", "generate", "--help"]).output
    assert "--preview" in out


def test_storymap_phases_outputs_phase_plan(monkeypatch):
    """storymap phases 只读预览叙事结构推导的阶段计划。"""
    import json as _json

    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {
        "schema_version": "novel-phase-plan.v1",
        "structure_key": "three_act",
        "structure_version": "1",
        "structure_title_zh": "三幕式",
        "allocation_policy": "chapter_span",
        "total_volumes": 1,
        "chapters_per_volume": 12,
        "total_chapters": 12,
        "phases": [
            {"ordinal": 1, "key": "act1", "title_zh": "第一幕·建置", "title_en": "Act I · Setup",
             "purpose": "setup", "chapter_count": 3, "start_chapter": 1, "end_chapter": 3,
             "entry_requirement": "引入主角", "exit_requirement": "入场决定"},
            {"ordinal": 2, "key": "act2", "title_zh": "第二幕·对抗", "title_en": "Act II · Confrontation",
             "purpose": "confrontation", "chapter_count": 6, "start_chapter": 4, "end_chapter": 9,
             "entry_requirement": "", "exit_requirement": ""},
            {"ordinal": 3, "key": "act3", "title_zh": "第三幕·解决", "title_en": "Act III · Resolution",
             "purpose": "resolution", "chapter_count": 3, "start_chapter": 10, "end_chapter": 12,
             "entry_requirement": "", "exit_requirement": "落地"},
        ],
        "plan_digest": "abc123",
    }
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    runner = CliRunner()
    result = runner.invoke(main, ["storymap", "phases", "p1", "--json"])
    assert result.exit_code == 0, result.output
    payload = _json.loads(result.output)
    assert payload["structure_key"] == "three_act"
    assert len(payload["phases"]) == 3
    assert payload["phases"][0]["start_chapter"] == 1

    human = runner.invoke(main, ["storymap", "phases", "p1"])
    assert human.exit_code == 0, human.output
    assert "三幕式" in human.output
    assert "第 1–3 章" in human.output


def test_storymap_append_phase_submits_next_phase(monkeypatch, tmp_path):
    """storymap append-phase 提交下一未完成阶段，带 digest/version/章纲预检。"""
    import json as _json

    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.side_effect = [
        {"story_map": {"version": 1}},  # _novel_state
        {"phases": [
            {"key": "act1", "title_zh": "第一幕·建置", "start_chapter": 1, "end_chapter": 2, "chapter_count": 2},
            {"key": "act2", "title_zh": "第二幕·对抗", "start_chapter": 3, "end_chapter": 4, "chapter_count": 2},
        ], "plan_digest": "dig123"},  # GET phases
        {"id": "cand-phase-1", "status": "active"},  # POST phase-append
    ]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    chapters = [{
        "id": "a1", "ordinal": 1, "title": "A1", "target_words": 1000,
        "outline": {"summary": "s", "active_goal": "g", "conflict": "c", "turn": "t",
                    "state_changes": {"k": "v"}, "anchor_ids": ["thread:letter"]},
    }]
    file_arg = _write(tmp_path, "chs.json", {"chapters": chapters})
    runner = CliRunner()
    result = runner.invoke(main, ["storymap", "append-phase", "p1", "act1", file_arg, "--json"])
    assert result.exit_code == 0, result.output
    paths = [call.args[1] for call in session.request.call_args_list]
    assert paths[-1].endswith("story-map/phase-append-propose")
    body = session.request.call_args_list[-1].kwargs["json_body"]
    assert body["phase_key"] == "act1"
    assert body["plan_digest"] == "dig123"
    assert body["expected_story_map_version"] == 1


def test_script_bible_example_lists_rich_keys():
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main, ["script", "bible-example"])
    assert result.exit_code == 0, result.output
    for key in ("desire", "fear", "weakness", "goal", "inner_need", "secret", "wound"):
        assert key in result.output, key


def test_script_episode_outline_example_lists_fields_and_beat_contrast():
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main, ["script", "episode-outline-example"])
    assert result.exit_code == 0, result.output
    for key in ("logline", "active_goal", "conflict", "turn", "state_changes", "anchor_ids"):
        assert key in result.output, key
    assert "正确示范" in result.output and "错误示范" in result.output


def test_novel_bible_example_lists_rich_keys():
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main, ["chapter", "bible-example"])
    assert result.exit_code == 0, result.output
    for key in ("desire", "fear", "weakness", "goal", "inner_need", "secret", "wound"):
        assert key in result.output, key
