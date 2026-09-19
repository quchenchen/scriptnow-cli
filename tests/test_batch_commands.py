"""CLI contracts for the automatic batch creation mode.

批次 = agent+CLI 侧串行编排：CLI 只负责逐单元串行跑完一批，四道门缺一即拒，
且只产候选、绝不自动采纳。这些断言盯的正是「门有没有牙」和「串行有没有被破坏」——
两者失效都不会报错，只会让设定静默漂移。
"""

from __future__ import annotations

import json
from unittest.mock import Mock

from click.testing import CliRunner

import cli_anything.scriptnow.scriptnow_cli as cli
from cli_anything.scriptnow.scriptnow_cli import main

NOVEL_STATE = {
    "story_map": {"volumes": [{"chapters": [{"id": "chapter-1-1"}, {"id": "chapter-1-2"}]}]},
    "documents": [{"chapter_id": "chapter-1-1", "status": "adopted_human", "revision_number": 2}],
}

SCRIPT_STATE = {
    "story_map": {"episodes": [{"scenes": [{"id": "scene-1"}, {"id": "scene-2"}]}]},
    "documents": [{"scene_id": "scene-1", "status": "adopted_human", "revision_number": 1}],
}

STYLE_MOUNTED = [{"skill_id": "style-1", "enabled": True}]


def _session(*, state=None, mounts=None, run_status="succeeded") -> Mock:
    """Session stub; records every request so tests can assert order and shape."""
    session = Mock()
    calls: list[tuple[str, str]] = []

    def request(method: str, path: str, **_kwargs):
        calls.append((method, path))
        if path.endswith("/state"):
            return state if state is not None else NOVEL_STATE
        if path.endswith("/skills"):
            return mounts if mounts is not None else STYLE_MOUNTED
        if path.endswith("/generate?background=true"):
            return {"run_id": "run-1"}
        if "/runs/" in path:
            return {"status": run_status}
        raise AssertionError(f"unexpected request: {method} {path}")

    session.request.side_effect = request
    session.calls = calls
    return session


def _install(monkeypatch, session: Mock) -> None:
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)


def _detail(result) -> str:
    return json.loads(result.output)["error"]["detail"]


def test_batch_refuses_a_batch_larger_than_three(monkeypatch) -> None:
    _install(monkeypatch, _session())
    result = CliRunner().invoke(
        main, ["chapter", "batch", "p1", "--chapters", "a,b,c,d", "--json"]
    )

    assert result.exit_code != 0
    assert "批次规模超限" in _detail(result)


def test_batch_refuses_a_single_unit_and_points_at_single_generate(monkeypatch) -> None:
    _install(monkeypatch, _session())
    result = CliRunner().invoke(
        main, ["chapter", "batch", "p1", "--chapters", "chapter-1-2", "--json"]
    )

    assert result.exit_code != 0
    detail = _detail(result)
    assert "批次规模不足" in detail
    assert "chapter generate" in detail


def test_batch_requires_the_first_chapter_to_be_adopted(monkeypatch) -> None:
    """新手期未过：第一章还没有已采纳正文，批次不许开。"""
    state = dict(NOVEL_STATE, documents=[])
    _install(monkeypatch, _session(state=state))
    result = CliRunner().invoke(
        main, ["chapter", "batch", "p1", "--chapters", "chapter-1-1,chapter-1-2", "--json"]
    )

    assert result.exit_code != 0
    assert "新手期未过" in _detail(result)


def test_batch_requires_a_mounted_methodology_skill(monkeypatch) -> None:
    """风格未明确：没有挂载通过门禁的方法论 Skill，批次不许开。"""
    _install(monkeypatch, _session(mounts=[]))
    result = CliRunner().invoke(
        main, ["chapter", "batch", "p1", "--chapters", "chapter-1-1,chapter-1-2", "--json"]
    )

    assert result.exit_code != 0
    assert "写作风格未明确" in _detail(result)


def test_batch_runs_units_serially_and_never_adopts(monkeypatch) -> None:
    session = _session()
    _install(monkeypatch, session)
    result = CliRunner().invoke(
        main,
        ["chapter", "batch", "p1", "--chapters", "chapter-1-1,chapter-1-2", "--yes", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["succeeded"] == 2
    assert [item["chapter_id"] for item in payload["results"]] == ["chapter-1-1", "chapter-1-2"]
    # 产出只是候选：命令自己不能宣称已采纳。
    assert payload["review_required"] is True

    # 串行编排：每章「生成 → 等 run 到终态」之后才轮到下一章，中间没有任何采纳写操作。
    assert session.calls == [
        ("GET", "/novel/projects/p1/state"),
        ("GET", "/projects/p1/skills"),
        ("POST", "/novel/projects/p1/chapters/chapter-1-1/generate?background=true"),
        ("GET", "/novel/projects/p1/runs/run-1"),
        ("POST", "/novel/projects/p1/chapters/chapter-1-2/generate?background=true"),
        ("GET", "/novel/projects/p1/runs/run-1"),
    ]


def test_resume_accepts_a_single_remaining_unit(monkeypatch) -> None:
    """续跑是接着同一批跑：只剩 1 个失败项时下限门不该把它拦下来。"""
    _install(monkeypatch, _session())

    class _ProgressFile:
        def __init__(self, _value: str) -> None:
            pass

        def read_text(self, **_kwargs) -> str:
            return json.dumps({"failed": ["chapter-1-2"]})

    monkeypatch.setattr(cli, "Path", _ProgressFile)
    result = CliRunner().invoke(
        main, ["chapter", "batch", "p1", "--resume-from", "failed.json", "--yes", "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["succeeded"] == 1


def test_script_scene_batch_shares_the_same_gates(monkeypatch) -> None:
    """剧本域走同一组门——「该模式」不是小说专有。"""
    _install(monkeypatch, _session(state=SCRIPT_STATE))
    result = CliRunner().invoke(
        main, ["scene", "batch", "p1", "--scenes", "scene-1,scene-2,scene-1,scene-2", "--json"]
    )

    assert result.exit_code != 0
    assert "批次规模超限" in _detail(result)


def test_script_scene_batch_requires_the_first_scene_adopted(monkeypatch) -> None:
    state = dict(SCRIPT_STATE, documents=[])
    _install(monkeypatch, _session(state=state))
    result = CliRunner().invoke(
        main, ["scene", "batch", "p1", "--scenes", "scene-1,scene-2", "--json"]
    )

    assert result.exit_code != 0
    assert "新手期未过" in _detail(result)
