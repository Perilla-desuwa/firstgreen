[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    Write-Host "== Ramsey v2 =="
    & .\scripts\controlled-live-ramsey.ps1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== TinyShop S3 Luna =="
    & .\scripts\controlled-live-tinyshop-s3.ps1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== JavaScript checkout Luna =="
    & .\scripts\controlled-live-js-checkout.ps1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "All controlled-live inputs passed preflight. No Codex planner or worker was started."
}
finally {
    Pop-Location
}
