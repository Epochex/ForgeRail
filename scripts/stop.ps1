param([switch]$RemoveProjectVolumes)
$ErrorActionPreference='Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $labArgs=@('compose','--env-file','.runtime/lab.env','-p','gamebuildlab','-f','infra/compose.yaml','down')
    if ($RemoveProjectVolumes) { $labArgs += '--volumes' }
    & docker @labArgs
    if ($LASTEXITCODE) { throw 'Project shutdown failed' }
} finally { Pop-Location }
