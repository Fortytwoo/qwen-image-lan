param([switch]$GatewayOnly)
. (Join-Path $PSScriptRoot 'Common.ps1')
Stop-QwenProcess -StatePath (Join-Path $QwenRoot 'gateway-process.json')
if (-not $GatewayOnly) {Stop-QwenProcess -StatePath (Join-Path $QwenRoot 'engine-process.json')}
Write-Output 'Stopped recorded Qwen processes; encrypted history remains.'
