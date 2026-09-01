"""Public CLI tests for the human-in-the-loop review packet commands.

These tests deliberately mock the platform boundary.  The CLI owns the
human-readable preview and digest calculation; the platform owns the packet
state and the one-time credential.  Keeping those responsibilities explicit
here protects the conversation-first flow from accidentally becoming a
second, mandatory UI workflow.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main


def _write_json(tmp_path, name: str, payload: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return f"@{path}"


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def test_review_preview_shows_content_registers_digest_and_returns_optional_url(
    monkeypatch, tmp_path
):
    session = Mock()
    session.base_url = "https://sn.example"
    session.request.return_value = {
        "packet_id": "packet-1",
        "review_path": "/projects/p1/reviews/packet-1",
        "status": "previewed",
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    content = {"summary": "主角在雨夜找到录音带", "beats": ["打开录音机"]}
    file_arg = _write_json(tmp_path, "candidate.json", content)

    result = CliRunner().invoke(
        main,
        ["review", "preview", "p1", "rough_outline_phase", "act-1", file_arg, "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["packet_id"] == "packet-1"
    assert payload["review_url"] == "https://sn.example/projects/p1/reviews/packet-1"
    call = session.request.call_args
    assert call.args[:2] == ("POST", "/creative-reviews/preview")
    assert call.kwargs["write"] is True
    body = call.kwargs["json_body"]
    assert body["project_id"] == "p1"
    assert body["resource_kind"] == "rough_outline_phase"
    assert body["resource_id"] == "act-1"
    assert body["content_digest"] == _digest(content)
    assert body["preview"]["content"] == content
    assert "保留 / 调整 / 换方向" in body["preview"]["human_action"]


def test_review_preview_human_mode_keeps_full_content_in_conversation(monkeypatch, tmp_path):
    session = Mock()
    session.base_url = "http://127.0.0.1:5173"
    session.request.return_value = {
        "packet_id": "packet-2",
        "review_path": "/projects/p1/reviews/packet-2",
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    content = {"title": "第一阶段", "text": "她把钥匙放回信封。"}

    result = CliRunner().invoke(
        main,
        [
            "review",
            "preview",
            "p1",
            "direction",
            "main",
            _write_json(tmp_path, "direction.json", content),
            "--title",
            "方向草案",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "方向草案" in result.output
    assert "她把钥匙放回信封" in result.output
    assert "一键查看" in result.output


def test_review_preview_normalizes_plain_text_file_whitespace(monkeypatch, tmp_path):
    session = Mock()
    session.base_url = "https://sn.example"
    session.request.return_value = {
        "packet_id": "packet-text",
        "review_path": "/projects/p1/reviews/packet-text",
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    path = tmp_path / "outline.txt"
    path.write_text("  精确梗概正文。\n", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        ["review", "preview", "p1", "synopsis_outline", "p1", f"@{path}", "--json"],
    )

    assert result.exit_code == 0, result.output
    body = session.request.call_args.kwargs["json_body"]
    assert body["preview"]["content"] == {"text": "精确梗概正文。"}
    assert body["content_digest"] == _digest({"text": "精确梗概正文。"})


def test_review_status_reads_human_feedback_without_a_second_user_message(monkeypatch):
    session = Mock()
    session.request.return_value = {
        "packet_id": "packet-1",
        "status": "revoked",
        "content_digest": "a" * 64,
        "evidence": "保留人物关系，但把结尾改成开放式。",
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, ["review", "status", "packet-1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "revoked"
    assert payload["evidence"].startswith("保留人物关系")
    session.request.assert_called_once_with("GET", "/creative-reviews/packet-1")


def test_review_status_translates_active_packet_for_human(monkeypatch):
    session = Mock()
    session.request.return_value = {
        "packet_id": "packet-1",
        "status": "active",
        "content_digest": "b" * 64,
        "evidence": "采用这一版，继续下一阶段。",
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, ["review", "status", "packet-1"])

    assert result.exit_code == 0, result.output
    assert "已确认保留，可提交" in result.output
    assert "采用这一版，继续下一阶段" in result.output
    assert "bbbbbbbbbbbb" in result.output


def test_review_confirm_records_explicit_human_words(monkeypatch):
    session = Mock()
    session.request.return_value = {
        "packet_id": "packet-1",
        "status": "active",
        "expires_in": 900,
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(
        main,
        [
            "review",
            "confirm",
            "packet-1",
            "--decision",
            "retain",
            "--evidence",
            "采用这一版，继续下一阶段。",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert session.request.call_args.kwargs["json_body"] == {
        "decision": "retain",
        "evidence": "采用这一版，继续下一阶段。",
    }


def test_review_claim_is_agent_only_credential_handoff(monkeypatch):
    session = Mock()
    session.request.return_value = {
        "packet_id": "packet-1",
        "token": "one-time-token",
        "expires_in": 900,
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, ["review", "claim", "packet-1", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["token"] == "one-time-token"
    session.request.assert_called_once_with(
        "POST", "/creative-reviews/packet-1/claim", write=True
    )


def test_candidate_preview_uses_canonical_platform_candidate(monkeypatch):
    session = Mock()
    session.base_url = "https://sn.example"
    session.request.return_value = {
        "packet_id": "packet-candidate",
        "review_path": "/projects/p1/reviews/packet-candidate",
        "preview": {"content": {"title": "灯塔回声", "concept": "她决定公开录音。"}},
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(main, [
        "review", "candidate-preview", "script", "p1",
        "story_core_candidate", "candidate-1", "--json",
    ])

    assert result.exit_code == 0, result.output
    body = session.request.call_args.kwargs["json_body"]
    assert body == {
        "resource_kind": "story_core_candidate",
        "candidate_id": "candidate-1",
        "title": "规划候选审阅",
    }
    assert session.request.call_args.args[1] == (
        "/script/projects/p1/creative-reviews/planning-candidate-preview"
    )
    assert json.loads(result.output)["review_url"].endswith("packet-candidate")


@pytest.mark.parametrize(
    ("medium", "kind", "payload", "expected_resource"),
    [
        ("script", "outline", "这是同一个未经修改的故事梗概文本。", "synopsis_outline"),
        ("script", "cores", {"drafts": [{"title": "方向"}]}, "story_cores"),
        ("novel", "blueprint", {"anchors": [{"id": "world:a"}]}, "blueprint"),
        (
            "script",
            "blueprint-extension",
            {"anchors": [{"id": "event:new", "kind": "event"}]},
            "blueprint_extension",
        ),
        ("script", "storymap", {"episodes": [{"id": "episode-1"}]}, "storymap"),
        ("novel", "storymap", {"volumes": [{"id": "volume-1"}]}, "storymap"),
    ],
)
def test_propose_preview_derives_review_scope(
    monkeypatch, tmp_path, medium, kind, payload, expected_resource
):
    session = Mock()
    session.base_url = "https://sn.example"
    session.request.return_value = {
        "packet_id": "packet-1",
        "review_path": "/projects/p1/reviews/packet-1",
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        main,
        ["review", "propose-preview", medium, "p1", kind, str(candidate), "--json"],
    )
    assert result.exit_code == 0, result.output
    body = session.request.call_args.kwargs["json_body"]
    assert body["resource_kind"] == expected_resource
    assert body["resource_id"] == "p1"
    if kind == "outline":
        assert body["preview"]["content"] == {"text": payload}
    response = json.loads(result.output)
    assert "token 字段" in " ".join(response["next_steps"])


def test_review_help_exposes_conversation_first_commands():
    output = CliRunner().invoke(main, ["review", "--help"]).output
    assert "preview" in output
    assert "status" in output
    assert "confirm" in output
    assert "claim" in output
    assert "candidate-preview" in output


@pytest.mark.parametrize("medium", ["novel", "script"])
def test_outline_adopt_preview_derives_candidate_scope(monkeypatch, medium):
    session = Mock()
    session.base_url = "https://sn.example"
    session.request.return_value = {
        "packet_id": "packet-outline",
        "review_path": "/projects/p1/reviews/packet-outline",
    }
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(
        main, [medium, "outline-adopt-preview", "p1", "--json"]
    )
    assert result.exit_code == 0, result.output
    body = session.request.call_args.kwargs["json_body"]
    assert body == {
        "resource_kind": "synopsis_outline_candidate",
        "candidate_id": "p1",
        "title": "故事梗概候选审阅",
    }
    assert f"/{medium}/projects/p1/creative-reviews/planning-candidate-preview" == session.request.call_args.args[1]
    assert "token 字段" in " ".join(json.loads(result.output)["next_steps"])
