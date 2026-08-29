from __future__ import annotations

import json
from unittest.mock import Mock

from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main
from cli_anything.scriptnow.utils.session import ScriptNowError


def test_json_platform_error_is_structured_without_traceback(monkeypatch) -> None:
    session = Mock()
    session.request.side_effect = ScriptNowError(
        "HTTP 409: Novel StoryMap version conflict"
    )
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, ["storymap", "state", "p1", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload == {
        "ok": False,
        "error": {
            "type": "platform_error",
            "status": 409,
            "detail": "Novel StoryMap version conflict",
        },
    }
    assert "Traceback" not in result.output


def test_json_usage_error_uses_same_envelope() -> None:
    result = CliRunner().invoke(main, ["project", "create", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "cli_error"
    assert payload["error"]["status"] is None
    assert "--name" in payload["error"]["detail"]
    assert "Usage:" not in result.output
