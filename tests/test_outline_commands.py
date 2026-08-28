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


def test_script_episode_outline_check_valid_and_invalid(tmp_path):
    import json as _json

    from click.testing import CliRunner

    ok = _write(tmp_path, "ok.json", {"episode": {
        "id": "e1", "logline": "阿澄把录音机放在柜台按下播放键", "active_goal": "g",
        "conflict": "c", "turn": "t", "state_changes": ["s"], "anchor_ids": ["character:shen-achen"]}})
    r_ok = CliRunner().invoke(main, ["script", "episode-outline-check", ok])
    assert r_ok.exit_code == 0, r_ok.output
    bad = _write(tmp_path, "bad.json", {"episode": {"id": "e2", "title": "缺字段"}})
    r_bad = CliRunner().invoke(main, ["script", "episode-outline-check", bad])
    assert r_bad.exit_code != 0


def test_script_storymap_phases_outputs_plan(monkeypatch):
    import json as _json

    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {
        "structure_key": "three_act", "structure_title_zh": "三幕式", "structure_version": "1",
        "total_chapters": 81, "allocation_policy": "chapter_span",
        "phases": [{"ordinal": 1, "key": "act1", "title_zh": "第一幕·建置", "title_en": "Setup",
                    "purpose": "setup", "chapter_count": 20, "start_chapter": 1, "end_chapter": 20,
                    "entry_requirement": "", "exit_requirement": ""}],
        "plan_digest": "d" * 16,
    }
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, ["script", "storymap-phases", "p1", "--json"])
    assert result.exit_code == 0, result.output
    assert _json.loads(result.output)["structure_key"] == "three_act"


def test_script_storymap_append_phase_submits_next_phase(monkeypatch, tmp_path):
    import json as _json

    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.side_effect = [
        {"story_map": {"version": 1}},  # state
        {"phases": [{"key": "act1", "title_zh": "第一幕·建置", "start_chapter": 1, "end_chapter": 20,
                     "chapter_count": 20}], "plan_digest": "d" * 16},  # phases
        {"id": "cand-1", "status": "active"},  # phase-append
    ]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    episodes = [{"id": f"ep-{i}", "ordinal": i, "title": f"第{i}集",
                 "logline": f"阿澄在第{i}集推进物证查证", "active_goal": "g", "conflict": "c", "turn": "t",
                 "state_changes": ["s"], "anchor_ids": ["character:shen-achen"],
                 "scenes": [{"id": f"s{i}-1", "ordinal": 1, "title": "场", "duration_seconds_target": 45,
                             "beats": [{"id": f"b{i}-1-{k}", "objective": "阿澄把录音机放在柜台按下播放键，店里收音机声戛然而止" if k == 0 else "村医老周的手指在药瓶上停住，说听不出这是谁的声音", "anchor_ids": ["character:shen-achen"]} for k in range(3)]}]}
                for i in range(1, 4)]
    file_arg = _write(tmp_path, "eps.json", {"episodes": episodes})
    result = CliRunner().invoke(main, ["script", "storymap-append-phase", "p1", "act1", file_arg, "--json"])
    assert result.exit_code == 0, result.output
    body = session.request.call_args_list[-1].kwargs["json_body"]
    assert body["phase_key"] == "act1"
    assert body["plan_digest"] == "d" * 16


def test_storymap_structure_save_passes_metadata(monkeypatch, tmp_path):
    import json as _json

    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {
        "key": "serial-saga", "title_zh": "连载体长线", "description": "每卷一个完整事件，全局留长线",
        "applicable_medium": "novel", "phase_count": 3,
    }
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    file_arg = _write(tmp_path, "structure.json", {
        "title_zh": "连载体长线", "title_en": "Serial Saga",
        "phases": [
            {"key": "v1", "title_zh": "第一卷", "purpose": "setup", "ratio": "0.4"},
            {"key": "v2", "title_zh": "第二卷", "purpose": "development", "ratio": "0.4"},
            {"key": "v3", "title_zh": "第三卷", "purpose": "resolution", "ratio": "0.2"},
        ],
    })
    result = CliRunner().invoke(main, [
        "storymap", "structure-save", "serial-saga", file_arg,
        "--description", "每卷一个完整事件，全局留长线", "--medium", "novel", "--json",
    ])
    assert result.exit_code == 0, result.output
    body = session.request.call_args.kwargs["json_body"]
    assert body["key"] == "serial-saga"
    assert body["applicable_medium"] == "novel"
    assert body["description"] == "每卷一个完整事件，全局留长线"
    assert len(body["phases"]) == 3
    assert _json.loads(result.output)["phase_count"] == 3


