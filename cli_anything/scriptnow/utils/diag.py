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


def _sanitize_args(args: tuple[str, ...]) -> list[str]:
    """保留命令名与位置参数，剔除长内容与明显敏感值。"""
    out: list[str] = []
    for arg in args:
        low = str(arg).lower()
        # 敏感前缀直接脱敏
        if any(low.startswith(prefix) for prefix in (
            "--password", "--token", "x-decision-token", "--evidence",
        )):
            out.append(arg.split("=")[0] + "=<redacted>")
            continue
        # 超长值（正文/JSON）截断
        if len(str(arg)) > 120:
            out.append(str(arg)[:60] + "…<truncated>")
            continue
        out.append(str(arg))
    return out


def _error_code(detail: str) -> str:
    """从错误详情提取 machine-readable 错误码，便于 CLI 给专属指引。

    规则：优先识别已知模式 → CLI_<AREA>_<KIND>；未知 → CLI_UNKNOWN。
    """
    d = str(detail)
    if "已不可采纳" in d or "candidate is unavailable" in d:
        return "CLI_ADOPT_REVISION_UNAVAILABLE"
    if "该版本（rev" in d and "无需重复采纳" in d:
        return "CLI_ADOPT_ALREADY_FINALIZED"
    if "superseded" in d or "已过期" in d:
        return "CLI_ADOPT_SUPERSEDED"
    if "定稿必须由人亲自决策" in d:
        return "CLI_ADOPT_REQUIRES_HUMAN"
    if "登录状态已失效" in d or "401" in d:
        return "CLI_AUTH_EXPIRED"
    if "decision token" in d or "授权令牌" in d:
        return "CLI_TOKEN_INVALID"
    if "No such option" in d:
        return "CLI_USAGE_UNKNOWN_OPTION"
    if "No such command" in d:
        return "CLI_USAGE_UNKNOWN_COMMAND"
    if d.startswith("HTTP 409"):
        return "CLI_HTTP_409"
    if d.startswith("HTTP 4"):
        return "CLI_HTTP_4XX"
    if d.startswith("HTTP 5"):
        return "CLI_HTTP_5XX"
    if "network error" in d or "Max retries" in d or "Connection" in d:
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
            "detail": str(detail)[:300],
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
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
    except Exception:
        return []


def clear_errors() -> None:
    """清空错误日志。"""
    try:
        _errors_path().unlink(missing_ok=True)
    except Exception:
        pass
