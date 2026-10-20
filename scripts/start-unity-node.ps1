$ErrorActionPreference='Stop'
$labRoot=Split-Path -Parent $PSScriptRoot
$labPython=Join-Path $labRoot '.venv/Scripts/python.exe'
$labUnity=Join-Path $labRoot 'runtime/tools/unity/6000.3.0f1/Editor/Unity.exe'
if (!(Test-Path -LiteralPath $labUnity)) { throw 'Install the pinned Unity Editor first.' }
if (!(Test-Path -LiteralPath (Join-Path $labRoot '.runtime/credentials.json'))) { throw 'Run scripts/start.ps1 first.' }
$labPidPath=Join-Path $labRoot '.runtime/windows-node.pid'
if (Test-Path -LiteralPath $labPidPath) {
    $labExisting=Get-Process -Id ([int](Get-Content -LiteralPath $labPidPath)) -ErrorAction SilentlyContinue
    if ($labExisting) { throw 'Recorded node is still running; use scripts/stop-unity-node.ps1 first.' }
}
$labProcess=Start-Process -FilePath $labPython -ArgumentList @('scripts/run-unity-node.py') -WorkingDirectory $labRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $labRoot '.runtime/node.stdout.log') -RedirectStandardError (Join-Path $labRoot '.runtime/node.stderr.log') -PassThru
$labProcess.Id | Set-Content -LiteralPath $labPidPath
Write-Host ('Windows Unity node started: PID ' + $labProcess.Id)
