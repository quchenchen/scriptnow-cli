# Args (work under both `irm ... | iex` and `powershell -File`):
#   -InstallDir <path>       venv location (default: %LOCALAPPDATA%\ScriptNow\cli)
#   -PythonVersion <x.y.z>   python.org release to bootstrap (default 3.12.10)
#   -SkipPythonBootstrap     fail instead of auto-installing Python
$InstallDir = (Join-Path $env:LOCALAPPDATA "ScriptNow\cli")
$PythonVersion = "3.12.10"
$SkipPythonBootstrap = $false
for ($i = 0; $i -lt $args.Count; $i++) {
    switch -Regex ($args[$i]) {
        '^-InstallDir$'       { $InstallDir = $args[++$i] }
        '^-PythonVersion$'    { $PythonVersion = $args[++$i] }
        '^-SkipPythonBootstrap$' { $SkipPythonBootstrap = $true }
    }
}

# Agent-friendly one-shot installer.
#   - No interactive prompts; safe for automation (codex / CI / assistants).
#   - If Python 3.10+ is missing, downloads the official python.org installer
#     and installs it silently per-user (no admin / UAC), then continues.
#   - Reuses an existing venv (upgrade in place) instead of rebuilding.
#   - Always installs the latest production release (reads version.txt).
#   - LAST LINE of stdout is the absolute path to scriptnow.exe so the agent
#     can capture and call it directly without relying on PATH.

$ErrorActionPreference = "Stop"
$versionUrl = "https://sn.igeewa.com/downloads/scriptnow-cli/version.txt"
$wheelBase = "https://sn.igeewa.com/downloads/scriptnow-cli"
$ProgressPreference = "SilentlyContinue"  # speed up Invoke-WebRequest downloads

function Test-Python10Plus([string]$PythonPath) {
    # $True if the given interpreter (absolute path or command name) is Python >= 3.10.
    $cmd = Get-Command $PythonPath -ErrorAction SilentlyContinue
    $resolved = if ($cmd) { $cmd.Source } else { $null }
    $probe = if (Test-Path $PythonPath -ErrorAction SilentlyContinue) { $PythonPath } else { $resolved }
    if (-not $probe) { return $false }
    try {
        $info = & $probe -c "import sys;print('%d.%d' % (sys.version_info.major, sys.version_info.minor))" 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        $info = ($info | Select-Object -Last 1).Trim()
        $parts = $info.Split('.')
        if ($parts.Count -lt 2) { return $false }
        $major = [int]$parts[0]; $minor = [int]$parts[1]
        return ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10))
    } catch { return $false }
}

function Find-SystemPython {
    # Returns an absolute python.exe path (Python >= 3.10) from py / python, or empty.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $exe = (& py -3 -c "import sys;print(sys.executable)" 2>$null | Select-Object -Last 1).Trim()
        if ($exe -and (Test-Python10Plus $exe)) { return $exe }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $exe = (& python -c "import sys;print(sys.executable)" 2>$null | Select-Object -Last 1).Trim()
        if ($exe -and (Test-Python10Plus $exe)) { return $exe }
    }
    return ""
}

function Install-PythonBootstrap {
    # Download the official per-user installer (tries CN mirrors first for speed,
    # then python.org) and run it silently. No admin needed.
    # Per-user installs land in %LOCALAPPDATA%\Programs\Python\Python<MM> by default
    # (no TargetDir passed, so no quoting hazards); the script only uses the
    # absolute python.exe path afterwards and never relies on PATH or `py`.
    $majorMinor = (($PythonVersion -split '\.')[0..1] -join '')
    $target = Join-Path $env:LOCALAPPDATA ("Programs\Python\Python" + $majorMinor)
    $exe = Join-Path $env:TEMP ("python-" + $PythonVersion + "-amd64.exe")
    if (-not (Test-Path $exe)) {
        $fileName = "python-" + $PythonVersion + "-amd64.exe"
        $mirrors = @(
            ("https://mirrors.tuna.tsinghua.edu.cn/python/" + $PythonVersion + "/" + $fileName),
            ("https://mirrors.huaweicloud.com/python/" + $PythonVersion + "/" + $fileName),
            ("https://mirrors.ustc.edu.cn/python/" + $PythonVersion + "/" + $fileName),
            ("https://www.python.org/ftp/python/" + $PythonVersion + "/" + $fileName)
        )
        $downloaded = $false
        foreach ($url in $mirrors) {
            Write-Output ("Downloading Python " + $PythonVersion + " from " + $url)
            try {
                Invoke-WebRequest -Uri $url -OutFile $exe -TimeoutSec 300 -UseBasicParsing
                if ((Get-Item $exe -ErrorAction SilentlyContinue).Length -gt 10000000) { $downloaded = $true; break }
            } catch {
                Write-Output ("Mirror failed: " + $url)
            }
        }
        if (-not $downloaded) { throw ("Failed to download Python " + $PythonVersion + " from all mirrors.") }
    }
    $installArgs = @("/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=0", "Include_pip=1", "Include_test=0", "Include_doc=0", "Shortcuts=0")
    $proc = Start-Process -FilePath $exe -ArgumentList $installArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0) { throw ("Python " + $PythonVersion + " installer failed (exit " + $proc.ExitCode + ").") }
    $pythonExe = Join-Path $target "python.exe"
    if (-not (Test-Path $pythonExe)) { throw ("Python install finished but " + $pythonExe + " was not found.") }
    return $pythonExe
}

$venvPython = Join-Path $InstallDir "Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

if (Test-Path $venvPython) {
    if (-not (Test-Python10Plus $venvPython)) {
        throw ("Existing venv at " + $InstallDir + " has Python < 3.10. Delete it and rerun.")
    }
    $python = $venvPython
} else {
    $python = Find-SystemPython
    if (-not $python) {
        if ($SkipPythonBootstrap) {
            throw "No Python 3.10+ found and --SkipPythonBootstrap was passed. Install Python 3.10+ from python.org, then rerun."
        }
        $python = Install-PythonBootstrap
    }
    & $python -m venv $InstallDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the ScriptNow virtual environment." }
    $python = $venvPython
}

$scriptnow = Join-Path $InstallDir "Scripts\scriptnow.exe"
$scripts = Join-Path $InstallDir "Scripts"

$version = (Invoke-RestMethod $versionUrl).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "The ScriptNow release service returned an invalid version: $version"
}
& $python -m pip install --upgrade "$wheelBase/scriptnow_cli-$version-py3-none-any.whl"
if ($LASTEXITCODE -ne 0) { throw "Failed to install ScriptNow CLI $version." }

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$pathEntries = @($userPath -split ';' | Where-Object { $_ })
if ($pathEntries -notcontains $scripts) {
    $newPath = if ($userPath) { "$scripts;$userPath" } else { $scripts }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
}
if (($env:Path -split ';') -notcontains $scripts) {
    $env:Path = "$scripts;$env:Path"
}

& $scriptnow --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "scriptnow --version failed after install." }

Write-Output "ScriptNow CLI $version installed in $InstallDir"
Write-Output $scriptnow
