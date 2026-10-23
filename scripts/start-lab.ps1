param([int]$Port = 18766, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$labPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $labPython)) {
    throw 'Install the locked Python dependencies in .venv first; see README.'
}
Push-Location -LiteralPath $projectRoot
try {
    $labArgs = @('-m', 'gamebuild.cli', 'lab', '--port', "$Port")
    if (-not $NoBrowser) { $labArgs += '--open' }
    & $labPython @labArgs
    if ($LASTEXITCODE -ne 0) { throw "Lab exited with code $LASTEXITCODE" }
} finally { Pop-Location }
