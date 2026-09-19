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

## 自动批次创作（agent+CLI 侧串行编排）

- 只在**该作品第一章（剧本：第一场）已有已采纳正文**、且**项目已挂载通过门禁的方法论 Skill**
  之后才开批次；两条缺一即停，不降级执行。
- 一批 2–3 个单元：`chapter batch <作品号> --chapters <id>,<id>`（剧本侧
  `scene batch <作品号> --scenes ...`）。1 个用 `chapter/scene generate`；> 3 必须拆批。
- CLI 逐单元串行跑（生成 → `run status` 轮询到终态 → 下一个）。不要并发、不要起 subagent
  并行写——上下文割裂会让设定漂移、伏笔失联。
- **批次只产候选，绝不自动采纳。** 全部完成后必须让作者逐单元读到完整可读正文
  （`chapter show <项目号> <章号> --plain` / `scene show`），给出明确决定后再走
  `review confirm` → `review claim` → 带 `--review-token` 的 `adopt`。
- 中断续跑：`--save-progress <文件>` 保存失败清单，`--resume-from <文件>` 续跑。
