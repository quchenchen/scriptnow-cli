from threading import Thread
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import Mock

import pytest
import requests

from cli_anything.scriptnow.utils import browser_login as module
from cli_anything.scriptnow.utils.session import ScriptNowError


@pytest.mark.parametrize('host', ['http://evil.test', 'https://a:b@evil.test', 'https://x.test/path'])
def test_rejects_insecure_or_ambiguous_host(host):
    with pytest.raises(ScriptNowError):
        module.browser_login(host)


def test_browser_callback_exchange_does_not_print_credentials(monkeypatch):
    session = Mock()
    session.api_root = 'https://platform.test/api'
    session.cookies = {}
    response = Mock(status_code=200)
    response.cookies = requests.cookies.cookiejar_from_dict({'sf_access': 'secret-access', 'sf_refresh': 'secret-refresh', 'sf_csrf': 'secret-csrf'})
    session._http.post.return_value = response
    monkeypatch.setattr(module, 'Session', lambda **kwargs: session)
    messages = []
    callback_results = []
    threads = []

    def open_browser(url, **kwargs):
        query = parse_qs(urlsplit(url).query)
        redirect = query['redirect_uri'][0]
        def callback():
            callback_results.append(requests.get(redirect + '?' + urlencode({'state': 'wrong', 'code': 'bad'}), timeout=5).status_code)
            callback_results.append(requests.get(redirect + '?' + urlencode({'state': query['state'][0], 'code': 'private-code'}), timeout=5).status_code)
        thread = Thread(target=callback)
        thread.start()
        threads.append(thread)
        return True

    monkeypatch.setattr(module.webbrowser, 'open', open_browser)
    assert module.browser_login('https://platform.test', timeout=5, notify=messages.append) is session
    for thread in threads:
        thread.join(5)
    assert callback_results == [400, 200]
    payload = session._http.post.call_args.kwargs['json']
    assert payload['code'] == 'private-code'
    assert len(payload['verifier']) >= 43
    session.save.assert_called_once()
    assert all(secret not in '\n'.join(messages) for secret in ['private-code', 'secret-access', 'secret-refresh', payload['verifier']])
