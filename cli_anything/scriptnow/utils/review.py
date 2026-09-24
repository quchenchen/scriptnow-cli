"""Canonical content digest and review-preview payloads.

Why this is a *local* copy instead of an import
----------------------------------------------
The CLI ships as a standalone wheel and must not depend on the backend package
(`scriptnow.backend`), so the canonical digest is mirrored here rather than
imported.

The mirror is exact, and it has to stay exact: this digest is what binds a
human's review decision to the content that later gets submitted. The platform
recomputes it from the visible content and rejects a mismatch, so a drift
between these two implementations does not fail loudly at review time — it
makes every legitimate submission return `reviewed content changed`.

Server side of the pair (change both in the same commit):
    scriptnow/platform/creative_review.py :: canonical_content_digest
"""

from __future__ import annotations

import hashlib
import json


def canonical_content_digest(value: object) -> str:
    """sha256 over the canonical JSON encoding of ``value``.

    ``sort_keys`` makes key order irrelevant, ``ensure_ascii=False`` keeps CJK
    text stable, and ``default=str`` avoids an exception on non-JSON scalars
    (e.g. datetimes) turning a digest mismatch into a crash.
    """

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def review_preview_payload(
    *, title: str, content: object, human_action: str,
) -> dict[str, object]:
    """Build the preview the platform recomputes its digest against.

    Keeping ``content`` in one known place is what lets the server verify that
    the human saw exactly what is being reviewed; every preview the CLI
    registers must go through here so none of them arrives without it.
    """

    return {"title": title, "content": content, "human_action": human_action}
