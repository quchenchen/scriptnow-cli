# 正文创作


- 正文默认由 dsh 创作。先以 `run claim` 领取绑定作品、单元和本次尝试的写资格，
  再读取平台已采纳事实与连续性；`skill selected <作品号> --unit-id <单元号>
  --json` 返回本轮选中方法的全文、引用和 `material_digest`，必须真实读取并核对
  `execution_ready`。写好正文后用 `chapter/scene propose --execution-token
  <写凭据> --material-digest <方法摘要>` 回填候选；方法摘要与当前选中内容不一致会拒收。
  用 `review revision-preview`
  展示平台实际保存的版本；作者明确决定后经 `review confirm`、`review claim`
  和带审阅凭证的 `adopt --human` 采纳。平台 AgentScope `generate` 只作显式
  后备，不作为默认引导。取消或接管只撤销旧尝试的写资格；若引擎尚未停止，
  界面必须如实显示，旧尝试不得再产生新候选，同一请求的已有回执仍可取回。

- 两个审阅包**不可互换**：提交包绑定 `chapter`/`scene` + 单元 ID
  （`review body-preview <medium> <作品号> <单元号> <文件>`），采纳包绑定
  `chapter_revision`/`scene_revision` + 版本号
  （`review revision-preview <medium> <作品号> <版本号>`）。拿错包去提交 / 采纳
  必然被拒（409），并且要重新走一遍审阅——不要把两枚 token 混用。

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
  `review revision-preview <medium> <项目号> <版本号>` → `review confirm` →
  `review claim` → 带 `--review-token` 的 `adopt`。
- 中断续跑：`--save-progress <文件>` 保存失败清单，`--resume-from <文件>` 续跑。
