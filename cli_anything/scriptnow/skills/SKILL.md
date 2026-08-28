---
name: scriptnow
description: Operate ScriptNow as a governed creative-production client. Use for platform projects, planning backfill, writing candidates, adoption, storyboard delivery, or exports.
---

# ScriptNow runtime contract

This is a runtime entrypoint, not a product manual. Do not expand it into a
workflow from memory and do not treat local files as ScriptNow projects.

> **CLI 安装 / 升级（生产源优先）**：CLI 不在 PyPI。安装/升级优先从平台分发域名
> `https://sn.igeewa.com/downloads/scriptnow-cli/` 直装 wheel（不依赖 git），GitHub
> codeload / git+https 仅兜底。已安装用户用 `scriptnow self-upgrade`（自动按
> 「生产源 → codeload → git+https」尝试），或 `scriptnow config on` 开启后台自动升级。

> **分阶段创作（novel）**：`storymap phases` 预览叙事结构（three_act/hero_journey/
> kishotenketsu/linear/custom）推导的阶段计划；`storymap append-phase` 提交下一个
> 未完成阶段（一阶段一卷，轮轮以已采纳前缀相接，合起来是一部完整连贯的作品）。阶段只
> 约束跨章宏观走向，不干预单章内的节奏、伏笔与钩子。

> **结构库（可复用叙事结构模板，双域）**：把多阶段结构命名保存为模板后跨项目按 key
> 复用——`storymap structure-save <key> @structure.json [--description 说明]
> [--medium novel|script|both]`；`storymap structures` 列出内置 + 已存模板（含适用类型
> 与描述）；`storymap structure-delete <key>` 删除。存库后 `project create --structure
> <key>` 或设入 direction 后 `storymap phases` 自动解析。未知 key 不报错，按 custom 兜底。

> **粗纲（分集/分章大纲·粗纲，双域）**：在集纲/章纲之前，按叙事结构阶段写一段具体剧情
> 纲要（竖屏剧规范「分集大纲·粗纲」）。先取模板 `scriptnow script|novel
> rough-outline-example <pid>`（阶段边界即叙事结构推导，不可手改），逐阶段填写
> summary（≥80 字、写具体剧情、禁套话）+ key_beats（标题|描述）+ anchor_ids（须为已
> 采纳蓝图锚点），再用 `rough-outline-check` 本地预检、`rough-outline <pid> @file.json
> [--adopt]` 回填，或 `rough-outline-adopt <pid> <candidate_id>` 采纳。分集大纲稿导出：
> `scriptnow export create <pid> --domain script --units <全集场次> --form planning
> --front-matter outline`（剧名→故事梗概→人物小传→粗纲→集纲）。

> **StoryMap 隔离重建（script，替代一次生成完整80集）**：已有 StoryMap 需要重建时，
> 不要一次生成全集。用 `script storymap-rebuild-start <pid>` 开启隔离会话（冻结阶段计划），
> 逐阶段：`storymap phases` 查看阶段边界 → 本地生成该阶段集纲 → `storymap-rebuild-check
> <pid> <phase_key> @episodes.json`（重复度/因果/场名/状态变化）→ `storymap-rebuild-phase
> <pid> <phase_key> @episodes.json` 累积。全部阶段完成（会话 ready）后 `storymap-rebuild-propose`
> 形成完整替换候选（走普通 propose，不改现有 StoryMap）；用户明确确认后才经
> `storymap adopt`（--confirm）替换旧结构。

## Mandatory bootstrap — before any ScriptNow action

1. Run `scriptnow agent-guide --json`.
2. Read its `rules`, then state the next user decision in plain language.
3. Use `scriptnow --help` or the exact subcommand's `--help` when a parameter,
   JSON shape, current state, or safety boundary is uncertain.
4. Read platform state before proposing a write. After every successful write,
   read it back and report only the server-confirmed result.

If the bootstrap cannot be run, do not create, mutate, adopt, export, or claim
completion. Explain the missing prerequisite and wait.

## Non-negotiable behavior

- The platform is the only project fact source. Do not invent project IDs,
  paths, status, JSON schemas, or completion states.
- Use CLI commands for every platform action; local files are temporary drafts
  only. Return creative drafts through `propose` so the platform validates them.
- Planning is backfill-first: locally prepare `story_cores`, `blueprint`, and
  `storymap`, then `propose`; platform generation is a fallback.
