"""scriptnow-cli — agent-native CLI for the ScriptNow creative platform.

Covers the core creation chain: projects, work interpretation (read-through →
source profile + reusable skill), novel chapters & StoryMap, and tenant skills.
Every command supports ``--json`` for structured agent consumption.

Configuration: session persisted at ~/.config/scriptnow-cli/session.json after
``scriptnow login``; or set SCRIPTNOW_CLI_CONFIG to relocate it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from cli_anything.scriptnow import ui
from cli_anything.scriptnow.utils.session import (
    ScriptNowError,
    Session,
    load,
    login,
    write_json,
)


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
VERSION = "0.1.0"


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


def _human(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


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
    ui.banner(VERSION)
    + "\n\n"
    + """ScriptNow 创作 CLI —— 从灵感到成书交付的一站式命令行。

典型流程（Agent 或创作者）：
  1. scriptnow project create --name 新作 --medium novel   # 建项目
  2. scriptnow interpret go 手稿.docx                       # 一书一 Skill：上传作品解读出创作方法论
  3. scriptnow storymap generate <pid> --wait               # 规划全书卷章节
  4. scriptnow book <pid>                                   # 查看全书托管创作规划
  5. scriptnow chapter generate <pid> chapter-1-1 --wait    # 逐章生成（Agent 审读后带 feedback 修正）
  6. scriptnow cover generate <pid> --image-model-id <id>   # 生成封面
  7. scriptnow export create <pid> --units chapter-1-1      # 导出成书
  8. scriptnow export download <pid> <manifest> -o 书.docx  # 下载交付

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
    message=f"{ui.paint('ScriptNow CLI', ui.GOLD)} %(version)s",
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
    if ctx.invoked_subcommand is None:
        click.echo(ui.banner(VERSION))
        click.echo(ui.dim("运行 scriptnow --help 查看全部命令；每个子命令 -h 查看用法。"))


# --------------------------------------------------------------------------- auth


@main.command()
@click.option("--host", required=True, help="Platform base URL, e.g. https://sn.igeewa.com")
@click.option("--email", required=True)
@click.option("--password", required=True, hide_input=True)
@click.option("--json", "json_output", is_flag=True)
def login_cmd(host: str, email: str, password: str, json_output: bool) -> None:
    """Authenticate and persist a session (cookie + CSRF)."""
    try:
        session = login(host, email, password)
    except ScriptNowError as error:
        raise click.ClickException(str(error)) from error
    if not json_output:
        click.echo(ui.ok(f"登录成功：{host}（{email}）"))
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
    """List projects."""
    _emit(_session(ctx).request("GET", "/projects"), json_output)


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
    _emit(
        _session(ctx).request("POST", "/projects", json_body=body, write=True),
        json_output,
    )


@project_group.command("upload")
@click.argument("project_id")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
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
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def account_summary(ctx: click.Context, json_output: bool) -> None:
    """Show account summary (plan, quota, credits) — check before long runs."""
    _emit(_session(ctx).request("GET", "/account/summary"), json_output)


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
    response = session._http.get(
        f"{session.api_root}/runs/{run_id}/events",
        headers=headers,
        cookies=session.cookies or None,
        timeout=60,
    )
    if response.status_code >= 400:
        from cli_anything.scriptnow.utils.session import _extract_detail

        raise click.ClickException(f"HTTP {response.status_code}: {_extract_detail(response)}")
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    _emit(payload, json_output)


# ------------------------------------------------------------ work interpretation


@main.group("interpret")
@click.pass_context
def interpret_group(ctx: click.Context) -> None:
    """一书一 Skill：上传作品，通读生成「源分析 + 创作方法论」双卡。"""


@interpret_group.command("go")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
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
        click.echo(f"项目: {project_id}  蒸馏: {distillation_id}  开始通读（可能数分钟）…", err=True)
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
        detail = session.request("GET", f"/skills/personal/{match['skill_id']}")
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
        click.echo(ui.ok(f"Skill 已创建：{created.get('name')}（{skill_id}）"))
        if result.get("mounted"):
            click.echo(ui.ok(f"已挂载到项目 {project_id}（version {result['mounted']['version_id']}）"))
        if result.get("mount_error"):
            click.echo(ui.warn(f"挂载失败：{result['mount_error']}"))
    _emit(result, json_output)


