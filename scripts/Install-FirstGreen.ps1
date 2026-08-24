param(
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Get-Command py.exe -ErrorAction SilentlyContinue
if ($py) {
    $python = $py.Source
    $pythonPrefix = @("-3.12")
} else {
    $pythonCommand = Get-Command python.exe -ErrorAction Stop
    $python = $pythonCommand.Source
    $pythonPrefix = @()
}

& $python @pythonPrefix -m pip install --user $root
if ($LASTEXITCODE -ne 0) {
    throw "FirstGreen installation failed with exit code $LASTEXITCODE"
}

$userBase = (& $python @pythonPrefix -c "import site; print(site.USER_BASE)").Trim()
$installedFg = Join-Path $userBase "Scripts\fg.exe"
if (-not (Test-Path -LiteralPath $installedFg)) {
    throw "Installed fg.exe was not found at $installedFg"
}

$launcherRoot = Join-Path $env:LOCALAPPDATA "FirstGreen"
New-Item -ItemType Directory -Force -Path $launcherRoot | Out-Null
$launcher = Join-Path $launcherRoot "FirstGreen.cmd"
$launcherContent = "@echo off`r`n`"$installedFg`" %*`r`n"
[IO.File]::WriteAllText($launcher, $launcherContent)

if (-not $NoShortcut) {
    $programs = [Environment]::GetFolderPath("Programs")
    $shortcutPath = Join-Path $programs "FirstGreen.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $launcher
    $shortcut.WorkingDirectory = [Environment]::GetFolderPath("UserProfile")
    $shortcut.Description = "Open the FirstGreen coding scheduler"
    $shortcut.Save()
    Write-Output "Start menu shortcut: $shortcutPath"
}

Write-Output "FirstGreen launcher: $launcher"
Write-Output "Next: fg configure --auto-codex --model MODEL_ID --reasoning low"
