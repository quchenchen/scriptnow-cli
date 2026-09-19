"""Hosted-instance behaviour: a CLI whose login session is owned by a host Agent.

A ScriptNow CLI runs in two very different places, and they need **opposite**
advice about logging in:

* **self-managed** (the author's own machine) — the CLI owns its session, so
  "run ``scriptnow login``" is correct;
* **hosted** (``SCRIPTNOW_HOSTED=1``, set by the deepseek-harness integration) —
  the host mints the session server-side and writes it to
  ``SCRIPTNOW_CLI_CONFIG``. Here ``scriptnow login`` waits for a browser callback
  on the *instance's* ``127.0.0.1``, which the author's browser can never reach,
  so it can only time out. On 2026-09-16 a live instance's agent reacted to that
  dead end by asking the author to paste ``sf_access`` / ``sf_refresh`` /
  ``sf_csrf`` out of devtools — a phishing-shaped request that must never be
  necessary, and one that puts live credentials into a transcript.

Both shapes are pinned here because the failure mode is silent: the wrong advice
looks like a perfectly reasonable sentence.

Note on how these are tested: the contract constants in ``scriptnow_cli``
(``_LOGIN_RULE``, ``_GUIDE_STEPS``, ``_MAIN_HELP``, …) are computed **at import
time** — a CLI process reads its environment once, at startup — so the contract
tests reload the module under the desired environment rather than monkeypatching
afterwards.
"""

from __future__ import annotations

import importlib

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.utils.hosted import (
    HOSTED_ENV,
    hosted_instance,
    login_remedy,
    login_remedy_example,
    login_unsupported_message,
)
from cli_anything.scriptnow.utils.session import ScriptNowError, load

MODULE_NAME = "cli_anything.scriptnow.scriptnow_cli"


@pytest.fixture
def cli_module(monkeypatch):
    """Load ``scriptnow_cli`` under a chosen SCRIPTNOW_HOSTED value.

    The module is reloaded on entry *and* restored to the self-managed shape on
    exit, so no later test inherits a hosted module object.
    """

    def _load(value: str | None):
        if value is None:
            monkeypatch.delenv(HOSTED_ENV, raising=False)
        else:
            monkeypatch.setenv(HOSTED_ENV, value)
        return importlib.reload(importlib.import_module(MODULE_NAME))

    yield _load
    monkeypatch.delenv(HOSTED_ENV, raising=False)
    importlib.reload(importlib.import_module(MODULE_NAME))


# ── detection ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("", False),
        ("   ", False),
    ],
)
def test_hosted_detection_truth_table(monkeypatch, value: str, expected: bool) -> None:
    monkeypatch.setenv(HOSTED_ENV, value)
    assert hosted_instance() is expected


def test_hosted_detection_defaults_to_self_managed(monkeypatch) -> None:
    """Unset means self-managed: guessing "hosted" would tell a normal user
    (who relocates their session via SCRIPTNOW_CLI_CONFIG) not to log in."""
    monkeypatch.delenv(HOSTED_ENV, raising=False)
    assert hosted_instance() is False


def test_relocating_the_session_file_is_not_treated_as_hosted(monkeypatch) -> None:
    """SCRIPTNOW_CLI_CONFIG is a documented self-service fix for sandboxed /
    permission-restricted setups; those users still own their own login."""
    monkeypatch.delenv(HOSTED_ENV, raising=False)
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", "/tmp/somewhere/session.json")
    assert hosted_instance() is False


# ── remedy wording ───────────────────────────────────────────────────────


def test_self_managed_remedy_points_at_login(monkeypatch) -> None:
    monkeypatch.delenv(HOSTED_ENV, raising=False)
    remedy = login_remedy()
    assert "scriptnow login" in remedy
    assert "scriptnow login" in login_remedy_example()


def test_hosted_remedy_never_points_at_login(monkeypatch) -> None:
    monkeypatch.setenv(HOSTED_ENV, "1")
    remedy = login_remedy()
    assert "宿主" in remedy
    # The whole point: no command the user cannot run.
    assert "scriptnow login --host" not in remedy
    assert login_remedy_example() == ""
    # And it must actively discourage credential hand-off.
    assert "Cookie" in remedy


def test_login_refusal_explains_why_and_offers_a_way_out() -> None:
    message = login_unsupported_message()
    assert "SCRIPTNOW_HOSTED" in message
    assert "127.0.0.1" in message
    assert "Cookie" in message
    # Escape hatch for the rare "I really do want to log in here" case.
    assert "unset SCRIPTNOW_HOSTED" in message


# ── session loading ──────────────────────────────────────────────────────


def test_missing_session_in_hosted_mode_does_not_suggest_login(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(HOSTED_ENV, "1")
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "missing.json"))
    with pytest.raises(ScriptNowError) as excinfo:
        load()
    text = str(excinfo.value)
    # The message deliberately *names* the command in order to forbid it, so the
    # assertion is on the runnable form — no host argument to copy out.
    assert "scriptnow login --host" not in text
    assert "宿主" in text


def test_missing_session_in_self_managed_mode_suggests_login(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv(HOSTED_ENV, raising=False)
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "missing.json"))
    with pytest.raises(ScriptNowError) as excinfo:
        load()
    assert "scriptnow login" in str(excinfo.value)


# ── the login command itself ─────────────────────────────────────────────


