import json
import zipfile
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from cli_anything.scriptnow.scriptnow_cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_session(monkeypatch):
    session = Mock()
    proposal_calls = 0

    def request(method, path, **kwargs):
        nonlocal proposal_calls
        if path.endswith("/proposal-contract"):
            return {"skill_snapshots": [
                {"name": "storyboard-import", "version": "1", "digest": "a" * 64, "source": "builtin_catalog"},
                {"name": "storyboard-planning", "version": "1", "digest": "b" * 64, "source": "builtin_catalog"},
                {"name": "suncx", "version": "1", "digest": "c" * 64, "source": "builtin_catalog"},
            ]}
        if path.endswith("/state"):
            return {
                "source": {"id": "source-1"},
                "source_batches": [
                    {"id": "source-1", "batch_no": 1, "episode_start": 1, "episode_end": 1, "parse_status": "ready"}
                ],
                "scenes": [{"id": "scene-1"}],
                "shots": [{"id": "shot-1"}],
            }
        if path.endswith("/propose"):
            proposal_calls += 1
            return {
                "id": "strategy-run-1",
                "candidates": [{"key": "agent-proposal"}],
                "decisions": [] if proposal_calls == 1 else [
                    {"id": "decision-1", "decision": "adopted"}
                ],
            }
        if path.endswith("/decisions"):
            return {"id": "decision-1", "decision": "adopted"}
        if kwargs.get("raw"):
            return Mock(content=b"artifact")
        return {"id": "result-1"}

    session.request.side_effect = request
    import cli_anything.scriptnow.scriptnow_cli as cli

    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    return session


