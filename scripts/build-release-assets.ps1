[CmdletBinding()]
param(
    [string]$Version = "0.1.0-rc1",
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot "output\release"
}
elseif (-not [System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot $OutputDirectory
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$expectedOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "output"))
if (-not $OutputDirectory.StartsWith($expectedOutputRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Release output must remain under $expectedOutputRoot"
}

& git diff --quiet
if ($LASTEXITCODE -ne 0) { throw "Tracked working-tree changes must be committed before release build." }
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { throw "The index must be clean before release build." }

$commit = (& git rev-parse HEAD).Trim()
$releaseName = "firstgreen-evidence-$Version"
$stagingParent = Join-Path $OutputDirectory ".staging"
$stagingRoot = Join-Path $stagingParent $releaseName
$zipPath = Join-Path $OutputDirectory "$releaseName.zip"
$zipChecksumPath = "$zipPath.sha256"
$reportSource = Join-Path $repoRoot "output\pdf\firstgreen-technical-report.pdf"
$reportAsset = Join-Path $OutputDirectory "firstgreen-technical-report-$Version.pdf"

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
foreach ($target in @($stagingParent, $zipPath, $zipChecksumPath)) {
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
}

& (Join-Path $PSScriptRoot "build-technical-report.ps1")
if (-not (Test-Path -LiteralPath $reportSource -PathType Leaf)) {
    throw "Technical report was not produced."
}
Copy-Item -LiteralPath $reportSource -Destination $reportAsset -Force

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $python = "python" }
$oldPythonPath = $env:PYTHONPATH
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
$releaseTemp = Join-Path $repoRoot ("tmp\release-build-" + [Guid]::NewGuid().ToString("N"))
$expectedTempRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "tmp"))
$releaseTemp = [System.IO.Path]::GetFullPath($releaseTemp)
if (-not $releaseTemp.StartsWith($expectedTempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Release temporary files must remain under $expectedTempRoot"
}
$bundledDependencies = Join-Path $repoRoot ".deps"
New-Item -ItemType Directory -Path $releaseTemp | Out-Null
$releaseSourceArchive = Join-Path $releaseTemp "tracked-source.zip"
$releaseSource = Join-Path $releaseTemp "tracked-source"
& git archive --format=zip --output=$releaseSourceArchive HEAD
if ($LASTEXITCODE -ne 0) { throw "Could not export the tracked release source." }
Expand-Archive -LiteralPath $releaseSourceArchive -DestinationPath $releaseSource
$env:TEMP = $releaseTemp
$env:TMP = $releaseTemp
if (Test-Path -LiteralPath $bundledDependencies -PathType Container) {
    $env:PYTHONPATH = @($bundledDependencies, $oldPythonPath) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Join-String -Separator ([IO.Path]::PathSeparator)
}
try {
    Push-Location $releaseSource
    try {
        & $python -m hatchling build --directory $OutputDirectory
        if ($LASTEXITCODE -ne 0) { throw "Python package build failed with $LASTEXITCODE" }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
}

try {
    Remove-Item -LiteralPath $releaseTemp -Recurse -Force
}
catch {
    Write-Warning "Could not remove bounded release temporary directory: $releaseTemp"
}

$packageVersion = $Version -replace '-rc', 'rc'
$sdistPath = Join-Path $OutputDirectory "firstgreen-$packageVersion.tar.gz"
if (-not (Test-Path -LiteralPath $sdistPath -PathType Leaf)) {
    throw "Expected source distribution is missing: $sdistPath"
}
$sdistEntries = & tar -tf $sdistPath
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the source distribution." }
$forbiddenSdistEntries = $sdistEntries | Select-String -Pattern '/docs/video/|/\.codex_doc_review/|\.docx$'
if ($forbiddenSdistEntries) {
    throw "The source distribution contains private or untracked release content."
}

$directories = @(
    $stagingRoot,
    (Join-Path $stagingRoot "environment"),
    (Join-Path $stagingRoot "frozen-inputs\ramsey-v2"),
    (Join-Path $stagingRoot "frozen-inputs\tinyshop-s3"),
    (Join-Path $stagingRoot "frozen-inputs\javascript-checkout-v1"),
    (Join-Path $stagingRoot "frozen-inputs\critical-path-ablation"),
    (Join-Path $stagingRoot "results"),
    (Join-Path $stagingRoot "figures"),
    (Join-Path $stagingRoot "report")
)
New-Item -ItemType Directory -Force -Path $directories | Out-Null

Copy-Item -LiteralPath (Join-Path $repoRoot "REPRODUCIBILITY.md") -Destination (Join-Path $stagingRoot "README.md")
Copy-Item -LiteralPath (Join-Path $repoRoot "docs\evidence\public-evidence-plan-v1.md") -Destination (Join-Path $stagingRoot "frozen-inputs")
Copy-Item -LiteralPath (Join-Path $repoRoot "docs\evidence\controlled-live-ramsey-v2-runbook.md") -Destination (Join-Path $stagingRoot "frozen-inputs\ramsey-v2")
Copy-Item -LiteralPath (Join-Path $repoRoot "docs\evidence\controlled-live-luna-s3.md") -Destination (Join-Path $stagingRoot "frozen-inputs\tinyshop-s3")
Copy-Item -LiteralPath (Join-Path $repoRoot "docs\evidence\javascript-idempotent-checkout-v1.md") -Destination (Join-Path $stagingRoot "frozen-inputs\javascript-checkout-v1")
Copy-Item -LiteralPath (Join-Path $repoRoot "benchmarks\scripted-critical-path.yaml") -Destination (Join-Path $stagingRoot "frozen-inputs\critical-path-ablation")
Copy-Item -LiteralPath (Join-Path $repoRoot "benchmarks\scripted-critical-path-stable.yaml") -Destination (Join-Path $stagingRoot "frozen-inputs\critical-path-ablation")
Copy-Item -LiteralPath (Join-Path $repoRoot "benchmarks\scripted-branch-join.yaml") -Destination (Join-Path $stagingRoot "frozen-inputs")
Copy-Item -Path (Join-Path $repoRoot "docs\evidence\results\*") -Destination (Join-Path $stagingRoot "results") -Recurse
Copy-Item -Path (Join-Path $repoRoot "docs\publication\figures\*") -Destination (Join-Path $stagingRoot "figures") -Recurse
Copy-Item -LiteralPath $reportSource -Destination (Join-Path $stagingRoot "report\firstgreen-technical-report.pdf")
Copy-Item -LiteralPath (Join-Path $repoRoot "docs\publication\technical-report.tex") -Destination (Join-Path $stagingRoot "report")
Copy-Item -LiteralPath (Join-Path $repoRoot "docs\publication\results.tex") -Destination (Join-Path $stagingRoot "report")
Copy-Item -LiteralPath (Join-Path $repoRoot "docs\publication\references.bib") -Destination (Join-Path $stagingRoot "report")

$doctorOutput = (& (Join-Path $repoRoot "fg.ps1") doctor 2>&1 | Out-String)
$doctorOutput = $doctorOutput.Replace($repoRoot, "<REPOSITORY>")
$doctorOutput = [regex]::Replace($doctorOutput, "[A-Za-z]:\\Users\\[^\\\s]+\\\.firstgreen", "<USER_STATE>")
$doctorOutput.Trim() | Set-Content -LiteralPath (Join-Path $stagingRoot "environment\doctor.txt") -Encoding utf8

$hostMetadata = [ordered]@{
    summary = "AMD Ryzen 7 7745HX; 16 logical processors; 63.69 GiB RAM; Windows 11; Python 3.12.13"
    logical_processors = 16
    memory_gib = 63.69
    operating_system = "Windows 11"
    timezone = "Asia/Shanghai"
}
$hostMetadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stagingRoot "environment\host.json") -Encoding utf8
$packageListCode = 'import importlib.metadata as m; print("\n".join(sorted((d.metadata.get("Name", "unknown") + "==" + d.version) for d in m.distributions())))'
$oldPackageListPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = @($bundledDependencies, $oldPackageListPythonPath) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Join-String -Separator ([IO.Path]::PathSeparator)
try {
    $packageList = & $python -c $packageListCode
    if ($LASTEXITCODE -ne 0 -or -not $packageList) {
        throw "Installed-package inventory could not be generated."
    }
    ($packageList | Sort-Object -Unique) | Set-Content -LiteralPath (Join-Path $stagingRoot "environment\package-lock.txt") -Encoding utf8
}
finally {
    $env:PYTHONPATH = $oldPackageListPythonPath
}
@(
    "git=$((& git --version).Trim())"
    "python=$((& $python --version 2>&1).Trim())"
    "firstgreen_release=$Version"
) | Set-Content -LiteralPath (Join-Path $stagingRoot "environment\tool-versions.txt") -Encoding utf8

$metadata = [ordered]@{
    schema = "firstgreen-public-artifact-v1"
    release = $Version
    code_commit = $commit
    created_at_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    experiment_protocol = "public-evidence-plan-v1"
    model = "gpt-5.6-luna"
    reasoning_effort = "low; JavaScript planner medium"
    host_summary = $hostMetadata.summary
    result_classes = @("scripted", "controlled-live", "case-study")
    known_missing_cells = @()
    known_invalid_cells = @(
        "critical-path-ablation/protocol-deviation-verifier2-stable",
        "critical-path-ablation/protocol-deviation-verifier2-critical",
        "critical-path-ablation/stable-pre-export-fix"
    )
    known_failed_cells = @("tinyshop-s3: sequential extraction (ready width one)")
}
$metadata | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $stagingRoot "ARTIFACT-METADATA.json") -Encoding utf8

