param([switch]$FullLabs)
$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
Push-Location $labRoot
try {
    $labPython = Join-Path $labRoot '.venv/Scripts/python.exe'
    if (!(Test-Path -LiteralPath $labPython)) { throw 'Prepare the project .venv using README first.' }
    New-Item -ItemType Directory -Force reports | Out-Null
    & $labPython -m pytest -q --junitxml=reports/pytest.xml *> reports/pytest-final.log
    $labTestExit = $LASTEXITCODE
    if ($labTestExit -eq 0) {
        & $labPython -m gamebuild.cli demo --root runtime/demo --report reports/demo.json *> reports/demo.log
        if ($LASTEXITCODE) { throw 'HTTP node experiment failed; inspect reports/demo.log.' }
    }
    if ($FullLabs) { & ./scripts/acceptance-labs.ps1 -Python $labPython }
    & $labPython scripts/summarize.py
    Get-Content -LiteralPath reports/pytest-final.log -Tail 8
    if ($labTestExit) { throw 'Python acceptance failed; inspect reports/pytest-final.log.' }
    Write-Host 'Acceptance matrix: reports/acceptance.json'
} finally { Pop-Location }
