[CmdletBinding()]
param(
    [string]$InstallRoot = "",
    [switch]$DownloadOnly
)
$ErrorActionPreference = 'Stop'
$lab = Split-Path $PSScriptRoot -Parent
$version = '6000.3.0f1'
$revision = 'd1870ce95baf'
if (-not $InstallRoot) { $InstallRoot = Join-Path $lab "runtime/tools/unity/$version" }
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$evidence = Join-Path $lab 'reports/unity'
$downloads = Join-Path $evidence 'downloads'
New-Item -ItemType Directory -Force $downloads | Out-Null
$editor = Join-Path $InstallRoot 'Editor/Unity.exe'
$url = "https://download.unity3d.com/download_unity/$revision/Windows64EditorInstaller/UnitySetup64-$version.exe"
$installer = Join-Path $downloads "UnitySetup64-$version.exe"
$record = [ordered]@{status='blocked'; version=$version; revision=$revision; source_url=$url; editor=$editor; started_at=[DateTime]::UtcNow.ToString('o')}
try {
    if (-not (Test-Path -LiteralPath $editor)) {
        if (-not (Test-Path -LiteralPath $installer)) {
            # Incomplete downloads retain .partial and cannot be mistaken for a complete installer.
            & curl.exe --fail --location --retry 2 --output "$installer.partial" $url
            if ($LASTEXITCODE -ne 0) { throw "Official installer download failed ($LASTEXITCODE)" }
            Move-Item -LiteralPath "$installer.partial" -Destination $installer
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        $record.signature_status = $signature.Status.ToString()
        $record.publisher = $signature.SignerCertificate.Subject
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Unity') {
            throw 'Installer Authenticode signature must be valid and issued to Unity'
        }
        $record.installer_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
        if ($DownloadOnly) { $record.status='downloaded'; return }
        if ((Get-PSDrive -Name ([IO.Path]::GetPathRoot($InstallRoot).TrimEnd(':\'))).Free -lt 20GB) { throw 'At least 20 GiB free space required' }
        # Unity's NSIS installer requires /D as the final unquoted argument, even for paths containing spaces.
        $process = Start-Process -FilePath $installer -ArgumentList "/S /D=$InstallRoot" -WindowStyle Hidden -Wait -PassThru
        $record.installer_exit_code = $process.ExitCode
        if ($process.ExitCode -ne 0) { throw "Installer failed ($($process.ExitCode))" }
        if (-not (Test-Path -LiteralPath $editor)) { throw "Installation did not produce $editor" }
    }
    $fileVersion = (Get-Item -LiteralPath $editor).VersionInfo
    $record.product_version = $fileVersion.ProductVersion
    $record.file_version = $fileVersion.FileVersion
    if ($record.product_version -notmatch [regex]::Escape($version)) { throw 'Installed Editor product version does not match pinned version' }
    $record.status='installed'
    $record.license_status='not_checked; real batch execution determines license availability'
    Write-Output "Editor installed: $editor"
} catch {
    $record.error=$_.Exception.Message
    throw
} finally {
    $record.finished_at=[DateTime]::UtcNow.ToString('o')
    $record | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $evidence 'installation.json')
}
