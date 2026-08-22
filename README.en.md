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
  truth, the planning trio is backfill-first, generation runs in the background (poll `run status`),
  and StoryMap restructuring requires explicit user authorization.
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

# Or straight from the latest GitHub code (codeload direct, no clone needed)
curl -sL -o /tmp/scriptnow-cli-latest.tar.gz https://codeload.github.com/quchenchen/scriptnow-cli/tar.gz/refs/heads/main
pip install --force-reinstall /tmp/scriptnow-cli-latest.tar.gz
```

## Login

```bash
scriptnow login --host https://sn.igeewa.com --email you@example.com   # interactive hidden password (or --password-stdin / SCRIPTNOW_PASSWORD)
```

The session (cookie + CSRF) is persisted at `~/.config/scriptnow-cli/session.json`
(cookie only, no password, mode 0600). Alternatively use the `SCRIPTNOW_BASE_URL` /
`SCRIPTNOW_EMAIL` / `SCRIPTNOW_PASSWORD` environment variables.

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
scriptnow project direction <pid> --apply @direction.json     # agent curates the full direction
# Planning (agent-side import; a single curated core adopts directly)
scriptnow novel propose <pid> cores @cores.json --adopt
scriptnow novel propose <pid> blueprint @blueprint.json --adopt
scriptnow novel propose <pid> storymap @storymap.json
scriptnow novel orchestrate <pid> --accept                    # review → adopt → full plan
# Writing loop (agent-driven review)
scriptnow book <pid>                                          # hosted plan: adopted/needs-generation/pending
scriptnow chapter show <pid> chapter-1-1 --plain
scriptnow chapter generate <pid> chapter-1-1 --wait --feedback "your notes"
scriptnow chapter adopt <pid> chapter-1-1 <rev>
# Adapted draft return: chapter propose <pid> chapter-1-1 --file @blocks.json
```

**Script (episodes × scenes)**

```bash
scriptnow project create --name "My Script" --medium script
scriptnow project direction <pid> --apply @direction.json
# Planning
scriptnow script propose <pid> cores @cores.json --adopt
scriptnow script propose <pid> blueprint @blueprint.json --adopt
scriptnow script propose <pid> storymap @storymap.json
# Writing loop
scriptnow script scene-list <pid>
scriptnow script scene-show <pid> scene-1-1 --plain
scriptnow script scene <pid> scene-1-1 --wait --feedback "your notes"
scriptnow script adopt-scene <pid> scene-1-1 <rev>
# Adapted draft return: script scene-propose <pid> scene-1-1 --file @blocks.json
```

**Delivery**: `cover generate` → `export create --units chapter-1-1|scene-1-1` →
`export download -o book.docx`.

## Command groups

| Group | Purpose |
|-------|---------|
| project | Projects: create / list / upload files / delete / direction (--apply agent-curated / --inspire platform inspiration) |
| interpret | One-work-one-skill: go (platform read-through) / local (agent-side, samples stay local) / create / read / status / decide |
| book | Hosted novel creation plan (agent orchestration primitive, includes Skill-support detection) |
| chapter | Novel chapters: list / show / generate / quality (--standard content/drama-filing/thousand-plan) / adopt / propose (local return) |
| storymap | Novel volumes×chapters: state / generate / **append-volume (add volume, append-only)** / **append-chapters (add chapters, append-only)** / adopt (**HIGH-RISK, requires --confirm**) |
| agent-guide | Agent operating contract (--json structured): platform is the source of truth, planning backfill-first, background generation with run-status polling, StoryMap restructuring needs explicit user authorization |
| novel | Novel chain: story-cores / blueprint / bootstrap / propose (local JSON import) / orchestrate |
| script | Script chain: state / scene-list / scene-show / scene / scene-propose (--auto-adopt/--help-format/--example) / scene-batch (serial + resume) / scene-quality / scene-diff / quality-report / storymap / blueprint / story-cores / propose / adopt-* |
| translate | Cross-cultural recreation: create / analyze-source / target-contract / strategies / mappings |
| cover | Covers: package / package-propose (agent-submitted packaging draft) / package-show / models / specs / generate (defaults to a single 1024×1600) / list / delete |
| export | Delivery: options / create / download (novel/script) |
| skill | Skill workshop: list / create / update / versions / archive / mount / mounts / upload; **growth** (methodology evolution); **canary** (version rollout) |
| admin | Administrator only (is_admin, 403 otherwise): status / tenant-status / skills / skill-show / skill-update / supply / provider-connect / model-add / image-model-add |
| run | Ops: status / events |
| version / self-upgrade | show version (--check force-checks the GitHub release mirror) / auto-upgrade (checks, asks for consent, then upgrades; a low-frequency background hint appears at startup) |

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

narrative-graph, onboarding, commerce (Paddle subscriptions), review-agent workbench,
evaluation v9 (deep evaluation), work-completion, invitations — to be added on demand.

## AI Agent installation (SKILL system)

Agents (Claude Code / npx skills compatible) can discover capabilities via SKILL.md:

```bash
npx skills add quchenchen/scriptnow-cli --skill scriptnow-cli -g -y
```

SKILL.md lives at [`cli_anything/scriptnow/skills/SKILL.md`](cli_anything/scriptnow/skills/SKILL.md).

## Tips for AI agents

- **MANDATORY: read the operating contract first** (`scriptnow agent-guide --json`): platform is
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
- Prefer `--json`; generation commands run in the background and return a `run_id` — poll with `run status` (never block with `--wait` in agent hosts; interactive terminals may set `SCRIPTNOW_WAIT_MAX_SECONDS`).
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

- **Role split**: Agent = project manager + quality reviewer; the platform
  (scene/chapter generation) = the writer. Agents must NEVER write manuscript
  content themselves — no local sample scripts or piled-up config files.
  Prepare direction/feedback, drive generation, review, demand regeneration,
  and adopt only passing versions.
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
