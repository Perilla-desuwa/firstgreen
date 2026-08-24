[CmdletBinding()]
param(
    [switch]$Run,
    [string]$Manifest = ".tmp\controlled-live-ramsey-v2\frozen.manifest.yaml",
    [string]$OutputDir = "benchmark-results\controlled-live-ramsey-v2",
    [double]$MinimumFreeMemoryGiB = 12
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$benchmarkRoot = Join-Path (Split-Path -Parent $repoRoot) "firstgreen_benchmarks"
$sourceRepo = Join-Path $benchmarkRoot "ramsey-sharded-proof-20260812\serial-1"
$expectedBaseSha = "3121edac96345cb35a7bea74c3670071221a0e1f"
$expectedManifestSha256 = "75E1CB02C450FFA184C6093C6EADF726B3C0989415ED72BCF10E448355D12FD4"
$codexBinary = "D:\ProgramData\CodexHome\.sandbox-bin\codex.exe"

Push-Location $repoRoot
try {
    if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) {
        throw "Frozen manifest is missing: $Manifest"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRepo ".git"))) {
        throw "Ramsey source repository is missing: $sourceRepo"
    }

    $actualManifestSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Manifest).Hash
    if ($actualManifestSha256 -ne $expectedManifestSha256) {
        throw "Frozen manifest hash changed: $actualManifestSha256"
    }

    $actualBaseSha = (& git -C $sourceRepo rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualBaseSha -ne $expectedBaseSha) {
        throw "Ramsey source base changed: $actualBaseSha"
    }
    $sourceStatus = & git -C $sourceRepo status --porcelain=v1
    if ($LASTEXITCODE -ne 0 -or $sourceStatus) {
        throw "Ramsey source repository must be clean before the matrix starts"
    }

    & .\fg.ps1 validate $Manifest
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen manifest validation failed"
    }
    & .\fg.ps1 doctor --codex-binary $codexBinary
    if ($LASTEXITCODE -ne 0) {
        throw "Codex preflight failed"
    }

    Add-Type -AssemblyName Microsoft.VisualBasic
    $computerInfo = [Microsoft.VisualBasic.Devices.ComputerInfo]::new()
    $freeMemoryGiB = [math]::Round($computerInfo.AvailablePhysicalMemory / 1GB, 2)
    $preflight = [ordered]@{
        experiment_id = "controlled-live-ramsey-v2"
        manifest_sha256 = $actualManifestSha256
        source_base_sha = $actualBaseSha
        slots = @(1, 2, 4, 8)
        repetitions = 2
        free_memory_gib = $freeMemoryGiB
        minimum_free_memory_gib = $MinimumFreeMemoryGiB
        live_execution_requested = [bool]$Run
    }
    $preflight | ConvertTo-Json

    if (-not $Run) {
        Write-Host "Preflight only: no Codex worker was started."
        exit 0
    }
    if ($env:FIRSTGREEN_RUN_CONTROLLED_LIVE -ne "1") {
        throw "Set FIRSTGREEN_RUN_CONTROLLED_LIVE=1 for the authorized live run"
    }
    if ($freeMemoryGiB -lt $MinimumFreeMemoryGiB) {
        throw "Free memory ${freeMemoryGiB} GiB is below the ${MinimumFreeMemoryGiB} GiB gate"
    }
    if (Test-Path -LiteralPath $OutputDir) {
        throw "Output directory already exists; preserve it and choose a new experiment ID"
    }

    & .\fg.ps1 benchmark scaling $Manifest `
        --slots "1,2,4,8" `
        --repetitions 2 `
        --output-dir $OutputDir
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