$checksumLines = Get-ChildItem -LiteralPath $stagingRoot -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
        $relative = [System.IO.Path]::GetRelativePath($stagingRoot, $_.FullName).Replace("\", "/")
        "$((Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant())  $relative"
    }
$checksumLines | Set-Content -LiteralPath (Join-Path $stagingRoot "SHA256SUMS.txt") -Encoding ascii

$sensitivePatterns = "[A-Za-z]:\\Users\\|[A-Za-z]:\\Files\\|yorigamishiso|authorization:|bearer[ ]|api[_-]?key[=:]"
$sensitiveHits = Get-ChildItem -LiteralPath $stagingRoot -File -Recurse |
    Where-Object { $_.Extension -notin @(".pdf", ".png") } |
    Select-String -Pattern $sensitivePatterns -CaseSensitive:$false
if ($sensitiveHits) {
    $locations = ($sensitiveHits | ForEach-Object { "$($_.Path):$($_.LineNumber)" }) -join ", "
    throw "Potential private path or secret found in release evidence: $locations"
}

Compress-Archive -LiteralPath $stagingRoot -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
"$zipHash  $([System.IO.Path]::GetFileName($zipPath))" | Set-Content -LiteralPath $zipChecksumPath -Encoding ascii

$releaseBody = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "docs\publication\release-body.md")
$releaseBody += "`n## Evidence archive checksum`n`n``$zipHash``  ``$([System.IO.Path]::GetFileName($zipPath))```n"
$releaseBody | Set-Content -LiteralPath (Join-Path $OutputDirectory "release-body.md") -Encoding utf8

Remove-Item -LiteralPath $stagingParent -Recurse -Force
Get-ChildItem -LiteralPath $OutputDirectory -File | Sort-Object Name