def test_storymap_structure_save_defaults_medium_from_json(monkeypatch, tmp_path):
    import json as _json

    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {"key": "dual-arc", "phase_count": 2, "applicable_medium": "script"}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    file_arg = _write(tmp_path, "structure.json", {
        "title_zh": "双弧", "applicable_medium": "script",
        "phases": [
            {"key": "a", "title_zh": "线A", "purpose": "setup", "ratio": "0.5"},
            {"key": "b", "title_zh": "线B", "purpose": "resolution", "ratio": "0.5"},
        ],
    })
    result = CliRunner().invoke(main, ["storymap", "structure-save", "dual-arc", file_arg, "--json"])
    assert result.exit_code == 0, result.output
    body = session.request.call_args.kwargs["json_body"]
    assert body["applicable_medium"] == "script"
    assert _json.loads(result.output)["applicable_medium"] == "script"


def test_storymap_structure_save_rejects_bad_medium(monkeypatch, tmp_path):
    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    file_arg = _write(tmp_path, "structure.json", {
        "phases": [{"key": "a", "title_zh": "甲", "ratio": "1"}],
    })
    result = CliRunner().invoke(main, ["storymap", "structure-save", "bad", file_arg, "--medium", "film"])
    assert result.exit_code != 0
    assert "not one of 'novel', 'script', 'both'" in result.output
    assert session.request.call_count == 0


def test_storymap_structures_lists_saved_metadata(monkeypatch):
    import json as _json

    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = [
        {"key": "serial-saga", "title_zh": "连载体长线", "description": "每卷一个完整事件",
         "applicable_medium": "novel", "phase_count": 3},
        {"key": "dual-arc", "title_zh": "双弧", "description": "", "applicable_medium": "both", "phase_count": 2},
    ]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    monkeypatch.setattr(cli, "_api_request", lambda _ctx, _method, _path, **_kw: session.request.return_value)
    result = CliRunner().invoke(main, ["storymap", "structures", "--json"])
    assert result.exit_code == 0, result.output
    payload = _json.loads(result.output)
    assert payload["saved_templates"][0]["applicable_medium"] == "novel"
    assert payload["saved_templates"][0]["description"] == "每卷一个完整事件"
    assert any("适用小说" in s["zh"] for s in payload["structures"])


def _rough_example(total: int = 10, keys: tuple[str, ...] = ("act1", "act2", "act3")) -> dict:
    import json as _json
    # 三阶段：1-4 / 5-7 / 8-10（比例 0.3/0.4/0.3 → 最大余数 4/7/4? 用模板原样即可，这里按给定边界）
    return {
        "structure_key": "three_act",
        "structure_title_zh": "三幕式",
        "total_units": total,
        "phases": [
            {"ordinal": i + 1, "phase_key": key, "phase_title_zh": f"幕{i+1}",
             "range_start": start, "range_end": end, "purpose": "p", "summary": "", "key_beats": [], "anchor_ids": []}
            for i, (key, start, end) in enumerate(zip(keys, (1, 5, 8), (4, 7, 10)))
        ],
    }


def test_script_rough_outline_propose_passes_phases_and_adopts(monkeypatch, tmp_path):
    import json as _json

    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.side_effect = [
        {"id": "ro-cand-1", "status": "active"},
        {"id": "ro-outline-1", "status": "adopted"},
    ]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    monkeypatch.setattr(cli, "_api_request", lambda _ctx, _method, _path, **_kw: _rough_example())
    phases = [
        {"ordinal": i + 1, "phase_key": key, "phase_title_zh": f"幕{i+1}",
         "range_start": start, "range_end": end,
         "summary": "方远志重生后拦下欲跳河的父亲，翻出祖传药典残页，决定承包村后坡地种上等地黄；先用一锅劣等地黄试制九蒸九晒地黄丸，失败后调整蒸晒火候，第二锅成品乌润药香，连夜赶到镇上免费送药给患老胃病的街坊，消息传开后济仁堂周世昌亲自登门收他为徒并签订供药合约。"}
        for i, (key, start, end) in enumerate(zip(("act1", "act2", "act3"), (1, 5, 8), (4, 7, 10)))
    ]
    file_arg = _write(tmp_path, "rough.json", {"phases": phases})
    result = CliRunner().invoke(main, ["script", "rough-outline", "p1", file_arg, "--adopt", "--json"])
    assert result.exit_code == 0, result.output
    body = session.request.call_args_list[0].kwargs["json_body"]
    assert body["phases"][0]["phase_key"] == "act1"
    assert session.request.call_args_list[0].args[1] == "/script/projects/p1/rough-outline/propose"
    assert session.request.call_args_list[1].args[1] == "/script/projects/p1/rough-outline/ro-cand-1/adopt"
    assert _json.loads(result.output)["adopted"] == "adopted"


