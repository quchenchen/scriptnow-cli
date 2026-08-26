"""scriptnow-cli — agent-native CLI for the ScriptNow creative platform.

Covers the core creation chain: projects, work interpretation (read-through →
source profile + reusable skill), novel chapters & StoryMap, and tenant skills.
Every command supports ``--json`` for structured agent consumption.

Configuration: session persisted at ~/.config/scriptnow-cli/session.json after
``scriptnow login``; or set SCRIPTNOW_CLI_CONFIG to relocate it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import click

from cli_anything.scriptnow import __version__ as VERSION
from cli_anything.scriptnow import ui
from cli_anything.scriptnow.utils.session import (
    ScriptNowError,
    Session,
    load,
    login,
    write_json,
)
from cli_anything.scriptnow.utils.upgrade import (
    latest_version,
    maybe_warn_in_background,
    upgrade as _upgrade_cli,
)


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _session(ctx: click.Context) -> Session:
    """Resolve a Session, logging in when --base-url/--email/--password are given."""
    base = ctx.obj.get("base_url")
    email = ctx.obj.get("email")
    password = ctx.obj.get("password")
    if base and email and password:
        return login(base, email, password)
    return load()


def _emit(value: Any, json_output: bool) -> None:
    if json_output:
        write_json(value)
    else:
        if isinstance(value, list):
            for item in value:
                _emit(item, False)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                click.echo(ui.kv(key, _human(item)))
            return
        click.echo(_human(value))


def _novel_state(session: Session, project_id: str) -> Any:
    """Fetch novel project state WITHOUT manuscript blocks (light payload).

    章节正文按章分批读取（chapter show 走按章 documents 端点），state 只承担
    结构/元数据：storymap、cores、blueprint、documents 摘要。响应从 ~336KB
    降到 ~55KB，受限网络下也不再触发响应截断。
    """
    return session.request(
        "GET",
        f"/novel/projects/{project_id}/state",
        params={"include_blocks": "false"},
    )


def _human(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


# ------------------------------------------------------------------ 用户友好交付语言
# 面向编剧/编辑（非技术用户）的提示翻译：把技术标识、状态词翻译成作品语言，
# 并在交付关键节点附上「下一步」引导，让用户在 agent+CLI 共创流程里始终知道
# 自己在哪、刚完成了什么、接下来做什么。--json 结构化输出不受影响。


def _pretty_kind(medium: str) -> str:
    """'novel' → 小说章节, 'script' → 剧本场次（用于生成/回传提示）。"""
    return "小说章节" if medium == "novel" else "剧本场次"


def _status_word(status: str | None, *, medium: str) -> str:
    """把平台状态词翻译成编辑能懂的话。

    人机协作铁律的可见化：adopted_human（人工核验定稿）与 adopted（agent 采纳）
    分开展示——编辑需要一眼看出「这版是经过人核验的」还是「AI 自己定的」。
    """
    if status in ("adopted_human", "adopted", "active"):
        return "已定稿"
    if status in ("candidate", "draft", "pending"):
        return "候选稿"
    if status == "succeeded":
        return "完成"
    if status == "running":
        return "创作中"
    if status == "queued":
        return "排队中"
    if status == "failed":
        return "未通过"
    if status in (None, ""):
        return "状态未知"
    unit = "章" if medium == "novel" else "场"
    return f"{status}（{unit}状态）"


def _next_step_after_generate(medium: str) -> str:
    """生成/回传完成后的下一步引导。"""
    if medium == "novel":
        return "下一步：用 chapter show 通读全文，满意后用 chapter adopt 定稿；不满意就带着反馈重新生成。"
    return "下一步：用 scene show 通读本场，满意后用 scene adopt 定稿；不满意就带着反馈重新生成。"


def _next_step_after_adopt(medium: str) -> str:
    """定稿后的下一步引导。"""
    if medium == "novel":
        return "本章已定稿并进入正文版本库，可随时回溯。继续下一章，或先审读修订本章。"
    return "本场已定稿并进入正文版本库，可随时回溯。继续下一场，或先审读修订本场。"


def _confirm_line(medium: str, *, adopted: bool) -> str:
    """生成/定稿的确认语，避免干巴巴的状态词。"""
    unit = "章节" if medium == "novel" else "场次"
    if adopted:
        return f"{unit}已定稿 ✅ —— {_next_step_after_adopt(medium)}"
    return f"{unit}候选稿已就绪 —— {_next_step_after_generate(medium)}"


# ------------------------------------------------------------------ token budget


# Rough token estimation for content imported via propose. Chinese is roughly
# 1 token per character; English roughly 1 token per 4 characters. These are
# conservative per-content estimates used to gate imports BEFORE they inflate
# downstream generation context — they are not billing numbers.
_CJK_RANGES = (
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Ext A
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
)


def _estimate_tokens(value: object) -> int:
    """Estimate token cost of a JSON payload (dict/list/str/scalar)."""
    if isinstance(value, str):
        if not value:
            return 0
        cjk = sum(
            1 for ch in value
            if any(lo <= ord(ch) <= hi for lo, hi in _CJK_RANGES)
        )
        other = len(value) - cjk
        return cjk + max(1, other // 4)
    if isinstance(value, dict):
        return sum(_estimate_tokens(k) + _estimate_tokens(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return sum(_estimate_tokens(item) for item in value)
    return len(str(value))


def _check_budget(payload: Any, budget: int | None, label: str, json_output: bool) -> None:
    """Reject an import when its estimated token cost exceeds the budget."""
    if budget is None:
        return
    cost = _estimate_tokens(payload)
    if cost > budget:
        raise click.ClickException(
            f"{label} 预估 {cost} tokens，超过预算 {budget}。"
            "请精简内容（如缩短 premise / point_of_view / beats 描述）后重试，"
            "或提高 --budget。"
        )
    if not json_output:
        click.echo(f"  {ui.dim(f'{label} 预估 {cost} tokens（预算 {budget}）')}", err=True)


_MAIN_HELP = (
    ui.banner(VERSION, logo=False)
    + "\n\n"
    + """ScriptNow 创作 CLI —— 从灵感到成书交付的一站式命令行。

典型流程（Agent 或创作者）：
  1. scriptnow project create --name 新作 --medium novel   # 建项目
  2. scriptnow interpret go 手稿.docx                       # 一书一 Skill：上传作品解读出创作方法论
  3. scriptnow storymap generate <pid>                      # 规划全书卷章节（后台，拿 run_id 后轮询 run status）
  4. scriptnow book <pid>                                   # 查看全书托管创作规划
  5. scriptnow chapter generate <pid> chapter-1-1           # 逐章生成（后台；run status <run_id> 轮询到完成；Agent 审读后带 feedback 修正）
  6. scriptnow cover generate <pid> --image-model-id <id>   # 生成封面
  7. scriptnow export create <pid> --units chapter-1-1      # 导出成书
  8. scriptnow export download <pid> <manifest> -o 书.docx  # 下载交付
  # Agent 注意：生成命令不带 --wait（宿主工具轮候窗口有限），用 run status 分次轮询

