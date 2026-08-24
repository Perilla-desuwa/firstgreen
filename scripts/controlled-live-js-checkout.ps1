[CmdletBinding()]
param(
    [switch]$Plan,
    [switch]$RunApproved,
    [double]$MinimumFreeMemoryGiB = 12,
    [string]$CodexBinary,
    [string]$NodeBinary
)

$ErrorActionPreference = "Stop"

if ($Plan -and $RunApproved) {
    throw "Choose either -Plan or -RunApproved"
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$benchmarkRoot = Join-Path (Split-Path -Parent $repoRoot) "firstgreen_benchmarks"
$sourceRepo = Join-Path $benchmarkRoot "firstgreen-js-checkout-case"
$stateRoot = Join-Path $benchmarkRoot "controlled-live-js-checkout-v1"
$planningState = Join-Path $stateRoot "planning-state"
$candidatePlan = Join-Path $stateRoot "candidate-plan.yaml"
$frozenManifest = Join-Path $repoRoot ".tmp\controlled-live-js-checkout-v1\frozen.manifest.yaml"
$issue = Join-Path $sourceRepo "issues\idempotent-checkout.md"
$expectedBaseSha = "59184e7b6ea77e6d6445b8544ef82edbe15e6996"
$expectedIssueSha256 = "A4D8293373084A61DAE5234A0A210E8CCE774B2FB93778334C91CE9BCD95F64B"
$expectedCandidatePlanSha256 = "E2B7BA77AC0D8D3CC8B9CD36A1C5AE9EEA186C972634BCA08B82D7E6B4C61A89"
$expectedManifestSha256 = "D6213E5DB3B697B5D866DFCC65886A2A944AF7B6CB062A068A41B0C9D32DE9F3"
if ([string]::IsNullOrWhiteSpace($CodexBinary)) {
    $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
    if ($null -eq $codexCommand) { throw "Codex CLI was not found on PATH; pass -CodexBinary." }
    $CodexBinary = $codexCommand.Source
}
else {
    $CodexBinary = [System.IO.Path]::GetFullPath($CodexBinary)
}
if ([string]::IsNullOrWhiteSpace($NodeBinary)) {
    $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
    if ($null -eq $nodeCommand) { throw "Node.js was not found on PATH; pass -NodeBinary." }
    $NodeBinary = $nodeCommand.Source
}
else {
    $NodeBinary = [System.IO.Path]::GetFullPath($NodeBinary)
}
$nodeDir = Split-Path -Parent $NodeBinary

Push-Location $repoRoot
try {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRepo ".git"))) {
        throw "JavaScript source repository is missing: $sourceRepo"
    }
    $actualBaseSha = (& git -C $sourceRepo rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualBaseSha -ne $expectedBaseSha) {
        throw "JavaScript source base changed: $actualBaseSha"
    }
    $sourceStatus = & git -C $sourceRepo status --porcelain=v1
    if ($LASTEXITCODE -ne 0 -or $sourceStatus) {
        throw "JavaScript source repository must be clean"
    }
    $actualIssueSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $issue).Hash
    if ($actualIssueSha256 -ne $expectedIssueSha256) {
        throw "Frozen JavaScript issue hash changed: $actualIssueSha256"
    }
    if (-not (Test-Path -LiteralPath $NodeBinary -PathType Leaf)) {
        throw "Node.js executable is missing: $NodeBinary"
    }

    $oldPath = $env:PATH
    $env:PATH = "$nodeDir$([IO.Path]::PathSeparator)$oldPath"
    Push-Location $sourceRepo
    try {
        & $NodeBinary --test
        if ($LASTEXITCODE -ne 0) {
            throw "JavaScript clean baseline failed"
        }
    }
    finally {
        Pop-Location
    }
    & .\fg.ps1 doctor --repo $sourceRepo --codex-binary $CodexBinary
    if ($LASTEXITCODE -ne 0) {
        throw "Codex preflight failed"
    }

    Add-Type -AssemblyName Microsoft.VisualBasic
    $computerInfo = [Microsoft.VisualBasic.Devices.ComputerInfo]::new()
    $freeMemoryGiB = [math]::Round($computerInfo.AvailablePhysicalMemory / 1GB, 2)
    [ordered]@{
        experiment_id = "controlled-live-js-checkout-v1"
        source_base_sha = $actualBaseSha
        issue_sha256 = $actualIssueSha256
        planner_model = "gpt-5.6-luna"
        planner_reasoning = "medium"
        worker_model = "gpt-5.6-luna"
        worker_reasoning = "low"
        root_slots_hard_max = 2
        repetitions = 1
        candidate_plan_exists = (Test-Path -LiteralPath $candidatePlan -PathType Leaf)
        frozen_manifest_exists = (Test-Path -LiteralPath $frozenManifest -PathType Leaf)
        free_memory_gib = $freeMemoryGiB
        minimum_free_memory_gib = $MinimumFreeMemoryGiB
        requested_phase = if ($Plan) { "plan" } elseif ($RunApproved) { "run-approved" } else { "preflight" }
    } | ConvertTo-Json

    if (-not $Plan -and -not $RunApproved) {
        Write-Host "Preflight only: no Codex planner or worker was started."
        exit 0
    }
    if ($env:FIRSTGREEN_RUN_CONTROLLED_LIVE -ne "1") {
        throw "Set FIRSTGREEN_RUN_CONTROLLED_LIVE=1 for an authorized live phase"
    }
    if ($freeMemoryGiB -lt $MinimumFreeMemoryGiB) {
        throw "Free memory ${freeMemoryGiB} GiB is below the ${MinimumFreeMemoryGiB} GiB gate"
    }

    if ($Plan) {
        if ($env:FIRSTGREEN_RUN_JS_CHECKOUT_PLAN -ne "1") {
            throw "Set FIRSTGREEN_RUN_JS_CHECKOUT_PLAN=1 for the single authorized Luna planner call"
        }
        if (Test-Path -LiteralPath $stateRoot) {
            throw "JavaScript planning output already exists; preserve it and inspect the candidate"
        }
        New-Item -ItemType Directory -Path $stateRoot | Out-Null
        & .\fg.ps1 plan $issue `
            --repo $sourceRepo `
            --output $candidatePlan `
            --planner-provider codex `
            --planner-model gpt-5.6-luna `
            --codex-binary $CodexBinary `
            --max-plan-tasks 5 `
            --allow-path "src/**" `
            --allow-path "test/**" `
            --allow-path "README.md" `
            --no-history-analysis `
            --state-dir $planningState
        exit $LASTEXITCODE
    }

    if ($env:FIRSTGREEN_RUN_JS_CHECKOUT_WORKERS -ne "1") {
        throw "Set FIRSTGREEN_RUN_JS_CHECKOUT_WORKERS=1 only after candidate review and Manifest freeze"
    }
    if (-not (Test-Path -LiteralPath $frozenManifest -PathType Leaf)) {
        throw "Reviewed frozen Manifest is missing; run the planner, review it, and freeze it first"
    }
    if (-not (Test-Path -LiteralPath $candidatePlan -PathType Leaf)) {
        throw "Reviewed candidate plan is missing"
    }
    $candidatePlanSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $candidatePlan).Hash
    if ($candidatePlanSha256 -ne $expectedCandidatePlanSha256) {
        throw "Reviewed candidate plan hash changed: $candidatePlanSha256"
    }
    $manifestSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $frozenManifest).Hash
    if ($manifestSha256 -ne $expectedManifestSha256) {
        throw "Frozen Manifest hash changed: $manifestSha256"
    }
    & .\fg.ps1 validate $frozenManifest
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen JavaScript Manifest validation failed"
    }
    & .\fg.ps1 run $frozenManifest --no-tui --state-dir (Join-Path $stateRoot "execution-state")
    exit $LASTEXITCODE
}
finally {
    if ($null -ne $oldPath) {
        $env:PATH = $oldPath
    }
    Pop-Location
}
