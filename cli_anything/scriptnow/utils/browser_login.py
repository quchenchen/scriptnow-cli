"""System-browser login. Never accept or print account passwords or tokens."""
import base64
import hashlib
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from .session import ScriptNowError, Session, _config_path


def browser_login(host: str, *, timeout: int = 180, notify=print) -> Session:
    origin = urlsplit(host)
    if (origin.scheme not in {"http", "https"} or not origin.netloc or origin.username
            or origin.password or origin.query or origin.fragment or origin.path not in {"", "/"}
            or (origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise ScriptNowError("登录地址必须为 HTTPS 平台地址；仅本机开发允许 HTTP")
    base = host.rstrip("/")
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            denied = query.get("error") == ["access_denied"]
            valid = (parsed.path == "/callback" and query.get("state") == [state]
                     and (denied or (len(query.get("code", [])) == 1 and len(query["code"][0]) <= 4096)))
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if valid:
                if denied:
                    result["error"] = "access_denied"
                else:
                    result["code"] = query["code"][0]
            message = "已取消登录，请返回创作助手。" if valid and denied else ("已收到确认，请返回创作助手继续。" if valid else "无效请求，请重新从 CLI 发起登录。")
            self.wfile.write(message.encode())

    with ThreadingHTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/callback"
        url = base + "/cli/authorize?" + urlencode({"challenge": challenge, "state": state, "redirect_uri": redirect})
        notify("请在系统浏览器中登录并确认授权。不要在对话中输入密码。")
        notify(url)
        try:
            webbrowser.open(url, new=2)
        except webbrowser.Error:
            pass  # The displayed URL is a safe browser fallback, never a password fallback.
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
        if result.get("error"):
            raise ScriptNowError("已取消浏览器授权；没有更改原有登录状态")
        if "code" not in result:
            raise ScriptNowError("浏览器授权超时；请在运行 CLI 的同一台电脑上重新登录，不要向 Agent 提供密码")
    session = Session(base_url=base)
    try:
        response = session._http.post(f"{session.api_root}/auth/cli/exchange",
                                      json={"code": result["code"], "verifier": verifier, "redirect_uri": redirect},
                                      timeout=30, allow_redirects=False)
    except Exception as error:
        raise ScriptNowError("授权结果交换失败，请重新运行浏览器登录") from error
    if response.status_code != 200:
        raise ScriptNowError("平台未支持浏览器登录或授权已失效，请更新平台或重新登录；不会回退到密码输入")
    for cookie in response.cookies:
        if cookie.name in {"sf_access", "sf_refresh", "sf_csrf"}:
            session.cookies[cookie.name] = cookie.value
    session.csrf = session.cookies.get("sf_csrf", "")
    if not all(session.cookies.get(key) for key in ("sf_access", "sf_refresh", "sf_csrf")):
        raise ScriptNowError("平台没有返回完整授权会话；未保存登录状态")
    session.save(_config_path())
    return session