剧本同理：medium=script，用 script scene / script storymap / export --domain script。
更多：每个子命令 -h 查看；所有命令支持 --json 输出结构化结果。"""
)


@click.group(context_settings=CONTEXT_SETTINGS, help=_MAIN_HELP, invoke_without_command=True)
@click.option("--base-url", envvar="SCRIPTNOW_BASE_URL", help="Platform base URL (e.g. https://sn.igeewa.com)")
@click.option("--email", envvar="SCRIPTNOW_EMAIL", help="Login email")
@click.option("--password", envvar="SCRIPTNOW_PASSWORD", help="Login password")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON")
@click.option("--no-color", "no_color", is_flag=True, help="Disable ANSI colors (also: NO_COLOR / SCRIPTNOW_NO_COLOR env)")
@click.version_option(
    VERSION,
    prog_name="scriptnow",
    message=f"{ui.paint('ScriptNow CLI', ui.MATRIX)} %(version)s",
)
@click.pass_context
def main(
    ctx: click.Context,
    base_url: str | None,
    email: str | None,
    password: str | None,
    json_output: bool,
    no_color: bool,
) -> None:
    """ScriptNow 创作 CLI —— 从灵感到成书交付的一站式命令行。"""
    ui.init(no_color)
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = base_url
    ctx.obj["email"] = email
    ctx.obj["password"] = password
    ctx.obj["json"] = json_output
    ctx.obj["no_color"] = no_color
    # 强制版本检查：后台低频（24h 缓存）查询 GitHub 发布镜像，有新版时提示
    # 升级（不阻塞任何命令，失败静默）。
    if not json_output:
        maybe_warn_in_background()
    if ctx.invoked_subcommand is None:
        click.echo(ui.banner(VERSION))
        click.echo(ui.dim("运行 scriptnow --help 查看全部命令；每个子命令 -h 查看用法。"))

@main.command("version")
@click.option("--check", "force_check", is_flag=True, help="强制联网检查最新版本（跳过 24h 缓存）")
@click.option("--json", "json_output", is_flag=True)
def version_cmd(force_check: bool, json_output: bool) -> None:
    """查看当前版本；--check 强制检查 GitHub 发布镜像是否有新版。"""
    current = VERSION
    if force_check:
        latest = latest_version()
        payload = {"current": current, "latest": latest}
        _emit(payload, json_output)
        if not json_output:
            if latest is None:
                click.echo(ui.dim("无法连接版本源（或已是最新）。"))
            elif latest == current:
                click.echo(ui.ok(f"当前已是最新版本 v{current}"))
            else:
                click.echo(
                    ui.warn(
                        f"发现新版本 v{latest}（当前 v{current}）。"
                        "运行 scriptnow self-upgrade 自动升级。"
                    )
                )
        return
    payload = {"current": current}
    _emit(payload, json_output)
    if not json_output:
        click.echo(f"ScriptNow CLI v{current}")

@main.command("self-upgrade")
@click.option("--yes", "assume_yes", is_flag=True, help="跳过确认直接升级")
@click.option("--json", "json_output", is_flag=True)
def self_upgrade_cmd(assume_yes: bool, json_output: bool) -> None:
    """自动升级 CLI 到最新版本（先检查，再确认，后执行）。"""
    latest = latest_version()
    if latest is None:
        _emit({"ok": False, "reason": "unreachable"}, json_output)
        if not json_output:
            click.echo(ui.warn("无法连接版本源，稍后再试。"))
        return
    if latest == VERSION:
        _emit({"ok": True, "current": VERSION, "upgraded": False}, json_output)
        if not json_output:
            click.echo(ui.ok(f"当前已是最新版本 v{VERSION}"))
        return
    if not json_output and not assume_yes:
        if not click.confirm(
            f"将把 CLI 从 v{VERSION} 升级到 v{latest}。是否继续？", default=True
        ):
            click.echo("已取消。")
            return
    success = _upgrade_cli(quiet=json_output)
    _emit({"ok": success, "current": VERSION, "latest": latest, "upgraded": success}, json_output)
    if not json_output:
        if success:
            click.echo(ui.ok("升级完成，请重新运行 scriptnow --version 确认。"))
        else:
            click.echo(ui.warn("升级未完成；本地开发模式请手动 pip install -e。"))


# --------------------------------------------------------------------------- auth


def _onboarding_path() -> Path:
    override = os.environ.get("SCRIPTNOW_CLI_CONFIG")
    if override:
        return Path(override).with_name("onboarded.json")
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "scriptnow-cli"
        / "onboarded.json"
    )


def _onboarding_done() -> bool:
    try:
        return _onboarding_path().exists()
    except OSError:
        return True  # fail closed: never block command flow on onboarding


def _mark_onboarding_done() -> None:
    import time as _time

    path = _onboarding_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    path.write_text(
        json.dumps({"onboarded": True, "at": int(_time.time()), "version": VERSION}, ensure_ascii=False)
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass


@main.command("authorize")
@click.argument("project_id")
@click.option("--chapter", default=None, help="限定章节（如 chapter-2-1）；不限定则可用于该项目任意章节定稿")
@click.option("--scene", default=None, help="限定场次（如 scene-1）")
@click.option("--purpose", default="定稿授权", help="授权用途说明")
@click.option("--evidence", default="", help="授权证据原文（用户对话里的原话引用）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def authorize_cmd(
    ctx: click.Context,
    project_id: str,
    chapter: str | None,
    scene: str | None,
    purpose: str,
    evidence: str,
    json_output: bool,
) -> None:
    """签发一次性「人工决策授权令牌」（对话内文字授权通道）。

    复用当前登录会话签发，**不要求重新登录**。用户在对话里明确授权定稿后，
    运行本命令拿到一次性 token（15 分钟有效），agent 用
    `chapter adopt --human --token <token>` 完成人工定稿，平台记录审计
    （用户、方式=对话授权、证据原文）。令牌只能由你的会话签发，agent 无法伪造。
    """
    body = {
        "project_id": project_id,
        "chapter_id": chapter,
        "scene_id": scene,
        "kind": "adopt",
        "purpose": purpose,
        "evidence": evidence,
    }
    result = _session(ctx).request("POST", "/api/decision-tokens", json_body=body, write=True)
    if not json_output:
        click.echo(ui.section("=== 人工决策授权令牌 ==="), err=True)
        click.echo(ui.kv("token", result.get("token")), err=True)
        click.echo(ui.dim(f"有效期：{result.get('expires_in')} 秒（一次性）"), err=True)
        if result.get("evidence"):
            click.echo(ui.dim(f"证据：{result.get('evidence')}"), err=True)
        click.echo("", err=True)
        click.echo(
            ui.dim(
                "agent 用法：chapter adopt --human --token <token> <作品号> <章节号> <版本号>"
                + ("（或对应 scene adopt）" if not chapter else "")
            ),
            err=True,
        )
        return
    _emit(result, json_output)


@main.command("feedback")
@click.option("--note", default="", help="补充说明（可选，例如你遇到的场景描述）")
@click.option("--send", is_flag=True, help="发送诊断包到平台（默认只本地生成，不发送）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def feedback_cmd(ctx: click.Context, note: str, send: bool, json_output: bool) -> None:
    """收集 CLI 诊断包（版本/近期错误/命令记录），供针对性修复。

    默认只生成本地诊断包并展示；--send 才发送到平台（需已登录）。
    诊断包不含密码、令牌、正文——只含脱敏参数与错误码。
    """
    from cli_anything.scriptnow import __version__ as _VERSION
    from cli_anything.scriptnow.utils.diag import recent_errors

    errors = recent_errors(50)
    package = {
        "cli_version": _VERSION,
        "note": note[:500],
        "error_count": len(errors),
        "errors": errors,
    }
    if send:
        try:
            result = _session(ctx).request(
                "POST", "/cli-feedback", json_body=package, write=True
            )
            if not json_output:
                click.echo(ui.ok("诊断包已发送到平台，感谢反馈！"), err=True)
            _emit({"sent": True, "result": result}, json_output)
            return
        except ScriptNowError as error:
            raise click.ClickException(f"发送失败：{error}")
    if not json_output:
        click.echo(ui.section("=== CLI 诊断包（本地）==="), err=True)
        click.echo(ui.kv("CLI 版本", package["cli_version"]), err=True)
        click.echo(ui.kv("错误条数", package["error_count"]), err=True)
        for e in errors[:5]:
            click.echo(f"  [{e.get('error_code','?')}] {e.get('iso','?')} {e.get('command','?')}", err=True)
            click.echo(ui.dim(f"      {str(e.get('detail',''))[:100]}"), err=True)
        if note:
            click.echo(ui.dim(f"备注：{note}"), err=True)
        click.echo("", err=True)
        click.echo(ui.dim("确认后运行 scriptnow feedback --send 发送到平台（需已登录）。"), err=True)
        return
    _emit(package, json_output)


@main.command("doctor")
@click.option("--clear-errors", is_flag=True, help="清空本地 CLI 错误日志（errors.jsonl）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def doctor_cmd(ctx: click.Context, clear_errors: bool, json_output: bool) -> None:
    """诊断：当前 CLI 版本、配置/会话位置、登录账号、平台连通性。

    Agent 排查「登录失败 / 找不到配置 / 409 权限」时先跑本命令，一眼看到
    会话写在哪、用的是哪个账号、能否连通平台。
    """
    from cli_anything.scriptnow import __version__ as _VERSION
    from cli_anything.scriptnow.utils.session import _config_path

    if clear_errors:
        from cli_anything.scriptnow.utils.diag import clear_errors as _clear

        cleared = _clear()
        if not json_output:
            if cleared:
                click.echo(ui.ok("CLI 错误日志已清空。"), err=True)
            else:
                click.echo(ui.error("清空失败（文件可能被占用或无权限）。"), err=True)
        else:
            _emit({"cleared": cleared}, json_output)
        return
    config = _config_path()
    report: dict[str, object] = {
        "version": _VERSION,
        "session_path": str(config),
        "session_exists": config.exists(),
    }
    # 尝试加载会话并取账号（不抛错，失败也算诊断信息）
    try:
        session = _session(ctx)
        me = session.request("GET", "/auth/me")
        user_id = me.get("user_id") if isinstance(me, dict) else None
        email = me.get("email") if isinstance(me, dict) else None
        report["logged_in"] = True
        report["user_id"] = user_id
        report["email"] = email
        report["base_url"] = session.base_url
    except Exception as error:  # noqa: BLE001 — 诊断命令要展示任何失败
        report["logged_in"] = False
        report["login_error"] = str(error)[:240]
    from cli_anything.scriptnow.utils.diag import recent_errors

    report["recent_errors"] = recent_errors(20)
    if not json_output:
        click.echo(ui.section("=== scriptnow doctor ==="), err=True)
        click.echo(ui.kv("CLI 版本", report["version"]), err=True)
        click.echo(ui.kv("会话文件", report["session_path"]), err=True)
        click.echo(
            ui.ok("会话文件存在") if report["session_exists"] else ui.warn("会话文件不存在——先 scriptnow login"),
            err=True,
        )
        if report.get("logged_in"):
            click.echo(ui.ok(f"已登录：{report.get('email')}（user {report.get('user_id')}）"), err=True)
            click.echo(ui.dim(f"平台：{report.get('base_url')}"), err=True)
        else:
            click.echo(ui.warn(f"未登录：{report.get('login_error')}"), err=True)
            click.echo(ui.dim("修复：scriptnow login --host <平台地址> --email <账号>（交互输入密码）"), err=True)
        click.echo(ui.dim("配置目录：~/.config/scriptnow-cli/（session.json + version-check.json + errors.jsonl）"), err=True)
        click.echo(ui.dim("可用环境变量 SCRIPTNOW_CLI_CONFIG 覆盖会话文件位置"), err=True)
        # 近期错误诊断
        from cli_anything.scriptnow.utils.diag import recent_errors

        errs = recent_errors(5)
        if errs:
            click.echo("", err=True)
            click.echo(ui.section("=== 近期 CLI 错误（最近 5 条）==="), err=True)
            for e in errs:
                click.echo(
                    f"  {e.get('iso','?')} [{e.get('error_code','?')}] "
                    f"{e.get('command','?')} {''.join(e.get('args') or [])[:40]}",
                    err=True,
                )
                click.echo(ui.dim(f"      {str(e.get('detail',''))[:90]}"), err=True)
            click.echo(ui.dim("可用 scriptnow feedback 发送诊断包；scriptnow doctor --clear-errors 清空。"), err=True)
        else:
            click.echo(ui.ok("近期无 CLI 错误记录 ✅"), err=True)
        return
    _emit(report, json_output)


@main.command()
@click.option("--steps", is_flag=True, help="只展示完整作品向导步骤（短篇/短剧闭环）")
@click.option("--step", type=click.IntRange(1, 10), default=None, help="只进入当前创作步骤，避免一次展示整套命令")
@click.option("--medium", type=click.Choice(["novel", "script"]), default="novel", help="按小说或剧本显示对应创作路径")
@click.option("--resume", is_flag=True, help="多轮发散后温和回到当前步骤（须与 --step 一起使用，不改变平台状态）")
@click.option("--pulse", default=None, help="最近对话的轻量脉搏 JSON（@file 或内联）；判断是否需要柔性回归，不写平台状态")
@click.option("--complete", is_flag=True, help="标记新手模式已完成（写入 onboarded 标记）")
@click.option("--status", is_flag=True, help="查看新手模式完成状态")
@click.option("--json", "json_output", is_flag=True)
def guide(steps: bool, step: int | None, medium: str, resume: bool, pulse: str | None, complete: bool, status: bool, json_output: bool) -> None:
    """新手模式：编辑/编剧视角介绍核心能力、共创愿景，并给出完成一部完整作品的向导。"""
    import time as _time

    if complete:
        _mark_onboarding_done()
        _emit({"onboarded": True, "marked_at": int(_time.time())}, json_output)
        if not json_output:
            click.echo(ui.ok("新手提示已关闭；随时可用 scriptnow guide 重看。"))
            click.echo(
                ui.dim(
                    "注意：这只是关闭新手引导，不代表作品已完成。"
                    "作品完成以平台导出物与完结记录为准（cover/export/验收）。"
                ),
                err=True,
            )
        return

    if status:
        _emit({"onboarded": _onboarding_done()}, json_output)
        if not json_output:
            click.echo(
                ui.ok("新手模式已完成") if _onboarding_done() else ui.warn("新手模式尚未完成")
            )
        return

    if (resume or pulse) and step is None:
        raise click.ClickException("--resume/--pulse 需要同时指定 --step <1..10>，以免猜测当前创作位置")
    if step is not None:
        guide_payload = (
            _guide_pulse(step, medium, pulse)
            if pulse
            else _guide_focus(step, medium, resume=resume)
        )
    elif steps:
        guide_payload = _guide_steps(medium)
    elif not json_output:
        # 人类首次进入只看当前一幕；完整路线仍可用 --steps 随时查看。
        guide_payload = _guide_focus(1, medium, welcome=True)
    else:
        guide_payload = _guide_full()
    _emit(guide_payload, json_output)
    if not json_output:
        _echo_guide(guide_payload)


_AGENT_CONTRACT = {
    "guide": "scriptnow-agent-contract",
    "title": "ScriptNow Agent 操作契约 —— 连接平台前必读",
    "audience": "在 ScriptNow 平台上创作小说/剧本的 AI Agent。以本契约为唯一操作准则；本契约与平台后端返回为准，优先于任何对平台的猜测。",
    "rules": [
        "创作对话优先于技术操作：新手模式按 scriptnow guide --step <n> --medium novel|script --json 一幕一幕推进。每轮只问一个主问题；用户卡住时才选择一个 lenses 角度启发。先用自然语言复述创作意图，再给一个具体候选，让用户只做『保留 / 调整 / 换方向』的决定。命令、JSON、id、质量术语默认留在幕后。多轮发散后可将最近对话的轻量摘要传给 guide --pulse @pulse.json --step <当前幕>：只含 rounds_without_progress / decision_advanced / captured_material / unresolved / conflicts / next_stage_requested，不传正文。仅当返回 drifting/conflict 才按 recovery 协议先收拢成果、再邀请回归；useful_detour 必须保留素材并允许继续探索。也可直接用 --resume 温和接回。所有机制都不得改变平台状态、强制跳转、倾倒整套流程、连续盘问，或用『作为 AI』『根据算法』等措辞破坏共创感。",
        "平台是唯一事实源：项目、章节、候选、采纳、版本、导出都以 ScriptNow 平台为准。禁止在本地自行创建『类项目目录/JSON 结构』冒充平台项目，也不要绕过 CLI 直接构造 HTTP 请求。唯一的体外例外是本地缓存与资料整理（下载素材、归档参考资料、暂存草稿片段等纯本地文件）——此类文件不得自称或伪装为平台项目，正式项目一律在平台内创建。",
        "一切平台操作必须经 scriptnow 命令：创建项目、规划、回传（propose）、采纳（adopt）、生成（generate）、导出（export）。离线创作的正文只是草稿，成品必须以 propose 回传为平台候选，由平台校验格式与质量。",
        "规划三件套（story_cores / blueprint / storymap）回填优先：默认由 Agent 本地生成后 propose 回填为候选，再经 planning-quality 质量门禁后采纳。平台端 generate 仅作后备，不依赖、不鼓励——不要把平台生成当作首选路径。StoryMap 不是只有 episode/scene 或 volume/chapter 容器：剧本每集必须提供平铺的 logline、active_goal、conflict、turn、state_changes、anchor_ids；小说每章必须提供 outline（summary 或 logline、active_goal、conflict、turn、state_changes，锚点可来自 outline 或 beat）。集纲/章纲未全量通过 planning-quality 并采纳前，不得批量进入正文；兼容读取旧项目，但生成新正文前必须按缺口补纲。",
        "分镜同样回填优先：先用 storyboard state/source-preflight/assets 取得平台事实；追加前若旧范围未知或内容重叠必须阻断，不得猜测，可经 source-range 补录或 source-revoke --confirm 审计撤销。Agent 在本地按已挂载 Skill 完成来源提取、场镜规划、资产锚定与 ScriptOut，再用 storyboard propose 回填候选。禁止默认调用平台 analyze、镜头设计或提示词 Agent；衔接策略必须由用户/导演选择。",
        "场次规划板是显式单场操作：先用 storyboard scene-board list/inspect 读取事实，再按用户要求 upload 或 generate；平台派生 layout/pages/shot_ids/digest，禁止绕过 CLI/API 或写入 shot.frame_refs。",
        "Skill 是逐章/逐场创作前的必然门禁：优先用 skill craft 共创。Agent 先以 --json 获取一次性问题协议，在自然对话中收齐答案，以 --answers @answers.json --json 回填并取得预检草案；向用户展示完整草案并获明确认可后，才用原命令加 --confirm。未 pass 不创建；通过后挂载并服务器回读。再用短样本检验约束力、诊断歧义并迭代。最后以 skill mounts <pid> 核实，才能启动正文。项目无已验证方法论 Skill 时禁止写正文。",
        "Skill 健壮性参照：craft / voice / continuity / evaluation / examples 五个维度必须有实质内容并含正反例；script 还必须覆盖四类质量锚点——场次功能与可观察转折、可见可听可表演、对白/VO/OS 发声时序、台词量与目标时长。skill craft 自动补系统锚点，不增加用户问卷；绕过 craft 直接创建也会由后端 robustness v2 检查。制作信息由系统派生，编剧不维护机器字段。",
        "回传被平台拒绝时，按返回的 detail 修正格式后重传；不要自建替代结构，也不要删除平台已有项目自行重建。",
        "会话由 CLI 自动续期（refresh token 30 天）。若提示『登录状态已失效』，用已知凭据重新运行 scriptnow login，不要伪造凭据或绕开 CLI。",
        "命令与参数以 scriptnow --help / scriptnow <命令> --help 为准；不确定时先查帮助，不要臆造参数或输出格式。",
        "需要保存的标识（project_id / chapter_id / revision_id / run_id）来自命令的 --json 输出；后续命令一律引用这些 id，不要自造 id 或猜测路径。",
        "CLI 版本与 /cli 页面一致；发现行为异常先检查 scriptnow --version 是否最新。",
        "生成类命令（storymap/chapter/scene generate）默认后台执行并立即返回 run_id，禁止用 --wait 长阻塞等待（宿主工具轮候窗口有限，会超时被杀）。用 scriptnow run status <run_id> 分次轮询直到 succeeded/failed；交互式终端才可 --wait，并可用 SCRIPTNOW_WAIT_MAX_SECONDS 限制单次等待。",
        "StoryMap 修订是超级高危操作：采纳（storymap adopt）会覆盖当前结构、改变保留章节的标题/字数并影响已采纳正文。只有主编/作者本人明确授权（CLI 需 --confirm，平台需勾选知情确认）才可执行；Agent 不得代替用户采纳 storymap，也不得在未获授权时自行 propose+adopt 重构。被替换的旧结构与各章正文快照会自动归档，可在平台「结构历史」中查看与导出。",
        "报告完成必须以服务器回读为据：任何写操作（创建项目/规划/回传/采纳/生成/导出）成功 = 服务器返回了 project_id / candidate_id / revision_id / run_id，并在成功后回读平台确认落盘。没有服务器返回的 ID 与回读确认，不得向用户报告『已完成』；不得用本地文件或文字自述代替平台状态。project create 后立即回读 project list 核对项目存在。",
        "人机协作铁律（逐章/逐场定稿必须来自人的明确决定）：禁止 Agent 自行定稿。候选产出后应把全文或用户要求的审读范围呈现出来；用户在对话中明确表达『定稿』『采用这版』『可以进入下一章/场』等，即构成人工决定，Agent 可直接执行 chapter adopt --human / scene adopt --human，平台记录 adopted_human。无需用户重复去终端或页面确认，也不强制签发令牌；令牌仅是可选的增强审计方式。没有明确表达时才追问一次，Agent 不得从沉默、泛泛称赞或大纲授权中自行推断定稿。",
    ],
    "quickstart": [
        "scriptnow guide --step 1 --medium novel|script --json（每步完成后按 next_step 衔接，不一次展示命令墙）",
        "scriptnow login --host https://sn.igeewa.com --email <邮箱>（随后安全输入密码）",
        "scriptnow project create --name <作品名> --medium novel|script --premise <前提> --genre <类型> --tone <文风> --chapter-target-words 1200",
        "scriptnow novel propose cores @cores.json --adopt && scriptnow novel propose blueprint @blueprint.json --adopt && scriptnow novel propose storymap @storymap.json",
        "分镜回填：scriptnow storyboard source-import <pid> source.txt --source-kind script --json → storyboard state/assets <pid> --json → Agent 本地生成 ScriptOut → storyboard propose <pid> @storyboard.json --source-id <sid>；仅在用户明确采用后加 --adopt",
        "场次规划板：scriptnow storyboard scene-board list <pid> --scene <scene_id> --json → 按用户要求 upload <pid> <scene_id> board.png --layout auto|3x3|4x4 --mode annotated|seedance_sequence 或 generate <pid> <scene_id> --layout auto --mode annotated；删除必须 --confirm。",
        "Skill 门禁（逐章创作前必做）：skill craft --domain novel|script --json → 自然共创 → --answers @answers.json --json 预检并展示草案 → 获认可后原命令加 --project-id <pid> --confirm（创建、挂载、回读）→ 短样本试写验证 → skill mounts <pid> 核实",
        "scriptnow chapter generate <pid> chapter-1-1（后台，run status 轮询） → 呈现正文 → 用户在对话中明确采用后，Agent 直接 chapter adopt --human <pid> <cid> <revision_id>",
        "集纲/章纲回填：剧本在 storymap JSON 的每个 episode 上填写平铺的 logline/active_goal/conflict/turn/state_changes/anchor_ids；小说在每个 chapter 的 outline 中填写 summary 或 logline、active_goal/conflict/turn/state_changes，锚点可来自 outline.anchor_ids 或 beat。先运行 scriptnow script/novel planning-quality <pid> storymap @storymap.json，再 propose；只在用户明确决定后 adopt。旧项目可用 script episode-outline <pid> <episode_id> @outline.json 或 chapter outline <pid> <chapter_id> @outline.json 单集/单章补纲；补纲候选仍须 planning-quality 与 StoryMap 采纳。新增卷/章（纯追加，不动已有卷章）：scriptnow storymap append-volume <pid> @volumes.json --adopt | scriptnow storymap append-chapters <pid> <volume_id> @chapters.json --adopt",
        "scriptnow export create <pid> --units chapter-1-1",
    ],
    "format_hint": "剧本正文 blocks 类型：slugline|action|character|dialogue|transition；小说正文 blocks 类型：heading|prose|dialogue|quote|divider。propose 前可用 --help-format 查看精确 JSON 规格。",
}

# The installed Skill calls `agent-guide --json` before the first action. Keep
# that handshake executable and bounded; the historical handbook remains
# available through `--full` for a human or a deliberate deep inspection.
_AGENT_RUNTIME_CONTRACT = {
    "guide": "scriptnow-agent-runtime-contract",
    "contract_version": "2",
    "title": "ScriptNow Agent 运行契约",
    "audience": "在 ScriptNow 平台执行创作任务的 AI Agent。",
    "rules": [
        "先读取平台状态和本契约；不确定命令或 JSON 结构时先运行对应 --help，不猜测。",
        "平台是唯一项目事实源：所有创建、回传、采纳、生成、导出都只能通过 scriptnow CLI。",
        "本地内容只是一时草稿；规划和正文必须 propose 回平台候选，等待平台校验与服务器回读。",
        "分集/分章集级规划是正文前的必需环节：剧本每个 episode 必须提供平铺的 logline、active_goal、conflict、turn、state_changes、anchor_ids；小说每个 chapter 必须提供 outline（summary 或 logline、active_goal、conflict、turn、state_changes，锚点可来自 outline 或 beat）。先用 planning-quality 检查全量覆盖，再 propose/采纳；旧项目可读，但补纲前不得批量生成正文。",
        "分镜追加先执行 source-preflight；未知范围或重叠必须阻断并走 source-range/source-revoke 正式审计路径。Agent 本地提取、规划和资产锚定后用 storyboard propose 回填；平台生成仅后备，衔接由用户选择。",
        "场次规划板必须经 storyboard scene-board list/inspect 读取；upload/generate/delete 只操作场次 planning_boards，平台派生分页和 shot_ids，绝不修改 shot.frame_refs。",
        "先让用户作一个明确决定，再做一次对应动作；不得自行采纳章节、场次或 StoryMap。",
        "生成命令只拿 run_id，随后分次 run status 轮询；不得用长阻塞等待伪装完成。",
        "写操作只有服务器返回 ID 且回读确认后才可报告完成；错误必须按 detail 修正，不能编造替代结果。",
        "不得输出安装命令、Skill 手册、隐藏推理或泛化教程到创作交付物。",
    ],
    "quickstart": ["scriptnow --help", "scriptnow agent-guide --full（仅需人工完整参考时）"],
    "format_hint": "具体 JSON 结构只以目标 propose 命令的 --help-format / --example 为准。",
    "next_action": "用自然语言说明当前事实和一个需要用户决定的下一步，再执行精确 CLI 命令。",
}


@main.command("agent-guide")
@click.option("--json", "json_output", is_flag=True)
@click.option("--full", "full", is_flag=True, help="输出完整人工参考手册（默认 JSON 为短运行契约）")
def agent_guide(json_output: bool, full: bool) -> None:
    """Agent 操作契约：连接 ScriptNow 平台前必读（禁止本地自建项目、一律走 CLI）。"""
    contract = _AGENT_CONTRACT if full or not json_output else _AGENT_RUNTIME_CONTRACT
    _emit(contract, json_output)
    if not json_output:
        click.echo(ui.section(f"=== {contract['title']} ==="), err=True)
        click.echo(ui.paint(contract["audience"], ui.GOLD), err=True)
        for idx, rule in enumerate(contract["rules"], 1):
            click.echo(ui.ok(f"{idx}. {rule}"), err=True)
        if "quickstart" in contract:
            click.echo(ui.section("常用命令速查"), err=True)
            for command in contract["quickstart"]:
                click.echo(ui.kv("", command), err=True)
        if "format_hint" in contract:
            click.echo(ui.dim(contract["format_hint"]), err=True)


_GUIDE_STEPS = [
    {
        "step": 1,
        "title": "登录平台",
        "scene": "推开工作室的门。这里存放着你所有的作品与灵感，先落下你的名字。",
        "why": "登录一次，之后所有创作命令都会自动带上你的身份，不用反复输入。",
        "command": "scriptnow login --host https://sn.igeewa.com --email <邮箱>（随后安全输入密码）",
        "verify": "输出 登录成功：https://sn.igeewa.com（<邮箱>）",
        "prompt": "此刻你想创作什么？不必完整，先说出那个让你心动的念头。",
        "masters": [
            {
                "name": "黑泽明",
                "quote": "创作是美妙的。",
                "source": "纪录片《黑泽明：创作是美妙的》",
                "how": "今天你推开的不是软件，而是一间工作室——大师们把一生献给的事，现在轮到你来体会它的美妙。",
            },
            {
                "name": "鲁迅",
                "quote": "哪里有天才？我是把别人喝咖啡的工夫都用在工作上的。",
                "source": "鲁迅自述（学生回忆录所载）",
                "how": "创作从来不是天赋的专利，而是日复一日坐在桌前。今天你坐下来了，这就是全部的开始。",
            },
        ],
    },
    {
        "step": 2,
        "title": "创建作品项目",
        "scene": "在空白稿纸上写下第一行：作品名、体裁、一句话前提——故事从这里开始呼吸。",
        "why": "先为你的故事建一个家：定下体裁（小说/剧本）与一句话前提，之后的创作都围绕它展开。",
        "command": (
            "scriptnow project create --name <作品名> --medium novel --premise <一句话前提> "
            "--genre <类型> --tone <文风> --chapter-target-words 1200"
        ),
        "verify": "返回作品编号；保存它（下文用 <作品号> 代替）。",
        "prompt": "如果只能用一个画面来概括你的故事，那会是什么？",
        "masters": [
            {
                "name": "海明威",
                "quote": "一切初稿都是狗屎。",
                "source": "访谈中对《巴黎评论》所说",
                "how": "别怕写得不好——海明威都这么说过。你要做的只是开始，剩下的交给共创与打磨。",
            },
            {
                "name": "老舍",
                "quote": "把普通的字用得飘飘欲仙，见出作者的苦心孤诣。",
                "source": "《老舍谈写作》",
                "how": "前提不必惊艳，真诚就好。老舍说，功夫在把寻常字用得见匠心——你的故事也一样。",
            },
        ],
    },
    {
        "step": 3,
        "title": "补齐创作方向",
        "scene": "像主编定下基调：风格、类型、语言、篇幅。方向立住，整部作品才不会走调。",
        "why": "风格、类型、写作语言、篇幅结构必须明确——Agent 依此保持全书一致。",
        "command": "scriptnow project direction --apply @direction.json（Agent 生成方向文件后回填）",
        "verify": "direction 字段齐全；也可用 --inspire 让平台按前提生成草稿。",
        "prompt": "你希望读者合上最后一页时，心里留下什么？",
        "masters": [
            {
                "name": "黑泽明",
                "quote": "你必须学习并经历各种事。",
                "source": "《蛤蟆的油》",
                "how": "方向不是束缚，是你在为自己储备的经验——它让之后每一章都站在坚实的地基上。",
            },
            {
                "name": "塔可夫斯基",
                "quote": "导演工作的本质，可以定义为雕刻时光。",
                "source": "《雕刻时光》",
                "how": "每一次设定，都是你在雕刻将要呈现的时光——方向定得越清晰，刻出的光影越动人。",
            },
        ],
    },
    {
        "step": 4,
        "title": "规划故事三件套",
        "scene": "摊开编剧的案头：故事核心、蓝图、卷章结构。先想清楚再动笔，是编辑的基本功。",
        "why": "先立故事核心，再画创作蓝图，最后排出全书章节结构——先想清楚再动笔，是编辑的基本功。",
        "command": (
            "scriptnow novel propose cores @cores.json --adopt && "
            "scriptnow novel propose blueprint @blueprint.json --adopt && "
            "scriptnow novel propose storymap @storymap.json（或 novel orchestrate --accept 采纳）"
        ),
        "verify": "全书结构已定稿，创作计划可打印（book）。",
        "prompt": "你的主角最想要什么，又最怕失去什么？",
        "masters": [
            {
                "name": "契诃夫",
                "quote": "简洁是天才的姐妹。",
                "source": "契诃夫书信",
                "how": "规划的意义就在于此：把千头万绪收拢成清晰的结构，落笔时才能干净、准确、有力。",
            },
            {
                "name": "马尔克斯",
                "quote": "生活不是我们活过的日子，而是我们记住的日子。",
                "source": "《活着为了讲述》",
                "how": "故事三件套，就是在替读者挑选「值得记住的日子」——你来决定哪些瞬间进入这本书。",
            },
        ],
    },
    {
        "step": 5,
        "title": "审阅并采纳结构",
        "scene": "把候选结构摊在桌上，像资深编辑逐页过目：接受、调整、或打回重写——采纳前一切可改。",
        "why": "先把候选结构摊开给你裁决：接受、调整、或让 Agent 重写——采纳前一切可改。",
        "command": "scriptnow novel orchestrate <作品号> --accept",
        "verify": "输出全书创作计划（各章状态为「待创作」）。",
        "prompt": "这个结构里，哪一章让你最期待动笔？",
        "masters": [
            {
                "name": "王家卫",
                "quote": "电影是时间的艺术。",
                "source": "访谈",
                "how": "结构就是你对时间的安排——这一卷卷、一章章，是你亲手为故事量出的节奏。",
            },
            {
                "name": "宫崎骏",
                "quote": "创作就是生活本身。",
                "source": "访谈（转述其创作理念）",
                "how": "采纳结构的那一刻，这部作品开始真正属于你——接下来的每一章，都是你生活的一部分。",
            },
        ],
    },
    {
        "step": 6,
        "title": "规划并挂载专属 Skill（门禁 · 须健壮性完善）",
        "scene": "在动笔之前，先为这部作品量身打造创作方法论：与你的创作搭档一起梳理风格锚点、角色守则、连续性标准——多轮打磨，并试写检验，直到方法论真正健壮、真正代表你的意图。",
        "why": "动笔之前，先为这部作品量身打造创作方法论：与你的创作搭档一起梳理风格、角色守则与连续性标准——多轮打磨、试写检验，直到它真正代表你的意图，然后挂载到作品上，才能开始逐章创作。",
        "command": "scriptnow skill mounts <作品号>（核实）→ 规划完善：interpret local <作品> --spec → 健壮性完善：试写样本对照方法论规则自审、迭代加固（可多轮）→ 回填创建：interpret local <作品> --submit @skill.json --project-id <作品号>（或 skill create + skill mount）",
        "verify": "scriptnow skill mounts <作品号> 显示该方法论已挂载，且经样本试写验证规则有效。",
        "prompt": "这部作品最需要怎样的创作方法论？哪些规则不能妥协？用一小段试写来检验它，够不够稳健？",
    },
    {
        "step": 7,
        "title": "逐章共创正文",
        "scene": "真正的共创时刻：Agent 递来一叠手稿，你逐页批注、润色、定稿。每一个字都有你的温度。",
        "why": "创作搭档递来手稿，你可以通读、局部审阅、批注或直接表达采用。只要你在对话中明确决定定稿，Agent 就会记录这次决定并继续；不要求你重复操作命令或页面。",
        "command": (
            "scriptnow book <作品号>（看计划）→ chapter show <作品号> <章节号> --plain（你通读全文）→ "
            "chapter generate <作品号> <章节号> --feedback ...（或 chapter propose --file @blocks.json 回填）→ "
            "用户在对话中明确采用 → Agent 执行 chapter adopt --human <作品号> <章节号> <版本号>"
        ),
        "verify": "每一章都有来自用户明确表达的定稿版本（adopted_human）；无需重复确认。",
        "prompt": "这一章，你想让读者和主角一起经历什么？",
        "masters": [
            {
                "name": "斯蒂芬·金",
                "quote": "关起门来写初稿，打开门来修改。",
                "source": "《写作这回事》",
                "how": "你正站在门内：先让故事自由生长，改稿的事交给下一轮——这是每一位写作者的日常。",
            },
            {
                "name": "余华",
                "quote": "写作的过程，就是不断发现自己内心真实想法的过程。",
                "source": "余华谈写作（访谈）",
                "how": "每一章都是你与自己的一次对话——Agent 递来的手稿，帮你把心里那些模糊的念头说清楚。",
            },
        ],
    },
    {
        "step": 8,
        "title": "审读与修订",
        "scene": "编辑的责任：不放过一处瑕疵。逐句逐帧以挑剔受众的目光审读——每一句是否值得停留，每一帧是否推动情绪。",
        "why": "Agent 审读必须严苛：化身资深编剧与挑剔受众，逐句引用证据、点名失败的节拍，拒绝泛泛而谈的称赞；低于标准的正文立即带反馈重新生成。",
        "command": "scriptnow chapter show <作品号> <章节号> --plain（通读全文后裁决；不满意即 chapter generate --feedback 迭代）",
        "verify": "每一句都经得起挑剔读者的审视；质量报告无阻断项。",
        "prompt": "如果只能删掉一段，你会删哪一段？删掉之后，故事会不会更有力？",
        "masters": [
            {
                "name": "海明威",
                "quote": "好的写作，就像一座冰山，只露出八分之一。",
                "source": "《死在午后》",
                "how": "修订不是删减，是把水面下的七分之八想清楚——你每改一处，作品就沉得更稳。",
            },
            {
                "name": "鲁迅",
                "quote": "时间就是性命，无端地空耗别人的时间，其实是无异于谋财害命。",
                "source": "鲁迅《门外文谈》",
                "how": "修订也是对读者时间的尊重——你留下的每一句，都要对得起他翻过的每一页。",
            },
        ],
    },
    {
        "step": 9,
        "title": "包装与导出交付",
        "scene": "杀青时刻：封面落定、包装成册、导出成品——手稿终于成为可以面世的作品。",
        "why": "封面、作品包装、导出格式——从手稿到可发布成品的一站式收尾。",
        "command": (
            "scriptnow cover package <作品号> && scriptnow cover generate <作品号> --image-model-id <生图模型> && "
            "scriptnow export options <作品号> && scriptnow export create <作品号>"
        ),
        "verify": "拿到导出文件（或封面 URL）。",
        "prompt": "这部作品完成时，你想把它交给谁？",
        "masters": [
            {
                "name": "宫崎骏",
                "quote": "创作就是生活本身。",
                "source": "访谈（转述其创作理念）",
                "how": "当手稿变成可以交付的作品，你才真正明白这句话——作品是活过的日子。",
            },
            {
                "name": "马尔克斯",
                "quote": "活着，是为了讲述。",
                "source": "《活着为了讲述》",
                "how": "交付不是告别，是讲述的开始——从今天起，这部作品替你向世界说话。",
            },
        ],
    },
    {
        "step": 10,
        "title": "标记完成",
        "scene": "合上最后一页。第一部作品完成——工作室的门从此为你常开，随时回来继续创作。",
        "why": "完成第一部作品后运行本命令，以后不再打扰；随时可重看本向导。",
        "command": "scriptnow guide --complete",
        "verify": "输出 新手模式已标记完成。",
        "prompt": "下一部作品，你想写什么？",
        "masters": [
            {
                "name": "黑泽明",
                "quote": "无论如何都要写到最后——只要放弃一次，就全完了。",
                "source": "黑泽明谈创作（访谈）",
                "how": "你写到了最后。今天这一步，值得被记住——它不是结束，是你创作生涯的第一个句点。",
            },
            {
                "name": "契诃夫",
                "quote": "写的越多，就写得越好。",
                "source": "契诃夫书信（转述其创作观）",
                "how": "第一部作品是起点，不是终点。你已证明自己能把一个故事写完——接下来，去写更多。",
            },
        ],
    },
]


def _guide_steps(medium: str | None = None) -> dict[str, object]:
    items = [dict(item) for item in _GUIDE_STEPS]
    if medium == "script":
        for item in items:
            if int(item["step"]) in _SCRIPT_GUIDE_OVERRIDES:
                item.update(_SCRIPT_GUIDE_OVERRIDES[int(item["step"])])
    return {
        "guide": "complete-works-onboarding",
        "title": "从零到一部完整作品（短篇/短剧闭环）",
        "mode": "agent-led",
        "medium": medium,
        "steps": items,
    }


_GUIDE_CREATIVE_LENSES: dict[int, list[str]] = {
    1: ["一个忘不掉的人", "一个反复出现的画面", "一个让你不甘心的问题"],
    2: ["谁正在争取什么", "什么力量阻止了他/她", "失败后会失去什么"],
    3: ["读者应感到什么", "作品坚决不成为什么", "语言与节奏更接近哪种气质"],
    4: ["主角的欲望与代价", "不可逆的关键选择", "结尾如何回应开端"],
    5: ["最期待的一段", "最像套路的一段", "尚未被结构回答的问题"],
    6: ["必须始终遵守的写法", "最容易写偏的地方", "一眼就能识别的正反例"],
    7: ["本章/场唯一任务", "人物在结束时发生的变化", "让读者继续下去的悬念"],
    8: ["删掉也不影响故事的内容", "人物只是被剧情推着走的地方", "解释多于行动的句子"],
    9: ["作品最适合交给谁", "一句能让目标读者停下来的介绍", "封面必须传达的第一情绪"],
    10: ["这次最满意的判断", "下次想改进的创作习惯", "下一部作品的第一颗种子"],
}


_SCRIPT_GUIDE_OVERRIDES: dict[int, dict[str, str]] = {
    2: {
        "command": "scriptnow project create --name <作品名> --medium script --premise <一句话前提> --genre <类型> --tone <影像与台词气质>",
        "verify": "返回作品编号，并回读确认体裁为 script、前提与气质准确。",
    },
    4: {
        "command": "scriptnow script propose <作品号> cores @cores.json --adopt → blueprint @blueprint.json --adopt → storymap @storymap.json",
        "verify": "故事核心与蓝图已采纳，季/集/场结构成为可审阅候选。",
    },
    5: {
        "command": "scriptnow script state <作品号> --json（展示候选结构；调整后再由用户决定是否采纳）",
        "verify": "用户能复述每集推进与关键场功能，并明确接受或指出调整。",
    },
    7: {
        "command": "scriptnow scene list <作品号> → scene generate/propose <作品号> <场次号> → 呈现正文 → 用户明确采用后 Agent 执行 scene adopt --human",
        "verify": "当前场有来自用户明确表达的 adopted_human 版本；不要求重复终端或页面确认。",
    },
    8: {
        "command": "scriptnow scene show <作品号> <场次号> --plain → scene quality <作品号> <场次号> → 按反馈修订",
        "verify": "场次功能、可拍性、潜台词与转折无阻断项；用户决定保留什么、修改什么。",
    },
}


def _guide_focus(
    step: int, medium: str, *, welcome: bool = False, resume: bool = False
) -> dict[str, object]:
    """Return one calm, creative step instead of a command wall."""
    source = next(item for item in _GUIDE_STEPS if int(item["step"]) == step)
    item = dict(source)
    if medium == "script" and step in _SCRIPT_GUIDE_OVERRIDES:
        item.update(_SCRIPT_GUIDE_OVERRIDES[step])
    masters = list(item.get("masters") or [])
    if masters:
        item["masters"] = masters[:1]
    item["lenses"] = _GUIDE_CREATIVE_LENSES[step]
    item["interaction"] = {
        "ask": item.get("prompt"),
        "how": "先听用户自由表达；只有表达停滞时才从三个观察角度中选一个启发，不要逐项盘问。",
        "agent_response": "先用一句话复述你听懂的创作意图，再提出一个具体候选；不要讲术语，不要先贴命令。",
        "decision": "请用户选择：保留、调整，或换一个方向。一次只处理一个决定。",
    }
    item["completion"] = item.get("verify")
    item["recovery"] = {
        "mode": "soft-return",
        "trigger": "仅在连续 3-4 轮没有推进当前决定或形成可用素材、进入下一阶段前仍有关键缺口、或新旧设定冲突时使用。",
        "capture": "先从刚才对话中提炼最多 3 条有价值的新素材；不要把发散描述为错误。",
        "bridge": "用一句话说明这些素材如何服务当前作品，再指出当前步骤只剩的一个决定。",
        "invite": f"用当前主问题温和邀请：{item.get('prompt')}；同时明确用户可以继续探索。",
        "choices": ["回到当前决定", "再探索一会儿", "把当前步骤换成更合适的问题"],
        "must_not": ["警告用户偏离流程", "丢弃刚才的灵感", "强制进入下一步", "重复整套路线"],
    }
    item["next_step"] = (
        None
        if step == 10
        else {
            "step": step + 1,
            "command": f"scriptnow guide --step {step + 1} --medium {medium}",
            "handoff": "本步完成并经用户认可后再进入下一步；不要提前抛出后续命令。",
        }
    )
    payload: dict[str, object] = {
        "guide": "scriptnow-creative-companion",
        "title": f"创作工作室 · 第 {step} 幕 / 10",
        "mode": "focused-step",
        "medium": medium,
        "medium_label": "小说" if medium == "novel" else "剧本",
        "step": item,
        "map_command": "scriptnow guide --steps",
        "resuming": resume,
    }
    if welcome:
        payload["opening"] = (
            "先别急着学命令。我们从你脑海里最舍不得放下的那个人、那个画面或那个问题开始。"
            "你负责判断什么值得写，我负责把模糊的念头整理成可以继续创作的候选。"
        )
    if resume:
        payload["opening"] = (
            "刚才的探索不是绕路。我会先把其中有价值的东西收好，再轻轻接回我们尚未完成的那个决定；"
            "如果灵感还在生长，也可以继续聊。"
        )
    return payload


def _guide_pulse(step: int, medium: str, value: str) -> dict[str, object]:
    """Assess conversational drift without writing workflow or project state."""
    raw = Path(value[1:]).read_text(encoding="utf-8") if value.startswith("@") else value
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise click.ClickException(f"pulse JSON 解析失败：{error}") from error
    if not isinstance(data, dict):
        raise click.ClickException("pulse JSON 根必须是对象")

    def short_list(key: str) -> list[str]:
        source = data.get(key) or []
        if not isinstance(source, list):
            raise click.ClickException(f"pulse.{key} 必须是字符串数组")
        return [str(item).strip()[:300] for item in source if str(item).strip()][:5]

    try:
        quiet_rounds = max(0, min(20, int(data.get("rounds_without_progress") or 0)))
    except (TypeError, ValueError) as error:
        raise click.ClickException("pulse.rounds_without_progress 必须是整数") from error
    captured = short_list("captured_material")
    unresolved = short_list("unresolved")
    conflicts = short_list("conflicts")
    decision_advanced = bool(data.get("decision_advanced"))
    next_stage_requested = bool(data.get("next_stage_requested"))

    if conflicts:
        pulse_status = "conflict"
        reason = "新旧创作设定出现冲突，需要一次温和取舍。"
    elif next_stage_requested and unresolved:
        pulse_status = "drifting"
        reason = "准备进入下一阶段，但当前仍有一个关键决定未完成。"
    elif quiet_rounds >= 4 and not captured and not decision_advanced:
        pulse_status = "drifting"
        reason = "连续多轮既未推进当前决定，也没有形成可回填素材。"
    elif captured and not decision_advanced:
        pulse_status = "useful_detour"
        reason = "讨论暂时离开当前决定，但形成了值得保留的新素材。"
    else:
        pulse_status = "on_track"
        reason = "对话仍在推进当前创作，或发散尚未影响流程衔接。"

    should_return = pulse_status in {"drifting", "conflict"}
    payload = _guide_focus(step, medium, resume=should_return)
    payload["pulse"] = {
        "status": pulse_status,
        "reason": reason,
        "should_invite_return": should_return,
        "captured_material": captured,
        "unresolved": unresolved,
        "conflicts": conflicts,
        "return_prompt": payload["step"]["prompt"] if should_return else None,
        "user_freedom": "用户可以选择回归、继续探索或重写当前问题；CLI 不改变任何平台状态。",
    }
    return payload


def _guide_full() -> dict[str, object]:
    return {
        "guide": "scriptnow-newcomer",
        "title": "ScriptNow 新手模式 —— 你既是主编，也是编剧",
        "opening": (
            "夜已深，台灯亮着。你面前是一张空白稿纸——不是让你独自对着它枯坐，"
            "而是请来一位不知疲倦的创作搭档，陪你把脑中的故事一个字一个字地落到纸上。"
            "ScriptNow 就是这间工作室：你决定故事的方向，Agent 与你并肩完成每一章。"
        ),
        "vision": (
            "ScriptNow 不是又一个生成器，而是一个以你为决策者的共创工作室："
            "Agent 是你的联合创作者——它提议（候选），你裁决（采纳），每个版本都可回溯。"
            "你不是在让 AI 替你写，而是在和一位不知疲倦的搭档共同完成作品。"
            "你获得的是创作的主导权，Agent 提供的是永不枯竭的灵感与执行力。"
        ),
        "editor_craft": [
            "编辑能力：先规划后动笔——故事核心、蓝图、卷章结构逐层把关，采纳前一切可改。",
            "编剧能力：逐场/逐章创作、风格锚点、伏笔与连续性维护，Agent 严格按方向执行。",
            "修订能力：生成候选与人工修订同一套版本管理，随时回退到任一历史版本。",
            "交付能力：质量门禁（planning-quality / chapter quality / scene quality）+ 封面 + 导出，一站成书。",
        ],
        "how_it_works": [
            "回填优先：Agent 本地创作经 propose 回传为候选，平台生成仅作后备——创作主力是你与 Agent 的协作。",
            "候选 → 采纳：采纳才进入正典；未采纳的候选不影响当前正文，可对比、可弃用。",
            "模型可选：chapter/scene generate --model 可为本项目写作指定模型，仅限项目内使用。",
            "双域统一：小说（卷×章）与剧本（季×场）命令对称，一套心智走两域。",
        ],
        "closing": (
            "从一句话前提，到一部可以交付的作品——这不是魔法，而是你与 Agent 一次次"
            "「提议 → 裁决 → 采纳」的共同创作。愿这间工作室见证你的每一个故事。"
        ),
        "masters": (
            "这一路，海明威、契诃夫、黑泽明、斯蒂芬·金、宫崎骏、王家卫、鲁迅、老舍、"
            "马尔克斯、塔可夫斯基……无数创作者的精神与你同行：他们也曾面对空白稿纸，"
            "也曾反复修订，也曾怀疑自己。你此刻的每一步，都是他们走过的路；"
            "而你要写的故事，只有你能写。"
        ),
        "gallery": [
            {"name": "鲁迅", "quote": "哪里有天才？我是把别人喝咖啡的工夫都用在工作上的。", "source": "鲁迅自述"},
            {"name": "老舍", "quote": "把普通的字用得飘飘欲仙，见出作者的苦心孤诣。", "source": "《老舍谈写作》"},
            {"name": "海明威", "quote": "一切初稿都是狗屎。", "source": "对《巴黎评论》所说"},
            {"name": "契诃夫", "quote": "简洁是天才的姐妹。", "source": "契诃夫书信"},
            {"name": "马尔克斯", "quote": "生活不是我们活过的日子，而是我们记住的日子。", "source": "《活着为了讲述》"},
            {"name": "塔可夫斯基", "quote": "导演工作的本质，可以定义为雕刻时光。", "source": "《雕刻时光》"},
            {"name": "斯蒂芬·金", "quote": "关起门来写初稿，打开门来修改。", "source": "《写作这回事》"},
            {"name": "黑泽明", "quote": "创作是美妙的。", "source": "纪录片《黑泽明：创作是美妙的》"},
            {"name": "宫崎骏", "quote": "创作就是生活本身。", "source": "访谈（转述）"},
            {"name": "王家卫", "quote": "电影是时间的艺术。", "source": "访谈（转述）"},
            {"name": "余华", "quote": "写作的过程，就是不断发现自己内心真实想法的过程。", "source": "余华谈写作（访谈）"},
            {"name": "加缪", "quote": "创作，就是给人每天的生活中多一种命运。", "source": "加缪札记（转述）"},
        ],
        "next": _guide_steps(),
    }


def _echo_guide(payload: dict[str, object]) -> None:
    click.echo(ui.section(f"=== {payload['title']} ==="), err=True)
    if "opening" in payload:
        click.echo(ui.paint(payload["opening"], ui.GOLD), err=True)
        click.echo("", err=True)
    if payload.get("mode") == "focused-step":
        item = dict(payload["step"])
        click.echo(ui.ok(f"{item['title']} · {payload['medium_label']}"), err=True)
        click.echo(ui.dim(str(item.get("scene") or "")), err=True)
        click.echo("", err=True)
        pulse = payload.get("pulse")
        if pulse:
            click.echo(ui.dim(f"创作脉搏：{pulse['reason']}"), err=True)
            if pulse.get("captured_material"):
                click.echo(ui.dim("刚才值得收好的灵感："), err=True)
                for material in pulse["captured_material"][:3]:
                    click.echo(f"  · {material}", err=True)
            click.echo("", err=True)
        click.echo(ui.paint(f"现在只想一件事：{item['prompt']}", ui.CYAN), err=True)
        click.echo(ui.dim("如果一时没有答案，可以任选一个角度开口："), err=True)
        for lens in item.get("lenses") or []:
            click.echo(f"  · {lens}", err=True)
        click.echo("", err=True)
        click.echo(ui.dim("你说完后，创作搭档应先复述理解，再给一个具体候选；你只需决定保留、调整或换方向。"), err=True)
        if payload.get("resuming"):
            click.echo(ui.dim("先收好刚才产生的新素材，再邀请你选择："), err=True)
            for choice in item["recovery"]["choices"]:
                click.echo(f"  · {choice}", err=True)
        masters = item.get("masters") or []
        if masters:
            master = masters[0]
            click.echo(ui.paint(f"「{master['quote']}」—— {master['name']}", ui.GOLD), err=True)
        click.echo("", err=True)
        click.echo(ui.dim("◆ 幕后操作（由 Agent 执行，你不需要记）"), err=True)
        click.echo(f"  {item['command']}", err=True)
        click.echo(ui.dim(f"  完成标志：{item['completion']}"), err=True)
        next_step = item.get("next_step")
        if next_step:
            click.echo(ui.ok(f"完成后进入第 {next_step['step']} 幕：{next_step['command']}"), err=True)
        else:
            click.echo(ui.ok("作品闭环完成。工作室的门随时为你打开。"), err=True)
        click.echo(ui.dim(f"完整路线：{payload['map_command']}"), err=True)
        return
    if "vision" in payload:
        click.echo(ui.dim("◆ 共创愿景"), err=True)
        click.echo(ui.paint(payload["vision"], ui.GOLD), err=True)
        click.echo("", err=True)
        click.echo(ui.dim("◆ 编辑/编剧能力（ScriptNow 能为你做什么）"), err=True)
        for item in payload["editor_craft"]:
            click.echo(f"  · {item}", err=True)
        click.echo("", err=True)
        click.echo(ui.dim("◆ 共创方式（人机如何一起工作）"), err=True)
        for item in payload["how_it_works"]:
            click.echo(f"  · {item}", err=True)
        click.echo("", err=True)
        steps = payload["next"]["steps"]
    else:
        steps = payload["steps"]
    click.echo(ui.dim("◆ 完整作品向导（短篇/短剧闭环）"), err=True)
    for item in steps:
        click.echo(ui.ok(f"Step {item['step']} · {item['title']}"), err=True)
        if item.get("scene"):
            click.echo(ui.dim(f"    {item['scene']}"), err=True)
        click.echo(f"    为什么：{item['why']}", err=True)
        click.echo(f"    命令：  {item['command']}", err=True)
        click.echo(f"    验证：  {item['verify']}", err=True)
        if item.get("prompt"):
            click.echo(ui.paint(f"    ➤ 想一想：{item['prompt']}", ui.CYAN), err=True)
        masters = item.get("masters") or ([item["master"]] if item.get("master") else [])
        for master in masters:
            source = master.get("source") or ""
            attribution = f"—— {master['name']}" + (f"，{source}" if source else "")
            click.echo(ui.paint(f"    「{master['quote']}」{attribution}", ui.GOLD), err=True)
            click.echo(ui.dim(f"    {master['how']}"), err=True)
    if payload.get("closing"):
        click.echo("", err=True)
        click.echo(ui.paint(payload["closing"], ui.GOLD), err=True)
    if payload.get("masters"):
        click.echo("", err=True)
        click.echo(ui.dim("◆ 大师同行"), err=True)
        click.echo(ui.paint(payload["masters"], ui.GOLD), err=True)
    gallery = payload.get("gallery")
    if gallery:
        click.echo("", err=True)
        click.echo(ui.dim("◆ 大师长廊（灵感随时取用）"), err=True)
        for entry in gallery:
            src = f"，{entry['source']}" if entry.get("source") else ""
            click.echo(
                ui.dim(f"  · 「{entry['quote']}」—— {entry['name']}{src}"), err=True
            )
    click.echo("", err=True)
    click.echo(ui.dim("提示：请 Agent 读取本向导并逐级引导你完成；完成全部步骤后运行 scriptnow guide --complete。"), err=True)


@main.command()
@click.option("--host", required=True, help="Platform base URL, e.g. https://sn.igeewa.com")
@click.option("--email", required=True)
@click.option(
    "--password",
    default=None,
    hide_input=True,
    help="密码。为安全起见不建议在命令行传明文：可省略后交互式隐藏输入，或用 --password-stdin / 环境变量 SCRIPTNOW_PASSWORD 传入",
)
@click.option(
    "--password-stdin",
    is_flag=True,
    help="从标准输入读取密码（管道/agent 安全传入，不落 shell history 与进程列表）",
)
@click.option("--json", "json_output", is_flag=True)
def login_cmd(host: str, email: str, password: str | None, password_stdin: bool, json_output: bool) -> None:
    """Authenticate and persist a session (cookie + CSRF).

    密码安全传递（按优先级）：
      1. --password-stdin：从标准输入读取（推荐给 agent/脚本，不落历史与进程表）
      2. 环境变量 SCRIPTNOW_PASSWORD（agent 场景）
      3. 省略 --password：交互式隐藏输入（getpass，屏幕上不显示、不落历史）
      4. --password <明文>：仅兼容旧脚本；明文会出现在 shell history，尽量不用
    """
    import getpass as _getpass
    import os as _os

    if password is None:
        if password_stdin:
            password = click.get_text_stream("stdin").readline().rstrip("\n")
        else:
            env_password = _os.environ.get("SCRIPTNOW_PASSWORD")
            if env_password:
                password = env_password
            else:
                password = _getpass.getpass("密码（输入时不显示）: ")
    if not password:
        raise click.ClickException("密码不能为空——请重新运行 scriptnow login")
    try:
        session = login(host, email, password)
    except ScriptNowError as error:
        raise click.ClickException(str(error)) from error
    password = None  # 用完即弃，避免残留在栈上
    if not json_output:
        click.echo(ui.ok(f"登录成功：{host}（{email}）"))
        if not _onboarding_done():
            click.echo(
                ui.warn("第一次来？小说运行 scriptnow guide --medium novel；剧本运行 --medium script。我们从一个念头开始。"),
                err=True,
            )
    _emit({"ok": True, "base_url": session.base_url, "user": email}, json_output)


# ------------------------------------------------------------------------ projects


@main.group("project")
@click.pass_context
def project_group(ctx: click.Context) -> None:
    """项目管理：创建作品、上传素材、查看与删除。"""


@project_group.command("list")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def project_list(ctx: click.Context, json_output: bool) -> None:
    """列出你的全部作品。"""
    result = _session(ctx).request("GET", "/projects")
    if not json_output and isinstance(result, list):
        if not result:
            click.echo(ui.dim("还没有作品——先 project create 建一个吧。"), err=True)
            return
        medium_label = {"novel": "小说", "script": "剧本"}
        click.echo(ui.section("=== 我的作品 ==="), err=True)
        for item in result:
            name = item.get("name") or item.get("id") or "未命名"
            medium = medium_label.get(item.get("medium") or "", item.get("medium") or "")
            premise = (item.get("premise") or "")[:40]
            status = _status_word(item.get("status"), medium=item.get("medium") or "novel")
            line = f"  {name}（{medium} · {status}）"
            if premise:
                line += f"\n      {premise}"
            click.echo(line, err=True)
            click.echo(ui.dim(f"      作品号 {item.get('id')}"), err=True)
        return
    _emit(result, json_output)


@project_group.command("create")
@click.option("--name", required=True)
@click.option("--medium", type=click.Choice(["novel", "script"]), default="novel")
@click.option("--source-mode", type=click.Choice(["original", "adaptation"]), default="original")
@click.option("--workflow-kind", default=None, help="e.g. cross_cultural_recreation")
@click.option("--genre", default="", help="类型标签（逗号分隔），如 mystery,werewolf")
@click.option("--premise", default="", help="故事前提/核心设定")
@click.option("--tone", default="", help="文风基调，如 少比喻、以动作体现情绪")
@click.option("--world-setting", default="", help="世界观设定")
@click.option("--language", default="zh-CN")
@click.option("--styles", default=None, help="文风标签（逗号分隔），如 heroic-epic")
@click.option("--structure", default="", help="叙事结构，如 hero_journey / three_act / custom")
@click.option("--script-format", default="", help="剧本格式（仅 script），如 chinese / hollywood")
@click.option("--volume-one", default="1", help="卷数（novel）或季数（script）")
@click.option("--volume-two", default="15", help="每卷章数（novel）或每季场次（script），可写区间如 20-30")
@click.option("--volume-three", default="", help="第三维规模（script 用）")
@click.option("--chapter-target-words", default="1200", help="每章目标字数（novel）")
@click.option("--creative-variance", type=click.Choice(["focused", "balanced", "exploratory"]), default="balanced", help="创意发散程度")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def project_create(
    ctx: click.Context,
    name: str,
    medium: str,
    source_mode: str,
    workflow_kind: str | None,
    genre: str,
    premise: str,
    tone: str,
    world_setting: str,
    language: str,
    styles: str | None,
    structure: str,
    script_format: str,
    volume_one: str,
    volume_two: str,
    volume_three: str,
    chapter_target_words: str,
    creative_variance: str,
    json_output: bool,
) -> None:
    """创建作品项目（补全平台要求的完整创作方向）。

    平台新建项目需要完整的 direction 设定（卷数/章数/字数/结构/风格等），
    否则后续生成 StoryMap/章节会缺少必要配置。CLI 已按平台要求补齐默认值：
    小说 1 卷 15 章、每章 1200 字、hero_journey 结构；剧本同理可设场次与格式。
    """
    direction: dict[str, Any] = {
        "language": language,
        "genre": genre,
        "premise": premise,
        "tone": tone,
        "world_setting": world_setting,
        "structure": structure or ("hero_journey" if medium == "novel" else "three_act"),
        "volume_one": volume_one,
        "volume_two": volume_two,
        "volume_three": volume_three,
        "chapter_target_words": chapter_target_words,
        "creative_variance": creative_variance,
    }
    if styles:
        direction["styles"] = [item.strip() for item in styles.split(",") if item.strip()]
    if medium == "script":
        direction["script_format"] = script_format or "chinese"
    body: dict[str, Any] = {
        "name": name,
        "medium": medium,
        "source_mode": source_mode,
        "direction": direction,
    }
    if workflow_kind:
        body["workflow_kind"] = workflow_kind
    # 幂等键 = 请求参数指纹：网络超时后重试同一条命令会命中同一项目，
    # 不会产生重复项目（后端按 creation_idempotency_key 去重）。
    import hashlib as _hashlib

    fingerprint = _hashlib.sha256(
        (
            name
            + "\x00"
            + medium
            + "\x00"
            + source_mode
            + "\x00"
            + json.dumps(direction, sort_keys=True, ensure_ascii=False)
        ).encode("utf-8")
    ).hexdigest()[:24]
    body["idempotency_key"] = f"cli-create-{fingerprint}"
    session = _session(ctx)
    created = session.request("POST", "/projects", json_body=body, write=True)
    project_id = str(created.get("id") or "")
    verified = False
    if project_id:
        # 自动回读：立即从平台拉取项目列表，确认已落盘（服务器回读才是完成依据）。
        try:
            listing = session.request("GET", "/projects")
            items = listing if isinstance(listing, list) else listing.get("items", [])
            verified = any(str(item.get("id")) == project_id for item in items)
        except ScriptNowError:
            verified = False
    receipt = {
        "command": "project create",
        "project_id": project_id,
        "name": name,
        "medium": medium,
        "idempotency_key": body["idempotency_key"],
        "verified": verified,
    }
    _emit(receipt, json_output)
    if not json_output and not verified and project_id:
        click.echo(
            ui.warn("项目已创建但回读未确认；请运行 scriptnow project list 复核。"),
            err=True,
        )


@project_group.command("upload")
@click.argument("project_id")
@click.argument("file_path", type=str)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def project_upload(ctx: click.Context, project_id: str, file_path: str, json_output: bool) -> None:
    """Upload a source file to a project (indexes the text synchronously)."""
    with open(file_path, "rb") as handle:
        result = _session(ctx).request(
            "POST",
            f"/projects/{project_id}/files",
            files={"file": (Path(file_path).name, handle)},
            write=True,
        )
    _emit(result, json_output)


@project_group.command("files")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def project_files(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """List project files."""
    _emit(_session(ctx).request("GET", f"/projects/{project_id}/files"), json_output)


@project_group.command("delete")
@click.argument("project_id")
@click.option("--confirm-name", required=True, help="Project name to confirm deletion (safety)")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def project_delete(ctx: click.Context, project_id: str, confirm_name: str, json_output: bool) -> None:
    """Delete a project and its contents (requires the exact project name)."""
    result = _session(ctx).request(
        "DELETE",
        f"/projects/{project_id}",
        json_body={"confirmation_name": confirm_name},
        write=True,
    )
    _emit({"ok": True, "project_id": project_id} if result is None else result, json_output)


@project_group.command("direction")
@click.argument("project_id")
@click.option("--inspire", default=None, help="平台灵感模式：给一句话种子，由平台 AI 生成方向并写入")
@click.option("--apply", "apply_json", default=None, help="客户端回填：JSON 字符串或 @文件路径，Agent 梳理好的完整方向一次写入")
@click.option("--language", default=None, help="灵感模式语言（默认 zh-CN）")
@click.option("--genres", default=None, help="灵感模式：逗号分隔的类型提示，如 mystery,werewolf")
@click.option("--variance", type=click.Choice(["balanced", "high", "low"]), default="balanced", help="灵感模式：创意发散程度")
@click.option("--set", "set_pairs", multiple=True, help="手动补齐字段：--set key=value（可多次），如 --set tone=暗黑 --set genre=\"mystery, werewolf\"")
@click.option("--show", is_flag=True, help="仅查看当前创作方向")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def project_direction(
    ctx: click.Context,
    project_id: str,
    inspire: str | None,
    apply_json: str | None,
    language: str | None,
    genres: str | None,
    variance: str,
    set_pairs: tuple[str, ...],
    show: bool,
    json_output: bool,
) -> None:
    """查看 / 灵感生成 / 客户端梳理回填 / 手动补齐项目的创作方向（direction）。

    推荐流程（客户端 Agent 梳理 → 回填，作为优先项）：
      1. 客户端 Agent 先了解创作要求，梳理出完整方向（premise/tone/
         world_setting/genre/structure/volume/字数 等）。
      2. 用 --apply 一次写入：
         scriptnow project direction <pid> --apply '{"premise":"...","tone":"...",...}'
         或 --apply @direction.json（从文件读）。
    优先级：--set（手动指定）> --apply（Agent 梳理回填）> --inspire（平台 AI）。
    --inspire 只填充 Agent 未提供的空缺字段，不会覆盖 --apply 的方向。
    备选：
      --inspire：交给平台 AI 根据一句话种子生成方向（仅补缺）。
      --set key=value：手动补齐单个字段（最高优先级）。
    """
    session = _session(ctx)
    if show and not inspire and not apply_json and not set_pairs:
        projects = session.request("GET", "/projects")
        project = next((item for item in projects if item.get("id") == project_id), None)
        if project is None:
            raise click.ClickException(f"project {project_id} not found")
        _emit(dict(project.get("direction") or {}), json_output)
        return
    direction: dict[str, Any] = {}
    if apply_json:
        import json as _json

        raw = apply_json
        if raw.startswith("@"):
            raw = Path(raw[1:]).read_text(encoding="utf-8")
        try:
            parsed = _json.loads(raw)
        except _json.JSONDecodeError as error:
            raise click.ClickException(f"--apply 需要合法 JSON：{error}") from error
        if not isinstance(parsed, dict):
            raise click.ClickException("--apply 需要 JSON 对象（键值对）")
        direction.update(parsed)
        if not json_output:
            click.echo(f"已读取客户端梳理方向：{sorted(parsed.keys())}", err=True)
    if inspire:
        body: dict[str, Any] = {
            "medium": "novel",
            "seed": inspire,
            "language": language or "zh-CN",
            "genres": [g.strip() for g in (genres or "").split(",") if g.strip()],
            "creative_variance": variance,
        }
        insp = session.request("POST", "/creative-inspiration", json_body=body, write=True, timeout=180)
        # Agent-梳理方向（--apply）优先：平台 AI 生成的字段只填充客户端未
        # 提供的空缺，绝不覆盖 agent 已梳理好的方向；--set 手动字段在之后
        # 统一覆盖，保持 手动 > agent 梳理 > 平台 AI 的优先级。
        direction.setdefault("premise", str(insp.get("premise") or "").strip())
        direction.setdefault("tone", str(insp.get("tone") or "").strip())
        direction.setdefault("world_setting", str(insp.get("world_setting") or "").strip())
        suggested = [str(g).strip() for g in (insp.get("genre_suggestions") or []) if str(g).strip()]
        if suggested and not direction.get("genre"):
            direction["genre"] = ", ".join(suggested[:4])
        if not json_output:
            echo_mode = "平台 AI 补全空缺" if direction.get("premise") or direction.get("tone") else "平台 AI 生成"
            click.echo(
                f"{echo_mode}：{insp.get('title')}（模型 {insp.get('model_key')}）", err=True
            )
    for pair in set_pairs:
        if "=" not in pair:
            raise click.ClickException(f"--set 需要 key=value 格式，收到：{pair}")
        key, value = pair.split("=", 1)
        direction[key.strip()] = value.strip()
    if not direction:
        raise click.ClickException("请提供 --apply 梳理结果、--inspire 种子文本、--set 字段，或 --show 查看当前方向")
    updated = session.request(
        "PATCH",
        f"/projects/{project_id}/direction",
        json_body={"direction": direction},
        write=True,
    )
    result = {
        "project_id": project_id,
        "updated_fields": sorted(direction.keys()),
        "direction": dict(updated.get("direction") or {}),
    }
    _emit(result, json_output)


@main.group("run")
@click.pass_context
def run_group(ctx: click.Context) -> None:
    """Inspect background runs and their event streams."""


@run_group.command("status")
@click.argument("run_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def run_status(ctx: click.Context, run_id: str, json_output: bool) -> None:
    """Show a run's status (queued/running/waiting/succeeded/failed)."""
    _emit(_session(ctx).request("GET", f"/runs/{run_id}"), json_output)


