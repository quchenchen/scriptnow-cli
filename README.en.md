# scriptnow-cli

**From spark to finished book — the agent-native creation CLI**

[English](README.en.md) · [中文](README.md)

<p align="center">
  <img src="assets/ascii-banner.png" alt="ScriptNow CLI — Matrix ASCII banner" width="100%" style="max-width:1200px" />
</p>

> Built for **terminal users and AI agents**: projects, one-work-one-skill
> interpretation, novel/script creation, skill evolution, covers and exports —
> all from the command line. Non-CLI creators should use the web app.

A one-stop CLI built on the [CLI-Anything](https://github.com/HKUDS/CLI-Anything) pattern,
covering **two creation domains (dual-domain): novels and scripts**. Every command supports
`--json` structured output for direct agent orchestration.

## Highlights

- **Dual-domain creation chains**: novel (volumes × chapters) and script (episodes × scenes)
  share "project → direction → planning → writing → delivery", with per-domain planning and
  writing loops that agents orchestrate separately.
- **Samples never leave your machine**: one-work-one-skill uses `interpret local` — the agent
  reads the work locally, distills the methodology and returns only the skill JSON; adapted
  drafts return via `chapter propose` / `script scene-propose` without platform text generation.
- **Skill capability & version evolution**: `skill growth` distills methodology from accepted
  work, evaluates it and publishes a new skill version; `skill canary` steers a new version via
  rollout decisions (retain / limit / need_evidence / rollback).
- **Admin branch**: the `admin` group is gated by `is_admin` (403 otherwise). Token consumption,
  quota and financial commands are deliberately **not** part of the CLI.
- **Token budget control**: local imports (propose / scene-propose / interpret local) gate with
  `--budget` estimation.
- **Auto-renewing session**: one `login` lasts 30 days — access tokens refresh automatically,
  so agent sessions never die mid-work.
- **Agent operating contract**: `scriptnow agent-guide` (--json) — platform is the single source of
  truth, the planning trio is backfill-first, episode/chapter outline completeness is gated before
  prose, generation runs in the background (poll `run status`), and StoryMap restructuring requires
  explicit user authorization.
- **Append-only structure growth**: `storymap append-volume` / `append-chapters` add volumes/chapters
  without touching existing ones; replaced structures are archived and reviewable.
- **Review is the agent's own judgment**: no fixed platform rubric — read the text, judge, and
  drive fixes with `--feedback`.

## Installation

Requires Python 3.10+. On macOS/Linux system Pythons (Homebrew, python.org) guarded by
PEP 668, install inside a virtual environment first:

```bash
# From source (editable — recommended for development)
git clone https://github.com/quchenchen/scriptnow-cli.git
cd scriptnow-cli && pip install -e .

# Preferred: production wheel host (sn.igeewa.com) — no git dependency, most stable
pip install https://sn.igeewa.com/downloads/scriptnow-cli/scriptnow_cli-0.3.74-py3-none-any.whl

# Fixed-version source archive (zip)
curl -sL -o /tmp/scriptnow-cli.zip https://sn.igeewa.com/downloads/scriptnow-cli/scriptnow-cli-v0.3.74.zip

# Fallback: latest GitHub code (codeload direct, no clone)
curl -sL -o /tmp/scriptnow-cli-latest.tar.gz https://codeload.github.com/quchenchen/scriptnow-cli/tar.gz/refs/heads/main
pip install --force-reinstall /tmp/scriptnow-cli-latest.tar.gz

# Fixed GitHub tag
pip install "https://codeload.github.com/quchenchen/scriptnow-cli/zip/refs/tags/v0.3.74"
```

`scriptnow self-upgrade` (and the opt-in background auto-upgrade) prefer the production
wheel host and fall back to codeload → git+https.

## Login

```bash
scriptnow login --host https://sn.igeewa.com --email you@example.com   # interactive hidden password (or --password-stdin / SCRIPTNOW_PASSWORD)
```

The session (cookie + CSRF) is persisted at `~/.config/scriptnow-cli/session.json`
(cookie only, no password, mode 0600). Alternatively use the `SCRIPTNOW_BASE_URL` /
`SCRIPTNOW_EMAIL` / `SCRIPTNOW_PASSWORD` environment variables.

### Config & session location (agents: run `scriptnow doctor` first)

| Item | Location |
|---|---|
| Session (cookies + CSRF) | `~/.config/scriptnow-cli/session.json` |
| Version-check cache | `~/.config/scriptnow-cli/version-check.json` |
| Onboarding flag | `~/.config/scriptnow-cli/` (onboarded marker) |
| Override session path | `SCRIPTNOW_CLI_CONFIG=/path/to/session.json` |

**When anything auth-ish fails — login failure, "cannot find config", 409, or
"No such option" — run `scriptnow doctor` FIRST.** It prints the CLI version, the
actual session path, whether you are logged in, which account, the platform URL and
connectivity. Do not guess where config lives. `doctor` says not logged in → re-run
`scriptnow login`; logged in but requests 409 → usually a refresh-token rotation race,
re-login (not a data problem). Shared session file across venvs/pipx/system means one
login works everywhere; concurrent refresh from multiple ends may revoke the old
token once (rotation protection) — just log in again.

## Quick start (dual-domain)

**Prerequisite — check Skill support** (before writing): if the project has no methodology
skill mounted, create one first:

```bash
scriptnow skill mounts <pid>                  # which skills are mounted?
# none → one-work-one-skill distillation (samples stay local): interpret local draft.docx --spec
#         → read locally → --submit @skill.json --project-id <pid>
#    or a personal skill: skill create --domain novel|script ... → skill mount <pid> <skill_id> <version_id>
```

**Novel (volumes × chapters)**

```bash
scriptnow project create --name "My Novel" --medium novel --volume-one 1 --volume-two 15 --chapter-target-words 1200
scriptnow project direction <pid> --apply @direction.json --review-token <direction-review-token>
# Planning (candidate submission and adoption are separate reviewed decisions)
scriptnow novel propose <pid> cores @cores.json --review-token <submission-review-token>
scriptnow review candidate-preview novel <pid> story_core_candidate <candidate_id>
scriptnow novel adopt-core <pid> <candidate_id> --review-token <adoption-review-token>
scriptnow novel propose <pid> blueprint @blueprint.json --review-token <submission-review-token>
scriptnow novel propose <pid> storymap @storymap.json --review-token <submission-review-token>
scriptnow novel planning-quality <pid> storymap @storymap.json  # full chapter-outline gate
scriptnow novel orchestrate <pid> --skip-adopt               # read-only orchestration
# Writing loop (agent-driven review)
scriptnow book <pid>                                          # hosted plan: adopted/needs-generation/pending
scriptnow chapter outline <pid> chapter-1-1 @outline.json --review-token <submission-review-token>
scriptnow chapter show <pid> chapter-1-1 --plain
scriptnow chapter generate <pid> chapter-1-1 --feedback "your notes"   # background; returns run_id
scriptnow run status <run_id>                                         # poll until done (agents: never --wait)
scriptnow chapter adopt <pid> chapter-1-1 <rev> --human --review-token <adoption-review-token>
# Adapted draft return: chapter propose <pid> chapter-1-1 --file @blocks.json --review-token <submission-review-token>
```

**Script (episodes × scenes)**

```bash
scriptnow project create --name "My Script" --medium script --point-of-view "limited witness" --volume-one 10 --volume-two 2-4 --volume-three 3
scriptnow project direction <pid> --apply @direction.json --review-token <direction-review-token>
# Planning
scriptnow script propose <pid> cores @cores.json --review-token <submission-review-token>
scriptnow review candidate-preview script <pid> story_core_candidate <candidate_id>
scriptnow script adopt-core <pid> <candidate_id> --review-token <adoption-review-token>
scriptnow script propose <pid> blueprint @blueprint.json --review-token <submission-review-token>
scriptnow script propose <pid> storymap @storymap.json --review-token <submission-review-token>
scriptnow script planning-quality <pid> storymap @storymap.json  # full episode-outline gate
# Writing loop
scriptnow script scene-list <pid>
scriptnow script scene-show <pid> scene-1-1 --plain
scriptnow script scene <pid> scene-1-1 --feedback "your notes"   # background; returns run_id
scriptnow run status <run_id>                                    # poll until done (agents: never --wait)
scriptnow script adopt-scene <pid> scene-1-1 <rev> --human --review-token <adoption-review-token>
# Adapted draft return: script scene-propose <pid> scene-1-1 --file @blocks.json --review-token <submission-review-token>
```

**Delivery**: `cover generate` → `export create --units chapter-1-1|scene-1-1` →
`export download -o book.docx`. Script `--form working` adds per-scene production
metadata to DOCX. The internal production contract is intentionally not exposed
as a writer-facing export file yet.

## Command groups

| Group | Purpose |
|-------|---------|
| guide | Focused newcomer flow (outline-first, layer by layer): `--step 1..12 --medium novel|script`; `--pulse/--resume` provide soft return; `--steps` shows the full map; `--complete/--status` mark completion and show its status |
| review | Human review loop: `preview` shows a local candidate / `candidate-preview` shows the canonical platform planning candidate / `status` reads feedback / `confirm` records one decision / `claim` lets the Agent claim a one-time credential; the page is optional |
| project | Projects: create / list / **files (project files)** / upload / **use (set as default project)** / delete / direction (--apply agent-curated / --inspire platform inspiration) |
| interpret | One-work-one-skill: go (platform read-through) / local (agent-side, samples stay local) / create / read / status / decide |
| book | Hosted novel creation plan (agent orchestration primitive, includes Skill-support detection) |
| chapter | Novel chapters: **outline (backfill one chapter) / outline-batch (batch backfill) / outline-check (self-check) / outline-example (structure example) / bible-example (character-bible example)** / list / show / generate / quality (--standard content/drama-filing/thousand-plan) / adopt / propose (local return) |
| scene | Script scenes (the script-side counterpart of chapter): list / show / generate / adopt (alias of script adopt-scene) / propose (local return) / batch / quality / diff |
| storymap | Cross-domain structure commands (novel+script share): state / generate / **append-volume (add volume, append-only)** / **append-chapters (add chapters, append-only)** / **append-phase (submit next phase; Novel uses whole-book chapter ranges, not forced volumes)** / **phases (narrative-structure phase plan)** / adopt (**HIGH-RISK, requires --confirm**) / **structures (built-ins + saved library templates)** / **structure-save (name a structure; --description/--medium metadata)** / **structure-delete**; isolated rebuild runs on the per-domain storymap-rebuild-* chain |
| agent-guide | Agent operating contract (--json structured): platform is the source of truth, planning backfill-first, episode/chapter outline gate, background generation with run-status polling, StoryMap restructuring needs explicit user authorization |
| authorize | Issue a one-time "human decision authorization token" (in-conversation text-authorization channel, reuses the login session — no re-login): `--chapter/--scene` scope the target, `--digest` binds the user-read content; the token powers `chapter adopt --human --token` / `scene adopt --human --token` finalized-by-human writes |
| novel | Novel chain: story-cores / blueprint / adopt-core / adopt-blueprint / bootstrap / outline / outline-adopt / outline-status / graph (story-graph reconciliation) / planning-quality / planning-status / ready-check / propose (local JSON import) / orchestrate / **rough-outline flat chain: rough-outline / adopt / check / example** / **storymap-rebuild isolated chain: start / rebuild / rebuild-phase / rebuild-phase-preview / rebuild-check / rebuild-propose** / **storymap-archives / storymap-archive (replaced-structure archive reads)**; rebuilding requires the novel rough outline adopted first, phases use whole-book chapter ranges and do not force one phase per volume |
| script | Script chain: outline / outline-adopt / outline-status / episode-outline / **episode-outline-check / episode-outline-example** / **bible-example** / state / story-cores / blueprint / adopt-blueprint / adopt-core / storymap / **storymap-phases / storymap-append-phase** / adopt-storymap (high-risk) / planning-quality / **ready-check** / propose (local JSON import) / adopt-scene / scene / scene-list / scene-show / scene-propose (--help-format/--example; --auto-adopt is disabled) / scene-batch / scene-quality / scene-diff / quality-report / **rough-outline phased chain: -start / -phase / -progress / -propose / -phase-preview / -check** / **storymap-rebuild isolated chain: start / rebuild / rebuild-phase / rebuild-phase-preview / rebuild-check / rebuild-propose** / **storymap-archives / storymap-archive (replaced-structure archive reads)** |
| storyboard | Storyboard backfill: state / source-preflight / source-import / source-range / source-revoke / propose / assets / asset-add / continuity / **scene-board upload|generate|list|inspect|delete** / readiness / export; scene boards are explicit single-scene actions and never write shot.frame_refs |
| translate | Cross-cultural recreation: create / analyze-source / target-contract / strategies / mappings |
| cover | Covers: package / package-propose (agent-submitted packaging draft) / package-show / models / specs / generate (defaults to a single 1024×1600) / list / delete |
| export | Delivery: options / create / **preview (delivery-scope review with a one-click review URL)** / download / zip; script working DOCX includes per-scene production metadata |
| skill | Skill workshop: craft (co-create, preflight, confirm, mount read-back) / list / create / **detail (personal skill summary)** / update / versions / archive / mount / mounts / upload; **growth** (methodology evolution); **canary** (version rollout) |
| admin | Administrator only (is_admin, 403 otherwise): status / tenant-status / skills / skill-show / skill-update / supply / provider-connect / model-add / image-model-add |
| run | Ops: status / events |
| feedback | Collect a CLI diagnostics bundle (version / recent errors / command trail); local-only by default, `--send` uploads to the platform (no passwords, tokens, or prose) |
| version / self-upgrade / config | show version (--check force-checks the GitHub release mirror) / auto-upgrade (checks, asks for consent, then upgrades; a low-frequency background hint appears at startup) / `config on|off` toggles automatic upgrade on new versions (off by default; when on, upgrades in the background and notifies you, never blocking commands) |

**Isolated StoryMap rebuild (the storymap-rebuild-* chain on novel/script)**: the domain rough
outline must be adopted first; `storymap-rebuild-start` freezes the phase plan and the current
StoryMap, then per phase (novel: a whole-book chapter range, without forcing volumes; script: an episode range) run `rebuild-check`
before `rebuild-phase` accumulates it; when all phases are done, `rebuild-propose` merges them
into a complete replacement candidate (not auto-adopted). Only after explicit user confirmation
does `storymap adopt --confirm` replace the structure, archiving the old structure and prose snapshots.
Archives are readable afterwards: novel `storymap-archives <pid>` / `storymap-archive <pid> <archive_id>`,
script mirror `script storymap-archives <pid>` / `script storymap-archive <pid> <archive_id>` — both carry
the full replaced episode/volume structure plus per-scene/per-chapter prose snapshots.

Scene-board visual-agent parameters are explicit: `--layout auto|2x2|2x3|3x3|3x4|4x4` and
`--mode annotated|seedance_sequence`. Upload uses multipart; the server returns the authoritative layout/pages/shot_ids/digest/source.
If the image proxy rejects asset references, the platform preserves the failed Attempt and safely retries with a new no-reference Attempt.
`reference_validation` reports accepted/rejected inputs and reasons. Re-upload rejected asset references before relying on visual consistency.
Generated asset references and planning boards are persisted in the project workspace first. Later multi-reference requests encode local media as base64 instead of depending on temporary provider URLs; the CLI uses only stable platform media URLs.

## Focused newcomer mode

`scriptnow guide` now starts with one calm creative step instead of a command wall.
Each step asks one main question, offers optional inspiration lenses, mirrors the
creator's intent, and presents one candidate for a simple keep / adjust / change
direction decision. Commands stay backstage.

Chapter/scene finalization follows a one-explicit-statement rule: when the user
says finalize, use this version, or continue in the Agent conversation, the
Agent records the original words, claims the one-time credential bound to the
current content digest, and runs `chapter adopt --human` / `scene adopt --human`
backstage. The user never handles a terminal or credential; ask once only if ambiguous.

Script Skills automatically add four system quality anchors beyond the user's
project-specific rules: scene function and observable turn, visible/audible/
performable action, ordered dialogue/VO/OS, and spoken-text fit against target
duration. The platform derives production metadata without extra questions.

## Human review protocol (conversation first)

The human is the observer and decision-maker; the Agent is the executor. Every
platform-changing creative action—direction, story cores, blueprint, character
bibles, rough outline, StoryMap/episode or chapter outlines, prose revision,
adoption, and export—uses the same lightweight loop: the Agent reads platform
facts and shows a complete human-readable candidate; the user says **keep**,
**adjust**, or **change direction** once in the conversation; the Agent records
the original words, reads later feedback, and claims a one-time credential in
the background when the user keeps it. The user never copies a token, repeats a
command, or has to open a page.

Any content change invalidates the old digest and credential, so the new version
must be shown and confirmed again. Long content may include the one-click
`review_url` returned by `review preview`; the page is an optional reading aid,
not an extra approval gate. Editing and saving directly in the frontend is
itself a human decision and receives the same audit treatment.

Long-form script rough outlines are backfilled phase by phase against the
project's narrative structure, but structure ranges are suggestions: the author
may adjust any continuous boundary. `rough-outline-start/progress/phase` always
reports `Phase X / N`, the current phase key, and completed phases; progress must
never exist only in background JSON.

These commands are normally run by the Agent behind the conversation:

```bash
# Show and register the complete candidate; this does not write creative content
scriptnow review preview <pid> <resource-kind> <resource-id> @candidate.json
# After the user's one clear decision, record the words and claim a one-time credential
scriptnow review confirm <packet-id> --decision retain --evidence "Keep this version and continue."
scriptnow review claim <packet-id> --json
# On adjustment, read the feedback, revise, and preview again; never reuse the old credential
scriptnow review status <packet-id> --json
```

`review status` lets the Agent read the user's feedback without asking them to
repeat it. `--evidence` should preserve the user's words, not an Agent summary.
`--json` is for Agent orchestration and never replaces the human-readable
preview.

```bash
scriptnow guide --step 1 --medium novel --json
scriptnow guide --step 1 --medium script --json
scriptnow guide --steps
scriptnow guide --step 4 --medium novel --pulse @pulse.json --json
scriptnow guide --step 4 --medium novel --resume --json
```

## Skill capability & version evolution

```bash
# Capability evolution (methodology growth): distill from accepted work → evaluate → publish
scriptnow skill growth start <pid> --domain novel        # start analysis (background)
scriptnow skill growth workspace <pid>                   # candidates & run history
scriptnow skill growth decide <candidate_id> --action accept|edit|reject ...
scriptnow skill growth evaluate <candidate_id>           # evaluation replay (background)
scriptnow skill growth preview <candidate_id> --evaluation-result <id>
scriptnow skill growth publish <candidate_id> --evaluation-result <id> \
  --description "..." --instructions "..." --mount <pid> # publish new version (--mount starts a canary)

# Version evolution (canary rollout)
scriptnow skill canary list
scriptnow skill canary decide <canary_id> --action retain|limit|need_evidence|rollback
```

## Administrator CLI

The `admin` group is available to `is_admin` users only (server-enforced, 403 otherwise):
platform system status, tenant activate/suspend, main-site Skill governance and capability
evolution (`skill-update` requires `--expected-digest` to prevent concurrent overwrites).
**Token consumption, quota and financial commands are deliberately NOT in the CLI** — use
the admin console for those.

## Known gaps (backend has it, CLI does not yet)

onboarding, commerce (Paddle subscriptions), review-agent workbench,
evaluation v9 (deep evaluation), work-completion, invitations — to be added on demand.

## AI Agent installation (SKILL system)

Agents (Claude Code / npx skills compatible) can discover capabilities via SKILL.md:

```bash
npx skills add quchenchen/scriptnow-cli --skill scriptnow-cli -g -y
```

SKILL.md lives at [`cli_anything/scriptnow/skills/SKILL.md`](cli_anything/scriptnow/skills/SKILL.md).

## Tips for AI agents

- **MANDATORY: read the short runtime contract first** (`scriptnow agent-guide --json`; use
  `--full` only for the human reference manual): the platform is
  the source of truth, planning trio is backfill-first via `propose`, generation commands run in
  the background (poll `run status`, never block with `--wait`), and StoryMap restructuring is a
  super high-risk operation that requires explicit user authorization (`--confirm`) — an agent must
  NEVER adopt a storymap on the user's behalf.
- **MANDATORY: Skill is a pre-writing gate with a robustness-honing duty** — once the
  intent is clear and the project exists, plan the methodology with the user (multi-round),
  then harden it (test-drive a sample chapter/scene against its rules, diagnose gaps, iterate),
  create and mount it on the platform (interpret local distillation or skill create), and
  verify with `skill mounts <pid>` before any per-chapter/scene writing. `book` also hard-stops
  on missing Skill support.
- **MANDATORY: fill the full project direction yourself** — backfill premise/tone/world_setting/
  genre/structure/volumes/word-counts with `project direction <pid> --apply @direction.json`;
  do not rely on `--inspire` and do not create bare projects.
- **Review credentials bind exact content** — bind a credential to the human-readable JSON the user actually read; parser-added defaults must not manufacture a content change.
- **two modes for prose writing (the user picks; the platform never blocks either)**: by default
  the platform is the writer — `chapter/scene generate` produces a candidate → `review preview`
  → `adopt`. Only when the user explicitly chooses local writing may the Agent write the prose
  locally and backfill it via `chapter propose` / `script scene-propose` → `review preview` →
  `adopt --human`. Without an explicit choice, default to the platform-authored path. This rule
  governs prose (chapters/scenes) only; the planning-trio backfill-first rule (story_cores /
  blueprint / storymap) is unchanged.
- **Episode/chapter outline is mandatory before prose** — Script episodes use flat
  `logline`/`active_goal`/`conflict`/`turn`/`state_changes`/`anchor_ids`; Novel chapters embed
  `outline` with `summary` or `logline`, `active_goal`, `conflict`, `turn`, and `state_changes`
  (anchors may come from the outline or beats). Run full-map `planning-quality` before adoption.
  Backfill one unit with `script episode-outline <pid> <episode_id> @outline.json` or
  `chapter outline <pid> <chapter_id> @outline.json`; each remains a reviewable StoryMap candidate.
- Prefer `--json`; generation commands run in the background and return a `run_id` — poll with `run status` (never block with `--wait` in agent hosts; interactive terminals may set `SCRIPTNOW_WAIT_MAX_SECONDS`). Failures use `{ok:false,error:{type,status,detail}}` without a traceback, and prefer the sanitized original domain detail so the Agent can act on it; never treat a generic localized fallback as a repair instruction.
- Version baseline: latest "adopted + human revision (even unadopted)"; unadopted agent
  candidates are not part of the baseline.
- Review is the agent's own judgment: read the text → judge → drive fixes with `--feedback`.

## Security notes

- Session stores cookies only (no passwords), file mode 0600.
- All writes go through the platform's auth (cookie + CSRF + tenant isolation); no cross-tenant access.
- Platform internals (built-in skills, admin endpoints, tool catalog) are not exposed via the CLI —
  the admin group is is_admin-gated.


## Evaluation standards

- `chapter quality --standard` defaults to **content-quality preference** (character agency / scene causality /
  relationship progression / narrative voice / continuity / source boundary / chapter propulsion / prose texture).
  Only when the user explicitly asks for **live-drama filing standards** (`--standard drama-filing`) or the
  **thousand-plan bulk-web-novel standard** (`--standard thousand-plan`) are those added.
- Evaluation pairs **agent systematic assessment** with **platform-suggested dimensions**: the CLI exposes the
  dimension list and the scene text; the agent evaluates dimension by dimension with cited evidence.

## Format-spec examples

`chapter propose --help-format/--example` and `script scene-propose --help-format/--example` show **format-spec
examples** (blocks JSON / prose layout). They demonstrate format compliance only — **not quality exemplars**;
quality is judged by the agent against the evaluation dimensions above.


## Agent creation roles & workflow discipline (must-read)

- **Role split (default: the platform is the writer)**: Agent = project manager +
  quality reviewer; the platform (scene/chapter generation) writes by default —
  prepare direction/feedback, drive generation, review, demand regeneration,
  and adopt only passing versions. Only when the user explicitly chooses local
  writing may the Agent write the prose locally and backfill it via
  `chapter propose` / `script scene-propose` — never otherwise (no piled-up
  local draft files).
- **Stage 1 (immediate)**: create the project at once, then backfill structure
  via propose (cores/blueprint/storymap, first 5-10 episodes/volumes) — push to
  the platform instead of accumulating local files.
- **Stage 2 (per-unit loop)**: per scene/chapter — prepare a detailed feedback
  brief → generate → review (`scene-show --plain` + `scene-quality`) → if below
  threshold, regenerate immediately with feedback → adopt only when it passes.
- **Quality threshold**: 9-10 excellent · 8-9 acceptable · **<8 regenerate
  immediately** — never adopt unqualified work.
- **Progress control**: after each episode/volume, report quality stats and ask
  the user whether to continue.
