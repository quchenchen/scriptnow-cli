# ScriptNow CLI

An agent-friendly command-line client for the [ScriptNow](https://sn.igeewa.com)
creative writing platform. Authors and screenwriters can work with an AI agent
to develop projects, review planning candidates, write chapters or scenes, and
export their work.

## Install

Requires Python 3.10 or later. Use a virtual environment or a CLI tool installer:

```sh
pipx install scriptnow-cli
# Alternatively, inside a virtual environment:
python -m pip install scriptnow-cli
```

The command is `scriptnow`; the distribution name is `scriptnow-cli`.

## Get started

```sh
scriptnow --version
scriptnow agent-guide --json
scriptnow doctor
scriptnow login --host https://sn.igeewa.com --email you@example.com
scriptnow guide --medium novel
# For screenwriting:
scriptnow guide --medium script
```

Enter your password at the hidden terminal prompt. A ScriptNow account and
appropriate project access are required; installing this client does not create
an account or grant service credits.

## For AI agents

Always read `scriptnow agent-guide --json` before operating the platform. Use
the current command's `--help` for arguments and schemas. Read platform state
before writes and read it back after success. Do not invent project IDs or
treat local drafts as saved platform content.

- Create each author's own project and retain the ID returned by the platform.
- Co-create planning locally, submit candidates through the appropriate
  `propose` commands, and obtain the author's explicit decision before adoption.
- Follow direction, story core, blueprint, synopsis, rough outline, chapter or
  episode outlines, then prose. Check planning quality and writing readiness.
- By default, invoke the platform's writing agent for chapters and scenes.
  Follow the returned run ID; do not repeatedly start the same generation.
- Show complete candidate content and record the human's actual decision using
  the current review protocol. Never infer adoption from silence.

Novels and scripts use separate domain commands and formats. The platform is
the source of truth for adopted content and continuity.

## Distribution and updates

The platform also distributes versioned wheels and Windows installers at
[its download host](https://sn.igeewa.com/downloads/scriptnow-cli/).
`scriptnow self-upgrade` checks the platform distribution first; GitHub is a
fallback. PyPI releases may appear on a different schedule. Automatic updates
are opt-in with `scriptnow config on`.

See the [full CLI documentation](https://github.com/quchenchen/scriptnow-cli#readme)
and [platform guide](https://sn.igeewa.com/cli). Licensed under MIT.