@run_group.command("events")
@click.argument("run_id")
@click.option("--last-event-id", default=None, help="Resume from a specific event id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def run_events(ctx: click.Context, run_id: str, last_event_id: str | None, json_output: bool) -> None:
    """Show a run's event stream (generation trace)."""
    session = _session(ctx)
    headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
    response = session.request(
        "GET",
        f"/runs/{run_id}/events",
        headers=headers,
        timeout=60,
        raw=True,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    _emit(payload, json_output)


# -------------------------------------------------------------- admin（仅管理员）


def _api_request(ctx: click.Context, method: str, path: str, **kwargs: Any) -> Any:
    """Admin / skill-evolution requests with friendly error rendering
    (auth failures and 4xx/5xx surface as ClickException, not a traceback)."""
    try:
        return _session(ctx).request(method, path, **kwargs)
    except ScriptNowError as error:
        raise click.ClickException(str(error)) from error


@main.group("admin")
@click.pass_context
def admin_group(ctx: click.Context) -> None:
    """管理员专用支线（后端 is_admin 校验，非管理员一律 403）：
    平台系统状态 / 租户状态 / 主站 Skill 治理与进化。
    注意：涉及 token 消费、额度与财务的命令一律不纳入 CLI（走管理后台）。"""


def _admin_summary(result: dict[str, object]) -> None:
    """Human-readable summary for admin outputs (kept thin; --json is the contract)."""
    click.echo(ui.section("=== 平台系统状态 ==="), err=True)
    for item in result.get("items", []) or []:
        status = str(item.get("status") or "unobserved")
        mark = ui.ok(status) if status == "healthy" else ui.error(status)
        click.echo(f"  {ui.kv(item.get('key'), item.get('label'))} {mark} — {item.get('summary')}", err=True)
    click.echo(ui.dim(f"overall: {result.get('overall_status')}"), err=True)


@admin_group.command("status")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def admin_status(ctx: click.Context, json_output: bool) -> None:
    """平台系统状态（数据库 / 模型服务 / 队列等能力级诊断）。"""
    result = _api_request(ctx, "GET", "/admin/api/system-status")
    if not json_output:
        _admin_summary(result)
        return
    _emit(result, json_output)


@admin_group.command("tenant-status")
@click.argument("tenant_id")
@click.argument("status", type=click.Choice(["active", "suspended"]))
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def admin_tenant_status(ctx: click.Context, tenant_id: str, status: str, json_output: bool) -> None:
    """启用 / 暂停租户（不能暂停当前管理员所在租户）。"""
    _api_request(
        ctx,
        "PATCH",
        f"/admin/api/tenants/{tenant_id}/status",
        json_body={"status": status},
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"租户 {tenant_id} → {status}"))
    else:
        _emit({"tenant_id": tenant_id, "status": status}, json_output)


@admin_group.command("skills")
@click.option("--domain", type=click.Choice(["platform", "novel", "script"]), default=None)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def admin_skills(ctx: click.Context, domain: str | None, json_output: bool) -> None:
    """主站 Skill 目录（能力 / 准入 / 质量状态）。"""
    params = {"domain": domain} if domain else None
    result = _api_request(ctx, "GET", "/admin/api/skills", params=params)
    if not json_output:
        click.echo(ui.section("=== 主站 Skill 目录 ==="), err=True)
        for item in (result.get("skills") or [])[:60]:
            click.echo(
                f"  {ui.kv(item['name'], item.get('description'))} "
                f"[{item.get('domain')}] admission={item.get('admission_status')} quality={item.get('quality_status')}",
                err=True,
            )
        return
    _emit(result, json_output)


@admin_group.command("skill-show")
@click.argument("skill_name")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def admin_skill_show(ctx: click.Context, skill_name: str, json_output: bool) -> None:
    """主站 Skill 详情（含 instructions 全文与准入基准）。"""
    result = _api_request(ctx, "GET", f"/admin/api/skills/{skill_name}")
    if not json_output:
        _emit({k: v for k, v in result.items() if k != "instructions"}, json_output)
        click.echo(ui.dim(f"instructions（{len(result.get('instructions') or '')} 字符）见 --json"), err=True)
        return
    _emit(result, json_output)


@admin_group.command("skill-update")
@click.argument("skill_name")
@click.option("--description", required=True)
@click.option("--instructions", required=True, help="新指令全文（能力进化，最长 100,000）")
@click.option("--expected-digest", required=True, help="当前版本 digest（64 位 hex，防并发覆盖）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def admin_skill_update(
    ctx: click.Context,
    skill_name: str,
    description: str,
    instructions: str,
    expected_digest: str,
    json_output: bool,
) -> None:
    """更新主站 Skill（能力进化，写操作；digest 不匹配则拒绝）。"""
    result = _api_request(
        ctx,
        "PUT",
        f"/admin/api/skills/{skill_name}",
        json_body={
            "description": description,
            "instructions": instructions,
            "expected_digest": expected_digest,
        },
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"Skill《{skill_name}》已更新并保存新版本"))
    _emit(result, json_output)


@admin_group.command("supply")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def admin_supply(ctx: click.Context, json_output: bool) -> None:
    """模型供给总览：第三方提供商 / 语言模型 / 生图模型 / 等级。"""
    result = _api_request(ctx, "GET", "/admin/api/supply")
    if not json_output:
        click.echo(ui.section("=== 提供商 ==="), err=True)
        for item in (result.get("providers") or [])[:30]:
            mark = ui.ok("connected") if item.get("status") == "connected" else ui.error(item.get("status"))
            click.echo(
                f"  {ui.kv(item.get('id'), item.get('name'))} {item.get('key')} {mark} "
                f"{item.get('base_url') or ''}",
                err=True,
            )
        click.echo(ui.section("=== 语言模型 ==="), err=True)
        for item in (result.get("models") or [])[:30]:
            click.echo(
                f"  {ui.kv(item.get('key'), item.get('display_name'))} "
                f"[{item.get('provider_name')}] {item.get('agentscope_class')} "
                f"min_tier={item.get('min_tier_code')} {'✓' if item.get('enabled') else '✗'}",
                err=True,
            )
        return
    _emit(result, json_output)


@admin_group.command("provider-connect")
@click.option("--key", required=True, help="provider key（小写字母数字下划线，如 beeapi）")
@click.option("--name", required=True, help="显示名，如 BeeAPI (OpenAI-compatible)")
@click.option("--base-url", required=True, help="OpenAI 兼容接口地址，如 https://beeapi.ai/v1")
@click.option("--credential", required=True, help="API Key（写操作，不会回显/存储明文外的内容）")
@click.option("--usage", type=click.Choice(["general", "evaluation", "economy"]), default="general")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def admin_provider_connect(
    ctx: click.Context,
    key: str,
    name: str,
    base_url: str,
    credential: str,
    usage: str,
    json_output: bool,
) -> None:
    """一步接入第三方 OpenAI 兼容提供商：验证 → 探测模型 → 同步 → 绑定最低等级。

    如 openai SDK：OpenAI(api_key=..., base_url=...) —— 本命令注册同款
    base_url + api_key，之后 AgentScope 以 OpenAIChatModel 调用。
    """
    result = _api_request(
        ctx,
        "POST",
        "/admin/api/providers/connect",
        json_body={
            "key": key,
            "name": name,
            "base_url": base_url,
            "credential": credential,
            "default_usage": usage,
        },
        write=True,
        timeout=120,
    )
    if not json_output:
        provider = result.get("provider") or {}
        click.echo(ui.ok(f"提供商已接入：{provider.get('name')}（{provider.get('key')}，{provider.get('status')}）"))
        synced = result.get("synchronized_models") or []
        click.echo(ui.dim(f"同步模型 {len(synced)} 个：{', '.join(m.get('key') for m in synced[:20])}"), err=True)
    _emit(result, json_output)


@admin_group.command("model-add")
@click.option("--key", required=True, help="模型 key，如 gpt-5.1")
@click.option("--name", required=True, help="显示名")
@click.option("--provider", "provider_id", required=True, help="提供商 id（admin supply 查看）")
@click.option("--class", "agentscope_class", default="OpenAIChatModel", help="AgentScope 模型类")
@click.option("--tier", "min_tier_code", required=True, help="最低可用等级代码")
@click.option("--in-price", type=float, required=True, help="输入价格（美元/百万 token）")
@click.option("--out-price", type=float, required=True, help="输出价格（美元/百万 token）")
@click.option("--context", type=int, default=32768, help="上下文窗口")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def admin_model_add(
    ctx: click.Context,
    key: str,
    name: str,
    provider_id: str,
    agentscope_class: str,
    min_tier_code: str,
    in_price: float,
    out_price: float,
    context: int,
    json_output: bool,
) -> None:
    """手动注册语言模型（connect 未发现时用）。"""
    result = _api_request(
        ctx,
        "POST",
        "/admin/api/models",
        json_body={
            "key": key,
            "display_name": name,
            "provider_id": provider_id,
            "agentscope_class": agentscope_class,
            "min_tier_code": min_tier_code,
            "input_price_per_million": in_price,
            "output_price_per_million": out_price,
            "context_window": context,
            "enabled": True,
        },
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"模型已注册：{result.get('key')}（{result.get('display_name')}，enabled={result.get('enabled')}）"))
    _emit(result, json_output)


@admin_group.command("image-model-add")
@click.option("--key", required=True, help="生图模型 key，如 gpt-image-2 / grok-imagine-image-2.0 / nanobanana")
@click.option("--name", required=True, help="显示名")
@click.option("--provider", "provider_id", required=True, help="提供商 id（admin supply 查看）")
@click.option("--protocol", type=click.Choice(["grsai_image2", "openai_images"]), default="openai_images")
@click.option("--endpoint-path", default=None, help="生图端点路径（openai_images 默认 /images/generations）")
@click.option("--tier", "min_tier_code", required=True, help="最低可用等级代码")
@click.option("--price", type=float, default=0.0, help="单张价格")
@click.option("--size", default="1024x1024", help="openai_images 尺寸（模型支持的枚举，如 1024x1024）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def admin_image_model_add(
    ctx: click.Context,
    key: str,
    name: str,
    provider_id: str,
    protocol: str,
    endpoint_path: str | None,
    min_tier_code: str,
    price: float,
    size: str,
    json_output: bool,
) -> None:
    """注册生图模型（openai_images = OpenAI 兼容 images/generations；grsai_image2 = GRSAI 代理）。"""
    result = _api_request(
        ctx,
        "POST",
        "/admin/api/image-models",
        json_body={
            "key": key,
            "display_name": name,
            "provider_id": provider_id,
            "protocol": protocol,
            "endpoint_path": endpoint_path
            or ("/images/generations" if protocol == "openai_images" else "/v1/api/generate"),
            "min_tier_code": min_tier_code,
            "price_per_image": price,
            "default_parameters": {"size": size, "n": 1},
            "enabled": True,
        },
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"生图模型已注册：{result.get('key')}（{result.get('display_name')}，{result.get('protocol')}，enabled={result.get('enabled')}）"))
    _emit(result, json_output)


# ------------------------------------------------------------ work interpretation


@main.group("interpret")
@click.pass_context
def interpret_group(ctx: click.Context) -> None:
    """一书一 Skill：上传作品，通读生成「源分析 + 创作方法论」双卡。"""


@interpret_group.command("go")
@click.argument("file_path", type=str)
@click.option("--project-id", default=None, help="Existing project to interpret into; defaults to auto-create named after the file")
@click.option("--project-name", default=None, help="Project name (defaults to the file's basename)")
@click.option("--language", default="zh-CN")
@click.option("--genre", default="", help="Comma-separated genre tags")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def interpret_go(
    ctx: click.Context,
    file_path: str,
    project_id: str | None,
    project_name: str | None,
    language: str,
    genre: str,
    json_output: bool,
) -> None:
    """一键解读作品：上传 → 自动建项目 → 通读 → 输出源分析画像 + 创作 Skill 卡。
    这是「一书一 Skill」的完整入口。"""
    session = _session(ctx)
    if project_id is None:
        base = Path(file_path).name
        base = __import__("re").sub(r"\.(txt|pdf|docx)$", "", base, flags=__import__("re").IGNORECASE).strip() or "源作品"
        name = project_name or base
        existing = session.request("GET", "/projects")
        project = next(
            (item for item in existing if item.get("medium") == "novel" and item.get("name") == name),
            None,
        )
        if project is None:
            project = session.request(
                "POST",
                "/projects",
                json_body={
                    "name": name,
                    "medium": "novel",
                    "source_mode": "adaptation",
                    "direction": {"language": language, "genre": genre},
                },
                write=True,
            )
        project_id = str(project["id"])
    uploaded = None
    with open(file_path, "rb") as handle:
        uploaded = session.request(
            "POST",
            f"/projects/{project_id}/files",
            files={"file": (Path(file_path).name, handle)},
            write=True,
        )
    if uploaded is None or uploaded.get("status") != "ready":
        raise click.ClickException("file was uploaded but not indexed to ready; retry from the project page")
    distillation = session.request(
        "POST",
        f"/projects/{project_id}/source-distillations",
        json_body={
            "source_file_ids": [str(uploaded["id"])],
            "idempotency_key": f"cli-onework-{__import__('time').time_ns()}",
        },
        write=True,
    )
    distillation_id = str(distillation["id"])
    body = {
        "idempotency_key": f"cli-onework-read-{__import__('time').time_ns()}",
        "external_processing_consent": True,
        "consent_version": "source-processing-v1",
    }
    if not json_output:
        click.echo(f"作品 {project_id} 正在通读素材（蒸馏 {distillation_id}，可能数分钟）…", err=True)
    session.request(
        "POST",
        f"/projects/{project_id}/source-distillations/{distillation_id}/read",
        json_body=body,
        write=True,
        timeout=900,
    )
    detail = session.request("GET", f"/projects/{project_id}/source-distillations/{distillation_id}")
    result: dict[str, Any] = {
        "project_id": project_id,
        "distillation_id": distillation_id,
        "status": detail.get("status"),
        "pass_key": detail.get("pass_key"),
        "candidate": detail.get("candidate"),
        "skill": _skill_card_for_project(session, project_id),
    }
    _emit(result, json_output)


@interpret_group.command("decide")
@click.argument("project_id")
@click.argument("profile_id")
@click.option("--approve/--reject", default=True, help="Approve the source profile into writing context (default approve)")
@click.option("--feedback", default=None)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def interpret_decide(
    ctx: click.Context,
    project_id: str,
    profile_id: str,
    approve: bool,
    feedback: str | None,
    json_output: bool,
) -> None:
    """Approve or reject a source profile (human decision)."""
    body: dict[str, Any] = {"approve": approve}
    if feedback:
        body["feedback"] = feedback
    _emit(
        _session(ctx).request(
            "POST",
            f"/projects/{project_id}/source-profiles/{profile_id}/decision",
            json_body=body,
            write=True,
        ),
        json_output,
    )


@interpret_group.command("create")
@click.argument("project_id")
@click.option("--file-id", "file_ids", multiple=True, required=True, help="Source file id(s) to interpret")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def interpret_create(ctx: click.Context, project_id: str, file_ids: tuple[str, ...], json_output: bool) -> None:
    """Create a source distillation for a project's uploaded files."""
    body = {
        "source_file_ids": list(file_ids),
        "idempotency_key": f"cli-interpret-{__import__('time').time_ns()}",
    }
    _emit(
        _session(ctx).request(
            "POST", f"/projects/{project_id}/source-distillations", json_body=body, write=True
        ),
        json_output,
    )


@interpret_group.command("read")
@click.argument("project_id")
@click.option("--distillation-id", default=None, help="Distillation id; defaults to latest")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def interpret_read(ctx: click.Context, project_id: str, distillation_id: str | None, json_output: bool) -> None:
    """Run the full read-through (blocks until done): analysis + reusable Skill."""
    session = _session(ctx)
    if distillation_id is None:
        latest = session.request("GET", f"/projects/{project_id}/source-distillations/latest")
        if not latest:
            raise click.ClickException("project has no source distillation; run 'scriptnow interpret create'")
        distillation_id = str(latest["id"])
    body = {
        "idempotency_key": f"cli-read-{__import__('time').time_ns()}",
        "external_processing_consent": True,
        "consent_version": "source-processing-v1",
    }
    _emit(
        session.request(
            "POST",
            f"/projects/{project_id}/source-distillations/{distillation_id}/read",
            json_body=body,
            write=True,
            timeout=900,
        ),
        json_output,
    )


@interpret_group.command("status")
@click.argument("project_id")
@click.option("--distillation-id", default=None)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def interpret_status(ctx: click.Context, project_id: str, distillation_id: str | None, json_output: bool) -> None:
    """Show distillation status / source profile / skill card."""
    session = _session(ctx)
    if distillation_id is None:
        latest = session.request("GET", f"/projects/{project_id}/source-distillations/latest")
        if not latest:
            raise click.ClickException("no source distillation for this project")
        distillation_id = str(latest["id"])
    detail = session.request("GET", f"/projects/{project_id}/source-distillations/{distillation_id}")
    result: dict[str, Any] = {
        "id": detail.get("id"),
        "status": detail.get("status"),
        "pass_key": detail.get("pass_key"),
        "coverage": detail.get("coverage"),
        "candidate": detail.get("candidate"),
    }
    skill_card = _skill_card_for_project(session, project_id)
    if skill_card:
        result["skill"] = skill_card
    _emit(result, json_output)


def _skill_card_for_project(session: Session, project_id: str) -> dict[str, Any] | None:
    try:
        mounts = session.request("GET", f"/projects/{project_id}/skills")
    except ScriptNowError:
        return None
    if not mounts:
        return None
    # The source-derived skill is the one whose name is not a plain manual mount;
    # prefer any read-through skill via its description/manifest marker.
    match = None
    for mount in mounts:
        if isinstance(mount, dict) and str(mount.get("name") or "").startswith(project_id[:8]):
            match = mount
            break
    if match is None and mounts:
        match = mounts[0]
    if match is None:
        return None
    try:
        detail = session.request(
            "GET", f"/skills/personal/{match['skill_id']}?include_instructions=true"
        )
    except ScriptNowError:
        return None
    return {
        "skill_id": detail.get("id"),
        "name": detail.get("name"),
        "description": detail.get("description"),
        "instructions": (detail.get("instructions") or "")[:4000],
    }


# ------------------------------------------------- one-work-one-skill: agent-side


# 平台 skill 规范（供 Agent 本地解读时遵循）。样本作品内容不需要也不应该
# 上传到平台：Agent 本地阅读作品，按此规范产出 instructions，再通过
# `interpret local --submit` 回传并挂载到项目。平台只接收最终方法论，不接触原文。
LOCAL_SKILL_SPEC = """\
# ScriptNow 可复用创作 Skill 规范（Agent 本地解读产出）

你正在把一部作品的可复用创作方法论蒸馏成一个 Skill。作品原文由你本地阅读，
不要上传平台；只把下面的方法论以 JSON 回传。

## 输出 JSON（提交给 `interpret local --submit`）

{
  "name": "kebab-case 短名（如 black-mirror-narrative）",
  "description": "一句话说明这是哪部作品的方法论",
  "domain": "novel",
  "role": "writer",
  "stage": "writing",
  "genre_tags": ["mystery", "werewolf"],
  "instructions": "Markdown 方法论正文，按本作品真正独特的创作维度组织（不是固定模板）"
}

## instructions 编写要求（按作品实际呈现，非模板）

系统性考虑并纳入本作品真正练到的维度（缺失的维度省略或合并）：
- 叙事策略：立场、结构、讲述者、时间线、隐藏与揭示
- 节奏：句/段节奏、场景节拍、加速与休止
- 对话模式：人物如何说话、潜台词、打断、沉默
- 密度：每句信息量、描写与行动之比
- 伏笔：铺垫/回收机制、埋设细节、回调
- 钩子：章/场开头与结尾、悬念手法
- 情绪：视角内在性、感受状态、共情机制
- 视角：镜头、限制、叙述者不可知之事
- 世界规则：设定规则如何引入与强制
- 爽点结构：愿望满足节拍、升级、释放

## 达标示例（达到此厚度与具体度才算健壮，能通过平台健壮性门禁）

小说（novel）示例：
本作品《血月契约》是悬疑言情，叙述笔调冷冽克制、以动作与物象代心理。
一、craft：慢热递进的张力节奏，每章结尾留钩子；视角纪律——第三人称限知只跟随女主；
    对白短促有力、避免长篇独白；以动作推进叙事而非心理旁白。
二、voice：短句冷冽、句式忌排比堆砌；用物件意象暗示情绪（灯、信、镜子）。
三、continuity：不得违反已采纳正文的伏笔；前文确立的设定不可更改；角色性格通过动作呈现。
四、evaluation：每章按张力/连贯/角色主动性三维自检，低于门槛即拒收重写。
五、examples：例如「她把信折了三折，没有抬头」；避免「她很难过」；
    反例：连续三句解释性旁白应删至一句。

剧本（script）示例：
本剧《第101天》是都市悬疑短剧，台词风格冷硬克制、画面感优先。
一、craft：镜头语言克制，每场 40 秒完成一个行动节拍；对白短促、避免台词化说明；
    转场用物件衔接；场次时长纪律——动作戏 30 秒、对白场 45 秒。
二、voice：台词信息量大、潜台词优先；情绪靠表演而非旁白。
三、continuity：跨场不丢伏笔；服装道具贯穿；角色语气一贯。
四、evaluation：逐场审读自检，按镜头信息量/对白推动力/时长利用率三维评估，不达质量门槛即拒收重写。
五、examples：例如以特写开场建立悬念；避免用旁白交代动机；
    反例：连续三句解释性对白应删至一句。

要求：你的 instructions 至少达到上述示例的厚度与具体度（craft/voice/continuity/
evaluation/examples 五个维度都有实质内容、含正反例），否则平台健壮性门禁会判
revise/block，需要继续完善后才能挂载并开始逐章创作。
- 语言习惯：句式形态、隐喻密度、重复意象
- 禁忌与边界：本作品绝不做的、语气护栏

## 证据纪律

- instructions 正文只能写有原文锚点支撑的规则，每条内联引用 1-2 个锚点示例。
- 弱观察/推断不可作为可执行规则，放在文末「待验证观察」小节。
- 整篇控制在 ~2500 词内。
- 忠实于原文：不要为了填充维度而编造手法，也不要泛化为通用写作建议。
"""


@interpret_group.command("local")
@click.argument("work_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--project-id", "project_id", default=None, help="可选：额外挂载到该项目（不传则只创建个人 Skill）")
@click.option("--submit", "submit_file", default=None, help="提交解读结果：@skill.json（Agent 按上方规范产出）")
@click.option("--spec", is_flag=True, help="仅输出平台 skill 规范（供 Agent 本地解读参考）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def interpret_local(
    ctx: click.Context,
    work_file: str,
    project_id: str | None,
    submit_file: str | None,
    spec: bool,
    json_output: bool,
) -> None:
    """一书一 Skill（Agent 本地解读版）：样本不传平台，Agent 按规范本地产出方法论后回传。

    流程：
      1. 先运行本命令（不带 --submit）输出平台 skill 规范（--spec）——Agent 读作品原文，
         按规范产出 skill JSON。
      2. Agent 完成后，运行 `interpret local <作品> --submit @skill.json`：
         校验规范 → 直接创建个人 Skill（不建项目）。
      3. 可选：需要给某项目用时，加 `--project-id <pid>` 额外挂载到该项目。

    样本内容全程在本地，平台只接收最终方法论，不接触作品原文。
    """
    import json as _json

    session = _session(ctx) if (submit_file or project_id) else None
    if spec:
        _emit({"work_file": work_file, "skill_spec": LOCAL_SKILL_SPEC}, json_output)
        return
    if not submit_file:
        _emit(
            {
                "work_file": work_file,
                "next": "先按上方规范本地解读作品并产出 skill JSON，"
                        "然后运行: scriptnow interpret local <作品> --submit @skill.json --project-id <pid>",
                "skill_spec": LOCAL_SKILL_SPEC,
            },
            json_output,
        )
        return
    # project_id 可选：默认只创建个人 Skill，不建项目、不挂载；
    # 传 --project-id 才额外挂载到该项目（用户明确指定时）。
    raw = Path(submit_file[1:] if submit_file.startswith("@") else submit_file).read_text(
        encoding="utf-8"
    )
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"skill JSON 解析失败：{error}") from error
    if not isinstance(data, dict):
        raise click.ClickException("skill JSON 必须是对象")
    name = str(data.get("name") or "").strip()
    instructions = str(data.get("instructions") or "").strip()
    description = str(data.get("description") or "").strip()
    if not name or not instructions:
        raise click.ClickException("skill JSON 需要 name 和 instructions（见 --spec 规范）")
    if not __import__("re").fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise click.ClickException("name 必须是 kebab-case（小写字母数字，连字符分隔）")
    # 预算检查：instructions 本身是文本，给一个宽松上限（100_000 是平台硬限）
    _check_budget(instructions, 100_000 if True else None, "skill 方法论", json_output)
    role = str(data.get("role") or "writer")
    stage = str(data.get("stage") or "writing")
    domain = str(data.get("domain") or "novel")
    body = {
        "name": name,
        "description": description or f"{Path(work_file).name} 的创作方法论",
        "domain": domain,
        "roles": [role],
        "stages": [stage],
        "instructions": instructions,
    }
    created = session.request("POST", "/skills/personal", json_body=body, write=True)
    skill_id = str(created.get("id") or "")
    result: dict[str, Any] = {
        "skill_id": skill_id,
        "name": created.get("name"),
        "status": created.get("status"),
    }
    # 挂载到项目（需 version_id）
    if skill_id and project_id:
        versions = session.request("GET", f"/skills/personal/{skill_id}/versions")
        if versions:
            version_id = str(versions[0]["version_id"])
            try:
                session.request(
                    "PUT",
                    f"/projects/{project_id}/skills/{skill_id}",
                    json_body={"version_id": version_id},
                    write=True,
                )
                result["mounted"] = {"project_id": project_id, "version_id": version_id}
            except ScriptNowError as error:
                result["mount_error"] = str(error)
    if not json_output:
        click.echo(ui.ok(f"专属方法论 Skill《{created.get('name')}》已创建"))
        if result.get("mounted"):
            click.echo(ui.ok("并已挂载到当前作品 —— 可以开始逐章/逐场创作了。"))
        if result.get("mount_error"):
            click.echo(ui.warn(f"挂载未完成：{result['mount_error']}"))
        return
    _emit(result, json_output)


# ----------------------------------------------------------------------- chapters


@main.group("chapter")
@click.pass_context
def chapter_group(ctx: click.Context) -> None:
    """小说章节：列表 / 阅读 / 生成 / 质量 / 采纳。"""


@chapter_group.command("outline")
@click.argument("project_id")
@click.argument("chapter_id")
@click.argument("file_path", type=str)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_outline(
    ctx: click.Context, project_id: str, chapter_id: str, file_path: str, json_output: bool
) -> None:
    """回填单章 outline（旧项目补纲入口；保存为 StoryMap 结构候选）。

    FILE_PATH is a JSON object containing ``outline`` or the outline fields
    directly. The candidate must still be reviewed and adopted through the
    normal StoryMap decision path.
    """
    import json as _json

    path = file_path[1:] if file_path.startswith("@") else file_path
    try:
        raw = _json.loads(Path(path).read_text(encoding="utf-8"))
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"章纲 JSON 解析失败：{error}") from error
    if not isinstance(raw, dict):
        raise click.ClickException("章纲 JSON 根必须是对象")
    outline = dict(raw.get("outline")) if isinstance(raw.get("outline"), dict) else dict(raw)
    outline.pop("expected_version", None)
    outline.pop("idempotency_key", None)
    outline.pop("outline", None)
    result = _session(ctx).request(
        "POST",
        f"/novel/projects/{project_id}/chapters/{chapter_id}/outline/propose",
        json_body={"outline": outline, "idempotency_key": f"cli-chapter-outline-{__import__('time').time_ns()}"},
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"第 {chapter_id} 章章纲已形成结构候选（{result.get('id')}）"))
        click.echo(ui.dim("请回读 StoryMap、运行 planning-quality，并在用户明确决定后采纳。"), err=True)
        return
    _emit(result, json_output)