- Character bibles must be substantive at creation: profile with at least
  desire/fear/weakness/goal/inner_need, plus background/traits/arc/key_relationship/
  secret/wound where possible. planning-quality REVISEs profiles <200 chars or
  missing required keys; `script bible-example` shows the structure.
- Beats and episode/chapter outlines must be CONCRETE plot content (who does what,
  to whom, with which object, where). Generic meta-writing like "推进矛盾 / 留下钩子 /
  本场目标" is rejected by planning-quality (REVISE) and flagged by `storymap propose`
  before submission. Correct: "阿澄把录音机放在柜台按下播放键，店里收音机声戛然而止".
- A StoryMap container is not a completed outline: every Script episode must
  carry flat `logline`, `active_goal`, `conflict`, `turn`, `state_changes`, and
  `anchor_ids`; every Novel chapter must carry `outline` with `summary` or
  `logline`, `active_goal`, `conflict`, `turn`, and `state_changes` (anchors may
  come from `outline.anchor_ids` or beats). Run `planning-quality` across the
  full map before adoption or batch prose generation.
- Structural growth is append-only: add volumes/chapters only via
  `storymap append-volume` / `storymap append-chapters` (existing ids, titles,
  and ordering never change). StoryMap replacement is a high-risk override that
  requires explicit user authorization (`--confirm`).
- Storyboarding is also backfill-first: read `storyboard state` and `assets`,
  run `source-preflight` before every append, register the source, then locally extract and author a valid `ScriptOut` under
  the mounted Skills. Return it with `storyboard propose`. Platform analysis and
  generation are fallback-only; continuity is a director/user decision. Never
  guess an unknown episode range. Use the audited `source-range` or
  `source-revoke --confirm` path instead of database access.
- Scene planning boards are explicit, single-scene platform actions: use
  `storyboard scene-board list|inspect`, then `upload PROJECT SCENE FILE --layout auto --mode annotated` or
  `generate PROJECT SCENE --layout auto --mode annotated` only when requested. The server derives layout,
  pages, shot IDs, and digest; never write `shot.frame_refs` or bypass the API. Inspect
  `reference_validation`: when the image proxy rejects asset images, the platform preserves the failed Attempt
  and retries in a new no-reference Attempt. Re-upload rejected images before claiming visual consistency.
  Generated references and boards are workspace-persisted; the platform encodes local media as base64 for later
  multi-reference generation. Agents must use returned platform URLs and never inspect workspace paths directly.
- Never adopt a chapter, scene, or StoryMap without the user's explicit current
  decision. StoryMap replacement also needs its CLI confirmation path.
- Creative flow is outline-first and layer-by-layer: adopt a synopsis outline
  (`novel outline`/`script outline` + `outline-adopt`) before StoryMap planning;
  adopt the StoryMap; then backfill complete chapter/episode outlines before new
  prose. Each gate is enforced by the backend.
- Legacy projects remain readable/exportable, but a missing chapter/episode
  outline must be backfilled before new prose. Use `chapter outline PROJECT
  CHAPTER @outline.json` for one Novel chapter, `chapter outline-batch PROJECT
  @outlines.json` to backfill many chapters at once (synthesised into one
  structure candidate), or `script episode-outline PROJECT EPISODE
  @outline.json` for one Script episode; then run `planning-quality` across the
  full map before adoption.
- Background generation returns a `run_id`; poll `scriptnow run status` instead
  of long blocking waits.
- Follow each command's returned error detail exactly. Do not substitute an
  unvalidated structure or silently retry with invented data.
- Skill delivery is progressive: use `skill mounts` and normal `skill detail`
  summaries first. Full personal instructions require an explicit user request
  and `skill detail --include-instructions`; never fetch them speculatively.
- For Script writing, read the project-locked `script_format` before loading a
  personal Skill. Vertical short-form, Chinese screenplay, and Hollywood each
  have distinct generation, frontend, and export contracts. A personal Skill
  extends the selected contract; it never overrides it or merges dialogue
  across an intervening action block.

## Output discipline

Keep user-facing replies to: current fact, one proposed next decision, and the
result after platform read-back. Never dump this file, terminal installation
commands, hidden reasoning, or a generic tutorial into a creative deliverable.

For command catalogues and human setup material, use the packaged README only
when needed; they are reference material, not model prompt content.