# ----------------------------------------------------------------------- chapters


@main.group("chapter")
@click.pass_context
def chapter_group(ctx: click.Context) -> None:
    """小说章节：列表 / 阅读 / 生成 / 质量 / 采纳。"""


@chapter_group.command("list")
@click.argument("project_id")
@click.option("--status", default=None, help="Filter by document status: candidate|adopted|active")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_list(ctx: click.Context, project_id: str, status: str | None, json_output: bool) -> None:
    """List chapters from the adopted StoryMap with their document state
    (adopted revision, candidate revisions, version counts)."""
    state = _session(ctx).request("GET", f"/novel/projects/{project_id}/state")
    volumes = state.get("story_map", {}).get("volumes", [])
    documents = state.get("documents", [])
    rows = []
    for volume in volumes:
        for chapter in volume.get("chapters", []):
            chapter_id = str(chapter["id"])
            docs = [doc for doc in documents if doc.get("chapter_id") == chapter_id]
            adopted = next((doc for doc in docs if doc.get("status") == "adopted"), None)
            candidates = [doc for doc in docs if doc.get("status") in ("candidate", "active")]
            candidates.sort(key=lambda doc: doc.get("revision_number", 0), reverse=True)
            row = {
                "chapter_id": chapter_id,
                "title": chapter.get("title"),
                "target_words": chapter.get("target_words"),
                "adopted_revision": adopted.get("revision_number") if adopted else None,
                "candidate_revisions": [doc.get("revision_number") for doc in candidates],
                "latest_candidate_id": candidates[0].get("id") if candidates else None,
            }
            if status is None or (status == "adopted" and adopted) or (status in ("candidate", "active") and candidates):
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
    This is the review primitive: an agent reads the text here and forms its
    own judgment; fixes are driven via `chapter generate --feedback`."""
    state = _session(ctx).request("GET", f"/novel/projects/{project_id}/state")
    documents = state.get("documents", [])
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
        },
        json_output,
    )


@chapter_group.command("generate")
@click.argument("project_id")
@click.argument("chapter_id")
@click.option("--feedback", default=None)
@click.option("--wait", is_flag=True, help="Poll until the background run finishes")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_generate(
    ctx: click.Context, project_id: str, chapter_id: str, feedback: str | None, wait: bool, json_output: bool
) -> None:
    """Generate a chapter candidate (background by default)."""
    session = _session(ctx)
    body = {"idempotency_key": f"cli-chapter-{__import__('time').time_ns()}", "feedback": feedback}
    result = session.request(
        "POST",
        f"/novel/projects/{project_id}/chapters/{chapter_id}/generate?background=true",
        json_body=body,
        write=True,
    )
    if wait and result.get("run_id"):
        _wait_for_run(session, project_id, str(result["run_id"]), json_output)
        return
    _emit(result, json_output)


@chapter_group.command("adopt")
@click.argument("project_id")
@click.argument("chapter_id")
@click.argument("revision_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_adopt(ctx: click.Context, project_id: str, chapter_id: str, revision_id: str, json_output: bool) -> None:
    """Adopt a chapter revision as the working text."""
    _emit(
        _session(ctx).request(
            "POST",
            f"/novel/projects/{project_id}/chapters/{chapter_id}/revisions/{revision_id}/adopt",
            write=True,
        ),
        json_output,
    )


@chapter_group.command("propose")
@click.argument("project_id")
@click.argument("chapter_id")
@click.option("--file", "blocks_file", default=None, help="章节正文 JSON：{\"blocks\":[{\"block_id\":\"h1\",\"type\":\"heading|prose|dialogue|quote|divider\",\"text\":\"...\"}]}")
@click.option("--text", default=None, help="纯文本正文（自动分段为 prose blocks，首段为标题）")
@click.option("--budget", type=int, default=None, help="正文 token 预算上限（中文≈1 token/字，英文≈1 token/4 字符）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_propose(
    ctx: click.Context,
    project_id: str,
    chapter_id: str,
    blocks_file: str | None,
    text: str | None,
    budget: int | None,
    json_output: bool,
) -> None:
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
    }
    result = session.request(
        "POST",
        f"/novel/projects/{project_id}/chapters/{chapter_id}/propose",
        json_body=body,
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"章节候选已回传 {chapter_id}（{result.get('status', 'candidate')}）"))
    _emit(result, json_output)


@chapter_group.command("quality")
@click.argument("project_id")
@click.argument("chapter_id")
@click.argument("revision_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def chapter_quality(
    ctx: click.Context, project_id: str, chapter_id: str, revision_id: str, json_output: bool
) -> None:
    """Run the serial-quality evaluation for a chapter revision (blocks)."""
    body = {"revision_id": revision_id, "idempotency_key": f"cli-quality-{__import__('time').time_ns()}"}
    _emit(
        _session(ctx).request(
            "POST",
            f"/novel/projects/{project_id}/chapters/{chapter_id}/quality-reports/generate",
            json_body=body,
            write=True,
            timeout=600,
        ),
        json_output,
    )


@main.command("book")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def book_plan(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """查看全书托管创作规划（Agent 编排原语）：各章已采纳 / 待生成 / 候选待审状态，
    供 Agent 决定逐章创作顺序与审读反馈。

    The agent (you, or another CLI-equipped agent) drives the hosted loop:
    read this plan, then for each chapter use `chapter show` to read the text,
    form your own judgment, drive fixes with `chapter generate --feedback`,
    and adopt with `chapter adopt`. Platform quality scoring is optional; the
    review judgment belongs to the agent, not to a fixed rubric.
    """
    state = _session(ctx).request("GET", f"/novel/projects/{project_id}/state")
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
        adopted = next((doc for doc in docs if doc.get("status") == "adopted"), None)
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
    _emit(summary, json_output)


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
    _emit(_session(ctx).request("GET", f"/novel/projects/{project_id}/state"), json_output)


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
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def storymap_adopt(ctx: click.Context, project_id: str, candidate_id: str, json_output: bool) -> None:
    """Adopt a StoryMap structure candidate."""
    _emit(
        _session(ctx).request(
            "POST",
            f"/novel/projects/{project_id}/story-map/{candidate_id}/adopt",
            write=True,
        ),
        json_output,
    )


# ------------------------------------------------------------------ novel core chain


@main.group("novel")
@click.pass_context
def novel_group(ctx: click.Context) -> None:
    """小说创作链：故事核心与蓝图（规划阶段）。"""


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
    state = session.request("GET", f"/novel/projects/{project_id}/state")
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
    state = session.request("GET", f"/novel/projects/{project_id}/state")
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
        state = session.request("GET", f"/novel/projects/{project_id}/state")
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
    state = session.request("GET", f"/novel/projects/{project_id}/state")
    sm = next((c for c in state.get("story_map_candidates") or [] if c.get("status") == "active"), None)
    if sm is None:
        note(f"StoryMap（{storymap_source}）", False, "没有候选")
        _emit({"project_id": project_id, "steps": steps}, json_output)
        return
    session.request(
        "POST",
        f"/novel/projects/{project_id}/story-map/{sm['id']}/adopt",
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
        state = session.request("GET", f"/novel/projects/{project_id}/state")
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
                f"/novel/projects/{project_id}/story-map/{candidate_id}/adopt",
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
    state = session.request("GET", f"/novel/projects/{project_id}/state")
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
            f"/novel/projects/{project_id}/story-map/{final_candidate['id']}/adopt",
            write=True,
        )
        if not json_output:
            click.echo(ui.ok(f"StoryMap 已采纳（{adopted.get('status')}）"), err=True)

    # ④ 输出全书创作计划
    fresh = session.request("GET", f"/novel/projects/{project_id}/state")
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


@script_group.command("state")
@click.argument("project_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_state(ctx: click.Context, project_id: str, json_output: bool) -> None:
    """Show script project state."""
    _emit(_session(ctx).request("GET", f"/script/projects/{project_id}/state"), json_output)


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
    """Show a scene's script text for agent review (review primitive)."""
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
    _emit(
        {
            "scene_id": scene_id,
            "revision_id": chosen.get("id"),
            "revision_number": chosen.get("revision_number"),
            "source": chosen.get("source"),
            "status": chosen.get("status"),
            "text": text,
            "block_count": len(blocks),
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
@click.option("--wait", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_scene(
    ctx: click.Context, project_id: str, scene_id: str, feedback: str | None, wait: bool, json_output: bool
) -> None:
    """Generate a scene candidate (script)."""
    session = _session(ctx)
    body = {"idempotency_key": f"cli-scene-{__import__('time').time_ns()}", "feedback": feedback}
    result = session.request(
        "POST",
        f"/script/projects/{project_id}/scenes/{scene_id}/generate?background=true",
        json_body=body,
        write=True,
    )
    if wait and result.get("run_id"):
        _wait_for_run(session, project_id, str(result["run_id"]), json_output, domain="script")
        return
    _emit(result, json_output)


@script_group.command("adopt-scene")
@click.argument("project_id")
@click.argument("scene_id")
@click.argument("revision_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_adopt_scene(
    ctx: click.Context, project_id: str, scene_id: str, revision_id: str, json_output: bool
) -> None:
    """Adopt a scene revision (script)."""
    _emit(
        _session(ctx).request(
            "POST",
            f"/script/projects/{project_id}/scenes/{scene_id}/revisions/{revision_id}/adopt",
            write=True,
        ),
        json_output,
    )


@script_group.command("scene-propose")
@click.argument("project_id")
@click.argument("scene_id")
@click.option("--file", "blocks_file", default=None, help="blocks JSON 路径（@file 前缀表示文本文件），每项 {para_id,type,text}")
@click.option("--text", default=None, help="纯文本：首段作 slugline，其余按 action block 回传")
@click.option("--budget", type=int, default=None, help="token 预算上限（超限拒绝）")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_scene_propose(
    ctx: click.Context,
    project_id: str,
    scene_id: str,
    blocks_file: str | None,
    text: str | None,
    budget: int | None,
    json_output: bool,
) -> None:
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
    }
    result = session.request(
        "POST",
        f"/script/projects/{project_id}/scenes/{scene_id}/propose",
        json_body=body,
        write=True,
    )
    if not json_output:
        click.echo(ui.ok(f"场次候选已回传 {scene_id}（{result.get('status', 'candidate')}）"))
    _emit(result, json_output)


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


# ------------------------------------------------------------------------- skills


@main.group("skill")
@click.pass_context
def skill_group(ctx: click.Context) -> None:
    """创作 Skill 工坊：列表 / 创建 / 编辑 / 挂载 / 上传。"""


@skill_group.command("list")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_list(ctx: click.Context, json_output: bool) -> None:
    """List personal skills."""
    _emit(_session(ctx).request("GET", "/skills/personal"), json_output)


@skill_group.command("detail")
@click.argument("skill_id")
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def skill_detail(ctx: click.Context, skill_id: str, json_output: bool) -> None:
    """Show a personal skill's full instructions."""
    _emit(_session(ctx).request("GET", f"/skills/personal/{skill_id}"), json_output)


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


# -------------------------------------------------------------------------- cover


@main.group("cover")
@click.pass_context
def cover_group(ctx: click.Context) -> None:
    """作品封面：生成 / 查看 / 删除（需先创建包装包 generate）。"""


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
@click.option("--output-keys", default=None, help="逗号分隔的输出规格 key（默认全部）")
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
    """为作品生成封面候选（同步返回封面列表）。"""
    body: dict[str, Any] = {"image_model_id": image_model_id}
    if output_keys:
        body["output_keys"] = tuple(key.strip() for key in output_keys.split(",") if key.strip())
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
@click.option("--form", type=click.Choice(["clean", "working"]), default="clean", help="clean=出版稿 working=带批注工作稿")
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
    response = session._http.get(
        f"{session.api_root}{prefix}/projects/{project_id}/exports/{manifest_id}/download",
        cookies=session.cookies or None,
        timeout=300,
    )
    if response.status_code >= 400:
        from cli_anything.scriptnow.utils.session import _extract_detail

        raise click.ClickException(f"HTTP {response.status_code}: {_extract_detail(response)}")
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(response.content)
    click.echo(ui.ok(f"已保存到 {out}（{len(response.content)} 字节）"))


# --------------------------------------------------------------------------- runs


def _wait_for_run(session: Session, project_id: str, run_id: str, json_output: bool, *, domain: str = "novel") -> None:
    import time

    path = f"/{domain}/projects/{project_id}/runs/{run_id}"
    deadline = time.time() + 16 * 60
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
    raise click.ClickException("run did not finish within 16 minutes")
