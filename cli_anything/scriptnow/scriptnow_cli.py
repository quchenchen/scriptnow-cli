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
                click.echo(f"{key}: {_human(item)}")
            return
        click.echo(_human(value))


def _human(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option("--base-url", envvar="SCRIPTNOW_BASE_URL", help="Platform base URL (e.g. https://sn.igeewa.com)")
@click.option("--email", envvar="SCRIPTNOW_EMAIL", help="Login email")
@click.option("--password", envvar="SCRIPTNOW_PASSWORD", help="Login password")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON")
@click.version_option(VERSION, prog_name="scriptnow")
@click.pass_context
def main(ctx: click.Context, base_url: str | None, email: str | None, password: str | None, json_output: bool) -> None:
    """ScriptNow 创作 CLI —— 从灵感到成书交付的一站式命令行。

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
    更多：每个子命令 -h 查看；所有命令支持 --json 输出结构化结果。
    """
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = base_url
    ctx.obj["email"] = email
    ctx.obj["password"] = password
    ctx.obj["json"] = json_output


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

    推荐流程（客户端 Agent 梳理 → 回填）：
      1. 客户端 Agent 先了解创作要求，梳理出完整方向（premise/tone/
         world_setting/genre/structure/volume/字数 等）。
      2. 用 --apply 一次写入：
         scriptnow project direction <pid> --apply '{"premise":"...","tone":"...",...}'
         或 --apply @direction.json（从文件读）。
    备选：
      --inspire：交给平台 AI 根据一句话种子生成方向。
      --set key=value：手动补齐单个字段。
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
        direction["premise"] = str(insp.get("premise") or "").strip()
        direction["tone"] = str(insp.get("tone") or "").strip()
        direction["world_setting"] = str(insp.get("world_setting") or "").strip()
        suggested = [str(g).strip() for g in (insp.get("genre_suggestions") or []) if str(g).strip()]
        if suggested:
            direction["genre"] = ", ".join(suggested[:4])
        if not json_output:
            click.echo(
                f"灵感已生成：{insp.get('title')}（模型 {insp.get('model_key')}）", err=True
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
    """Generate story core candidates (novel)."""
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
    """Generate a blueprint candidate (novel)."""
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
    """Generate story core candidates (script)."""
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


@script_group.command("blueprint")
@click.argument("project_id")
@click.option("--feedback", default=None)
@click.option("--wait", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_blueprint(
    ctx: click.Context, project_id: str, feedback: str | None, wait: bool, json_output: bool
) -> None:
    """Generate a blueprint candidate (script)."""
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
    """Generate a script StoryMap (episodes -> scenes) candidate."""
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
    click.echo(f"已保存到 {out}（{len(response.content)} 字节）")


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
                click.echo(f"run {run_id}: {status}", err=True)
            last = status
        time.sleep(2)
    raise click.ClickException("run did not finish within 16 minutes")
