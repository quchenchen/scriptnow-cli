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
| chapter | list, show, generate, adopt, quality |
| storymap | state, generate, adopt |
| book | plan (全书托管创作规划，Agent 编排原语) |
| novel | story-cores, adopt-core, blueprint, adopt-blueprint, bootstrap (一键规划), propose (本地 JSON 导入: cores/blueprint/storymap, 支持 --adopt) |
| script | state, story-cores, adopt-core, blueprint, adopt-blueprint, storymap, adopt-storymap, scene, adopt-scene, scene-list, scene-show |
| translate | create, analyze-source, target-contract, strategies, mappings |
| cover | package (generate the work package — required before cover generation), package-propose (agent-submitted packaging draft), package-show, models, specs, generate (defaults to a single 1024×1600 output), list, delete |
| export | options, create, download (novel/script) |
| skill | list, detail, versions, create, update, archive, mounts, mount, upload; growth (workspace/start/decide/candidate/evaluate/preview/publish — methodology evolution); canary (list/decide — version rollout) |
| admin | status, tenant-status, skills, skill-show, skill-update, supply (provider/model overview), provider-connect (one-step OpenAI-compatible provider), model-add, image-model-add — administrator-only (403 otherwise); token-consumption/quota/financial commands are intentionally NOT in the CLI |
| run | status, events |
| login | — |

## For AI Agents

- Always use `--json` for structured output; JSON output is the default for automation.
- **MANDATORY: check Skill support before writing (both domains).** Before driving
  the per-chapter/per-scene creation loop, run `scriptnow skill mounts <project_id>`.
  If the project has **no** methodology Skill mounted, create one FIRST and mount it,
  then write:
  - One-work-one-skill distillation (preferred; keeps samples off-platform):
    `scriptnow interpret local <work> --spec` → read the work locally, produce the
    skill JSON per the spec → `scriptnow interpret local <work> --submit @skill.json
    --project-id <pid>` (creates the personal skill and mounts it). For scripts, set
    `"domain": "script"` in the skill JSON. Novels may also use `interpret go`
    (platform read-through; the work is uploaded).
  - Direct personal-skill submission:
    `scriptnow skill create --name ... --domain novel|script --role writer --stage
    writing --instructions "..."`, then `skill mounts <pid>` for the version id and
    `skill mount <pid> <skill_id> <version_id>`.
  - The hosted plan command (`scriptnow book`) also flags missing Skill support in
    human-readable mode.
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
    `novel propose cores|blueprint|storymap @file` (agent-side) or
    `storymap generate --wait` (platform), then `novel orchestrate --accept` to
    review+adopt and print the plan. Writing loop: `book <pid>` (hosted plan) →
    per chapter `chapter show --plain` → judge → `chapter generate --feedback` →
    `chapter adopt`. Agent-written adaptation text returns via `chapter propose
    --file @blocks.json`.
  - **Script (episodes × scenes)**: planning via
    `script propose cores|blueprint|storymap @file` (agent-side) or the platform
    generation commands (`script story-cores --wait` → adopt → `script blueprint`
    → adopt → `script storymap` → adopt). Writing loop: `script scene-list` →
    `script scene-show --plain` → judge → `script scene --feedback` → `script
    adopt-scene`. Agent-written adaptation text returns via `script scene-propose
    --file @blocks.json` (block types slugline|action|character|dialogue|transition).
  - Export differs only in the unit dimension: novel `--units chapter-1-1`;
    script `--units scene-1-1`.
- **`scriptnow book <project_id>` prints the hosted creation plan** (per-chapter
  adopted / needs-generation / candidate-pending-review state). The agent drives
  the loop: read the plan, then per chapter use `chapter show --plain` to read
  the text, form its own judgment, drive fixes with `chapter generate --feedback`,
  and adopt with `chapter adopt`. Review is the agent's own judgment, not a
  platform quality gate.
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
