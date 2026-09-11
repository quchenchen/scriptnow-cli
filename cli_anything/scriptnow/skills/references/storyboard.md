# 分镜交付


- Storyboarding is also backfill-first: read `storyboard state` and `assets`,
  run `source-preflight` before every append, register the source, then locally extract and author a valid `ScriptOut` under
  the mounted Skills. Return it with `storyboard propose`. Platform analysis and
  generation are fallback-only; continuity is a director/user decision. Never
  guess an unknown episode range. Use the audited `source-range` or
  `source-revoke --confirm` path instead of database access. Then use
  `storyboard candidate-preview` to review the exact saved candidate; only a
  later explicit decision may flow through `review confirm` → `review claim` →
  `storyboard adopt --review-token`.

- Scene planning boards are explicit, single-scene platform actions: use
  `storyboard scene-board list|inspect`, then `upload PROJECT SCENE FILE --layout auto --mode annotated` or
  `generate PROJECT SCENE --layout auto --mode annotated` only when requested. The server derives layout,
  pages, shot IDs, and digest; never write `shot.frame_refs` or bypass the API. Inspect
  `reference_validation`: when the image proxy rejects asset images, the platform preserves the failed Attempt
  and retries in a new no-reference Attempt. Re-upload rejected images before claiming visual consistency.
  Generated references and boards are workspace-persisted; the platform encodes local media as base64 for later
  multi-reference generation. Agents must use returned platform URLs and never inspect workspace paths directly.
