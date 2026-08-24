$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }

$pythonPaths = [System.Collections.Generic.List[string]]::new()
$pythonPaths.Add((Join-Path $root "src"))
$dependencies = Join-Path $root ".deps"
if (Test-Path -LiteralPath $dependencies) {
    $pythonPaths.Add($dependencies)
}
if ($env:PYTHONPATH) {
    $pythonPaths.Add($env:PYTHONPATH)
}
$env:PYTHONPATH = $pythonPaths -join [IO.Path]::PathSeparator
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

& $python -m firstgreen.cli @args
exit $LASTEXITCODE
