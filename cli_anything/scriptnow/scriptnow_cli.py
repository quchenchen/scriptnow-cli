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
import sys
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
    check_for_update,
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
            click.echo(ui.ok(f"升级完成，请重新运行 scriptnow --version 确认。"))
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


@main.command()
@click.option("--steps", is_flag=True, help="只展示完整作品向导步骤（短篇/短剧闭环）")
@click.option("--complete", is_flag=True, help="标记新手模式已完成（写入 onboarded 标记）")
@click.option("--status", is_flag=True, help="查看新手模式完成状态")
@click.option("--json", "json_output", is_flag=True)
def guide(steps: bool, complete: bool, status: bool, json_output: bool) -> None:
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

    if steps:
        guide_payload = _guide_steps()
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
        "平台是唯一事实源：项目、章节、候选、采纳、版本、导出都以 ScriptNow 平台为准。禁止在本地自行创建『类项目目录/JSON 结构』冒充平台项目，也不要绕过 CLI 直接构造 HTTP 请求。唯一的体外例外是本地缓存与资料整理（下载素材、归档参考资料、暂存草稿片段等纯本地文件）——此类文件不得自称或伪装为平台项目，正式项目一律在平台内创建。",
        "一切平台操作必须经 scriptnow 命令：创建项目、规划、回传（propose）、采纳（adopt）、生成（generate）、导出（export）。离线创作的正文只是草稿，成品必须以 propose 回传为平台候选，由平台校验格式与质量。",
        "规划三件套（story_cores / blueprint / storymap）回填优先：默认由 Agent 本地生成后 propose 回填为候选，再经 planning-quality 质量门禁后采纳。平台端 generate 仅作后备，不依赖、不鼓励——不要把平台生成当作首选路径。",
        "回传被平台拒绝时，按返回的 detail 修正格式后重传；不要自建替代结构，也不要删除平台已有项目自行重建。",
        "会话由 CLI 自动续期（refresh token 30 天）。若提示『登录状态已失效』，用已知凭据重新运行 scriptnow login，不要伪造凭据或绕开 CLI。",
        "命令与参数以 scriptnow --help / scriptnow <命令> --help 为准；不确定时先查帮助，不要臆造参数或输出格式。",
        "需要保存的标识（project_id / chapter_id / revision_id / run_id）来自命令的 --json 输出；后续命令一律引用这些 id，不要自造 id 或猜测路径。",
        "CLI 版本与 /cli 页面一致；发现行为异常先检查 scriptnow --version 是否最新。",
        "生成类命令（storymap/chapter/scene generate）默认后台执行并立即返回 run_id，禁止用 --wait 长阻塞等待（宿主工具轮候窗口有限，会超时被杀）。用 scriptnow run status <run_id> 分次轮询直到 succeeded/failed；交互式终端才可 --wait，并可用 SCRIPTNOW_WAIT_MAX_SECONDS 限制单次等待。",
        "StoryMap 修订是超级高危操作：采纳（storymap adopt）会覆盖当前结构、改变保留章节的标题/字数并影响已采纳正文。只有主编/作者本人明确授权（CLI 需 --confirm，平台需勾选知情确认）才可执行；Agent 不得代替用户采纳 storymap，也不得在未获授权时自行 propose+adopt 重构。被替换的旧结构与各章正文快照会自动归档，可在平台「结构历史」中查看与导出。",
        "报告完成必须以服务器回读为据：任何写操作（创建项目/规划/回传/采纳/生成/导出）成功 = 服务器返回了 project_id / candidate_id / revision_id / run_id，并在成功后回读平台确认落盘。没有服务器返回的 ID 与回读确认，不得向用户报告『已完成』；不得用本地文件或文字自述代替平台状态。project create 后立即回读 project list 核对项目存在。",
    ],
    "quickstart": [
        "scriptnow login --host https://sn.igeewa.com --email <邮箱> --password <密码>",
        "scriptnow project create --name <作品名> --medium novel|script --premise <前提> --genre <类型> --tone <文风> --chapter-target-words 1200",
        "scriptnow novel propose cores @cores.json --adopt && scriptnow novel propose blueprint @blueprint.json --adopt && scriptnow novel propose storymap @storymap.json",
        "scriptnow chapter generate <pid> chapter-1-1（后台，run status 轮询） → 审读 → scriptnow chapter adopt <pid> <cid> <revision_id>",
        "新增卷/章（纯追加，不动已有卷章）：scriptnow storymap append-volume <pid> @volumes.json --adopt | scriptnow storymap append-chapters <pid> <volume_id> @chapters.json --adopt",
        "scriptnow export create <pid> --units chapter-1-1",
    ],
    "format_hint": "剧本正文 blocks 类型：slugline|action|character|dialogue|transition；小说正文 blocks 类型：heading|prose|dialogue|quote|divider。propose 前可用 --help-format 查看精确 JSON 规格。",
}


