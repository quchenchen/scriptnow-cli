from unittest.mock import Mock
from io import BytesIO
from types import SimpleNamespace

from cli_anything.scriptnow.utils.session import Session
from cli_anything.scriptnow.utils.session import ScriptNowError
import pytest


def test_request_preserves_custom_headers_and_adds_csrf() -> None:
    response = Mock(status_code=204, cookies=[], headers={})
    http = Mock()
    http.request.return_value = response
    session = Session(base_url="https://example.test", csrf="csrf-token", _http=http)

    session.request(
        "POST",
        "/decision",
        write=True,
        headers={"X-Decision-Token": "decision-token"},
    )

    sent = http.request.call_args.kwargs["headers"]
    assert sent["X-CSRF-Token"] == "csrf-token"
    assert sent["X-Decision-Token"] == "decision-token"
    assert sent["X-ScriptNow-Client"] == "scriptnow-cli"


def test_request_rejects_cli_below_server_minimum() -> None:
    response = Mock(
        status_code=200,
        cookies=[],
        headers={
            "X-ScriptNow-Minimum-CLI-Version": "9.0.0",
            "X-ScriptNow-API-Contract": "future-contract",
        },
    )
    http = Mock()
    http.request.return_value = response
    session = Session(base_url="https://example.test", _http=http)

    with pytest.raises(ScriptNowError, match="最低需要 9.0.0"):
        session.request("GET", "/projects")


def test_multipart_file_is_rewound_before_refresh_retry(tmp_path, monkeypatch) -> None:
    first = Mock(status_code=401, cookies=[], headers={})
    second = Mock(status_code=200, cookies=[], headers={})
    refresh_cookie = SimpleNamespace(name="sf_csrf", value="csrf-rotated")
    refresh = Mock(status_code=200, cookies=[refresh_cookie], headers={})
    http = Mock()
    sent_contents: list[bytes] = []
    responses = iter([first, second])

    def request(*args, **kwargs):
        del args
        sent_contents.append(kwargs["files"]["file"][1].read())
        return next(responses)

    http.request.side_effect = request
    http.post.return_value = refresh
    session = Session(
        base_url="https://example.test",
        csrf="csrf-token",
        cookies={"sf_refresh": "refresh-token"},
        _http=http,
    )
    import cli_anything.scriptnow.utils.session as session_module

    monkeypatch.setattr(session_module, "_config_path", lambda: tmp_path / "session.json")
    handle = BytesIO(b"planning-board-bytes")
    result = session.request(
        "POST",
        "/storyboard/projects/p/scenes/s/planning-boards",
        form_data={"layout_key": "3x3"},
        files={"file": ("board.png", handle, "application/octet-stream")},
        write=True,
    )
    assert result is not None
    assert sent_contents == [b"planning-board-bytes", b"planning-board-bytes"]
