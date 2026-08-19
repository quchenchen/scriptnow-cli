# scriptnow-cli

ScriptNow 创作 CLI —— 从灵感到成书交付的一站式命令行。
基于 [CLI-Anything](https://github.com/HKUDS/CLI-Anything) 模式，所有命令支持 `--json`。

## 安装

```bash
pip install -e .
```

## 登录

```bash
scriptnow login --host https://sn.igeewa.com --email you@example.com --password '...'
```

## 典型创作流程（双域：小说 / 剧本）

小说与剧本共享「项目 → 方向 → 规划 → 创作 → 导出」，但规划结构与创作循环有差异。
**编排前置：确认方法论 Skill 支撑**（见第 0 步）——缺 Skill 时先创建再创作，不要裸写。

```bash
# ── 0. Skill 支撑检查（创作前必做）────────────────────────────
scriptnow skill mounts <pid>                 # 项目已挂载哪些方法论 Skill？
# 无 → 先创建（两种方式任选）：
#   ① 一书一 Skill 蒸馏（推荐，样本不传平台，Agent 本地解读回传）：
scriptnow interpret local 手稿.docx --spec  # Agent 读作品原文 → 按规范产出 skill JSON
scriptnow interpret local 手稿.docx --submit @skill.json --project-id <pid>   # 创建并挂载
#   ② 个人 Skill 直接提交：
scriptnow skill create --name my-method --description "..." --domain novel \
  --role writer --stage writing --instructions "方法论正文"
#   然后挂载到项目：
scriptnow skill mounts <pid>                 # 查 version_id
scriptnow skill mount <pid> <skill_id> <version_id>

# ── 1. 建项目 + 完整方向（Agent 主动梳理回填，不依赖平台灵感）──
# 小说：
scriptnow project create --name 新作 --medium novel --genre "mystery, werewolf" \
  --volume-one 1 --volume-two 15 --chapter-target-words 1200
# 剧本：
scriptnow project create --name 新剧 --medium script
# 两域都推荐用 --apply 一次写入完整 direction（premise/tone/world_setting/structure/卷章数…）：
scriptnow project direction <pid> --apply @direction.json

# ── 2. 规划全书（双域差异）───────────────────────────────────
# 小说（卷章结构，两种方式）：
#   ① Agent 本地生成导入（零平台压力，可只给 1 个主推方向直接采纳）
scriptnow novel propose <pid> cores @cores.json --adopt
scriptnow novel propose <pid> blueprint @blueprint.json --adopt
scriptnow novel propose <pid> storymap @storymap.json
scriptnow novel orchestrate <pid> --accept          # 审阅 → 采纳 → 全书计划
#   ② 平台生成
scriptnow storymap generate <pid> --wait
scriptnow novel orchestrate <pid> --accept
# 剧本（剧集 × 场次，结构 propose 与小说同构）：
scriptnow script propose <pid> cores @cores.json --adopt
scriptnow script propose <pid> blueprint @blueprint.json --adopt
scriptnow script propose <pid> storymap @storymap.json
#     或平台生成：script story-cores --wait → adopt-core → script blueprint → … → script storymap

# ── 3. 创作循环（双域差异）───────────────────────────────────
# 小说：book 看编排计划 → 逐章生成/审读/采纳
scriptnow book <pid>                                # 编排原语：各章已采纳/待生成/候选待审
scriptnow chapter show <pid> chapter-1-1 --plain    # 读正文（Agent 自身审读）
scriptnow chapter generate <pid> chapter-1-1 --wait --feedback "你的意见"
scriptnow chapter adopt <pid> chapter-1-1 <rev>
# 剧本：场次循环
scriptnow script scene-list <pid>
scriptnow script scene-show <pid> scene-1-1 --plain
scriptnow script scene <pid> scene-1-1 --wait --feedback "你的意见"
scriptnow script adopt-scene <pid> scene-1-1 <rev>
# 改编稿 Agent 本地写好后直接回传候选（不经平台文本生成）：
scriptnow script scene-propose <pid> scene-1-1 --file @blocks.json

# ── 4. 封面（通用）───────────────────────────────────────────
scriptnow cover models <pid>                        # 选生图模型
scriptnow cover generate <pid> --image-model-id <id>

# ── 5. 导出交付（双域差异在 unit 维度）───────────────────────
scriptnow export options <pid>
scriptnow export create <pid> --units chapter-1-1   # 小说按章节；剧本按场次 scene-1-1
scriptnow export download <pid> <manifest> -o 书.docx
```

## 命令组

| 组 | 用途 |
|----|------|
| project | 项目管理：创建 / 列表 / 上传素材 / 删除 / 查看与设定创作方向（含灵感模式） |
| interpret | 一书一 Skill：go（一键解读）/ create / read / status / decide |
| book | 全书托管创作规划（Agent 编排原语） |
| chapter | 小说章节：list / show / generate / quality / adopt |
| storymap | 小说卷章结构：state / generate / adopt |
| novel | 小说创作链：story-cores / blueprint / bootstrap（一键规划）/ propose（本地 JSON 导入） |
| script | 剧本创作链：state / scene-list / scene-show / scene / storymap / blueprint / story-cores |
| translate | 故事归化：create / analyze-source / target-contract / strategies / mappings |
| cover | 封面：models / specs / generate / list / delete |
| export | 导出交付：options / create / download |
| skill | Skill 工坊：list / create / update / versions / archive / mount / upload |
| run | 运行排查：status / events |
| account | 账户额度查询 |

## Agent 使用提示

- **编排前置：Skill 支撑检查（MANDATORY）**：开始逐章/逐场创作前，先 `skill mounts <pid>` 确认项目已挂载方法论 Skill。若为空，**先创建 Skill 再创作**：一书一 Skill 蒸馏（`interpret local`，样本不传平台、Agent 本地解读回传；剧本域把 skill JSON 的 domain 设为 `script`）或个人 Skill 提交（`skill create --domain novel|script`），然后 `skill mount`。小说也可用 `interpret go`（平台通读，作品会上传）。
- **必须主动填充完整 direction**：创建项目或设定方向时，Agent 应主动梳理并回填全部关键字段（premise/tone/world_setting/genre/structure/卷数/章数/字数/发散度/约束），用 `project direction <pid> --apply '{"...":...}'` 或建项目时带全参数；**不要依赖 `--inspire` 让平台生成，也不要建裸项目**。仅当用户明确要求平台灵感时才用 `--inspire`。
- 优先 `--json`；所有生成命令默认后台，`--wait` 阻塞等待。
- 版本管理：创作搭档与后续章节基准 = 最新「已采纳 + 人工修订（未采纳也算）」，未采纳的 Agent 候选不进入基准。
- 审读是 Agent 自身能力：`chapter show` / `scene-show --plain` 读正文 → 判断 → `--feedback` 驱动修正。
