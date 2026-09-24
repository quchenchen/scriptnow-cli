"""dsh execution claims may save candidates but never adopt them."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main


def test_run_claim_returns_a_scoped_attempt(monkeypatch) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {
        "run_id": "run-1", "operation_id": "op-1", "attempt_id": "attempt-1",
        "generation": 1, "state_version": 1, "token": "ea1.attempt-1.signature",
    }
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    monkeypatch.setenv("DSH_SESSION_ID", "dsh-session-1")
    result = CliRunner().invoke(main, [
        "run", "claim", "project-1", "scene", "scene-1",
        "--task-key", "write-scene", "--attempt-key", "first-try", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["attempt_id"] == "attempt-1"
    call = session.request.call_args
    assert call.args == ("POST", "/projects/project-1/execution-attempts/claim")
    assert call.kwargs["json_body"]["domain"] == "script"
    assert call.kwargs["json_body"]["resource_id"] == "scene-1"
    assert call.kwargs["json_body"]["engine_session_id"] == "dsh-session-1"


def test_run_renew_keeps_the_same_attempt_and_sends_its_credential(monkeypatch) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {
        "attempt_id": "attempt-1", "state_version": 2,
        "expires_at": "2026-09-23T16:00:00+00:00", "status": "active",
    }
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, [
        "run", "renew", "project-1", "attempt-1",
        "--execution-token", "ea1.attempt-1.signature",
        "--state-version", "1", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["state_version"] == 2
    call = session.request.call_args
    assert call.args == ("POST", "/projects/project-1/execution-attempts/attempt-1/renew")
    assert call.kwargs["headers"] == {"X-Creative-Attempt": "ea1.attempt-1.signature"}
    assert call.kwargs["json_body"] == {"expected_state_version": 1}


def test_stop_status_probes_without_resending_cancel(monkeypatch) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {"cancel_signal_sent": False, "engine_stopped": True}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, [
        "run", "stop-status", "project-1", "attempt-1",
        "--operation-id", "operation-1", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["engine_stopped"] is True
    call = session.request.call_args
    assert call.args == (
        "POST", "/projects/project-1/execution-attempts/attempt-1/stop-status",
    )
    assert call.kwargs["json_body"] == {"operation_id": "operation-1"}


@pytest.mark.parametrize("medium,key", [("novel", "volumes"), ("script", "episodes")])
def test_direct_rebuild_submits_one_scoped_storymap_candidate(
    monkeypatch, tmp_path, medium: str, key: str,
) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.side_effect = lambda method, _path, **_kwargs: (
        {"story_map": {"version": 1}} if method == "GET"
        else {"id": "candidate-1", "status": "active"}
    )
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    path = tmp_path / "rebuild.json"
    path.write_text(json.dumps({key: [{"id": "replacement-1", "scenes": []}]}))
    result = CliRunner().invoke(main, [
        medium, "propose", "project-1", "storymap", str(path),
        "--execution-token", "ea1.attempt.signature", "--rebuild-direct", "--json",
    ])
    assert result.exit_code == 0, result.output
    post = next(call for call in session.request.call_args_list if call.args[0] == "POST")
    assert post.args[1] == f"/{medium}/projects/project-1/story-map/propose?rebuild_direct=true"
    assert post.kwargs["headers"] == {"X-Creative-Attempt": "ea1.attempt.signature"}


@pytest.mark.parametrize("medium", ["novel", "script"])
def test_synopsis_propose_retries_with_the_same_execution_identity(monkeypatch, medium: str) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.delenv("SCRIPTNOW_CREATIVE_ATTEMPT", raising=False)
    session = Mock()
    session.request.return_value = {
        "id": "synopsis-1", "project_id": "project-1",
        "content": "她找到录音带后决定公开证据。", "status": "candidate", "version": 1,
    }
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    args = [
        medium, "outline", "project-1", "--text", "她找到录音带后决定公开证据。",
        "--execution-token", "ea1.attempt-1.signature", "--json",
    ]
    first = CliRunner().invoke(main, args)
    second = CliRunner().invoke(main, args)
    assert first.exit_code == second.exit_code == 0, first.output + second.output
    calls = session.request.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["json_body"]["idempotency_key"] == calls[1].kwargs["json_body"]["idempotency_key"]
    assert calls[0].kwargs["headers"] == {"X-Creative-Attempt": "ea1.attempt-1.signature"}


def test_scene_propose_uses_execution_grant_without_submit_review(monkeypatch, tmp_path) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.delenv("SCRIPTNOW_CREATIVE_ATTEMPT", raising=False)
    session = Mock()
    session.request.return_value = {"id": "candidate-1", "status": "candidate"}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    path = tmp_path / "scene.json"
    path.write_text(json.dumps({"blocks": [
        {"para_id": "s1", "type": "slugline", "text": "INT. ROOM - DAY"},
        {"para_id": "s2", "type": "action", "text": "She opens the letter."},
    ]}), encoding="utf-8")
    result = CliRunner().invoke(main, [
        "scene", "propose", "project-1", "scene-1", "--file", str(path),
        "--execution-token", "ea1.attempt-1.signature",
        "--material-digest", "d" * 64, "--json",
    ])
    assert result.exit_code == 0, result.output
    call = session.request.call_args
    assert call.kwargs["headers"] == {
        "X-Creative-Attempt": "ea1.attempt-1.signature",
        "X-Creative-Material-Digest": "d" * 64,
    }
    assert call.kwargs["json_body"]["source"] == "agent"
    assert json.loads(result.output)["status"] == "candidate"


def test_chapter_propose_uses_execution_grant_without_submit_review(monkeypatch, tmp_path) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.delenv("SCRIPTNOW_CREATIVE_ATTEMPT", raising=False)
    session = Mock()
    session.request.return_value = {"id": "candidate-1", "status": "candidate"}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    path = tmp_path / "chapter.json"
    path.write_text(json.dumps({"blocks": [
        {"block_id": "c1", "type": "heading", "text": "第一章"},
        {"block_id": "c2", "type": "prose", "text": "她拆开信封。"},
    ]}, ensure_ascii=False), encoding="utf-8")
    result = CliRunner().invoke(main, [
        "chapter", "propose", "project-1", "chapter-1", "--file", str(path),
        "--execution-token", "ea1.attempt-1.signature",
        "--material-digest", "d" * 64, "--json",
    ])
    assert result.exit_code == 0, result.output
    call = session.request.call_args
    assert call.kwargs["headers"] == {
        "X-Creative-Attempt": "ea1.attempt-1.signature",
        "X-Creative-Material-Digest": "d" * 64,
    }
    assert call.kwargs["json_body"]["source"] == "agent"


def test_script_planning_propose_uses_one_request_identity_on_retry(monkeypatch, tmp_path) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.delenv("SCRIPTNOW_CREATIVE_ATTEMPT", raising=False)
    session = Mock()
    session.request.return_value = [{"id": "core-1", "status": "active"}]
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    path = tmp_path / "core.json"
    path.write_text(json.dumps({"drafts": [{
        "title": "A choice", "concept": "A witness exposes herself to save a friend."
    }]}), encoding="utf-8")
    args = [
        "script", "propose", "project-1", "cores", str(path),
        "--execution-token", "ea1.attempt-1.signature", "--json",
    ]
    first = CliRunner().invoke(main, args)
    second = CliRunner().invoke(main, args)
    assert first.exit_code == second.exit_code == 0, first.output + second.output
    calls = session.request.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["json_body"]["idempotency_key"] == calls[1].kwargs["json_body"]["idempotency_key"]
    assert calls[0].kwargs["headers"] == {"X-Creative-Attempt": "ea1.attempt-1.signature"}
    assert json.loads(first.output)["candidates"][0]["id"] == "core-1"


def test_novel_blueprint_propose_accepts_execution_grant(monkeypatch, tmp_path) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.delenv("SCRIPTNOW_CREATIVE_ATTEMPT", raising=False)
    session = Mock()
    session.request.return_value = {"id": "blueprint-1", "status": "active"}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    path = tmp_path / "blueprint.json"
    path.write_text(json.dumps({"anchors": [{
        "id": "plot:first-choice", "kind": "plot", "name": "First choice",
        "payload": {"description": "She exposes the record and loses her ally."},
    }]}), encoding="utf-8")
    result = CliRunner().invoke(main, [
        "novel", "propose", "project-1", "blueprint", str(path),
        "--execution-token", "ea1.attempt-1.signature", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert session.request.call_args.kwargs["headers"] == {
        "X-Creative-Attempt": "ea1.attempt-1.signature"
    }


def test_script_rough_outline_can_be_submitted_as_one_dsh_candidate(monkeypatch, tmp_path) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.delenv("SCRIPTNOW_CREATIVE_ATTEMPT", raising=False)
    session = Mock()
    session.request.return_value = {"id": "rough-1", "status": "active"}
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    path = tmp_path / "rough.json"
    path.write_text(json.dumps({"phases": [{
        "ordinal": 1, "phase_key": "one", "phase_title_zh": "开端",
        "range_start": 1, "range_end": 1,
        "summary": "她发现录音带并选择公开证据。",
        "key_beats": [{"title": "公开", "description": "她把证据交给证人。"}],
    }]}, ensure_ascii=False), encoding="utf-8")
    result = CliRunner().invoke(main, [
        "script", "propose", "project-1", "rough_outline", str(path),
        "--execution-token", "ea1.attempt-1.signature", "--json",
    ])
    assert result.exit_code == 0, result.output
    call = session.request.call_args
    assert call.args == ("POST", "/script/projects/project-1/rough-outline/propose")
    assert call.kwargs["headers"] == {"X-Creative-Attempt": "ea1.attempt-1.signature"}


@pytest.mark.parametrize("medium", ["novel", "script"])
def test_dsh_bible_propose_saves_a_candidate_instead_of_adopting(monkeypatch, tmp_path, medium: str) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.delenv("SCRIPTNOW_CREATIVE_ATTEMPT", raising=False)
    session = Mock()
    session.request.return_value = {
        "id": "bible-candidate-1", "status": "candidate", "character_key": "character:lin",
    }
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    path = tmp_path / "bible.json"
    path.write_text(json.dumps({"bibles": [{
        "character_key": "character:lin", "display_name": "林澄",
        "profile": {"summary": "她在档案室工作，必须决定是否公开母亲隐瞒的证据。"},
    }]}, ensure_ascii=False), encoding="utf-8")
    result = CliRunner().invoke(main, [
        medium, "propose", "project-1", "bibles", str(path),
        "--execution-token", "ea1.attempt-1.signature", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["candidate_id"] == "bible-candidate-1"
    call = session.request.call_args
    assert call.args == ("POST", f"/{medium}/projects/project-1/characters/bibles/propose")
    assert call.kwargs["headers"] == {"X-Creative-Attempt": "ea1.attempt-1.signature"}


def test_selected_skill_command_reads_full_project_scoped_materials(monkeypatch) -> None:
    import cli_anything.scriptnow.scriptnow_cli as cli

    session = Mock()
    session.request.return_value = {
        "project_id": "project-1", "selected_count": 1, "loaded_count": 1,
        "material_digest": "digest", "materials": [{
            "key": "builtin:script-write", "name": "script-write",
            "version": "1", "digest": "skill-digest",
            "instructions": "Write concrete scenes.", "references": {},
        }],
    }
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, [
        "skill", "selected", "project-1", "--unit-id", "scene-1",
        "--role", "writer", "--stage", "writing", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["materials"][0]["instructions"] == "Write concrete scenes."
    assert session.request.call_args.args == (
        "GET", "/projects/project-1/creative-skill-plan/materials",
    )
