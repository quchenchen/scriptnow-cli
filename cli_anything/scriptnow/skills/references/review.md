# 候选预览与人工决定

提交候选或采纳之前读取，严格区分两次决定。

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