@chapter_group.command("outline-batch")
@click.argument("project_id")
@click.argument("file_path", type=str)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_outline_batch(
    ctx: click.Context, project_id: str, file_path: str, json_output: bool
) -> None:
    """批量回填多章 outline（已成型作品后补章纲入口）。

    正常流程是「先出章纲，再细化逐章写作」；对已经成型但缺章纲的作品，
    用本命令批量补纲。每章 outline 走标准 StoryMap 候选流程（逐章提交、
    累积进同一结构候选），仍需 planning-quality 与采纳。

    FILE_PATH is JSON in either shape:
      {"outlines": {"chapter-3-1": {outline...}, "chapter-3-2": {...}}}
      {"chapters": [{"chapter_id": "...", "outline": {...}}, ...]}
    """
    import json as _json

    path = file_path[1:] if file_path.startswith("@") else file_path
    try:
        raw = _json.loads(Path(path).read_text(encoding="utf-8"))
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"章纲 JSON 解析失败：{error}") from error
    if not isinstance(raw, dict):
        raise click.ClickException("章纲 JSON 根必须是对象")
    outlines = raw.get("outlines") or {}
    if isinstance(outlines, list):  # [{"chapter_id": ..., "outline": ...}, ...]
        outlines = {
            str(item["chapter_id"]): item.get("outline")
            for item in outlines
            if isinstance(item, dict) and item.get("chapter_id")
        }
    if not isinstance(outlines, dict) or not outlines:
        raise click.ClickException("章纲 JSON 需包含 outlines（chapter_id → outline 对象）")
    session = _session(ctx)
    # 读取已采纳 StoryMap，把全部章纲一次性应用并合成单个结构候选，
    # 避免逐章提案生成互不累积的多个候选。
    state = _novel_state(session, project_id)
    volumes = [dict(volume) for volume in (state.get("story_map") or {}).get("volumes") or []]
    if not volumes:
        raise click.ClickException("当前项目没有已采纳的 StoryMap 卷章结构，无法补纲")
    applied: list[str] = []
    not_found: list[str] = []
    for volume in volumes:
        chapters = [dict(chapter) for chapter in volume.get("chapters") or []]
        for chapter in chapters:
            outline = outlines.get(str(chapter.get("id")))
            if outline is None:
                continue
            if not isinstance(outline, dict):
                raise click.ClickException(f"章节 {chapter.get('id')} 的 outline 必须是对象")
            payload = dict(outline)
            for key in ("expected_version", "idempotency_key", "outline"):
                payload.pop(key, None)
            chapter["outline"] = payload
            applied.append(str(chapter.get("id")))
        volume["chapters"] = chapters
    for chapter_id in outlines:
        if chapter_id not in applied:
            not_found.append(str(chapter_id))
    if not applied:
        raise click.ClickException("outlines 中的章节 ID 都不存在于已采纳 StoryMap 中")
    version = int((state.get("story_map") or {}).get("version") or 1)
    result = session.request(
        "POST",
        f"/novel/projects/{project_id}/story-map/propose",
        json_body={
            "volumes": volumes,
            "expected_version": version,
            "idempotency_key": f"cli-ch-outline-batch-{__import__('time').time_ns()}",
        },
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"已合成单候选并提交 {len(applied)} 章章纲（候选 {result.get('id')}）"))
        for chapter_id in applied:
            click.echo(ui.dim(f"  · {chapter_id}"))
        if not_found:
            click.echo(ui.warn(f"以下章节不在已采纳 StoryMap 中，已忽略：{'、'.join(not_found)}"), err=True)
        click.echo(ui.dim("请运行 planning-quality，并在用户明确决定后采纳 StoryMap。"), err=True)
        return
    _emit({"candidate_id": result.get("id"), "applied": applied, "ignored_not_found": not_found}, json_output)


@chapter_group.command("list")
@click.argument("project_id")
@click.option("--status", default=None, help="Filter by document status: candidate|adopted|active")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_list(ctx: click.Context, project_id: str, status: str | None, json_output: bool) -> None:
    """List chapters from the adopted StoryMap with their document state
    (adopted revision, candidate revisions, version counts)."""
    state = _novel_state(_session(ctx), project_id)
    volumes = state.get("story_map", {}).get("volumes", [])
    documents = state.get("documents", [])
    rows = []
    for volume in volumes:
        for chapter in volume.get("chapters", []):
            chapter_id = str(chapter["id"])
            docs = [doc for doc in documents if doc.get("chapter_id") == chapter_id]
            adopted_human = next((doc for doc in docs if doc.get("status") == "adopted_human"), None)
            adopted = adopted_human or next((doc for doc in docs if doc.get("status") == "adopted"), None)
            candidates = [doc for doc in docs if doc.get("status") in ("candidate", "active")]
            candidates.sort(key=lambda doc: doc.get("revision_number", 0), reverse=True)
            row = {
                "chapter_id": chapter_id,
                "title": chapter.get("title"),
                "target_words": chapter.get("target_words"),
                "adopted_revision": adopted.get("revision_number") if adopted else None,
                "adopted_human": adopted_human is not None,
                "candidate_revisions": [doc.get("revision_number") for doc in candidates],
                "latest_candidate_id": candidates[0].get("id") if candidates else None,
            }
            if status is None or (status in ("adopted", "adopted_human") and adopted) or (status in ("candidate", "active") and candidates):
                rows.append(row)
    _emit(rows, json_output)


@chapter_group.command("show")
@click.argument("project_id")
@click.argument("chapter_id")
@click.option("--revision", default=None, help="Revision id or number to show; defaults to the adopted revision, else latest candidate")
@click.option("--plain", is_flag=True, help="Emit only the manuscript text, no JSON wrapper (for direct reading)")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_show(
    ctx: click.Context, project_id: str, chapter_id: str, revision: str | None, plain: bool, json_output: bool
) -> None:
    """Show a chapter's manuscript text and metadata for review.
    This is the review primitive: an agent reads the FULL text here and forms its
    own judgment — as a demanding audience member and a working screenwriter,
    never skimming and never self-congratulating. Quote evidence for every
    verdict; fix weak lines via `chapter generate --feedback` before adopting.
    """
    # 按章分批读取正文（每章一个小响应），不走整份 /state —— 受限网络下
    # /state 大响应会被中间层截断，按章读取保持稳定。
    documents = _session(ctx).request(
        "GET",
        f"/novel/projects/{project_id}/chapters/{chapter_id}/documents",
    )
    docs = [doc for doc in documents if doc.get("chapter_id") == chapter_id]
    if not docs:
        raise click.ClickException(f"no documents for chapter {chapter_id}")
    chosen = None
    if revision:
        chosen = next(
            (doc for doc in docs if doc.get("id") == revision or str(doc.get("revision_number")) == revision),
            None,
        )
        if chosen is None:
            raise click.ClickException(f"revision {revision} not found for chapter {chapter_id}")
    else:
        adopted = next((doc for doc in docs if doc.get("status") == "adopted"), None)
        if adopted:
            chosen = adopted
        else:
            candidates = sorted(
                [doc for doc in docs if doc.get("status") in ("candidate", "active")],
                key=lambda doc: doc.get("revision_number", 0),
                reverse=True,
            )
            chosen = candidates[0] if candidates else docs[0]
    blocks = chosen.get("blocks") or []
    text = "\n\n".join(
        (block.get("text") or "") for block in blocks if block.get("type") != "heading" and (block.get("text") or "").strip()
    )
    heading = next((block.get("text") for block in blocks if block.get("type") == "heading"), "")
    if plain:
        click.echo((f"{heading}\n\n" if heading else "") + text)
        return
    revision_summary = [
        {
            "revision_id": doc.get("id"),
            "revision_number": doc.get("revision_number"),
            "status": doc.get("status"),
            "source": doc.get("source"),
        }
        for doc in sorted(docs, key=lambda item: item.get("revision_number", 0))
    ]
    if not json_output:
        source_label = "平台生成" if chosen.get("source") == "platform" else "共创回填"
        status_label = _status_word(chosen.get("status"), medium="novel")
        click.echo(ui.section(f"=== 第 {chosen.get('revision_number', 1)} 版 · {source_label} · {status_label} ==="), err=True)
        click.echo((f"{heading}\n\n" if heading else "") + text, err=True)
        click.echo("", err=True)
        click.echo(ui.dim(_next_step_after_generate("novel")), err=True)
        return
    _emit(
        {
            "chapter_id": chapter_id,
            "revision_id": chosen.get("id"),
            "revision_number": chosen.get("revision_number"),
            "source": chosen.get("source"),
            "status": chosen.get("status"),
            "title": heading,
            "text": text,
            "block_count": len(blocks),
            "revisions": revision_summary,
            "candidate_revisions": [
                item for item in revision_summary if item["status"] in ("candidate", "active")
            ],
            "adopted_revision": next(
                (item for item in revision_summary if item["status"] == "adopted"), None
            ),
        },
        json_output,
    )


@chapter_group.command("generate")
@click.argument("project_id")
@click.argument("chapter_id")
@click.option("--feedback", default=None)
@click.option("--model", "model_id", default=None, help="指定本项目中该章节写作使用的模型 id（仅项目写作，禁止用于非项目文本生成）")
@click.option("--wait", is_flag=True, help="Poll until the background run finishes")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_generate(
    ctx: click.Context,
    project_id: str,
    chapter_id: str,
    feedback: str | None,
    model_id: str | None,
    wait: bool,
    json_output: bool,
) -> None:
    """Generate a chapter candidate (background by default)."""
    session = _session(ctx)
    body: dict[str, Any] = {"idempotency_key": f"cli-chapter-{__import__('time').time_ns()}", "feedback": feedback}
    if model_id:
        body["model_id"] = model_id
    try:
        result = session.request(
            "POST",
            f"/novel/projects/{project_id}/chapters/{chapter_id}/generate?background=true",
            json_body=body,
            write=True,
        )
    except ScriptNowError as error:
        if "concurrent" in str(error) or "already active" in str(error):
            raise click.ClickException(
                "并发逐章创作被拒绝：同一项目已有正文生成在运行。\n"
                "正确方式：逐章严格串行——用 scriptnow run status <run_id> 等当前生成完成后，再生成下一章。\n"
                "不要并发启动多个 chapter generate（设定会漂移、伏笔会失联）。"
            ) from error
        raise
    if wait and result.get("run_id"):
        _wait_for_run(session, project_id, str(result["run_id"]), json_output)
        return
    _emit(result, json_output)


@chapter_group.command("adopt")
@click.argument("project_id")
@click.argument("chapter_id")
@click.argument("revision_id")
@click.option(
    "--human",
    "human_decision",
    is_flag=True,
    help="人工决定已明确：用户本人执行，或已在与 Agent 的对话中明确表示定稿/采用这版",
)
@click.option(
    "--token",
    "decision_token",
    default=None,
    help="可选增强审计令牌；用户在对话中明确采用时，Agent 直接使用 --human 即可",
)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_adopt(ctx: click.Context, project_id: str, chapter_id: str, revision_id: str, human_decision: bool, decision_token: str | None, json_output: bool) -> None:
    """Adopt a chapter revision as the working text.

    定稿必须来自人的明确决定。用户本人运行，或在与 Agent 的对话中明确表示
    「定稿 / 采用这版 / 可以继续」后，均可带 --human；无需重复终端确认。
    """
    # --human 既可表示用户本人执行，也可表示 Agent 已收到用户在对话中的明确决定。
    # --token 仅为需要更强审计时的可选通道。
    if not decision_token and not human_decision:
        if not json_output:
            if not click.confirm(
                "你明确决定采用这份候选稿并将其定稿吗？",
                default=False,
            ):
                click.echo(ui.warn("已取消定稿——你可以继续讨论或修改；明确采用时再运行 chapter adopt --human。"), err=True)
                return
            human_decision = True
        else:
            raise click.ClickException(
                "尚未收到人工决定。请先向用户呈现内容；用户在对话中明确表示定稿/采用后，"
                "Agent 可直接用 chapter adopt --human。--token 仅为可选增强审计方式。"
            )
    # 前置检查：revision 定位 + 已定稿拦截（避免重复采纳撞 409）。
    # revision_id 支持 uuid 或版本号（rev1/1）——版本号自动从 state 解析为 uuid，
    # 避免 agent 误用版本号导致 409「候选不可用」。
    resolved_revision_id = revision_id
    try:
        state = _novel_state(_session(ctx), project_id)
        docs = [d for d in state.get("documents", []) if d.get("chapter_id") == chapter_id]
        target = next(
            (d for d in docs
             if d.get("id") == revision_id
             or str(d.get("revision_number")) == str(revision_id)
             or str(revision_id).lower().removeprefix("rev") == str(d.get("revision_number"))),
            None,
        )
        if target:
            resolved_revision_id = str(target.get("id"))
            if target.get("status") in ("adopted", "adopted_human"):
                msg = f"该版本（rev{target.get('revision_number')}）已是定稿（{_status_word(target.get('status'), medium='novel')}），无需重复采纳。"
                if not json_output:
                    click.echo(ui.ok(msg), err=True)
                    return
                _emit({"ok": True, "already_adopted": True, "revision_id": target.get("id")}, json_output)
                return
            if target.get("status") == "superseded":
                click.echo(ui.warn("该版本已过期（superseded）——请用 chapter list 查看最新候选，采纳最新版本。"), err=True) if not json_output else _emit({"ok": False, "superseded": True}, json_output)
                return
    except ScriptNowError:
        pass  # 前置检查失败不阻塞，交给平台权威校验
    extra_headers = {}
    if decision_token:
        extra_headers["X-Decision-Token"] = decision_token
    result = _session(ctx).request(
        "POST",
        f"/novel/projects/{project_id}/chapters/{chapter_id}/revisions/{resolved_revision_id}/adopt?human_decision={str(human_decision).lower()}",
        write=True,
        headers=extra_headers,
    )
    if not json_output:
        click.echo(ui.ok(_confirm_line("novel", adopted=True)))
        return
    _emit(result, json_output)


_CHAPTER_BLOCKS_FORMAT = """小说章节 blocks JSON 格式（chapter propose --file 要求）：
{
  "blocks": [
    {"block_id": "h1", "type": "heading",  "text": "第一章 复职日"},
    {"block_id": "p1", "type": "prose",    "text": "宋晚踏进辰川投资大楼。"},
    {"block_id": "d1", "type": "dialogue", "text": "\"赵总把尽调包甩到你桌上。\""},
    {"block_id": "q1", "type": "quote",    "text": "账本最后一页，页码跳了一格。"}
  ]
}
type 仅限：heading | prose | dialogue | quote | divider。block_id 唯一即可。
（这是格式规格示例，不代表质量水准——质量由 Agent 按内容质量维度评估。）"""

_CHAPTER_EXAMPLE = """第一章 复职日

宋晚踏进辰川投资大楼，前台的眼神在她工牌上多停了一秒。
（规格示例：演示 heading/prose 结构，非质量典范）"""


@chapter_group.command("propose")
@click.argument("project_id", required=False)
@click.argument("chapter_id", required=False)
@click.option("--file", "blocks_file", default=None, help="章节正文 JSON：{\"blocks\":[{\"block_id\":\"h1\",\"type\":\"heading|prose|dialogue|quote|divider\",\"text\":\"...\"}]}")
@click.option("--text", default=None, help="纯文本正文（自动分段为 prose blocks，首段为标题）")
@click.option("--budget", type=int, default=None, help="正文 token 预算上限（中文≈1 token/字，英文≈1 token/4 字符）")
@click.option("--help-format", is_flag=True, help="显示 blocks JSON 格式说明")
@click.option("--example", is_flag=True, help="显示规格示例文本")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_propose(
    ctx: click.Context,
    project_id: str,
    chapter_id: str,
    blocks_file: str | None,
    text: str | None,
    budget: int | None,
    help_format: bool,
    example: bool,
    json_output: bool,
) -> None:
    if help_format:
        click.echo(_CHAPTER_BLOCKS_FORMAT)
        return
    if example:
        click.echo(_CHAPTER_EXAMPLE)
        return
    """Agent 本地创作章节 → 回传为候选（改编创作不经过平台文本生成）。

    适用于改编场景：Agent 已用解读出的 skill 方法论（interpret local 产出）在本地
    写好了章节正文，这里只负责把成品按标准格式回传为候选，平台不参与文本生成。
    """
    import json as _json

    if not blocks_file and not text:
        raise click.ClickException("需要 --file（blocks JSON）或 --text（纯文本）")
    if blocks_file:
        raw = Path(blocks_file[1:] if blocks_file.startswith("@") else blocks_file).read_text(
            encoding="utf-8"
        )
        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError as error:
            raise click.ClickException(f"blocks JSON 解析失败：{error}") from error
        blocks = data.get("blocks") if isinstance(data, dict) else data
        if not isinstance(blocks, list) or not blocks:
            raise click.ClickException("blocks 需要是至少 1 个 block 的数组")
        for block in blocks:
            if block.get("type") not in ("heading", "prose", "dialogue", "quote", "divider"):
                raise click.ClickException(
                    f"block type 必须是 heading|prose|dialogue|quote|divider，收到：{block.get('type')}"
                )
            if "block_id" not in block or "text" not in block:
                raise click.ClickException("每个 block 需要 block_id 和 text")
    else:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            raise click.ClickException("正文为空")
        blocks = []
        if paragraphs:
            blocks.append({"block_id": "h1", "type": "heading", "text": paragraphs[0]})
        for idx, para in enumerate(paragraphs[1:], 2):
            blocks.append({"block_id": f"p{idx}", "type": "prose", "text": para})
    _check_budget(blocks, budget, "章节正文", json_output)
    session = _session(ctx)
    body = {
        "idempotency_key": f"cli-chapter-propose-{__import__('time').time_ns()}",
        "blocks": blocks,
        "source": "cli",
    }
    result = session.request(
        "POST",
        f"/novel/projects/{project_id}/chapters/{chapter_id}/propose",
        json_body=body,
        write=True,
    )
    if not json_output:
        adopted = result.get("status") in ("adopted", "adopted_human")
        click.echo(ui.ok(_confirm_line("novel", adopted=adopted)))
        return
    _emit(result, json_output)


@chapter_group.command("quality")
@click.argument("project_id")
@click.argument("chapter_id")
@click.argument("revision_id")
@click.option(
    "--standard",
    type=click.Choice(["content", "drama-filing", "thousand-plan"]),
    default="content",
    help="评估标准：content=内容质量偏好（默认）；drama-filing=真人剧备案口径；thousand-plan=千部计划/批量网文标准",
)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_quality(
    ctx: click.Context,
    project_id: str,
    chapter_id: str,
    revision_id: str,
    standard: str,
    json_output: bool,
) -> None:
    """Run the serial-quality evaluation for a chapter revision (blocks).

    评估默认使用内容质量偏好；用户明确提出真人剧备案或千部计划标准时指定 --standard。
    """
    body = {
        "revision_id": revision_id,
        "idempotency_key": f"cli-quality-{__import__('time').time_ns()}",
        "standard": standard.replace("-", "_"),
    }
    result = _session(ctx).request(
        "POST",
        f"/novel/projects/{project_id}/chapters/{chapter_id}/quality-reports/generate",
        json_body=body,
        write=True,
        timeout=600,
    )
    if not json_output:
        click.echo(ui.ok("本章质量审读已生成——请通读审读报告，低于标准就用 chapter generate --feedback 迭代。"))
        return
    _emit(result, json_output)


