import json
from types import SimpleNamespace

from click.testing import CliRunner

from cli_anything.scriptnow import scriptnow_cli as cli


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if kwargs.get("raw"):
            return SimpleNamespace(content=b"PKsynthetic-docx", headers={"X-ScriptNow-Baseline": "current"})
        return {"id": "candidate-1", "status": "candidate"}


def test_translate_propose_sends_frozen_contract_and_attempt(tmp_path, monkeypatch):
    payload = tmp_path / "source.json"
    payload.write_text(json.dumps({"story_summary": "A promise changes a family."}), encoding="utf-8")
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({
        "project_id": "project-1", "kind": "source_story_model",
        "dependency_versions": {}, "missing_prerequisites": [],
    }), encoding="utf-8")
    session = FakeSession()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(cli.main, [
        "translate", "propose", "project-1", "source_story_model", f"@{payload}",
        "--contract", f"@{contract}", "--execution-token", "attempt-1",
        "--request-key", "save-1", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert len(session.calls) == 1
    method, path, options = session.calls[0]
    assert method == "POST"
    assert path == "/cross-cultural-recreations/by-project/project-1/candidates/source_story_model"
    assert options["headers"]["X-Creative-Attempt"] == "attempt-1"
    assert options["json_body"]["expected_dependencies"] == {}
    assert options["json_body"]["request_key"] == "save-1"


def test_translate_legacy_command_explains_local_delivery(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(cli.main, ["translate", "analyze-source", "project-1", "--json"])
    assert result.exit_code != 0
    assert "本地" in result.output
    assert session.calls == []


def test_translate_state_stays_read_only_when_attempt_env_is_present(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    result = CliRunner().invoke(
        cli.main, ["translate", "state", "project-1", "--json"],
        env={"SCRIPTNOW_CREATIVE_ATTEMPT": "ea1.synthetic.token"},
    )
    assert result.exit_code == 0, result.output
    assert session.calls == [("GET", "/cross-cultural-recreations/by-project/project-1", {})]


def test_translate_unit_review_revision_manuscript_and_export(tmp_path, monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    runner = CliRunner()
    revision = tmp_path / "revision.json"
    revision.write_text(json.dumps({"title": "Revised", "target_language_draft": "New prose"}), encoding="utf-8")
    for args in (
        ["translate", "state", "project-1", "--json"],
        ["translate", "contract", "project-1", "source_story_model", "--json"],
        ["translate", "review-unit", "project-1", "unit-1", "--json"],
        ["translate", "adopt", "project-1", "unit-1", "--kind", "unit",
         "--review-token", "human-token", "--json"],
        ["translate", "revise-unit", "project-1", "unit-1", f"@{revision}", "--request-key", "revision-1", "--json"],
        ["translate", "manuscript", "project-1", "--work-package-key", "1", "--scale-plan-id", "plan-1", "--json"],
    ):
        result = runner.invoke(cli.main, args)
        assert result.exit_code == 0, result.output
    assert session.calls[0][0] == "GET" and session.calls[0][1].endswith("/by-project/project-1")
    assert session.calls[1][1].endswith("/contract/source_story_model")
    assert session.calls[2][1].endswith("/production-units/unit-1/review")
    assert session.calls[3][2]["headers"]["X-Review-Token"] == "human-token"
    assert session.calls[4][2]["json_body"]["idempotency_key"] == "revision-1"
    assert session.calls[5][2]["params"] == {"work_package_keys": ["1"], "scale_plan_id": "plan-1"}
    target = tmp_path / "recreation.docx"
    exported = runner.invoke(cli.main, ["translate", "export", "project-1", "-o", str(target), "--json"])
    assert exported.exit_code == 0, exported.output
    assert target.read_bytes() == b"PKsynthetic-docx"
    assert json.loads(exported.output)["baseline"] == "current"


def test_translate_method_is_offline_and_self_contained(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline method must not access session or network")
    monkeypatch.setattr(cli, "_session", forbidden)
    monkeypatch.setattr(cli, "maybe_warn_in_background", forbidden)
    for options in (["--json"], []):
        result = CliRunner().invoke(cli.main, ["translate", "method", "--section", "all", *options])
        assert result.exit_code == 0, result.output
        assert "webnovel-localization" in result.output
        if options:
            payload = json.loads(result.output)
            assert payload["platform_required"] is False
            assert set(payload["documents"]) == {"SKILL.md", "references/method.md",
                "references/continuity.md", "references/review.md", "references/platform.md", "references/research.md", "references/world.md"}
            assert all(payload["documents"].values())


def test_translate_review_preview_uses_saved_server_candidate(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(cli, "_session", lambda _ctx: session)
    for kind, resource in (("artifact", "artifacts"), ("unit", "production-units")):
        result = CliRunner().invoke(cli.main, ["translate", "review-preview", "p1", "c1",
                                              "--kind", kind, "--json"])
        assert result.exit_code == 0, result.output
        assert session.calls[-1] == ("POST",
            f"/cross-cultural-recreations/by-project/p1/{resource}/c1/review-preview", {"write": True})
