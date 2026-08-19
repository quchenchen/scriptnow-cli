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

## 典型创作流程

```bash
# 1. 建项目（小说）
scriptnow project create --name 新作 --medium novel

# 2. 一书一 Skill：上传作品 → 通读 → 源分析 + 创作方法论
scriptnow interpret go 手稿.docx

# 3. 规划全书（StoryMap 卷章节）
scriptnow storymap generate <pid> --wait
scriptnow storymap adopt <pid> <candidate_id>

# 4. 查看全书托管创作规划
scriptnow book <pid>

# 5. 逐章创作（Agent 审读驱动）
scriptnow chapter list <pid>
scriptnow chapter show <pid> chapter-1-1 --plain     # 读正文
scriptnow chapter generate <pid> chapter-1-1 --wait  # 生成候选
scriptnow chapter quality <pid> chapter-1-1 <rev>    # 可选质量评估
scriptnow chapter adopt <pid> chapter-1-1 <rev>      # 采纳

# 6. 剧本同理
scriptnow project create --name 新剧 --medium script
scriptnow script scene-list <pid>
scriptnow script scene-show <pid> scene-1-1 --plain
scriptnow script scene <pid> scene-1-1 --wait

# 7. 封面
scriptnow cover models <pid>                          # 选生图模型
scriptnow cover generate <pid> --image-model-id <id>

# 8. 导出交付
scriptnow export options <pid>
scriptnow export create <pid> --units chapter-1-1
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
| novel | 小说创作链：story-cores / blueprint（规划阶段） |
| script | 剧本创作链：state / scene-list / scene-show / scene / storymap / blueprint / story-cores |
| translate | 故事归化：create / analyze-source / target-contract / strategies / mappings |
| cover | 封面：models / specs / generate / list / delete |
| export | 导出交付：options / create / download |
| skill | Skill 工坊：list / create / update / versions / archive / mount / upload |
| run | 运行排查：status / events |
| account | 账户额度查询 |

## Agent 使用提示

- 优先 `--json`；所有生成命令默认后台，`--wait` 阻塞等待。
- 版本管理：创作搭档与后续章节基准 = 最新「已采纳 + 人工修订（未采纳也算）」，未采纳的 Agent 候选不进入基准。
- 审读是 Agent 自身能力：`chapter show` / `scene-show --plain` 读正文 → 判断 → `--feedback` 驱动修正。
