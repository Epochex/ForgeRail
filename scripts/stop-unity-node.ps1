$ErrorActionPreference='Stop'
$labRoot=Split-Path -Parent $PSScriptRoot
$labPidPath=Join-Path $labRoot '.runtime/windows-node.pid'
if (!(Test-Path -LiteralPath $labPidPath)) { Write-Host 'No recorded Windows node.'; exit 0 }
$labNodeId=[int](Get-Content -LiteralPath $labPidPath)
$labProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$labNodeId" -ErrorAction SilentlyContinue
if ($labProcess) {
    if ($labProcess.CommandLine -notmatch 'scripts[\\/]run-unity-node\.py') { throw 'PID belongs to another command; refusing to stop it.' }
    Stop-Process -Id $labNodeId
}
Remove-Item -LiteralPath $labPidPath
Write-Host 'Windows Unity node stopped.'