@main.command("book")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def book_plan(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """查看全书托管创作规划（Agent 编排原语）：各章已采纳 / 待生成 / 候选待审状态，
    供 Agent 决定逐章创作顺序与审读反馈。非 --json 模式同时侦测项目的 Skill 支撑：
    缺方法论 Skill 时提示先创建（interpret local 一书一 Skill 或 skill create）再创作。

    The agent (you, or another CLI-equipped agent) drives the hosted loop:
    read this plan, then for each chapter use `chapter show` to read the text,
    form your own judgment, drive fixes with `chapter generate --feedback`,
    and adopt with `chapter adopt`. Platform quality scoring is optional; the
    review judgment belongs to the agent, not to a fixed rubric.
    """
    state = _novel_state(_session(ctx), project_id)
    volumes = state.get("story_map", {}).get("volumes", [])
    chapters = [
        chapter
        for volume in volumes
        for chapter in volume.get("chapters", [])
    ]
    if not chapters:
        raise click.ClickException("project has no adopted StoryMap; generate and adopt one first")
    documents = state.get("documents", [])
    plan = []
    for chapter in chapters:
        chapter_id = str(chapter["id"])
        docs = [doc for doc in documents if doc.get("chapter_id") == chapter_id]
        # 优先取人工核验定稿（adopted_human），否则 agent 采纳（adopted）
        adopted_human = next((doc for doc in docs if doc.get("status") == "adopted_human"), None)
        adopted = adopted_human or next((doc for doc in docs if doc.get("status") == "adopted"), None)
        candidates = [doc for doc in docs if doc.get("status") in ("candidate", "active")]
        candidates.sort(key=lambda doc: doc.get("revision_number", 0), reverse=True)
        plan.append({
            "chapter_id": chapter_id,
            "title": chapter.get("title"),
            "ordinal": chapter.get("ordinal"),
            "target_words": chapter.get("target_words"),
            "point_of_view": chapter.get("point_of_view"),
            "beats": [beat.get("objective") for beat in chapter.get("beats") or []],
            "state": {
                "adopted_revision": adopted.get("revision_number") if adopted else None,
                "adopted_human": adopted_human is not None,
                "candidate_revisions": [doc.get("revision_number") for doc in candidates],
                "latest_candidate_id": candidates[0].get("id") if candidates else None,
                "needs_generation": adopted is None and not candidates,
                "has_candidate_pending_review": bool(candidates),
            },
        })
    summary = {
        "project_id": project_id,
        "total_chapters": len(plan),
        "adopted": sum(1 for item in plan if item["state"]["adopted_revision"] is not None),
        "needs_generation": [item["chapter_id"] for item in plan if item["state"]["needs_generation"]],
        "candidates_pending_review": [
            item["chapter_id"] for item in plan if item["state"]["has_candidate_pending_review"]
        ],
        "plan": plan,
    }
    if json_output:
        _emit(summary, json_output)
        return
    # 人读模式：只渲染友好创作计划，不打印技术字段
    mounted = _session(ctx).request("GET", f"/projects/{project_id}/skills")
    names = [str(item.get("name") or "") for item in mounted] if isinstance(mounted, list) else []
    click.echo(ui.section(f"=== 全书创作计划（{len(plan)} 章）==="), err=True)
    for item in plan:
        st = item["state"]
        if st["adopted_revision"] is not None:
            mark = "已定稿"
            icon = ui.ok("✓")
        elif st["has_candidate_pending_review"]:
            mark = "候选待审"
            icon = ui.warn("…")
        else:
            mark = "待创作"
            icon = "·"
        click.echo(f"  {icon} 第{item.get('ordinal') or '?'}章 · {item.get('title') or '未命名'}（{mark}）", err=True)
    click.echo(ui.dim(f"已定稿 {summary['adopted']}/{len(plan)} 章；待创作 {len(summary['needs_generation'])} 章；候选待审 {len(summary['candidates_pending_review'])} 章"), err=True)
    if names:
        click.echo(ui.dim(f"方法论 Skill：{', '.join(names)}"), err=True)
    else:
        click.echo(
            ui.warn(
                "项目暂无方法论 Skill —— 建议先创建再创作："
                "interpret local 一书一 Skill（样本不传平台，Agent 本地蒸馏）"
                "或 skill create --domain novel；完成后 skill mount 到本项目。"
            ),
            err=True,
        )


# ----------------------------------------------------------------------- storymap


@main.group("storymap")
@click.pass_context
def storymap_group(ctx: click.Context) -> None:
    """小说卷章结构：查看状态 / 生成候选 / 采纳（全书规划）。"""


@storymap_group.command("state")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storymap_state(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """Show the project's novel state (storymap, blueprint, documents)."""
    _emit(_novel_state(_session(ctx), project_id), json_output)


@storymap_group.command("generate")
@click.argument("project_id")
@click.option("--feedback", default=None)
@click.option("--wait", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storymap_generate(
    ctx: click.Context, project_id: str, feedback: str | None, wait: bool, json_output: bool
) -> None:
    """Generate a StoryMap structure candidate."""
    session = _session(ctx)
    body = {"idempotency_key": f"cli-storymap-{__import__('time').time_ns()}", "feedback": feedback}
    result = session.request(
        "POST",
        f"/novel/projects/{project_id}/story-map/generate?background=true",
        json_body=body,
        write=True,
    )
    if wait and result.get("run_id"):
        _wait_for_run(session, project_id, str(result["run_id"]), json_output)
        return
    _emit(result, json_output)


@storymap_group.command("adopt")
@click.argument("project_id")
@click.argument("candidate_id")
@click.option("--confirm", is_flag=True, help="高危操作：明确授权采纳此结构修订（覆盖当前 StoryMap 并影响已采纳正文；旧结构将自动归档）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storymap_adopt(ctx: click.Context, project_id: str, candidate_id: str, confirm: bool, json_output: bool) -> None:
    """Adopt a StoryMap structure candidate (HIGH-RISK, requires --confirm).

    StoryMap 修订是高危操作：采纳会覆盖当前结构、改变保留章节的标题/字数，
    并影响已采纳正文的匹配关系。必须由主编/作者明确授权（--confirm）后才会执行；
    被替换的旧结构与各章正文快照会自动归档，可在平台「结构历史」中查看与导出。
    """
    if not confirm:
        raise click.ClickException(
            "StoryMap 修订是高危操作：需要 --confirm 明确授权。"
            "请先核对影响（新增/移除/保留章节、已采纳正文），确认由主编/作者本人授权后再执行。"
        )
    _emit(
        _session(ctx).request(
            "POST",
            f"/novel/projects/{project_id}/story-map/{candidate_id}/adopt?confirm=true",
            write=True,
        ),
        json_output,
    )


def _read_append_json(file_path: str, key: str) -> list[dict[str, object]]:
    """读取追加 JSON（volumes 数组或 chapters 数组），并给出格式提示。"""
    import json as _json

    resolved = Path(file_path[1:] if file_path.startswith("@") else file_path)
    if not resolved.exists():
        raise click.ClickException(f"文件不存在：{resolved}")
    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as error:
        raise click.ClickException(f"无法读取文件：{error}") from error
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"JSON 解析失败：{error}") from error
    items = data.get(key) if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise click.ClickException(
            f"需要至少 1 个条目的 {key} 数组。"
            f"{key} == 'volumes' 时格式：[{{\"id\":\"volume-2\",\"ordinal\":1,\"title\":\"第二卷\",\"chapters\":[{{\"id\":\"chapter-2-1\",\"ordinal\":1,\"title\":\"新章\",\"target_words\":3000,\"beats\":[]}}]}}]；"
            f"{key} == 'chapters' 时格式：[{{\"id\":\"chapter-2-1\",\"ordinal\":1,\"title\":\"新章\",\"target_words\":3000,\"beats\":[]}}]"
        )
    return items


@storymap_group.command("append-volume")
@click.argument("project_id")
@click.argument("file_path")
@click.option("--adopt", is_flag=True, help="追加形成候选后直接采纳（追加不动已有章节，风险低；仍是结构变更，平台会记录）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storymap_append_volume(
    ctx: click.Context, project_id: str, file_path: str, adopt: bool, json_output: bool
) -> None:
    """新增卷章（追加模式）：在现有 StoryMap 尾部新增卷，已有卷章完全不动。

    这是「新增」而非「修订」：保留章节的 id/序号/标题/字数都不变，只追加新卷
    （新卷内的章节序号自动从 1 编排）。生成的候选仍走采纳（append 不影响已采纳正文）。

    联动提示：新卷/新章的 beats 若引用蓝图锚点，锚点必须已存在于已采纳蓝图；
    如需新角色/新主题锚点，先更新蓝图（蓝图更新会校验不破坏已采纳结构的引用）。
    故事图谱与人物圣经随章节采纳自动跟进，无需手动更新。
    """
    volumes = _read_append_json(file_path, "volumes")
    session = _session(ctx)
    body = {
        "idempotency_key": f"cli-append-vol-{__import__('time').time_ns()}",
        "volumes": volumes,
    }
    result = session.request(
        "POST",
        f"/novel/projects/{project_id}/story-map/append-propose",
        json_body=body,
        write=True,
    )
    if adopt and result.get("id"):
        adopted = session.request(
            "POST",
            f"/novel/projects/{project_id}/story-map/{result['id']}/adopt?confirm=true",
            write=True,
        )
        _emit({"candidate_id": result["id"], "adopted": adopted.get("status")}, json_output)
        return
    _emit(result, json_output)


@storymap_group.command("append-chapters")
@click.argument("project_id")
@click.argument("volume_id")
@click.argument("file_path")
@click.option("--adopt", is_flag=True, help="追加形成候选后直接采纳（追加不动已有章节，风险低）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storymap_append_chapters(
    ctx: click.Context,
    project_id: str,
    volume_id: str,
    file_path: str,
    adopt: bool,
    json_output: bool,
) -> None:
    """新增章节（追加模式）：向指定卷尾部新增章节，已有卷章完全不动。

    新章序号自动接续到该卷现有章节之后；保留章节的 id/序号/标题/字数都不变。

    联动提示：新章 beats 若引用蓝图锚点，锚点必须已存在（新锚点需先更新蓝图）；
    蓝图更新会校验不破坏已采纳结构引用；故事图谱/人物圣经随采纳自动跟进。
    """
    chapters = _read_append_json(file_path, "chapters")
    session = _session(ctx)
    body = {
        "idempotency_key": f"cli-append-ch-{__import__('time').time_ns()}",
        "chapters": chapters,
        "volume_id": volume_id,
    }
    result = session.request(
        "POST",
        f"/novel/projects/{project_id}/story-map/append-propose",
        json_body=body,
        write=True,
    )
    if adopt and result.get("id"):
        adopted = session.request(
            "POST",
            f"/novel/projects/{project_id}/story-map/{result['id']}/adopt?confirm=true",
            write=True,
        )
        _emit({"candidate_id": result["id"], "adopted": adopted.get("status")}, json_output)
        return
    _emit(result, json_output)


# ------------------------------------------------------------------ novel core chain


@main.group("novel")
@click.pass_context
def novel_group(ctx: click.Context) -> None:
    """小说创作链：故事核心与蓝图（规划阶段）。"""


@novel_group.command("outline")
@click.argument("project_id", required=False)
@click.option("--text", default=None, help="梗概大纲正文（≤500 字）")
@click.option("--file", default=None, help="@outline.txt（≤500 字）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_outline(
    ctx: click.Context, project_id: str | None, text: str | None, file: str | None, json_output: bool
) -> None:
    """回填梗概大纲（≤500 字，早于 StoryMap 的渐进披露节点）→ 用户审阅 → outline 采纳后 storymap 才可规划。"""
    pid = _resolve_project_id(ctx, project_id)
    if not text and not file:
        raise click.ClickException("需要 --text 或 --file（梗概 ≤500 字）")
    if file:
        raw = Path(file[1:] if file.startswith("@") else file).read_text(encoding="utf-8").strip()
        text = raw
    if len((text or "").strip()) > 500:
        raise click.ClickException("梗概大纲需在 500 字以内")
    result = _api_request(
        ctx,
        "POST",
        f"/novel/projects/{pid}/synopsis-outline/propose",
        json_body={"content": (text or "").strip(), "idempotency_key": f"cli-outline-{__import__('time').time_ns()}"},
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"梗概大纲已回填（v{result.get('version')}，{_status_word(result.get('status'), medium='novel')}）——请先通读审阅："))
        click.echo(ui.dim("  满意就采纳：scriptnow novel outline-adopt <作品号>；采纳后即可规划全书结构。"), err=True)
    _emit(result, json_output)


@novel_group.command("outline-status")
@click.argument("project_id", required=False)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_outline_status(ctx: click.Context, project_id: str | None, json_output: bool) -> None:
    """查看梗概大纲状态与内容。"""
    pid = _resolve_project_id(ctx, project_id)
    result = _api_request(ctx, "GET", f"/novel/projects/{pid}/synopsis-outline")
    if result is None:
        click.echo(ui.warn('尚无梗概大纲——先写一句 ≤500 字的梗概：novel outline <作品号> --text "……"'), err=True)
        return
    if not json_output:
        mark = ui.ok("已采纳") if result.get("status") == "adopted" else ui.warn("候选待审")
        click.echo(f"{ui.kv('状态', mark)}（v{result.get('version')}）", err=True)
        click.echo(result.get("content"), err=True)
        return
    _emit(result, json_output)


@novel_group.command("outline-adopt")
@click.argument("project_id", required=False)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_outline_adopt(ctx: click.Context, project_id: str | None, json_output: bool) -> None:
    """采纳梗概大纲（StoryMap 规划的前置条件）。"""
    pid = _resolve_project_id(ctx, project_id)
    result = _api_request(ctx, "POST", f"/novel/projects/{pid}/synopsis-outline/adopt", write=True)
    if not json_output:
        click.echo(ui.ok(f"梗概大纲已定稿（v{result.get('version')}）——接下来规划全书结构（storymap）。"))
        return
    _emit(result, json_output)


@novel_group.command("ready-check")
@click.argument("project_id", required=False)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_ready_check(ctx: click.Context, project_id: str | None, json_output: bool) -> None:
    """逐章写作前置完整性检查（强制 gate）：direction / cores / blueprint / 梗概大纲 / storymap / skill。"""
    pid = _resolve_project_id(ctx, project_id)
    session = _session(ctx)
    state = _novel_state(session, pid)
    checks = []
    direction_ok = bool((state.get("creation_settings") or {}).get("chapter_target_words"))
    checks.append(("创作方向（direction）", direction_ok, "project direction --apply @direction.json"))
    cores = [c for c in (state.get("story_cores") or []) if c.get("status") in ("adopted", "active")]
    checks.append(("故事核心（已定稿）", bool(cores), "novel propose cores @file --adopt"))
    checks.append(("蓝图", state.get("blueprint") is not None, "novel propose blueprint @file --adopt"))
    outline = _api_request(ctx, "GET", f"/novel/projects/{pid}/synopsis-outline")
    checks.append(("梗概大纲（已定稿）", bool(outline and outline.get("status") == "adopted"), 'novel outline <作品号> --text "…" → outline-adopt'))
    sm = state.get("story_map") or {}
    checks.append(("StoryMap（全书结构）", bool(sm.get("volumes")), "novel propose storymap @file 或 storymap generate --wait"))
    chapters = [
        chapter
        for volume in (sm.get("volumes") or [])
        if isinstance(volume, dict)
        for chapter in (volume.get("chapters") or [])
    ]
    checks.append(("章纲（全书 chapter.outline）", _all_planning_contracts(chapters, "chapter_contract"), "在每个 chapter 的 outline 填写章纲 → chapter outline <pid> <chapter_id> @outline.json（单章补纲）→ planning-quality → propose"))
    try:
        mounted = session.request("GET", f"/projects/{pid}/skills")
        skills = [str(i.get("name") or "") for i in mounted] if isinstance(mounted, list) else []
    except Exception:
        skills = []
    checks.append(("方法论 Skill", bool(skills), "interpret local 一书一 Skill 或 skill create → skill mount"))
    if json_output:
        _emit({"project_id": pid, "ready": all(c[1] for c in checks), "checks": [
            {"item": c[0], "ok": c[1], "fix": c[2]} for c in checks
        ], "skills": skills}, json_output)
        return
    all_ok = True
    for name, ok, fix in checks:
        mark = ui.ok("✓") if ok else ui.error("✗")
        if not ok:
            all_ok = False
        click.echo(f"  {mark} {name}" + ("" if ok else f"  → {fix}"), err=True)
    if skills:
        click.echo(ui.dim(f"  Skill：{', '.join(skills)}"), err=True)
    click.echo(ui.ok(f"创作前检查通过：{sum(1 for c in checks if c[1])}/{len(checks)} 项就绪" if all_ok else ui.error(f"还差 {sum(1 for c in checks if not c[1])} 项未就绪——按上面提示补齐后再开始逐章创作")), err=True)



@novel_group.command("story-cores")
@click.argument("project_id")
@click.option("--feedback", default=None)
@click.option("--wait", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_story_cores(
    ctx: click.Context, project_id: str, feedback: str | None, wait: bool, json_output: bool
) -> None:
    """Generate story core candidates (novel) via platform AI [后备].

    推荐由 Agent 本地生成方向后回填（不消耗平台生成资源、结果可控）：
      scriptnow novel propose <project_id> cores <file.json>
      -- 文件格式：{"drafts": [{"title","premise","point_of_view",
      "narrative_constraints":[],"angles":[]}]}，1-3 个 draft；
      可加 --adopt 直接采纳最佳候选。
    本命令是平台 AI 生成，仅在 Agent 无法自行产出方向时使用。
    """
    session = _session(ctx)
    body = {"idempotency_key": f"cli-cores-{__import__('time').time_ns()}", "feedback": feedback}
    result = session.request(
        "POST",
        f"/novel/projects/{project_id}/story-cores/generate?background=true",
        json_body=body,
        write=True,
    )
    if wait and result.get("run_id"):
        _wait_for_run(session, project_id, str(result["run_id"]), json_output)
        return
    _emit(result, json_output)


@novel_group.command("adopt-core")
@click.argument("project_id")
@click.argument("candidate_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_adopt_core(ctx: click.Context, project_id: str, candidate_id: str, json_output: bool) -> None:
    """Adopt a story core candidate (novel)."""
    _emit(
        _session(ctx).request(
            "POST",
            f"/novel/projects/{project_id}/story-cores/{candidate_id}/adopt",
            write=True,
        ),
        json_output,
    )


@novel_group.command("blueprint")
@click.argument("project_id")
@click.option("--feedback", default=None)
@click.option("--wait", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_blueprint(
    ctx: click.Context, project_id: str, feedback: str | None, wait: bool, json_output: bool
) -> None:
    """Generate a blueprint candidate (novel) via platform AI [后备].

    推荐由 Agent 本地生成锚点后回填：
      scriptnow novel propose <project_id> blueprint <file.json>
      -- {"anchors":[{"id":"kind:key","kind":"world|character|relationship|
      character_arc|plot|foreshadow|motif","name","payload":{}}]}
      可加 --adopt 直接采纳。
    本命令是平台 AI 生成，仅在 Agent 无法自行产出蓝图时使用。
    """
    session = _session(ctx)
    body = {"idempotency_key": f"cli-bp-{__import__('time').time_ns()}", "feedback": feedback}
    result = session.request(
        "POST",
        f"/novel/projects/{project_id}/blueprints/generate?background=true",
        json_body=body,
        write=True,
    )
    if wait and result.get("run_id"):
        _wait_for_run(session, project_id, str(result["run_id"]), json_output)
        return
    _emit(result, json_output)


@novel_group.command("adopt-blueprint")
@click.argument("project_id")
@click.argument("candidate_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_adopt_blueprint(ctx: click.Context, project_id: str, candidate_id: str, json_output: bool) -> None:
    """Adopt a blueprint candidate (novel)."""
    _emit(
        _session(ctx).request(
            "POST",
            f"/novel/projects/{project_id}/blueprints/{candidate_id}/adopt",
            write=True,
        ),
        json_output,
    )


@novel_group.command("bootstrap")
@click.argument("project_id")
@click.option("--cores-file", default=None, type=click.Path(exists=True, dir_okay=False),
              help="故事核心回填 JSON（推荐：Agent 本地生成 → propose；不传则平台 AI 生成，增加平台压力）")
@click.option("--blueprint-file", default=None, type=click.Path(exists=True, dir_okay=False),
              help="蓝图回填 JSON（推荐：Agent 本地生成 → propose；不传则平台 AI 生成，增加平台压力）")
@click.option("--storymap-file", default=None, type=click.Path(exists=True, dir_okay=False),
              help="StoryMap 回填 JSON（推荐：Agent 本地生成 → propose；不传则平台 AI 生成，增加平台压力）")
@click.option("--budget", type=int, default=None, help="回填内容 token 预算上限（中文≈1 token/字，英文≈1 token/4 字符）")
@click.option("--cores-feedback", default=None, help="故事核心生成反馈（仅平台生成时使用）")
@click.option("--blueprint-feedback", default=None, help="蓝图生成反馈（仅平台生成时使用）")
@click.option("--stop-at", type=click.Choice(["cores", "blueprint", "storymap"]), default=None, help="在哪个阶段后停止（默认跑完整规划）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_bootstrap(
    ctx: click.Context,
    project_id: str,
    cores_file: str | None,
    blueprint_file: str | None,
    storymap_file: str | None,
    budget: int | None,
    cores_feedback: str | None,
    blueprint_feedback: str | None,
    stop_at: str | None,
    json_output: bool,
) -> None:
    """一键完成小说规划：故事核心(3候选)→采纳→蓝图→采纳→StoryMap→采纳。

    Agent 处理优先：传入 --*-file（本地生成的 JSON）则走 propose 回填，
    未传该文件时才由平台 AI 生成（后备）。可 --stop-at cores|blueprint 在
    中间停下让人审阅候选。
    """
    import json as _json
    import time as _time

    session = _session(ctx)
    steps: list[dict[str, Any]] = []

    def note(step: str, ok: bool, detail: str = "") -> None:
        steps.append({"step": step, "ok": ok, "detail": detail})
        if not json_output:
            mark = ui.ok("") if ok else ui.error("")
            click.echo(f"  {mark}{step}{(' · ' + detail) if detail else ''}", err=True)

    def load_json(file_path: str | None) -> dict[str, Any] | None:
        if not file_path:
            return None
        try:
            return _json.loads(Path(file_path).read_text(encoding="utf-8"))
        except (_json.JSONDecodeError, OSError) as error:
            raise click.ClickException(f"回填 JSON 解析失败（{file_path}）：{error}") from error

    # ① story cores
    cores_source = "Agent 回填" if cores_file else "平台 AI"
    if cores_file:
        data = load_json(cores_file)
        drafts = (data or {}).get("drafts") or []
        if not 1 <= len(drafts) <= 3:
            raise click.ClickException("cores 回填需要 1 到 3 个 draft")
        _check_budget(drafts, budget, "故事方向回填", json_output)
        result = session.request(
            "POST",
            f"/novel/projects/{project_id}/story-cores/propose",
            json_body={
                "idempotency_key": f"cli-boot-cores-{_time.time_ns()}",
                "drafts": drafts,
            },
            write=True,
        )
        if isinstance(result, list):
            result = result[0] if result else {}
    else:
        gen = session.request(
            "POST",
            f"/novel/projects/{project_id}/story-cores/generate?background=true",
            json_body={
                "idempotency_key": f"cli-boot-cores-{_time.time_ns()}",
                "feedback": cores_feedback,
            },
            write=True,
        )
        if gen.get("run_id"):
            _wait_for_run(session, project_id, str(gen["run_id"]), True, domain="novel")
    state = _novel_state(session, project_id)
    cores = [c for c in state.get("story_cores") or [] if c.get("status") in ("candidate", "active")]
    if not cores:
        note(f"故事核心（{cores_source}）", False, "没有候选，请检查 direction 是否完整")
        _emit({"project_id": project_id, "steps": steps}, json_output)
        return
    cores.sort(key=lambda c: c.get("ordinal", 0))
    session.request(
        "POST",
        f"/novel/projects/{project_id}/story-cores/{cores[0]['id']}/adopt",
        write=True,
    )
    note(f"故事核心生成并采纳（{cores_source}）", True, cores[0].get("title"))
    if stop_at == "cores":
        _emit({"project_id": project_id, "steps": steps}, json_output)
        return

    # ② blueprint
    blueprint_source = "Agent 回填" if blueprint_file else "平台 AI"
    if blueprint_file:
        data = load_json(blueprint_file)
        anchors = (data or {}).get("anchors") or []
        _check_budget(anchors, budget, "蓝图回填", json_output)
        if not anchors:
            raise click.ClickException("blueprint 回填需要至少 1 个 anchor")
        allowed = {"world", "character", "relationship", "character_arc", "plot", "foreshadow", "motif"}
        for anchor in anchors:
            if anchor.get("kind") not in allowed:
                raise click.ClickException(
                    f"anchor kind 必须是 {sorted(allowed)}，收到：{anchor.get('kind')}"
                )
        session.request(
            "POST",
            f"/novel/projects/{project_id}/blueprints/propose",
            json_body={
                "idempotency_key": f"cli-boot-bp-{_time.time_ns()}",
                "anchors": anchors,
            },
            write=True,
        )
    else:
        gen = session.request(
            "POST",
            f"/novel/projects/{project_id}/blueprints/generate?background=true",
            json_body={
                "idempotency_key": f"cli-boot-bp-{_time.time_ns()}",
                "feedback": blueprint_feedback,
            },
            write=True,
        )
        if gen.get("run_id"):
            _wait_for_run(session, project_id, str(gen["run_id"]), True, domain="novel")
    state = _novel_state(session, project_id)
    bp = next((c for c in state.get("blueprint_candidates") or [] if c.get("status") == "active"), None)
    if bp is None:
        note(f"蓝图（{blueprint_source}）", False, "没有候选")
        _emit({"project_id": project_id, "steps": steps}, json_output)
        return
    session.request(
        "POST",
        f"/novel/projects/{project_id}/blueprints/{bp['id']}/adopt",
        write=True,
    )
    anchor_count = len((state.get("blueprint") or {}).get("anchors") or [])
    note(f"蓝图生成并采纳（{blueprint_source}）", True, f"锚点 {anchor_count} 个")
    if stop_at == "blueprint":
        _emit({"project_id": project_id, "steps": steps}, json_output)
        return

    # ③ storymap
    # ③ storymap
    storymap_source = "Agent 回填" if storymap_file else "平台 AI"
    if storymap_file:
        data = load_json(storymap_file)
        volumes = (data or {}).get("volumes") or []
        _check_budget(volumes, budget, "卷章结构回填", json_output)
        if not volumes:
            raise click.ClickException("storymap 回填需要至少 1 个 volume")
        state = _novel_state(session, project_id)
        version = int((state.get("story_map") or {}).get("version") or 1)
        session.request(
            "POST",
            f"/novel/projects/{project_id}/story-map/propose",
            json_body={
                "idempotency_key": f"cli-boot-sm-{_time.time_ns()}",
                "expected_version": version,
                "volumes": volumes,
            },
            write=True,
        )
    else:
        gen = session.request(
            "POST",
            f"/novel/projects/{project_id}/story-map/generate?background=true",
            json_body={
                "idempotency_key": f"cli-boot-sm-{_time.time_ns()}",
                "feedback": None,
            },
            write=True,
        )
        if gen.get("run_id"):
            _wait_for_run(session, project_id, str(gen["run_id"]), True, domain="novel")
    state = _novel_state(session, project_id)
    sm = next((c for c in state.get("story_map_candidates") or [] if c.get("status") == "active"), None)
    if sm is None:
        note(f"StoryMap（{storymap_source}）", False, "没有候选")
        _emit({"project_id": project_id, "steps": steps}, json_output)
        return
    session.request(
        "POST",
        f"/novel/projects/{project_id}/story-map/{sm['id']}/adopt?confirm=true",
        write=True,
    )
    volumes = state.get("story_map", {}).get("volumes", [])
    total_chapters = sum(len(v.get("chapters", [])) for v in volumes)
    note(f"StoryMap 生成并采纳（{storymap_source}）", True, f"{len(volumes)} 卷 {total_chapters} 章")
    _emit({"project_id": project_id, "steps": steps, "story_map_ready": True}, json_output)


@novel_group.command("propose")
@click.argument("project_id")
@click.argument("kind", type=click.Choice(["cores", "blueprint", "storymap", "bibles"]))
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--adopt", is_flag=True, help="propose 成功后自动采纳（采纳最佳候选）")
@click.option("--budget", type=int, default=None, help="导入内容 token 预算上限；超限拒绝（如 20000）。中文≈1 token/字，英文≈1 token/4 字符")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_propose(
    ctx: click.Context, project_id: str, kind: str, file_path: str, adopt: bool, budget: int | None, json_output: bool
) -> None:
    """从本地 JSON 导入创作候选（Agent 本地生成 → 标准格式导入，降低平台生成压力）。

    kind:
      cores      — 1 到 3 个故事方向候选（可只给 1 个主推，直接采纳）：{"drafts":[{"title","premise","point_of_view",
                   "narrative_constraints":[],"angles":["欲望","阻力","情感承诺","道德困境","结局代价"]}]}
      blueprint  — 蓝图锚点：{"anchors":[{"id":"kind:key","kind":"world|character|relationship|
                   character_arc|plot|foreshadow|motif","name","payload":{}}]}
      storymap   — 卷章结构：{"volumes":[{"id","ordinal","title","chapters":[
                   {"id","ordinal","title","target_words","point_of_view","beats":[
                   {"id","objective","anchor_ids":[]}]}]}]}
      bibles     — 人物圣经（逐条采纳）：{"bibles":[{"character_key","display_name","profile":{},
                   "source_note"?}]}
    storymap 导入前需已采纳 blueprint（beats 引用的 anchor_ids 必须存在）；
    bibles 建议在采纳 blueprint 后回填（character_key 通常与蓝图锚点一致）。
    """
    import json as _json

    raw = Path(file_path).read_text(encoding="utf-8")
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"JSON 解析失败：{error}") from error
    if not isinstance(data, dict):
        raise click.ClickException("JSON 根必须是对象")
    session = _session(ctx)
    idem = f"cli-propose-{kind}-{__import__('time').time_ns()}"

    if kind == "cores":
        drafts = data.get("drafts") or []
        if not 1 <= len(drafts) <= 3:
            raise click.ClickException("story cores 需要 1 到 3 个 draft（可只给 1 个主推方向）")
        _check_budget(drafts, budget, "故事方向", json_output)
        body = {"idempotency_key": idem, "drafts": drafts}
        result = session.request(
            "POST", f"/novel/projects/{project_id}/story-cores/propose", json_body=body, write=True
        )
        # story-cores/propose 返回 3 个候选的 list；取第一个用于 adopt。
        if isinstance(result, list):
            result = result[0] if result else {}
    elif kind == "blueprint":
        anchors = data.get("anchors") or []
        if not anchors:
            raise click.ClickException("blueprint 需要至少 1 个 anchor")
        allowed = {"world", "character", "relationship", "character_arc", "plot", "foreshadow", "motif"}
        for anchor in anchors:
            if anchor.get("kind") not in allowed:
                raise click.ClickException(
                    f"anchor kind 必须是 {sorted(allowed)}，收到：{anchor.get('kind')}"
                )
        _check_budget(anchors, budget, "蓝图锚点", json_output)
        body = {"idempotency_key": idem, "anchors": anchors}
        result = session.request(
            "POST", f"/novel/projects/{project_id}/blueprints/propose", json_body=body, write=True
        )
    else:  # storymap
        volumes = data.get("volumes") or []
        if not volumes:
            raise click.ClickException("storymap 需要至少 1 个 volume")
        _check_budget(volumes, budget, "卷章结构", json_output)
        state = _novel_state(session, project_id)
        version = int((state.get("story_map") or {}).get("version") or 1)
        body = {
            "idempotency_key": idem,
            "expected_version": version,
            "volumes": volumes,
        }
        result = session.request(
            "POST", f"/novel/projects/{project_id}/story-map/propose", json_body=body, write=True
        )
    if kind == "bibles":
        # 人物圣经是逐条采纳（PUT），不是 propose→adopt；--adopt 参数在此无意义。
        bibles = data.get("bibles") or []
        if not bibles:
            raise click.ClickException("bibles 需要至少 1 条人物圣经")
        _check_budget(bibles, budget, "人物圣经", json_output)
        adopted = []
        for bible in bibles:
            if not bible.get("character_key") or not bible.get("display_name"):
                raise click.ClickException("每条 bible 需要 character_key 与 display_name")
            record = session.request(
                "PUT",
                f"/novel/projects/{project_id}/characters/bibles",
                json_body={
                    "character_key": bible["character_key"],
                    "display_name": bible["display_name"],
                    "profile": dict(bible.get("profile") or {}),
                    "source_note": bible.get("source_note"),
                },
                write=True,
            )
            adopted.append(
                {"character_key": record.get("character_key"), "status": record.get("status")}
            )
        _emit({"adopted_bibles": adopted}, json_output)
        return
    candidate_id = str(result.get("id") or "")
    payload: dict[str, Any] = {"candidate_id": candidate_id, "status": result.get("status")}
    if adopt and candidate_id:
        if kind == "cores":
            adopted = session.request(
                "POST",
                f"/novel/projects/{project_id}/story-cores/{candidate_id}/adopt",
                write=True,
            )
            payload["adopted"] = adopted.get("status")
        elif kind == "blueprint":
            adopted = session.request(
                "POST",
                f"/novel/projects/{project_id}/blueprints/{candidate_id}/adopt",
                write=True,
            )
            payload["adopted"] = adopted.get("status")
        else:
            adopted = session.request(
                "POST",
                f"/novel/projects/{project_id}/story-map/{candidate_id}/adopt?confirm=true",
                write=True,
            )
            payload["adopted"] = adopted.get("status")
    _emit(payload, json_output)


@novel_group.command("planning-quality")
@click.argument("project_id")
@click.argument("kind", type=click.Choice(["cores", "blueprint", "storymap", "bibles"]))
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_planning_quality(
    ctx: click.Context, project_id: str, kind: str, file_path: str, json_output: bool
) -> None:
    """评估规划产物质量（cores/blueprint/storymap/bibles）。

    校验必须交付字段（风格/类型/语言/卷章规划）与内容长度标准；bibles 还会
    对照已采纳蓝图锚点。产物内容从本地 JSON 读取（与 propose 相同的格式），
    服务端确定性评估，输出 pass/revise/block 与 evidence。
    """
    import json as _json

    raw = Path(file_path).read_text(encoding="utf-8")
    try:
        artifact = _json.loads(raw)
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"JSON 解析失败：{error}") from error
    if not isinstance(artifact, dict):
        raise click.ClickException("JSON 根必须是对象")
    _emit(
        _session(ctx).request(
            "POST",
            f"/novel/projects/{project_id}/planning-quality",
            json_body={"artifact_kind": kind, "artifact": artifact},
            write=True,
        ),
        json_output,
    )


@novel_group.command("orchestrate")
@click.argument("project_id")
@click.option("--storymap-candidate", "candidate_id", default=None, help="要审阅/采纳的 storymap 候选 id（默认取最新 active 候选）")
@click.option("--adjust", "adjust_file", default=None, help="审阅后调整：传入修改后的 storymap JSON（@file），重新 propose 并采纳")
@click.option("--accept", is_flag=True, help="确认接受当前 storymap 候选并采纳")
@click.option("--skip-adopt", is_flag=True, help="只展示候选与计划，不自动采纳（等人工决策）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_orchestrate(
    ctx: click.Context,
    project_id: str,
    candidate_id: str | None,
    adjust_file: str | None,
    accept: bool,
    skip_adopt: bool,
    json_output: bool,
) -> None:
    """编排故事结构：审阅 storymap 候选 → 决定 接受/调整 → 采纳 → 输出全书创作计划。

    这是「用户是否对 storymap 进行调整」的显式决策步骤：
      1. 展示当前 storymap 候选（卷/章/节拍摘要）。
      2. 决策：
         --accept        采纳当前候选；
         --adjust @file  用修改后的 JSON 重新导入并采纳（旧的自动过期）；
         都不传则只展示（配合 --skip-adopt 完全等人决定）。
      3. 采纳后输出 book plan（各章创作状态），作为逐章创作的起点。
    """
    import json as _json

    session = _session(ctx)
    state = _novel_state(session, project_id)
    story_map = state.get("story_map") or {}
    candidates = state.get("story_map_candidates") or []
    active = [c for c in candidates if c.get("status") in ("active", "candidate")]
    if candidate_id:
        chosen = next((c for c in active if c.get("id") == candidate_id), None)
    else:
        chosen = active[0] if active else None
    if chosen is None and adjust_file is None:
        raise click.ClickException(
            "没有可审阅的 storymap 候选。先用 storymap generate 生成，或 novel propose storymap @file 导入。"
        )

    def summarize(cand: dict[str, Any]) -> dict[str, Any]:
        volumes = cand.get("volumes") or []
        return {
            "candidate_id": cand.get("id"),
            "status": cand.get("status"),
            "volumes": len(volumes),
            "chapters": sum(len(v.get("chapters", [])) for v in volumes),
            "structure": [
                {
                    "volume": v.get("title"),
                    "chapters": [c.get("title") for c in (v.get("chapters") or [])],
                }
                for v in volumes
            ],
        }

    # ① 展示候选供审阅
    if chosen is not None and not json_output:
        click.echo(ui.section("=== 当前 StoryMap 候选（审阅）==="), err=True)
        for vol in summarize(chosen).get("structure", []):
            click.echo(f"  卷 · {vol['volume']}", err=True)
            for title in vol["chapters"]:
                click.echo(f"    - {title}", err=True)
    elif chosen is not None:
        _emit(summarize(chosen), json_output)
        return

    final_candidate = chosen
    # ② 用户决策：调整 → 重新导入
    if adjust_file:
        import pathlib as _pl

        raw = _pl.Path(adjust_file[1:] if adjust_file.startswith("@") else adjust_file).read_text(
            encoding="utf-8"
        )
        data = _json.loads(raw)
        version = int(story_map.get("version") or 1)
        body = {
            "idempotency_key": f"cli-orchestrate-adjust-{__import__('time').time_ns()}",
            "expected_version": version,
            "volumes": data.get("volumes") or [],
        }
        result = session.request(
            "POST",
            f"/novel/projects/{project_id}/story-map/propose",
            json_body=body,
            write=True,
        )
        final_candidate = {
            "id": result.get("id"),
            "status": result.get("status"),
            "volumes": data.get("volumes") or [],
        }
        if not json_output:
            click.echo(
                f"已用调整后的 JSON 重新导入（候选 {result.get('id')}，旧候选自动过期）", err=True
            )

    # ③ 采纳（除非 --skip-adopt 且无 accept）
    if not skip_adopt or accept:
        if final_candidate is None or not final_candidate.get("id"):
            raise click.ClickException("没有可采纳的 storymap 候选")
        adopted = session.request(
            "POST",
            f"/novel/projects/{project_id}/story-map/{final_candidate['id']}/adopt?confirm=true",
            write=True,
        )
        if not json_output:
            click.echo(ui.ok(f"全书结构已定稿（{_status_word(adopted.get('status'), medium='novel')}）——下面打印全书创作计划。"), err=True)

    # ④ 输出全书创作计划
    fresh = _novel_state(session, project_id)
    volumes = (fresh.get("story_map") or {}).get("volumes", [])
    documents = fresh.get("documents") or []
    plan = []
    for volume in volumes:
        for chapter in volume.get("chapters", []):
            cid = str(chapter["id"])
            docs = [d for d in documents if d.get("chapter_id") == cid]
            adopted = next((d for d in docs if d.get("status") == "adopted"), None)
            candidates = [d for d in docs if d.get("status") in ("candidate", "active")]
            candidates.sort(key=lambda d: d.get("revision_number", 0), reverse=True)
            plan.append({
                "chapter_id": cid,
                "title": chapter.get("title"),
                "ordinal": chapter.get("ordinal"),
                "target_words": chapter.get("target_words"),
                "state": {
                    "adopted_revision": adopted.get("revision_number") if adopted else None,
                    "candidate_revisions": [d.get("revision_number") for d in candidates],
                    "needs_generation": adopted is None and not candidates,
                },
            })
    _emit({
        "project_id": project_id,
        "storymap_adopted": not skip_adopt or accept,
        "adopted_candidate_id": final_candidate.get("id") if final_candidate else None,
        "total_chapters": len(plan),
        "needs_generation": [p["chapter_id"] for p in plan if p["state"]["needs_generation"]],
        "plan": plan,
    }, json_output)


# ------------------------------------------------------------------------ script


@main.group("script")
@click.pass_context
def script_group(ctx: click.Context) -> None:
    """剧本创作链：状态 / 故事核心 / 蓝图 / 剧集结构 / 场次。"""


@main.group("scene")
@click.pass_context
def scene_group(ctx: click.Context) -> None:
    """剧本场次（与 chapter 组对称）：列表 / 阅读 / 生成 / 采纳 / 回传 / 批量 / 质量 / 差异。"""


@scene_group.command("list")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def scene_list(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """List scenes (alias of script scene-list)."""
    script_scene_list.callback(project_id, json_output)


@scene_group.command("show")
@click.argument("project_id")
@click.argument("scene_id")
@click.option("--revision", default=None, help="Revision id or number; defaults to adopted, else latest candidate")
@click.option("--plain", is_flag=True, help="Emit only the script text for direct reading")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def scene_show(
    ctx: click.Context, project_id: str, scene_id: str, revision: str | None, plain: bool, json_output: bool
) -> None:
    """Show a scene (alias of script scene-show)."""
    script_scene_show.callback(project_id, scene_id, revision, plain, json_output)


@scene_group.command("generate")
@click.argument("project_id")
@click.argument("scene_id")
@click.option("--feedback", default=None)
@click.option("--model", "model_id", default=None, help="指定本项目中该场次写作使用的模型 id（仅项目写作，禁止用于非项目文本生成）")
@click.option("--wait", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def scene_generate(
    ctx: click.Context,
    project_id: str,
    scene_id: str,
    feedback: str | None,
    model_id: str | None,
    wait: bool,
    json_output: bool,
) -> None:
    """Generate a scene candidate (alias of script scene)."""
    script_scene.callback(project_id, scene_id, feedback, model_id, wait, json_output)


@scene_group.command("adopt")
@click.argument("project_id")
@click.argument("scene_id")
@click.argument("revision_id")
@click.option(
    "--human",
    "human_decision",
    is_flag=True,
    help="人工决定已明确：用户本人执行，或已在与 Agent 的对话中明确表示定稿/采用这版",
)
@click.option(
    "--token",
    "decision_token",
    default=None,
    help="可选增强审计令牌；用户在对话中明确采用时，Agent 直接使用 --human 即可",
)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def scene_adopt(ctx: click.Context, project_id: str, scene_id: str, revision_id: str, human_decision: bool, decision_token: str | None, json_output: bool) -> None:
    """Adopt a scene revision (alias of script adopt-scene)."""
    script_adopt_scene.callback(project_id, scene_id, revision_id, human_decision, decision_token, json_output)


@scene_group.command("propose")
@click.argument("project_id", required=False)
@click.argument("scene_id", required=False)
@click.option("--file", "blocks_file", default=None, help="blocks JSON 路径（@file 前缀表示文本文件），每项 {para_id,type,text}")
@click.option("--text", default=None, help="纯文本：首段作 slugline，其余按 action block 回传")
@click.option("--budget", type=int, default=None, help="token 预算上限（超限拒绝）")
@click.option("--auto-adopt", is_flag=True, help="回传后自动采纳该候选")
@click.option("--help-format", is_flag=True, help="显示 blocks JSON 格式说明")
@click.option("--example", is_flag=True, help="显示示例文本")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def scene_propose(
    ctx: click.Context,
    project_id: str,
    scene_id: str,
    blocks_file: str | None,
    text: str | None,
    budget: int | None,
    auto_adopt: bool,
    help_format: bool,
    example: bool,
    json_output: bool,
) -> None:
    """Agent 本地创作场次 → 回传为候选（alias of script scene-propose）。"""
    script_scene_propose.callback(
        project_id, scene_id, blocks_file, text, budget, auto_adopt, help_format, example, json_output
    )


@scene_group.command("batch")
@click.argument("project_id")
@click.option("--scenes", default=None, help="逗号分隔的场次 id（与 --resume-from 二选一）")
@click.option("--feedback", default=None, help="统一创作/修订反馈")
@click.option("--model", "model_id", default=None, help="批量场次写作统一使用的模型 id（仅项目写作，禁止用于非项目文本生成）")
@click.option("--save-progress", "progress_file", default=None, help="完成后保存失败清单（续跑用）")
@click.option("--resume-from", "resume_file", default=None, help="从上次失败清单续跑（JSON 文件，含 failed 列表）")
@click.option("--yes", is_flag=True, help="确认已知风险后跳过警告")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def scene_batch(
    ctx: click.Context,
    project_id: str,
    scenes: str | None,
    feedback: str | None,
    model_id: str | None,
    progress_file: str | None,
    resume_file: str | None,
    yes: bool,
    json_output: bool,
) -> None:
    """Serialize scene generation (alias of script scene-batch)."""
    script_scene_batch.callback(project_id, scenes, feedback, model_id, progress_file, resume_file, yes, json_output)


@scene_group.command("quality")
@click.argument("project_id")
@click.argument("scene_id")
@click.option("--revision", default=None, help="Revision id or number; defaults to adopted, else latest candidate")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def scene_quality(
    ctx: click.Context, project_id: str, scene_id: str, revision: str | None, json_output: bool
) -> None:
    """Evaluate a scene revision (alias of script scene-quality)."""
    script_scene_quality.callback(project_id, scene_id, revision, json_output)


@scene_group.command("diff")
@click.argument("scene_id")
@click.option("--project", "project_id", default=None, help="项目 id（默认取 project use 设定的项目）")
@click.option("--from", "from_rev", required=True, help="起始修订号/id")
@click.option("--to", "to_rev", required=True, help="目标修订号/id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def scene_diff(
    ctx: click.Context,
    scene_id: str,
    project_id: str | None,
    from_rev: str,
    to_rev: str,
    json_output: bool,
) -> None:
    """Diff two scene revisions (alias of script scene-diff)."""
    script_scene_diff.callback(scene_id, project_id, from_rev, to_rev, json_output)


def _planning_contract_complete(unit: object, key: str) -> bool:
    """Return whether a unit carries the causal planning minimum.

    Keep this read-only check tolerant of transitional payloads. The server is
    still the final validator; this command only gives agents an actionable
    preflight before they start a generation run.
    """
    if not isinstance(unit, dict):
        return False
    # Script episodes expose the outline fields at the episode level. Novel
    # chapters embed them under ``outline``. ``key`` is retained in the call
    # sites as a domain-readable label, not as a wire-field assumption.
    contract = unit if key == "episode_contract" else unit.get("outline")
    if not isinstance(contract, dict):
        return False
    if key == "chapter_contract":
        if not str(contract.get("summary") or contract.get("logline") or "").strip():
            return False
    else:
        if not str(contract.get("logline") or "").strip():
            return False
    for field in ("active_goal", "conflict", "turn"):
        if not str(contract.get(field) or "").strip():
            return False
    state_changes = contract.get("state_changes")
    if isinstance(state_changes, dict):
        if not any(str(k).strip() and str(v).strip() for k, v in state_changes.items()):
            return False
    elif not isinstance(state_changes, list) or not state_changes:
        return False
    anchors = contract.get("anchor_ids")
    if not anchors and key == "chapter_contract":
        anchors = [
            anchor
            for beat in (unit.get("beats") or [])
            if isinstance(beat, dict)
            for anchor in (beat.get("anchor_ids") or [])
        ]
    if not isinstance(anchors, list) or not anchors:
        return False
    return True


def _all_planning_contracts(units: object, key: str) -> bool:
    return isinstance(units, list) and bool(units) and all(
        _planning_contract_complete(unit, key) for unit in units
    )


@script_group.command("ready-check")
@click.argument("project_id", required=False)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_ready_check(ctx: click.Context, project_id: str | None, json_output: bool) -> None:
    """剧本逐场写作前置完整性检查（强制 gate）：方向 / 核心 / 蓝图 / 集纲 / StoryMap / Skill。"""
    pid = _resolve_project_id(ctx, project_id)
    session = _session(ctx)
    state = session.request("GET", f"/script/projects/{pid}/state")
    checks = [
        ("创作方向（direction）", bool(state.get("story_cores") or state.get("blueprint")), "project direction --apply @direction.json"),
        ("故事核心（adopted core）", bool([c for c in (state.get("story_cores") or []) if c.get("status") in ("adopted", "active")]), "script propose cores @file --adopt"),
        ("蓝图（blueprint）", state.get("blueprint") is not None, "script propose blueprint @file --adopt"),
        ("StoryMap", bool((state.get("story_map") or {}).get("episodes")), "script propose storymap @file 或 script storymap --wait"),
    ]
    outline = _api_request(ctx, "GET", f"/script/projects/{pid}/synopsis-outline")
    checks.append(("梗概大纲（已定稿）", bool(outline and outline.get("status") == "adopted"), 'script outline <作品号> --text "…" → script outline-adopt'))
    episodes = (state.get("story_map") or {}).get("episodes") or []
    checks.append(("集纲（全剧 Episode 平铺字段）", _all_planning_contracts(episodes, "episode_contract"), "可用 script episode-outline <pid> <episode_id> @outline.json 单集补纲；完成全量后运行 script planning-quality → propose/adopt"))
    try:
        mounted = session.request("GET", f"/projects/{pid}/skills")
        skills = [str(i.get("name") or "") for i in mounted] if isinstance(mounted, list) else []
    except Exception:
        skills = []
    checks.append(("方法论 Skill", bool(skills), "interpret local 一书一 Skill 或 skill create → skill mount"))
    if json_output:
        _emit({"project_id": pid, "ready": all(c[1] for c in checks), "checks": [
            {"item": c[0], "ok": c[1], "fix": c[2]} for c in checks
        ], "skills": skills}, json_output)
        return
    all_ok = True
    for name, ok, fix in checks:
        mark = ui.ok("✓") if ok else ui.error("✗")
        if not ok:
            all_ok = False
        click.echo(f"  {mark} {name}" + ("" if ok else f"  → {fix}"), err=True)
    click.echo(ui.ok(f"创作前检查通过：{sum(1 for c in checks if c[1])}/{len(checks)} 项就绪" if all_ok else ui.error(f"还差 {sum(1 for c in checks if not c[1])} 项未就绪——按上面提示补齐")), err=True)




@script_group.command("episode-outline")
@click.argument("project_id")
@click.argument("episode_id")
@click.argument("file_path", type=str)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_episode_outline(
    ctx: click.Context, project_id: str, episode_id: str, file_path: str, json_output: bool
) -> None:
    """回填单集纲（旧项目补纲入口；保存为 StoryMap 结构候选）。

    FILE_PATH is a JSON object containing the episode outline fields or an
    ``outline`` wrapper. Existing episodes/scenes are preserved by the server;
    the candidate still requires normal StoryMap review and adoption.
    """
    import json as _json

    path = file_path[1:] if file_path.startswith("@") else file_path
    try:
        raw = _json.loads(Path(path).read_text(encoding="utf-8"))
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"集纲 JSON 解析失败：{error}") from error
    if not isinstance(raw, dict):
        raise click.ClickException("集纲 JSON 根必须是对象")
    outline = dict(raw.get("outline")) if isinstance(raw.get("outline"), dict) else dict(raw)
    outline.pop("expected_version", None)
    outline.pop("idempotency_key", None)
    outline.pop("outline", None)
    state = _session(ctx).request("GET", f"/script/projects/{project_id}/state")
    expected_version = int((state.get("story_map") or {}).get("version") or 0)
    result = _session(ctx).request(
        "POST",
        f"/script/projects/{project_id}/story-map/episodes/{episode_id}/outline/propose",
        json_body={
            "expected_version": expected_version,
            "idempotency_key": f"cli-episode-outline-{__import__('time').time_ns()}",
            **outline,
        },
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"第 {episode_id} 集集纲已形成结构候选（{result.get('id')}）"))
        click.echo(ui.dim("请回读 StoryMap、运行 planning-quality，并在用户明确决定后采纳。"), err=True)
        return
    _emit(result, json_output)


@script_group.command("state")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_state(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """Show script project state."""
    _emit(_session(ctx).request("GET", f"/script/projects/{project_id}/state"), json_output)


@script_group.command("outline")
@click.argument("project_id", required=False)
@click.option("--text", default=None, help="梗概大纲正文（≤500 字）")
@click.option("--file", default=None, help="@outline.txt（≤500 字）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_outline(
    ctx: click.Context, project_id: str | None, text: str | None, file: str | None, json_output: bool
) -> None:
    """回填剧本梗概大纲（≤500 字，早于 StoryMap 的渐进披露节点）→ 采纳后 StoryMap 才可规划。"""
    pid = _resolve_project_id(ctx, project_id)
    if not text and not file:
        raise click.ClickException("需要 --text 或 --file（梗概 ≤500 字）")
    if file:
        text = Path(file[1:] if file.startswith("@") else file).read_text(encoding="utf-8").strip()
    if len((text or "").strip()) > 500:
        raise click.ClickException("梗概大纲需在 500 字以内")
    result = _api_request(
        ctx,
        "POST",
        f"/script/projects/{pid}/synopsis-outline/propose",
        json_body={"content": (text or "").strip(), "idempotency_key": f"cli-script-outline-{__import__('time').time_ns()}"},
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"梗概大纲已回填（v{result.get('version')}，{_status_word(result.get('status'), medium='script')}）"))
        click.echo(ui.dim("  满意就采纳：scriptnow script outline-adopt <作品号>；采纳后即可规划剧集结构。"), err=True)
        return
    _emit(result, json_output)


@script_group.command("outline-adopt")
@click.argument("project_id", required=False)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_outline_adopt(ctx: click.Context, project_id: str | None, json_output: bool) -> None:
    """采纳剧本梗概大纲（StoryMap 规划的前置条件）。"""
    pid = _resolve_project_id(ctx, project_id)
    result = _api_request(ctx, "POST", f"/script/projects/{pid}/synopsis-outline/adopt", write=True)
    if not json_output:
        click.echo(ui.ok(f"梗概大纲已定稿（v{result.get('version')}）——接下来规划剧集结构（storymap）。"))
        return
    _emit(result, json_output)


@script_group.command("outline-status")
@click.argument("project_id", required=False)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_outline_status(ctx: click.Context, project_id: str | None, json_output: bool) -> None:
    """查看剧本梗概大纲状态与内容。"""
    pid = _resolve_project_id(ctx, project_id)
    outline = _api_request(ctx, "GET", f"/script/projects/{pid}/synopsis-outline")
    if not json_output:
        if not outline:
            click.echo(ui.warn("尚未回填梗概大纲。scriptnow script outline <作品号> --text '…'"))
            return
        click.echo(ui.kv("状态", _status_word(outline.get("status"), medium="script")))
        click.echo(ui.kv("版本", outline.get("version")))
        click.echo(outline.get("content") or "")
        return
    _emit(outline, json_output)


@script_group.command("scene-list")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_scene_list(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """List scenes from the adopted script StoryMap with document state."""
    state = _session(ctx).request("GET", f"/script/projects/{project_id}/state")
    story_map = state.get("story_map") or {}
    episodes = story_map.get("episodes") or []
    documents = state.get("documents") or []
    rows = []
    for episode in episodes:
        for scene in episode.get("scenes") or []:
            scene_id = str(scene["id"])
            docs = [doc for doc in documents if doc.get("scene_id") == scene_id]
            adopted = next((doc for doc in docs if doc.get("status") == "adopted"), None)
            candidates = [doc for doc in docs if doc.get("status") in ("candidate", "active")]
            candidates.sort(key=lambda doc: doc.get("revision_number", 0), reverse=True)
            rows.append({
                "scene_id": scene_id,
                "title": scene.get("title"),
                "episode": episode.get("title"),
                "adopted_revision": adopted.get("revision_number") if adopted else None,
                "candidate_revisions": [doc.get("revision_number") for doc in candidates],
                "latest_candidate_id": candidates[0].get("id") if candidates else None,
            })
    _emit(rows, json_output)


@script_group.command("scene-show")
@click.argument("project_id")
@click.argument("scene_id")
@click.option("--revision", default=None, help="Revision id or number; defaults to adopted, else latest candidate")
@click.option("--plain", is_flag=True, help="Emit only the script text for direct reading")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_scene_show(
    ctx: click.Context, project_id: str, scene_id: str, revision: str | None, plain: bool, json_output: bool
) -> None:
    """Show a scene's script text for agent review (review primitive).
    Read every line as a demanding viewer and a working screenwriter: judge
    each frame's purpose, each line's necessity. Never skim, never cheerlead;
    quote evidence for every verdict and drive fixes via feedback before adopt."""
    state = _session(ctx).request("GET", f"/script/projects/{project_id}/state")
    documents = state.get("documents") or []
    docs = [doc for doc in documents if doc.get("scene_id") == scene_id]
    if not docs:
        raise click.ClickException(f"no documents for scene {scene_id}")
    chosen = None
    if revision:
        chosen = next(
            (doc for doc in docs if doc.get("id") == revision or str(doc.get("revision_number")) == revision),
            None,
        )
        if chosen is None:
            raise click.ClickException(f"revision {revision} not found for scene {scene_id}")
    else:
        adopted = next((doc for doc in docs if doc.get("status") == "adopted"), None)
        if adopted:
            chosen = adopted
        else:
            candidates = sorted(
                [doc for doc in docs if doc.get("status") in ("candidate", "active")],
                key=lambda doc: doc.get("revision_number", 0),
                reverse=True,
            )
            chosen = candidates[0] if candidates else docs[0]
    blocks = chosen.get("blocks") or []
    text = "\n\n".join(
        (block.get("text") or "") for block in blocks if (block.get("text") or "").strip()
    )
    if plain:
        click.echo(text)
        return
    revision_summary = [
        {
            "revision_id": doc.get("id"),
            "revision_number": doc.get("revision_number"),
            "status": doc.get("status"),
            "source": doc.get("source"),
        }
        for doc in sorted(docs, key=lambda item: item.get("revision_number", 0))
    ]
    if not json_output:
        source_label = "平台生成" if chosen.get("source") == "platform" else "共创回填"
        status_label = _status_word(chosen.get("status"), medium="script")
        click.echo(ui.section(f"=== 本场（第 {chosen.get('revision_number', 1)} 版 · {source_label} · {status_label}）==="), err=True)
        click.echo(text, err=True)
        click.echo("", err=True)
        click.echo(ui.dim(_next_step_after_generate("script")), err=True)
        return
    _emit(
        {
            "scene_id": scene_id,
            "revision_id": chosen.get("id"),
            "revision_number": chosen.get("revision_number"),
            "source": chosen.get("source"),
            "status": chosen.get("status"),
            "text": text,
            "block_count": len(blocks),
            "revisions": revision_summary,
            "candidate_revisions": [
                item for item in revision_summary if item["status"] in ("candidate", "active")
            ],
            "adopted_revision": next(
                (item for item in revision_summary if item["status"] == "adopted"), None
            ),
        },
        json_output,
    )


@script_group.command("story-cores")
@click.argument("project_id")
@click.option("--feedback", default=None)
@click.option("--wait", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_story_cores(
    ctx: click.Context, project_id: str, feedback: str | None, wait: bool, json_output: bool
) -> None:
    """Generate story core candidates (script) via platform AI [后备].

    推荐由 Agent 本地生成方向后回填（不消耗平台生成资源、结果可控）：
      scriptnow script propose <project_id> cores <file.json>
      -- 文件格式：{"drafts": [{"title","concept","angles":[...],
      "details":{"narrative_engine":[],"viewpoint_anchor":[],"pacing_recipe":[],
      "market_judgement":[]}}]}，1-3 个 draft；
      可加 --adopt 直接采纳最佳候选。
    本命令是平台 AI 生成，仅在 Agent 无法自行产出方向时使用。
    """
    session = _session(ctx)
    body = {"idempotency_key": f"cli-scores-{__import__('time').time_ns()}", "feedback": feedback}
    result = session.request(
        "POST",
        f"/script/projects/{project_id}/story-cores/generate?background=true",
        json_body=body,
        write=True,
    )
    if wait and result.get("run_id"):
        _wait_for_run(session, project_id, str(result["run_id"]), json_output, domain="script")
        return
    _emit(result, json_output)


@script_group.command("adopt-core")
@click.argument("project_id")
@click.argument("candidate_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_adopt_core(ctx: click.Context, project_id: str, candidate_id: str, json_output: bool) -> None:
    """Adopt a story core candidate (script)."""
    _emit(
        _session(ctx).request(
            "POST", f"/script/projects/{project_id}/story-cores/{candidate_id}/adopt", write=True
        ),
        json_output,
    )


@script_group.command("planning-quality")
@click.argument("project_id")
@click.argument("kind", type=click.Choice(["cores", "blueprint", "storymap", "bibles"]))
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_planning_quality(
    ctx: click.Context, project_id: str, kind: str, file_path: str, json_output: bool
) -> None:
    """评估剧本规划产物质量（cores/blueprint/storymap/bibles）。

    校验必须交付字段（风格/类型/语言/分集时长规划）与内容长度标准；bibles
    对照已采纳蓝图锚点。产物内容从本地 JSON 读取，服务端确定性评估。
    """
    import json as _json

    raw = Path(file_path).read_text(encoding="utf-8")
    try:
        artifact = _json.loads(raw)
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"JSON 解析失败：{error}") from error
    if not isinstance(artifact, dict):
        raise click.ClickException("JSON 根必须是对象")
    _emit(
        _session(ctx).request(
            "POST",
            f"/script/projects/{project_id}/planning-quality",
            json_body={"artifact_kind": kind, "artifact": artifact},
            write=True,
        ),
        json_output,
    )


@script_group.command("propose")
@click.argument("project_id")
@click.argument("kind", type=click.Choice(["cores", "blueprint", "storymap", "bibles"]))
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--adopt", is_flag=True, help="propose 成功后自动采纳（采纳最佳候选）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_propose(
    ctx: click.Context, project_id: str, kind: str, file_path: str, adopt: bool, json_output: bool
) -> None:
    """从本地 JSON 导入创作候选（Agent 本地生成 → 标准格式导入，降低平台生成压力）。

    kind:
      cores      — 1 到 3 个故事方向候选（可只给 1 个主推，直接采纳）：{"drafts":[
                   {"title","concept","angles":["欲望","阻力","情感承诺","道德困境","结局代价"],
                   "details":{"narrative_engine":[],"viewpoint_anchor":[],"pacing_recipe":[],
                   "market_judgement":[]}}]}
      blueprint  — 蓝图锚点：{"anchors":[{"id":"kind:key","kind":"world|character|relationship|
                   character_arc|plot|foreshadow|motif","name","payload":{}}]}
      storymap   — 分集场次结构：{"episodes":[{"id","ordinal","title","scenes":[
                   {"id","ordinal","title","duration_seconds_target","beats":[{"id","objective",
                   "anchor_ids":[]}]}]}]}
      bibles     — 人物圣经（逐条采纳）：{"bibles":[{"character_key","display_name","profile":{},
                   "source_note"?}]}
    storymap 导入前需已采纳 blueprint（beats 引用的 anchor_ids 必须存在）；
    bibles 建议在采纳 blueprint 后回填（character_key 通常与蓝图锚点一致）。
    """
    import json as _json

    raw = Path(file_path).read_text(encoding="utf-8")
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"JSON 解析失败：{error}") from error
    if not isinstance(data, dict):
        raise click.ClickException("JSON 根必须是对象")
    session = _session(ctx)
    idem = f"cli-script-propose-{kind}-{__import__('time').time_ns()}"

    if kind == "cores":
        drafts = data.get("drafts") or []
        if not 1 <= len(drafts) <= 3:
            raise click.ClickException("script story cores 需要 1 到 3 个 draft（可只给 1 个主推方向）")
        body = {"idempotency_key": idem, "drafts": drafts}
        result = session.request(
            "POST", f"/script/projects/{project_id}/story-cores/propose", json_body=body, write=True
        )
        if isinstance(result, list):
            result = result[0] if result else {}
    elif kind == "blueprint":
        anchors = data.get("anchors") or []
        if not anchors:
            raise click.ClickException("blueprint 需要至少 1 个 anchor")
        allowed = {"world", "character", "relationship", "character_arc", "plot", "foreshadow", "motif"}
        for anchor in anchors:
            if anchor.get("kind") not in allowed:
                raise click.ClickException(
                    f"anchor kind 必须是 {sorted(allowed)}，收到：{anchor.get('kind')}"
                )
        body = {"idempotency_key": idem, "anchors": anchors}
        result = session.request(
            "POST", f"/script/projects/{project_id}/blueprints/propose", json_body=body, write=True
        )
    else:  # storymap
        episodes = data.get("episodes") or []
        if not episodes:
            raise click.ClickException("storymap 需要至少 1 个 episode")
        state = session.request("GET", f"/script/projects/{project_id}/state")
        version = int((state.get("story_map") or {}).get("version") or 1)
        body = {
            "idempotency_key": idem,
            "expected_version": version,
            "episodes": episodes,
        }
        result = session.request(
            "POST", f"/script/projects/{project_id}/story-map/propose", json_body=body, write=True
        )
    if kind == "bibles":
        # 人物圣经是逐条采纳（PUT），不是 propose→adopt；--adopt 参数在此无意义。
        bibles = data.get("bibles") or []
        if not bibles:
            raise click.ClickException("bibles 需要至少 1 条人物圣经")
        adopted = []
        for bible in bibles:
            if not bible.get("character_key") or not bible.get("display_name"):
                raise click.ClickException("每条 bible 需要 character_key 与 display_name")
            record = session.request(
                "PUT",
                f"/script/projects/{project_id}/characters/bibles",
                json_body={
                    "character_key": bible["character_key"],
                    "display_name": bible["display_name"],
                    "profile": dict(bible.get("profile") or {}),
                    "source_note": bible.get("source_note"),
                },
                write=True,
            )
            adopted.append(
                {"character_key": record.get("character_key"), "status": record.get("status")}
            )
        _emit({"adopted_bibles": adopted}, json_output)
        return
    candidate_id = str(result.get("id") or "")
    payload: dict[str, Any] = {"candidate_id": candidate_id, "status": result.get("status")}
    if adopt and candidate_id:
        if kind == "cores":
            adopted = session.request(
                "POST",
                f"/script/projects/{project_id}/story-cores/{candidate_id}/adopt",
                write=True,
            )
            payload["adopted"] = adopted.get("status")
        elif kind == "blueprint":
            adopted = session.request(
                "POST",
                f"/script/projects/{project_id}/blueprints/{candidate_id}/adopt",
                write=True,
            )
            payload["adopted"] = adopted.get("status")
        else:
            adopted = session.request(
                "POST",
                f"/script/projects/{project_id}/story-map/{candidate_id}/adopt",
                write=True,
            )
            payload["adopted"] = adopted.get("status")
    _emit(payload, json_output)


@script_group.command("blueprint")
@click.argument("project_id")
@click.option("--feedback", default=None)
@click.option("--wait", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_blueprint(
    ctx: click.Context, project_id: str, feedback: str | None, wait: bool, json_output: bool
) -> None:
    """Generate a blueprint candidate (script) via platform AI [后备].

    推荐由 Agent 本地生成锚点后回填：
      scriptnow script propose <project_id> blueprint <file.json>
      -- {"anchors":[{"id":"kind:key","kind":"world|character|relationship|
      character_arc|plot|foreshadow|motif","name","payload":{}}]}
      可加 --adopt 直接采纳。
    本命令是平台 AI 生成，仅在 Agent 无法自行产出蓝图时使用。
    """
    session = _session(ctx)
    body = {"idempotency_key": f"cli-sbp-{__import__('time').time_ns()}", "feedback": feedback}
    result = session.request(
        "POST",
        f"/script/projects/{project_id}/blueprints/generate?background=true",
        json_body=body,
        write=True,
    )
    if wait and result.get("run_id"):
        _wait_for_run(session, project_id, str(result["run_id"]), json_output, domain="script")
        return
    _emit(result, json_output)


@script_group.command("adopt-blueprint")
@click.argument("project_id")
@click.argument("candidate_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_adopt_blueprint(ctx: click.Context, project_id: str, candidate_id: str, json_output: bool) -> None:
    """Adopt a blueprint candidate (script)."""
    _emit(
        _session(ctx).request(
            "POST", f"/script/projects/{project_id}/blueprints/{candidate_id}/adopt", write=True
        ),
        json_output,
    )


@script_group.command("storymap")
@click.argument("project_id")
@click.option("--feedback", default=None)
@click.option("--wait", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_storymap(
    ctx: click.Context, project_id: str, feedback: str | None, wait: bool, json_output: bool
) -> None:
    """Generate a script StoryMap (episodes -> scenes) candidate via platform AI [后备].

    推荐由 Agent 本地生成分集场次后回填：
      scriptnow script propose <project_id> storymap <file.json>
      -- {"episodes":[{"id","ordinal","title","scenes":[{"id","ordinal","title",
      "duration_seconds_target","beats":[{"id","objective","anchor_ids":[]}]}]}]}
      可加 --adopt 直接采纳。
    本命令是平台 AI 生成，仅在 Agent 无法自行产出 StoryMap 时使用。
    """
    session = _session(ctx)
    body = {"idempotency_key": f"cli-ssm-{__import__('time').time_ns()}", "feedback": feedback}
    result = session.request(
        "POST",
        f"/script/projects/{project_id}/story-map/generate?background=true",
        json_body=body,
        write=True,
    )
    if wait and result.get("run_id"):
        _wait_for_run(session, project_id, str(result["run_id"]), json_output, domain="script")
        return
    _emit(result, json_output)


@script_group.command("adopt-storymap")
@click.argument("project_id")
@click.argument("candidate_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_adopt_storymap(ctx: click.Context, project_id: str, candidate_id: str, json_output: bool) -> None:
    """Adopt a script StoryMap candidate."""
    _emit(
        _session(ctx).request(
            "POST", f"/script/projects/{project_id}/story-map/{candidate_id}/adopt", write=True
        ),
        json_output,
    )


@script_group.command("scene")
@click.argument("project_id")
@click.argument("scene_id")
@click.option("--feedback", default=None)
@click.option("--model", "model_id", default=None, help="指定本项目中该场次写作使用的模型 id（仅项目写作，禁止用于非项目文本生成）")
@click.option("--wait", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_scene(
    ctx: click.Context,
    project_id: str,
    scene_id: str,
    feedback: str | None,
    model_id: str | None,
    wait: bool,
    json_output: bool,
) -> None:
    """Generate a scene candidate (script)."""
    session = _session(ctx)
    body: dict[str, Any] = {"idempotency_key": f"cli-scene-{__import__('time').time_ns()}", "feedback": feedback}
    if model_id:
        body["model_id"] = model_id
    try:
        result = session.request(
            "POST",
            f"/script/projects/{project_id}/scenes/{scene_id}/generate?background=true",
            json_body=body,
            write=True,
        )
    except ScriptNowError as error:
        if "concurrent" in str(error) or "already active" in str(error):
            raise click.ClickException(
                "并发逐场创作被拒绝：同一项目已有正文生成在运行。\n"
                "正确方式：逐场严格串行——用 scriptnow run status <run_id> 等当前生成完成后，再生成下一场。\n"
                "不要并发启动多个 scene generate（设定会漂移、伏笔会失联）。"
            ) from error
        raise
    if wait and result.get("run_id"):
        _wait_for_run(session, project_id, str(result["run_id"]), json_output, domain="script")
        return
    _emit(result, json_output)


@script_group.command("adopt-scene")
@click.argument("project_id")
@click.argument("scene_id")
@click.argument("revision_id")
@click.option(
    "--human",
    "human_decision",
    is_flag=True,
    help="人工决定已明确：用户本人执行，或已在与 Agent 的对话中明确表示定稿/采用这版",
)
@click.option(
    "--token",
    "decision_token",
    default=None,
    help="可选增强审计令牌；用户在对话中明确采用时，Agent 直接使用 --human 即可",
)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_adopt_scene(
    ctx: click.Context, project_id: str, scene_id: str, revision_id: str, human_decision: bool, decision_token: str | None, json_output: bool
) -> None:
    """Adopt a scene revision (script).

    定稿必须来自人的明确决定。用户本人运行，或在与 Agent 的对话中明确表示
    「定稿 / 采用这版 / 可以继续」后，均可带 --human；无需重复终端确认。
    """
    # --human 既可表示用户本人执行，也可表示 Agent 已收到用户在对话中的明确决定。
    # --token 仅为需要更强审计时的可选通道。
    if not decision_token and not human_decision:
        if not json_output:
            if not click.confirm(
                "你明确决定采用这份候选稿并将其定稿吗？",
                default=False,
            ):
                click.echo(ui.warn("已取消定稿——你可以继续讨论或修改；明确采用时再运行 scene adopt --human。"), err=True)
                return
            human_decision = True
        else:
            raise click.ClickException(
                "尚未收到人工决定。请先向用户呈现内容；用户在对话中明确表示定稿/采用后，"
                "Agent 可直接用 scene adopt --human。--token 仅为可选增强审计方式。"
            )
    # 前置检查：revision 定位 + 已定稿拦截（避免重复采纳撞 409）。
    # revision_id 支持 uuid 或版本号（rev1/1）——版本号自动从 state 解析为 uuid。
    resolved_revision_id = revision_id
    try:
        state = _session(ctx).request("GET", f"/script/projects/{project_id}/state")
        docs = [d for d in state.get("documents", []) if d.get("scene_id") == scene_id]
        target = next(
            (d for d in docs
             if d.get("id") == revision_id
             or str(d.get("revision_number")) == str(revision_id)
             or str(revision_id).lower().removeprefix("rev") == str(d.get("revision_number"))),
            None,
        )
        if target:
            resolved_revision_id = str(target.get("id"))
            if target.get("status") in ("adopted", "adopted_human"):
                msg = f"该版本（rev{target.get('revision_number')}）已是定稿（{_status_word(target.get('status'), medium='script')}），无需重复采纳。"
                if not json_output:
                    click.echo(ui.ok(msg), err=True)
                    return
                _emit({"ok": True, "already_adopted": True, "revision_id": target.get("id")}, json_output)
                return
            if target.get("status") == "superseded":
                click.echo(ui.warn("该版本已过期（superseded）——请用 scene list 查看最新候选，采纳最新版本。"), err=True) if not json_output else _emit({"ok": False, "superseded": True}, json_output)
                return
    except ScriptNowError:
        pass  # 前置检查失败不阻塞，交给平台权威校验
    extra_headers = {}
    if decision_token:
        extra_headers["X-Decision-Token"] = decision_token
    result = _session(ctx).request(
        "POST",
        f"/script/projects/{project_id}/scenes/{scene_id}/revisions/{resolved_revision_id}/adopt?human_decision={str(human_decision).lower()}",
        write=True,
        headers=extra_headers,
    )
    if not json_output:
        click.echo(ui.ok(_confirm_line("script", adopted=True)))
        return
    _emit(result, json_output)


_SCENE_BLOCKS_FORMAT = """剧本 blocks JSON 格式（scene-propose --file 要求）：
{
  "blocks": [
    {"para_id": "p1", "type": "slugline",   "text": "内景. 教室 - 清晨"},
    {"para_id": "p2", "type": "action",     "text": "林澈从课桌上醒来。"},
    {"para_id": "p3", "type": "character",  "text": "林澈"},
    {"para_id": "p4", "type": "dialogue",   "text": "今天又多了一条。"},
    {"para_id": "p5", "type": "transition", "text": "切至走廊"}
  ]
}
type 仅限：slugline（场景标题）| action（动作）| character（说话人）|
dialogue（对白）| transition（转场）。para_id 唯一即可。"""

_SCENE_EXAMPLE = """内景. 教室 - 清晨
林澈从课桌上醒来，黑板上的守则比昨天多了一条。

林澈
今天又多了一条。

林澈走到门口，门缝下塞进一张纸条，字迹与黑板相同。"""


@script_group.command("scene-propose")
@click.argument("project_id", required=False)
@click.argument("scene_id", required=False)
@click.option("--file", "blocks_file", default=None, help="blocks JSON 路径（@file 前缀表示文本文件），每项 {para_id,type,text}")
@click.option("--text", default=None, help="纯文本：首段作 slugline，其余按 action block 回传")
@click.option("--budget", type=int, default=None, help="token 预算上限（超限拒绝）")
@click.option("--auto-adopt", is_flag=True, help="回传后自动采纳该候选")
@click.option("--help-format", is_flag=True, help="显示 blocks JSON 格式说明")
@click.option("--example", is_flag=True, help="显示示例文本")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_scene_propose(
    ctx: click.Context,
    project_id: str,
    scene_id: str,
    blocks_file: str | None,
    text: str | None,
    budget: int | None,
    auto_adopt: bool,
    help_format: bool,
    example: bool,
    json_output: bool,
) -> None:
    if help_format:
        click.echo(_SCENE_BLOCKS_FORMAT)
        return
    if example:
        click.echo(_SCENE_EXAMPLE)
        return
    """Agent 本地创作场次 → 回传为候选（剧本改编不经过平台文本生成）。

    适用于改编场景：Agent 已用解读出的 skill 方法论（interpret local 产出）在本地
    写好了场次正文，这里只负责按标准格式回传为候选。block type 取剧本五种：
    slugline | action | character | dialogue | transition。
    """
    import json as _json

    if not blocks_file and not text:
        raise click.ClickException("需要 --file（blocks JSON）或 --text（纯文本）")
    script_types = ("slugline", "action", "character", "dialogue", "transition")
    if blocks_file:
        raw = Path(blocks_file[1:] if blocks_file.startswith("@") else blocks_file).read_text(
            encoding="utf-8"
        )
        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError as error:
            raise click.ClickException(f"blocks JSON 解析失败：{error}") from error
        blocks = data.get("blocks") if isinstance(data, dict) else data
        if not isinstance(blocks, list) or not blocks:
            raise click.ClickException("blocks 需要是至少 1 个 block 的数组")
        for block in blocks:
            if block.get("type") not in script_types:
                raise click.ClickException(
                    f"block type 必须是 {'|'.join(script_types)}，收到：{block.get('type')}"
                )
            if "para_id" not in block or "text" not in block:
                raise click.ClickException("每个 block 需要 para_id 和 text")
    else:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            raise click.ClickException("正文为空")
        blocks = []
        for idx, para in enumerate(paragraphs, 1):
            blocks.append(
                {
                    "para_id": f"p{idx}",
                    "type": "slugline" if idx == 1 else "action",
                    "text": para,
                }
            )
    _check_budget(blocks, budget, "场次正文", json_output)
    session = _session(ctx)
    body = {
        "idempotency_key": f"cli-scene-propose-{__import__('time').time_ns()}",
        "blocks": blocks,
        "source": "cli",
    }
    try:
        result = session.request(
            "POST",
            f"/script/projects/{project_id}/scenes/{scene_id}/propose",
            json_body=body,
            write=True,
        )
    except ScriptNowError as error:
        if "409" in str(error) or "缺少" in str(error):
            raise click.ClickException(
                str(error)
                + "\n提示：场次回传需要剧本 blocks 结构，推荐用 JSON 文件：\n"
                + "  scriptnow script scene-propose <pid> <scene_id> --file @blocks.json\n"
                + "  格式说明：scriptnow script scene-propose --help-format\n"
                + "  示例：scriptnow script scene-propose --example"
            ) from error
        raise
    if auto_adopt and result.get("id"):
        adopted = session.request(
            "POST",
            f"/script/projects/{project_id}/scenes/{scene_id}/revisions/{result['id']}/adopt",
            write=True,
        )
        result["adopted"] = adopted.get("status")
    if not json_output:
        adopted = result.get("status") in ("adopted", "adopted_human") or result.get("adopted")
        click.echo(ui.ok(_confirm_line("script", adopted=adopted)))
        click.echo(
            ui.dim(
                "下一步：采纳 scriptnow script adopt-scene <作品号> <场次号> <版本号>；"
                "审读 scriptnow script scene-show <作品号> <场次号>"
            ),
            err=True,
        )
        return
    _emit(result, json_output)


def _poll_run_status(session: Session, project_id: str, run_id: str, *, domain: str = "novel") -> str:
    """Poll a run to a terminal status without emitting (batch use)."""
    import time as _time

    path = f"/{domain}/projects/{project_id}/runs/{run_id}"
    deadline = _time.time() + 16 * 60
    while _time.time() < deadline:
        state = session.request("GET", path)
        status = str(state.get("status") or "")
        if status in ("succeeded", "failed", "cancelled"):
            return status
        _time.sleep(2)
    return "timeout"


@script_group.command("scene-batch")
@click.argument("project_id")
@click.option("--scenes", default=None, help="逗号分隔的场次 id（与 --resume-from 二选一）")
@click.option("--feedback", default=None, help="统一创作/修订反馈")
@click.option("--model", "model_id", default=None, help="批量场次写作统一使用的模型 id（仅项目写作，禁止用于非项目文本生成）")
@click.option("--save-progress", "progress_file", default=None, help="完成后保存失败清单（续跑用）")
@click.option("--resume-from", "resume_file", default=None, help="从上次失败清单续跑（JSON 文件，含 failed 列表）")
@click.option("--yes", is_flag=True, help="确认已知风险后跳过警告")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_scene_batch(
    ctx: click.Context,
    project_id: str,
    scenes: str | None,
    feedback: str | None,
    model_id: str | None,
    progress_file: str | None,
    resume_file: str | None,
    yes: bool,
    json_output: bool,
) -> None:
    """批量生成场次（串行）：实时进度 + 失败集中汇总 + 断点续跑。

    ⚠ 谨慎使用：批量生成可能造成情节/设定不一致或伏笔失误。
    最佳实践是逐场创作 + 审读 + 采纳（scene generate → scene-show → adopt-scene）。
    中断恢复：首次 --save-progress 保存失败清单，之后 --resume-from 续跑。
    """
    import json as _json
    import time as _time

    if resume_file:
        try:
            prior = _json.loads(Path(resume_file).read_text(encoding="utf-8"))
            ids = [str(item) for item in (prior.get("failed") or [])]
        except (ValueError, OSError) as error:
            raise click.ClickException(f"读取进度文件失败：{error}")
    else:
        ids = [item.strip() for item in (scenes or "").split(",") if item.strip()]
    if not ids:
        raise click.ClickException("需要 --scenes 或 --resume-from（失败清单非空）")
    if not json_output:
        click.echo(ui.warn("批量生成注意事项（请确认已了解风险，--yes 跳过本提示）："), err=True)
        click.echo(ui.dim("  1. 批量生成可能产生情节/设定不一致、伏笔失误，务必逐场审读后再采纳；"), err=True)
        click.echo(ui.dim("  2. 最佳实践是逐场创作完善：scene generate → scene-show 审读 → adopt-scene；"), err=True)
        click.echo(ui.dim("  3. Agent 请勿用 subagent 并发批量——上下文割裂会造成设定漂移。"), err=True)
        if not yes:
            click.echo(ui.dim("（使用 --yes 确认后开始）"), err=True)
    session = _session(ctx)
    summary: list[dict[str, object]] = []
    for index, scene_id in enumerate(ids, 1):
        started = _time.time()
        try:
            queued = session.request(
                "POST",
                f"/script/projects/{project_id}/scenes/{scene_id}/generate?background=true",
                json_body={
                    "idempotency_key": f"cli-scene-{_time.time_ns()}",
                    "feedback": feedback,
                    **({"model_id": model_id} if model_id else {}),
                },
                write=True,
            )
            run_id = str(queued.get("run_id") or "")
            status = _poll_run_status(session, project_id, run_id, domain="script")
            elapsed = int(_time.time() - started)
            summary.append({"scene_id": scene_id, "status": status, "seconds": elapsed})
            if not json_output:
                mark = ui.ok("✓") if status == "succeeded" else ui.error("✗")
                click.echo(f"[{index}/{len(ids)}] {mark} {scene_id} {status} ({elapsed}s)", err=True)
        except ScriptNowError as error:
            summary.append({"scene_id": scene_id, "status": "error", "detail": str(error)})
            if not json_output:
                click.echo(ui.error(f"[{index}/{len(ids)}] {scene_id} error: {error}"), err=True)
    failed = [item for item in summary if item.get("status") != "succeeded"]
    if progress_file and failed:
        Path(progress_file).write_text(
            _json.dumps({"failed": [str(item["scene_id"]) for item in failed]}, ensure_ascii=False),
            encoding="utf-8",
        )
        if not json_output:
            click.echo(ui.dim(f"失败清单已保存：{progress_file}（续跑：--resume-from {progress_file}）"), err=True)
    if not json_output:
        if failed:
            click.echo(ui.error(f"未完成 {len(failed)}/{len(ids)} 场：{', '.join(str(i['scene_id']) for i in failed)}——可续跑：--resume-from {progress_file or '<失败清单>'}"), err=True)
        else:
            click.echo(ui.ok(f"全部完成：{len(ids)} 个场次 ✅ —— 下一步逐场 scene show 审读，满意后 scene adopt 定稿。"))
        return
    _emit({"total": len(ids), "succeeded": len(ids) - len(failed), "failed": failed, "results": summary}, json_output)


@script_group.command("scene-quality")
@click.argument("project_id")
@click.argument("scene_id")
@click.option("--revision", default=None, help="指定修订号/id（默认最新候选，无则已采纳）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_scene_quality(
    ctx: click.Context, project_id: str, scene_id: str, revision: str | None, json_output: bool
) -> None:
    """场次质量快检（客户端统计，不消耗模型）：篇幅 / 对白轮数 / 镜头语言。"""
    state = _session(ctx).request("GET", f"/script/projects/{project_id}/state")
    docs = [doc for doc in (state.get("documents") or []) if doc.get("scene_id") == scene_id]
    if not docs:
        raise click.ClickException(f"no documents for scene {scene_id}")
    chosen = None
    if revision:
        chosen = next(
            (d for d in docs if d.get("id") == revision or str(d.get("revision_number")) == revision),
            None,
        )
        if chosen is None:
            raise click.ClickException(f"revision {revision} not found for scene {scene_id}")
    else:
        candidates = sorted(
            [d for d in docs if d.get("status") in ("candidate", "active")],
            key=lambda d: d.get("revision_number", 0),
            reverse=True,
        )
        chosen = candidates[0] if candidates else max(docs, key=lambda d: d.get("revision_number", 0))
    blocks = chosen.get("blocks") or []
    total_chars = sum(len(str(b.get("text") or "")) for b in blocks)
    sluglines = [b for b in blocks if b.get("type") == "slugline"]
    dialogues = [b for b in blocks if b.get("type") == "dialogue"]
    characters = [b for b in blocks if b.get("type") == "character"]
    transitions = [b for b in blocks if b.get("type") == "transition"]
    dialogue_rounds = min(len(characters), len(dialogues)) if (characters and dialogues) else len(dialogues)
    checks: list[dict[str, object]] = []
    checks.append({
        "check": "篇幅",
        "value": f"{total_chars} 字符",
        "target": "400-700",
        "ok": 400 <= total_chars <= 700,
        "flag": "过短" if total_chars < 250 else ("偏短" if total_chars < 400 else ("偏长" if total_chars > 700 else "达标")),
    })
    checks.append({
        "check": "对白",
        "value": f"{dialogue_rounds} 轮",
        "target": "≥2",
        "ok": dialogue_rounds >= 2,
        "flag": "不足" if dialogue_rounds < 2 else "达标",
    })
    checks.append({
        "check": "镜头语言",
        "value": f"{len(sluglines)} slugline / {len(transitions)} transition",
        "target": "≥1 slugline",
        "ok": bool(sluglines),
        "flag": "缺场景标题" if not sluglines else "达标",
    })
    if not json_output:
        source_label = "平台生成" if chosen.get("source") == "platform" else "共创回填"
        click.echo(ui.section(f"=== 本场（第 {chosen.get('revision_number', 1)} 版 · {source_label}）==="), err=True)
        for item in checks:
            mark = ui.ok("") if item["ok"] else ui.warn("")
            click.echo(f"  {mark} {item['check']}：{item['value']}（目标 {item['target']}）{item['flag']}", err=True)
        passed = sum(1 for item in checks if item["ok"])
        overall = "整体达标" if passed == len(checks) else ("还需打磨" if passed >= 1 else "不达标")
        click.echo(ui.dim(f"综合评价：{overall}（{passed}/{len(checks)} 项通过）"), err=True)
        click.echo(ui.dim(_next_step_after_generate("script")), err=True)
        return
    _emit(
        {
            "scene_id": scene_id,
            "revision_number": chosen.get("revision_number"),
            "revision_id": chosen.get("id"),
            "source": chosen.get("source"),
            "total_chars": total_chars,
            "blocks": len(blocks),
            "dialogue_rounds": dialogue_rounds,
            "checks": checks,
        },
        json_output,
    )




def _default_project_file() -> Path:

    if os.environ.get("SCRIPTNOW_CLI_CONFIG"):
        return Path(os.environ["SCRIPTNOW_CLI_CONFIG"]).with_name("project.json")
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "scriptnow-cli" / "project.json"


def _resolve_project_id(ctx: click.Context, project_id: str | None) -> str:
    """Resolve an optional project id from the CLI default (project use)."""
    if project_id:
        return project_id
    path = _default_project_file()
    if path.exists():
        import json as _json

        try:
            value = str(_json.loads(path.read_text(encoding="utf-8")).get("project_id") or "")
            if value:
                return value
        except (ValueError, OSError):
            pass
    raise click.ClickException("请提供 project_id，或先用 scriptnow project use <pid> 设定默认项目")


@project_group.command("use")
@click.argument("project_id")
@click.pass_context
def project_use(ctx: click.Context, project_id: str) -> None:
    """将项目设为默认，后续新命令（scene-diff / quality-report 等）可省略 project_id。"""
    path = _default_project_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    import json as _json

    path.write_text(_json.dumps({"project_id": project_id}, ensure_ascii=False), encoding="utf-8")
    click.echo(ui.ok("默认作品已设置 —— 后续命令可省略作品号。"))


@script_group.command("quality-report")
@click.argument("project_id", required=False)
@click.option("--format", "fmt", type=click.Choice(["console", "markdown"]), default="console")
@click.option("--out", default=None, help="写入报告文件（markdown 时）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_quality_report(
    ctx: click.Context, project_id: str | None, fmt: str, out: str | None, json_output: bool
) -> None:
    """全项目场次质量分布：达标 / 过短 / 对白不足 / 缺标题（客户端统计，零模型消耗）。"""
    pid = _resolve_project_id(ctx, project_id)
    state = _session(ctx).request("GET", f"/script/projects/{pid}/state")
    documents = state.get("documents") or []
    latest: dict[str, dict[str, object]] = {}
    for doc in documents:
        sid = str(doc.get("scene_id") or "")
        if not sid:
            continue
        current = latest.get(sid)
        if current is None or doc.get("revision_number", 0) >= current.get("revision_number", 0):
            latest[sid] = doc
    rows: list[dict[str, object]] = []
    for sid, doc in sorted(latest.items()):
        blocks = doc.get("blocks") or []
        chars = sum(len(str(b.get("text") or "")) for b in blocks)
        dialogues = [b for b in blocks if b.get("type") == "dialogue"]
        characters = [b for b in blocks if b.get("type") == "character"]
        sluglines = [b for b in blocks if b.get("type") == "slugline"]
        rounds = min(len(characters), len(dialogues)) if (characters and dialogues) else len(dialogues)
        flags = []
        if chars < 250:
            flags.append("严重过短")
        elif chars < 400:
            flags.append("偏短")
        if rounds < 2:
            flags.append("对白不足")
        if not sluglines:
            flags.append("缺标题")
        rows.append({
            "scene_id": sid,
            "revision": doc.get("revision_number"),
            "status": doc.get("status"),
            "chars": chars,
            "rounds": rounds,
            "flags": flags,
        })
    total = len(rows)
    ok = sum(1 for r in rows if not r["flags"])
    short = [r for r in rows if any(f in ("严重过短", "偏短") for f in r["flags"])]
    dialogue_low = [r for r in rows if "对白不足" in r["flags"]]
    no_title = [r for r in rows if "缺标题" in r["flags"]]
    summary = {
        "total": total,
        "good": ok,
        "short": [r["scene_id"] for r in short],
        "dialogue_low": [r["scene_id"] for r in dialogue_low],
        "no_title": [r["scene_id"] for r in no_title],
    }
    if json_output:
        _emit({"summary": summary, "scenes": rows}, json_output)
        return
    if fmt == "markdown":
        lines = [
            "## 场次质量报告",
            "",
            f"- 总场次：{total}",
            f"- 达标：{ok}（{round(100 * ok / max(total, 1))}%）",
            f"- 过短：{len(short)}（<400 字符）",
            f"- 对白不足：{len(dialogue_low)}（<2 轮）",
            f"- 缺标题：{len(no_title)}",
            "",
            "| 场次 | rev | 字符 | 对白轮 | 问题 |",
            "|---|---|---|---|---|",
        ]
        for r in sorted(rows, key=lambda x: x["chars"]):
            lines.append(f"| {r['scene_id']} | {r['revision']} | {r['chars']} | {r['rounds']} | {'、'.join(r['flags']) or '—'} |")
        report = "\n".join(lines)
        if out:
            Path(out).write_text(report, encoding="utf-8")
            click.echo(ui.ok(f"报告已写入 {out}"))
        else:
            click.echo(report)
        return
    click.echo(ui.section(f"=== 场次质量报告（{total} 场）==="), err=True)
    click.echo(
        f"  {ui.ok('')} 达标 {ok}  过短 {len(short)}  对白不足 {len(dialogue_low)}  缺标题 {len(no_title)}",
        err=True,
    )
    for r in sorted(rows, key=lambda x: x["chars"]):
        mark = ui.ok("") if not r["flags"] else ui.warn("")
        click.echo(
            f"  {mark} {r['scene_id']} 第{r['revision']}版 {r['chars']}字 {r['rounds']}轮"
            + (f"  ⚠ {'、'.join(r['flags'])}" if r["flags"] else ""),
            err=True,
        )


@script_group.command("scene-diff")
@click.argument("scene_id")
@click.option("--project", "project_id", default=None, help="项目 id（默认取 project use 设定的项目）")
@click.option("--from", "from_rev", required=True, help="起始修订号/id")
@click.option("--to", "to_rev", required=True, help="目标修订号/id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_scene_diff(
    ctx: click.Context,
    scene_id: str,
    project_id: str | None,
    from_rev: str,
    to_rev: str,
    json_output: bool,
) -> None:
    """对比场次两个修订：字符/块/对白/镜头变化概览（客户端，零模型）。"""
    pid = _resolve_project_id(ctx, project_id)
    state = _session(ctx).request("GET", f"/script/projects/{pid}/state")
    docs = [d for d in (state.get("documents") or []) if d.get("scene_id") == scene_id]
    if not docs:
        raise click.ClickException(f"no documents for scene {scene_id}")
    def pick(ref: str) -> dict[str, object]:
        found = next(
            (d for d in docs if d.get("id") == ref or str(d.get("revision_number")) == ref), None
        )
        if found is None:
            raise click.ClickException(f"revision {ref} not found for scene {scene_id}")
        return found
    before = pick(from_rev)
    after = pick(to_rev)
    def stats(doc: dict[str, object]) -> dict[str, object]:
        blocks = doc.get("blocks") or []
        return {
            "chars": sum(len(str(b.get("text") or "")) for b in blocks),
            "blocks": len(blocks),
            "dialogues": sum(1 for b in blocks if b.get("type") == "dialogue"),
            "characters": sum(1 for b in blocks if b.get("type") == "character"),
            "sluglines": sum(1 for b in blocks if b.get("type") == "slugline"),
            "transitions": sum(1 for b in blocks if b.get("type") == "transition"),
        }
    a, b = stats(before), stats(after)
    delta = {
        "chars": b["chars"] - a["chars"],
        "chars_pct": round(100 * (b["chars"] - a["chars"]) / max(a["chars"], 1)),
        "blocks": b["blocks"] - a["blocks"],
        "dialogue_rounds": min(b["characters"], b["dialogues"]) - min(a["characters"], a["dialogues"]),
        "sluglines": b["sluglines"] - a["sluglines"],
        "transitions": b["transitions"] - a["transitions"],
    }
    if json_output:
        _emit(
            {"scene_id": scene_id, "from": {"revision": before.get("revision_number"), **a},
             "to": {"revision": after.get("revision_number"), **b}, "delta": delta},
            json_output,
        )
        return
    click.echo(ui.section(f"=== 本场修订对比：第 {before.get('revision_number')} 版 → 第 {after.get('revision_number')} 版 ==="), err=True)
    click.echo(f"  字数：{a['chars']} → {b['chars']}（{'+' if delta['chars'] >= 0 else ''}{delta['chars']}，{'+' if delta['chars_pct'] >= 0 else ''}{delta['chars_pct']}%）", err=True)
    click.echo(f"  内容块：{a['blocks']} → {b['blocks']}（{'+' if delta['blocks'] >= 0 else ''}{delta['blocks']}）", err=True)
    click.echo(f"  对白轮：{min(a['characters'], a['dialogues'])} → {min(b['characters'], b['dialogues'])}（{'+' if delta['dialogue_rounds'] >= 0 else ''}{delta['dialogue_rounds']}）", err=True)
    click.echo(f"  场景标题：{a['sluglines']} → {b['sluglines']} | 转场：{a['transitions']} → {b['transitions']}", err=True)


# ----------------------------------------------------------------- translation


@main.group("translate")
@click.pass_context
def translate_group(ctx: click.Context) -> None:
    """故事归化（翻译改编）：目标市场契约 / 源分析 / 策略 / 映射。"""


@translate_group.command("create")
@click.option("--project-id", required=True)
@click.option("--source-language", required=True)
@click.option("--target-language", required=True)
@click.option("--target-market", required=True)
@click.option("--target-audience", required=True)
@click.option("--distribution-context", default="")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def translate_create(
    ctx: click.Context,
    project_id: str,
    source_language: str,
    target_language: str,
    target_market: str,
    target_audience: str,
    distribution_context: str,
    json_output: bool,
) -> None:
    """Create a cross-cultural recreation for a project."""
    body = {
        "project_id": project_id,
        "source_language": source_language,
        "target_language": target_language,
        "target_market": target_market,
        "target_audience": target_audience,
        "distribution_context": distribution_context,
    }
    _emit(
        _session(ctx).request(
            "POST", "/cross-cultural-recreations", json_body=body, write=True
        ),
        json_output,
    )


@translate_group.command("analyze-source")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def translate_analyze_source(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """Analyze the source work for recreation (blocks until done)."""
    result = _session(ctx).request(
        "POST", f"/cross-cultural-recreations/by-project/{project_id}/analyze-source", write=True, timeout=900
    )
    _emit(result, json_output)


@translate_group.command("target-contract")
@click.argument("project_id")
@click.option("--genre-promise", required=True)
@click.option("--background-policy", required=True)
@click.option("--cultural-distance", required=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def translate_target_contract(
    ctx: click.Context,
    project_id: str,
    genre_promise: str,
    background_policy: str,
    cultural_distance: str,
    json_output: bool,
) -> None:
    """Set the target-market contract for a recreation."""
    body = {
        "genre_promise": genre_promise,
        "background_policy": background_policy,
        "cultural_distance": cultural_distance,
    }
    _emit(
        _session(ctx).request(
            "POST",
            f"/cross-cultural-recreations/by-project/{project_id}/target-contract",
            json_body=body,
            write=True,
        ),
        json_output,
    )


@translate_group.command("strategies")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def translate_strategies(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """Generate recreation strategies (blocks until done)."""
    result = _session(ctx).request(
        "POST", f"/cross-cultural-recreations/by-project/{project_id}/strategies", write=True, timeout=900
    )
    _emit(result, json_output)


@translate_group.command("mappings")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def translate_mappings(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """Confirm cultural mappings (blocks until done)."""
    result = _session(ctx).request(
        "POST", f"/cross-cultural-recreations/by-project/{project_id}/cultural-mappings", write=True, timeout=900
    )
    _emit(result, json_output)


# -------------------------------------------------------------------- storyboard

_STORYBOARD_FORMAT = """Storyboard ScriptOut JSON（顶层对象）
必填：title, scenes[]；可选：logline, assets[]。
assets[]: {kind: character|scene|prop, name, description, aliases[]}。
scenes[]: {title, location, time_of_day, description, characters[], narrative_purpose, shots[]}。
shots[]: {shot_no, shot_size, camera_angle, camera_move, visual_description,
          dialogue:[{speaker,text}], sound, duration_ms}。
只提交分镜事实，不提交 Skill 手册、安装命令或解释性正文。字幕/音乐/音效遵从 storyboard state 中的项目策略。"""

_STORYBOARD_EXAMPLE = """{
  "title": "示例分镜",
  "assets": [{"kind":"character","name":"刘大宝","description":"项目角色身份","aliases":[]}],
  "scenes": [{
    "title":"购买洗衣机","location":"潘家园二手市场","time_of_day":"日",
    "description":"刘大宝查看旧洗衣机","characters":["刘大宝"],"narrative_purpose":"建立人物处境",
    "shots":[{
      "shot_no":"1","shot_size":"CU","camera_angle":"平视","camera_move":"缓推",
      "visual_description":"@刘大宝 查看洗衣机正面掉漆处",
      "dialogue":[],"sound":"市场环境声、手指擦过金属声","duration_ms":4000
    }]
  }]
}"""


@main.group("storyboard")
@click.pass_context
def storyboard_group(ctx: click.Context) -> None:
    """分镜回填工作流：读取事实、本地创作、候选回填、人工采纳与导出。"""


def _storyboard_json(value: str) -> dict[str, Any]:
    raw = Path(value[1:] if value.startswith("@") else value).read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise click.ClickException(f"分镜 JSON 无法解析：{error}") from error
    if not isinstance(payload, dict):
        raise click.ClickException("分镜 JSON 顶层必须是对象")
    return payload


def _storyboard_source_text(path: Path) -> str:
    if path.suffix.lower() in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".docx":
        import zipfile
        from xml.etree import ElementTree

        try:
            with zipfile.ZipFile(path) as archive:
                root = ElementTree.fromstring(archive.read("word/document.xml"))
        except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
            raise click.ClickException(f"DOCX 正文无法提取：{error}") from error
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(f"{namespace}p"):
            text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
            if text.strip():
                paragraphs.append(text.strip())
        return "\n\n".join(paragraphs)
    raise click.ClickException("source-import 仅支持 TXT、Markdown 与 DOCX")


def _storyboard_source_units(text: str) -> list[int]:
    import re as _re

    return [int(value) for value in _re.findall(r"(?m)^第\s*(\d+)\s*[章集]", text)]


def _storyboard_slice_units(text: str, start: int | None, end: int | None) -> str:
    if start is None and end is None:
        return text
    if start is None or end is None or end < start:
        raise click.ClickException("切分范围必须同时提供，且结束值不能小于起始值")
    import re as _re

    matches = list(_re.finditer(r"(?m)^第\s*(\d+)\s*[章集].*$", text))
    selected = []
    for index, match in enumerate(matches):
        unit = int(match.group(1))
        if start <= unit <= end:
            boundary = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            selected.append(text[match.start():boundary].strip())
    if not selected:
        raise click.ClickException(f"正文中未找到第 {start}–{end} 章/集")
    return "\n\n".join(selected)


@storyboard_group.group("scene-board")
@click.pass_context
def storyboard_scene_board_group(ctx: click.Context) -> None:
    """场次规划板：上传、单场生成、查看与删除；不改镜头帧。"""


def _scene_board_state(state: dict[str, Any], scene_id: str | None = None) -> Any:
    scenes = state.get("scenes") or []
    shots_by_scene: dict[str, list[str]] = {}
    for shot in state.get("shots") or []:
        shots_by_scene.setdefault(str(shot.get("scene_id")), []).append(str(shot.get("id")))

    def scene_payload(scene: dict[str, Any]) -> dict[str, Any]:
        current_shots = shots_by_scene.get(str(scene.get("id")), [])
        boards = []
        for board in scene.get("planning_boards") or []:
            item = dict(board)
            item["layout_key"] = item.get("layout_key") or "auto"
            item["board_mode"] = item.get("board_mode") or "annotated"
            item["stale"] = list(item.get("shot_ids") or []) != current_shots
            boards.append(item)
        return {
            "scene_id": scene.get("id"),
            "scene_no": scene.get("scene_no"),
            "title": scene.get("title"),
            "shot_count": len(current_shots),
            "planning_boards": boards,
        }

    if scene_id is None:
        return [scene_payload(scene) for scene in scenes]
    scene = next((item for item in scenes if str(item.get("id")) == scene_id), None)
    if scene is None:
        raise click.ClickException(f"找不到场次：{scene_id}")
    return scene_payload(scene)


@storyboard_scene_board_group.command("upload")
@click.argument("project_id")
@click.argument("scene_id")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--layout", "layout_key", type=click.Choice(["auto", "2x2", "2x3", "3x3", "3x4", "4x4"]), default="auto", show_default=True, help="规划板网格布局")
@click.option("--mode", "board_mode", type=click.Choice(["annotated", "seedance_sequence"]), default="annotated", show_default=True, help="视觉代理模式")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_scene_board_upload(
    ctx: click.Context, project_id: str, scene_id: str, file_path: str,
    layout_key: str, board_mode: str, json_output: bool,
) -> None:
    """上传本地 PNG/JPEG/WebP 规划板；布局与 shot_ids 由平台派生。"""
    path = Path(file_path)
    session = _session(ctx)
    with path.open("rb") as handle:
        result = session.request(
            "POST",
            f"/storyboard/projects/{project_id}/scenes/{scene_id}/planning-boards",
            files={"file": (path.name, handle, "application/octet-stream")},
            form_data={"layout_key": layout_key, "board_mode": board_mode},
            write=True,
            command="storyboard scene-board upload",
        )
    _emit(result, json_output)


@storyboard_scene_board_group.command("generate")
@click.argument("project_id")
@click.argument("scene_id")
@click.option("--layout", "layout_key", type=click.Choice(["auto", "2x2", "2x3", "3x3", "3x4", "4x4"]), default="auto", show_default=True, help="规划板网格布局")
@click.option("--mode", "board_mode", type=click.Choice(["annotated", "seedance_sequence"]), default="annotated", show_default=True, help="视觉代理模式")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_scene_board_generate(
    ctx: click.Context, project_id: str, scene_id: str, layout_key: str, board_mode: str, json_output: bool
) -> None:
    """显式生成单场规划板；不会批量调用，也不会写 shot.frame_refs。"""
    result = _session(ctx).request(
        "POST",
        f"/storyboard/projects/{project_id}/scenes/{scene_id}/planning-boards/generate",
        json_body={"layout_key": layout_key, "board_mode": board_mode},
        write=True,
        timeout=900,
        command="storyboard scene-board generate",
    )
    _emit(result, json_output)


@storyboard_scene_board_group.command("delete")
@click.argument("project_id")
@click.argument("scene_id")
@click.argument("board_id")
@click.option("--confirm", is_flag=True, help="确认删除该场次的规划板记录与本地文件")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_scene_board_delete(
    ctx: click.Context,
    project_id: str,
    scene_id: str,
    board_id: str,
    confirm: bool,
    json_output: bool,
) -> None:
    """删除指定规划板；必须显式确认，镜头帧不受影响。"""
    if not confirm:
        raise click.ClickException("删除规划板需要 --confirm")
    result = _session(ctx).request(
        "DELETE",
        f"/storyboard/projects/{project_id}/scenes/{scene_id}/planning-boards/{board_id}",
        write=True,
        command="storyboard scene-board delete",
    )
    _emit({"deleted": board_id, "result": result}, json_output)


@storyboard_scene_board_group.command("list")
@click.argument("project_id")
@click.option("--scene", "scene_id", default=None, help="只查看一个场次")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_scene_board_list(
    ctx: click.Context, project_id: str, scene_id: str | None, json_output: bool
) -> None:
    """查看平台事实中的场次规划板清单与派生布局。"""
    state = _session(ctx).request(
        "GET", f"/storyboard/projects/{project_id}/state", command="storyboard scene-board list"
    )
    _emit(_scene_board_state(state, scene_id), json_output)


@storyboard_scene_board_group.command("inspect")
@click.argument("project_id")
@click.argument("scene_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_scene_board_inspect(
    ctx: click.Context, project_id: str, scene_id: str, json_output: bool
) -> None:
    """查看一个场次的规划板完整 manifest、来源与 lineage。"""
    state = _session(ctx).request(
        "GET", f"/storyboard/projects/{project_id}/state", command="storyboard scene-board inspect"
    )
    _emit(_scene_board_state(state, scene_id), json_output)


@storyboard_group.command("state")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_state(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """读取平台分镜事实，供 Agent 在本地规划与续写。"""
    _emit(_session(ctx).request("GET", f"/storyboard/projects/{project_id}/state"), json_output)


@storyboard_group.command("source-import")
@click.argument("project_id")
@click.argument("file_path")
@click.option("--source-kind", type=click.Choice(["novel", "script", "upload"]), default="upload")
@click.option("--name", default=None, help="来源名称；默认使用文件名")
@click.option("--append", is_flag=True, help="作为下一制作批次追加，不覆盖既有批次")
@click.option("--episode-start", type=click.IntRange(min=1), default=None)
@click.option("--episode-end", type=click.IntRange(min=1), default=None)
@click.option("--slice-unit-start", type=click.IntRange(min=1), default=None, help="只提取 DOCX/TXT 中指定起始章/集")
@click.option("--slice-unit-end", type=click.IntRange(min=1), default=None, help="只提取 DOCX/TXT 中指定结束章/集")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_source_import(ctx: click.Context, project_id: str, file_path: str, source_kind: str, name: str | None, append: bool, episode_start: int | None, episode_end: int | None, slice_unit_start: int | None, slice_unit_end: int | None, json_output: bool) -> None:
    """登记本地小说/剧本文本来源；不调用平台 Agent。"""
    path = Path(file_path[1:] if file_path.startswith("@") else file_path)
    if episode_start is not None and episode_end is not None and episode_end < episode_start:
        raise click.ClickException("--episode-end 不能小于 --episode-start")
    source_text = _storyboard_slice_units(
        _storyboard_source_text(path), slice_unit_start, slice_unit_end
    )
    if append and (episode_start is None or episode_end is None):
        raise click.ClickException("追加批次必须明确提供 --episode-start 与 --episode-end")
    if (episode_start is None) != (episode_end is None):
        raise click.ClickException("集数范围必须同时提供 --episode-start 与 --episode-end")
    if episode_start is not None and episode_end is not None:
        units = _storyboard_source_units(source_text)
        expected_units = set(range(episode_start, episode_end + 1))
        outside = [unit for unit in units if unit < episode_start or unit > episode_end]
        missing = sorted(expected_units - set(units))
        if not units:
            raise click.ClickException("追加正文未识别到『第 N 章/集』边界，不能确认范围")
        if outside:
            raise click.ClickException(
                f"正文仍包含范围外章/集 {outside}；请用 --slice-unit-start/--slice-unit-end 精确切分"
            )
        if missing:
            raise click.ClickException(f"正文缺少请求范围内章/集 {missing}，不能标记为完整批次")
    result = _session(ctx).request(
        "POST", f"/storyboard/projects/{project_id}/import",
        json_body={"source_kind": source_kind, "source_name": name or path.name, "source_text": source_text, "import_mode": "append" if append else "initial", "episode_start": episode_start, "episode_end": episode_end},
        write=True,
    )
    _emit(result, json_output)


@storyboard_group.command("source-preflight")
@click.argument("project_id")
@click.argument("file_path")
@click.option("--episode-start", type=click.IntRange(min=1), required=True)
@click.option("--episode-end", type=click.IntRange(min=1), required=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_source_preflight(ctx: click.Context, project_id: str, file_path: str, episode_start: int, episode_end: int, json_output: bool) -> None:
    """只读检查文档边界、未知批次和集数重叠；不写平台。"""
    if episode_end < episode_start:
        raise click.ClickException("--episode-end 不能小于 --episode-start")
    path = Path(file_path[1:] if file_path.startswith("@") else file_path)
    text = _storyboard_source_text(path)
    units = _storyboard_source_units(text)
    state = _session(ctx).request("GET", f"/storyboard/projects/{project_id}/state")
    active = [item for item in state.get("source_batches", []) if item.get("parse_status") != "revoked"]
    unknown = [item["batch_no"] for item in active if item.get("episode_start") is None or item.get("episode_end") is None]
    overlaps = [item["batch_no"] for item in active if item.get("episode_start") is not None and episode_start <= item["episode_end"] and episode_end >= item["episode_start"]]
    reasons = []
    if unknown:
        reasons.append(f"有效批次 {unknown} 未登记集数范围")
    if overlaps:
        reasons.append(f"请求范围与有效批次 {overlaps} 重叠")
    if not units:
        reasons.append("文档未识别到『第 N 章/集』边界")
    outside = [unit for unit in units if unit < episode_start or unit > episode_end]
    missing = sorted(set(range(episode_start, episode_end + 1)) - set(units))
    if outside:
        reasons.append(f"文档包含请求范围外章/集 {outside}，必须先精确切分")
    if missing:
        reasons.append(f"文档缺少请求范围内章/集 {missing}")
    payload = {
        "pass": not reasons,
        "document_units": units,
        "requested_range": [episode_start, episode_end],
        "unknown_range_batches": unknown,
        "overlap_batches": overlaps,
        "outside_requested_units": outside,
        "missing_requested_units": missing,
        "reasons": reasons,
        "suggested_non_overlapping_start": max([item.get("episode_end") or 0 for item in active], default=0) + 1,
    }
    _emit(payload, json_output)
    if reasons and not json_output:
        raise click.ClickException("；".join(reasons))


@storyboard_group.command("source-range")
@click.argument("project_id")
@click.argument("source_id")
@click.option("--episode-start", type=click.IntRange(min=1), required=True)
@click.option("--episode-end", type=click.IntRange(min=1), required=True)
@click.option("--reason", required=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_source_range(ctx: click.Context, project_id: str, source_id: str, episode_start: int, episode_end: int, reason: str, json_output: bool) -> None:
    result = _session(ctx).request("PUT", f"/storyboard/projects/{project_id}/sources/{source_id}/range", json_body={"episode_start": episode_start, "episode_end": episode_end, "reason": reason}, write=True)
    state = _session(ctx).request("GET", f"/storyboard/projects/{project_id}/state")
    _emit({"result": result, "source_batches": state.get("source_batches", [])}, json_output)


@storyboard_group.command("source-revoke")
@click.argument("project_id")
@click.argument("source_id")
@click.option("--reason", required=True)
@click.option("--confirm", is_flag=True, help="确认撤销最新且未消费的追加批次")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_source_revoke(ctx: click.Context, project_id: str, source_id: str, reason: str, confirm: bool, json_output: bool) -> None:
    if not confirm:
        raise click.ClickException("撤销来源批次需要 --confirm")
    session = _session(ctx)
    result = session.request("POST", f"/storyboard/projects/{project_id}/sources/{source_id}/revoke", json_body={"reason": reason}, write=True)
    state = session.request("GET", f"/storyboard/projects/{project_id}/state")
    _emit({"result": result, "current_source": state.get("source"), "source_batches": state.get("source_batches", []), "scene_count": len(state.get("scenes", [])), "shot_count": len(state.get("shots", []))}, json_output)


@storyboard_group.command("propose")
@click.argument("project_id", required=False)
@click.argument("file_path", required=False)
@click.option("--source-id", default=None, help="source-import 返回的来源 ID")
@click.option("--adopt", is_flag=True, help="仅在用户明确采用后提交人工采纳")
@click.option("--help-format", is_flag=True, help="按需显示精简 ScriptOut 字段契约")
@click.option("--example", is_flag=True, help="按需显示最小分镜示例")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_propose(ctx: click.Context, project_id: str | None, file_path: str | None, source_id: str | None, adopt: bool, help_format: bool, example: bool, json_output: bool) -> None:
    """回填 Agent 在本地完成的 ScriptOut 分镜候选；平台只校验和版本化。"""
    if help_format:
        click.echo(_STORYBOARD_FORMAT)
        return
    if example:
        click.echo(_STORYBOARD_EXAMPLE)
        return
    if not project_id or not file_path or not source_id:
        raise click.ClickException("需要 PROJECT_ID、FILE_PATH 与 --source-id；格式见 storyboard propose --help-format")
    payload = _storyboard_json(file_path)
    script = payload.get("script") if isinstance(payload.get("script"), dict) else payload
    import hashlib as _hashlib

    proposal_identity = _hashlib.sha256(
        json.dumps(
            {"project_id": project_id, "source_id": source_id, "script": script},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:40]
    session = _session(ctx)
    contract = session.request(
        "GET", f"/storyboard/projects/{project_id}/proposal-contract"
    )
    run = session.request(
        "POST", f"/storyboard/projects/{project_id}/propose",
        json_body={"source_id": source_id, "script": script, "skill_snapshots": contract["skill_snapshots"], "idempotency_key": f"cli-storyboard-propose-{proposal_identity}"},
        write=True,
    )
    result: dict[str, Any] = {"strategy_run": run, "adopted": False}
    if adopt:
        existing = next(
            (
                item for item in reversed(run.get("decisions", []))
                if item.get("decision") in {"adopted", "modified"}
            ),
            None,
        )
        decision = existing or session.request(
            "POST", f"/storyboard/projects/{project_id}/strategy-runs/{run['id']}/decisions",
            json_body={"decision": "adopted", "selected_candidate_key": "agent-proposal", "modification": {}, "reason": "用户明确采用 Agent 本地分镜候选", "final_payload": {}}, write=True,
        )
        result.update({"adopted": True, "decision": decision})
    _emit(result, json_output)


@storyboard_group.command("assets")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_assets(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """读取项目资产身份、版本、参考图和镜头绑定。"""
    _emit(_session(ctx).request("GET", f"/storyboard/projects/{project_id}/asset-hub"), json_output)


@storyboard_group.command("asset-add")
@click.argument("project_id")
@click.argument("shot_id")
@click.option("--name", required=True)
@click.option("--kind", type=click.Choice(["character", "scene", "prop"]), required=True)
@click.option("--description", default="")
@click.option("--scope", type=click.Choice(["shot_only", "project_continuity"]), default="shot_only")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_asset_add(ctx: click.Context, project_id: str, shot_id: str, name: str, kind: str, description: str, scope: str, json_output: bool) -> None:
    """补充项目资产并绑定当前镜头或当前及后续镜头。"""
    _emit(_session(ctx).request(
        "POST", f"/storyboard/projects/{project_id}/shots/{shot_id}/quick-assets",
        json_body={"name": name, "kind": kind, "description": description, "scope": scope}, write=True,
    ), json_output)


@storyboard_group.command("continuity")
@click.argument("project_id")
@click.argument("from_shot_id")
@click.argument("to_shot_id")
@click.option("--dimension", "dimensions", type=click.Choice(["edit", "visual", "sound", "narrative"]), multiple=True)
@click.option("--intent", required=True, help="导演明确选择的衔接意图")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_continuity(ctx: click.Context, project_id: str, from_shot_id: str, to_shot_id: str, dimensions: tuple[str, ...], intent: str, json_output: bool) -> None:
    """记录人工导演衔接策略；不生成 AI 建议。"""
    _emit(_session(ctx).request(
        "POST", f"/storyboard/projects/{project_id}/shot-links/{from_shot_id}/{to_shot_id}/manual-decision",
        json_body={"idempotency_key": f"cli-storyboard-continuity-{__import__('time').time_ns()}", "dimensions": {key: "导演自主选择" for key in dimensions}, "rationale": intent}, write=True,
    ), json_output)


@storyboard_group.command("readiness")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storyboard_readiness(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """检查正式交付前的镜头、资产、任务与 QA 门禁。"""
    _emit(_session(ctx).request("GET", f"/storyboard/projects/{project_id}/readiness"), json_output)


@storyboard_group.command("export")
@click.argument("project_id")
@click.option("--kind", type=click.Choice(["csv", "prompts", "json", "pdf", "production-pdf"]), default="production-pdf")
@click.option("--output", required=True, type=click.Path(dir_okay=False))
@click.pass_context
def storyboard_export(ctx: click.Context, project_id: str, kind: str, output: str) -> None:
    """下载分镜表、提示词、JSON 或制作稿，不调用平台 Agent。"""
    endpoints = {"csv": "export.csv", "prompts": "export/prompts", "json": "export.json", "pdf": "export.pdf", "production-pdf": "export/production.pdf"}
    response = _session(ctx).request("GET", f"/storyboard/projects/{project_id}/{endpoints[kind]}", raw=True)
    Path(output).write_bytes(response.content)
    click.echo(ui.ok(f"已下载：{output}"), err=True)


# ------------------------------------------------------------------------- skills


@main.group("skill")
@click.pass_context
def skill_group(ctx: click.Context) -> None:
    """创作 Skill 工坊：列表 / 创建 / 编辑 / 挂载 / 上传。"""


# ------------------------------------------------------------------ skill craft
# 面向编辑/编剧（不懂技术「Skill」概念）的人机共建向导：把「写作方法论」翻译成
# 编辑语言，用启发式问题引导用户逐条给出作品专属规则，生成 skill JSON 草案后
# 必须由真人确认/修改才提交。禁止 agent 静默独立完成。


def _skill_craft_questions() -> list[dict[str, object]]:
    """启发式提问清单（编辑语言，非技术术语）。"""
    return [
        {
            "key": "work",
            "prompt": "这部作品是什么？用一句话说清故事与类型（例如：都市悬疑言情，女主查账本真相）。",
            "hint": "这就是方法论的开头——让创作搭档知道你在写什么。",
        },
        {
            "key": "craft",
            "prompt": "写作上你最在意什么？（节奏/张力/视角/镜头感/对白/场景时长……）请给出 2-3 条你希望每一章/每一场都遵守的写作规则。",
            "hint": "例如：每章结尾留钩子；对白短促有力；镜头语言克制、避免解释性台词。",
        },
        {
            "key": "voice",
            "prompt": "这部作品的「声音」是什么？句式、语感、用词上有哪些讲究？（短句冷冽 / 细腻长句 / 画面感优先……）",
            "hint": "这是作品区别于其他故事的辨识度所在。",
        },
        {
            "key": "continuity",
            "prompt": "连续性上必须守住什么？伏笔、设定、人物性格、跨场衔接……哪些不能破坏？",
            "hint": "例如：不丢已埋伏笔；已确立的设定不可更改；服装道具贯穿全剧。",
        },
        {
            "key": "evaluation",
            "prompt": "你判断一章/一场「写得好不好」的标准是什么？不满意时怎么处理？",
            "hint": "例如：按张力/连贯/角色主动性三维自检；不达标就拒收重写。",
        },
        {
            "key": "examples",
            "prompt": "给一个你喜欢的写法（正例）和一个你绝不想要的写法（反例）？",
            "hint": "例如：正例——用动作替代心理描写；反例——连续三句解释性旁白。",
        },
    ]


def _craft_answers_to_draft(domain: str, answers: dict[str, str]) -> dict[str, str]:
    """把编辑语言的回答组装成平台 skill 规范草案（结构化分节 + 正反例配对）。"""
    work = answers.get("work", "").strip()
    craft = answers.get("craft", "").strip()
    voice = answers.get("voice", "").strip()
    continuity = answers.get("continuity", "").strip()
    evaluation = answers.get("evaluation", "").strip()
    examples = answers.get("examples", "").strip()
    instructions = (
        f"本作品：{work}。"
        f"一、craft：{craft}"
        f"二、voice：{voice}"
        f"三、continuity：{continuity}"
        f"四、evaluation：{evaluation}"
        f"五、examples：{examples}"
    )
    if domain == "script":
        instructions += (
            "六、script-quality-anchors：每场必须有唯一戏剧功能，并让目标、关系、信息或风险"
            "发生可观察转折；只写镜头可见、声音可听、演员可表演的内容；对白、VO、OS 按正文"
            "时序清楚排列，台词量必须能装入目标时长；人物、道具、伏笔与转场保持连续。"
            "预计时长、发声轨等制作信息由系统从正文派生，编剧不维护机器字段。"
        )
    return {"instructions": instructions, "work": work}


def _load_skill_craft_answers(value: str) -> dict[str, str]:
    """Load agent-collected editor answers without creating project-like local state."""
    import json as _json

    raw = (
        Path(value[1:]).read_text(encoding="utf-8")
        if value.startswith("@")
        else value
    )
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"answers JSON 解析失败：{error}") from error
    if not isinstance(data, dict):
        raise click.ClickException("answers JSON 根必须是对象")
    keys = {str(item["key"]) for item in _skill_craft_questions()}
    return {key: str(data.get(key) or "").strip() for key in keys}


def _craft_missing_answers(answers: dict[str, str]) -> list[str]:
    """All six answers materially affect downstream writing quality."""
    return [str(item["key"]) for item in _skill_craft_questions() if not answers.get(str(item["key"]), "").strip()]


def _sanitize_skill_name(work: str) -> str:
    """从一句话作品描述生成 kebab-case skill 名（可人工修改）。"""
    import re as _re

    cleaned = _re.sub(r"[^0-9a-zA-Z]+", "-", work.strip().lower())
    cleaned = _re.sub(r"-+", "-", cleaned).strip("-")
    if not cleaned:
        import hashlib as _hashlib

        if work.strip():
            cleaned = "work-methodology-" + _hashlib.sha256(work.strip().encode("utf-8")).hexdigest()[:8]
        else:
            cleaned = "my-writing-methodology"
    return cleaned[:48]


@skill_group.command("craft")
@click.option("--domain", type=click.Choice(["novel", "script"]), default="novel", help="体裁：小说（novel）或剧本（script）")
@click.option("--project-id", default=None, help="可选：完成后挂载到指定作品（作品号）")
@click.option("--answers", default=None, help="Agent 已与用户共创的答案 JSON（@file 或内联 JSON）")
@click.option("--confirm", is_flag=True, help="确认用户已审阅最终方法论；Agent/JSON 模式提交必需")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_craft(
    ctx: click.Context,
    domain: str,
    project_id: str | None,
    answers: str | None,
    confirm: bool,
    json_output: bool,
) -> None:
    """人机共建写作方法论（Skill）—— 不需要懂技术，用编辑的语言逐条回答即可。

    这是一个「启发式共创」向导：用大白话问你作品与写作规则，把回答整理成
    平台需要的结构化方法论，最后必须由你亲自确认才提交。AI 不会替你决定
    你的写作标准——这份方法论代表你的判断。
    """
    medium = "小说" if domain == "novel" else "剧本"
    if not json_output:
        click.echo(ui.section("=== 人机共建写作方法论（共创向导）==="), err=True)
        click.echo(ui.paint(f"先花两分钟说清「{medium}」的创作标准——之后每一章/每一场都按它来写。", ui.GOLD), err=True)
        click.echo(ui.dim("所谓「Skill」就是这份写作方法的存档：你负责定规则，创作搭档负责严格执行。"), err=True)
        click.echo("", err=True)

    if json_output and answers is None:
        _emit(
            {
                "status": "needs_user_input",
                "domain": domain,
                "questions": _skill_craft_questions(),
                "answer_schema": {str(item["key"]): "" for item in _skill_craft_questions()},
                "next": "与用户自然共创后，将答案写入一个 JSON 对象，再运行 skill craft --answers @answers.json --confirm --json。",
            },
            True,
        )
        return

    collected: dict[str, str] = _load_skill_craft_answers(answers) if answers else {}
    if answers is None:
        for q in _skill_craft_questions():
            key = str(q["key"])
            prompt = str(q["prompt"])
            hint = str(q["hint"])
            click.echo(ui.dim(f"◆ {hint}"), err=True)
            click.echo(f"{prompt}", err=True)
            collected[key] = click.prompt("  你的回答", default="", show_default=False).strip()

    missing = _craft_missing_answers(collected)
    if missing:
        raise click.ClickException(
            "方法论信息不完整（缺少：" + ", ".join(missing) + "）。请补齐后一次提交，避免用通用模板进入正文创作。"
        )

    draft = _craft_answers_to_draft(domain, collected)
    suggested = _sanitize_skill_name(draft.get("work") or "my-methodology")
    if answers is None:
        click.echo("", err=True)
        click.echo(ui.section("=== 方法论草案（请审阅）==="), err=True)
        click.echo(draft["instructions"], err=True)
        click.echo("", err=True)
        name = click.prompt("方法论名称（kebab-case，可改）", default=suggested, show_default=True)
        description = click.prompt(
            f"一句话说明（例如：{medium}写作方法论——{draft.get('work') or '作品专属'}）",
            default=f"{medium}写作方法论",
            show_default=True,
        )
    else:
        name = suggested
        description = f"{medium}写作方法论"
    name = name.strip() or suggested
    description = description.strip() or f"{medium}写作方法论"

    payload = {
        "name": name,
        "description": description,
        "domain": domain,
        "roles": ["writer"],
        "stages": ["writing"],
        "instructions": draft["instructions"],
    }
    if answers is None:
        click.echo("", err=True)
        if not click.confirm("你已审阅这份方法论并确认它代表你的创作标准吗？（确认后提交）", default=False):
            click.echo(ui.warn("已取消——你可以用 skill update 修改已创建的方法论，或重新运行 skill craft。"), err=True)
            return
    check_result = _session(ctx).request(
        "POST", "/skills/personal/robustness-check", json_body=payload, write=True
    )
    check = dict(check_result.get("check") or {})
    if check.get("overall_status") != "pass":
        result = {
            "status": "needs_revision",
            "draft": payload,
            "robustness": check,
            "next": "只修改报告中 revise/block 的维度；保留用户已确认的创作意图，再次运行 craft 预检。",
        }
        _emit(result, json_output)
        if not json_output:
            click.echo(ui.warn("方法论尚未通过健壮性预检，未创建、未挂载。请按报告完善后重试。"), err=True)
        return
    if answers is not None and not confirm:
        _emit(
            {
                "status": "needs_confirmation",
                "draft": payload,
                "robustness": check,
                "next": "把 draft.instructions 完整展示给用户；明确认可后原命令加 --confirm。",
            },
            json_output,
        )
        return
    result = _session(ctx).request("POST", "/skills/personal", json_body=payload, write=True)
    if project_id:
        skill_id = str(result.get("id") or result.get("skill_id") or "")
        if skill_id:
            version_id = str(result.get("version_id") or result.get("versions", [{}])[0].get("id") or "")
            try:
                _session(ctx).request(
                    "PUT",
                    f"/projects/{project_id}/skills/{skill_id}",
                    json_body={"version_id": version_id} if version_id else {},
                    write=True,
                )
                mounted = _session(ctx).request("GET", f"/projects/{project_id}/skills")
                verified = any(str(item.get("skill_id") or item.get("id") or "") == skill_id for item in (mounted or []))
                if not json_output:
                    click.echo(ui.ok(f"方法论《{name}》已创建并挂载到作品 {project_id}（回读{'通过' if verified else '未通过'}）。"))
                _emit({**result, "robustness": check, "mounted_to": project_id, "verified": verified}, json_output)
                return
            except ScriptNowError as mount_error:
                if not json_output:
                    click.echo(ui.warn(f"方法论已创建，但挂载未完成：{mount_error}——可稍后 skill mount 手动挂载。"), err=True)
    if not json_output:
        click.echo(ui.ok(f"方法论《{name}》已创建 —— 用 skill mount <作品号> <skill_id> <version_id> 挂载到作品后即可开始创作。"))
    _emit({**result, "robustness": check}, json_output)


@skill_group.command("list")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_list(ctx: click.Context, json_output: bool) -> None:
    """List personal skills."""
    _emit(_session(ctx).request("GET", "/skills/personal"), json_output)


@skill_group.command("detail")
@click.argument("skill_id")
@click.option("--include-instructions", is_flag=True, help="显式读取完整私有方法论；默认仅返回安全摘要")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_detail(
    ctx: click.Context, skill_id: str, include_instructions: bool, json_output: bool
) -> None:
    """Show a personal Skill summary; full instructions require an explicit opt-in."""
    suffix = "?include_instructions=true" if include_instructions else ""
    _emit(_session(ctx).request("GET", f"/skills/personal/{skill_id}{suffix}"), json_output)


@skill_group.command("mounts")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_mounts(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """List skills mounted on a project."""
    _emit(_session(ctx).request("GET", f"/projects/{project_id}/skills"), json_output)


@skill_group.command("create")
@click.option("--name", required=True, help="kebab-case skill name, e.g. character-subtext")
@click.option("--description", required=True)
@click.option("--domain", type=click.Choice(["novel", "script"]), required=True)
@click.option("--role", type=click.Choice(["director", "architect", "writer", "reviewer"]), required=True)
@click.option("--stage", type=click.Choice(["ideation", "planning", "writing", "revision", "review"]), required=True)
@click.option("--instructions", required=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_create(
    ctx: click.Context,
    name: str,
    description: str,
    domain: str,
    role: str,
    stage: str,
    instructions: str,
    json_output: bool,
) -> None:
    """Create a personal skill (workshop)."""
    body = {
        "name": name,
        "description": description,
        "domain": domain,
        "roles": [role],
        "stages": [stage],
        "instructions": instructions,
    }
    _emit(_session(ctx).request("POST", "/skills/personal", json_body=body, write=True), json_output)


@skill_group.command("update")
@click.argument("skill_id")
@click.option("--description", default=None)
@click.option("--role", type=click.Choice(["director", "architect", "writer", "reviewer"]), default=None)
@click.option("--stage", type=click.Choice(["ideation", "planning", "writing", "revision", "review"]), default=None)
@click.option("--instructions", default=None)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_update(
    ctx: click.Context,
    skill_id: str,
    description: str | None,
    role: str | None,
    stage: str | None,
    instructions: str | None,
    json_output: bool,
) -> None:
    """Save a new version of a personal skill."""
    body: dict[str, Any] = {}
    if description is not None:
        body["description"] = description
    if role is not None:
        body["roles"] = [role]
    if stage is not None:
        body["stages"] = [stage]
    if instructions is not None:
        body["instructions"] = instructions
    if not body:
        raise click.ClickException("provide at least one field to update")
    _emit(_session(ctx).request("PUT", f"/skills/personal/{skill_id}", json_body=body, write=True), json_output)


@skill_group.command("versions")
@click.argument("skill_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_versions(ctx: click.Context, skill_id: str, json_output: bool) -> None:
    """List a skill's versions."""
    _emit(_session(ctx).request("GET", f"/skills/personal/{skill_id}/versions"), json_output)


@skill_group.command("archive")
@click.argument("skill_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_archive(ctx: click.Context, skill_id: str, json_output: bool) -> None:
    """Archive (soft-delete) a personal skill."""
    result = _session(ctx).request("DELETE", f"/skills/personal/{skill_id}", write=True)
    _emit({"ok": True, "skill_id": skill_id} if result is None else result, json_output)


@skill_group.command("mount")
@click.argument("project_id")
@click.argument("skill_id")
@click.option("--version-id", required=True, help="Skill version to pin")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_mount(ctx: click.Context, project_id: str, skill_id: str, version_id: str, json_output: bool) -> None:
    """Mount a skill version onto a project."""
    result = _session(ctx).request(
        "PUT",
        f"/projects/{project_id}/skills/{skill_id}",
        json_body={"version_id": version_id},
        write=True,
    )
    _emit({"ok": True, "project_id": project_id, "skill_id": skill_id} if result is None else result, json_output)


@skill_group.command("upload")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_upload(ctx: click.Context, file_path: str, json_output: bool) -> None:
    """Upload a SKILL.md or ZIP skill package."""
    with open(file_path, "rb") as handle:
        result = _session(ctx).request(
            "POST",
            "/skills/personal/upload",
            files={"file": (Path(file_path).name, handle)},
            write=True,
        )
    _emit(result, json_output)


# ------------------------------------------------------- skill 进化：method-growth


@skill_group.group("growth")
@click.pass_context
def skill_growth_group(ctx: click.Context) -> None:
    """Skill 能力进化（方法论成长）：从创作实绩提炼方法论 → 候选 → 评估 → 发布为新 Skill 版本。
    这是「主站 Skill 进化」的作者侧链路：run → candidates → decide → evaluate → preview → publish。"""


@skill_growth_group.command("workspace")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_growth_workspace(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """项目的方法论成长工作台（候选 / 证据 / 可发布物）。"""
    _emit(
        _api_request(ctx, "GET", "/skills/method-growth", params={"project_id": project_id}),
        json_output,
    )


@skill_growth_group.command("start")
@click.argument("project_id")
@click.option("--domain", type=click.Choice(["novel", "script"]), required=True)
@click.option("--episode-ids", default=None, help="逗号分隔的 episode/章节 id（默认自动取全部 eligible）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_growth_start(
    ctx: click.Context, project_id: str, domain: str, episode_ids: str | None, json_output: bool
) -> None:
    """启动方法论成长分析（后台执行，产出成长候选）。"""
    body: dict[str, Any] = {
        "domain": domain,
        "episode_ids": [item.strip() for item in episode_ids.split(",") if item.strip()]
        if episode_ids
        else [],
        "idempotency_key": f"cli-growth-{__import__('time').time_ns()}",
    }
    result = _api_request(
        ctx,
        "POST",
        f"/skills/method-growth/projects/{project_id}/runs",
        json_body=body,
        write=True,
    )
    if not json_output:
        click.echo(ui.ok("方法论成长分析已启动，完成后用 skill growth workspace 查看候选，再 decide → evaluate → publish。"))
        click.echo(ui.dim("完成后用 skill growth workspace 查看候选，再 decide → evaluate → publish。"), err=True)
    _emit(result, json_output)


@skill_growth_group.command("decide")
@click.argument("candidate_id")
@click.option(
    "--action",
    type=click.Choice(["only_project", "accept", "edit", "defer", "reject", "suppress", "withdraw"]),
    required=True,
)
@click.option("--edit", "edit_file", default=None, help="@edited_change.json（action=edit 时的修改内容）")
@click.option("--reason", default=None)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_growth_decide(
    ctx: click.Context,
    candidate_id: str,
    action: str,
    edit_file: str | None,
    reason: str | None,
    json_output: bool,
) -> None:
    """对成长候选做决策（accept 采纳进入评估 / reject 拒绝 / edit 修改后采纳…）。"""
    import json as _json

    body: dict[str, Any] = {
        "action": action,
        "idempotency_key": f"cli-growth-decide-{__import__('time').time_ns()}",
    }
    if edit_file:
        raw = Path(edit_file[1:] if edit_file.startswith("@") else edit_file).read_text(encoding="utf-8")
        body["edited_change"] = _json.loads(raw)
    if reason:
        body["reason"] = reason
    result = _api_request(ctx, 
        "POST", f"/skills/method-growth/candidates/{candidate_id}/decisions", json_body=body, write=True
    )
    if not json_output:
        click.echo(ui.ok(f"候选 {candidate_id} → {action}（{result.get('resulting_state')}）"))
    _emit(result, json_output)


@skill_growth_group.command("candidate")
@click.option("--from", "source_ids", required=True, help="逗号分隔的已采纳 source_candidate_ids")
@click.option("--skill", "target_skill_id", required=True, help="目标个人 Skill id")
@click.option("--intent", "author_intent", required=True, help="作者意图说明（≤2000）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_growth_candidate(
    ctx: click.Context, source_ids: str, target_skill_id: str, author_intent: str, json_output: bool
) -> None:
    """把已采纳的项目证据显式聚合为一个个人成长候选。"""
    body: dict[str, Any] = {
        "source_candidate_ids": [item.strip() for item in source_ids.split(",") if item.strip()],
        "target_skill_id": target_skill_id,
        "author_intent": author_intent,
        "idempotency_key": f"cli-growth-cand-{__import__('time').time_ns()}",
    }
    result = _api_request(ctx, 
        "POST", "/skills/method-growth/personal-candidates", json_body=body, write=True
    )
    if not json_output:
        click.echo(ui.ok(f"个人候选已创建：{result.get('id')}（{result.get('state')}）"))
    _emit(result, json_output)


@skill_growth_group.command("evaluate")
@click.argument("candidate_id")
@click.option("--policy-version", default=None, help="评估策略版本 id（默认取最新 active）")
@click.option("--attribution", type=click.Choice(["combination", "ablation"]), default="combination")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_growth_evaluate(
    ctx: click.Context, candidate_id: str, policy_version: str | None, attribution: str, json_output: bool
) -> None:
    """对候选启动评估回放（后台执行，产出 evaluation_result_id 供 publish 用）。"""
    body: dict[str, Any] = {
        "policy_version_id": policy_version,
        "attribution_mode": attribution,
        "idempotency_key": f"cli-growth-eval-{__import__('time').time_ns()}",
    }
    result = _api_request(ctx, 
        "POST",
        f"/skills/method-growth/candidates/{candidate_id}/evaluation-runs",
        json_body=body,
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"评估已启动：replay {result.get('id')}（{result.get('status')}，{result.get('pair_count')} 对）"))
    _emit(result, json_output)


@skill_growth_group.command("preview")
@click.argument("candidate_id")
@click.option("--evaluation-result", "evaluation_result_id", required=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_growth_preview(
    ctx: click.Context, candidate_id: str, evaluation_result_id: str, json_output: bool
) -> None:
    """发布前预览：Skill 能力进化后的版本物料与 mount 影响。"""
    _emit(
        _api_request(ctx, 
            "GET",
            f"/skills/method-growth/candidates/{candidate_id}/promotion-preview",
            params={"evaluation_result_id": evaluation_result_id},
        ),
        json_output,
    )


@skill_growth_group.command("publish")
@click.argument("candidate_id")
@click.option("--evaluation-result", "evaluation_result_id", required=True)
@click.option("--description", required=True)
@click.option("--instructions", required=True, help="进化后的方法论正文（≤100,000）")
@click.option("--role", type=click.Choice(["director", "architect", "writer", "reviewer"]), default="writer")
@click.option("--stage", type=click.Choice(["ideation", "planning", "writing", "revision", "review"]), default="writing")
@click.option("--mount", "mount_ids", default=None, help="逗号分隔的挂载项目 id（触发 canary 灰度）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_growth_publish(
    ctx: click.Context,
    candidate_id: str,
    evaluation_result_id: str,
    description: str,
    instructions: str,
    role: str,
    stage: str,
    mount_ids: str | None,
    json_output: bool,
) -> None:
    """发布进化后的 Skill 版本（写操作）：评估通过 → 新版本 → 可选 canary 灰度。"""
    body: dict[str, Any] = {
        "evaluation_result_id": evaluation_result_id,
        "description": description,
        "roles": [role],
        "stages": [stage],
        "instructions": instructions,
        "mount_project_ids": [item.strip() for item in mount_ids.split(",") if item.strip()]
        if mount_ids
        else [],
    }
    result = _api_request(ctx, 
        "POST",
        f"/skills/method-growth/candidates/{candidate_id}/publish",
        json_body=body,
        write=True,
    )
    if not json_output:
        click.echo(
            ui.ok(
                f"Skill 已进化发布：{result.get('id')} 版本 {result.get('version')}（version_id {result.get('version_id')}）"
            )
        )
        if result.get("canary_id"):
            click.echo(ui.dim(f"canary 灰度：{result.get('canary_id')}（{result.get('canary_status')}）"), err=True)
    _emit(result, json_output)


# ------------------------------------------------------- skill 版本进化：canary 灰度


@skill_group.group("canary")
@click.pass_context
def skill_canary_group(ctx: click.Context) -> None:
    """Skill 版本进化（金丝雀灰度）：新版发布后在小范围项目上观察，作者决策
    retain（全量保留）/ limit（限量）/ need_evidence（需更多证据）/ rollback（回滚旧版）。"""


@skill_canary_group.command("list")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_canary_list(ctx: click.Context, json_output: bool) -> None:
    """我发起的 Skill canary 灰度列表。"""
    _emit(_api_request(ctx, "GET", "/skills/canaries"), json_output)


@skill_canary_group.command("decide")
@click.argument("canary_id")
@click.option("--action", type=click.Choice(["retain", "limit", "need_evidence", "rollback"]), required=True)
@click.option("--project-ids", default=None, help="逗号分隔的保留/限量项目 id（action=retain/limit 时）")
@click.option("--reason", default=None)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_canary_decide(
    ctx: click.Context,
    canary_id: str,
    action: str,
    project_ids: str | None,
    reason: str | None,
    json_output: bool,
) -> None:
    """对 Skill canary 灰度做决策（版本进化方向）。"""
    body: dict[str, Any] = {
        "action": action,
        "retained_project_ids": [item.strip() for item in project_ids.split(",") if item.strip()]
        if project_ids
        else [],
        "idempotency_key": f"cli-canary-{__import__('time').time_ns()}",
    }
    if reason:
        body["reason"] = reason
    result = _session(ctx).request(
        "POST", f"/skills/canaries/{canary_id}/decisions", json_body=body, write=True
    )
    if not json_output:
        click.echo(
            ui.ok(f"canary {canary_id} → {action}（{result.get('previous_status')} → {result.get('resulting_status')}）")
        )
    _emit(result, json_output)


# -------------------------------------------------------------------------- cover


@main.group("cover")
@click.pass_context
def cover_group(ctx: click.Context) -> None:
    """作品封面：先生成作品包装包（package）→ 选生图模型 → 生成封面。"""


@cover_group.command("package")
@click.argument("project_id")
@click.option("--feedback", default=None, help="对现有包装的修改意见（可选）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def cover_package(ctx: click.Context, project_id: str, feedback: str | None, json_output: bool) -> None:
    """生成 / 重建作品包装包（title/synopsis/tags/cover_brief/cover_prompt）。
    生图前置：未生成包装包时无法生图。同步等待（可能数分钟）。"""
    body: dict[str, Any] = {
        "idempotency_key": f"cli-package-{__import__('time').time_ns()}",
    }
    if feedback:
        body["feedback"] = feedback
    result = _api_request(
        ctx,
        "POST",
        f"/projects/{project_id}/packaging/generate",
        json_body=body,
        write=True,
        timeout=600,
    )
    if not json_output:
        click.echo(ui.ok(f"作品包装已生成：《{result.get('title')}》（v{result.get('version')}）—— 下一步 cover generate 生成封面。"))
        return
    _emit(result, json_output)


@cover_group.command("package-propose")
@click.argument("project_id")
@click.option("--file", "draft_file", required=True, help="@package.json（Agent 本地产出的包装文案）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def cover_package_propose(ctx: click.Context, project_id: str, draft_file: str, json_output: bool) -> None:
    """Agent 自主提交作品包装文案 → 最新包装包（不经平台 AI 生成）。

    与 chapter/scene propose 同构：Agent 在本地按规范写好
    {title, synopsis(≥100字), tags(3-12), cover_brief:{subject, setting,
    visual_metaphor, palette, composition, title_safe_area, style,
    forbidden_elements}}，平台只做校验、幂等与落库。
    """
    import json as _json

    raw = Path(draft_file[1:] if draft_file.startswith("@") else draft_file).read_text(
        encoding="utf-8"
    )
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError as error:
        raise click.ClickException(f"包装文案 JSON 解析失败：{error}") from error
    if not isinstance(data, dict):
        raise click.ClickException("包装文案必须是对象（title/synopsis/tags/cover_brief）")
    result = _api_request(
        ctx,
        "POST",
        f"/projects/{project_id}/packaging/propose",
        json_body={
            "idempotency_key": f"cli-pkg-propose-{__import__('time').time_ns()}",
            "draft": data,
        },
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"作品包装包已提交：{result.get('title')}（v{result.get('version')}）"))
    _emit(result, json_output)


@cover_group.command("package-show")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def cover_package_show(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """查看最新作品包装包（封面 brief 与 prompt）。"""
    result = _api_request(ctx, "GET", f"/projects/{project_id}/packaging")
    if result is None:
        if not json_output:
            click.echo(ui.warn("该作品尚未生成作品包装——先运行 cover package <作品号> 生成，再生成封面图。"), err=True)
        return
    if not json_output:
        click.echo(ui.section(f"=== 作品包装包 {result.get('id')}（v{result.get('version')}）==="), err=True)
        click.echo(f"  {ui.kv('title', result.get('title'))}", err=True)
        click.echo(f"  {ui.kv('synopsis', result.get('synopsis'))}", err=True)
        click.echo(f"  {ui.kv('language', result.get('language'))}", err=True)
        click.echo(ui.dim("cover_brief / cover_prompt 见 --json 输出"), err=True)
        return
    _emit(result, json_output)


@cover_group.command("models")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def cover_models(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """列出可用的生图模型（封面生成前先选模型）。"""
    _emit(_session(ctx).request("GET", f"/projects/{project_id}/packaging/image-models"), json_output)


@cover_group.command("specs")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def cover_specs(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """列出封面输出规格（尺寸/用途，如 3:4 主封面）。"""
    _emit(_session(ctx).request("GET", f"/projects/{project_id}/packaging/cover-output-specs"), json_output)


@cover_group.command("generate")
@click.argument("project_id")
@click.option("--image-model-id", required=True, help="生图模型 id（用 cover models 查看）")
@click.option("--output-keys", default=None, help="逗号分隔的输出规格 key（默认 1 个：wattpad_hd = 1024×1600）")
@click.option("--prompt", default=None, help="覆盖封面 prompt（默认由平台根据作品生成）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def cover_generate(
    ctx: click.Context,
    project_id: str,
    image_model_id: str,
    output_keys: str | None,
    prompt: str | None,
    json_output: bool,
) -> None:
    """为作品生成封面候选（同步返回封面列表）。默认只生成 1 个规格：1024×1600（wattpad_hd）。"""
    body: dict[str, Any] = {"image_model_id": image_model_id}
    # 默认 1 个规格 1024×1600；--output-keys 可覆盖
    body["output_keys"] = (
        tuple(key.strip() for key in output_keys.split(",") if key.strip())
        if output_keys
        else ("wattpad_hd",)
    )
    if prompt:
        body["prompt"] = prompt
    _emit(
        _session(ctx).request(
            "POST",
            f"/projects/{project_id}/packaging/covers/generate",
            json_body=body,
            write=True,
            timeout=300,
        ),
        json_output,
    )


@cover_group.command("list")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def cover_list(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """列出项目已生成的封面候选。"""
    _emit(_session(ctx).request("GET", f"/projects/{project_id}/packaging/covers"), json_output)


@cover_group.command("delete")
@click.argument("project_id")
@click.argument("cover_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def cover_delete(ctx: click.Context, project_id: str, cover_id: str, json_output: bool) -> None:
    """删除一张封面候选。"""
    result = _session(ctx).request(
        "DELETE", f"/projects/{project_id}/packaging/covers/{cover_id}", write=True
    )
    _emit({"ok": True, "cover_id": cover_id} if result is None else result, json_output)


# ------------------------------------------------------------------------- export


@main.group("export")
@click.pass_context
def export_group(ctx: click.Context) -> None:
    """导出与交付：小说成书 / 剧本成册，可下载。"""


@export_group.command("options")
@click.argument("project_id")
@click.option("--domain", type=click.Choice(["novel", "script"]), default="novel")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def export_options(ctx: click.Context, project_id: str, domain: str, json_output: bool) -> None:
    """查看该项目的导出选项（可用章节/场次、格式、翻译模式）。"""
    prefix = "/novel" if domain == "novel" else "/script"
    _emit(_session(ctx).request("GET", f"{prefix}/projects/{project_id}/exports/options"), json_output)


@export_group.command("create")
@click.argument("project_id")
@click.option("--domain", type=click.Choice(["novel", "script"]), default="novel")
@click.option("--units", required=True, help="逗号分隔的章节/场次 id（用 export options 或 chapter/scene list 查看）")
@click.option("--form", type=click.Choice(["clean", "working"]), default="clean", help="clean=纯净稿；working=含预计时长/发声轨/转场的制作工作稿")
@click.option("--translation-mode", type=click.Choice(["none", "faithful"]), default="none")
@click.option("--target-language", default=None, help="翻译目标语言（translation-mode=faithful 时必填）")
@click.option("--front-matter", type=click.Choice(["none", "outline"]), default="none")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def export_create(
    ctx: click.Context,
    project_id: str,
    domain: str,
    units: str,
    form: str,
    translation_mode: str,
    target_language: str | None,
    front_matter: str,
    json_output: bool,
) -> None:
    """创建导出（返回 manifest，用于下载）。"""
    prefix = "/novel" if domain == "novel" else "/script"
    unit_key = "chapter_ids" if domain == "novel" else "scene_ids"
    body: dict[str, Any] = {
        unit_key: tuple(item.strip() for item in units.split(",") if item.strip()),
        "form": form,
        "translation_mode": translation_mode,
        "front_matter": front_matter,
        "idempotency_key": f"cli-export-{__import__('time').time_ns()}",
    }
    if target_language:
        body["target_language"] = target_language
    _emit(
        _session(ctx).request(
            "POST", f"{prefix}/projects/{project_id}/exports", json_body=body, write=True, timeout=600
        ),
        json_output,
    )


@export_group.command("download")
@click.argument("project_id")
@click.argument("manifest_id")
@click.option("--domain", type=click.Choice(["novel", "script"]), default="novel")
@click.option("--output", "-o", default="export.bin", help="保存到本地文件路径")
@click.pass_context
def export_download(
    ctx: click.Context, project_id: str, manifest_id: str, domain: str, output: str
) -> None:
    """下载导出文件到本地（如 .epub / .docx / 打包 zip）。"""
    session = _session(ctx)
    prefix = "/novel" if domain == "novel" else "/script"
    response = session.request(
        "GET",
        f"{prefix}/projects/{project_id}/exports/{manifest_id}/download",
        timeout=300,
        raw=True,
    )
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(response.content)
    click.echo(ui.ok(f"已保存到 {out}（{len(response.content)} 字节）"))


@export_group.command("zip")
@click.argument("project_id")
@click.option("--domain", type=click.Choice(["novel", "script"]), default="novel")
@click.option("--units", required=True, help="逗号分隔的章节/场次 id（用 export options 或 chapter/scene list 查看）")
@click.option("--form", type=click.Choice(["clean", "working"]), default="clean", help="clean=纯净稿；working=含预计时长/发声轨/转场的制作工作稿")
@click.option("--translation-mode", type=click.Choice(["none", "faithful"]), default="none")
@click.option("--target-language", default=None, help="翻译目标语言（translation-mode=faithful 时必填）")
@click.option("--front-matter", type=click.Choice(["none", "outline"]), default="none")
@click.option("--output", "-o", default=None, help="保存到本地 zip 文件路径（默认取响应文件名）")
@click.pass_context
def export_zip(
    ctx: click.Context,
    project_id: str,
    domain: str,
    units: str,
    form: str,
    translation_mode: str,
    target_language: str | None,
    front_matter: str,
    output: str | None,
) -> None:
    """下载整部作品 ZIP 包（docx + 封面 + manifest.json）到本地。"""
    import re as _re

    session = _session(ctx)
    prefix = "/novel" if domain == "novel" else "/script"
    unit_key = "chapter_ids" if domain == "novel" else "scene_ids"
    body: dict[str, Any] = {
        unit_key: tuple(item.strip() for item in units.split(",") if item.strip()),
        "form": form,
        "translation_mode": translation_mode,
        "front_matter": front_matter,
        "idempotency_key": f"cli-export-zip-{__import__('time').time_ns()}",
    }
    if target_language:
        body["target_language"] = target_language
    response = session.request(
        "POST",
        f"{prefix}/projects/{project_id}/exports/zip",
        json_body=body,
        write=True,
        timeout=600,
        raw=True,
    )
    if not response.content.startswith(b"PK"):
        raise click.ClickException("响应不是有效的 zip 文件")
    out = output
    if out is None:
        disposition = response.headers.get("Content-Disposition", "")
        star = _re.search(r"filename\*=UTF-8''([^;]+)", disposition, _re.IGNORECASE)
        out = star.group(1) if star else "export.zip"
        try:
            out = __import__("urllib.parse", fromlist=["unquote"]).unquote(out)
        except Exception:
            pass
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    click.echo(ui.ok(f"已保存 ZIP 到 {path}（{len(response.content)} 字节）"))


# --------------------------------------------------------------------------- runs


def _wait_for_run(session: Session, project_id: str, run_id: str, json_output: bool, *, domain: str = "novel") -> None:
    import os as _os
    import time

    # Long synchronous waits are hostile to agent hosts: the host caps how
    # long a single tool call may run ("tool waiting window") and kills the
    # call on timeout. Default 16 minutes suits interactive terminals; agent
    # hosts should set SCRIPTNOW_WAIT_MAX_SECONDS to their own window and
    # continue polling with `scriptnow run status` afterwards.
    try:
        max_seconds = int(_os.environ.get("SCRIPTNOW_WAIT_MAX_SECONDS", "960"))
    except ValueError:
        max_seconds = 960
    path = f"/{domain}/projects/{project_id}/runs/{run_id}"
    deadline = time.time() + max_seconds
    last = None
    while time.time() < deadline:
        state = session.request("GET", path)
        status = str(state.get("status") or "")
        if status in ("succeeded", "failed", "cancelled"):
            _emit(state, json_output)
            if status != "succeeded":
                raise click.ClickException(f"run ended with status {status}")
            return
        if status != last:
            if not json_output:
                click.echo(ui.dim(f"run {run_id}: {status}"), err=True)
            last = status
        time.sleep(2)
    raise click.ClickException(
        f"run {run_id} did not finish within {max_seconds}s; "
        "继续用 scriptnow run status 轮询（agent 场景建议 SCRIPTNOW_WAIT_MAX_SECONDS=45）"
    )
