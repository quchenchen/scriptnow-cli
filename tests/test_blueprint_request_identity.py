"""R2-C：`script propose <作品号> blueprint` 的原请求身份必须是**稳定且可解释的**。

判据（与 2B-1 场次、2B-2 章节同一条）换到规划类候选上：

1. 同一次提交的两次调用必须得到**同一个**身份 —— 否则"平台已保存、响应丢了"的重试就
   拿不回原结果。本批之前它是 `cli-script-propose-blueprint-<time_ns>`，每次都不同，
   所以平台那条恢复优先的 `POST /script/projects/{pid}/blueprints/propose` 虽然备着
   回执表，也**永远命中不了** —— 恢复链断在接缝上。
2. 另一次提交即使锚点逐字相同，也必须得到**另一个**身份 —— 否则会命中旧回执、绕过人审。
   CLI 用来区分两者的依据是**这一次的人工授权凭证**。

另外三条是本批特有的边界：

* **只有 blueprint 一条 kind 拿到稳定身份**。cores / storymap / bibles 的平台端点没有
  回执表，本批**刻意不推广**（ADR-004 §5「不一次推广所有规划命令」）：换一个稳定身份
  买不到任何恢复，却会把"重试"变成"撞上端点自己的唯一键"。所以那几条必须仍是时间戳
  形态，而 `--request-key` 对它们必须**报错**而不是被静默收下。
* 身份必须出现在输出里（调用方要把它持久保存）—— 但**只在真能取回的 blueprint 上**：
  对没有回执的 kind 一并回报，就与同一批 `--request-key` 的帮助文本和拒绝逻辑自相矛盾。
  **审阅凭证明文不得**出现 —— 它只是 sha256 的输入，不是输出。
* 一条**写死的 golden 串**把派生规则钉住：改键名、改前缀或改参与哈希的字段就立刻变红。
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main
from cli_anything.scriptnow.utils.request_identity import (
    blueprint_propose_request_key,
    chapter_propose_request_key,
    scene_propose_request_key,
)

PREFIX = "cli-script-blueprint-propose-"

BLUEPRINT_PATH = "/script/projects/project-1/blueprints/propose"

ANCHORS = [
    {
        "id": "world:tide",
        "kind": "world",
        "name": "潮汐记年",
        "payload": {"description": "海平面即历法"},
    },
    {
        "id": "character:lin",
        "kind": "character",
        "name": "林溯",
        "payload": {"description": "记录员"},
    },
]

CORES = {"drafts": [{"title": "复职日", "concept": "记忆被定期删除"}]}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_session(monkeypatch):
    """桩掉 HTTP：只关心 CLI 往 body 里放了什么身份，以及它是否稳定。"""

    session = Mock()
    session.base_url = "https://sn.example.test"
    session.request.return_value = {"id": "candidate-1", "status": "candidate"}
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    return session


def _json_file(tmp_path, payload, name="blueprint.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _posted(session: Mock) -> list[tuple[str, str]]:
    """(路径, 请求身份) —— 只取提交类端点，避免把 GET 之类混进来。"""

    return [
        (str(call.args[1]), call.kwargs["json_body"]["idempotency_key"])
        for call in session.request.call_args_list
        if str(call.args[1]).endswith("/propose")
    ]


def _posted_keys(session: Mock) -> list[str]:
    return [key for _, key in _posted(session)]


def _invoke(runner, path, *, kind="blueprint", token="review-token-1", extra=()):
    return runner.invoke(
        main,
        [
            "script", "propose", "project-1", kind, str(path),
            "--review-token", token, "--json", *extra,
        ],
    )


def test_script_blueprint_preserves_quote_and_narrative_arc(
    runner, fake_session, tmp_path
):
    """Script kind validation belongs to the server; arc must not become character_arc."""

    anchors = ANCHORS + [
        {"id": "arc:change", "kind": "arc", "name": "转变", "payload": {}},
        {"id": "quote:line", "kind": "quote", "name": "金句", "payload": {}},
    ]
    path = _json_file(tmp_path, {"anchors": anchors})
    result = _invoke(runner, path)
    assert result.exit_code == 0, result.output
    assert fake_session.request.call_args.kwargs["json_body"]["anchors"] == anchors


def test_retry_of_the_same_submission_reuses_the_same_identity(runner, fake_session, tmp_path):
    """同一次提交调用两次 ⇒ 同一个身份（这就是跨调用恢复的前提）。"""

    path = _json_file(tmp_path, {"anchors": ANCHORS})
    assert _invoke(runner, path).exit_code == 0
    assert _invoke(runner, path).exit_code == 0

    keys = _posted_keys(fake_session)
    assert len(keys) == 2
    assert keys[0] == keys[1]
    # 旧实现的时间戳键无法做到这一点：它每次都不同。这里显式否认那种形态。
    assert keys[0].startswith(PREFIX)
    assert not keys[0].removeprefix(PREFIX).isdigit()


def test_a_new_human_credential_is_a_new_request_even_with_identical_anchors(
    runner, fake_session, tmp_path
):
    """锚点完全相同、但换了一次人工授权 ⇒ 必须是另一个身份（否则绕过人审）。"""

    path = _json_file(tmp_path, {"anchors": ANCHORS})
    assert _invoke(runner, path, token="review-token-1").exit_code == 0
    assert _invoke(runner, path, token="review-token-2").exit_code == 0

    keys = _posted_keys(fake_session)
    assert keys[0] != keys[1]


def test_changed_anchors_are_a_different_identity(runner, fake_session, tmp_path):
    first = _json_file(tmp_path, {"anchors": ANCHORS}, name="a.json")
    second = _json_file(
        tmp_path,
        {"anchors": [*ANCHORS, {"id": "plot:blackout", "kind": "plot", "name": "全城停电"}]},
        name="b.json",
    )
    assert _invoke(runner, first).exit_code == 0
    assert _invoke(runner, second).exit_code == 0

    keys = _posted_keys(fake_session)
    assert keys[0] != keys[1]


def test_the_identity_is_sent_to_the_recovery_first_endpoint(runner, fake_session, tmp_path):
    """身份必须送到那条**恢复优先**的端点 —— 送到别处再稳定也取不回结果。"""

    path = _json_file(tmp_path, {"anchors": ANCHORS})
    assert _invoke(runner, path).exit_code == 0

    assert _posted(fake_session) == [(BLUEPRINT_PATH, _posted_keys(fake_session)[0])]


def test_explicit_request_key_wins_over_the_derived_one(runner, fake_session, tmp_path, monkeypatch):
    """调用方要把身份真正持久保留在自己那边时，`--request-key` 是出口。"""

    path = _json_file(tmp_path, {"anchors": ANCHORS})
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

    path = _json_file(tmp_path, {"anchors": ANCHORS})
    result = _invoke(runner, path)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["request_key"] == _posted_keys(fake_session)[0]


def test_the_identity_is_reported_only_where_it_can_actually_be_used(
    runner, fake_session, tmp_path
):
    """字段名就是"拿它去取回"的意思 ⇒ 只在真能取回的 kind 上出现。

    对没有回执的 kind 也回报，与同一批 `--request-key` 的帮助文本和拒绝逻辑**自相矛盾**：
    一手把值交出去、另一手把它拒掉，调用方会以为那是可重试身份。这是"输出契约必须自洽"
    的护栏 —— 它挡住的正是"顺手一起回报"这种无据可依的扩大。
    """

    blueprint = _invoke(runner, _json_file(tmp_path, {"anchors": ANCHORS}))
    assert blueprint.exit_code == 0, blueprint.output
    assert json.loads(blueprint.stdout)["request_key"].startswith(PREFIX)

    cores = _invoke(runner, _json_file(tmp_path, CORES, name="cores.json"), kind="cores")
    assert cores.exit_code == 0, cores.output
    assert "request_key" not in json.loads(cores.stdout)


def test_the_review_credential_plaintext_never_reaches_the_output(runner, fake_session, tmp_path):
    """凭证是 sha256 的**输入**，不是输出：派生身份不得泄漏它。"""

    path = _json_file(tmp_path, {"anchors": ANCHORS})
    secret = "review-token-super-secret-value"
    result = _invoke(runner, path, token=secret)
    assert result.exit_code == 0, result.output
    assert secret not in result.output
    assert secret not in _posted_keys(fake_session)[0]


def test_the_blueprint_identity_lives_in_its_own_namespace():
    """规划候选没有单元键，命名空间全由前缀承担 ⇒ 三条派生必须互不相同。

    若蓝图前缀不带领域，将来小说侧蓝图身份一旦接入就会与它共用同一段命名空间，
    "同一条身份换了资源"这条服务端冲突判据就失去意义。
    """

    common = dict(project_id="project-1", review_token="t")
    blueprint = blueprint_propose_request_key(anchors=[{"id": "a"}], **common)
    chapter = chapter_propose_request_key(
        chapter_id="unit-1", blocks=[{"block_id": "b", "type": "prose", "text": "x"}], **common
    )
    scene = scene_propose_request_key(
        scene_id="unit-1", blocks=[{"para_id": "b", "type": "action", "text": "x"}], **common
    )
    assert blueprint.startswith(PREFIX)
    assert chapter.startswith("cli-chapter-propose-")
    assert scene.startswith("cli-scene-propose-")
    assert len({blueprint, chapter, scene}) == 3


def test_only_the_blueprint_kind_carries_a_stable_identity(runner, fake_session, tmp_path):
    """护栏：本批**不推广**到其余规划 kind —— 它们必须仍是每次新铸的时间戳形态。

    它们的平台端点没有回执表：换一个稳定身份买不到恢复，只会把"重试"变成"撞上端点
    自己的唯一键"。这个断言就是"没有顺手一起改"的证据。
    """

    path = _json_file(tmp_path, CORES, name="cores.json")
    assert _invoke(runner, path, kind="cores").exit_code == 0
    assert _invoke(runner, path, kind="cores").exit_code == 0

    keys = _posted_keys(fake_session)
    assert len(keys) == 2
    assert keys[0] != keys[1], "cores 的端点没有回执，稳定身份在这里是无据可依的行为改变"
    assert all(key.startswith("cli-script-propose-cores-") for key in keys)
    assert all(key.removeprefix("cli-script-propose-cores-").isdigit() for key in keys)


def test_request_key_is_refused_for_a_kind_without_a_platform_receipt(
    runner, fake_session, tmp_path
):
    """显式传一个身份给没有回执的 kind ⇒ 必须报错，不能被静默收下。

    静默收下是最坏的一种：调用方以为自己拿到了"可重试身份"，实际平台侧根本没有回执，
    重试会变成一次新提交（甚至撞唯一键），而 CLI 一声不吭。
    """

    path = _json_file(tmp_path, CORES, name="cores.json")
    result = _invoke(runner, path, kind="cores", extra=("--request-key", "dsh-submission-42"))
    assert result.exit_code != 0
    assert "blueprint" in result.output and "只对" in result.output, result.output
    assert _posted_keys(fake_session) == [], "被拒的调用不得发出任何请求"


def test_the_env_request_key_is_ignored_for_other_kinds_without_being_silent(
    runner, fake_session, tmp_path, monkeypatch
):
    """环境变量是**上下文**而不是本次调用的明确意图：忽略，但不静默。

    全局导出 `SCRIPTNOW_REQUEST_KEY` 的调用方不该因为跑了一次 cores 就整体失败；反过来，
    一声不吭地忽略它会让调用方以为自己指定了身份。提示落 stderr ⇒ `--json` 的 stdout
    仍是干净可解析的对象（本用例就是用它来证明的两件事同时成立）。
    """

    monkeypatch.setenv("SCRIPTNOW_REQUEST_KEY", "dsh-submission-42")
    path = _json_file(tmp_path, CORES, name="cores.json")
    result = _invoke(runner, path, kind="cores")
    assert result.exit_code == 0, result.output

    keys = _posted_keys(fake_session)
    assert keys != ["dsh-submission-42"]
    assert keys[0].removeprefix("cli-script-propose-cores-").isdigit()
    assert "SCRIPTNOW_REQUEST_KEY" in result.stderr and "未使用" in result.stderr, result.stderr
    # stdout 仍是**只有**一个 JSON 对象：提示没有污染 `--json` 契约。
    json.loads(result.stdout)


def test_the_derived_identity_is_pinned_by_a_literal_golden_key():
    """**回归护栏**：派生规则被写死的值钉住。

    值写死而不是"再算一次比对"—— 重算只能证明函数稳定，证明不了输入字典的键名与
    前缀还是这一版发出的那一组。改掉 `anchors` 这个键名、把前缀改成不带领域的
    `cli-blueprint-propose-`、或往 payload 里补一个字段，这里都会立刻变红。
    """

    assert blueprint_propose_request_key(
        project_id="project-1",
        anchors=ANCHORS,
        review_token="review-token-1",
    ) == "cli-script-blueprint-propose-b807eadb902a272a48eee0f2adb52fdfc96886d1"


def test_the_derivation_is_pure_and_key_order_insensitive():
    """纯函数：同输入同输出，且与字典键序无关（否则重试会算出不同身份）。"""

    base = blueprint_propose_request_key(
        project_id="p", anchors=ANCHORS, review_token="t"
    )
    reordered = blueprint_propose_request_key(
        project_id="p",
        anchors=[{key: item[key] for key in ("payload", "name", "kind", "id")} for item in ANCHORS],
        review_token="t",
    )
    assert base == reordered
    for changed in (
        blueprint_propose_request_key(project_id="p", anchors=ANCHORS[:1], review_token="t"),
        blueprint_propose_request_key(
            project_id="p",
            anchors=[{**ANCHORS[0], "name": "潮汐记年（改）"}, *ANCHORS[1:]],
            review_token="t",
        ),
        blueprint_propose_request_key(project_id="p", anchors=ANCHORS, review_token="u"),
        blueprint_propose_request_key(project_id="q", anchors=ANCHORS, review_token="t"),
    ):
        assert changed != base
