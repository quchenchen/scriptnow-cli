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


def test_synopsis_outline_cli_does_not_impose_a_hard_length_ceiling(monkeypatch):
    session = Mock()
    session.request.return_value = {"id": "outline-1", "version": 1, "status": "active"}
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    runner = CliRunner()
    for medium in ("novel", "script"):
        accepted = runner.invoke(
            main,
            [medium, "outline", "p1", "--text", "故" * 1_001,
            "--review-token", "review-1", "--json"],
        )
        assert accepted.exit_code == 0, (medium, accepted.output)
        assert session.request.call_args.kwargs["json_body"]["content"] == "故" * 1_001


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
    result = CliRunner().invoke(main, [
        "script", "episode-outline", "p1", "episode-1", file_arg,
        "--review-token", "review-1", "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == "candidate-episode-1"
    method, path = session.request.call_args_list[1].args[:2]
    assert method == "POST"
    assert path == "/script/projects/p1/story-map/episodes/episode-1/outline/propose"
    body = session.request.call_args_list[1].kwargs["json_body"]
    assert body["expected_version"] == 7
    assert body["logline"] == "主角公开证据"


def test_dsh_episode_outline_uses_scoped_write_grant_and_stable_request(monkeypatch, tmp_path):
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.delenv("SCRIPTNOW_CREATIVE_ATTEMPT", raising=False)
    session = Mock()
    session.request.side_effect = [
        {"story_map": {"version": 7}}, {"id": "candidate-1", "status": "active"},
        {"story_map": {"version": 7}}, {"id": "candidate-1", "status": "active"},
    ]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    file_arg = _write(tmp_path, "episode-dsh.json", {
        "summary": "她打开档案柜找到录音带，最终公开证据并失去盟友。",
        "anchor_ids": ["event:tape"],
    })
    args = [
        "script", "episode-outline", "p1", "episode-1", file_arg,
        "--execution-token", "ea1.attempt-1.sig", "--json",
    ]
    first = CliRunner().invoke(main, args)
    second = CliRunner().invoke(main, args)
    assert first.exit_code == second.exit_code == 0, first.output + second.output
    writes = [call for call in session.request.call_args_list if call.args[0] == "POST"]
    assert writes[0].kwargs["json_body"]["idempotency_key"] == writes[1].kwargs["json_body"]["idempotency_key"]
    assert writes[0].kwargs["json_body"]["source"] == "agent"
    assert writes[0].kwargs["headers"] == {"X-Creative-Attempt": "ea1.attempt-1.sig"}


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
    result = CliRunner().invoke(main, [
        "chapter", "outline", "p1", "chapter-1", file_arg,
        "--review-token", "review-1", "--json",
    ])
    assert result.exit_code == 0, result.output
    body = session.request.call_args.kwargs["json_body"]
    assert body["outline"]["summary"] == "主角走进旧仓库"


def test_dsh_chapter_outline_saves_candidate_without_submit_review(monkeypatch, tmp_path):
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.delenv("SCRIPTNOW_CREATIVE_ATTEMPT", raising=False)
    session = Mock()
    session.request.return_value = {"id": "candidate-1", "status": "active"}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    file_arg = _write(tmp_path, "chapter-dsh.json", {
        "summary": "她进入旧仓库，找到失踪者留下的录音带，并决定公开证据。",
        "anchor_ids": ["plot:tape"],
    })
    result = CliRunner().invoke(main, [
        "chapter", "outline", "p1", "chapter-1", file_arg,
        "--execution-token", "ea1.attempt-1.sig", "--json",
    ])
    assert result.exit_code == 0, result.output
    call = session.request.call_args
    assert call.args == ("POST", "/novel/projects/p1/chapters/chapter-1/outline/propose")
    assert call.kwargs["headers"] == {"X-Creative-Attempt": "ea1.attempt-1.sig"}
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

    bad = _write(tmp_path, "bad.json", {"anchor_ids": ["event:medicine"]})
    r_bad = runner.invoke(main, ["chapter", "outline-check", bad])
    assert r_bad.exit_code != 0
    assert "行动者目标" in r_bad.output


def test_outline_check_accepts_narrative_only(tmp_path):
    """叙事式章纲（无任何分栏字段）必须能通过 CLI 预检。

    体例拍板（2026-09-19）：一段整段叙事本身就是合格形态。此前
    「只有 summary」会被判不合格 —— 那是把作者逼进分栏的旧契约。
    """
    runner = CliRunner()
    f = _write(tmp_path, "narrative.json", {
        "summary": "主角为拿回药方踏入被封锁的旧仓库，对手设伏，他抢到的是被调包的药方。",
        "anchor_ids": ["event:medicine"],
    })
    r = runner.invoke(main, ["chapter", "outline-check", f])
    assert r.exit_code == 0, r.output
    # state_changes 不再参与门禁，缺了不该出现在缺失项里。
    assert "state_changes" not in r.output


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
    f = _write(tmp_path, "bad.json", {"anchor_ids": ["event:medicine"]})
    r = runner.invoke(main, ["chapter", "outline-check", f, "--json"])
    assert r.exit_code == 1
    assert '"valid": false' in r.output or '"valid":false' in r.output


def test_outline_example_no_project_uses_cli_fallback():
    runner = CliRunner()
    result = runner.invoke(main, ["chapter", "outline-example", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["source"] == "cli-fallback"



def test_chapter_outline_adopt_flag_is_rejected(monkeypatch, tmp_path):
    """章纲提交与采纳必须是两次可见的人类决定。"""
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
    result = runner.invoke(main, [
        "chapter", "outline", "p1", "chapter-1", file_arg, "--adopt",
        "--review-token", "review-1", "--json",
    ])
    assert result.exit_code == 1
    assert "已取消隐式 --adopt" in result.output
    session.request.assert_not_called()


def test_storymap_adopt_latest_resolves_active_candidate(monkeypatch):
    """storymap adopt --latest 自动采用最新 active 候选（仍需 --confirm）。"""
    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.side_effect = [
        # 第一次 /state：--latest 解析 active 候选
        {
            "story_map_candidates": [
                {"id": "cand-9", "status": "active"},
                {"id": "cand-8", "status": "adopted"},
            ],
            "story_map": {"version": 1},
        },
        # 第二次 /state：采纳前影响面核对（将移除/新增/保留单元）
        {
            "story_map_candidates": [
                {
                    "id": "cand-9",
                    "status": "active",
                    "impact": {"added_units": 1, "removed_units": 0, "retained_units": 5},
                },
                {"id": "cand-8", "status": "adopted"},
            ],
            "story_map": {"version": 1},
        },
        {"status": "adopted", "version": 2},
    ]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    runner = CliRunner()
    result = runner.invoke(main, [
        "storymap", "adopt", "p1", "--latest", "--confirm",
        "--review-token", "review-1", "--json",
    ])
    assert result.exit_code == 0, result.output
    paths = [call.args[1] for call in session.request.call_args_list]
    assert paths[0].endswith("/state")  # --latest 解析
    assert paths[1].endswith("/state")  # 影响面核对
    assert "cand-9" in paths[2]  # 第三次请求才是 adopt POST
    assert session.request.call_args_list[2].kwargs["headers"] == {"X-Review-Token": "review-1"}


def test_chapter_generate_help_lists_preview():
    from click.testing import CliRunner

    runner = CliRunner()
    out = runner.invoke(main, ["chapter", "generate", "--help"]).output
    assert "--preview" in out


def test_storymap_phases_outputs_phase_plan(monkeypatch):
    """storymap phases 只读预览叙事结构推导的阶段计划。"""
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
    payload = json.loads(result.output)
    assert payload["structure_key"] == "three_act"
    assert len(payload["phases"]) == 3
    assert payload["phases"][0]["start_chapter"] == 1

    human = runner.invoke(main, ["storymap", "phases", "p1"])
    assert human.exit_code == 0, human.output
    assert "三幕式" in human.output
    assert "第 1–3 章" in human.output


def test_storymap_append_phase_submits_next_phase(monkeypatch, tmp_path):
    """storymap append-phase 提交下一未完成阶段，带 digest/version/章纲预检。"""

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
    result = runner.invoke(main, [
        "storymap", "append-phase", "p1", "act1", file_arg,
        "--review-token", "review-1", "--json",
    ])
    assert result.exit_code == 0, result.output
    paths = [call.args[1] for call in session.request.call_args_list]
    assert paths[-1].endswith("story-map/phase-append-propose")
    body = session.request.call_args_list[-1].kwargs["json_body"]
    assert body["phase_key"] == "act1"
    assert body["plan_digest"] == "dig123"
    assert body["expected_story_map_version"] == 1


def _cli_text(result) -> str:
    """stdout + stderr 合并 —— 示范里的「可选说明」走 stderr（``err=True``）。"""
    return result.output + (getattr(result, "stderr", "") or "")


def test_script_bible_example_shows_narrative_and_optional_legacy_keys():
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main, ["script", "bible-example"])
    assert result.exit_code == 0, result.output
    text = _cli_text(result)
    # 主路：一段整段叙事。
    assert "summary" in text
    assert "整段叙事" in text
    # 存量分栏键仍合法，但示范只把它们当**可选**说明，不再逐键要求。
    for key in ("desire", "fear", "weakness", "goal", "inner_need"):
        assert key in text, key
    assert "不是必填" in text


def test_script_episode_outline_example_leads_with_narrative():
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main, ["script", "episode-outline-example"])
    assert result.exit_code == 0, result.output
    text = _cli_text(result)
    # 叙事是主路，anchor_ids 是机器索引 —— 两者都在示范里。
    assert "summary" in text
    assert "anchor_ids" in text
    # 「两形任一」的口径必须出现在示范里，否则读者会以为分栏被禁了。
    assert "两形任一即可" in text
    assert "正确示范" in text and "错误示范" in text


def test_novel_bible_example_shows_narrative_and_optional_legacy_keys():
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main, ["chapter", "bible-example"])
    assert result.exit_code == 0, result.output
    text = _cli_text(result)
    assert "summary" in text
    for key in ("desire", "fear", "weakness", "goal", "inner_need"):
        assert key in text, key
    assert "不是必填" in text


def test_script_episode_outline_check_valid_and_invalid(tmp_path):

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
    result = CliRunner().invoke(main, [
        "script", "storymap-append-phase", "p1", "act1", file_arg,
        "--review-token", "review-1", "--json",
    ])
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
    # 三阶段：1-4 / 5-7 / 8-10（比例 0.3/0.4/0.3 → 最大余数 4/7/4? 用模板原样即可，这里按给定边界）
    phases = [
        {"ordinal": i + 1, "phase_key": key, "phase_title_zh": f"幕{i+1}",
         "range_start": start, "range_end": end, "purpose": "p", "summary": "", "key_beats": [], "anchor_ids": []}
        for i, (key, start, end) in enumerate(zip(keys, (1, 5, 8), (4, 7, 10)))
    ]
    return {
        "structure_key": "three_act",
        "structure_title_zh": "三幕式",
        "total_units": total,
        "agent_guidance": {"purpose": "完整讲述阶段剧情"},
        "phase_requirements": [
            {"phase_key": phase["phase_key"], "recommended_min_chars": 800, "recommended_min_events": 8}
            for phase in phases
        ],
        "phases": phases,
    }


def test_script_rough_outline_rejects_implicit_adoption(monkeypatch, tmp_path):
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
         "summary": (
             "方远志拦下欲跳河的父亲并承诺三天还债，随后翻出祖传药典残页寻找翻身办法。"
             "他发现家中劣等地黄无法入药，转而说服李福贵承包村后坡地并引山泉灌溉。"
             "黄麻子派马六要求方家只能低价交货，方远志没有动手，而是记下药行掺假的证据。"
             "第一锅地黄丸因火候失控失败，他逐项记录温度湿度并重新安排九蒸九晒顺序。"
             "第二锅成品乌润药香，他免费送给患老胃病和老寒腿的街坊试用，建立第一批口碑。"
             "病人好转后主动传播消息，刘二婶从嘲讽转为替方家说话，镇上舆论开始改变。"
             "济仁堂周世昌登门验药，确认药效后提出收徒并签长期供药合约。"
             "黄麻子发现方远志绕开收购渠道，先砸药摊，再向坡地撒除草剂毁掉大半新苗。"
             "方远志封存被污染的土样、假药样本和街坊证言，准备向县药材公司举报。"
             "父亲从劝他忍让转为主动守地，其他药农也开始讨论联合起来拒绝压价。"
             "周晓梅替他保管供货合约，避免一次打砸让全部经营证据消失。"
             "方远志拜访受害药农，逐户记录被压价和被迫借贷的时间、金额与见证人。"
             "马六再次上门威胁时，村民第一次没有散开，而是站在方家院门口共同作证。"
             "陈国栋收到举报材料后答应初步检测，但要求方远志补齐可以追溯来源的实物样本。"
             "阶段结束时，方远志获得济仁堂和部分药农支持，也正式成为黄麻子的打击目标。"
             "下一阶段必须在保住药田、合作关系和家人安全的同时，取得能够立案的完整物证。"
         ) * 2}
        for i, (key, start, end) in enumerate(zip(("act1", "act2", "act3"), (1, 5, 8), (4, 7, 10)))
    ]
    file_arg = _write(tmp_path, "rough.json", {"phases": phases})
    result = CliRunner().invoke(main, [
        "script", "rough-outline", "p1", file_arg, "--adopt",
        "--review-token", "review-1", "--json",
    ])
    assert result.exit_code == 1
    assert "已取消隐式 --adopt" in result.output
    session.request.assert_not_called()


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


