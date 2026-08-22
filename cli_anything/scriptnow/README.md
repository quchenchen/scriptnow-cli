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
- **Agent 操作契约**：`scriptnow agent-guide`（--json）输出连接平台唯一准则——平台是事实源、规划回填优先、生成后台轮询、StoryMap 修订需用户明确授权。
- **新增卷章 = 纯追加**：`storymap append-volume` / `append-chapters` 只尾部新增，已有卷章完全不动；旧结构自动归档可回溯。
- **审读是 Agent 自身能力**：平台不提供固定 rubric，Agent 读正文、自行判断、用 `--feedback` 驱动修正。

## 安装

要求 Python 3.10+。macOS/Linux 系统 Python（Homebrew、python.org）受 PEP 668 保护时，
请先在虚拟环境中安装：

```bash
# 从源码（editable，推荐开发使用）
git clone https://github.com/quchenchen/scriptnow-cli.git
cd scriptnow-cli && pip install -e .

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
scriptnow project direction <pid> --apply @direction.json     # Agent 主动梳理回填完整方向
# 规划（Agent 本地导入，可只给 1 个主推直接采纳）
scriptnow novel propose <pid> cores @cores.json --adopt
scriptnow novel propose <pid> blueprint @blueprint.json --adopt
scriptnow novel propose <pid> storymap @storymap.json
scriptnow novel orchestrate <pid> --accept                    # 审阅 → 采纳 → 全书计划
# 创作循环（Agent 审读驱动）
scriptnow book <pid>                                          # 编排原语：各章已采纳/待生成/候选待审
scriptnow chapter show <pid> chapter-1-1 --plain
scriptnow chapter generate <pid> chapter-1-1 --feedback "你的意见"  # 后台，run status 轮询
scriptnow chapter adopt <pid> chapter-1-1 <rev>
# 改编稿本地回传：chapter propose <pid> chapter-1-1 --file @blocks.json
```

**剧本（剧集 × 场次）**

```bash
scriptnow project create --name 新剧 --medium script
scriptnow project direction <pid> --apply @direction.json
# 规划
scriptnow script propose <pid> cores @cores.json --adopt
scriptnow script propose <pid> blueprint @blueprint.json --adopt
scriptnow script propose <pid> storymap @storymap.json
# 创作循环
scriptnow script scene-list <pid>
scriptnow script scene-show <pid> scene-1-1 --plain
scriptnow script scene <pid> scene-1-1 --feedback "你的意见"  # 后台，run status 轮询
scriptnow script adopt-scene <pid> scene-1-1 <rev>
# 改编稿本地回传：script scene-propose <pid> scene-1-1 --file @blocks.json
```

**交付**：`cover generate` 封面 → `export create --units chapter-1-1|scene-1-1` → `export download -o 书.docx`。

## 命令组

| 组 | 用途 |
|----|------|
| project | 项目管理：创建 / 列表 / 上传素材 / 删除 / 方向（--apply 客户端梳理回填 / --inspire 平台灵感） |
| interpret | 一书一 Skill：go（一键解读）/ local（Agent 本地解读，样本不传平台）/ create / read / status / decide |
| book | 全书托管创作规划（Agent 编排原语，含 Skill 支撑侦测） |
| chapter | 小说章节：list / show / generate / quality（--standard 内容/备案/千部）/ adopt / propose（本地回传） |
| storymap | 小说卷章结构：state / generate / **append-volume（新增卷，纯追加）** / **append-chapters（新增章，纯追加）** / adopt（**高危，需 --confirm**） |
| novel | 小说创作链：story-cores / blueprint / bootstrap / propose（本地 JSON 导入）/ orchestrate |
| script | 剧本创作链：state / scene-list / scene-show / scene / scene-propose（--auto-adopt/--help-format/--example）/ scene-batch（批量+断点续跑）/ scene-quality / scene-diff / quality-report / storymap / blueprint / story-cores / propose / adopt-* |
| translate | 故事归化：create / analyze-source / target-contract / strategies / mappings |
| cover | 封面：package（平台生成包装包）/ package-propose（Agent 自主提交包装文案）/ package-show / models / specs / generate（默认 1 张 1024×1600）/ list / delete |
| export | 导出交付：options / create / download（novel/script） |
| skill | Skill 工坊：list / create / update / versions / archive / mount / mounts / upload；**growth**（方法论进化）；**canary**（版本灰度） |
| admin | 管理员专用（仅 is_admin，非管理员 403）：status / tenant-status / skills / skill-show / skill-update / supply / provider-connect / model-add / image-model-add |
| run | 运行排查：status / events |
| version / self-upgrade | 版本查看与强制检查（--check）/ 自动升级（确认后执行） |

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

narrative-graph（叙事图谱）、onboarding、commerce（Paddle 订阅）、review-agent（审读工作台）、
evaluation v9（深度评估）、work-completion（完结）、invitations（邀请码）——按需补齐。

## AI Agent 安装（SKILL 体系）

Agent（Claude Code / npx skills 兼容）可通过 SKILL.md 发现能力：

```bash
npx skills add quchenchen/scriptnow-cli --skill scriptnow-cli -g -y
```

SKILL.md 位于 [`cli_anything/scriptnow/skills/SKILL.md`](cli_anything/scriptnow/skills/SKILL.md)。

## Agent 使用提示

- **编排前置：Skill 支撑检查（MANDATORY）**：创作前 `skill mounts <pid>`；无方法论 Skill 时
  先创建（interpret local 蒸馏 或 skill create）再创作。`book` 也会在缺 Skill 时提示。
- **必须主动填充完整 direction**：用 `project direction <pid> --apply @direction.json` 回填
  premise/tone/world_setting/genre/structure/卷章数/字数等；不要依赖 `--inspire`，也不要建裸项目。
- 优先 `--json`；生成命令默认后台，`--wait` 阻塞等待。
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

- **角色分工**：Agent = 项目经理 + 质量审查；平台（scene/chapter 生成）= 主笔。
  **Agent 绝不自己写正文**——不在本地堆样本剧本/配置文件；准备好 direction/feedback，
  驱动生成、审查、要求重生成、采纳达标版本。
- **阶段 1（立即）**：收到需求后立刻 `project create` → 立刻用 propose 回填结构
  （cores/blueprint/storymap，前 5-10 集/卷）——不要攒本地文件。
- **阶段 2（逐场循环）**：每场/每章 = 准备详细 feedback → 生成 → 审查
  （scene-show --plain 读原文 + scene-quality 快检）→ 不达标立即带 feedback 重生成 → 达标才采纳。
- **质量门槛**：9-10 优秀 · 8-9 良好 · **<8 分立即重生成**，绝不采纳不达标内容。
- **进度控制**：每集/卷完成后汇报质量统计，询问用户是否继续。
