"""2B-1：`scene propose` 的原请求身份在 CLI 侧必须是**稳定且可解释的**。

要测的判据只有两条，且互相制约：

1. 同一次提交的两次调用必须得到**同一个**身份 —— 否则"平台已保存、响应丢了"的
   重试就拿不回原结果（旧实现用 `time_ns`，每次都不同，所以它做不到）。
2. 另一次提交即使正文完全相同，也必须得到**另一个**身份 —— 否则会命中旧回执、
   绕过人审。CLI 用来区分两者的依据是**这一次的人工授权凭证**。

把这两条写成断言，而不是写成"看起来很幂等"的实现：只按正文摘要派生会满足 (1)
却不满足 (2)。
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main
from cli_anything.scriptnow.utils.request_identity import scene_propose_request_key

BLOCKS = [
    {"para_id": "s1-1", "type": "slugline", "text": "INT. RECORDS ANNEX - NIGHT"},
    {"para_id": "s1-2", "type": "action", "text": "LIN sets the cassette on the desk."},
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_session(monkeypatch):
    """桩掉 HTTP：只关心 CLI 往 body 里放了什么身份，以及它是否稳定。"""

    session = Mock()
    session.base_url = "https://sn.example.test"
    session.request.return_value = {"id": "revision-1", "status": "candidate"}
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    return session


def _blocks_file(tmp_path, blocks=BLOCKS):
    path = tmp_path / "blocks.json"
    path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    return path


def _posted_keys(session: Mock) -> list[str]:
    return [
        call.kwargs["json_body"]["idempotency_key"]
        for call in session.request.call_args_list
        if str(call.args[1]).endswith("/propose")
    ]


def _invoke(runner, path, *, token="review-token-1", extra=()):
    return runner.invoke(
        main,
        [
            "script", "scene-propose", "project-1", "scene-1",
            "--file", str(path), "--review-token", token, "--json", *extra,
        ],
    )


def test_retry_of_the_same_submission_reuses_the_same_identity(runner, fake_session, tmp_path):
    """同一次提交调用两次 ⇒ 同一个身份（这就是跨调用恢复的前提）。"""

    path = _blocks_file(tmp_path)
    assert _invoke(runner, path).exit_code == 0
    assert _invoke(runner, path).exit_code == 0

    keys = _posted_keys(fake_session)
    assert len(keys) == 2
    assert keys[0] == keys[1]
    # 旧实现的时间戳键无法做到这一点：它每次都不同。这里显式否认那种形态。
    assert keys[0].startswith("cli-scene-propose-")
    assert not keys[0].removeprefix("cli-scene-propose-").isdigit()


def test_a_new_human_credential_is_a_new_request_even_with_identical_prose(
    runner, fake_session, tmp_path
):
    """正文完全相同、但换了一次人工授权 ⇒ 必须是另一个身份（否则绕过人审）。"""

    path = _blocks_file(tmp_path)
    assert _invoke(runner, path, token="review-token-1").exit_code == 0
    assert _invoke(runner, path, token="review-token-2").exit_code == 0

    keys = _posted_keys(fake_session)
    assert keys[0] != keys[1]


def test_changed_prose_is_a_different_identity(runner, fake_session, tmp_path):
    first = _blocks_file(tmp_path)
    second = tmp_path / "blocks-2.json"
    second.write_text(
        json.dumps([*BLOCKS, {"para_id": "s1-3", "type": "action", "text": "She listens."}]),
        encoding="utf-8",
    )
    assert _invoke(runner, first).exit_code == 0
    assert _invoke(runner, second).exit_code == 0

    keys = _posted_keys(fake_session)
    assert keys[0] != keys[1]


def test_explicit_request_key_wins_over_the_derived_one(runner, fake_session, tmp_path, monkeypatch):
    """调用方要把身份真正持久保留在自己那边时，`--request-key` 是出口。"""

    path = _blocks_file(tmp_path)
    result = _invoke(runner, path, extra=("--request-key", "dsh-submission-42"))
    assert result.exit_code == 0, result.output
    assert _posted_keys(fake_session) == ["dsh-submission-42"]

    fake_session.request.reset_mock()
    monkeypatch.setenv("SCRIPTNOW_REQUEST_KEY", "dsh-submission-43")
    assert _invoke(runner, path).exit_code == 0
    assert _posted_keys(fake_session) == ["dsh-submission-43"]


def test_the_printed_json_carries_the_identity_so_it_can_be_persisted(
    runner, fake_session, tmp_path
):
    """身份必须出现在输出里 —— 否则调用方拿不到"可持久取回"的那个引用。"""

    path = _blocks_file(tmp_path)
    result = _invoke(runner, path)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["request_key"] == _posted_keys(fake_session)[0]


def test_alias_scene_propose_accepts_the_same_identity_options(runner, fake_session, tmp_path):
    """`scene propose` 是别名，必须同样能收到原请求身份（保持旧调用兼容）。"""

    path = _blocks_file(tmp_path)
    derived = _invoke(runner, path)
    assert derived.exit_code == 0, derived.output
    expected = _posted_keys(fake_session)[0]

    fake_session.request.reset_mock()
    aliased = runner.invoke(
        main,
        [
            "scene", "propose", "project-1", "scene-1",
            "--file", str(path), "--review-token", "review-token-1", "--json",
        ],
    )
    assert aliased.exit_code == 0, aliased.output
    assert _posted_keys(fake_session) == [expected]

    fake_session.request.reset_mock()
    explicit = runner.invoke(
        main,
        [
            "scene", "propose", "project-1", "scene-1",
            "--file", str(path), "--review-token", "review-token-1", "--json",
            "--request-key", "alias-key-1",
        ],
    )
    assert explicit.exit_code == 0, explicit.output
    assert _posted_keys(fake_session) == ["alias-key-1"]


def test_the_derivation_is_pure_and_key_order_insensitive():
    """纯函数：同输入同输出，且与字典键序无关（否则重试会算出不同身份）。"""

    base = scene_propose_request_key(
        project_id="p", scene_id="scene-1",
        blocks=[{"para_id": "a", "type": "action", "text": "x"}],
        review_token="t",
    )
    reordered = scene_propose_request_key(
        project_id="p", scene_id="scene-1",
        blocks=[{"text": "x", "type": "action", "para_id": "a"}],
        review_token="t",
    )
    assert base == reordered
    for changed in (
        scene_propose_request_key(
            project_id="p", scene_id="scene-2",
            blocks=[{"para_id": "a", "type": "action", "text": "x"}], review_token="t",
        ),
        scene_propose_request_key(
            project_id="p", scene_id="scene-1",
            blocks=[{"para_id": "a", "type": "action", "text": "y"}], review_token="t",
        ),
        scene_propose_request_key(
            project_id="p", scene_id="scene-1",
            blocks=[{"para_id": "a", "type": "action", "text": "x"}], review_token="u",
        ),
    ):
        assert changed != base