@main.command("agent-guide")
@click.option("--json", "json_output", is_flag=True)
def agent_guide(json_output: bool) -> None:
    """Agent 操作契约：连接 ScriptNow 平台前必读（禁止本地自建项目、一律走 CLI）。"""
    _emit(_AGENT_CONTRACT, json_output)
    if not json_output:
        click.echo(ui.section(f"=== {_AGENT_CONTRACT['title']} ==="), err=True)
        click.echo(ui.paint(_AGENT_CONTRACT["audience"], ui.GOLD), err=True)
        for idx, rule in enumerate(_AGENT_CONTRACT["rules"], 1):
            click.echo(ui.ok(f"{idx}. {rule}"), err=True)
        click.echo(ui.section("常用命令速查"), err=True)
        for command in _AGENT_CONTRACT["quickstart"]:
            click.echo(ui.kv("", command), err=True)
        click.echo(ui.dim(_AGENT_CONTRACT["format_hint"]), err=True)


_GUIDE_STEPS = [
    {
        "step": 1,
        "title": "登录平台",
        "scene": "推开工作室的门。这里存放着你所有的作品与灵感，先落下你的名字。",
        "why": "建立安全会话（cookie+CSRF），之后所有创作命令自动携带身份。",
        "command": "scriptnow login --host https://sn.igeewa.com --email <邮箱> --password <密码>",
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
        "why": "一部作品 = 一个项目；先定体裁（小说/剧本）与故事前提，作为后续一切的锚点。",
        "command": (
            "scriptnow project create --name <作品名> --medium novel --premise <一句话前提> "
            "--genre <类型> --tone <文风> --chapter-target-words 1200"
        ),
        "verify": "返回 project_id；保存它（下文用 <pid> 代替）。",
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
        "why": "故事核心（cores）→ 蓝图（blueprint）→ 卷章结构（storymap）。先想清楚再动笔，是编辑的基本功。",
        "command": (
            "scriptnow novel propose cores @cores.json --adopt && "
            "scriptnow novel propose blueprint @blueprint.json --adopt && "
            "scriptnow novel propose storymap @storymap.json（或 novel orchestrate --accept 采纳）"
        ),
        "verify": "story_map 已采纳，book 计划可打印。",
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
        "why": "orchestrate 把候选结构摊开给你裁决：接受、调整、或让 Agent 重写——采纳前一切可改。",
        "command": "scriptnow novel orchestrate <pid> --accept",
        "verify": "输出全书创作计划（各章状态 needs_generation）。",
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
        "title": "逐章共创正文",
        "scene": "真正的共创时刻：Agent 递来一叠手稿，你逐页批注、润色、定稿。每一个字都有你的温度。",
        "why": "Agent 逐章创作回填（chapter propose）或平台生成（chapter generate），你逐章审读采纳——这是人机共创的核心循环。",
        "command": (
            "scriptnow book <pid>（看计划）→ chapter show <pid> <cid> --plain（读文本）→ "
            "chapter generate <pid> <cid> --feedback ...（或 chapter propose --file @blocks.json 回填）→ "
            "chapter adopt <pid> <cid> <revision_id>"
        ),
        "verify": "每一章都有 adopted 版本。",
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
        "step": 7,
        "title": "审读与修订",
        "scene": "编辑的责任：不放过一处瑕疵。逐句逐帧以挑剔受众的目光审读——每一句是否值得停留，每一帧是否推动情绪。",
        "why": "Agent 审读必须严苛：化身资深编剧与挑剔受众，逐句引用证据、点名失败的节拍，拒绝泛泛而谈的称赞；低于标准的正文立即带反馈重新生成。",
        "command": "scriptnow chapter show <pid> <cid> --plain（通读全文后裁决；不满意即 chapter generate --feedback 迭代）",
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
        "step": 8,
        "title": "包装与导出交付",
        "scene": "杀青时刻：封面落定、包装成册、导出成品——手稿终于成为可以面世的作品。",
        "why": "封面、作品包装、导出格式——从手稿到可发布成品的一站式收尾。",
        "command": (
            "scriptnow cover package <pid> && scriptnow cover generate <pid> --image-model-id <生图模型> && "
            "scriptnow export options <pid> && scriptnow export create <pid>"
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
        "step": 9,
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


def _guide_steps() -> dict[str, object]:
    return {
        "guide": "complete-works-onboarding",
        "title": "从零到一部完整作品（短篇/短剧闭环）",
        "mode": "agent-led",
        "steps": _GUIDE_STEPS,
    }


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
        if not _onboarding_done():
            click.echo(
                ui.warn("首次使用？运行 scriptnow guide 进入新手模式——Agent 将带你完成一部完整作品。"),
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
        click.echo(ui.ok(f"Skill {skill_name} 已更新（digest {result.get('digest')}）"))
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
    This is the review primitive: an agent reads the FULL text here and forms its
    own judgment — as a demanding audience member and a working screenwriter,
    never skimming and never self-congratulating. Quote evidence for every
    verdict; fix weak lines via `chapter generate --feedback` before adopting.
    """
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
    revision_summary = [
        {
            "revision_id": doc.get("id"),
            "revision_number": doc.get("revision_number"),
            "status": doc.get("status"),
            "source": doc.get("source"),
        }
        for doc in sorted(docs, key=lambda item: item.get("revision_number", 0))
    ]
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
        click.echo(ui.ok(f"章节候选已回传 {chapter_id}（{result.get('status', 'candidate')}）"))
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
    供 Agent 决定逐章创作顺序与审读反馈。非 --json 模式同时侦测项目的 Skill 支撑：
    缺方法论 Skill 时提示先创建（interpret local 一书一 Skill 或 skill create）再创作。

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
    # 编排前置侦测：项目是否已有方法论 Skill 支撑（仅人读模式，--json 契约不变）
    if not json_output:
        mounted = _session(ctx).request("GET", f"/projects/{project_id}/skills")
        names = [str(item.get("name") or "") for item in mounted] if isinstance(mounted, list) else []
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
        click.echo(ui.ok(f"梗概大纲已回填（v{result.get('version')}，{result.get('status')}）——请用户审阅后采纳："))
        click.echo(ui.dim("  采纳：scriptnow novel outline-adopt <pid>；storymap 规划前必须采纳。"), err=True)
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
        click.echo(ui.warn('尚无梗概大纲——novel outline <pid> --text "≤500 字梗概"'), err=True)
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
        click.echo(ui.ok(f"梗概大纲已采纳（v{result.get('version')}）——可开始 storymap 规划"))
    _emit(result, json_output)


@novel_group.command("ready-check")
@click.argument("project_id", required=False)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def novel_ready_check(ctx: click.Context, project_id: str | None, json_output: bool) -> None:
    """逐章写作前置完整性检查（强制 gate）：direction / cores / blueprint / 梗概大纲 / storymap / skill。"""
    pid = _resolve_project_id(ctx, project_id)
    session = _session(ctx)
    state = session.request("GET", f"/novel/projects/{pid}/state")
    direction = state.get("blueprint") is not None and bool(state.get("creation_settings"))
    checks = []
    direction_ok = bool((state.get("creation_settings") or {}).get("chapter_target_words"))
    checks.append(("创作方向（direction）", direction_ok, "project direction --apply @direction.json"))
    cores = [c for c in (state.get("story_cores") or []) if c.get("status") in ("adopted", "active")]
    checks.append(("故事核心（adopted core）", bool(cores), "novel propose cores @file --adopt"))
    checks.append(("蓝图（blueprint）", state.get("blueprint") is not None, "novel propose blueprint @file --adopt"))
    outline = _api_request(ctx, "GET", f"/novel/projects/{pid}/synopsis-outline")
    checks.append(("梗概大纲（adopted outline）", bool(outline and outline.get("status") == "adopted"), 'novel outline <pid> --text "…" → outline-adopt'))
    sm = state.get("story_map") or {}
    checks.append(("StoryMap", bool(sm.get("volumes")), "novel propose storymap @file 或 storymap generate --wait"))
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
    click.echo(ui.ok(f"就绪：{sum(1 for c in checks if c[1])}/{len(checks)} 项" if all_ok else ui.error(f"阻塞：{sum(1 for c in checks if not c[1])} 项缺失——先补齐再逐章写作")), err=True)



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
            f"/novel/projects/{project_id}/story-map/{final_candidate['id']}/adopt?confirm=true",
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
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def scene_adopt(ctx: click.Context, project_id: str, scene_id: str, revision_id: str, json_output: bool) -> None:
    """Adopt a scene revision (alias of script adopt-scene)."""
    script_adopt_scene.callback(project_id, scene_id, revision_id, json_output)


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


@script_group.command("ready-check")
@click.argument("project_id", required=False)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def script_ready_check(ctx: click.Context, project_id: str | None, json_output: bool) -> None:
    """剧本逐场写作前置完整性检查（强制 gate）：direction / cores / blueprint / storymap / skill。"""
    pid = _resolve_project_id(ctx, project_id)
    session = _session(ctx)
    state = session.request("GET", f"/script/projects/{pid}/state")
    checks = [
        ("创作方向（direction）", bool(state.get("story_cores") or state.get("blueprint")), "project direction --apply @direction.json"),
        ("故事核心（adopted core）", bool([c for c in (state.get("story_cores") or []) if c.get("status") in ("adopted", "active")]), "script propose cores @file --adopt"),
        ("蓝图（blueprint）", state.get("blueprint") is not None, "script propose blueprint @file --adopt"),
        ("StoryMap", bool((state.get("story_map") or {}).get("episodes")), "script propose storymap @file 或 script storymap --wait"),
    ]
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
    click.echo(ui.ok(f"就绪：{sum(1 for c in checks if c[1])}/{len(checks)} 项" if all_ok else ui.error(f"阻塞：{sum(1 for c in checks if not c[1])} 项缺失")), err=True)




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
        click.echo(ui.ok(f"场次候选已回传 {scene_id}（{result.get('status', 'candidate')}）"))
        click.echo(
            ui.dim(
                "下一步：采纳 scriptnow script adopt-scene <pid> <scene_id> <revision_id>；"
                "审读 scriptnow script scene-show <pid> <scene_id>"
            ),
            err=True,
        )
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
            click.echo(ui.error(f"失败 {len(failed)}/{len(ids)}：{', '.join(str(i['scene_id']) for i in failed)}"), err=True)
        else:
            click.echo(ui.ok(f"全部成功：{len(ids)} 个场次"))
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
        click.echo(ui.section(f"=== {scene_id} · rev{chosen.get('revision_number')}（{chosen.get('source')}）==="), err=True)
        for item in checks:
            mark = ui.ok("") if item["ok"] else ui.warn("")
            click.echo(f"  {mark} {item['check']}：{item['value']}（目标 {item['target']}）{item['flag']}", err=True)
        passed = sum(1 for item in checks if item["ok"])
        overall = "GOOD" if passed == len(checks) else ("NEEDS WORK" if passed >= 1 else "POOR")
        click.echo(ui.dim(f"Overall: {overall}（{passed}/{len(checks)} 项达标）"), err=True)
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
    import os as _os

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
    click.echo(ui.ok(f"默认项目已设为 {project_id}"))


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
            f"  {mark} {r['scene_id']} rev{r['revision']} {r['chars']}字符 {r['rounds']}轮"
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
    click.echo(ui.section(f"=== {scene_id}：rev{before.get('revision_number')} → rev{after.get('revision_number')} ==="), err=True)
    click.echo(f"  字符：{a['chars']} → {b['chars']}（{'+' if delta['chars'] >= 0 else ''}{delta['chars']}，{'+' if delta['chars_pct'] >= 0 else ''}{delta['chars_pct']}%）", err=True)
    click.echo(f"  块：{a['blocks']} → {b['blocks']}（{'+' if delta['blocks'] >= 0 else ''}{delta['blocks']}）", err=True)
    click.echo(f"  对白轮：{min(a['characters'], a['dialogues'])} → {min(b['characters'], b['dialogues'])}（{'+' if delta['dialogue_rounds'] >= 0 else ''}{delta['dialogue_rounds']}）", err=True)
    click.echo(f"  slugline：{a['sluglines']} → {b['sluglines']} | transition：{a['transitions']} → {b['transitions']}", err=True)


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
        click.echo(ui.ok(f"方法论成长分析已启动：run {result.get('id')}（{result.get('status')}）"))
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
        click.echo(ui.ok(f"作品包装包已生成：{result.get('title')}（v{result.get('version')}）"))
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
            click.echo(ui.warn("该项目尚未生成作品包装包 —— 先运行 cover package <pid> 生成后再生图。"), err=True)
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


@export_group.command("zip")
@click.argument("project_id")
@click.option("--domain", type=click.Choice(["novel", "script"]), default="novel")
@click.option("--units", required=True, help="逗号分隔的章节/场次 id（用 export options 或 chapter/scene list 查看）")
@click.option("--form", type=click.Choice(["clean", "working"]), default="clean", help="clean=出版稿 working=带批注工作稿")
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
    response = session._http.post(
        f"{session.api_root}{prefix}/projects/{project_id}/exports/zip",
        json=body,
        headers={"X-CSRF-Token": session.csrf} if session.csrf else {},
        cookies=session.cookies or None,
        timeout=600,
    )
    if response.status_code >= 400:
        from cli_anything.scriptnow.utils.session import _extract_detail

        raise click.ClickException(f"HTTP {response.status_code}: {_extract_detail(response)}")
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