def test_storyboard_propose_backfills_local_candidate_and_optional_adoption(
    runner: CliRunner, fake_session, tmp_path
) -> None:
    candidate = tmp_path / "storyboard.json"
    candidate.write_text(
        json.dumps(
            {"title": "Local storyboard", "scenes": [{"title": "Scene", "shots": []}]}
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        main,
        [
            "storyboard",
            "propose",
            "project-1",
            f"@{candidate}",
            "--source-id",
            "source-1",
            "--adopt",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    calls = fake_session.request.call_args_list
    assert calls[1].args[:2] == (
        "POST",
        "/storyboard/projects/project-1/propose",
    )
    assert calls[1].kwargs["json_body"]["script"]["title"] == "Local storyboard"
    assert calls[2].args[1].endswith("/strategy-runs/strategy-run-1/decisions")
    assert calls[2].kwargs["json_body"]["selected_candidate_key"] == "agent-proposal"
    assert all("analyze" not in call.args[1] for call in calls)


def test_scene_board_upload_uses_session_multipart_and_preserves_server_manifest(
    runner: CliRunner, fake_session, tmp_path
) -> None:
    board = tmp_path / "board.png"
    board.write_bytes(b"png-bytes")
    fake_session.request.side_effect = lambda method, path, **kwargs: {
        "id": "board-1",
        "source": "local_upload",
        "columns": 3,
        "pages": [{"page": 1, "shot_ids": ["shot-1"]}],
        "sha256": "a" * 64,
    }
    result = runner.invoke(main, ["storyboard", "scene-board", "upload", "project-1", "scene-1", str(board), "--json"])
    assert result.exit_code == 0, result.output
    call = fake_session.request.call_args
    assert call.args[:2] == ("POST", "/storyboard/projects/project-1/scenes/scene-1/planning-boards")
    assert call.kwargs["write"] is True
    assert call.kwargs["form_data"] == {"layout_key": "auto", "board_mode": "annotated"}
    assert "file" in call.kwargs["files"]
    assert call.kwargs["files"]["file"][0] == "board.png"


def test_scene_board_generate_and_delete_require_explicit_delete_confirmation(
    runner: CliRunner, fake_session
) -> None:
    fake_session.request.side_effect = lambda method, path, **kwargs: {"status": "done", "job_id": "job-1", "board": {"id": "board-1"}}
    generated = runner.invoke(main, ["storyboard", "scene-board", "generate", "project-1", "scene-1", "--layout", "3x3", "--mode", "seedance_sequence", "--json"])
    assert generated.exit_code == 0, generated.output
    assert fake_session.request.call_args.kwargs["write"] is True
    assert fake_session.request.call_args.kwargs["json_body"] == {"layout_key": "3x3", "board_mode": "seedance_sequence"}
    blocked = runner.invoke(main, ["storyboard", "scene-board", "delete", "project-1", "scene-1", "board-1"])
    assert blocked.exit_code != 0
    assert "--confirm" in blocked.output
    deleted = runner.invoke(main, ["storyboard", "scene-board", "delete", "project-1", "scene-1", "board-1", "--confirm", "--json"])
    assert deleted.exit_code == 0, deleted.output
    assert fake_session.request.call_args.args[:2] == (
        "DELETE", "/storyboard/projects/project-1/scenes/scene-1/planning-boards/board-1"
    )


def test_scene_board_list_marks_stale_boards_and_exposes_layout_mode(runner, fake_session) -> None:
    fake_session.request.side_effect = lambda method, path, **kwargs: {
        "scenes": [{"id": "scene-1", "scene_no": 1, "title": "Market", "planning_boards": [{"id": "b1", "layout_key": "3x3", "board_mode": "annotated", "shot_ids": ["old"]}]}],
        "shots": [{"id": "new", "scene_id": "scene-1"}],
    }
    result = runner.invoke(main, ["storyboard", "scene-board", "inspect", "project-1", "scene-1", "--json"])
    assert result.exit_code == 0, result.output
    assert '"layout_key": "3x3"' in result.output
    assert '"board_mode": "annotated"' in result.output
    assert '"stale": true' in result.output
def test_storyboard_source_import_registers_text_without_platform_generation(
    runner: CliRunner, fake_session, tmp_path
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("场景正文", encoding="utf-8")
    result = runner.invoke(
        main,
        [
            "storyboard",
            "source-import",
            "project-1",
            str(source),
            "--source-kind",
            "script",
        ],
    )
    assert result.exit_code == 0, result.output
    call = fake_session.request.call_args
    assert call.args[1] == "/storyboard/projects/project-1/import"
    assert call.kwargs["json_body"]["source_text"] == "场景正文"


def test_storyboard_source_import_extracts_docx_and_records_episode_range(
    runner: CliRunner, fake_session, tmp_path
) -> None:
    source = tmp_path / "episodes.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>第 1 集</w:t></w:r></w:p><w:p><w:r><w:t>正文</w:t></w:r></w:p></w:body>
    </w:document>"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    result = runner.invoke(
        main,
        [
            "storyboard", "source-import", "project-1", str(source), "--source-kind", "script",
            "--append", "--episode-start", "1", "--episode-end", "1",
        ],
    )

    assert result.exit_code == 0, result.output
    body = fake_session.request.call_args.kwargs["json_body"]
    assert body["source_text"] == "第 1 集\n\n正文"
    assert body["import_mode"] == "append"
    assert (body["episode_start"], body["episode_end"]) == (1, 1)


def test_storyboard_initial_import_rejects_range_not_matching_document(
    runner: CliRunner, fake_session, tmp_path
) -> None:
    source = tmp_path / "initial.txt"
    source.write_text("第 1 集\n正文", encoding="utf-8")
    result = runner.invoke(
        main,
        ["storyboard", "source-import", "project-1", str(source), "--episode-start", "1", "--episode-end", "2"],
    )
    assert result.exit_code != 0
    assert "缺少请求范围内章/集 [2]" in result.output
    fake_session.request.assert_not_called()


def test_storyboard_continuity_records_human_decision(
    runner: CliRunner, fake_session
) -> None:
    result = runner.invoke(
        main,
        [
            "storyboard",
            "continuity",
            "project-1",
            "shot-1",
            "shot-2",
            "--dimension",
            "visual",
            "--intent",
            "保持运动方向",
        ],
    )
    assert result.exit_code == 0, result.output
    call = fake_session.request.call_args
    assert call.args[1].endswith("/shot-links/shot-1/shot-2/manual-decision")
    assert call.kwargs["json_body"]["dimensions"] == {"visual": "导演自主选择"}


def test_storyboard_export_uses_authenticated_session(
    runner: CliRunner, fake_session, tmp_path
) -> None:
    output = tmp_path / "workpaper.pdf"
    result = runner.invoke(
        main,
        [
            "storyboard",
            "export",
            "project-1",
            "--kind",
            "production-pdf",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.read_bytes() == b"artifact"
    assert fake_session.request.call_args.kwargs["raw"] is True


def test_storyboard_propose_discloses_bounded_contract_on_demand(
    runner: CliRunner, fake_session
) -> None:
    result = runner.invoke(main, ["storyboard", "propose", "--help-format"])

    assert result.exit_code == 0, result.output
    assert "Storyboard ScriptOut JSON" in result.output
    assert "Skill 手册" in result.output
    fake_session.request.assert_not_called()


def test_storyboard_propose_retry_uses_stable_content_identity(
    runner: CliRunner, fake_session, tmp_path
) -> None:
    candidate = tmp_path / "storyboard.json"
    candidate.write_text(
        json.dumps({"title": "Stable", "scenes": [{"title": "Scene", "shots": []}]}),
        encoding="utf-8",
    )
    arguments = [
        "storyboard",
        "propose",
        "project-1",
        str(candidate),
        "--source-id",
        "source-1",
    ]

    assert runner.invoke(main, arguments).exit_code == 0
    assert runner.invoke(main, arguments).exit_code == 0
    keys = [
        call.kwargs["json_body"]["idempotency_key"]
        for call in fake_session.request.call_args_list
        if call.args[1].endswith("/propose")
    ]
    assert keys[0] == keys[1]


def test_storyboard_source_preflight_detects_overlap(
    runner: CliRunner, fake_session, tmp_path
) -> None:
    source = tmp_path / "episodes.txt"
    source.write_text("第 1 章\n旧内容\n第 2 章\n新内容", encoding="utf-8")
    result = runner.invoke(
        main,
        ["storyboard", "source-preflight", "project-1", str(source), "--episode-start", "1", "--episode-end", "2", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["pass"] is False
    assert payload["overlap_batches"] == [1]


def test_storyboard_source_revoke_requires_confirmation_and_reads_back(
    runner: CliRunner, fake_session
) -> None:
    denied = runner.invoke(
        main,
        ["storyboard", "source-revoke", "project-1", "source-2", "--reason", "重复"],
    )
    assert denied.exit_code != 0
    fake_session.request.reset_mock()
    accepted = runner.invoke(
        main,
        ["storyboard", "source-revoke", "project-1", "source-2", "--reason", "重复", "--confirm", "--json"],
    )
    assert accepted.exit_code == 0, accepted.output
    assert fake_session.request.call_args_list[0].args[1].endswith("/sources/source-2/revoke")
    assert fake_session.request.call_args_list[1].args[1].endswith("/state")


def test_storyboard_adopt_retry_reuses_existing_decision(
    runner: CliRunner, fake_session, tmp_path
) -> None:
    candidate = tmp_path / "storyboard.json"
    candidate.write_text(
        json.dumps({"title": "Stable", "scenes": [{"title": "Scene", "shots": []}]}),
        encoding="utf-8",
    )
    arguments = [
        "storyboard", "propose", "project-1", str(candidate),
        "--source-id", "source-1", "--adopt", "--json",
    ]
    assert runner.invoke(main, arguments).exit_code == 0
    assert runner.invoke(main, arguments).exit_code == 0
    decision_posts = [
        call for call in fake_session.request.call_args_list
        if call.args[1].endswith("/decisions")
    ]
    assert len(decision_posts) == 1
