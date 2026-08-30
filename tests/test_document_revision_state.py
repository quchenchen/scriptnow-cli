"""Regression tests for human-finalized chapter/scene state aggregation."""

from __future__ import annotations

import json
from unittest.mock import Mock

from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main


def _blocks(text: str) -> list[dict[str, str]]:
    return [{"type": "slugline", "text": "内景. 书房 - 夜"}, {"type": "action", "text": text}]


def _documents(unit_key: str) -> list[dict[str, object]]:
    unit_id = "scene-1" if unit_key == "scene_id" else "chapter-1"
    return [
        {
            "id": f"{unit_key}-human-1",
            unit_key: unit_id,
            "revision_number": 1,
            "status": "adopted_human",
            "source": "agent",
            "blocks": _blocks("人工定稿正文"),
        },
        {
            "id": f"{unit_key}-candidate-2",
            unit_key: unit_id,
            "revision_number": 2,
            "status": "candidate",
            "source": "platform",
            "blocks": _blocks("较新的候选正文"),
        },
        {
            "id": f"{unit_key}-active-3",
            unit_key: unit_id,
            "revision_number": 3,
            "status": "active",
            "source": "platform",
            "blocks": _blocks("最新活动候选正文"),
        },
    ]


def _script_state() -> dict[str, object]:
    return {
        "story_map": {
            "episodes": [{"id": "episode-1", "title": "第一集", "scenes": [{"id": "scene-1", "title": "书房"}]}]
        },
        "documents": _documents("scene_id"),
    }


def _novel_state() -> dict[str, object]:
    return {
        "story_map": {
            "volumes": [{"id": "volume-1", "chapters": [{"id": "chapter-1", "title": "第一章", "ordinal": 1}]}]
        },
        "documents": _documents("chapter_id"),
    }


def test_scene_list_and_show_treat_adopted_human_as_final(monkeypatch):
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = _script_state()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    runner = CliRunner()

    listed = runner.invoke(main, ["scene", "list", "project-1", "--json"])
    assert listed.exit_code == 0, listed.output
    row = json.loads(listed.output)[0]
    assert row["adopted_revision"] == 1
    assert row["adopted_human"] is True
    assert row["candidate_revisions"] == [3, 2]
    assert row["latest_candidate_id"] == "scene_id-active-3"

    shown = runner.invoke(main, ["scene", "show", "project-1", "scene-1", "--json"])
    assert shown.exit_code == 0, shown.output
    payload = json.loads(shown.output)
    assert payload["revision_id"] == "scene_id-human-1"
    assert payload["status"] == "adopted_human"
    assert payload["adopted_human"] is True
    assert payload["adopted_revision"]["revision_number"] == 1
    assert [item["revision_number"] for item in payload["candidate_revisions"]] == [2, 3]


def test_scene_show_explicit_revision_still_allows_reading_candidate(monkeypatch):
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = _script_state()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, ["scene", "show", "project-1", "scene-1", "--revision", "2", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["revision_id"] == "scene_id-candidate-2"
    assert payload["status"] == "candidate"
    assert payload["adopted_revision"]["revision_number"] == 1
    assert payload["adopted_human"] is True


def test_chapter_list_book_and_show_share_human_final_state(monkeypatch):
    import cli_anything.scriptnow.scriptnow_cli as cli

    state = _novel_state()
    session = Mock()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    monkeypatch.setattr(cli, "_novel_state", lambda *_args: state)
    runner = CliRunner()

    listed = runner.invoke(main, ["chapter", "list", "project-1", "--json"])
    assert listed.exit_code == 0, listed.output
    row = json.loads(listed.output)[0]
    assert row["adopted_revision"] == 1
    assert row["adopted_human"] is True
    assert row["candidate_revisions"] == [3, 2]

    book = runner.invoke(main, ["book", "project-1", "--json"])
    assert book.exit_code == 0, book.output
    book_state = json.loads(book.output)["plan"][0]["state"]
    assert book_state["adopted_revision"] == 1
    assert book_state["adopted_human"] is True
    assert book_state["candidate_revisions"] == [3, 2]

    # chapter show reads the chapter-specific endpoint, not _novel_state.
    session.request.return_value = state["documents"]
    shown = runner.invoke(main, ["chapter", "show", "project-1", "chapter-1", "--json"])
    assert shown.exit_code == 0, shown.output
    payload = json.loads(shown.output)
    assert payload["revision_id"] == "chapter_id-human-1"
    assert payload["adopted_revision"]["revision_number"] == 1
    assert payload["adopted_human"] is True


def test_show_help_documents_adopted_human_default():
    runner = CliRunner()
    assert "adopted/adopted_human" in runner.invoke(main, ["chapter", "show", "--help"]).output
    assert "adopted/adopted_human" in runner.invoke(main, ["scene", "show", "--help"]).output


def test_novel_orchestrate_plan_marks_human_final(monkeypatch):
    import cli_anything.scriptnow.scriptnow_cli as cli

    state = _novel_state()
    state["story_map_candidates"] = [{"id": "storymap-candidate-1", "status": "active", "volumes": []}]
    monkeypatch.setattr(cli, "_novel_state", lambda *_args: state)
    result = CliRunner().invoke(main, ["novel", "orchestrate", "project-1"])
    assert result.exit_code == 0, result.output
    assert '"adopted_revision": 1' in result.output
    assert '"adopted_human": true' in result.output
