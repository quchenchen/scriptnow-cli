"""`interpret propose` —— 回填优先那条主路的回归测试（2026-09-19）。

为什么这个文件存在
------------------

`interpret propose` 是「改编项目来源画像」的**默认入口**：Agent 在本地读完原著、
把画像与锚点回填给平台，平台只校验与采纳（不调模型、不阻塞、原文不出本地）。
它是规划门禁「先批准来源画像」唯一不依赖平台通读的路。

命令随 CLI 0.4.3 引入（提交 `359f24d4`），**函数体里用了 `_json` 却漏了那行局部
导入**（本文件模块级第 13 行是 `import json`，函数内 41 处兄弟都写
`import json as _json`）。于是任何一次真实调用都在读到画像的第一行就炸：

    NameError: name '_json' is not defined
      @ .../scriptnow_cli.py line 2851, in interpret_propose

它逃过了当时**全部**验收，因为当时的证据全是**结构级**的：配方 67/67 只证明命令与
选项在命令树里解析得到（`--help` 能列出来），`check-vendored-cli.py` 只逐字节比对
源码与预装 wheel，两者都不执行函数体；CLI 测试套件里也**一处都没碰过**
`interpret propose`（`grep -rn "interpret propose" tests/` 为空）。Python 能编译它
（不是语法错），所以四个渠道一路把它发到了用户手上。

所以这里要钉两件事：
1. **真的把命令跑起来** —— 覆盖那两处 `_json`（裸对象与 `--skill` 文件）；
2. 断言失败时给的是**一句话**，不是 traceback —— 出错的正是 `except` 那一行，
   它自己也会因为同一个名字而二次抛错。
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main

PROFILE = {
    "title": "同名小说改编",
    "logline": "一个把论文读成寓言的人",
    "themes": ["技术主权", "寓言叙事"],
    "characters": [{"name": "龙国首席", "role": "主角"}],
}


def _stub_session(monkeypatch: pytest.MonkeyPatch, response: dict[str, object]) -> Mock:
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = response
    monkeypatch.setattr(cli, "_session", lambda *_args: session)
    return session


def _write(tmp_path, name: str, payload: object):
    path = tmp_path / name
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_spec_prints_the_backfill_contract_without_any_session():
    """`--spec` 是 Agent 的第一步，必须**在没有登录态时**也能用（它在请求之前就返回）。"""
    result = CliRunner().invoke(main, ["interpret", "propose", "project-1", "--spec", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["project_id"] == "project-1"
    assert payload["profile_spec"].strip(), "回填规范不能是空的"


def test_propose_posts_a_bare_profile_object(monkeypatch, tmp_path):
    """裸画像对象 —— 这条就是当初 NameError 的那条路。"""
    session = _stub_session(
        monkeypatch,
        {"id": "profile-9", "version": 2, "decision": "candidate",
         "profile": {"attestation": {"anchors": [{"chapter": 1}]}}},
    )
    profile_file = _write(tmp_path, "profile.json", PROFILE)

    result = CliRunner().invoke(
        main, ["interpret", "propose", "project-1", "--profile", f"@{profile_file}", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert "_json" not in result.output, "不该再把内部名字漏进用户可见的输出"

    method, path = session.request.call_args.args[:2]
    assert (method, path) == ("POST", "/projects/project-1/source-profiles/propose")
    body = session.request.call_args.kwargs["json_body"]
    assert body["profile"] == PROFILE
    # 原文没有交给平台：请求体里只有画像与自证，没有正文。
    assert "text" not in body and "source" not in body
    assert body["attestation"]["origin"] == "agent_local"  # 默认值
    assert body["idempotency_key"].startswith("cli-propose-")
    assert session.request.call_args.kwargs["timeout"] == 120

    echoed = json.loads(result.output)
    assert echoed["profile_id"] == "profile-9"
    assert echoed["version"] == 2
    assert echoed["anchors"] == 1


def test_propose_accepts_the_wrapped_form_with_anchors_reader_and_coverage(monkeypatch, tmp_path):
    """包装形式 `{profile, attestation, coverage}` + 命令行锚点合并进去。"""
    session = _stub_session(monkeypatch, {"id": "profile-10", "version": 1, "profile": {}})
    profile_file = _write(
        tmp_path,
        "wrapped.json",
        {
            "profile": PROFILE,
            "attestation": {"anchors": [{"chapter": 1, "note": "开场即点题"}], "reader": "旧值"},
            "coverage": {"coverage": "partial", "note": "只读了前 10 章"},
        },
    )

    result = CliRunner().invoke(
        main,
        [
            "interpret", "propose", "project-1",
            "--profile", f"@{profile_file}",
            "--anchor", "第 12 章：主角第一次说谎",
            "--reader", "改编搭档",
            "--coverage", "representative",
            "--origin", "agent_local",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    body = session.request.call_args.kwargs["json_body"]
    anchors = body["attestation"]["anchors"]
    # 文件里的锚点在前（结构化对象），命令行 --anchor 追加在后（自由文本）
    assert anchors[0]["chapter"] == 1
    assert anchors[-1] == "第 12 章：主角第一次说谎"
    assert body["attestation"]["reader"] == "改编搭档"  # 命令行覆盖文件里的
    assert body["coverage"]["coverage"] == "representative"  # 同上
    assert body["coverage"]["note"] == "只读了前 10 章"  # 未覆盖的键保留


def test_propose_reads_the_optional_skill_file(monkeypatch, tmp_path):
    """`--skill` 是**同一处的第二个 `_json` 使用点**，别只修住第一个。"""
    session = _stub_session(monkeypatch, {"id": "profile-11", "version": 1, "profile": {}})
    profile_file = _write(tmp_path, "profile.json", PROFILE)
    skill_file = _write(tmp_path, "skill.json", {"name": "改编搭档", "rules": ["先读后写"]})

    result = CliRunner().invoke(
        main,
        [
            "interpret", "propose", "project-1",
            "--profile", f"@{profile_file}",
            "--skill", f"@{skill_file}",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert session.request.call_args.kwargs["json_body"]["skill"] == {
        "name": "改编搭档",
        "rules": ["先读后写"],
    }


def test_malformed_profile_json_is_one_line_not_a_traceback(monkeypatch, tmp_path):
    """坏 JSON 必须给一句话 —— 那句 `except _json.JSONDecodeError` 一度自己也会炸。"""
    _stub_session(monkeypatch, {})
    broken = _write(tmp_path, "broken.json", "{不是合法 JSON")

    result = CliRunner().invoke(
        main, ["interpret", "propose", "project-1", "--profile", f"@{broken}", "--json"]
    )
    assert result.exit_code != 0
    assert "来源画像 JSON 解析失败" in result.output
    assert "NameError" not in result.output
    assert "_json" not in result.output
    assert "Traceback" not in result.output


def test_propose_without_a_profile_explains_the_first_step(monkeypatch):
    _stub_session(monkeypatch, {})
    result = CliRunner().invoke(main, ["interpret", "propose", "project-1"])
    assert result.exit_code != 0
    assert "--profile @profile.json" in result.output
    assert "--spec" in result.output  # 指回第一步


def test_propose_rejects_a_non_object_profile(monkeypatch, tmp_path):
    _stub_session(monkeypatch, {})
    array_file = _write(tmp_path, "array.json", [1, 2, 3])
    result = CliRunner().invoke(
        main, ["interpret", "propose", "project-1", "--profile", f"@{array_file}", "--json"]
    )
    assert result.exit_code != 0
    assert "必须是对象" in result.output
