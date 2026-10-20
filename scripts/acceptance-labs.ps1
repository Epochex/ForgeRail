param([string]$Python='py', [switch]$SkipImages, [switch]$SkipJenkins)
$ErrorActionPreference='Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $labPythonArgs=@(); if ($Python -eq 'py') { $labPythonArgs=@('-3') }
    if (!$SkipImages) { & $Python @labPythonArgs labs/acceptance.py images; if ($LASTEXITCODE) { throw '8-target acceptance failed' } }
    foreach ($labAction in @('services','runtime','messaging')) { & $Python @labPythonArgs labs/acceptance.py $labAction; if ($LASTEXITCODE) { throw "$labAction acceptance failed" } }
    & $Python @labPythonArgs labs/controlplane.py
    if ($LASTEXITCODE) { throw 'Compose control plane acceptance failed' }
    if (!$SkipJenkins) { & $Python @labPythonArgs labs/jenkins.py; if ($LASTEXITCODE) { throw 'Jenkins acceptance failed' } }
    & $Python @labPythonArgs labs/acceptance.py verify
    if ($LASTEXITCODE) { throw 'Required evidence missing' }
} finally { Pop-Location }
