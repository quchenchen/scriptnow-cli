"""CLI contracts for background run inspection."""

from __future__ import annotations

from unittest.mock import Mock

from cli_anything.scriptnow.scriptnow_cli import main
from click.testing import CliRunner


def test_run_events_requests_machine_readable_empty_list(monkeypatch) -> None:
    session = Mock()
    session.request.return_value = []
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)

    result = CliRunner().invoke(main, ["run", "events", "run-1", "--json"])

    assert result.exit_code == 0
    assert result.output.strip() == "[]"
    session.request.assert_called_once_with(
        "GET",
        "/runs/run-1/events",
        headers={},
        params={"format": "json"},
        timeout=60,
    )


def test_run_status_preserves_structured_failure_detail(monkeypatch) -> None:
    session = Mock()
    session.request.return_value = {
        "id": "run-1",
        "status": "failed",
        "error_code": "script_scene_failed",
        "error": {
            "detail": "usage is outside an active reservation",
            "retryable": True,
        },
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)

    result = CliRunner().invoke(main, ["run", "status", "run-1", "--json"])

    assert result.exit_code == 0
    assert "usage is outside an active reservation" in result.output
