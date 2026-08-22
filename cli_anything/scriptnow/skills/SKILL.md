---
name: scriptnow-cli
description: >-
  Command-line interface for the ScriptNow creative platform.
  Manages projects, work interpretation (one-work-one-skill read-through),
  novel and script creation chains (story cores, blueprints, StoryMap,
  chapters/scenes), cross-cultural recreation (translation), and the
  tenant skill workshop.
---

# scriptnow-cli

CLI harness for ScriptNow — built with the CLI-Anything pattern.

## Installation

```bash
pip install -e /path/to/cli/scriptnow-cli
```

## Configuration

```bash
scriptnow login --host https://sn.igeewa.com --email you@example.com --password '...'
```

The session (cookies + CSRF) is persisted at `~/.config/scriptnow-cli/session.json`.
Alternatively pass `--base-url/--email/--password` on every invocation, or set
`SCRIPTNOW_BASE_URL`, `SCRIPTNOW_EMAIL`, `SCRIPTNOW_PASSWORD`.

## Command Groups

| Group | Commands |
|-------|----------|
| project | list, create, upload, files, delete, direction (--show / --apply 客户端梳理回填 / --inspire 平台灵感 / --set 手动补齐) |
| interpret | go, create, read, status, decide |
| chapter | list, show, generate, adopt, quality (--standard content/drama-filing/thousand-plan), propose (agent-written chapter return) |
| storymap | state, generate, append-volume (新增卷·纯追加), append-chapters (新增章·纯追加), adopt (**高危，需 --confirm**) |
| agent-guide | 连接平台的 Agent 操作契约（--json 结构化）：平台是事实源、规划回填优先、生成后台轮询、StoryMap 修订需用户明确授权 |
| book | plan (全书托管创作规划，Agent 编排原语) |
| novel | story-cores, adopt-core, blueprint, adopt-blueprint, bootstrap (一键规划), propose (本地 JSON 导入: cores/blueprint/storymap/bibles, 支持 --adopt), planning-quality |
| script | state, story-cores, adopt-core, blueprint, adopt-blueprint, storymap, adopt-storymap, scene, adopt-scene, scene-list, scene-show, scene-propose (--auto-adopt/--help-format/--example), scene-batch (serial + resume), scene-quality, scene-diff, quality-report, planning-quality |
| scene | list, show, generate, adopt, propose, batch, quality, diff — 顶层组，与 chapter 组对称（script 正文命令的新命名入口；旧 `script scene-*` 命令保留为别名） |
| translate | create, analyze-source, target-contract, strategies, mappings |
| cover | package (generate the work package — required before cover generation), package-propose (agent-submitted packaging draft), package-show, models, specs, generate (defaults to a single 1024×1600 output), list, delete |
| export | options, create, download, zip (novel/script) — `zip` 下载整部作品 ZIP 包（docx+封面+manifest.json） |
| skill | list, detail, versions, create, update, archive, mounts, mount, upload; growth (workspace/start/decide/candidate/evaluate/preview/publish — methodology evolution); canary (list/decide — version rollout) |
| admin | status, tenant-status, skills, skill-show, skill-update, supply (provider/model overview), provider-connect (one-step OpenAI-compatible provider), model-add, image-model-add — administrator-only (403 otherwise); token-consumption/quota/financial commands are intentionally NOT in the CLI |
| run | status, events |
| version | 查看当前版本（--check 强制联网检查 GitHub 发布镜像是否有新版） |
| self-upgrade | 自动升级 CLI（先检查最新版本，用户确认后执行升级） |
| login | — |

## For AI Agents

