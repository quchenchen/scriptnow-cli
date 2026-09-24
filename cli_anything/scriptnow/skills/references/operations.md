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

- Use CLI commands for every platform action; local files are drafts until the
  platform returns a candidate ID. dsh is the default author. An author's
  creative delegation covers guidance, reading, drafting and scoped candidate
  saving. It never expands to adoption, StoryMap replacement, deletion or
  publishing.

- For a dsh candidate path, `scriptnow run claim <project> <kind> <resource>
  --task-key <stable-task> --attempt-key <this-attempt> --json` returns the
  scoped `token`, `attempt_id`, `state_version` and `expires_at`. Read adopted
  facts and methods, draft, then propose with `--execution-token <token>`.
  Before prose, call `skill selected <project> --unit-id <unit> --json` and read
  all selected instructions and references. `chapter/scene propose` requires
  both the execution token and the returned `material_digest`; the platform
  checks the current selected bundle and records its digest on the artifact.
  This proves a matching bundle was available to the writer, while actual
  application remains a separate review claim. A long task must call
  `run renew <project> <attempt_id> --execution-token
  <token> --state-version <latest> --json` before expiry and keep the new
  state version. Renewal failure means this attempt no longer owns writes.
  `run revoke` withdraws write authority first. Only `engine_stopped=true`
  confirms dsh became idle; when false, `run stop-status` probes without
  sending another cancel that could interrupt a successor turn.
  The write token cannot be used for human adoption.

- Character bibles must be substantive at creation: write `profile.summary` as one
  continuous narrative — background / what they want / what they fear / the soft
  spot / where it ends. Aim for >=200 characters; a shorter profile only earns an
  advisory note and never blocks. The legacy column keys
  (desire/fear/weakness/goal/inner_need, plus background/traits/arc/key_relationship/
  secret/wound) stay legal but are optional, and no gate reads them.
  `script bible-example` shows the structure.

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

- When a candidate submission's response is lost, resend the **same request**
  with the same execution token, request key and content. The platform may
  return an already committed receipt even if this attempt was later revoked;
  a different attempt cannot take that receipt. Body candidates and the
  story_cores / blueprint / synopsis / rough_outline / storymap planning candidates,
  one character-bible candidate at a time, and scoped episode/chapter outline
  backfills have this new path.
  Synopsis proposals get separate immutable candidate IDs; the author reviews
  and adopts one exact ID. Character bibles are also saved as immutable candidates:
  use `run claim ... bible <character_key>`, `novel/script propose ... bibles
  --execution-token`, then `bible-candidate-preview` and a separate human
  `bible-candidate-adopt`. Formal adoption, export, structure append and rebuild
  do not inherit the candidate receipt semantics.

- For rough and episode planning, treat unknown causal dependencies as sequential. Concurrency settings are ceilings for proven-independent work, never proof of independence. Reuse a checkpoint only when frozen execution identity, input signature, and predecessor chain match; unsigned or incompatible history regenerates the suffix without changing adopted content.

- CLI quality diagnostics are human opt-in only. An Agent must never run
  `doctor --enable-diagnostics`, `feedback --send`, or `feedback --send --yes`
  on its own. Only after the user explicitly requests diagnostics may the Agent
  enable a short window; sending still requires the user's separate confirmation.
  `doctor --disable-diagnostics` stops collection and `doctor --clear-errors`
  deletes local v2 events. v2 never contains arguments, details, notes, paths,
  identifiers, or creative content; legacy v1 files are never uploaded.
