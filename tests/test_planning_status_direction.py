"""Planning status reads direction through the public project list API."""

from __future__ import annotations

import json
from unittest.mock import Mock

from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main


def test_novel_planning_status_reads_direction_without_a_nonexistent_get_route(
    monkeypatch,
) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = [{
        "id": "p1",
        "direction": {"volume_one": 1, "volume_two": 1},
    }]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    monkeypatch.setattr(cli, "_novel_state", lambda _session, _pid: {
        "story_map": {"version": 1, "volumes": [{
            "id": "v1", "chapters": [{"id": "c1", "outline": "已采纳章纲"}],
        }]},
        "documents": [],
    })
    monkeypatch.setattr(cli, "_api_request", lambda _ctx, _method, _path: {})

    result = CliRunner().invoke(main, ["novel", "planning-status", "p1", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["alignment"]["consistent"] is True
    session.request.assert_called_once_with("GET", "/projects")