def test_novel_rough_outline_check_flags_meta_and_range(monkeypatch, tmp_path):
    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    monkeypatch.setattr(cli, "_api_request", lambda _ctx, _method, _path, **_kw: _rough_example())
    bad = {
        "phases": [
            {"ordinal": 1, "phase_key": "act1", "phase_title_zh": "幕1", "range_start": 2, "range_end": 4,
             "summary": "围绕本场目标推进矛盾，为下一场留下钩子。"},
        ]
    }
    file_arg = _write(tmp_path, "bad.json", bad)
    result = CliRunner().invoke(main, ["novel", "rough-outline-check", "p1", file_arg])
    assert result.exit_code != 0
    assert "区间起点应为 1" in result.output
    assert "套话" in result.output
    assert session.request.call_count == 0


def test_script_rough_outline_example_prints_phase_ranges(monkeypatch):
    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    monkeypatch.setattr(cli, "_api_request", lambda _ctx, _method, _path, **_kw: _rough_example(80, ("ki", "sho", "ten", "ketsu")) if "example" in _path else {})
    # 80 集 + 4 阶段（起承转合）：用 1-16/17-40/41-64/65-80 边界
    example = {
        "structure_key": "kishotenketsu", "structure_title_zh": "起承转合", "total_units": 80,
        "phases": [
            {"ordinal": i + 1, "phase_key": key, "phase_title_zh": title, "range_start": start, "range_end": end,
             "purpose": "p", "summary": "", "key_beats": [], "anchor_ids": []}
            for i, (key, title, start, end) in enumerate(
                (("ki", "起·引入", 1, 16), ("sho", "承·发展", 17, 40), ("ten", "转·转折", 41, 64), ("ketsu", "合·收束", 65, 80)))
        ],
    }
    monkeypatch.setattr(cli, "_api_request", lambda _ctx, _method, _path, **_kw: example)
    result = CliRunner().invoke(main, ["script", "rough-outline-example", "p1"])
    assert result.exit_code == 0, result.output
    assert "起承转合" in result.output
    assert "第 65–80 集" in result.output


def test_script_storymap_rebuild_start_and_phase_flow(monkeypatch, tmp_path):
    import json as _json

    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.side_effect = [
        {"id": "rebuild-1", "status": "building", "base_story_map_version": 3,
         "phase_keys": ["act1", "act2", "act3"], "completed_phases": [], "next_phase": "act1"},
        {"id": "rebuild-1", "status": "building", "completed_phases": ["act1"],
         "accumulated_episodes": 3, "next_phase": "act2"},
    ]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    start = CliRunner().invoke(main, ["script", "storymap-rebuild-start", "p1", "--json"])
    assert start.exit_code == 0, start.output
    assert _json.loads(start.output)["phase_keys"] == ["act1", "act2", "act3"]

    episodes = [
        {"id": f"ep-{i}", "ordinal": i, "title": f"第{i}集",
         "logline": f"阿澄在第{i}集推进物证查证", "active_goal": "g", "conflict": "c", "turn": "t",
         "state_changes": ["s"], "anchor_ids": ["character:achen"],
         "scenes": [{"id": f"s{i}-1", "ordinal": 1, "title": "场",
                     "beats": [{"id": f"b{i}-1", "objective": f"阿澄把第{i}条物证放上柜台", "anchor_ids": ["character:achen"]}]}]}
        for i in range(1, 4)
    ]
    file_arg = _write(tmp_path, "phase1.json", {"episodes": episodes})
    result = CliRunner().invoke(main, ["script", "storymap-rebuild-phase", "p1", "act1", file_arg, "--json"])
    assert result.exit_code == 0, result.output
    body = session.request.call_args_list[1].kwargs["json_body"]
    assert body["phase_key"] == "act1"
    assert len(body["episodes"]) == 3
    assert session.request.call_args_list[1].args[1] == "/script/projects/p1/storymap/rebuild-phase"
    assert _json.loads(result.output)["accumulated_episodes"] == 3


def test_script_storymap_rebuild_check_flags_duplicates(monkeypatch, tmp_path):
    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    monkeypatch.setattr(
        cli, "_api_request",
        lambda _ctx, _method, _path, **_kw: {"pass": False, "issues": ["集 ID 重复：ep-1", "集序号应连续"]},
    )
    file_arg = _write(tmp_path, "phase.json", {"episodes": [{"id": "ep-1", "ordinal": 1}]})
    result = CliRunner().invoke(main, ["script", "storymap-rebuild-check", "p1", "act1", file_arg])
    assert result.exit_code != 0
    assert "集 ID 重复" in result.output


def test_script_storymap_rebuild_propose_returns_candidate(monkeypatch):
    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {"id": "cand-rebuild-1", "status": "active"}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, ["script", "storymap-rebuild-propose", "p1", "--json"])
    assert result.exit_code == 0, result.output
    assert session.request.call_args.args[1] == "/script/projects/p1/storymap/rebuild-propose"
