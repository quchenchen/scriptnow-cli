# 安装与连接

> **CLI 安装 / 升级**：发行包名为 `scriptnow-cli`，命令名与 Skill 名为 `scriptnow`。
> 可用 `pipx install scriptnow-cli` 或虚拟环境内的 `python -m pip install scriptnow-cli` 从
> [PyPI](https://pypi.org/project/scriptnow-cli/) 安装；平台分发源继续可用，先读取
> `https://sn.igeewa.com/downloads/scriptnow-cli/version.txt`，再安装对应版本的 wheel。
> 不使用 `scriptnow_cli-latest-...whl`，新版 pip 会拒绝该版本名。
> `scriptnow self-upgrade` 的实际顺序仍是「生产源 → codeload → git+https」，不会自动改为 PyPI；
> PyPI 与平台版本可能不同，分别核对来源。自动升级默认关闭，用户明确选择后才用 `config on`。
> 安装 CLI 不等于已登录或已创建作品；先 doctor，再按本文 bootstrap 读取实时契约。
> Agent 客户端如需注册 Skill，另用 `npx skills add quchenchen/scriptnow-cli --skill scriptnow -g -y`
> （仅适用于支持该工具且已有 Node.js 的客户端）；否则直接执行 `agent-guide --json` 读取契约。

安装前检查现有命令与版本，已可用则不重复安装。密码仅由用户在系统浏览器的平台登录页输入，不让用户把凭据粘贴到聊天。安装失败时报告具体缺失条件，不继续创建作品。

## 默认启动：自检、补齐环境、继续创作

用户开始或继续 ScriptNow 创作，即触发自检；不以用户说出“安装”为前提。若 CLI 缺失，在当前 Agent 实际执行环境中自动安装 CLI 及必要运行依赖，验证后继续原任务。简短说明正在准备连接工具即可，不把技术选项或重复的安装确认交给作者。已有可用版本直接复用；自动补齐缺失依赖不等于自动升级已有环境。用户明确禁止安装或平台强制要求授权时遵守该限制。

作者已表达的灵感、目标作品和创作意图要保留；安装结束不重新问一遍。只有必须本人完成的登录验证、系统权限或无法自动解决的具体阻碍才打断，并且只说明当前需要的一步。若安装因已确认的原因失败，不无限重试。

用户单独说“帮我安装并启动 ScriptNow”时也执行同一路径，不只返回教程。

先确认工具实际执行在哪台机器。Windows 用户的 Agent 可能运行在 WSL、容器或远程主机；不能把远程 Linux 安装成功说成已安装到用户 Windows。安装到 Agent 真正执行 CLI 的环境；用户明确指定本机而你无法访问时，说明限制并给出本机一步操作。

检查已有 `scriptnow --version`；Windows 同时检查 `%LOCALAPPDATA%\ScriptNow\cli\Scripts\scriptnow.exe`。已有可用版本先使用，不因 PATH 尚未刷新就重复安装。升级须有用户要求或明确选择。

## Windows：调用官方一键脚本

在可执行 PowerShell 的 Windows 环境中，使用官方 `install-agent.ps1`。现有脚本会寻找 Python 3.10+，缺失时安装用户级 Python，创建独立环境，安装平台发布版本，并返回 `scriptnow.exe` 的绝对路径。不要求用户安装 Git、Node.js 或手动激活环境。

当前 Python 自动安装分支下载 **amd64** 安装器。若为 ARM64 或其他架构且没有已验证可用的 Python，不直接运行该自动安装分支；先解决匹配架构的 Python，再使用 `-SkipPythonBootstrap`。不得宣称已验证所有 Windows 架构。

下载到临时文件再执行，便于查看失败点；不要把远程脚本直接拼入作者聊天中的长命令。以下代码供 Agent 在 PowerShell 内执行：

```powershell
$installer = Join-Path $env:TEMP ("scriptnow-install-" + [guid]::NewGuid().ToString() + ".ps1")
Invoke-WebRequest -UseBasicParsing -Uri "https://sn.igeewa.com/downloads/scriptnow-cli/install-agent.ps1" -OutFile $installer
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
if ($LASTEXITCODE -ne 0) { throw "ScriptNow installation failed; inspect the preceding error." }
$cli = Join-Path $env:LOCALAPPDATA "ScriptNow\cli\Scripts\scriptnow.exe"
if (-not (Test-Path $cli)) { throw "Installer did not produce the expected CLI executable." }
& $cli --version
if ($LASTEXITCODE -ne 0) { throw "Installed CLI did not start." }
& $cli doctor
```

`-ExecutionPolicy Bypass` 仅作用于该次子进程，不修改系统或用户执行策略，不绕过组织的组策略。安装脚本会添加用户级 PATH；父进程通常不会同步更新，所以后续仍用返回的绝对路径，例如 `& $cli agent-guide --json`。若传入自定义 `-InstallDir`，从该目录解析路径，不使用上述默认值。

## Windows 失败时按证据处理

| 实际现象 | Agent 的下一步 |
|---|---|
| `python` 打开应用商店、没有输出，或 Python launcher 报错 | 检查可执行文件来源与退出码，尝试已安装解释器的绝对路径；不能把命令存在当作 Python 可用。 |
| 安装结束但找不到 `scriptnow` 命令 | 直接运行安装器返回的绝对路径；确认可用后继续，不要求作者重启整台电脑。 |
| 中文用户名或路径含空格 | 用 `Join-Path` 和 PowerShell 调用运算符 `&`；不拼接未引用的字符串命令。 |
| 既有虚拟环境损坏或 Python 版本过旧 | 说明已发现的问题，使用新的独立安装目录；不直接删除旧环境或其他 Python。 |
| 网络超时或证书错误 | 确认具体失败地址，只重试失败步骤；可使用用户已配置且授权的代理。不要关闭证书校验或改全局网络配置。 |
| 组织策略、终端权限或安全软件阻止运行 | 报告被阻止的具体动作，交给用户或管理员处理；不反复尝试提权或关闭安全软件。 |
| 安装器退出非零 | 保留错误原因，先修复该原因；不能凭目录存在就报告安装成功。 |

安装器目前没有对所有 Windows 失败场景自动恢复的保证。Skill 负责诊断与衔接，不把“支持一键安装”解释成任何环境都无需人工参与。

## macOS 与其他执行环境

先复用可用 CLI。若需安装且已有 pipx，使用 `pipx install scriptnow-cli`；否则用已验证的 Python 3.10+ 创建独立虚拟环境，再通过该环境的 `python -m pip install scriptnow-cli` 安装。不要使用 sudo pip 或改系统 Python。记录安装后 CLI 的绝对路径，不依赖 shell 激活是否能跨工具调用保留。

没有可用 Python 时，先检查现有包管理器与环境能力，再选择官方 Python 安装方式；需要图形界面确认时只引导当前一步。不为安装 CLI 顺带安装不需要的工具链。

## 安装完成的判断

依次核对：可执行文件能启动 → 版本可读取 → `doctor` 的环境与连接检查 → `agent-guide --json` 可读取。区分“安装成功”“平台连接成功”“账号已登录”：未登录不是安装失败，网络失败也不意味着必须重装。不得自动开启诊断上传。

随后回到主 Skill 的登录和创作流程。向作者只报告结果，例如：“连接工具已经装好，可以启动。接下来登录你的 ScriptNow 账号。”仅在对应检查真实成功后才能这样说。

## 浏览器授权登录

执行 `scriptnow login --host https://sn.igeewa.com` 打开系统浏览器，由作者在网页输入账号密码并确认授权。Agent 不读取登录页密码框、不代填密码、不索取验证码、cookie 或回调授权码；等待 CLI 返回结果即可。CLI 仅接收一次性授权码并交换独立会话。超时、浏览器无法打开或服务端版本不支持时，不退回密码参数、stdin、环境变量或直接调用登录 API。当前本机回调要求浏览器与 CLI 在同一台电脑；远程 Agent 不得冒充本机已登录。

授权码完全由浏览器和 CLI 自动传递，不要求作者查看、复制或粘贴。已有有效会话直接复用；短期访问凭据到期由 CLI 自动刷新，成功刷新延长服务端配置的闲置窗口。不得为每次创作重新调用 login。
