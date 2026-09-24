"""Reading a JSON input file that was named on the command line.

Why this module exists (2026-09-22)
-----------------------------------

Commands that take a `FILE_PATH` mostly read it the same way, and the long-standing
inline shape is:

    raw = Path(file_path[1:] if file_path.startswith("@") else file_path).read_text(
        encoding="utf-8"
    )

Four of them - `script propose`, `novel propose`, `script planning-quality` and
`novel planning-quality` - omitted the `startswith("@")` half entirely and just
wrote:

    raw = Path(file_path).read_text(encoding="utf-8")

`script propose` and `novel propose` are the pair the agent guide tells an author
to run on the planning back-fill of every project, with `@cores.json` /
`@storymap.json` spelled out - so the exact form the guide prints was read as a
file whose name begins with `@`. The author got a raw `FileNotFoundError`
traceback: the wrong message (the file was right there), and an escape from the
`--json` error contract.

`@` is a marker, not part of the name. It is the CLI's own convention - see the
37 inline `startswith("@")` sites this module is meant to replace - so a value
that begins with `@` names the path after it. A real file whose name begins with
`@` stays reachable: `@@name` strips to `@name` (the marker comes off at most
once), and `./@name` never carries the marker to begin with.

None of these failure modes is a crash: at the call sites that use this module,
an unreadable file, a file that is not valid UTF-8 and a file that is not valid
JSON all leave through `click.ClickException`, so they reach an agent as
`{"ok": false, "error": {...}}`.

That last sentence is a statement about these call sites, **not about the whole
CLI**. Other commands still read their file arguments with a bare
`Path(...).read_text()`, so a missing file there is a raw `FileNotFoundError`
traceback an agent cannot parse - `review preview` is one, and it is reachable
straight from the guide's step 4. `@` handling is already correct at those sites
(measured: the `@` and bare forms send byte-identical requests); what is missing
is the error envelope. Bringing them in line is a separate, wider pass.

Scope: this batch wires the four `FILE_PATH`-positional commands through
`read_json_object` and the two `--resume-from` options through
`strip_file_marker`. The other inline sites already handle `@` correctly; they
should still converge here for the error contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

#: The CLI-wide marker meaning "the rest of this value names a file to read".
FILE_MARKER = "@"


def strip_file_marker(value: str) -> str:
    """Return `value` with the `@` file marker removed.

    Stripped at most once, so `@@name` names the file `@name` - which is as close
    as this convention gets to escaping the marker.

    Returns a **string** rather than a `pathlib.Path` on purpose. Callers in
    `scriptnow_cli` read through that module's own `Path`, which is the seam the
    batch tests replace to hand the command a fake progress file; returning a
    `Path` here would bind `pathlib.Path` inside this module and quietly read the
    real disk instead.

    Args:
        value: The raw argument as Click handed it over.
    """
    if value.startswith(FILE_MARKER):
        return value[len(FILE_MARKER) :]
    return value


def resolve_input_path(value: str) -> Path:
    """Return the path `value` names, with the `@` file marker removed.

    The `Path`-returning convenience over `strip_file_marker`, for callers that
    read through a local `Path` of their own.

    Args:
        value: The raw argument as Click handed it over.
    Returns:
        The path to read. Not checked for existence here: the read is where a
        missing file should turn into the caller's error, not this function.
    """
    return Path(strip_file_marker(value))


def read_json_object(file_path: str) -> dict[str, Any]:
    """Read a JSON **object** from a `FILE_PATH` argument.

    Args:
        file_path: The raw argument; a leading `@` is stripped.
    Returns:
        The parsed object.
    Raises:
        click.ClickException: The file cannot be read, is not valid UTF-8, is
            not valid JSON, or does not have an object at its root. All four go
            through Click so the `--json` envelope stays the single error
            contract.
    """
    path = resolve_input_path(file_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        # Covers missing, unreadable and "that is a directory" alike: to the
        # caller they are one mistake - the path does not lead to a readable file.
        raise click.ClickException(f"读取文件失败：{error}") from error
    except UnicodeDecodeError as error:
        # A separate clause, not folded into the `OSError` one above: a badly
        # encoded file is not an I/O failure, and `UnicodeDecodeError` is a
        # `ValueError`, so the `OSError` branch never sees it. Measured on the
        # first version of this module (2026-09-22 review): `script propose
        # --json … @bad.json` with a `\xff` byte inside still exited 1 with an
        # empty stdout - the very traceback-instead-of-envelope escape this
        # module exists to close. Deliberately not `errors="ignore"`/`"replace"`
        # and no encoding sniffing: silently repairing or guessing would change
        # the author's bytes, and this path only ever wants to say the file is
        # not UTF-8.
        raise click.ClickException(
            f"文件须为 UTF-8 编码，无法解码 {path}：{error}"
        ) from error
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise click.ClickException(f"JSON 解析失败：{error}") from error
    if not isinstance(data, dict):
        # Every caller indexes into the result, so accepting a list here would
        # only move the failure somewhere less useful.
        raise click.ClickException("JSON 根必须是对象")
    return data
