"""2B-2：`chapter propose` 的原请求身份在 CLI 侧必须是**稳定且可解释的**。

与 `test_scene_request_identity.py`（2B-1，场次）同一条判据，换一个介质：

1. 同一次提交的两次调用必须得到**同一个**身份 —— 否则"平台已保存、响应丢了"的
   重试就拿不回原结果（旧实现用 `time_ns`，每次都不同，所以它做不到）。
2. 另一次提交即使正文完全相同，也必须得到**另一个**身份 —— 否则会命中旧回执、
   绕过人审。CLI 用来区分两者的依据是**这一次的人工授权凭证**。

多出来的两条是本次改动最容易踩坏的地方：

* **场次身份的字节不能被这次改动改变**。把两条派生函数合并成一个"通用 `unit_id`"
  会静默改掉 0.4.10 已发出的 `cli-scene-propose-…`：那等于让所有在途重试换一次
  提交。所以这里钉一个**写死的 golden 串**，改动就立刻变红。
* 身份必须出现在输出里；而**审阅凭证明文不得**出现在输出里（它是 sha256 的输入，
  不是输出）。
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main
from cli_anything.scriptnow.utils.request_identity import (
    chapter_propose_request_key,
    scene_propose_request_key,
)

BLOCKS = [
    {"block_id": "h1", "type": "heading", "text": "第一章 复职日"},
    {"block_id": "p1", "type": "prose", "text": "宋晚踏进辰川投资大楼。"},
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
            "chapter", "propose", "project-1", "chapter-1",
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
    assert keys[0].startswith("cli-chapter-propose-")
    assert not keys[0].removeprefix("cli-chapter-propose-").isdigit()


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
        json.dumps([*BLOCKS, {"block_id": "p2", "type": "prose", "text": "前台看了她一眼。"}]),
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


def test_the_review_credential_plaintext_never_reaches_the_output(runner, fake_session, tmp_path):
    """凭证是 sha256 的**输入**，不是输出：派生身份不得泄漏它。"""

    path = _blocks_file(tmp_path)
    secret = "review-token-super-secret-value"
    result = _invoke(runner, path, token=secret)
    assert result.exit_code == 0, result.output
    assert secret not in result.output
    assert secret not in _posted_keys(fake_session)[0]


def test_the_chapter_identity_lives_in_its_own_namespace():
    """同一项目、同一单元号、同一正文：章节身份必须与场次身份不同。

    两侧在服务端各有自己的回执表与候选表；身份若可互换，"同一条身份换了资源"
    这条冲突判据就失去意义。
    """

    common = dict(
        project_id="project-1",
        blocks=[{"block_id": "b", "type": "prose", "text": "x"}],
        review_token="t",
    )
    chapter = chapter_propose_request_key(chapter_id="unit-1", **common)
    scene = scene_propose_request_key(scene_id="unit-1", **common)
    assert chapter.startswith("cli-chapter-propose-")
    assert scene.startswith("cli-scene-propose-")
    assert chapter != scene


def test_the_scene_identity_bytes_are_frozen_for_backward_compatibility():
    """**回归护栏**：2B-2 不得改变场次（2B-1，已在 0.4.10 发出）身份的字节。

    值写死而不是"再算一次比对"—— 重算只能证明函数稳定，证明不了它与 0.4.10 的
    派生规则同形。这里钉的是那次发布的真实输出。
    """

    assert scene_propose_request_key(
        project_id="p1",
        scene_id="s1",
        blocks=[{"para_id": "p1", "type": "slugline", "text": "内景. 教室 - 清晨"}],
        review_token="tok-abc",
    ) == "cli-scene-propose-ed40f60dc865e1e48f420fced3707cdccb239e6f"


def test_the_derivation_is_pure_and_key_order_insensitive():
    """纯函数：同输入同输出，且与字典键序无关（否则重试会算出不同身份）。"""

    base = chapter_propose_request_key(
        project_id="p", chapter_id="chapter-1",
        blocks=[{"block_id": "a", "type": "prose", "text": "x"}],
        review_token="t",
    )
    reordered = chapter_propose_request_key(
        project_id="p", chapter_id="chapter-1",
        blocks=[{"text": "x", "type": "prose", "block_id": "a"}],
        review_token="t",
    )
    assert base == reordered
    for changed in (
        chapter_propose_request_key(
            project_id="p", chapter_id="chapter-2",
            blocks=[{"block_id": "a", "type": "prose", "text": "x"}], review_token="t",
        ),
        chapter_propose_request_key(
            project_id="p", chapter_id="chapter-1",
            blocks=[{"block_id": "a", "type": "prose", "text": "y"}], review_token="t",
        ),
        chapter_propose_request_key(
            project_id="p", chapter_id="chapter-1",
            blocks=[{"block_id": "a", "type": "prose", "text": "x"}], review_token="u",
        ),
    ):
        assert changed != base
