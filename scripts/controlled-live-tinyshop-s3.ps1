[CmdletBinding()]
param(
    [switch]$Run,
    [ValidatePattern("^[a-z0-9][a-z0-9-]{0,79}$")]
    [string]$ExperimentId = "controlled-live-tinyshop-s3-luna-v1",
    [double]$MinimumFreeMemoryGiB = 12
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$benchmarkRoot = Join-Path (Split-Path -Parent $repoRoot) "firstgreen_benchmarks"
$runtimeDir = Join-Path $benchmarkRoot "$ExperimentId-runtime"
$reportsDir = Join-Path $benchmarkRoot "$ExperimentId-reports"
$issue = Join-Path $repoRoot "tests\firstgreen_testbed_package\issues\S3_password_reset.md"
$expectedIssueSha256 = "4B3611B8FF7BB30E39A05BCD0CAA4B538AE2F6B9F6F15FE49C5144EF60039DCC"
$expectedTinyShopTree = "776283b66abaa167ef972e853681f0f29b18ee75"
$codexBinary = "D:\ProgramData\CodexHome\.sandbox-bin\codex.exe"
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

Push-Location $repoRoot
try {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Repository Python runtime is missing: $python"
    }
    if (-not (Test-Path -LiteralPath $issue -PathType Leaf)) {
        throw "Frozen S3 issue is missing: $issue"
    }
    $actualIssueSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $issue).Hash
    if ($actualIssueSha256 -ne $expectedIssueSha256) {
        throw "Frozen S3 issue hash changed: $actualIssueSha256"
    }
    $actualTree = (& git rev-parse HEAD:tests/firstgreen_testbed_package/tinyshop).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualTree -ne $expectedTinyShopTree) {
        throw "TinyShop source tree changed: $actualTree"
    }

    & .\fg.ps1 doctor --codex-binary $codexBinary
    if ($LASTEXITCODE -ne 0) {
        throw "Codex preflight failed"
    }

    Add-Type -AssemblyName Microsoft.VisualBasic
    $computerInfo = [Microsoft.VisualBasic.Devices.ComputerInfo]::new()
    $freeMemoryGiB = [math]::Round($computerInfo.AvailablePhysicalMemory / 1GB, 2)
    [ordered]@{
        experiment_id = $ExperimentId
        source_tree = $actualTree
        issue_sha256 = $actualIssueSha256
        model = "gpt-5.6-luna"
        reasoning = "low"
        root_slots = 2
        maximum_tasks = 5
        repetitions = 1
        free_memory_gib = $freeMemoryGiB
        minimum_free_memory_gib = $MinimumFreeMemoryGiB
        live_execution_requested = [bool]$Run
    } | ConvertTo-Json

    if (-not $Run) {
        Write-Host "Preflight only: no Codex planner or worker was started."
        exit 0
    }
    if ($env:FIRSTGREEN_RUN_CONTROLLED_LIVE -ne "1") {
        throw "Set FIRSTGREEN_RUN_CONTROLLED_LIVE=1 for the authorized live run"
    }
    if ($freeMemoryGiB -lt $MinimumFreeMemoryGiB) {
        throw "Free memory ${freeMemoryGiB} GiB is below the ${MinimumFreeMemoryGiB} GiB gate"
    }
    if ((Test-Path -LiteralPath $runtimeDir) -or (Test-Path -LiteralPath $reportsDir)) {
        throw "TinyShop output already exists; preserve it and choose a new experiment ID"
    }

    $env:FIRSTGREEN_RUN_LIVE_TESTBED_PLANNER = "1"
    $env:FIRSTGREEN_RUN_LIVE_TESTBED_CODING = "1"
    $env:PYTHONPATH = @((Join-Path $repoRoot ".deps"), (Join-Path $repoRoot "src")) -join [IO.Path]::PathSeparator
    & $python -m firstgreen.testbed.run `
        --scenario S3 `
        --live-planner `
        --live-coding `
        --codex-binary $codexBinary `
        --model gpt-5.6-luna `
        --reasoning low `
        --max-live-tasks 5 `
        --live-timeout-seconds 900 `
        --reports-dir $reportsDir `
        --runtime-dir $runtimeDir
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
