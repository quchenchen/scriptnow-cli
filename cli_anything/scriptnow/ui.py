"""scriptnow-cli 界面规范层 —— 轻量 ANSI 着色与排版。

原则：规范、克制、不复杂化。只做着色与对齐，不做 TUI。
颜色默认仅在输出到 TTY 时启用；可用 ``NO_COLOR`` / ``SCRIPTNOW_NO_COLOR``
环境变量或全局 ``--no-color`` 关闭，用 ``SCRIPTNOW_FORCE_COLOR=1`` 强制开启
（管道、CI 或演示场景）。
"""

from __future__ import annotations

import os
import sys

_RESET = "\033[0m"
_BOLD = "\033[1m"

# ScriptNow 品牌金（与 Hermes Agent CLI 的金色一致）：LOGO 与主强调。
GOLD = "\033[1;38;2;255;215;0m"
CYAN = "\033[36m"     # 标题 / key
GREEN = "\033[32m"    # 成功
RED = "\033[31m"      # 错误
YELLOW = "\033[33m"   # 警告
GREY = "\033[90m"     # 次要信息

TAGLINE = "从灵感到成书 —— agent-native 创作 CLI"

# 进入横幅字符画（品牌 logo，等宽字体下展示）
LOGO = r"""   d888888o.       ,o888888o.    8 888888888o.    8 8888 8 888888888o 8888888 8888888888 b.             8     ,o888888o.  `8.`888b                 ,8'
 .`8888:' `88.    8888     `88.  8 8888    `88.   8 8888 8 8888    `88.     8 8888       888o.          8  . 8888     `88. `8.`888b               ,8'
 8.`8888.   Y8 ,8 8888       `8. 8 8888     `88   8 8888 8 8888     `88     8 8888       Y88888o.       8 ,8 8888       `8b `8.`888b             ,8'
 `8.`8888.     88 8888           8 8888     ,88   8 8888 8 8888     ,88     8 8888       .`Y888888o.    8 88 8888        `8b `8.`888b     .b    ,8'
  `8.`8888.    88 8888           8 8888.   ,88'   8 8888 8 8888.   ,88'     8 8888       8o. `Y888888o. 8 88 8888         88  `8.`888b    88b  ,8'
   `8.`8888.   88 8888           8 888888888P'    8 8888 8 888888888P'      8 8888       8`Y8o. `Y88888o8 88 8888         88   `8.`888b .`888b,8'
    `8.`8888.  88 8888           8 8888`8b        8 8888 8 8888             8 8888       8   `Y8o. `Y8888 88 8888        ,8P    `8.`888b8.`8888'
8b   `8.`8888. `8 8888       .8' 8 8888 `8b.      8 8888 8 8888             8 8888       8      `Y8o. `Y8 `8 8888       ,8P      `8.`888`8.`88'
`8b.  ;8.`8888    8888     ,88'  8 8888   `8b.    8 8888 8 8888             8 8888       8         `Y8o.`  ` 8888     ,88'        `8.`8' `8,`'
 `Y8888P ,88P'     `8888888P'    8 8888     `88.  8 8888 8 8888             8 8888       8            `Yo     `8888888P'           `8.`   `8'"""

_no_color = False


def init(no_color: bool = False) -> None:
    """Set the CLI-wide color policy (called once from the entry group)."""
    global _no_color
    _no_color = no_color


def enabled() -> bool:
    if _no_color:
        return False
    if os.environ.get("NO_COLOR") or os.environ.get("SCRIPTNOW_NO_COLOR"):
        return False
    if os.environ.get("SCRIPTNOW_FORCE_COLOR") == "1":
        return True
    return sys.stdout.isatty()


def paint(text: str, code: str = "") -> str:
    """Wrap *text* in *code* when color is enabled, else return it unchanged."""
    if not code or not enabled():
        return text
    return f"{code}{text}{_RESET}"


def banner(version: str, *, logo: bool = True) -> str:
    """Concise brand banner. 规范、不复杂：``logo=True`` 时带进入横幅字符画
    （裸运行欢迎页），``logo=False`` 只输出品牌行（--help 顶部，避免干扰）。"""
    head = [paint("ScriptNow CLI", GOLD), paint(f"v{version} · {TAGLINE}", GREY)]
    if logo:
        return "\n".join([paint(LOGO, GOLD), *head])
    return "\n".join(head)


def ok(text: str) -> str:
    return paint(f"✓ {text}", GREEN)


def warn(text: str) -> str:
    return paint(f"! {text}", YELLOW)


def error(text: str) -> str:
    return paint(f"✗ {text}", RED)


def dim(text: str) -> str:
    return paint(text, GREY)


def section(text: str) -> str:
    return paint(text, CYAN)


def kv(key: str, value: object) -> str:
    """``key: value`` line with the key tinted (stable, minimal)."""
    return f"{paint(key, CYAN)}: {value}"
