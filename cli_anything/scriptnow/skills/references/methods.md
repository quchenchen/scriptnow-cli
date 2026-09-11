# 作品写作方法

## 以创作决定形成方法

作品 Skill 是作者持续完善的创作主张与决策依据。先理解作者希望作品带来什么体验、愿意为此作何取舍，再提炼方法。正反例只用于必要的局部澄清或接口所需的证据，不作为共建的主流程，不让作者反复选范文或填写标签问卷。

从灵感、核心、蓝图、规划和审读对话中持续收集作者已经明确的判断。正文前汇总确认；已有项目从当前方法和已采纳事实继续，不重新盘问。项目事实始终从平台读取，不复制成一份平行人物设定或剧情库。

## 共建循环

1. **创作追求**：从作者的话中提炼作品要表达什么、读者应经历什么、最不能牺牲什么。信息不足才问当前最关键的问题，不要求作者先提出完整理论。
2. **真实决定**：选取当前规划或候选中确实需要判断的一处，例如何时揭示真相、是否让人物承担代价、结尾该收束还是留下行动。说明不同处理会得到什么、失去什么，让作者决定；不为凑教学材料额外制造剧情。
3. **条件性原则**：复述作者选择背后的理由，提议它是否可以指导后续类似情境。区分本处选择与长期原则，不能未经确认把一次决定推广到全书。
4. **边界与取舍**：明确何时适用、何时不适用，以及它和其他追求冲突时先保住什么。不默认“更快”“更多冲突”“更强反转”就是更好。
5. **实际检验**：在作者已要求的后续候选与审读中观察效果，再讨论保留、缩小适用范围或修订。检验是作品推进的一部分，不额外启动未经请求的测试创作或自动采纳。

每轮只处理当前最重要的判断；作者已经给出充分理由时直接整理，不机械走完五轮追问。

## Agent 的观察维度，不是作者的问卷

- **核心追求**：主题与情感落点如何通过人物选择、关系变化和代价体现。
- **人物与因果**：什么驱动人物行动，选择怎样产生后果；哪些推进方式会损害可信度。
- **信息与视角**：读者、人物各自知道什么；揭示或保留信息如何影响行动与体验。
- **节奏**：当前叙事阶段和单元功能需要蓄势、推进、停留还是释放；为什么。
- **钩子与兑现**：未完成的行动或问题是否值得继续，是否来自已建立的因果，如何承接与兑现。允许有意义的收束，不强迫每章悬崖结尾。
- **表达**：叙述声音、对白、内心与动作怎样服务人物和体验，而不是只规定长短句。
- **取舍**：刺激性、可信度、情感完整性等发生冲突时，作者的优先顺序是什么。

小说侧重阅读经验、视角与叙述声音；剧本侧重视听信息、可表演行动、场次功能及时间容量。两域方法分别整理，遵守项目已选格式。

## 一个决定怎样变成原则

当前情节中，主角即将发现真相。Agent 可以说明：“此刻揭示，会让下一段转向他怎样承担后果；延后揭示，可以让他在误判下作一次有代价的选择。你更想写哪一种经历？”仅在这些处理确实符合当前作品时使用这种讨论。

若作者选择后者并说明理由，不提炼成“真相一律晚揭示”，而提出待确认的原则：“保留信息应促成人物选择与代价；如果只是延长等待，没有新的行动，就应揭示。”适用边界来自作者决定，不自定揭示章数或强制悬念密度。

## 汇总为可读的创作主张

在需要保存时，向作者展示简洁草案：核心追求、已确认的原则、适用边界、冲突时的优先级、实际决定依据，以及仍待验证的问题。重要原则连接到相关单元或决定，便于审读时回看，不把未经确认的建议写成定论。

未解决的想法保留为待讨论材料，不混入生效指令。若它影响当前必需的写作准备，先讨论清楚再提交；否则继续按已确认方法推进。节奏和钩子的要求应说明服务什么体验，而非堆叠数量指标。

## 与现有 CLI 契约兼容

主流程使用 `scriptnow skill setup <project_id> --json` 获取推荐选项和 answer_schema。把作者已确认的选择对应到实际支持的字段，将创作主张、条件性原则和边界放入 `custom_instructions`。推荐值不是作者决定；没有对应意见时不能静默替作者接受全部预设。

剧本的 `source_candidate` 及 Method DNA 选项仅按实时 schema 使用，由服务端编译、评估和绑定。不得自行新增 decision_log、principles 等 API 字段，不在 CLI 或本 Skill 内编译 Method DNA、判断规则启停或拼接创作 prompt。

深度通道 `skill craft` 当前仍要求六个非空字段。先运行 `scriptnow skill craft --domain novel --json`（剧本使用 `--domain script`）读取实际契约，再把自然对话所得映射进去：

