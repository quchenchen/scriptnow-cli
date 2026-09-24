"""`@file` 与裸路径必须等价，读不到文件必须走 `--json` 契约。

治的是什么
==========

四条**位置参数** `FILE_PATH` 的命令把它直接当成路径读 —— `script propose`、`novel propose`、
`script planning-quality`、`novel planning-quality`：

    raw = Path(file_path).read_text(encoding="utf-8")

而 agent-guide 教给作者的正是 `@cores.json` 这一形态（每个项目都要走一遍的规划回填步骤，
guide 第 4/5/6 步都在用 `@`）。于是照抄 guide 得到的是：

    FileNotFoundError: [Errno 2] No such file or directory: '@cores.json'

一个 **Python traceback**：既是错的消息（文件明明在那儿），又**绕过了 `--json` 的错误契约**。
两个 `--resume-from` 选项（`chapter batch` / `script scene-batch`）是同一处代码的轻症 ——
`@` 不被识别、报错本来就干净，所以只剥标记。

⚠️ 这里要克制：**「读不到文件就给 traceback」不是这四条独有的**。按仓内实点，39 处
`read_text` 里只有 11 处附近有 `except …OSError`，所以别的命令同样会把「文件读不到」冒成
裸 traceback —— `review preview`（guide 第 4 步可达）实测就是这样。那是一片更宽的**既有**
面，本批不动它；本批只保证自己碰的这六处走契约。反过来说，`@` 的处理在别处**是对的**：
实测那些命令的 `@` 形态与裸形态发出逐字节相同的请求。

`@` 是标记，不是文件名的一部分 —— `scriptnow_cli.py` 里 37 处内联写法都是这么处理的。

本文件断言三件事
================

1. **`@` 形态与裸形态发出同一个请求**：请求体相同，且**文件内容真的进了请求体**（用一个
   哨兵串找得到）。两条合起来才排得掉「两边都没读到文件、所以两边都是空」这种假等价。

   一条例外要写清楚：`novel propose` 的请求身份是**按设计**每次新铸的
   `cli-propose-<kind>-<time_ns()>`，所以只对它归一化那一个字段；其余三条（含
   `script propose`，其身份由内容派生、因而稳定）连**原始字节**都必须相同。
2. **读不到 / 不是 UTF-8 / 不是合法 JSON / 根不是对象** 四种都走 `--json` 契约，
   且**没有 traceback**（坏编码是 2026-09-22 复审补齐的第四条 —— `UnicodeDecodeError`
   属 `ValueError`，原先的 `except OSError` 看不见它）。
3. 两个 `--resume-from` 也剥标记：报错里出现的是**剥掉 `@` 之后的**文件名。

为什么用 `catch_exceptions=False`
================================

它才是本文件的判据所在。`CliRunner` 默认把异常吞成 `exit_code == 1` —— 修复前的
`FileNotFoundError` 会**伪装成一次普通的失败**，而普通失败正是本文件要证其「消息正确」的东西。
关掉它之后：命令自己抛的 `SystemExit`（`--json` 契约那条路径）照样落到 `exit_code`，
而**任何**未预期异常都会冒成真实 traceback、把用例打红。

会话：`tests/conftest.py` 已把 `SCRIPTNOW_CLI_CONFIG` 钉在一个必然不存在的路径上。本文件在
读文件之后就要打请求，所以显式替换 `_session`（与 `tests/test_json_errors.py` 同法）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow import scriptnow_cli as cli
from cli_anything.scriptnow.utils.json_input import (
    read_json_object,
    resolve_input_path,
    strip_file_marker,
)

PROJECT_ID = "p1"

#: 哨兵：它出现在请求体里，才能证明「文件内容真的读进去了」。
SENTINEL = "AT-INPUT-SENTINEL"

ANCHORS = [
    {"id": "world:at-input", "kind": "world", "name": SENTINEL, "payload": {}},
]

#: 位置参数 `FILE_PATH` 的四条命令。`kind` 用 blueprint：四条的取值域都含它。
POSITIONAL_COMMANDS = [
    ("script propose", ["script", "propose", PROJECT_ID, "blueprint"], True),
    ("novel propose", ["novel", "propose", PROJECT_ID, "blueprint"], True),
    ("script planning-quality", ["script", "planning-quality", PROJECT_ID, "blueprint"], False),
    ("novel planning-quality", ["novel", "planning-quality", PROJECT_ID, "blueprint"], False),
]

#: `--resume-from` 的两条命令（`chapter batch` 是顶层 `chapter` 组）。
BATCH_COMMANDS = [
    ("chapter batch", ["chapter", "batch", PROJECT_ID]),
    ("script scene-batch", ["script", "scene-batch", PROJECT_ID]),
]

#: 请求身份**按设计**每次新铸的命令 —— 归一化那一个字段，而不是放过差异。
#: R2-C 只把 `script propose` 的 blueprint 一条 kind 换成了内容派生的稳定身份；
#: `novel propose` 仍是 `cli-propose-<kind>-<time_ns()>`，这一批不动它。
VOLATILE_IDENTITY_COMMANDS = {"novel propose"}

#: 归一化时只替换**值**：键名仍参与比较，一边有、一边没有照样红。
VOLATILE_BODY_FIELDS = ("idempotency_key",)


class _RecordingSession:
    """记录每一次请求，并回一个形状够用的响应。

    形状取 `{"id", "status"}`：`propose` 从它取 `id` 做候选号，`planning-quality` 直接
    `_emit` 它。本文件关心的是**发出去的请求**，不是回来的响应。
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        body = kwargs.get("json_body")
        self.calls.append({"method": method, "path": path, "body": body})
        return {"id": "cand-1", "status": "active"}


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> _RecordingSession:
    recorder = _RecordingSession()
    monkeypatch.setattr(cli, "_session", lambda _ctx: recorder)
    return recorder


