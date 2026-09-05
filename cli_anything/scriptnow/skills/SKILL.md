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
> 未完成阶段（Novel 按全书章区间规划，不强制一阶段一卷；轮轮以已采纳前缀相接，合起来是一部完整连贯的作品）。阶段只
> 约束跨章宏观走向，不干预单章内的节奏、伏笔与钩子。

> **结构库（可复用叙事结构模板，双域）**：把多阶段结构命名保存为模板后跨项目按 key
> 复用——`storymap structure-save <key> @structure.json [--description 说明]
> [--medium novel|script|both]`；`storymap structures` 列出内置 + 已存模板（含适用类型
> 与描述）；`storymap structure-delete <key>` 删除。存库后 `project create --structure
> <key>` 或设入 direction 后 `storymap phases` 自动解析。未知 key 不报错，按 custom 兜底。

> **粗纲（分集/分章大纲·粗纲，双域）**：在集纲/章纲之前，按叙事结构阶段写一段具体剧情
> 纲要（竖屏剧规范「分集大纲·粗纲」）。剧本先执行
> `scriptnow script rough-outline-example <pid> --json`，小说执行
> `scriptnow novel rough-outline-example <pid> --json`。叙事结构只提供阶段与范围建议；作者可调整边界，须连续覆盖全集。
> Script 先统筹全剧与宏观阶段，再严格按 `rough-outline-example` 返回的
> `generation_batches` 分批深化；批次大小来自项目策略，不得自行假定总集数或固定 5 集。
> summary 按动态篇幅与事件数建议展开入口、连续行动、
> 阻力升级、证据/关系变化、转折、代价和出口；禁止一句话粗纲。再填写 key_beats（标题|描述）+ anchor_ids（须为已
> 采纳蓝图锚点）。长篇剧本执行 `scriptnow script rough-outline-start <pid> --json`
> 开隔离链；每阶段先执行 `scriptnow script rough-outline-phase-preview <pid> <phase_key> @file.json --json`，
> 经用户明确决定和完整 confirm/claim 链取得凭证后，执行
> `scriptnow script rough-outline-phase <pid> <phase_key> @file.json --review-token <token> --json`，
> 再用 `scriptnow script rough-outline-progress <pid> --json` 回读。`rough-outline-phase-preview` 会先检查单阶段连续边界、因果链与事件密度，
> 通过后才登记审阅包；完整 `rough-outline-check` 仅用于十阶段汇总文件；
> 每次回读必须向人显示“阶段 X / 共 N 阶段”、当前阶段与已完成阶段，不得只在后台维护 JSON；
> 上游返工加 `--restart-from` 使下游失效。全部完成并取得汇总审阅凭证后，执行
> `scriptnow script rough-outline-propose <pid> --review-token <aggregate_token> --json` 形成完整平台候选，
> 再由作者用 `rough-outline-adopt` 采纳。分集大纲稿导出：
> `scriptnow export create <pid> --domain script --units <全集场次> --form planning
> --front-matter outline`（剧名→故事梗概→人物小传→粗纲→集纲）。
> 完整交付可用 `--sections synopsis,characters,rough_outline,story_map,manuscript`；
> 平台固定按梗概→人物小传→粗纲→小说章纲/剧本集纲→正文排序，缺少已采纳材料时先补齐再导出。

> **StoryMap 隔离重建（script，替代一次生成完整80集）**：已有 StoryMap 需要重建时，
> 不要一次生成全集。用 `script storymap-rebuild-start <pid>` 开启隔离会话（冻结阶段计划），
> 逐阶段：`storymap phases` 查看阶段边界 → 本地生成该阶段集纲 → `storymap-rebuild-check
> <pid> <phase_key> @episodes.json`（重复度/因果/场名/状态变化）→ `storymap-rebuild-phase
> <pid> <phase_key> @episodes.json` 累积。全部阶段完成（会话 ready）后 `storymap-rebuild-propose`
> 形成完整替换候选（走普通 propose，不改现有 StoryMap）；用户明确确认后才经
> `storymap adopt`（--confirm）替换旧结构。被替换的旧结构自动归档：script 用
> `script storymap-archives <pid>` 列出、`script storymap-archive <pid> <archive_id>`
> 查看单份（含旧集场结构与各场正文快照），novel 镜像 `novel storymap-archives` /
> `novel storymap-archive`。