- Always use `--json` for structured output; JSON output is the default for automation.
- **NEW-USER MODE (first activation / `scriptnow guide`)**: when the user is new
  (first login, or `scriptnow guide --status` shows not onboarded), run
  `scriptnow guide --json` and act as the **studio guide**, not a command
  dispatcher. Lead a complete short-work closed loop (novel ~1 volume × 3-5
  chapters, or script ~1 season × 4-6 scenes) from premise to deliverable,
  following the guide steps 1-9. Keep the co-creation atmosphere throughout:
  the user is the editor/writer in charge, you are the co-creator proposing
  candidates — every step is "提案 → 裁决 → 采纳" (propose → decide → adopt).
  Do not hand the user a wall of commands; translate each step into a short
  narrative of *what we are creating now* and run the commands yourself,
  confirming at each decision point. Only after the work is complete run
  `scriptnow guide --complete` (and keep the session in character: "工作室的门
  从此为你常开"). The immersive tone is part of the product: even inside an
  agent conversation the user should feel the creative workshop atmosphere.
- **Master's words as encouragement (new-user mode)**: each guide step carries a
  `masters` list — verified quotes from world-famous writers / screenwriters /
  directors (Hemingway, Chekhov, Kurosawa, Stephen King, Miyazaki, Wong Kar-wai,
  Lu Xun, Lao She, García Márquez, Tarkovsky…) plus warm one-line
  interpretations, and a `prompt` question that invites the user to express
  their own creative intent. The guide also carries a `gallery` of 12+ quotes
  for free use. When the user hesitates, doubts their work, or finishes a step,
  quote the matching master's words (`「...」—— 大师名`) and connect it to what
  they just did; use the `prompt` of the current step to draw out the user's
  own vision before proceeding. Treat the user with respect and warmth: they
  are the decision-maker, never a passive consumer. Encourage them to express
  their own creative intent at every decision point instead of letting the
  agent decide alone — the goal is 尊重、合作、温度、引导表达.
- **MANDATORY: read the operating contract first.** Run `scriptnow agent-guide --json`
  and follow it as the only operating rule: the platform is the single source of
  truth (never create local "project-like" structures; the only off-platform
  exception is local caching/material organization); planning trio
  (story_cores/blueprint/storymap) is backfill-first — generate locally and
  return via `propose`; generation commands run in the background — poll with
  `run status` and never block with `--wait`; StoryMap restructuring is a
  super high-risk operation that requires explicit user authorization
  (`--confirm` on adopt) — an Agent must NEVER adopt a storymap on the user's
  behalf.
- **Reported completion = server read-back (MANDATORY)**: a write operation succeeds
  only when the server returns an id (project_id / candidate_id / revision_id / run_id)
  AND a follow-up read-back confirms it landed (`project create` auto-reads-back and
  prints a receipt with `verified`). Never report "done" to the user without server-returned
  ids and read-back confirmation; local files or textual self-claims are never evidence.
- **SKILL IS A MANDATORY PRE-WRITING GATE (both domains, first priority after
  the project lands).** Once the creative intent is clear and the project exists,
  **no per-chapter/per-scene generation may start until the project has a
  robust, project-specific methodology Skill mounted on the platform**. The gate
  has three phases — plan, harden, mount — and the agent must actively GUIDE the
  user/author through every one, never shortcutting to writing:
  1. **PLAN (multi-round, co-created)**: work with the user/author to plan what
     methodology this work needs — craft rules, style anchors, character/
     continuity standards, genre conventions, evaluation dimensions. Ask
     probing questions (opening hooks, pacing, POV discipline, series
     continuity, taboo/avoid-lists, audience expectations). Refine across
     rounds until the author agrees it reflects the work's intent. Do NOT skip
     to writing because a generic Skill exists.
  2. **HARDEN for robustness (MANDATORY, the agent's active duty)**:
     - Draft the Skill, then **test-drive it**: write a short sample chapter /
       scene following the Skill (a beat from the adopted StoryMap, or a probe
       paragraph), and audit the result against the Skill's own rules.
     - **Diagnose weaknesses**: does the Skill actually constrain quality, or
       is it generic filler? Are there gaps (no continuity rule, no voice
       anchor, no scene-duration discipline for scripts)? Are instructions
       unambiguous enough that two writers would produce the same discipline?
     - **Iterate until robust**: fix gaps, tighten vague rules, add concrete
       examples/anti-examples; re-test the sample until the Skill demonstrably
       produces on-intent work. Surface each hardening round to the user and
       get their sign-off — a Skill that merely exists is not enough; it must
       be battle-tested against the work's intent.
   - **REFERENCE — a robust novel Skill (passes the gate)** — structure your
     Skill at least this concretely:
     ```
     本作品《血月契约》是悬疑言情，叙述笔调冷冽克制、以动作与物象代心理。
     一、craft：慢热递进的张力节奏，每章结尾留钩子；视角纪律——第三人称限知只跟随女主；
         对白短促有力、避免长篇独白；以动作推进叙事而非心理旁白。
     二、voice：短句冷冽、句式忌排比堆砌；用物件意象暗示情绪（灯、信、镜子）。
     三、continuity：不得违反已采纳正文的伏笔；前文确立的设定不可更改；角色性格通过动作呈现。
     四、evaluation：每章按张力/连贯/角色主动性三维自检，低于门槛即拒收重写。
     五、examples：例如「她把信折了三折，没有抬头」；避免「她很难过」；
         反例：连续三句解释性旁白应删至一句。
     ```
   - **REFERENCE — a robust script Skill (passes the gate)**:
     ```
     本剧《第101天》是都市悬疑短剧，台词风格冷硬克制、画面感优先。
     一、craft：镜头语言克制，每场 40 秒完成一个行动节拍；对白短促、避免台词化说明；
         转场用物件衔接；场次时长纪律——动作戏 30 秒、对白场 45 秒。
     二、voice：台词信息量大、潜台词优先；情绪靠表演而非旁白。
     三、continuity：跨场不丢伏笔；服装道具贯穿；角色语气一贯。
     四、evaluation：逐场审读自检，按镜头信息量/对白推动力/时长利用率三维评估，不达质量门槛即拒收重写。
     五、examples：例如以特写开场建立悬念；避免用旁白交代动机；
         反例：连续三句解释性对白应删至一句。
     ```
     Use these as the minimum bar: if your Skill is thinner than these
     examples, it will fail the gate — harden it before mounting.
  3. **MOUNT & VERIFY (MANDATORY)**: create the project-specific Skill on the
     platform and mount it, then confirm with `scriptnow skill mounts
     <project_id>` **before** the first `chapter/scene generate` or `propose`
     body-text write:
     - One-work-one-skill distillation (preferred; samples stay off-platform):
       `scriptnow interpret local <work> --spec` → read the work locally, write
       the skill JSON per the spec → harden it per phase 2 → `scriptnow
       interpret local <work> --submit @skill.json --project-id <pid>` (creates
       and mounts). For scripts set `"domain": "script"`. Novels may also use
       `interpret go` (platform read-through).
     - Direct personal-skill submission:
       `scriptnow skill create --name ... --domain novel|script --role writer
       --stage writing --instructions "..."`, then `skill mounts <pid>` for the
       version id and `skill mount <pid> <skill_id> <version_id>`.
  4. **Hard stop if not mounted**: if `scriptnow skill mounts <project_id>` shows
     **no** methodology Skill, stop and complete the gate — never start
     per-chapter writing on a bare project. The hosted plan command
     (`scriptnow book`) flags missing Skill support in human-readable mode;
     treat that flag as a hard stop for body-text work.
- **MANDATORY: fill the full project direction yourself — never rely on the
  platform to generate it.** When creating a project or setting direction, the
  agent MUST actively curate and backfill every field that matters for the work
  (premise, tone, world_setting, genre, structure, volume_one, volume_two,
  chapter_target_words, creative_variance, and constraints when known), instead
  of leaving them empty or delegating to `--inspire`. Use:
  `scriptnow project direction <pid> --apply '{"premise":"...","tone":"...",...}'`
  (or `--apply @direction.json`). Only fall back to `--inspire` when the user
  explicitly asks for platform-generated inspiration, and always review the
  result before proceeding.
- `project create` accepts the full direction flags (`--premise --tone
  --world-setting --genre --structure --volume-one --volume-two
  --chapter-target-words --creative-variance`); prefer supplying them at
  creation time over creating bare projects.
- **Dual-domain orchestration (novel vs script)**: the chains share
  project → direction → planning → writing → export, but the structure and the
  writing loop differ:
  - **Novel (volumes × chapters)**: planning via
    `novel propose cores|blueprint|storymap @file` (agent-side, backfill-first) or
    `storymap generate` (platform fallback; background, poll `run status`), then `novel orchestrate --accept` to
    review+adopt and print the plan. Writing loop: `book <pid>` (hosted plan) →
    per chapter `chapter show --plain` → judge → `chapter generate --feedback` →
    `chapter adopt`. Agent-written adaptation text returns via `chapter propose
    --file @blocks.json`.
  - **Script (episodes × scenes)**: planning via
    `script propose cores|blueprint|storymap|bibles @file` (agent-side) or the platform
    generation commands (`script story-cores --wait` → adopt → `script blueprint`
    → adopt → `script storymap` → adopt). Writing loop: `scene list` (或 `script
    scene-list`) → `scene show --plain` → judge → `scene generate --feedback` (或
    `script scene`) → `scene adopt`. Agent-written adaptation text returns via
    `scene propose --file @blocks.json` (或 `script scene-propose`; block types
    slugline|action|character|dialogue|transition).
  - Export differs only in the unit dimension: novel `--units chapter-1-1`;
    script `--units scene-1-1`. For a whole-work archive (docx + cover +
    manifest.json in one file) use `export zip <pid> --units ... -o 作品.zip`
    instead of the create→download two-step.
- **`scriptnow book <project_id>` prints the hosted creation plan** (per-chapter
  adopted / needs-generation / candidate-pending-review state). The agent drives
  the loop: read the plan, then per chapter use `chapter show --plain` to read
  the text, form its own judgment, drive fixes with `chapter generate --feedback`,
  and adopt with `chapter adopt`. Review is the agent's own judgment, not a
  platform quality gate.
- **Per-chapter/per-scene model selection**: `chapter generate --model <id>`,
  `scene generate --model <id>` (或 `script scene --model`), and
  `scene batch --model <id>` accept a model id that applies **only to that
  project's writing run** — the id flows through the project-bound run snapshot
  and is validated against the tenant's tier and the model's enabled/connected
  status. Model selection is **strictly limited to project writing**: there is
  no CLI pathway to invoke a model for non-project text generation, and the
  image model (`cover generate --image-model-id`) is likewise only usable for
  the project's cover generation after work packaging exists. Never pass or
  request a model id outside a project-scoped writing command.
- `interpret read`, `translate analyze-source/strategies/mappings`, `chapter quality`
  block until finished (can take minutes); poll with their status commands instead
  if you prefer async.
- `chapter/storymap generate`, `novel story-cores/blueprint`, `script *` generation
  commands run in background by default; add `--wait` to block until the run finishes.
- All mutating requests carry CSRF automatically after `login`.
- **Administrator commands** (`scriptnow admin *`) are guarded server-side by the
  `is_admin` flag — non-admin sessions receive 403. Available: `admin status`
  (platform diagnostics), `admin tenant-status` (activate/suspend a tenant),
  `admin skills`/`skill-show`/`skill-update` (main-site skill governance &
  capability evolution; `skill-update` requires the current `--expected-digest`
  to prevent concurrent overwrites). Model supply: `admin supply` (providers/
  models overview), `admin provider-connect --base-url <url> --credential <key>`
  (one-step OpenAI-compatible provider: verify → discover → sync → bind lowest
  tier), `admin model-add` / `admin image-model-add` for manual registration.
  Per product policy, token consumption, quota, billing and other financial
  operations are deliberately NOT exposed in the CLI — use the admin console
  for those.
- **Skill capability evolution** (`scriptnow skill growth *`): after a project
  accumulates accepted work, run `skill growth start <pid> --domain novel|script`,
  review candidates with `skill growth workspace <pid>`, decide per candidate
  (`accept`/`edit`/`reject`/…), evaluate with `skill growth evaluate`, preview,
  then `skill growth publish` (optionally `--mount <pid>` to roll out via canary).
- **Skill version evolution** (`scriptnow skill canary *`): `skill canary list`
  shows your rollouts; `skill canary decide <id> --action retain|limit|
  need_evidence|rollback` steers a new version to full adoption or rollback.
- Project ids, skill ids and revision ids are UUID strings — never guess them,
  always resolve via `project list` / `skill list` / `storymap state` / `script state`.
- `storymap state` / `script state` return full project state including adopted
  structures, blueprint anchors, and document version history.

- **Batch generation discipline**: `script scene-batch` exists but MUST be used
  sparingly — bulk generation risks plot/setting drift and broken foreshadowing.
  The CLI warns before each batch; review every scene before adopting. The
  best practice is per-scene/per-chapter refinement (generate → show --plain →
  judge → feedback → adopt). Do NOT fan out subagents for parallel batch
  writing — split contexts cause canon drift. Keep project writing serial and
  context-shared.

- **Evaluation standard**: `chapter quality` defaults to the content-quality preference (platform-suggested
  dimensions: character agency / causality / relationship progression / narrative voice / continuity / source
  boundary / propulsion / prose texture). Add `--standard drama-filing` (live-drama filing) or
  `--standard thousand-plan` (bulk web-novel) only when the user explicitly requests them. Assessment is the
  agent's systematic judgment per dimension, citing evidence — combine with the platform's suggested dimensions.
- **REVIEW DISCIPLINE (MANDATORY, first priority — strict rejection of self-congratulation)**:
  Reviewing is the agent's single most important duty; never skim, never cheerlead.
  1. **Become the audience, not the author's fan**: read every sentence of every
     scene/chapter as a demanding viewer who paid to be moved. Ask at each line:
     "would I keep reading? is this earning my attention?" If it would bore you,
     it will bore the reader — say so plainly.
  2. **Judge with the professional skill of a screenwriter/editor who matches the
     work's style**: evaluate craft — dramatic stakes, character agency, causality,
     escalation, subtext, rhythm, camera language (for scripts), prose texture (for
     novels) — with the same expertise a working screenwriter would apply to a
     colleague's draft. Match the project's declared style/genre standards; do not
     grade everything by one generic rubric.
  3. **Be cold, serious and specific**: praise only what genuinely works (cite the
     line/beat); attack what fails with concrete evidence (quote the weak line, name
     the missing beat, state the dropped thread). Vague approval ("不错", "很有
     张力") without citation is forbidden; unsupported praise is self-high.
  4. **Never rubber-stamp**: if a draft would not hold an audience, say "this needs
     regeneration" and give the exact reasons + what to fix, instead of adopting to
     avoid conflict. An 8/10 that can be a 9 is a revision, not an adoption.
  5. **Frame every verdict for the reader/viewer's experience**, not the author's
     effort: "this scene spends 40s of screen time on exposition with no character
     choice" beats "this scene is well written". Judge每一句、每一帧.
  6. When the user asks for review feedback via `--feedback` or in chat, deliver
     the same rigor: a prioritized fix list (blockers first), each item quoting the
     text and prescribing the fix.
- **Format-spec examples** (`--help-format`/`--example`) show format compliance, not quality exemplars.

## MANDATORY creation roles & workflow (from production reflection)

- **Planning-artifact quality gate (MANDATORY, before adopting any planning
  artifact)**: run `novel/script planning-quality <pid> <kind> <file.json>` on
  every agent-curated cores / blueprint / storymap / bibles JSON before
  adopting. The endpoint deterministically checks must-deliver fields (style,
  genre, writing language, volume/chapter and scene-duration planning) and
  content-length standards, and reports `pass|revise|block` with evidence.
  Adopt only on `pass` (or after fixing `revise` items); never adopt a `block`.
  Format: `novel/script planning-quality <pid> cores|blueprint|storymap|bibles
  @file.json`.
- **Agent backfill is the primary path, platform generation is fallback**:
  for the four planning artifact kinds (cores/blueprint/storymap/bibles) and
  for body text (chapter/scene), prefer the agent-curated `propose`/`*-propose`
  commands; use platform generation (`generate`/`--inspire`) only when the user
  explicitly asks or the agent cannot produce the artifact itself. `novel
  bootstrap --cores-file/--blueprint-file/--storymap-file` runs the whole
  planning chain from agent files (falling back to platform generation per step
  when a file is absent).
- **Manual human revision is always available** in the creator UI for both
  domains (chapter/scene 人工修订 → 另存人工修订 creates a human-sourced
  candidate); the CLI backfills the same candidate via `chapter propose` /
  `scene propose` with `source` human|cli.
- **Role split**: You are the **project manager + quality reviewer**. The
  platform (scene/chapter generation) is the **writer**. Your job: prepare
  direction/feedback, drive generation, review quality, demand regeneration,
  and adopt passing versions. You MAY provide **sample chapters/demos** and
  iterate on them per the user's requests — but any final result MUST be
  persisted into the project's per-chapter writing as a **candidate revision**
  (`chapter/scene propose`), never left as stray local text.
- **Stage 1 — immediate setup**: after receiving a brief, immediately
  `project create`, then backfill structure via propose
  (`novel/script propose cores|blueprint|storymap` for the first 5-10
  episodes/volumes). Do not accumulate local files — push to the platform at
  once.
- **Stage 2 — per-unit loop (generate → review → regenerate → adopt)**:
  for each scene/chapter:
  1. prepare a detailed feedback brief (opening hook / conflict / dramatic turn /
     ending hook / camera language as appropriate);
  2. run generation (`script scene` / `chapter generate`);
  3. **read the candidate in full** (`scene-show --plain` / `chapter show
     --plain` — never judge from a summary), then review it the way a demanding
     audience member and a working screenwriter would: is each line earning its
     place, each frame justified? Run `scene-quality` only as a length/dialogue/
     camera sanity check, never as a substitute for reading the text;
  4. score against the evaluation dimensions with the **REVIEW DISCIPLINE**
     above: quote evidence, name the failing beats, reject self-congratulation;
  5. if below threshold — **regenerate immediately with feedback**; never adopt
     unqualified work;
  6. adopt only when it passes.

- **Prerequisite completeness check (MANDATORY, before per-chapter writing)**:
  verify direction, adopted cores, blueprint and StoryMap are all in place
  (`novel/script state`, `book`); if any is missing, complete it first —
  writing before prerequisites are settled corrupts project robustness.
- **Creative ideation**: when the user has no concrete idea, guide them to
  brainstorm instead of forcing a direction. The ideation backfill on the CLI
  is simply an **idea already audited by the user** (`project direction
  --apply` with the agreed idea, or a single-core `propose`). Never invent a
  direction the user has not seen.
- **Synopsis outline (MANDATORY, before StoryMap)**: once the creative direction
  and blueprint are clear, produce a **≤500-word synopsis outline** and submit it
  for the user's review; after approval, persist it ON THE PLATFORM — never keep
  it only locally — with `novel outline <pid> --text "..."` then
  `novel outline-adopt <pid>` (check with `novel outline-status <pid>`). StoryMap
  planning is gated on an adopted outline, so an outline kept only in the agent's
  local context will cause the next `storymap` step to be rejected.
- **Quality threshold**: 9-10 excellent · 8-9 acceptable · **<8 regenerate**.
- **Progress control**: after each episode/volume, report quality statistics and
  ask the user whether to continue. Review is your own judgment (not a platform
  gate); the platform supplies suggested dimensions.
