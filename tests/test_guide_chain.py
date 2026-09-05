"""Public CLI tests for the 12-step focused guide chain and contract sync.

The 12-step guide is the agent's creation-order backbone; it must chain
1 -> 2 -> ... -> 12 with no overflow (step 12 yields no next_step), keep the
planning trio (cores/blueprint -> synopsis -> rough outline -> StoryMap with
episode/chapter outlines) in dependency order, and stay in sync with the
short/long agent contracts and the frontend /cli page.

These tests deliberately reuse the in-memory _GUIDE_STEPS payloads so a
reorder cannot silently drop a step or break the chain.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import (
    _AGENT_CONTRACT,
    _AGENT_RUNTIME_CONTRACT,
    _GUIDE_CREATIVE_LENSES,
    _GUIDE_STEPS,
    _SCRIPT_GUIDE_OVERRIDES,
    main,
)

NL = chr(10)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _guide_json(runner: CliRunner, step: int, medium: str = "novel") -> dict:
    result = runner.invoke(main, ["guide", "--step", str(step), "--medium", medium, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


# ---------------------------------------------------------------- chain ---

def test_guide_steps_are_exactly_12_in_fixed_order() -> None:
    steps = [int(s["step"]) for s in _GUIDE_STEPS]
    assert steps == list(range(1, 13))
    titles = [s["title"] for s in _GUIDE_STEPS]
    # Fixed dependency order approved by the author: login -> create -> direction
    # -> cores/blueprint -> synopsis -> rough outline -> StoryMap with episode/
    # chapter outlines -> Skill -> prose -> review -> export -> done.
    assert titles[0] == "登录平台"
    assert "故事核心与创作蓝图" in titles[3], titles[3]
    assert titles[4] == "先写故事梗概，定下全书走向"
    assert titles[5] == "全剧统筹与粗纲"
    assert "StoryMap" in titles[6] and "集纲" in titles[6], titles[6]
    assert titles[7] == "规划并挂载专属 Skill（门禁 · 须健壮性完善）"
    assert titles[8] == "逐章共创正文"
    assert titles[9] == "审读与修订"
    assert titles[10] == "包装与导出交付"
    assert titles[11] == "标记完成"


def test_next_step_chain_runs_1_to_12_and_ends_at_12(runner: CliRunner) -> None:
    for step in range(1, 12):
        data = _guide_json(runner, step)
        ns = data["step"]["next_step"]
        assert ns is not None, f"step {step} must chain onward"
        assert ns["step"] == step + 1, f"step {step} must point to {step + 1}"
        assert "scriptnow guide --step" in ns["command"], ns
    # Step 12 is the terminal act: no overflow into step 13.
    data = _guide_json(runner, 12)
    assert data["step"]["next_step"] is None


def test_creative_lenses_spans_all_12_steps() -> None:
    assert sorted(_GUIDE_CREATIVE_LENSES.keys()) == list(range(1, 13))
    for step, lenses in _GUIDE_CREATIVE_LENSES.items():
        assert isinstance(lenses, list) and len(lenses) == 3, (step, lenses)


def test_script_overrides_cover_planning_trio_and_dual_mode() -> None:
    expected = {2, 4, 5, 6, 7, 9, 10}
    assert expected <= set(_SCRIPT_GUIDE_OVERRIDES.keys())
    # step 6 = rough outline (new step), step 7 = merged StoryMap + episode outline
    assert "rough-outline" in _SCRIPT_GUIDE_OVERRIDES[6]["command"]
    assert "storymap" in _SCRIPT_GUIDE_OVERRIDES[7]["command"]
    assert "episode-outline" in _SCRIPT_GUIDE_OVERRIDES[7]["command"] or "集纲" in _SCRIPT_GUIDE_OVERRIDES[7]["verify"]


def test_rough_outline_precedes_storymap_in_guide_text(runner: CliRunner) -> None:
    step6 = _guide_json(runner, 6)
    step7 = _guide_json(runner, 7)
    assert "粗纲" in step6["step"]["title"]
    assert "StoryMap" in step7["step"]["title"]
    assert "StoryMap" in step6["step"]["why"] or "集纲" in step6["step"]["why"]


# ------------------------------------------------------------ endpoints ---

def test_guide_error_message_mentions_1_to_12(runner: CliRunner) -> None:
    result = runner.invoke(main, ["guide", "--resume", "--medium", "novel"])
    assert result.exit_code != 0
    assert "--step <1..12>" in result.output


def test_guide_docstring_mentions_12_steps() -> None:
    from click.testing import CliRunner as Runner

    r = Runner().invoke(main, ["guide", "--help"])
    assert r.exit_code == 0
    assert "12 步" in r.output or "固定 12 步" in r.output or "12 幕" in r.output


# ------------------------------------------------------------- contracts ---

def test_runtime_contract_has_backfill_platform_author_and_order() -> None:
    rc = _AGENT_RUNTIME_CONTRACT
    assert rc["contract_version"] == "4"
    rules = NL.join(rc["rules"])
    assert "创作顺序固定为 12 步" in rules
    assert "规划回填优先" in rules
    assert "正文最终创作默认由平台内真实 AgentScope Agent 主笔" in rules
    assert "绝不自动扩大为采纳、结构覆盖、删除或发布" in rules
    assert "已弃用" in rules and "authorize" in rules
    quickstart = NL.join(rc["quickstart"])
    # HEAD 版 quickstart 保持精简入口（--help / agent-guide --full）
    assert "agent-guide" in quickstart
    assert "--help" in quickstart



def test_long_contract_planning_chain_is_cores_first() -> None:
    quickstart = NL.join(_AGENT_CONTRACT["quickstart"])
    idx_cores = quickstart.index("故事核心与蓝图")
    idx_synopsis = quickstart.index("梗概")
    idx_rough = quickstart.index("粗纲")
    idx_storymap = quickstart.index("storymap")
    assert idx_cores < idx_synopsis < idx_rough < idx_storymap
    rules = NL.join(_AGENT_CONTRACT["rules"])
    assert "创作顺序铁律" in rules
    assert "已弃用" in rules and "decision-token" in rules
    assert "scriptnow novel|script adopt" not in quickstart
    assert "scriptnow novel adopt-core <作品号> <候选号> --review-token" in quickstart
    assert "scriptnow script adopt-blueprint <作品号> <候选号> --review-token" in quickstart


# ------------------------------------------------------------ doc sync ---

def test_doc_files_reflect_fixed_creation_order() -> None:
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    files = [
        root / "cli_anything" / "scriptnow" / "README.md",
        root / "README.md",
        root / "README.en.md",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert ("故事核心与蓝图" in text) or ("cores & blueprint" in text), path
        assert ("粗纲" in text) or ("rough outline" in text), path
        assert (("authorize" in text) and ("已弃用" in text)) or ("DEPRECATED" in text), path
        novel_row = next(line for line in text.splitlines() if line.startswith("| novel |"))
        script_row = next(line for line in text.splitlines() if line.startswith("| script |"))
        assert novel_row.index("story-cores") < novel_row.index("outline"), path
        assert script_row.index("story-cores") < script_row.index("outline"), path


def test_skill_md_reflects_layer_order() -> None:
    import pathlib

    skill = (
        pathlib.Path(__file__).resolve().parents[1]
        / "cli_anything" / "scriptnow" / "skills" / "SKILL.md"
    )
    text = skill.read_text(encoding="utf-8")
    assert "adopt story cores and blueprint" in text
    assert "synopsis outline" in text
    assert "rough outline" in text
    assert "StoryMap" in text


def test_readmes_and_skill_match_current_review_contract() -> None:
    import pathlib

    cli_root = pathlib.Path(__file__).resolve().parents[1]
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    cli_docs = [
        cli_root / "README.md",
        cli_root / "README.en.md",
        cli_root / "cli_anything" / "scriptnow" / "README.md",
    ]
    for path in cli_docs:
        text = path.read_text(encoding="utf-8")
        assert "propose-preview" in text, path

    english = (cli_root / "README.en.md").read_text(encoding="utf-8")
    assert (
        'scriptnow review confirm <packet-id> --decision retain '
        '--evidence "Keep this version and continue." --json'
    ) in english
    assert "automation/--json is rejected" not in english

    skill = (
        cli_root / "cli_anything" / "scriptnow" / "skills" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "scriptnow script|novel" not in skill
    assert "scriptnow script rough-outline-phase-preview" in skill
    assert "scriptnow script rough-outline-phase <pid> <phase_key>" in skill
    assert "scriptnow script rough-outline-progress <pid> --json" in skill
    assert "scriptnow script rough-outline-propose <pid>" in skill
    assert "scriptnow review confirm <packet_id> --decision retain" in skill

    root_readme = (repo_root / "README.md").read_text(encoding="utf-8")
    flow = root_readme[root_readme.index("## 四种故事生产模式"):]
    assert flow.index("故事核心与小说蓝图") < flow.index("故事梗概")
    assert "`authorize` 为显式授权入口" not in root_readme


def test_cli_page_has_12_acts() -> None:
    import pathlib

    # workspace root = parents[3] (tests live in cli/scriptnow-cli/tests)
    page = (
        pathlib.Path(__file__).resolve().parents[3]
        / "scriptnow" / "frontend" / "apps" / "creator" / "src" / "views" / "CliGuidePage.vue"
    )
    text = page.read_text(encoding="utf-8")
    assert ("12 幕" in text) or ("12 acts" in text)
    assert "故事核心与蓝图" in text
    assert "全剧统筹与粗纲" in text
    assert "StoryMap 与集纲/章纲一体" in text


def test_cli_page_uses_the_canonical_cores_first_order_and_no_retired_bootstrap() -> None:
    import pathlib

    page = (
        pathlib.Path(__file__).resolve().parents[3]
        / "scriptnow" / "frontend" / "apps" / "creator" / "src" / "views" / "CliGuidePage.vue"
    )
    text = page.read_text(encoding="utf-8")
    novel = text[text.index("name: 'novel'"):text.index("name: 'chapter / storymap'")]
    script = text[text.index("name: 'script'"):text.index("name: 'storyboard'")]
    assert novel.index("propose <项目ID> cores") < novel.index("novel outline")
    assert script.index("script propose <项目ID> cores") < script.index("script outline")
    assert "novel bootstrap" not in text
    assert "默认由平台内真实 AgentScope 主笔" in text

# ------------------------------------------------ P2 hardening -----

WIP_CMD_NAMES = [
    'is_editable_install',
    'outline-preview',
    'storymap-preview',
    '_conversation_review',
    'human_preview',
]


def _all_step_commands(runner: CliRunner, medium: str) -> list[str]:
    out = []
    for step in range(1, 13):
        data = _guide_json(runner, step, medium)
        out.append(data['step']['command'])
        out.append(data['step'].get('verify', ''))
        ns = data['step'].get('next_step')
        if ns:
            out.append(ns.get('command', ''))
    return out


def test_step5_synopsis_chain_uses_review_confirm_claim_token(runner: CliRunner) -> None:
    for medium in ('novel', 'script'):
        data = _guide_json(runner, 5, medium)
        cmd = data['step']['command']
        assert 'review propose-preview' in cmd, (medium, cmd)
        assert 'review confirm' in cmd, (medium, cmd)
        assert 'review claim' in cmd, (medium, cmd)
        assert '--review-token' in cmd, (medium, cmd)
        assert '-status' in cmd or 'adopt' in cmd, (medium, cmd)
        for wip in ('outline-adopt-preview', 'authorize'):
            assert wip not in cmd, (medium, wip, cmd)


def test_step6_rough_outline_chain_example_check_candidate_adopt(runner: CliRunner) -> None:
    novel = _guide_json(runner, 6, 'novel')['step']['command']
    assert 'rough-outline-example' in novel, novel
    assert 'rough-outline-check' in novel, novel
    assert 'review candidate-preview novel' in novel, novel
    assert 'rough_outline_candidate' in novel, novel
    assert 'rough-outline-adopt' in novel, novel
    assert '--review-token' in novel, novel
    script = _guide_json(runner, 6, 'script')['step']['command']
    assert 'rough-outline-start' in script, script
    assert 'rough-outline-phase' in script, script
    assert 'rough-outline-progress' in script, script
    assert 'rough-outline-phase-preview' in script, script
    for wip in ('rough-outline-prepare', 'rough-outline-phase-continue', 'propose-preview'):
        assert wip not in novel and wip not in script, wip


def test_step7_storymap_chain_gates_with_confirm_and_token(runner: CliRunner) -> None:
    for medium in ('novel', 'script'):
        cmd = _guide_json(runner, 7, medium)['step']['command']
        assert 'review preview' in cmd, (medium, cmd)
        assert 'storymap adopt' in cmd, (medium, cmd)
        assert '--confirm' in cmd, (medium, cmd)
        assert '--review-token' in cmd, (medium, cmd)
        assert 'planning-quality' in cmd or '集纲' in cmd, (medium, cmd)
        for wip in ('storymap-preview', 'outline-adopt-preview', 'propose-preview'):
            assert wip not in cmd, (medium, wip, cmd)



def test_step4_planning_adopt_requires_confirm_claim_token(runner: CliRunner) -> None:
    for medium in ('novel', 'script'):
        cmd = _guide_json(runner, 4, medium)['step']['command']
        assert 'review preview' in cmd, (medium, cmd)
        assert 'candidate-preview' in cmd, (medium, cmd)
        assert 'review confirm' in cmd, (medium, cmd)
        assert 'review claim' in cmd, (medium, cmd)
        assert ('adopt-core <作品号> <候选号> --review-token' in cmd
                or 'adopt-blueprint <作品号> <候选号> --review-token' in cmd), (medium, cmd)
        for wip in ('authorize', 'blueprint-extend', 'propose-preview'):
            assert wip not in cmd, (medium, wip, cmd)

def test_step9_prose_adopt_requires_human_and_review_token(runner: CliRunner) -> None:
    for medium in ('novel', 'script'):
        cmd = _guide_json(runner, 9, medium)['step']['command']
        assert 'review preview' in cmd, (medium, cmd)
        assert 'review confirm' in cmd, (medium, cmd)
        assert 'review claim' in cmd, (medium, cmd)
        assert ('chapter adopt <作品号> <章节号> <版本号> --human --review-token' in cmd
                or 'scene adopt <作品号> <场号> <版本号> --human --review-token' in cmd), (medium, cmd)
        for wip in ('authorize', 'outline-adopt-preview', 'propose-preview'):
            assert wip not in cmd, (medium, wip, cmd)

def test_step6_script_long_chain_aggregate_review_before_propose(runner: CliRunner) -> None:
    script = _guide_json(runner, 6, 'script')['step']['command']
    assert 'rough_outline_build' in script, script
    assert 'scriptnow script rough-outline-propose <作品号> --review-token <汇总凭证> --json' in script, script
    i_build = script.find('rough_outline_build')
    i_propose = script.find('rough-outline-propose')
    assert 0 <= i_build < i_propose, (i_build, i_propose)


def _click_command(path: tuple[str, ...]) -> click.Command:
    """Resolve the real Click command used by a guide example."""
    command: click.Command = main
    for name in path:
        assert isinstance(command, click.Group), path
        nested = command.get_command(click.Context(command), name)
        assert nested is not None, path
        command = nested
    return command


def _assert_click_signature(
    path: tuple[str, ...],
    arguments: list[str],
    *,
    required_options: set[str] | None = None,
    options: set[str] | None = None,
) -> None:
    """Compare guide placeholders with Click's executable parameter contract.

    ``command ... --help`` is intentionally not used here: Click's eager help
    option exits before it validates missing or surplus positional arguments.
    """
    command = _click_command(path)
    click_arguments = [
        parameter.name
        for parameter in command.params
        if isinstance(parameter, click.Argument)
    ]
    click_options = {
        parameter.name: parameter
        for parameter in command.params
        if isinstance(parameter, click.Option)
    }
    assert click_arguments == arguments, path
    for name in required_options or set():
        assert name in click_options and click_options[name].required, (path, name)
    for name in options or set():
        assert name in click_options, (path, name)


def test_guide_adoption_examples_match_click_required_arguments(runner: CliRunner) -> None:
    """Guide placeholders must satisfy the command contracts they teach."""
    adoption_commands = [
        (("novel", "adopt-core"), ["project_id", "candidate_id"], set()),
        (("novel", "adopt-blueprint"), ["project_id", "candidate_id"], set()),
        (("script", "adopt-core"), ["project_id", "candidate_id"], set()),
        (("script", "adopt-blueprint"), ["project_id", "candidate_id"], set()),
        (("chapter", "adopt"), ["project_id", "chapter_id", "revision_id"], {"human_decision"}),
        (("scene", "adopt"), ["project_id", "scene_id", "revision_id"], {"human_decision"}),
    ]
    for path, arguments, optional_flags in adoption_commands:
        _assert_click_signature(
            path,
            arguments,
            required_options={"review_token"},
            options={"json_output", *optional_flags},
        )

    for medium in ("novel", "script"):
        planning = _guide_json(runner, 4, medium)["step"]["command"]
        prose = _guide_json(runner, 9, medium)["step"]["command"]
        assert "<作品号> <候选号> --review-token" in planning, planning
        assert "--human --review-token" in prose, prose


def test_script_rough_outline_guide_examples_match_click_command_groups(runner: CliRunner) -> None:
    commands = [
        (("script", "rough-outline-start"), ["project_id"], set()),
        (("script", "rough-outline-phase-preview"), ["project_id", "phase_key", "file_path"], set()),
        (("script", "rough-outline-phase"), ["project_id", "phase_key", "file_path"], {"review_token"}),
        (("script", "rough-outline-progress"), ["project_id"], set()),
        (("script", "rough-outline-propose"), ["project_id"], {"review_token"}),
    ]
    for path, arguments, required_options in commands:
        _assert_click_signature(
            path,
            arguments,
            required_options=required_options,
            options={"json_output"},
        )

    guide = _guide_json(runner, 6, "script")["step"]["command"]
    for command in (
        "scriptnow script rough-outline-start",
        "scriptnow script rough-outline-phase-preview",
        "scriptnow script rough-outline-phase",
        "scriptnow script rough-outline-progress",
        "scriptnow script rough-outline-propose",
    ):
        assert command in guide, guide


def test_subcommand_json_never_starts_background_upgrade_check(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A command-local --json is a clean stdout contract, even with auto-upgrade on."""
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "config.json"))
    from cli_anything.scriptnow.utils.upgrade import set_config

    set_config(autoUpgrade=True)
    with patch("cli_anything.scriptnow.scriptnow_cli.maybe_warn_in_background") as warning:
        result = runner.invoke(main, ["guide", "--step", "12", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["step"]["step"] == 12
    assert result.stderr == ""
    warning.assert_not_called()

def test_all_review_confirm_and_claim_carry_packet_id(runner: CliRunner) -> None:
    import re as _re
    for medium in ('novel', 'script'):
        text = NL.join(_all_step_commands(runner, medium))
        for m in _re.finditer(r'review confirm(?![ <])', text):
            raise AssertionError('bare review confirm: ' + m.group(0))
        for m in _re.finditer(r'review confirm <packet_id>(?! --decision)', text):
            raise AssertionError('confirm missing --decision: ' + m.group(0))
        if '--evidence' not in text:
            raise AssertionError('no confirm carries --evidence')
        for m in _re.finditer(r'review claim(?![ <])', text):
            raise AssertionError('bare review claim: ' + m.group(0))


def test_contracts_never_emit_bare_review_commands() -> None:
    import re as _re

    text = _json_dump_contract()
    for pat, label in (
        (r'review confirm(?![ <])', 'bare confirm'),
        (r'review confirm <packet_id>(?! --decision)', 'confirm missing --decision'),
        (r'review claim(?![ <])', 'bare claim'),
    ):
        for m in _re.finditer(pat, text):
            raise AssertionError(label + ': ' + m.group(0))
    assert '--evidence' in text, 'no confirm carries --evidence'


def test_contracts_use_valid_decision_values() -> None:
    import re as _re

    text = _json_dump_contract()
    for m in _re.finditer(r'--decision <[^>]+>', text):
        raise AssertionError('invalid decision placeholder: ' + m.group(0))


def _json_dump_contract() -> str:
    import json as _json

    return _json.dumps(
        [_AGENT_CONTRACT, _AGENT_RUNTIME_CONTRACT], ensure_ascii=False,
    )


def test_guide_never_suggests_wip_command_names(runner: CliRunner) -> None:
    for medium in ('novel', 'script'):
        text = NL.join(_all_step_commands(runner, medium))
        for wip in WIP_CMD_NAMES:
            assert wip not in text, (medium, wip)


def test_cli_page_fixed_order_words_and_no_legacy_phrase() -> None:
    import pathlib

    page = (
        pathlib.Path(__file__).resolve().parents[3]
        / 'scriptnow' / 'frontend' / 'apps' / 'creator' / 'src' / 'views' / 'CliGuidePage.vue'
    )
    text = page.read_text(encoding='utf-8')
    journey = _journey_acts_source(text)
    assert '故事核心与蓝图' in journey
    idx_cores = journey.index('故事核心与蓝图')
    assert '故事梗概' in journey
    assert journey.index('故事梗概') > idx_cores
    assert '全剧统筹与粗纲' in journey
    assert '一次明确采用' in text or '一次明确输入' in text
    assert '句明确采用' not in text


def test_cli_page_journey_acts_start_at_login_and_desc_chain_fixed() -> None:
    import pathlib

    page = (
        pathlib.Path(__file__).resolve().parents[3]
        / 'scriptnow' / 'frontend' / 'apps' / 'creator' / 'src' / 'views' / 'CliGuidePage.vue'
    )
    text = page.read_text(encoding='utf-8')
    journey = _journey_acts_source(text)
    # Check the rendered 12-act source, not unrelated command-group copy.
    assert '登录平台' in journey
    i_login = journey.index('登录平台')
    assert '故事核心与蓝图' in journey
    i_cores = journey.index('故事核心与蓝图')
    assert '故事梗概' in journey
    i_synopsis = journey.index('故事梗概')
    assert '全剧统筹与粗纲' in journey
    i_rough = journey.index('全剧统筹与粗纲')
    assert i_login < i_cores < i_synopsis < i_rough
    # 12 幕标题区仍标注 12 幕
    assert '12 幕' in text


def _journey_acts_source(text: str) -> str:
    """Return the 12-act UI data without conflating unrelated page prose."""
    start = text.index('const journeyActs')
    end = text.index('const contractPillars', start)
    return text[start:end]