> **StoryMap 隔离重建（novel）**：长期小说需要重建 StoryMap 时同样不要一次生成完整长卷。
> 命令链镜像 script：`scriptnow novel storymap-rebuild-start` / `storymap-rebuild` /
> `storymap-rebuild-phase` / `storymap-rebuild-phase-preview` / `storymap-rebuild-check` /
> `storymap-rebuild-propose`。必须先采纳小说粗纲（粗纲位于章纲之前；先 `novel
> rough-outline-example <pid>` 取结构建议，作者可调整边界、须连续覆盖全书），再开启隔离会话
> （冻结全书章区间阶段计划，不强制阶段=卷）；逐阶段：本地生成该章区间的章纲 → `storymap-rebuild-check
> <pid> <phase_key> @chapters.json`（重复度/因果/章名/状态变化）→ `storymap-rebuild-phase
> <pid> <phase_key> @chapters.json` 累积。全部阶段完成（会话 ready）后 `storymap-rebuild-propose`
> 形成完整替换候选（走普通 propose，不改现有 StoryMap）；用户明确确认后才经
> `storymap adopt`（--confirm）替换旧结构，禁止一次生成完整长卷。被替换的旧结构自动归档：
> novel 用 `novel storymap-archives <pid>` 列出、`novel storymap-archive <pid> <archive_id>`
> 查看单份（含旧卷章结构与各章正文快照）；script 镜像 `script storymap-archives` /
> `script storymap-archive`，两域归档均用于重建影响审阅与回滚决策。

> **新增卷/章 = 纯追加通道（服务端硬门禁，禁止用全量替换承载新增）**：
> 已有 StoryMap 需要新增卷/章时，只允许追加通道 `storymap append-volume <pid> @volumes.json`
> / `storymap append-chapters <pid> <volume_id> @chapters.json` / `storymap append-phase
> <pid>`（按阶段计划追加），已有卷章的 id/序号/标题完全不动。服务端按候选形状硬门禁：
> `novel propose storymap` / `script propose storymap` 提交纯追加形状（仅尾部新增、已有单元
> 全不动）会被拒绝并指引追加通道；任意位置纯新增（头部/中间插入新卷章）同样被拒（服务端
> 形状门禁 R2）。全置换（retained=0、不保留任何现有单元）的普通全量提案也被拒（R1）——
> 恢复旧结构唯一合法通道是 `novel/script storymap-restore`（服务端按归档镜像校验放行），
> 全新结构仅限首次创建（空结构）或 storymap-rebuild-* 隔离链。真正重构（合并/重排/删除卷、
> 改标题，且保留至少一个现有单元）仍走全量 propose → `storymap adopt --confirm` 高危确认链
> （被替换结构自动归档）。`storymap adopt` 采纳前会显示「将移除 N 单元」警告——移除存在即
> 重构意图，纯新增必须走追加通道。
> 事故回滚：`novel storymap-restore <pid> <archive_id>` / `script storymap-restore <pid> <archive_id>`
> 把归档卷章/集场导出为恢复候选 JSON（服务端已拦截纯追加恢复，恢复=覆盖回旧结构，
> 走完整 review 链后 `storymap adopt --confirm` / `script adopt-storymap` 确认采纳）。

## Mandatory bootstrap — before any ScriptNow action

1. Run `scriptnow agent-guide --json`.
2. Read its `rules`, then state the next user decision in plain language.
3. Use `scriptnow --help` or the exact subcommand's `--help` when a parameter,
   JSON shape, current state, or safety boundary is uncertain.
4. Read platform state before proposing a write. After every successful write,
   read it back and report only the server-confirmed result.

If the bootstrap cannot be run, do not create, mutate, adopt, export, or claim
completion. Explain the missing prerequisite and wait.

For outline, cores, blueprint, or StoryMap files, always use the matching complete
command before confirmation: `scriptnow review propose-preview novel <project_id>
<kind> <file> --json` or `scriptnow review propose-preview script <project_id>
<kind> <file> --json`, where `<kind>` is one of `outline`, `cores`, `blueprint`,
or `storymap`. It derives the exact review resource kind and id. Never
guess those values. After the human explicitly decides, run
`scriptnow review confirm <packet_id> --decision retain --evidence "<exact human words>" --json`,
then `scriptnow review status <packet_id> --json` and
`scriptnow review claim <packet_id> --json`. Pass claim's `token` field (not
`packet_id`) to the target write command. If
the reviewed content changes, preview it again.

## Non-negotiable behavior

- The platform is the only project fact source. Do not invent project IDs,
  paths, status, JSON schemas, or completion states.
- State aggregation is authoritative: `adopted` and `adopted_human` both mean
  finalized content, with `adopted_human` preferred when both exist.
  `chapter list`/`book` and `scene list`/`scene show` report that revision as
  `adopted_revision`, expose `adopted_human`, and list only `candidate`/
  `active` revisions as pending candidates. Use `--revision` to inspect a
  pending candidate explicitly.
