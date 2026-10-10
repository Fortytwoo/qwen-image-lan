param([switch]$NoBrowser)
. (Join-Path $PSScriptRoot 'Common.ps1')
$config=Get-QwenConfig
$script=Join-Path $QwenRoot 'service\run_server.py'
$python=Join-Path $QwenRoot 'service\.venv\Scripts\python.exe'
$listener=Get-NetTCPConnection -LocalPort $config.port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owner=Get-CimInstance Win32_Process -Filter "ProcessId = $($listener[0].OwningProcess)"
    if ($owner.CommandLine -notmatch [regex]::Escape($script) -or $listener[0].LocalAddress -ne $config.host) {throw 'HTTPS port belongs to another program.'}
    Write-QwenProcessState -Process $owner -Path (Join-Path $QwenRoot 'gateway-process.json') -Script $script
    Write-Output ('Already running: '+$config.origin)
    if (-not $NoBrowser) {Start-Process ($config.origin+'/')}
    exit 0
}
& (Join-Path $PSScriptRoot 'Start-Engine.ps1') -NoBrowser
$env:PYTHONUTF8='1';$env:PYTHONIOENCODING='utf-8'
$process=Start-QwenProcess -File $python -Arguments @('-X','utf8',$script) -WorkingDirectory (Join-Path $QwenRoot 'service') -LogPrefix (Join-Path $QwenRoot 'logs\gateway')
$deadline=(Get-Date).AddMinutes(2)
while ((Get-Date) -lt $deadline) {
    $listener=Get-NetTCPConnection -LocalAddress $config.host -LocalPort $config.port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        & $python (Join-Path $PSScriptRoot 'check_health.py') (Join-Path $QwenRoot 'service\config.json') 2>$null
        if ($LASTEXITCODE -eq 0) {
            $owner=Get-CimInstance Win32_Process -Filter "ProcessId = $($listener[0].OwningProcess)"
            Write-QwenProcessState -Process $owner -Path (Join-Path $QwenRoot 'gateway-process.json') -Script $script
            Write-Output ('Ready: '+$config.origin)
            if (-not $NoBrowser) {Start-Process ($config.origin+'/')}
            exit 0
        }
    }
    $process.Refresh()
    if ($process.HasExited) {throw 'Gateway exited. Inspect logs/gateway.stderr.log.'}
    Start-Sleep -Seconds 2
}
throw 'HTTPS health check failed. Check hostname resolution, gateway logs and configured LAN address.'
