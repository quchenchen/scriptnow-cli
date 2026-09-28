# 选择平台时的衔接

只有作者选择平台保存或明确要求继续已绑定平台项目，才执行本页。先 `scriptnow agent-guide --json`，核对当前命令与 `--help`。本地方法读取不需要此步骤。没有项目 ID 就先确认要保存到哪个项目；不要自行把所有本地草稿或原著上传。

使用 `scriptnow project create --help` 与 `scriptnow translate create --help` 核对建项参数，只在作者授权后建立 novel / cross_cultural_recreation 项目及归化记录。既有项目先 `translate state`，不得重复创建。平台未部署本契约、登录失效或命令不存在时，保留本地工作并如实说明未写入，不用其他域命令或旧生成接口冒充成功。

本地局部试写不代表满足平台来源完整覆盖门禁；准备接入时按实时 contract 补足阅读，不伪造 complete。自由模式的作者认可也不自动成为平台采纳凭证。

平台内置归化方法会随项目级 creative-skill-plan 返回；个人写作方法配置与其健壮性门禁仍独立有效。内置方法已选中不能冒充个人 Skill 已挂载或已过门禁。

# 故事归化：本地细读、文化重构、候选回填

先加载 `webnovel-localization` 或 `scriptnow translate method --section all --json`。方法读取无需登录和项目；自由本地分析、试写与修订不要求保存平台。仅在作者选择平台或要求继续已绑定项目时使用下面的候选链。

只用于小说归化项目。原著文件、抽取全文、扫描图像、章节切分和逐页阅读记录留在当前 Agent 环境；平台只保存有边界的源身份、覆盖自证、故事分析、文化决策和创作候选。`scriptnow_read_document` 返回 `truncated` 时继续按 offset 读取；扫描无文本层、缺页或读取失败必须如实列在自证里，不能把读到首页称为通读。平台只能检查自证形状，不能替作者证明已读完。

先把原作里的关键元素写成“它在故事中做什么”：谁因什么制度、关系或期待受阻，采取什么行动，改变谁的处境。再与作者确定目标读者、类型承诺、发行场景和背景边界。目标语言不自动决定背景地点。对每个真正需要处理的文化载体，选择保留、解释、迁移或重构；迁移或重构须写明新载体和人物动机、因果变化。触及作者保护项时先提交冲突决策候选，等作者明确采纳。不要凑满类别或固定国家、章节数、字数、评分轮次。

contract 若返回缺失/过期依赖或未采纳前序工作包，先只读解释并处理前置，不领取写资格或盲试提交。

执行顺序：`translate state <作品号> --json` 看当前已采纳基线；`translate contract <作品号> <kind> --json` 读必需依赖与作用域并原样保存为 `@contract.json`；`run claim <作品号> <kind> <资源号> --domain novel --task-key ... --attempt-key ... --json` 领取本次候选写资格；若为 recreation_unit，先按下文用同一凭据真实读取 facts 与 methods 并确认准备就绪，再开始本轮正文创作；Agent 本地创作 `@file.json`；`translate propose <作品号> <kind> @file.json --contract @contract.json --execution-token ... --request-key ... --json` 回填；再次 `translate state` 回读候选。`recreation_unit` 的资源号和 `--work-package-key` 都是已采纳方案中的工作包键，其契约用 `translate contract <作品号> recreation_unit --work-package-key <键> --json` 取得。重试同一请求须保留同一契约文件、请求键、凭据和内容；候选回执只证明已保存，不证明已采纳。

成果依故事需要推进：源故事模型候选（`source_identity` 含 title 与 `sha256:<64位十六进制>` 指纹；`coverage_attestation.units[]` 写本地 unit_id/length，read_ranges[] 写 unit_id/start/end，anchor_refs[] 写 unit_id/start/end/digest/summary，并如实写 complete/truncated/unread_ranges；连贯叙事写进 `story_summary`）→ 作者采纳 → 目标意图候选（`target_intent` 连贯叙述）→ 策略候选（`story_proposal` 连贯叙述，可附 `transformations`）→ 对实际迁移/重构的载体提交映射候选 → 对实际触碰的保护项提交决策候选 → 选文化或因果风险最高的片段试写（`unit_title`、`rationale`、`target_language_draft`）→ 整书方案（`target_story_bible`、有序 `work_packages`）→ 串行逐章候选。每个 transformation 需要 `source_element`、`narrative_function`、`treatment`、`causal_reason`；relocate/reconstruct 还需 `target_carrier`。映射须解释旧元素的叙事功能、目标承载和因果理由。试写是可修改的实验，不把模拟审读称为真人读者验证。

逐章前用同一 `recreation_unit` 执行凭据分别调用 `translate state <作品号> --unit-key <键> --read-kind facts --execution-token ... --json` 和 `--read-kind methods`；服务端回执证明本次 attempt 真正读取了已采纳事实、前序单元和所选方法全文。`material_digest` 来自 methods 回执，随 `translate propose ... --material-digest ...` 提交。归化工作包不是普通 novel chapter ID，方法选择按项目 scope 解析；读取并不证明模型实际应用方法。上一工作包未采纳、修订后版本已变、方法未就绪或未取得两种读取回执，正式章节候选被拒绝。

采纳前用 `translate state` 找到候选号与完整内容；向作者展示原文分析、目标方案、试写或章节候选的完整版本及受影响依赖。章节候选先 `translate review-unit <作品号> <候选号>`，需要人工改稿可用 `translate revise-unit <作品号> <候选号> @revision.json --request-key ...` 另存候选。先 `translate review-preview <作品号> <候选号> --kind artifact|unit --json` 获取服务端绑定的完整候选与 packet_id。向作者展示后，明确保留才执行 `review confirm <packet_id> --decision retain --evidence "<作者原话>"` → `review claim <packet_id>`，再 `translate adopt <作品号> <候选号> --kind artifact|unit --review-token ...`。写资格绝不自动采纳。上游改变后查看 `stale_dependencies`，旧候选不能当作当前版本采纳；`translate manuscript` 和 `translate export -o 稿.docx` 可按指定基线交付历史稿，并明确需复核状态。旧 `/analyze-source` 已停用；其余平台生成只作作者显式选择的后台后备，仍产候选并走同一人审。