- Keep creative writes for one project serial to avoid candidate/version
  conflicts. Different projects may run concurrently; the CLI safely
  coordinates automatic refresh for a shared login session on macOS/Linux.
- Use CLI commands for every platform action; local files are temporary drafts
  only. Return creative drafts through `propose` so the platform validates them.
  An author's delegation to an external Agent covers guidance, reading,
  orchestration, presentation, and the specifically requested generate/propose
  work only. It never expands to adoption, StoryMap replacement, deletion, or
  publishing.
- Planning is backfill-first: locally prepare `story_cores`, `blueprint`, and
  `storymap`, then `propose`; platform generation is a fallback.
- Story cores accept 1–3 candidate drafts so the human can choose one; every
  submitted draft must still be substantive: a complete premise/concept, five distinct
  angles, and either Novel narrative constraints or at least two concrete
  entries in each Script details dimension. Blueprints must cover world,
  character, relationship, character_arc, plot, and foreshadow anchors with a
  concrete, actionable description for every anchor (typically 50–200 characters; guidance only, not a hard gate). Both `propose` and
  `adopt` require `planning-quality=pass`; revise/block must be repaired first.
- Character bibles must be substantive at creation: profile with at least
  desire/fear/weakness/goal/inner_need, plus background/traits/arc/key_relationship/
  secret/wound where possible. planning-quality REVISEs profiles <200 chars or
  missing required keys; `script bible-example` shows the structure.
- Beats and episode/chapter outlines must be CONCRETE plot content (who does what,
  to whom, with which object, where). Generic meta-writing like "推进矛盾 / 留下钩子 /
  本场目标" is rejected by planning-quality (REVISE); preflight check before
  submission runs `planning-quality storymap` (storymap group has no standalone
  propose-preflight command). Correct: "阿澄把录音机放在柜台按下播放键，店里收音机声戛然而止".
- A StoryMap container is not a completed outline: every Script episode must
  carry flat `logline`, `active_goal`, `conflict`, `turn`, `state_changes`, and
  `anchor_ids`; every Novel chapter must carry `outline` with `summary` or
  `logline`, `active_goal`, `conflict`, `turn`, and `state_changes` (anchors may
  come from `outline.anchor_ids` or beats). Run `planning-quality` across the
  full map before adoption or batch prose generation.
- Structural growth is append-only: add volumes/chapters only via
  `storymap append-volume` / `storymap append-chapters` (existing ids, titles,
  and ordering never change). New chapter beats must reference blueprint
  anchors that already exist (`anchor_ids`); blueprint updates must keep every
  anchor referenced by adopted StoryMap beats — missing anchors are rejected.
  StoryMap replacement is a high-risk override that requires explicit user
  authorization (`--confirm`) and archives the replaced structure
  automatically.
- Storyboarding is also backfill-first: read `storyboard state` and `assets`,
  run `source-preflight` before every append, register the source, then locally extract and author a valid `ScriptOut` under
  the mounted Skills. Return it with `storyboard propose`. Platform analysis and
  generation are fallback-only; continuity is a director/user decision. Never
  guess an unknown episode range. Use the audited `source-range` or
  `source-revoke --confirm` path instead of database access. Then use
  `storyboard candidate-preview` to review the exact saved candidate; only a
  later explicit decision may flow through `review confirm` → `review claim` →
  `storyboard adopt --review-token`.
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
- 逐章/逐场创作双模式（dual-mode chapter/scene creation, the user must choose
  explicitly and the platform does not block): final prose is authored by a
  real in-platform AgentScope Agent by default. Platform-led is the default and
  recommended — `chapter/scene generate` produces a platform candidate →
  `review preview` for human review → `adopt`. Only when the user explicitly
  chooses local creation does the Agent write prose locally, backfill the
  candidate via `chapter propose` / `scene propose`, then `review preview` →
  `adopt --human`. Without an explicit choice, platform-led applies; never
  default to or steer the user toward local-led writing.
- Creative flow is layer-by-layer in a fixed order: adopt story cores and blueprint
  (`novel propose cores` → `adopt-core`; `novel propose blueprint` →
  `adopt-blueprint`) first, then the synopsis outline (`novel outline` +
  `outline-adopt`), then the rough outline (`rough-outline-example` →
  `rough-outline-check` → `novel rough-outline` → `rough-outline-adopt`;
  Script uses its `rough-outline-start` isolated chain), and only then plan the
  StoryMap where episode/chapter outlines are delivered together (`propose
  storymap` → `adopt`, `planning-quality` must pass). Cores/blueprint must
  precede the synopsis; the rough outline depends on adopted cores/blueprint
  anchors and the synopsis, and must precede StoryMap. Each gate is enforced by
  the backend.