def test_login_command_refuses_in_hosted_mode_without_waiting(
    cli_module, monkeypatch, tmp_path
) -> None:
    """It must refuse *before* attempting the browser flow: waiting for a
    callback that can never arrive is exactly the timeout the agent then
    misreports to the user."""
    module = cli_module("1")
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "missing.json"))
    result = CliRunner().invoke(module.main, ["login"])
    assert result.exit_code != 0
    assert "宿主" in result.output
    assert "127.0.0.1" in result.output


def test_login_command_is_allowed_in_self_managed_mode(
    cli_module, monkeypatch, tmp_path
) -> None:
    """Guarded by *reaching* the browser flow, not by exit code: self-managed
    mode must get past the refusal and hand off to ``browser_login``."""
    module = cli_module(None)
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "missing.json"))
    reached: list[str] = []

    def fake_browser_login(host, *, timeout, notify):  # noqa: ANN001, ARG001
        reached.append(host)
        raise ScriptNowError("stubbed: browser flow reached")

    monkeypatch.setattr(
        "cli_anything.scriptnow.utils.browser_login.browser_login", fake_browser_login
    )
    result = CliRunner().invoke(
        module.main, ["login", "--host", "https://example.test"]
    )
    assert reached == ["https://example.test"]
    assert "宿主 Agent 托管" not in result.output


# ── doctor ───────────────────────────────────────────────────────────────


def test_doctor_reports_hosted_remedy(cli_module, monkeypatch, tmp_path) -> None:
    module = cli_module("1")
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "missing.json"))
    result = CliRunner().invoke(module.main, ["doctor"])
    combined = result.output + (result.stderr if result.stderr else "")
    assert "宿主" in combined
    assert "scriptnow login --host" not in combined


def test_doctor_reports_login_remedy_when_self_managed(
    cli_module, monkeypatch, tmp_path
) -> None:
    module = cli_module(None)
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "missing.json"))
    result = CliRunner().invoke(module.main, ["doctor"])
    combined = result.output + (result.stderr if result.stderr else "")
    assert "scriptnow login" in combined


def test_doctor_states_the_remedy_exactly_once(
    cli_module, monkeypatch, tmp_path
) -> None:
    """`doctor` must not say the same remedy twice.

    ``session.load()``'s message already carries the remedy, and ``doctor`` has
    its own ``修复：`` line — printing both made the output read like a stuck
    record. The strip in ``doctor`` keeps exactly one copy, in both modes.
    """
    monkeypatch.setenv("SCRIPTNOW_CLI_CONFIG", str(tmp_path / "missing.json"))
    for flag in ("1", None):
        module = cli_module(flag)
        result = CliRunner().invoke(module.main, ["doctor"])
        # Click 8.5 的 `result.output` 已经是 stdout+stderr 的合并流，再拼一次
        # `result.stderr` 会把同一段文本数两遍 —— 计数断言不能沿用成员断言那套写法。
        combined = result.output
        assert combined.count(login_remedy()) == 1, (flag, combined)


# ── agent-facing contracts ───────────────────────────────────────────────


def test_runtime_contract_forbids_cookie_handoff_when_hosted(cli_module) -> None:
    module = cli_module("1")
    rules = module._AGENT_RUNTIME_CONTRACT["rules"]
    joined = "\n".join(rules)
    # 托管形态下契约必须：① 不引导走那条必然超时的普通登录；② 指出**能走通**的设备流；
    # ③ 明确禁止向用户要 Cookie，以及 agent 自行换发/读会话文件。
    assert "scriptnow login --device" in joined
    assert "普通的 scriptnow login 在实例里只会超时" in joined
    assert "Cookie" in joined
    assert "换发/刷新端点" in joined
    # Step 1 of the 12-step order is not "登录" when the host owns the session.
    assert "确认已登录" in joined


def test_runtime_contract_keeps_login_guidance_when_self_managed(cli_module) -> None:
    module = cli_module(None)
    joined = "\n".join(module._AGENT_RUNTIME_CONTRACT["rules"])
    assert "登录只用 scriptnow login" in joined
    # 设备流是托管形态的出路；自助形态下 loopback 回调本来就通，不该引它。
    assert "scriptnow login --device" not in joined
    assert "确认已登录" not in joined


def test_guide_step_one_switches_command_when_hosted(cli_module) -> None:
    hosted = cli_module("1")
    step = hosted._GUIDE_STEPS[0]
    assert step["command"] == "scriptnow doctor --json"
    assert "宿主" in step["title"]

    self_managed = cli_module(None)
    step = self_managed._GUIDE_STEPS[0]
    assert step["command"] == "scriptnow login --host https://sn.igeewa.com"
    assert step["title"] == "登录平台"


def test_main_help_switches_step_one_when_hosted(cli_module) -> None:
    hosted = cli_module("1")
    assert "scriptnow doctor --json" in hosted._LOGIN_HELP_LINE
    assert "scriptnow login --host" not in hosted._LOGIN_HELP_LINE

    self_managed = cli_module(None)
    assert "scriptnow login --host" in self_managed._LOGIN_HELP_LINE


def test_full_contract_quickstart_switches_when_hosted(cli_module) -> None:
    hosted = cli_module("1")
    quickstart = hosted._AGENT_CONTRACT["quickstart"]
    assert any("scriptnow doctor --json" in item for item in quickstart)
    assert not any(
        item.strip().startswith("scriptnow login") for item in quickstart
    )