| 现有字段 | 从已确认讨论整理的内容 |
|---|---|
| work | 作品方向与核心追求 |
| craft | 条件性创作原则、节奏与钩子策略、取舍顺序 |
| voice | 已确认的叙述与表达判断 |
| continuity | 因果、人物、信息边界和衔接要求 |
| evaluation | 如何观察原则是否有效、何时需要调整 |
| examples | 对已讨论的具体处理，归纳作者认可的做法与明确排除的做法，并说明理由和适用情境 |

`examples` 是兼容现有深度接口的必填字段，不代表必须组织“正反例选秀”。优先从真实已确认的创作取舍提取；不得编造作者认可、不认可的例子，不能塞“无”“同上”绕过校验。缺少必要证据时，仅针对当前作品的一处未明判断补充讨论；如果无法得到完整答案，暂不提交 craft，可按 setup 的实际能力继续。任何通道都不得绕过服务端质量检查。

作者确认完整草案后，才使用相应提交命令与确认参数。核对回执中的质量检查、实际挂载、精确版本；剧本核对 Method DNA 绑定。保存本地笔记、创建成功、挂载成功与本单元实际启用是不同状态，不混为一谈。

## 随作品生长，保持版本可追溯

写前通过 `ready-check --unit-id` 读取当前单元的已采纳阶段、功能和方法准备；剧本必要时用 `method-resolve --unit-id` 查看服务端启用/停用规则与原因。不能从章节百分比推测阶段，不能只凭已挂载就声称规则已应用。

审读时依据正文观察：人物选择是否体现创作追求、快慢是否服务单元功能、钩子是否有因果与承接。方法效果不等同于关键词命中或机械计数。

作者提出修改时，先区分局部修改与长期方法调整。长期调整须展示变更、理由和影响范围，由作者确认后经现有平台版本机制更新。先查看当前方法和支持的更新接口，不重复新建或叠加矛盾挂载；不自动重写此前已采纳正文。已确认的原则也可修订，但需要保留其来由和版本依据。

- Skill delivery is progressive: use `skill mounts` and normal `skill detail`
  summaries first. Full personal instructions require an explicit user request
  and `skill detail --include-instructions`; never fetch them speculatively.

- If a mounted Skill is wrong or blocks generation, do not archive the global
  Skill or rebuild the project. Only after explicit user approval run `skill
  unmount <project_id> <skill_id> --confirm --json`; it disables that one
  project mount, reads mounts back for verification, and leaves other projects
  and versions untouched. A project with no enabled methodology Skill is not
  ready for writing.

- `skill setup <project_id>` is the default pre-writing co-creation path: fetch
  `skill setup <project_id> --json` for server-recommended presets (dialogue
  styles, pacing, forbidden words; script domain also carries Method DNA axes),
  walk the author through the choices in editor language, then submit
  `--answers @answers.json --confirm --json`; the server compiles and mounts and
  the receipt must show `gate_passed`/`mounted` (script: `method_dna` binding).
  `skill craft` remains the deep six-question channel; old personal Skills keep
  working.

- `skill craft` preflight, its creation receipt, the mount gate, and runtime
  must resolve the same complete methodology reference; never replace it with a
  summary or leak a cross-tenant detail.

- For Script writing, read the project-locked `script_format` before loading a
  personal Skill. Vertical short-form, Chinese screenplay, and Hollywood each
  have distinct generation, frontend, and export contracts. A personal Skill
  extends the selected contract; it never overrides it or merges dialogue
  across an intervening action block.

- Creating a script project (`project create --medium script`) defaults to
  `script_format=chinese-short` (vertical short-drama storyboard format) unless
  `--script-format chinese|hollywood` is passed explicitly. In an interactive
  terminal with no `--script-format`, the author is prompted to choose the
  format before creation (never silently locked); pass a value from the three
  supported formats and read it back from project state before writing.

## Unified creative Skill plan

CLI, Creator and creative runs use the server creative-skill-plan. Before writing, use ready-check --unit-id <unit-id> to inspect the adopted narrative stage, unit function, personal and built-in methods, and execution readiness. Submit narrative_stage and unit_function with episode/chapter outline candidates; adoption activates them. Never infer stages from episode percentages. Pacing advice is not a veto; selection, reading and application are distinct evidence.

For Script Method DNA, use only the server-backed `skill method-current`,
`method-compile`, `method-compare`, `method-bind`, and `method-resolve` commands.
The CLI must not compile rules, infer activation, or build prompt fragments. Before
writing a unit, inspect `ready-check --unit-id` or `skill method-resolve --unit-id`
for active and inactive rules, reasons, required reads, and the verification plan.
