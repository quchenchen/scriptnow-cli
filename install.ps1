param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "ScriptNow\cli")
)

$ErrorActionPreference = "Stop"
$versionUrl = "https://sn.igeewa.com/downloads/scriptnow-cli/version.txt"
$wheelBase = "https://sn.igeewa.com/downloads/scriptnow-cli"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' was not found. Install Python 3.10 or newer from python.org, then retry."
}

$pythonVersion = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3 could not be started through 'py -3'."
}
$parts = $pythonVersion.Trim().Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    throw "ScriptNow CLI requires Python 3.10 or newer; found $pythonVersion."
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
& py -3 -m venv $InstallDir
if ($LASTEXITCODE -ne 0) { throw "Failed to create the ScriptNow virtual environment." }

$python = Join-Path $InstallDir "Scripts\python.exe"
$scripts = Join-Path $InstallDir "Scripts"
$scriptnow = Join-Path $scripts "scriptnow.exe"
$version = (Invoke-RestMethod $versionUrl).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "The ScriptNow release service returned an invalid version: $version"
}
$wheel = "$wheelBase/scriptnow_cli-$version-py3-none-any.whl"
& $python -m pip install --upgrade $wheel
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

& $scriptnow --version
Write-Host "ScriptNow CLI installed in $InstallDir"
Write-Host "Open a new PowerShell window, then run: scriptnow doctor"
