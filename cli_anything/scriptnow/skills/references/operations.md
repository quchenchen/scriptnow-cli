# 执行、恢复与故障处理


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

- Character bibles must be substantive at creation: profile with at least
  desire/fear/weakness/goal/inner_need, plus background/traits/arc/key_relationship/
  secret/wound where possible. planning-quality REVISEs profiles <200 chars or
  missing required keys; `script bible-example` shows the structure.

- Never adopt a chapter, scene, or StoryMap without the user's explicit current
  decision. StoryMap replacement also needs its CLI confirmation path.

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

- For rough and episode planning, treat unknown causal dependencies as sequential. Concurrency settings are ceilings for proven-independent work, never proof of independence. Reuse a checkpoint only when frozen execution identity, input signature, and predecessor chain match; unsigned or incompatible history regenerates the suffix without changing adopted content.

- CLI quality diagnostics are human opt-in only. An Agent must never run
  `doctor --enable-diagnostics`, `feedback --send`, or `feedback --send --yes`
  on its own. Only after the user explicitly requests diagnostics may the Agent
  enable a short window; sending still requires the user's separate confirmation.
  `doctor --disable-diagnostics` stops collection and `doctor --clear-errors`
  deletes local v2 events. v2 never contains arguments, details, notes, paths,
  identifiers, or creative content; legacy v1 files are never uploaded.