def test_script_rough_outline_progress_shows_current_and_total_phase(monkeypatch):
    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {
        "current_phase_ordinal": 2,
        "current_phase_key": "sho",
        "total_phases": 4,
        "completed_phases": ["ki"],
    }
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, ["script", "rough-outline-progress", "p1"])
    assert result.exit_code == 0, result.output
    assert "阶段 2 / 共 4 阶段" in result.output
    assert "sho" in result.output
    assert "ki" in result.output


def test_single_phase_preflight_uses_progress_boundary_and_dynamic_density():
    from cli_anything.scriptnow.scriptnow_cli import _rough_outline_phase_issues

    summary = "阿澄拆开同盟的利益差异，让证人公开选择并承担代价。" * 45
    phase = {
        "ordinal": 4,
        "phase_key": "alliance_cracks",
        "phase_title_zh": "同盟裂解",
        "range_start": 22,
        "range_end": 30,
        "summary": summary,
        # 每阶段 ≥1 关键转折点是**结构规范**（平台硬拒，CLI 同判据）：
        # 缺了它粗纲就不成其为粗纲。这个用例原本给的是空数组。
        "key_beats": [{"title": "录音曝光", "description": "阿澄把录音放给老周听，老周没有否认"}],
    }
    example = {
        "total_units": 80,
        "phases": [
            {"ordinal": index, "phase_key": key}
            for index, key in enumerate(
                ("return_probe", "voices_identified", "ship_ledger", "alliance_cracks",
                 "reach_yichuan", "false_timeline", "wreck_truth", "revenge_or_rescue",
                 "rescue_testimony", "public_aftermath"),
                start=1,
            )
        ],
    }
    progress = {
        "current_phase_key": "alliance_cracks",
        "phases": [{"range_end": 6}, {"range_end": 13}, {"range_end": 21}],
    }
    assert _rough_outline_phase_issues(phase, example, progress) == []
    assert "第 22 集" in _rough_outline_phase_issues(
        {**phase, "range_start": 23}, example, progress
    )[0]
    final_phase = {
        **phase,
        "ordinal": 10,
        "phase_key": "public_aftermath",
        "range_start": 72,
        "range_end": 79,
    }
    final_progress = {
        "current_phase_key": "public_aftermath",
        "phases": [{"range_end": value} for value in (6, 13, 21, 30, 38, 46, 55, 62, 71)],
    }
    assert any(
        "最后阶段必须覆盖到第 80 集" in issue
        for issue in _rough_outline_phase_issues(final_phase, example, final_progress)
    )
    # 缺 key_beats 是**阻断**，不是建议：粗纲前检里只有套话才带 [建议] 前缀。
    without_beats = {**phase, "key_beats": []}
    blocking = _rough_outline_phase_issues(without_beats, example, progress)
    assert any("key_beats" in issue for issue in blocking), blocking
    assert not any(
        issue.startswith("[建议] ") for issue in blocking if "key_beats" in issue
    ), blocking
    # ⚠ 隔离链（Script 的长篇分批回填）与平铺提交**不是同一把尺子**：它的
    # phase_key 是**进度游标**，必须来自叙事结构模板 —— 这是机器索引要求，
    # 不是体例要求。作者自定的阶段颗粒度走的是平铺路径
    # （`_rough_outline_issues`：只看结构规范，与模板划分不同只给 [建议]）。
    assert _rough_outline_phase_issues(
        {**phase, "phase_key": "author_named_phase"}, example, progress
    ) == ["阶段 author_named_phase 不属于当前叙事结构"]