def _invoke(
    argv: list[str], *, path: str, as_marker: bool
) -> tuple[Any, _RecordingSession]:
    """把路径插在 `FILE_PATH` 的位置上，`@` 形态与裸形态各跑一次。"""

    rendered = f"@{path}" if as_marker else path
    args = [*argv[:4], rendered, *argv[4:]]
    if argv[1] in {"propose"}:
        args += ["--review-token", "review-token"]
    args += ["--json"]
    # `catch_exceptions=False`：见模块 docstring —— 未预期异常必须以 traceback 现形。
    result = CliRunner(catch_exceptions=False).invoke(cli.main, args)
    return result, args


def _write(tmp_path: Path, name: str, payload: Any) -> Path:
    target = tmp_path / name
    target.write_text(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def _error_of(result: Any) -> dict[str, Any]:
    return json.loads(result.stdout)["error"]


def _normalized(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把「每次调用都新铸」的身份字段值换成占位符，其余字节一律保持原样。"""

    out = []
    for call in calls:
        body = call["body"]
        if isinstance(body, dict):
            body = {
                key: ("<volatile>" if key in VOLATILE_BODY_FIELDS else value)
                for key, value in body.items()
            }
        out.append({**call, "body": body})
    return out


def test_the_marker_form_and_the_bare_form_send_the_same_request(
    tmp_path: Path, session: _RecordingSession
) -> None:
    """`@file` 与 `file` 必须发出同一个请求，且内容真的进了请求体。"""

    path = _write(tmp_path, "anchors.json", {"anchors": ANCHORS})

    for label, argv, _ in POSITIONAL_COMMANDS:
        with_marker = _RecordingSession()
        cli._session = lambda _ctx, _r=with_marker: _r  # type: ignore[assignment]
        result_marker, _ = _invoke(argv, path=str(path), as_marker=True)
        assert result_marker.exit_code == 0, f"{label}（@ 形态）：{result_marker.output}"

        bare = _RecordingSession()
        cli._session = lambda _ctx, _r=bare: _r  # type: ignore[assignment]
        result_bare, _ = _invoke(argv, path=str(path), as_marker=False)
        assert result_bare.exit_code == 0, f"{label}（裸形态）：{result_bare.output}"

        if label in VOLATILE_IDENTITY_COMMANDS:
            # 身份本来就逐次不同；先归一化那个字段，再比**其余**字节。
            assert _normalized(with_marker.calls) == _normalized(bare.calls), (
                f"{label}：除请求身份外，两种形态发出的请求不同"
            )
            # 归一化不得掩盖身份方案被换掉：前缀仍须是这条命令的既定形态。
            keys = [call["body"].get("idempotency_key") for call in with_marker.calls]
            assert keys and all(
                isinstance(key, str) and key.startswith("cli-propose-blueprint-")
                for key in keys
            ), f"{label}：请求身份形态变了 —— {keys}"
        else:
            # 其余三条连原始字节都必须相同（`script propose` 的身份由内容派生，故也稳定）。
            assert with_marker.calls == bare.calls, f"{label}：两种形态发出的请求不同"

        # 内容真的到了：哨兵出现在请求体里。
        sent = json.dumps([call["body"] for call in with_marker.calls], ensure_ascii=False)
        assert SENTINEL in sent, f"{label}：请求体里没有文件内容（读到的可能不是这个文件）"

    # 复原 fixture 装的 recorder，免得影响后续用例。
    cli._session = lambda _ctx: session  # type: ignore[assignment]


@pytest.mark.parametrize(("label", "argv", "_needs_token"), POSITIONAL_COMMANDS)
def test_a_missing_file_leaves_through_the_json_contract(
    label: str, argv: list[str], _needs_token: bool
) -> None:
    """缺文件：干净 JSON、无 traceback，且报的是**剥掉 `@` 之后**的真实文件名。"""

    for as_marker in (True, False):
        result, _ = _invoke(
            argv, path="/tmp/definitely-not-here/anchors.json", as_marker=as_marker
        )
        assert result.exit_code == 1, f"{label}：{result.output}"
        assert "Traceback" not in result.output, f"{label}：又漏出 traceback 了"
        error = _error_of(result)
        assert error["type"] == "cli_error"
        assert "读取文件失败" in error["detail"]
        assert "'/tmp/definitely-not-here/anchors.json'" in error["detail"]
        assert "'@/tmp" not in error["detail"], f"{label}：`@` 没被剥掉"


@pytest.mark.parametrize(("label", "argv", "_needs_token"), POSITIONAL_COMMANDS)
def test_bad_json_leaves_through_the_json_contract(
    label: str, argv: list[str], _needs_token: bool, tmp_path: Path
) -> None:
    """非法 JSON 与非对象根：同样是干净 JSON，不是 traceback。"""

    broken = _write(tmp_path, "broken.json", "{ not json")
    result, _ = _invoke(argv, path=str(broken), as_marker=True)
    assert result.exit_code == 1, f"{label}：{result.output}"
    assert "Traceback" not in result.output
    assert "JSON 解析失败" in _error_of(result)["detail"]

    array = _write(tmp_path, "array.json", [1, 2, 3])
    result, _ = _invoke(argv, path=str(array), as_marker=True)
    assert result.exit_code == 1, f"{label}：{result.output}"
    assert "Traceback" not in result.output
    assert _error_of(result)["detail"] == "JSON 根必须是对象"


@pytest.mark.parametrize(("label", "argv"), BATCH_COMMANDS)
def test_the_batch_resume_option_also_strips_the_marker(
    label: str, argv: list[str], session: _RecordingSession
) -> None:
    """两个 `--resume-from` 也认 `@`：报错里出现的是剥掉标记之后的文件名。

    只测缺文件这一支：文件存在时命令会继续往下走批量生成，那不是本文件的对象。
    """

    args = [*argv, "--resume-from", "@/tmp/definitely-not-here/resume.json", "--yes", "--json"]
    result = CliRunner(catch_exceptions=False).invoke(cli.main, args)

    assert result.exit_code == 1, f"{label}：{result.output}"
    assert "Traceback" not in result.output
    detail = _error_of(result)["detail"]
    # 各自的领域文案保留原样，只有文件名被剥掉 `@`。
    assert "读取进度文件失败" in detail, f"{label}：{detail}"
    assert "'/tmp/definitely-not-here/resume.json'" in detail
    assert "'@/tmp" not in detail


@pytest.mark.parametrize(("label", "argv", "_needs_token"), POSITIONAL_COMMANDS)
def test_a_file_that_is_not_utf8_leaves_through_the_json_contract(
    label: str,
    argv: list[str],
    _needs_token: bool,
    tmp_path: Path,
    session: _RecordingSession,
) -> None:
    """非法 UTF-8：干净 JSON、无 traceback，且**一次请求都没发出去**。

    这一条是 2026-09-22 复审留下的 P2 缺口。`read_text(encoding="utf-8")` 原先只捕获
    `OSError`，而 `UnicodeDecodeError` 属 `ValueError` 一支，两边都不沾 ⇒ 含坏字节的文件
    仍冒成裸 traceback。复审实测：`--json script propose … @<坏文件>` 退出码 1、
    **stdout 为空**，agent 拿不到任何错误对象。

    修法是把解码失败也转成 `ClickException`，而**不是** `errors="ignore"` / `"replace"`，
    也不猜编码 —— 那两种都会**改掉作者的字节**，而这里的意图只有一个：告诉作者这文件不是
    UTF-8。断言「不发请求」是有意义的：四条命令都在 `_session(ctx)` **之前**读文件，
    所以坏输入必须止步于读取。
    """

    # 一个真字节 0xFF：UTF-8 里**必然非法**，且它出现在字符串字面量位置上 ——
    # 与「合法的 JSON 结构 + 坏的编码」这个真实场景同形。
    bad = tmp_path / "bad-utf8.json"
    bad.write_bytes(b'{"title":"\xff"}')

    for as_marker in (True, False):
        result, _ = _invoke(argv, path=str(bad), as_marker=as_marker)
        assert result.exit_code == 1, f"{label}：{result.output}"
        assert "Traceback" not in result.output, f"{label}：坏字节又冒成 traceback 了"
        error = _error_of(result)
        assert error["type"] == "cli_error"
        assert "UTF-8" in error["detail"], f"{label}：{error['detail']}"
        # 报的是**剥掉 `@` 之后**的路径：`@` 是标记，不是名字的一部分。
        assert str(bad) in error["detail"], f"{label}：{error['detail']}"
        assert f"@{bad}" not in error["detail"], f"{label}：`@` 没被剥掉"

    assert session.calls == [], f"{label}：坏输入还没抛错，请求就先发出去了"


def test_the_helper_itself(tmp_path: Path) -> None:
    """助手的三条边界：剥一次、裸路径不动、`@@` 指到真名以 `@` 开头的文件。"""

    assert strip_file_marker("@a.json") == "a.json"
    assert strip_file_marker("a.json") == "a.json"
    assert strip_file_marker("@@a.json") == "@a.json"
    # 纯字符串：`--resume-from` 的调用点要用**本模块之外**的 `Path`（见助手 docstring），
    # 返回 `Path` 会让那条测试的替身失效。
    assert isinstance(strip_file_marker("@a.json"), str)
    assert resolve_input_path("@a.json") == Path("a.json")
    assert resolve_input_path("a.json") == Path("a.json")
    assert resolve_input_path("@@a.json") == Path("@a.json")

    # 目录：读不到 ⇒ ClickException（而不是 IsADirectoryError 冒到顶）。
    import click

    with pytest.raises(click.ClickException):
        read_json_object(str(tmp_path))

    # 根不是对象：连 `{"a": 1}` 之外的形状都不放行。
    array = _write(tmp_path, "arr.json", [1])
    with pytest.raises(click.ClickException, match="JSON 根必须是对象"):
        read_json_object(str(array))

    # 非法 UTF-8：也转成 ClickException，提示里点名 UTF-8（不看编码就抛 traceback 的那条）。
    undecodable = tmp_path / "undecodable.json"
    undecodable.write_bytes(b'{"a":"\xff"}')
    with pytest.raises(click.ClickException, match="UTF-8"):
        read_json_object(str(undecodable))

    # `@` 形态读得到真实存在的文件。
    good = _write(tmp_path, "good.json", {"anchors": ANCHORS})
    assert read_json_object(f"@{good}")["anchors"] == ANCHORS
