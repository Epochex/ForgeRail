[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Request,
    [string]$UnityPath = '',
    [string]$ProjectPath = '',
    [string]$ReportsDirectory = '',
    [string]$AssetCacheDirectory = '',
    [int]$TimeoutSeconds = 900,
    [switch]$Smoke,
    [switch]$EditorTests
)
$ErrorActionPreference = 'Stop'
$lab = Split-Path $PSScriptRoot -Parent
if (-not $UnityPath) { $UnityPath=Join-Path $lab 'runtime/tools/unity/6000.3.0f1/Editor/Unity.exe' }
if (-not $ProjectPath) { $ProjectPath=Join-Path $lab 'unity/BuildLab' }
if (-not $ReportsDirectory) { $ReportsDirectory=Join-Path $lab ('reports/unity/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8)) }
$ReportsDirectory=[IO.Path]::GetFullPath($ReportsDirectory)
New-Item -ItemType Directory -Force $ReportsDirectory | Out-Null
$record=[ordered]@{status='failed'; adapter='unity'; started_at=[DateTime]::UtcNow.ToString('o'); unity_path=$UnityPath; project_path=$ProjectPath; request=[IO.Path]::GetFullPath($Request)}
$exitCode=1
function Invoke-OwnedProcess([string]$Executable, [string[]]$Arguments, [int]$Seconds) {
    # Start-Process passes one command line on Windows; quote every individual path/value.
    $line=($Arguments | ForEach-Object { '"' + $_.Replace('"','\"') + '"' }) -join ' '
    $child=Start-Process -FilePath $Executable -ArgumentList $line -WorkingDirectory $lab -WindowStyle Hidden -PassThru
    if (-not $child.WaitForExit($Seconds * 1000)) {
        & taskkill.exe /PID $child.Id /T /F | Out-Null
        throw "Process timed out after $Seconds seconds"
    }
    $child.Refresh()
    return $child.ExitCode
}
try {
    if (-not (Test-Path -LiteralPath $UnityPath -PathType Leaf)) {
        $record.status='blocked'; $exitCode=2
        throw "Unity Editor missing. Run scripts/install-unity.ps1, then activate via Unity Hub."
    }
    $requestData=Get-Content -Encoding UTF8 -LiteralPath $Request -Raw | ConvertFrom-Json
    $log=Join-Path $ReportsDirectory 'editor.log'
    $arguments=@('-batchmode','-nographics','-quit','-projectPath',[IO.Path]::GetFullPath($ProjectPath),'-buildTarget','Win64','-logFile',$log)
    if ($AssetCacheDirectory) { $arguments+=@('-assetCacheDir',[IO.Path]::GetFullPath($AssetCacheDirectory)) }
    if ($EditorTests) {
        $arguments+=@('-executeMethod','GameBuild.EditorAcceptance.Run','-acceptanceOutput',(Join-Path $ReportsDirectory 'editor-tests.json'))
    } else {
        $arguments+=@('-executeMethod','GameBuild.BuildEntry.Build','-buildRequest',[IO.Path]::GetFullPath($Request))
    }
    $record.command_arguments=$arguments
    $record.editor_exit_code=Invoke-OwnedProcess $UnityPath $arguments $TimeoutSeconds
    if ($record.editor_exit_code -ne 0) {
        if ((Test-Path -LiteralPath $log) -and (Get-Content -Encoding UTF8 -LiteralPath $log -Raw) -match '(?i)(no valid (Unity Editor )?licen[cs]e|failed to (activate|acquire|obtain).*licen[cs]e|licen[cs]e (activation|validation) failed|licen[cs]e.*(not available|has expired)|exiting.*licen[cs]e|unable to.*licen[cs]e)') {
            $record.status='blocked'; $exitCode=2
            throw 'Unity license unavailable; activate this Editor using Unity Hub and rerun the recorded command'
        }
        throw "Unity batch invocation failed ($($record.editor_exit_code)); inspect $log"
    }
    if ($EditorTests) {
        $checks=Get-Content -Encoding UTF8 -LiteralPath (Join-Path $ReportsDirectory 'editor-tests.json') -Raw | ConvertFrom-Json
        if ($checks.status -ne 'passed') { throw 'Editor resource acceptance did not pass' }
    } else {
        $buildReport=Get-Content -Encoding UTF8 -LiteralPath (Join-Path $requestData.output_dir 'build-report.json') -Raw | ConvertFrom-Json
        if ($buildReport.status -ne 'passed' -or $buildReport.build_id -ne $requestData.build_id) { throw 'Missing or mismatched engine BuildReport' }
        if ($Smoke) {
            $receipt=Join-Path $ReportsDirectory 'smoke-receipt.json'
            $player=Join-Path $requestData.output_dir 'player/GameBuildLab.exe'
            $record.smoke_exit_code=Invoke-OwnedProcess $player @('-batchmode','-nographics','-logFile',(Join-Path $ReportsDirectory 'player.log'),'--smoke-output',$receipt) 45
            if ($record.smoke_exit_code -ne 0) { throw 'Player smoke process failed' }
            $smokeData=Get-Content -Encoding UTF8 -LiteralPath $receipt -Raw | ConvertFrom-Json
            if (-not $smokeData.asset_loaded -or $smokeData.status -ne 'passed') { throw 'Player did not load its AssetBundle' }
            foreach ($field in @('build_id','commit_sha','input_digest','target','configuration')) {
                if ($smokeData.$field -ne $requestData.$field) { throw "Smoke identity mismatch: $field" }
            }
        }
    }
    $record.status='passed'; $exitCode=0
} catch {
    $record.error=$_.Exception.Message
    Write-Warning $record.error
} finally {
    $record.finished_at=[DateTime]::UtcNow.ToString('o')
    $record | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $ReportsDirectory 'invocation.json')
}
Write-Output (Join-Path $ReportsDirectory 'invocation.json')
exit $exitCode