def test_flat_rough_outline_allows_author_chosen_granularity():
    """平铺提交：作者自定阶段颗粒度（1-5 集 / 1-10 集一段）只给建议、不阻断。

    体例拍板（2026-09-19）。此前 CLI 拿「摘要句子数」去比 `max(8, 区间长度)` ——
    单位就抄错了，且它让「1-10 集颗粒度」根本做不出来。硬拒只剩**结构规范**。
    """
    from cli_anything.scriptnow.scriptnow_cli import (
        _rough_outline_issues,
        rough_outline_advisory_issues,
        rough_outline_blocking_issues,
    )

    example = {
        "total_units": 20,
        "phases": [  # 结构给出的**建议**划分（两个阶段）
            {"ordinal": 1, "phase_key": "template_a", "range_start": 1, "range_end": 15},
            {"ordinal": 2, "phase_key": "template_b", "range_start": 16, "range_end": 20},
        ],
    }
    phases = [  # 作者按自己的颗粒度分：1-5 集一段 + 6-20 集一段
        {
            "ordinal": 1, "phase_key": "author_first_five",
            "range_start": 1, "range_end": 5,
            "summary": "阿澄从老屋取回录音机。",
            "key_beats": [{"title": "录音到手", "description": "阿澄从老屋取回录音机"}],
        },
        {
            "ordinal": 2, "phase_key": "author_rest",
            "range_start": 6, "range_end": 20,
            "summary": "证据链逐层铺开。",
            "key_beats": [{"title": "证据链铺开", "description": "证人逐个改口"}],
        },
    ]
    issues = _rough_outline_issues(phases, example, range_label="集")
    blocking = rough_outline_blocking_issues(issues)
    assert blocking == [], blocking
    advices = rough_outline_advisory_issues(issues)
    assert advices and all(item.startswith("[建议] ") for item in advices)

    # 结构规范照旧阻断：区间必须从 1 起连续铺满。
    gapped = [phases[0], {**phases[1], "range_start": 7}]
    assert rough_outline_blocking_issues(
        _rough_outline_issues(gapped, example, range_label="集")
    ), "区间有缺口必须阻断"

    # 每阶段 ≥1 key_beats 同样是结构规范（平台硬拒，CLI 同判据）。
    thin = [phases[0], {**phases[1], "key_beats": []}]
    thin_blocking = rough_outline_blocking_issues(
        _rough_outline_issues(thin, example, range_label="集")
    )
    assert any("key_beats" in item for item in thin_blocking), thin_blocking


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
    result = CliRunner().invoke(main, ["script", "storymap-rebuild-phase", "p1", "act1", file_arg, "--review-token", "tok", "--json"])
    assert result.exit_code == 0, result.output
    body = session.request.call_args_list[1].kwargs["json_body"]
    assert body["phase_key"] == "act1"
    assert len(body["episodes"]) == 3
    assert body["episodes"][0]["promise"] is None
    assert body["episodes"][0]["payoff"] is None
    assert body["episodes"][0]["exit_hook"] is None
    assert body["episodes"][0]["scenes"][0]["character_action"] is None
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


