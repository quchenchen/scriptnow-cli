# 正文创作


- 逐章/逐场创作双模式（dual-mode chapter/scene creation, the user must choose
  explicitly and the platform does not block): final prose is authored by a
  real in-platform AgentScope Agent by default. Platform-led is the default and
  recommended — `chapter/scene generate` produces a platform candidate →
  `review preview` for human review → `adopt`. Only when the user explicitly
  chooses local creation does the Agent write prose locally, backfill the
  candidate via `chapter propose` / `scene propose`, then `review preview` →
  `adopt --human`. Without an explicit choice, platform-led applies; never
  default to or steer the user toward local-led writing.

- For Novel `chapter propose`, each `block.text` is only that block's prose: never
  embed another `blocks` JSON document in it. Ordinary JSON text is allowed; if
  the platform rejects embedded Novel blocks, repair from its detail and regenerate.
