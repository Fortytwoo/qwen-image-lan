param([switch]$NoBrowser)
. (Join-Path $PSScriptRoot 'Common.ps1')
$config=Get-QwenConfig
$port=[int]$config.engine.port
$engine=Join-Path $QwenRoot 'engine\sd-server.exe'
$listener=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owner=Get-CimInstance Win32_Process -Filter "ProcessId = $($listener[0].OwningProcess)"
    if ($owner.ExecutablePath -ne $engine -or $listener[0].LocalAddress -ne '127.0.0.1') {throw 'Engine port belongs to another program.'}
    Write-Output 'Engine already running.'
    exit 0
}
$models=@('Qwen-Image-2.1-Turbo-AD-Q4_K.gguf','Qwen-Image-2.1-Turbo-Abliterated-Uncensored-AD-Q4_K.gguf','qwen_image_2.1_vae_bf16.safetensors','mmproj-Qwen-Image-2.1-Turbo-Abliterated-Uncensored-F16.gguf')
foreach ($model in $models) {if (-not (Test-Path -LiteralPath (Join-Path $QwenRoot "models\$model"))) {throw "Missing model: $model"}}
$arguments=@(
    '--diffusion-model',(Join-Path $QwenRoot ('models\'+$models[0])),
    '--llm',(Join-Path $QwenRoot ('models\'+$models[1])),
    '--vae',(Join-Path $QwenRoot ('models\'+$models[2])),
    '--llm_vision',(Join-Path $QwenRoot ('models\'+$models[3])),
    '--listen-ip','127.0.0.1','--listen-port',"$port",'--serve-html-path',(Join-Path $QwenRoot 'webui-turbo.html'),
    '--steps','8','--cfg-scale','1.0','--sampling-method','euler',
    '--sigmas','1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0',
    '-W','1024','-H','1024','--backend','CUDA0','--offload-to-cpu','--mmap','--diffusion-fa','--vae-tiling',
    '--max-vram',([double]$config.engine.max_vram).ToString([Globalization.CultureInfo]::InvariantCulture),'--threads',"$($config.engine.threads)",'--conditioning-cache-size','2')
New-Item -ItemType Directory -Path (Join-Path $QwenRoot 'logs') -Force | Out-Null
$process=Start-QwenProcess -File $engine -Arguments $arguments -WorkingDirectory (Join-Path $QwenRoot 'engine') -LogPrefix (Join-Path $QwenRoot 'logs\engine')
$deadline=(Get-Date).AddMinutes(5)
while ((Get-Date) -lt $deadline) {
    $process.Refresh()
    if ($process.HasExited) {throw 'Engine exited. See logs/engine.stderr.log.'}
    try {
        $response=Invoke-RestMethod -Uri "http://127.0.0.1:$port/sdcpp/v1/capabilities" -TimeoutSec 3
        if ($response.supported_modes) {
            $owner=Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
            Write-QwenProcessState -Process $owner -Path (Join-Path $QwenRoot 'engine-process.json')
            Write-Output 'Engine ready; loopback only.'
            exit 0
        }
    } catch {}
    Start-Sleep -Seconds 2
}
throw 'Engine startup timed out; inspect logs before retrying.'