def test_script_rough_outline_finalize_requires_and_forwards_review_token(monkeypatch):
    from unittest.mock import Mock

    from click.testing import CliRunner

    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {"id": "rough-candidate", "status": "active"}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, [
        "script", "rough-outline-propose", "p1",
        "--review-token", "review-final", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert session.request.call_args.args[1] == (
        "/script/projects/p1/rough-outline/build/finalize"
    )
    assert session.request.call_args.kwargs["headers"] == {
        "X-Review-Token": "review-final",
    }


def test_script_blueprint_extend_submits_sparse_patch_for_server_merge(monkeypatch, tmp_path):
    import cli_anything.scriptnow.scriptnow_cli as cli

    patch_file = tmp_path / "blueprint-patch.json"
    patch_file.write_text(json.dumps({"anchors": [{
        "id": "event:new-clue", "kind": "event", "name": "新线索",
        "payload": {"description": "该线索跨阶段改变调查方向"},
    }]}), encoding="utf-8")
    session = Mock()
    session.request.return_value = {"id": "candidate-merged", "status": "active"}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, [
        "script", "blueprint-extend", "p1", str(patch_file),
        "--review-token", "patch-token", "--json",
    ])
    assert result.exit_code == 0, result.output
    call = session.request.call_args
    assert call.args[1] == "/script/projects/p1/blueprints/extend"
    assert call.kwargs["headers"] == {"X-Review-Token": "patch-token"}
    assert call.kwargs["json_body"]["anchors"][0]["id"] == "event:new-clue"
    assert call.kwargs["json_body"]["anchors"][0]["kind"] == "event"
    assert json.loads(result.output)["merged_full_blueprint"] is True


