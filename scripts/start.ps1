param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
Push-Location $labRoot
try {
    New-Item -ItemType Directory -Force .runtime,reports/labs | Out-Null
    if (!(Test-Path .runtime/lab.env)) {
        foreach ($labPort in @(18980,18981,18982,18983)) {
            $labListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,$labPort)
            try { $labListener.Start() } finally { $labListener.Stop() }
        }
        $labPassword = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
        $labToken = [guid]::NewGuid().ToString('N')
        "JENKINS_PASSWORD=$labPassword`nGAMEBUILD_TOKEN=$labToken`nJENKINS_PORT=18980`nAPI_PORT=18981" | Set-Content .runtime/lab.env
        @{password=$labPassword;token=$labToken} | ConvertTo-Json | Set-Content .runtime/credentials.json
    }
    $labArgs = @('compose','--env-file','.runtime/lab.env','-p','gamebuildlab','-f','infra/compose.yaml','up','-d')
    if (!$SkipBuild) { $labArgs += '--build' }
    & docker @labArgs
    if ($LASTEXITCODE) { throw 'Project startup failed' }
    Write-Host 'Jenkins: http://127.0.0.1:18980 (labadmin; local credential file .runtime/credentials.json)'
    Write-Host 'Control plane: http://127.0.0.1:18981; local GAMEBUILD_TOKEN is in .runtime/lab.env'
} finally { Pop-Location }
