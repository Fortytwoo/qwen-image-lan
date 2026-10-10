param(
    [string]$InstallDir=(Join-Path $env:LOCALAPPDATA 'QwenImageLAN'),
    [string]$HostAddress='', [string]$Network='', [string]$RpId=($env:COMPUTERNAME.ToLowerInvariant()+'.local'),
    [int]$Port=8443,[int]$EnginePort=1235,[double]$MaxVram=8,[int]$Threads=8,
    [switch]$ConfigureOnly,[switch]$SkipDownloads,[switch]$SkipHardwareCheck
)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$InstallDir=[IO.Path]::GetFullPath($InstallDir)
$RpId=$RpId.ToLowerInvariant().TrimEnd('.')
if ($InstallDir -eq [IO.Path]::GetFullPath($repo)) {throw 'Use a separate installation directory; do not install into the source checkout.'}
if (-not [Environment]::Is64BitOperatingSystem) {throw 'Windows x64 is required.'}
$uv=Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {throw 'Install uv first: winget install --id astral-sh.uv --exact. Reopen PowerShell afterwards.'}
if (-not $HostAddress) {
    $candidates=@(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway -and $_.IPv4Address.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)'})
    if ($candidates.Count -ne 1) {throw 'Specify -HostAddress and -Network explicitly: more than one or no private LAN adapter was detected.'}
    $HostAddress=$candidates[0].IPv4Address.IPAddress
    $prefix=[int]$candidates[0].IPv4Address.PrefixLength
} else {
    $address=Get-NetIPAddress -IPAddress $HostAddress -AddressFamily IPv4 -ErrorAction Stop | Select-Object -First 1
    $prefix=[int]$address.PrefixLength
}
$env:PYTHONUTF8='1';$env:PYTHONIOENCODING='utf-8'
if (-not $SkipHardwareCheck -and -not $ConfigureOnly) {
    $gpuCommand=Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $gpuCommand) {throw 'NVIDIA driver and nvidia-smi are required.'}
    $gpus=@(& $gpuCommand.Source --query-gpu=name,memory.total --format=csv,noheader,nounits)
    if ($LASTEXITCODE -ne 0 -or -not $gpus) {throw 'Could not query the NVIDIA GPU.'}
    $gpu=$gpus[0] -split ','
    if ([int]$gpu[1].Trim() -lt 11000) {throw 'This tested preset requires approximately 12 GB VRAM. Do not skip this check without reviewing memory settings.'}
    Write-Output ('GPU: '+$gpus[0])
}
$drive=New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($InstallDir))
if ($drive.DriveFormat -ne 'NTFS' -or $drive.DriveType -eq 'Network') {throw 'Use a local NTFS installation directory.'}
if (-not $ConfigureOnly -and $drive.AvailableFreeSpace -lt 30GB) {throw 'Reserve at least 30 GB of free disk space for downloads, extraction and encrypted history.'}
New-Item -ItemType Directory -Path (Join-Path $InstallDir 'service') -Force | Out-Null
$python=Join-Path $InstallDir 'service\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & $uv.Source venv --python 3.12 (Join-Path $InstallDir 'service\.venv')
    if ($LASTEXITCODE -ne 0) {throw 'uv venv failed.'}
}
if (-not $Network) {
    $Network=& $python -c 'import ipaddress,sys;print(ipaddress.ip_interface(sys.argv[1]).network)' "$HostAddress/$prefix"
    if ($LASTEXITCODE -ne 0) {throw 'Could not determine LAN subnet.'}
}
& $uv.Source pip install --python $python -r (Join-Path $repo 'service\requirements.txt')
if ($LASTEXITCODE -ne 0) {throw 'Python dependency installation failed. If upgrading a running instance, stop it first.'}
# Validate existing configuration and establish private ACLs before touching application files.
& $python (Join-Path $repo 'service\setup_service.py') --root (Join-Path $InstallDir 'service') --host $HostAddress --network $Network --rp-id $RpId --port $Port --engine-port $EnginePort --max-vram $MaxVram --threads $Threads
if ($LASTEXITCODE -ne 0) {throw 'Configuration differs or setup failed. Existing keys and data were preserved.'}
$backupName=(Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss-fff')
foreach ($directory in @('service','scripts')) {
    $destination=Join-Path $InstallDir $directory
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    foreach ($file in (Get-ChildItem -LiteralPath (Join-Path $repo $directory) -File)) {
        if ($file.Extension -notin @('.py','.ps1','.html','.js','.txt')) {continue}
        $target=Join-Path $destination $file.Name
        if (Test-Path -LiteralPath $target) {
            if ((Get-FileHash -LiteralPath $target).Hash -eq (Get-FileHash -LiteralPath $file.FullName).Hash) {continue}
            $backup=Join-Path $InstallDir "backups\$backupName\$directory"
            New-Item -ItemType Directory -Path $backup -Force | Out-Null
            Copy-Item -LiteralPath $target -Destination $backup
        }
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
    }
}
foreach ($name in @('models-manifest.json','Start-Qwen.cmd','Stop-Qwen.cmd','Register-Qwen-Passkey.cmd','Trust-Certificate.cmd')) {
    Copy-Item -LiteralPath (Join-Path $repo $name) -Destination (Join-Path $InstallDir $name) -Force
}
$origin="https://${RpId}:$Port"
& $python (Join-Path $repo 'scripts\localize_webui.py') --input (Join-Path $repo 'vendor\webui.html') --output (Join-Path $InstallDir 'webui-turbo.html') --origin $origin
if ($LASTEXITCODE -ne 0) {throw 'WebUI localization failed.'}
$fingerprint=(Get-FileHash -LiteralPath (Join-Path $InstallDir 'service\certs\Qwen-LAN-CA.cer') -Algorithm SHA256).Hash.ToLowerInvariant()
@{sha256=$fingerprint} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $InstallDir 'certificate-fingerprint.json') -Encoding UTF8
if (-not $ConfigureOnly) {
    $arguments=@((Join-Path $repo 'scripts\download_models.py'),'--manifest',(Join-Path $repo 'models-manifest.json'),'--root',$InstallDir)
    if ($SkipDownloads) {$arguments+='--skip-download'}
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {throw 'Model/engine verification failed; partial downloads were preserved.'}
}
Write-Output "Prepared: $InstallDir"
Write-Output "URL: $origin"
Write-Output 'Next: trust the private CA yourself, start the service, and register your real Passkey.'
if ($ConfigureOnly) {Write-Output 'Configuration only: no engine/models were downloaded or started.'}