def test_script_blueprint_extend_keeps_quote_and_arc_kinds(monkeypatch, tmp_path):
    import cli_anything.scriptnow.scriptnow_cli as cli

    anchors = [
        {"id": "arc:new", "kind": "arc", "name": "新弧线"},
        {"id": "quote:new", "kind": "quote", "name": "新金句"},
    ]
    patch_file = tmp_path / "blueprint-patch.json"
    patch_file.write_text(json.dumps({"anchors": anchors}), encoding="utf-8")
    session = Mock()
    session.request.return_value = {"id": "candidate-merged", "status": "active"}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, [
        "script", "blueprint-extend", "p1", str(patch_file),
        "--review-token", "patch-token", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert session.request.call_args.kwargs["json_body"]["anchors"] == anchors


def test_rough_outline_phase_normalization_matches_server_defaults():
    import cli_anything.scriptnow.scriptnow_cli as cli

    normalized = cli._normalize_rough_outline_phase({
        "ordinal": 1,
        "phase_key": "act1",
        "phase_title_zh": "第一幕",
        "range_start": 1,
        "range_end": 3,
        "summary": "具体剧情",
        "key_beats": [{"title": "证据出现", "description": "主角找到被删除的录音"}],
    })
    assert normalized["phase_title_en"] == ""
    assert normalized["purpose"] == ""
    assert normalized["anchor_ids"] == []
    assert normalized["key_beats"][0]["anchor_ids"] == []


def test_rough_outline_prepare_returns_exact_task_packet(monkeypatch):
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.side_effect = [
        {
            "phases": [{"ordinal": 2, "phase_key": "false-answer",
                        "phase_title_zh": "错误答案", "range_start": 17, "range_end": 40}],
            "generation_batches": [
                {"phase_key": "false-answer", "ordinal": 1, "start": 17, "end": 21},
                {"phase_key": "false-answer", "ordinal": 2, "start": 22, "end": 26},
            ],
        },
        {"current_phase_key": "false-answer", "current_phase_ordinal": 2,
         "total_phases": 4, "completed_phases": ["clue"]},
        {"blueprint": {"anchors": [{"id": "character:lin", "kind": "character", "name": "林澄"}]}},
    ]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(
        main, ["script", "rough-outline-prepare", "p1", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ready_to_write"
    assert payload["schema"]["key_beats"][0] == {
        "title": "关键事件标题",
        "description": "人物行动、阻力及造成的状态变化",
        "anchor_ids": [],
    }
    assert payload["generation_batches"][0]["start"] == 17
    assert payload["allowed_anchors"][0]["id"] == "character:lin"
    assert "rough-outline-phase-preview" in payload["next_command"]


def test_rough_outline_phase_continue_stops_while_waiting_for_human(monkeypatch):
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {
        "packet_id": "packet-1",
        "project_id": "p1",
        "resource_kind": "rough_outline_phase",
        "status": "previewed",
        "preview": {"title": "第一幕", "content": {"summary": "阶段剧情"}},
    }
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(
        main, ["script", "rough-outline-phase-continue", "p1", "packet-1", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "waiting_for_human"
    assert payload["allowed_next_commands"] == ["scriptnow review status packet-1 --json"]
    assert session.request.call_count == 1


def test_rough_outline_phase_continue_claims_and_submits_active_packet(monkeypatch):
    import cli_anything.scriptnow.scriptnow_cli as cli

    phase = {"ordinal": 1, "phase_key": "act1", "phase_title_zh": "第一幕",
             "phase_title_en": "", "purpose": "", "range_start": 1, "range_end": 3,
             "summary": "阶段剧情", "key_beats": [], "anchor_ids": []}
    session = Mock()
    session.request.side_effect = [
        {"packet_id": "packet-1", "project_id": "p1", "resource_kind": "rough_outline_phase",
         "status": "active", "preview": {"title": "第一幕", "content": phase}},
        {"token": "review-token"},
        {"current_phase_key": "act2"},
    ]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(
        main, ["script", "rough-outline-phase-continue", "p1", "packet-1", "--json"]
    )
    assert result.exit_code == 0, result.output
    submit = session.request.call_args_list[2]
    assert submit.kwargs["json_body"]["phase"] == phase
    assert submit.kwargs["headers"] == {"X-Review-Token": "review-token"}
