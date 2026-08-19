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
| novel | story-cores, adopt-core, blueprint, adopt-blueprint, bootstrap (一键规划: 故事核心→蓝图→StoryMap→采纳) |
| script | state, story-cores, adopt-core, blueprint, adopt-blueprint, storymap, adopt-storymap, scene, adopt-scene, scene-list, scene-show |
| translate | create, analyze-source, target-contract, strategies, mappings |
| cover | models, specs, generate, list, delete |
| export | options, create, download (novel/script) |
| skill | list, detail, versions, create, update, archive, mounts, mount, upload |
| run | status, events |
| account | summary |
| login | — |

## For AI Agents

- Always use `--json` for structured output; JSON output is the default for automation.
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
- Project ids, skill ids and revision ids are UUID strings — never guess them,
  always resolve via `project list` / `skill list` / `storymap state` / `script state`.
- `storymap state` / `script state` return full project state including adopted
  structures, blueprint anchors, and document version history.
