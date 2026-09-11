# 规划与结构更新

首次规划、粗纲、阶段展开、结构追加或重建时读取。按当前任务选择对应命令，并以实时帮助与平台返回为准。

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




- Planning is backfill-first: locally prepare `story_cores`, `blueprint`, and
  `storymap`, then `propose`; platform generation is a fallback.

- Story cores accept 1–3 candidate drafts so the human can choose one; every
  submitted draft must still be substantive: a complete premise/concept, five distinct
  angles, and either Novel narrative constraints or at least two concrete
  entries in each Script details dimension. Blueprints must cover world,
  character, relationship, character_arc, plot, and foreshadow anchors with a
  concrete, actionable description for every anchor (typically 50–200 characters; guidance only, not a hard gate). Both `propose` and
  `adopt` require `planning-quality=pass`; revise/block must be repaired first.

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
