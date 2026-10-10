$ErrorActionPreference = 'Stop'
$QwenRoot = Split-Path -Parent $PSScriptRoot
function Get-QwenConfig {
    param([string]$Root=$QwenRoot)
    $configFile=Join-Path $Root 'service\config.json'
    if (-not (Test-Path -LiteralPath $configFile)) { throw 'Run Install-Qwen.ps1 first, then use the launchers in its installation directory.' }
    return Get-Content -LiteralPath $configFile -Raw -Encoding UTF8 | ConvertFrom-Json
}
function ConvertTo-WindowsArgument {
    param([string]$Value)
    # CommandLineToArgvW-compatible quoting, including spaces and trailing backslashes.
    $quoted=[regex]::Replace($Value,'(\\*)"','$1$1\"')
    $quoted=[regex]::Replace($quoted,'(\\+)$','$1$1')
    return '"'+$quoted+'"'
}
function Start-QwenProcess {
    param([string]$File,[string[]]$Arguments,[string]$WorkingDirectory,[string]$LogPrefix)
    $argumentLine=($Arguments | ForEach-Object {ConvertTo-WindowsArgument $_}) -join ' '
    return Start-Process -FilePath $File -ArgumentList $argumentLine -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput ($LogPrefix+'.stdout.log') -RedirectStandardError ($LogPrefix+'.stderr.log')
}
function Write-QwenProcessState {
    param($Process,[string]$Path,[string]$Script='')
    @{process_id=$Process.ProcessId;created_at=$Process.CreationDate.ToUniversalTime().ToString('o');executable=$Process.ExecutablePath;script=$Script} | ConvertTo-Json | Set-Content -LiteralPath $Path -Encoding UTF8
}
function Stop-QwenProcess {
    param([string]$StatePath)
    if (-not (Test-Path -LiteralPath $StatePath)) {return}
    $state=Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $process=Get-CimInstance Win32_Process -Filter "ProcessId = $($state.process_id)"
    if ($process) {
        if ($process.ExecutablePath -ne $state.executable) {throw 'PID belongs to another program; nothing stopped.'}
        if ($state.created_at -is [DateTime]) {$started=$state.created_at.ToUniversalTime()}
        else {$started=[DateTime]::Parse($state.created_at,$null,[Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()}
        if ([Math]::Abs(($process.CreationDate.ToUniversalTime()-$started).TotalSeconds) -gt 2) {throw 'PID creation time differs; nothing stopped.'}
        if ($state.script -and $process.CommandLine -notmatch [regex]::Escape($state.script)) {throw 'PID script differs; nothing stopped.'}
        Stop-Process -Id $state.process_id
    }
    Remove-Item -LiteralPath $StatePath
}
