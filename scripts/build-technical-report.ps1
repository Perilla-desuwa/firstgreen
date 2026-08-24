[CmdletBinding()]
param(
    [switch]$AllowPlaceholders,
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$sourceDirectory = Join-Path $repoRoot "docs\publication"
$reportSource = Join-Path $sourceDirectory "technical-report.tex"
$resultsSource = Join-Path $sourceDirectory "results.tex"
$referencesSource = Join-Path $sourceDirectory "references.bib"
$temporaryDirectory = Join-Path $repoRoot "tmp\pdfs\technical-report-build"

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot "output\pdf"
}
elseif (-not [System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot $OutputDirectory
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)

foreach ($required in @($reportSource, $resultsSource, $referencesSource)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required report source is missing: $required"
    }
}

if (-not $AllowPlaceholders) {
    $citationFile = Join-Path $repoRoot "CITATION.cff"
    if (-not (Test-Path -LiteralPath $citationFile -PathType Leaf)) {
        $citationFile = Join-Path $repoRoot "CITATION.cff.template"
    }
    $placeholderFiles = @(
        $reportSource,
        $resultsSource,
        $citationFile,
        (Join-Path $repoRoot ".github\ISSUE_TEMPLATE\config.yml")
    )
    $placeholders = Select-String -LiteralPath $placeholderFiles -Pattern "TBD|FILL_ME|YYYY-MM-DD"
    if ($placeholders) {
        $locations = ($placeholders | ForEach-Object { "$($_.Path):$($_.LineNumber)" }) -join ", "
        throw "Release placeholders remain: $locations. Use -AllowPlaceholders only for draft QA."
    }
}

foreach ($tool in @("pdflatex", "bibtex")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool is required to build the technical report."
    }
}

New-Item -ItemType Directory -Force -Path $temporaryDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$pdflatexOutput = "-output-directory=$temporaryDirectory"
$oldBibInputs = $env:BIBINPUTS
$env:BIBINPUTS = "$sourceDirectory;$oldBibInputs"

try {
    Push-Location $sourceDirectory
    try {
        Write-Host "Compiling technical report (pass 1/3)..."
        & pdflatex -interaction=nonstopmode -halt-on-error $pdflatexOutput technical-report.tex |
            Out-Null
        if ($LASTEXITCODE -ne 0) { throw "pdflatex first pass failed with $LASTEXITCODE" }

        Push-Location $temporaryDirectory
        try {
            Write-Host "Resolving bibliography..."
            & bibtex technical-report | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "bibtex failed with $LASTEXITCODE" }
        }
        finally {
            Pop-Location
        }

        Write-Host "Compiling technical report (pass 2/3)..."
        & pdflatex -interaction=nonstopmode -halt-on-error $pdflatexOutput technical-report.tex |
            Out-Null
        if ($LASTEXITCODE -ne 0) { throw "pdflatex second pass failed with $LASTEXITCODE" }
        Write-Host "Compiling technical report (pass 3/3)..."
        & pdflatex -interaction=nonstopmode -halt-on-error $pdflatexOutput technical-report.tex |
            Out-Null
        if ($LASTEXITCODE -ne 0) { throw "pdflatex final pass failed with $LASTEXITCODE" }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:BIBINPUTS = $oldBibInputs
}

$builtPdf = Join-Path $temporaryDirectory "technical-report.pdf"
$releasePdf = Join-Path $OutputDirectory "firstgreen-technical-report.pdf"
Copy-Item -LiteralPath $builtPdf -Destination $releasePdf -Force

$layoutProblems = Select-String `
    -LiteralPath (Join-Path $temporaryDirectory "technical-report.log") `
    -Pattern "Overfull"
if ($layoutProblems) {
    throw "The report compiled but contains overfull boxes. Inspect the build log before release."
}

Get-Item -LiteralPath $releasePdf
