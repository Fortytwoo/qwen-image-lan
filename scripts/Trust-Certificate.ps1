. (Join-Path $PSScriptRoot 'Common.ps1')
$config=Get-QwenConfig
$certificate=$config.ca_der
$expected=(Get-Content -LiteralPath (Join-Path $QwenRoot 'certificate-fingerprint.json') -Raw -Encoding UTF8 | ConvertFrom-Json).sha256
$actual=(Get-FileHash -LiteralPath $certificate -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) {throw 'Certificate fingerprint differs. Nothing imported.'}
Import-Certificate -FilePath $certificate -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
Write-Output 'CA trusted for this Windows user. Complete any Windows security prompt yourself.'
