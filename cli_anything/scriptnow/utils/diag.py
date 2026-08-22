"""CLI 诊断日志与错误遥测：自动记录失败命令，供针对性修复。

设计目标：
- 零打扰：命令失败自动写一条结构化记录，用户无感
- 可诊断：每条含 命令 / 参数（脱敏）/ 错误码 / 详情 / 时间 / CLI 版本
- 可上报：`scriptnow feedback` 收集诊断包发给平台
- 可轮转：只保留最近 N 条，不无限增长
- 隐私：绝不记录密码、令牌、Cookie、正文内容
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


MAX_ERROR_ENTRIES = 50  # 轮转上限：只保留最近 50 条


def _config_dir() -> Path:
    override = os.environ.get("SCRIPTNOW_CLI_CONFIG")
    if override:
        return Path(override).parent
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "scriptnow-cli"


def _errors_path() -> Path:
    return _config_dir() / "errors.jsonl"


# ── 脱敏：从命令参数里剔除敏感值（密码/令牌/CSRF/正文） ──


_SENSITIVE_OPTIONS = ("--password", "--token", "x-decision-token", "--evidence", "--csrf", "--email")


def _sanitize_args(args: tuple[str, ...]) -> list[str]:
    """保留命令名与位置参数，剔除长内容与明显敏感值。

    敏感选项（--password/--token/--evidence 等）连同其值一起脱敏：
    `--password secret` → `--password=<redacted>`；等号形式同样处理。
    超长值截断。绝不记录密码/令牌/Cookie/正文。
    """
    out: list[str] = []
    skip_next = False
    for arg in args:
        low = str(arg).lower()
        if skip_next:
            skip_next = False
            out.append("<redacted>")
            continue
        # 等号形式：--password=secret
        if "=" in low:
            opt, _, val = low.partition("=")
            if any(opt == o for o in _SENSITIVE_OPTIONS):
                out.append(f"{opt}=<redacted>")
                continue
        # 分离形式：--password secret
        if any(low == o or low.startswith(o + "=") for o in _SENSITIVE_OPTIONS):
            out.append(low.split("=")[0] + "=<redacted>")
            skip_next = True
            continue
        # 超长值（正文/JSON）截断
        if len(str(arg)) > 120:
            out.append(str(arg)[:60] + "…<truncated>")
            continue
        out.append(str(arg))
    return out


def _sanitize_detail(detail: str) -> str:
    """净化错误详情：剔除可能被服务端回显的敏感片段（token/cookie 形态）。"""
    import re as _re

    text = str(detail)
    # JWT（eyJ...两段点号）与常见令牌形态
    text = _re.sub(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "<jwt-redacted>", text)
    text = _re.sub(r"(?i)(token|csrf|cookie)[=: ]+[A-Za-z0-9_-]{12,}", r"\1=<redacted>", text)
    return text[:300]


def _error_code(detail: str) -> str:
    """从错误详情提取 machine-readable 错误码，便于 CLI 给专属指引。

    规则：优先识别已知模式 → CLI_<AREA>_<KIND>；未知 → CLI_UNKNOWN。
    """
    d = str(detail)
    dl = d.lower()
    if "已不可采纳" in d or "candidate is unavailable" in dl:
        return "CLI_ADOPT_REVISION_UNAVAILABLE"
    if "该版本（rev" in d and "无需重复采纳" in d:
        return "CLI_ADOPT_ALREADY_FINALIZED"
    if "superseded" in dl or "已过期" in d:
        return "CLI_ADOPT_SUPERSEDED"
    if "定稿必须由人亲自决策" in d:
        return "CLI_ADOPT_REQUIRES_HUMAN"
    if "登录状态已失效" in d or "401" in dl:
        return "CLI_AUTH_EXPIRED"
    if "decision token" in dl or "授权令牌" in d:
        return "CLI_TOKEN_INVALID"
    if "No such option" in d:
        return "CLI_USAGE_UNKNOWN_OPTION"
    if "No such command" in d:
        return "CLI_USAGE_UNKNOWN_COMMAND"
    if dl.startswith("http 409"):
        return "CLI_HTTP_409"
    if dl.startswith("http 4"):
        return "CLI_HTTP_4XX"
    if dl.startswith("http 5"):
        return "CLI_HTTP_5XX"
    if "network error" in dl or "max retries" in dl or "connection" in dl:
        return "CLI_NETWORK"
    return "CLI_UNKNOWN"


def record_error(*, command: str, args: tuple[str, ...], detail: str) -> str:
    """记录一条失败命令（自动轮转）。返回错误码。"""
    try:
        path = _errors_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": int(time.time()),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "command": command,
            "args": _sanitize_args(args),
            "error_code": _error_code(detail),
            "detail": _sanitize_detail(detail),
        }
        # 追加 + 轮转（保留最近 N 条）
        lines = []
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
        lines.append(json.dumps(entry, ensure_ascii=False))
        lines = lines[-MAX_ERROR_ENTRIES:]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return entry["error_code"]
    except Exception:
        return "CLI_UNKNOWN"  # 记录失败不影响主流程


def recent_errors(limit: int = 20) -> list[dict[str, object]]:
    """读取最近 N 条错误记录（供 doctor 与 feedback 使用）。"""
    path = _errors_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            # 单条损坏跳过（不整体失败），保留其余
            continue
    return out


def clear_errors() -> bool:
    """清空错误日志。返回是否成功（失败不静默）。"""
    try:
        _errors_path().unlink(missing_ok=True)
        return True
    except Exception:
        return False
