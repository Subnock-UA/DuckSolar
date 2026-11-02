param([switch]$AllowUnsigned)
$ErrorActionPreference = 'Stop'
$sourceTask = [IO.Path]::GetFullPath($PSScriptRoot)
$exeTask = Join-Path $sourceTask 'DuckSolar_PC_Client.exe'
$manifestTask = Get-Content -LiteralPath (Join-Path $sourceTask 'PAYLOAD_SHA256.json') -Raw | ConvertFrom-Json
$signatureTask = Get-AuthenticodeSignature -LiteralPath $exeTask
if ($manifestTask.signing_thumbprint) {
    if ($signatureTask.Status -ne 'Valid' -or $signatureTask.SignerCertificate.Thumbprint -ne $manifestTask.signing_thumbprint) { throw 'Invalid application signature. Installation stopped.' }
} elseif (-not $AllowUnsigned) { throw 'Unsigned build: verify the release SHA256, then use -AllowUnsigned if trusted, or run the portable EXE.' }
try { $mutexTask=[Threading.Mutex]::OpenExisting('Local\DuckSolar_B2_Client'); $mutexTask.Dispose(); throw 'Close Duck Solar b2, including the tray icon, before installation.' } catch [Threading.WaitHandleCannotBeOpenedException] { }
$baseTask = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs\DuckSolarB2PC'))
$targetTask = [IO.Path]::GetFullPath((Join-Path $baseTask 'b2.0.0'))
if (-not $targetTask.StartsWith($baseTask+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid installation directory' }
foreach ($entryTask in $manifestTask.files.PSObject.Properties) {
    $inputTask=[IO.Path]::GetFullPath((Join-Path $sourceTask $entryTask.Name))
    if (-not $inputTask.StartsWith($sourceTask+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid package member' }
    if ((Get-FileHash -LiteralPath $inputTask -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entryTask.Value) { throw ('Package checksum mismatch: '+$entryTask.Name) }
}
New-Item -ItemType Directory -Path $targetTask -Force | Out-Null
foreach ($entryTask in $manifestTask.files.PSObject.Properties) {
    $inputTask=Join-Path $sourceTask $entryTask.Name
    $outputTask=[IO.Path]::GetFullPath((Join-Path $targetTask $entryTask.Name))
    if (-not $outputTask.StartsWith($targetTask+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid package output' }
    New-Item -ItemType Directory -Path (Split-Path $outputTask) -Force | Out-Null
    Copy-Item -LiteralPath $inputTask -Destination $outputTask -Force
}
Copy-Item -LiteralPath (Join-Path $sourceTask 'PAYLOAD_SHA256.json') -Destination $targetTask -Force
$installedExeTask=Join-Path $targetTask 'DuckSolar_PC_Client.exe'
$shellTask=New-Object -ComObject WScript.Shell
foreach ($folderTask in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))) {
    $shortcutTask=$shellTask.CreateShortcut((Join-Path $folderTask 'Duck Solar b2 (ПК).lnk'))
    $shortcutTask.TargetPath=$installedExeTask; $shortcutTask.WorkingDirectory=$targetTask; $shortcutTask.IconLocation=$installedExeTask; $shortcutTask.Save()
}
Write-Host 'Duck Solar PC b2.0.0 installed. Start from the desktop shortcut.'
Write-Host 'Profiles remain in %LOCALAPPDATA%\DuckSolarB2\PCClient. Old data is preserved.'

