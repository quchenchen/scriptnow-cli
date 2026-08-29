# scriptnow-cli

**从灵感到成书 —— agent-native 创作 CLI**

[English](README.en.md) · [中文](README.md)

> 面向**命令行用户与 AI Agent**：建项目、一书一 Skill 解读、小说/剧本创作、Skill 进化、
> 封面生成、导出交付，全部可用命令行完成。非命令行创作者请使用网页端。

基于 [CLI-Anything](https://github.com/HKUDS/CLI-Anything) 模式的一站式命令行，覆盖**小说与剧本
两条创作域（dual-domain）**。所有命令支持 `--json` 结构化输出，供 AI Agent 直接编排。

## 特性

- **双域创作链**：小说（卷×章）与剧本（剧集×场次）共享「项目 → 方向 → 规划 → 创作 → 交付」，
  但规划结构与创作循环按域细化，Agent 按域编排。
- **样本不传平台**：一书一 Skill 用 `interpret local` 在 Agent 本地解读作品、产出方法论后回传，
  平台只接收最终 Skill，不接触作品原文；改编稿用 `chapter propose` / `script scene-propose` 本地回传。
- **Skill 能力与版本进化**：`skill growth` 从创作实绩提炼方法论、评估后发布新版本；
  `skill canary` 对新版本做灰度决策（retain / limit / need_evidence / rollback）。
- **管理员支线**：`admin` 命令组仅 `is_admin` 可用（非管理员 403）；token 消费、额度与财务命令
  一律不纳入 CLI。
- **Token 预算控制**：本地导入（propose / scene-propose / interpret local）带 `--budget` 预估拦截。
- **会话自动续期**：一次 login 后 access 过期自动 refresh 续期（30 天），Agent 长会话无需反复登录。
- **Agent 操作契约**：`scriptnow agent-guide`（--json）输出连接平台唯一准则——平台是事实源、规划回填优先、集纲/章纲质量门禁、生成后台轮询、StoryMap 修订需用户明确授权。
- **新增卷章 = 纯追加**：`storymap append-volume` / `append-chapters` 只尾部新增，已有卷章完全不动；旧结构自动归档可回溯。
- **审读是 Agent 自身能力**：平台不提供固定 rubric，Agent 读正文、自行判断、用 `--feedback` 驱动修正。

## 安装

要求 Python 3.10+。macOS/Linux 系统 Python（Homebrew、python.org）受 PEP 668 保护时，
请先在虚拟环境中安装：

```bash
# 从源码（editable，推荐开发使用）
git clone https://github.com/quchenchen/scriptnow-cli.git
cd scriptnow-cli && pip install -e .

# 优先生产源直装 wheel（sn.igeewa.com，最稳，不依赖 git）
pip install https://sn.igeewa.com/downloads/scriptnow-cli/scriptnow_cli-0.3.69-py3-none-any.whl

# 或从 GitHub 最新代码直接安装（codeload 直连，无需 clone）
curl -sL -o /tmp/scriptnow-cli-latest.tar.gz https://codeload.github.com/quchenchen/scriptnow-cli/tar.gz/refs/heads/main
pip install --force-reinstall /tmp/scriptnow-cli-latest.tar.gz
```

## 登录

```bash
scriptnow login --host https://sn.igeewa.com --email 你的账号   # 交互式隐藏输入密码（或 --password-stdin / SCRIPTNOW_PASSWORD）
```

会话保存到 `~/.config/scriptnow-cli/session.json`（仅 Cookie，不含密码，权限 0600）。

**Agent 排查入口：先跑 `scriptnow doctor`** —— 输出 CLI 版本、会话文件实际路径、
是否登录、账号、平台地址与连通性。任何「登录失败 / 找不到配置 / 409 / No such option」
先 `scriptnow doctor` 定位，不要猜配置位置。`SCRIPTNOW_CLI_CONFIG` 可覆盖会话路径；
多环境共用同一会话文件时登录一次全部生效。
也可用 `SCRIPTNOW_BASE_URL` / `SCRIPTNOW_EMAIL` / `SCRIPTNOW_PASSWORD` 环境变量。

## 快速开始（双域）

**前置：Skill 是逐章/逐场创作前的必然门禁（须健壮性完善）**——创作意图明确且项目落地后：

1. 与用户规划专属方法论（可多轮，直到代表作品意图）；
2. **健壮性完善**：试写样本章节/场次检验 Skill 约束力，诊断规则缺口与歧义，迭代加固；
3. 在平台创建并挂载到项目，`skill mounts <pid>` 核实后，才能启动正文逐章/逐场创作。

```bash
scriptnow skill mounts <pid>                  # 项目已挂载哪些 Skill？无 → 走下方创建流程
# 一书一 Skill 蒸馏（样本不传平台）：interpret local 手稿.docx --spec → 本地解读+多轮完善 → --submit @skill.json --project-id <pid>
#   或 个人 Skill：skill create --domain novel|script ... → skill mount <pid> <skill_id> <version_id>
```

**小说（卷 × 章）**

```bash
scriptnow project create --name 新作 --medium novel --volume-one 1 --volume-two 15 --chapter-target-words 1200
scriptnow project direction <pid> --apply @direction.json --review-token <方向审阅凭证>
# 规划（候选提交与采纳分开；采纳前用 candidate-preview 展示平台事实）
scriptnow novel propose <pid> cores @cores.json --review-token <提交审阅凭证>
scriptnow review candidate-preview novel <pid> story_core_candidate <candidate_id>
scriptnow novel adopt-core <pid> <candidate_id> --review-token <采纳审阅凭证>
scriptnow novel propose <pid> blueprint @blueprint.json --review-token <提交审阅凭证>
scriptnow novel propose <pid> storymap @storymap.json --review-token <提交审阅凭证>
scriptnow novel orchestrate <pid> --skip-adopt               # 只读编排
# 创作循环（Agent 审读驱动）
scriptnow book <pid>                                          # 编排原语：各章已采纳/待生成/候选待审
scriptnow chapter show <pid> chapter-1-1 --plain
scriptnow chapter generate <pid> chapter-1-1 --feedback "你的意见"  # 后台，run status 轮询
scriptnow chapter adopt <pid> chapter-1-1 <rev> --human --review-token <定稿审阅凭证>
# 改编稿本地回传：chapter propose <pid> chapter-1-1 --file @blocks.json --review-token <提交审阅凭证>
```

**剧本（剧集 × 场次）**

```bash
scriptnow project create --name 新剧 --medium script
scriptnow project direction <pid> --apply @direction.json --review-token <方向审阅凭证>
# 规划
scriptnow script propose <pid> cores @cores.json --review-token <提交审阅凭证>
scriptnow review candidate-preview script <pid> story_core_candidate <candidate_id>
scriptnow script adopt-core <pid> <candidate_id> --review-token <采纳审阅凭证>
scriptnow script propose <pid> blueprint @blueprint.json --review-token <提交审阅凭证>
scriptnow script propose <pid> storymap @storymap.json --review-token <提交审阅凭证>
# 创作循环
scriptnow script scene-list <pid>
scriptnow script scene-show <pid> scene-1-1 --plain
scriptnow script scene <pid> scene-1-1 --feedback "你的意见"  # 后台，run status 轮询
scriptnow script adopt-scene <pid> scene-1-1 <rev> --human --review-token <定稿审阅凭证>
# 改编稿本地回传：script scene-propose <pid> scene-1-1 --file @blocks.json --review-token <提交审阅凭证>
```

**交付**：`cover generate` 封面 → `export create --units chapter-1-1|scene-1-1` → `export download -o 书.docx`。
剧本 `--form working` 输出每场制作信息；内部制作契约暂不作为编剧交付文件导出。

## 命令组

| 组 | 用途 |
|----|------|
| guide | 聚焦式新手创作（outline-first 逐层深入）：--step 1..12 / --medium novel\|script / --pulse / --resume / --steps / --complete / --status |
| review | 人类审阅：preview（本地候选）/ candidate-preview（平台规划候选）/ status（读取反馈）/ confirm（登记一次决定）/ claim（Agent 领取凭证）；长内容页面可选 |
| authorize | 签发一次性「人工决策授权令牌」（对话内文字授权通道，复用登录会话不要求重新登录）：`--chapter/--scene` 限定目标，`--digest` 绑定用户已读内容；token 供 `chapter adopt --human --token` / `scene adopt --human --token` 完成人工定稿 |
| project | 项目管理：创建 / 列表 / **files（项目文件）** / 上传素材 / **use（设为默认项目）** / 删除 / 方向（--apply 客户端梳理回填 / --inspire 平台灵感） |
| interpret | 一书一 Skill：go（一键解读）/ local（Agent 本地解读，样本不传平台）/ create / read / status / decide |
| book | 全书托管创作规划（Agent 编排原语，含 Skill 支撑侦测） |
| chapter | 小说章节：**outline（单章补纲）/ outline-batch（批量补纲）/ outline-check（章纲自查）/ outline-example（章纲结构示范）/ bible-example（人物圣经范例）** / list / show / generate / quality（--standard 内容/备案/千部）/ adopt / propose（本地回传） |
| scene | 剧本场次（chapter 的剧本侧对称）：list / show / generate / adopt（alias of script adopt-scene）/ propose（本地回传）/ batch（批量串行）/ quality / diff |
| storymap | 跨域共享结构命令（novel+script 通用）：state / generate / **append-volume（新增卷，纯追加）** / **append-chapters（新增章，纯追加）** / **append-phase（按叙事阶段提交下一未完成阶段，阶段=卷）** / **phases（按叙事结构推导的阶段计划预览）** / adopt（**高危，需 --confirm**） / **structures（内置 + 结构库已存模板）** / **structure-save（命名结构存库，--description/--medium 元数据）** / **structure-delete**；隔离重建走各域 storymap-rebuild-* 链 |
| novel | 小说创作链：story-cores / blueprint / adopt-core / adopt-blueprint / bootstrap / outline / outline-adopt / outline-status / graph（叙事图谱对账）/ planning-quality / planning-status / ready-check / propose（本地 JSON 导入）/ orchestrate / **rough-outline 平铺链：rough-outline / adopt / check / example** / **storymap-rebuild 隔离重建链：start / rebuild / rebuild-phase / rebuild-phase-preview / rebuild-check / rebuild-propose** / **storymap-archives / storymap-archive（旧结构归档读取）**；重建须先采纳小说粗纲，逐阶段=卷区间 |
| script | 剧本创作链：outline / outline-adopt / outline-status / episode-outline / **episode-outline-check / episode-outline-example** / **bible-example** / state / story-cores / blueprint / adopt-blueprint / adopt-core / storymap / **storymap-phases / storymap-append-phase** / adopt-storymap（高危）/ planning-quality / **ready-check** / propose（本地 JSON 导入）/ adopt-scene / scene / scene-list / scene-show / scene-propose（--help-format/--example；--auto-adopt 已停用）/ scene-batch / scene-quality / scene-diff / quality-report / **rough-outline 分阶段链：-start / -phase / -progress / -propose / -phase-preview / -check** / **storymap-rebuild 隔离重建链：start / rebuild / rebuild-phase / rebuild-phase-preview / rebuild-check / rebuild-propose** / **storymap-archives / storymap-archive（旧结构归档读取）** |
| storyboard | 分镜回填链：state / source-preflight / source-import / source-range / source-revoke / propose / assets / asset-add / continuity / **scene-board upload|generate|list|inspect|delete** / readiness / export；规划板是显式单场操作，不写 shot.frame_refs |
| translate | 故事归化：create / analyze-source / target-contract / strategies / mappings |
| cover | 封面：package（平台生成包装包）/ package-propose（Agent 自主提交包装文案）/ package-show / models / specs / generate（默认 1 张 1024×1600）/ list / delete |
| export | 导出交付：options / create / **preview（交付范围审阅，返回一键审阅地址）** / download / zip；剧本 working DOCX 含每场制作信息 |
| skill | Skill 工坊：craft（共创、预检、确认、挂载回读）/ list / create / **detail（个人 Skill 摘要）** / update / versions / archive / mount / mounts / upload；**growth**（方法论进化）；**canary**（版本灰度） |
| admin | 管理员专用（仅 is_admin，非管理员 403）：status / tenant-status / skills / skill-show / skill-update / supply / provider-connect / model-add / image-model-add |
| run | 运行排查：status / events |
| feedback | CLI 诊断包收集：版本 / 近期错误 / 命令记录；默认仅本地生成，--send 才发送平台（不含密码、令牌、正文） |
| version / self-upgrade / config | 版本查看与强制检查（--check）/ 自动升级（确认后执行）/ `config on|off` 开启或关闭「有新版本时后台自动升级 + 通知」（默认关闭） |

**StoryMap 隔离重建（novel/script 的 storymap-rebuild-* 链）**：必须先采纳该域粗纲；
`storymap-rebuild-start` 冻结阶段计划与现有 StoryMap，逐阶段（小说=卷区间、剧本=集区间）
先 `rebuild-check` 确定性预检再 `rebuild-phase` 累积；全部完成后 `rebuild-propose` 合并为
完整替换候选，不自动采纳；用户明确确认后才经 `storymap adopt --confirm` 替换，旧结构与正文
快照自动归档可回溯：novel 用 `storymap-archives <pid>` 列出、`storymap-archive <pid> <归档ID>`
查看单份；script 镜像 `script storymap-archives <pid>` / `script storymap-archive <pid> <归档ID>`，
均含被替换的完整集场/卷章结构与各章/场正文快照。

场次规划板的视觉代理参数显式传递给平台：`--layout auto|2x2|2x3|3x3|3x4|4x4` 与
`--mode annotated|seedance_sequence`。上传使用 multipart，服务端返回最终 layout/pages/shot_ids/digest/source。
图片代理拒绝资产参考图时，平台会保留失败 Attempt，并以无参考图的新 Attempt 安全重试；
`reference_validation` 会返回 accepted/rejected 及原因。存在 rejected 时应补传资产参考图，不能把无参考生成误认为已保持一致性。
平台生成的资产参考图与规划板先持久化到项目工作区；后续多参考生图从本地媒体编码 base64，
不依赖供应商临时 URL。CLI 只消费平台返回的稳定媒体地址。

## Skill 能力与版本进化

```bash
# 能力进化（方法论成长）：从创作实绩提炼 → 评估 → 发布新版
scriptnow skill growth start <pid> --domain novel        # 启动分析（后台）
scriptnow skill growth workspace <pid>                   # 查看候选与历史 runs
scriptnow skill growth decide <candidate_id> --action accept|edit|reject ...
scriptnow skill growth evaluate <candidate_id>           # 评估回放（后台）
scriptnow skill growth preview <candidate_id> --evaluation-result <id>
scriptnow skill growth publish <candidate_id> --evaluation-result <id> \
  --description "..." --instructions "..." --mount <pid> # 发布新版（--mount 触发 canary 灰度）

# 版本进化（金丝雀灰度）
scriptnow skill canary list
scriptnow skill canary decide <canary_id> --action retain|limit|need_evidence|rollback
```

## 管理员 CLI

`admin` 组仅 `is_admin` 用户可用（后端校验，非管理员 403）：平台系统状态、租户启停、
主站 Skill 治理与能力进化（`skill-update` 需 `--expected-digest` 防并发覆盖）。
**token 消费、额度与财务命令一律不纳入 CLI**——这些走管理后台。

## 已知缺口（后端已具备、CLI 未覆盖）

onboarding、commerce（Paddle 订阅）、review-agent（审读工作台）、
evaluation v9（深度评估）、work-completion（完结）、invitations（邀请码）——按需补齐。

## AI Agent 安装（SKILL 体系）

Agent（Claude Code / npx skills 兼容）可通过 SKILL.md 发现能力：

```bash
npx skills add quchenchen/scriptnow-cli --skill scriptnow-cli -g -y
```

SKILL.md 位于 [`cli_anything/scriptnow/skills/SKILL.md`](cli_anything/scriptnow/skills/SKILL.md)。

安装入口是短运行契约；Agent 的第一个动作必须是 `scriptnow agent-guide --json`。
需要人工完整说明时才运行 `scriptnow agent-guide --full`，不得把手册当作创作提示词。

- **聚焦式新手创作**：从 `scriptnow guide --step 1 --medium novel|script --json`
  开始，只跟随当前返回的 `next_step`。每轮只问一个主问题；用户卡住时从 `lenses`
  中只选一个启发。先复述创作意图，再提供一个具体候选，请用户决定保留、调整或换方向。
  命令、JSON、ID 与评分术语默认留在幕后；完整路线仅在用户主动询问时用 `guide --steps` 展示。
- **柔性回归**：多轮发散后由 Agent 把轻量摘要传给
  `guide --step <当前幕> --pulse @pulse.json --json`。`useful_detour` 先保留素材并允许继续；
  只有 `drifting/conflict` 才按 `recovery` 先收拢、再邀请回归。`--resume` 可直接生成温和接续。
  两者均不写平台状态、不阻断创作命令。
- **一次明确表达即可定稿**：用户在 Agent 对话中说“定稿”“采用这版”或“可以继续”，
  Agent 在后台登记原话、领取绑定当前版本 digest 的一次性凭证，再执行
  `chapter adopt --human` / `scene adopt --human` 并记录 `adopted_human`。
  用户不操作终端、不复制凭证；语义不明确时只追问一次。
- **剧本 Skill 质量锚点**：`skill craft --domain script` 自动叠加场次功能与转折、
  可见可听可表演、对白/VO/OS 时序、台词量与目标时长四类系统锚点；不增加用户问卷，
  直接创建的 script Skill 也必须通过 robustness v2。
- **格式契约先于个人 Skill**：项目创建时锁定的竖屏短剧分镜式、中国剧本或好莱坞格式，
  由 Agent 生成、前端显示与 DOCX 导出全链路共同遵守；个人 Skill 只叠加题材方法，不能混用格式。

## 人类审阅协议（对话优先）

Agent 负责执行，作者/编辑负责观察和决定。方向、故事核心、蓝图、人物圣经、粗纲、StoryMap
集纲/章纲、正文修订、采纳和导出都经过同一条回路：Agent 从平台读取事实，完整呈现候选；用户
在对话中只表达一次「保留 / 调整 / 换方向」；Agent 后台登记原话、读取意见，并在保留时领取绑定
候选 digest 的一次性凭证，写入后回读平台结果。用户无需复制 token、重复命令或打开页面。

内容变化会使旧 digest/凭证失效，必须重新展示新版本。长内容才附带 `review_url` 作为可选阅读
入口；页面不是额外审批关卡。用户直接在前端编辑并保存，本身就是一次人类决定并纳入审计。

长篇剧本粗纲按叙事结构逐阶段回填，但结构范围只是建议；作者可调整连续边界。
`rough-outline-start/progress/phase` 必须持续显示「阶段 X / 共 N 阶段」、当前阶段与已完成阶段，
不得只在后台推进 JSON。

```bash
scriptnow review preview <pid> <resource-kind> <resource-id> @candidate.json
# 用户在当前 Agent 对话中决定后，由 Agent 执行：
scriptnow review confirm <packet-id> --decision retain --evidence "采用这一版，继续下一阶段。"
scriptnow review claim <packet-id> --json
# 调整时由 Agent 读取原话，修订后重新 preview；不复用旧凭证
scriptnow review status <packet-id> --json
```

`review preview` 会在终端展示完整内容并登记 digest；`review status` 让 Agent 直接读取用户反馈；
`--json` 只服务于 Agent 编排，不能替代可读预览。

## Agent 使用提示

- **编排前置：Skill 支撑检查（MANDATORY）**：创作前 `skill mounts <pid>`；无方法论 Skill 时
  优先用 `skill craft` 共创。Agent 先以 `--json` 获取问题协议，再以 `--answers @answers.json`
  一次回填；向用户展示草案并获明确认可后才加 `--confirm`。CLI 创建前做健壮性预检，
  通过后自动挂载并回读验证。也可用 interpret local 蒸馏或 skill create。`book` 也会在缺 Skill 时提示。
- **必须主动填充完整 direction**：用 `project direction <pid> --apply @direction.json` 回填
  premise/tone/world_setting/genre/structure/卷章数/字数等；不要依赖 `--inspire`，也不要建裸项目。
- **正文创作双模式（用户明确选择，平台侧不阻塞）**：默认由平台主笔完成——`chapter/scene generate`
  生成候选 → `review preview` 审读 → `adopt`；仅当用户**明确选择本地创作**时，Agent 才在本地写好
  正文后经 `chapter propose` / `script scene-propose` 回填候选 → `review preview` 审读 →
  `adopt --human`。未明确选择时一律按平台主笔执行；本规则只约束正文（章节/场次）创作，
  「规划回填优先」（story_cores / blueprint / storymap 规划三件套）保持不变、不受影响。
- 优先 `--json`；生成命令默认后台，`--wait` 阻塞等待。平台拒绝操作时，CLI 优先透出
  经脱敏的原始领域 detail；Agent 按可行动提示修正，不把中文通用兜底当作修复指令。
- 版本管理：创作基准 = 最新「已采纳 + 人工修订（未采纳也算）」，未采纳的 Agent 候选不进入基准。
- 审读是 Agent 自身能力：读正文 → 判断 → `--feedback` 驱动修正。

## 安全说明

- 会话只存 Cookie 不存密码；文件权限 0600。
- 所有写操作走平台同一套鉴权（Cookie + CSRF + tenant 隔离），无法越权访问其他用户数据。
- 平台核心能力（内置 Skill、管理端点、工具目录）不通过 CLI 暴露——admin 命令组仅 is_admin 可用。

## 创作纪律（批量 vs 逐章）

- **批量生成（scene-batch）务必谨慎**：批量可能造成情节/设定不一致、伏笔失误——每次批量前 CLI 会提示风险，
  请逐场审读后再采纳。
- **最佳实践：逐章/逐场创作完善**——generate → show 审读（--plain）→ 带意见 feedback 修正 → adopt。
- **Agent 请勿用 subagent 并发批量**：上下文割裂会造成设定漂移；同一项目的创作应串行且共享上下文。


## 质量评估标准

- `chapter quality --standard` 评估**默认使用内容质量偏好**（人物能动性/场景因果/关系推进/叙述声音/连贯性/源边界/章节推进/文本质感）；
  仅当用户明确提出 **真人剧备案口径**（`--standard drama-filing`）或 **千部计划/批量网文标准**（`--standard thousand-plan`）时才附加对应标准。
- 评估 = **Agent 系统评估 + 平台建议维度**：CLI 提供平台维度与场次原文，Agent 按维度逐项系统评估、引用证据。

## 规格示例

`chapter propose --help-format / --example`、`script scene-propose --help-format / --example` 展示**格式规格示例**
（blocks JSON 结构/正文分段），仅保证格式合规，**不代表质量水准**——质量由 Agent 按上述评估维度判断。

## Agent 创作角色与流程纪律（必读）

- **角色分工（默认：平台=主笔）**：Agent = 项目经理 + 质量审查；平台（scene/chapter 生成）
  默认完成正文——准备好 direction/feedback，驱动生成、审查、要求重生成、采纳达标版本。
  仅当用户**明确选择本地创作**时，Agent 才在本地写好正文并经 `chapter propose` /
  `script scene-propose` 回填——除此之外绝不自己写正文（不在本地堆样本/配置草稿）。
- **阶段 1（立即）**：收到需求后立刻 `project create` → 立刻用 propose 回填结构
  （cores/blueprint/storymap，前 5-10 集/卷）——不要攒本地文件。
- **阶段 2（逐场循环）**：每场/每章 = 准备详细 feedback → 生成 → 审查
  （scene-show --plain 读原文 + scene-quality 快检）→ 不达标立即带 feedback 重生成 → 达标才采纳。
- **质量门槛**：9-10 优秀 · 8-9 良好 · **<8 分立即重生成**，绝不采纳不达标内容。
- **进度控制**：每集/卷完成后汇报质量统计，询问用户是否继续。
