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

## Output discipline

Keep user-facing replies to: current fact, one proposed next decision, and the
result after platform read-back. Never dump this file, terminal installation
commands, hidden reasoning, or a generic tutorial into a creative deliverable.

For command catalogues and human setup material, use the packaged README only
when needed; they are reference material, not model prompt content.