- Legacy projects remain readable/exportable, but a missing chapter/episode
  outline must be backfilled before new prose. Use `chapter outline PROJECT
  CHAPTER @outline.json` for one Novel chapter, `chapter outline-batch PROJECT
  @outlines.json` to backfill many chapters at once (synthesised into one
  structure candidate), or `script episode-outline PROJECT EPISODE
  @outline.json` for one Script episode; then run `planning-quality` across the
  full map before adoption.
- Background generation returns a `run_id`; poll `scriptnow run status` instead
  of long blocking waits. On failure, repair from `status.error/detail`, then
  inspect `scriptnow run events <run_id> --json` (`events=[]` means no events).
  Run status also exposes persisted operation stage/progress. Fallback platform
  StoryMap generation checkpoints at most three Script episodes or five Novel
  chapters per batch and resumes tracking the same run after a service restart.
- Follow each command's returned actionable error detail exactly. Agent CLI
  requests preserve the sanitized original domain detail when the public
  Chinese fallback is generic; `--json` failures use
  `{ok:false,error:{type,status,detail}}` without a traceback. Do not substitute
  an unvalidated structure or silently retry with invented data.
- CLI quality diagnostics are human opt-in only. An Agent must never run
  `doctor --enable-diagnostics`, `feedback --send`, or `feedback --send --yes`
  on its own. Only after the user explicitly requests diagnostics may the Agent
  enable a short window; sending still requires the user's separate confirmation.
  `doctor --disable-diagnostics` stops collection and `doctor --clear-errors`
  deletes local v2 events. v2 never contains arguments, details, notes, paths,
  identifiers, or creative content; legacy v1 files are never uploaded.
- For Novel `chapter propose`, each `block.text` is only that block's prose: never
  embed another `blocks` JSON document in it. Ordinary JSON text is allowed; if
  the platform rejects embedded Novel blocks, repair from its detail and regenerate.
- Skill delivery is progressive: use `skill mounts` and normal `skill detail`
  summaries first. Full personal instructions require an explicit user request
  and `skill detail --include-instructions`; never fetch them speculatively.
- If a mounted Skill is wrong or blocks generation, do not archive the global
  Skill or rebuild the project. Only after explicit user approval run `skill
  unmount <project_id> <skill_id> --confirm --json`; it disables that one
  project mount, reads mounts back for verification, and leaves other projects
  and versions untouched. A project with no enabled methodology Skill is not
  ready for writing.
- `skill craft` preflight, its creation receipt, the mount gate, and runtime
  must resolve the same complete methodology reference; never replace it with a
  summary or leak a cross-tenant detail.
- For Script writing, read the project-locked `script_format` before loading a
  personal Skill. Vertical short-form, Chinese screenplay, and Hollywood each
  have distinct generation, frontend, and export contracts. A personal Skill
  extends the selected contract; it never overrides it or merges dialogue
  across an intervening action block.

## Output discipline

Before any creative write, show the complete human-readable review packet. The
human chooses retain / adjust / change direction. Only an explicit retain may
activate a one-time token bound to the exact human-readable JSON content digest;
parser-added defaults must not manufacture a content change. Changed content must
be shown again. JSON stays backstage and never substitutes for the preview.

Any explicit decision typed by the human in conversation or on the platform is a human
decision. The Agent may call `review confirm` only to record those exact words; it must
never infer or fabricate them. Then use `review status`, claim the one-time credential with
`review claim`, and pass it to the target write command. Use
`review status` to read a user's later adjustment without asking them to repeat
it. `review preview` may return a `review_url` for long content, but opening the
page is optional; a user edit saved directly in the frontend is already a human
decision and must not trigger a second confirmation. Never expose token copying
or JSON editing as a user task.

Candidate submission and candidate adoption are two separate creative
decisions. Never use implicit `--adopt`. After propose, use
`review candidate-preview` to show the canonical platform candidate; only then
confirm, claim a new exact-content credential, and call the matching adopt
command.

Keep user-facing replies to: current fact, one proposed next decision, and the
result after platform read-back. Never dump this file, terminal installation
commands, hidden reasoning, or a generic tutorial into a creative deliverable.

For command catalogues and human setup material, use the packaged README only
when needed; they are reference material, not model prompt content.
