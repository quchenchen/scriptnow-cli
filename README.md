# cli-anything-scriptnow

ScriptNow 创作 CLI —— 从灵感到成书交付的一站式命令行。

> 面向**命令行用户与 AI Agent**：建项目、一书一 Skill 解读、小说/剧本创作、
> 封面生成、导出交付，全部可用命令行完成。非命令行创作者请使用网页端。

## 安装

要求 Python 3.10+。

```bash
# 从本仓库安装
pip install git+https://github.com/quchenchen/scriptnow-cli.git

# 或克隆后本地安装
git clone https://github.com/quchenchen/scriptnow-cli.git
cd scriptnow-cli && pip install .
```

## 登录

```bash
scriptnow login --host https://sn.igeewa.com --email 你的账号 --password '你的密码'
```

会话保存到 `~/.config/scriptnow-cli/session.json`（仅 Cookie，不含密码，权限 0600）。

## 创作者 5 步

```bash
# ① 建项目（小说 / 剧本）
scriptnow project create --name 你的作品名 --medium novel

# ② 解读参考作品（一书一 Skill：上传作品 → 生成创作方法论）
scriptnow interpret go 手稿.docx

# ③ 规划全书
scriptnow storymap generate <项目ID> --wait
scriptnow book <项目ID>

# ④ 逐章创作（读原文 → 带意见重新生成 → 采纳）
scriptnow chapter generate <项目ID> chapter-1-1
scriptnow chapter show <项目ID> chapter-1-1 --plain
scriptnow chapter generate <项目ID> chapter-1-1 --feedback "你的修改意见"
scriptnow chapter adopt <项目ID> chapter-1-1 <修订ID>

# ⑤ 收尾交付
scriptnow cover generate <项目ID> --image-model-id <模型ID>
scriptnow export create <项目ID> --units chapter-1-1
scriptnow export download <项目ID> <清单ID> -o 书.docx
```

剧本同理：`--medium script`，命令用 `script scene-list / scene-show / scene`。

## 命令组

| 组 | 用途 |
|----|------|
| project | 项目管理：创建 / 列表 / 上传素材 / 删除 |
| interpret | 一书一 Skill：go（一键解读）/ create / read / status / decide |
| book | 全书托管创作规划（Agent 编排原语） |
| chapter | 小说章节：list / show / generate / quality / adopt |
| storymap | 小说卷章结构：state / generate / adopt |
| novel | 小说创作链：story-cores / blueprint |
| script | 剧本创作链：state / scene-list / scene-show / scene / storymap / blueprint / story-cores |
| translate | 故事归化：create / analyze-source / target-contract / strategies / mappings |
| cover | 封面：models / specs / generate / list / delete |
| export | 导出交付：options / create / download |
| skill | Skill 工坊：list / create / update / versions / archive / mount / upload |
| run | 运行排查：status / events |
| account | 账户额度查询 |

## AI Agent 安装（SKILL 体系）

Agent（Claude Code / Pi / npx skills 兼容）可通过 SKILL.md 发现能力：

```bash
npx skills add quchenchen/scriptnow-cli --skill cli-anything-scriptnow -g -y
```

SKILL.md 位于 `cli_anything/scriptnow/skills/SKILL.md`。

## 安全说明

- 会话只存 Cookie 不存密码；文件权限 0600。
- 所有写操作走平台同一套鉴权（Cookie + CSRF + tenant 隔离），无法越权访问其他用户数据。
- 平台核心能力（内置 Skill、管理端点、工具目录）不通过 CLI 暴露。
