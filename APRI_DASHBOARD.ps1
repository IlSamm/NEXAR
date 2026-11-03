$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
$pyw=Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if(-not(Test-Path $pyw)){throw 'Esegui prima INSTALLA_E_AVVIA.cmd'}
$port=8765
$running=$false
try {$c=[System.Net.Sockets.TcpClient]::new();$c.Connect('127.0.0.1',$port);$running=$true;$c.Close()} catch {}
if(-not $running){Start-Process -FilePath $pyw -ArgumentList ('"'+(Join-Path $PSScriptRoot 'tray.py')+'"') -WorkingDirectory $PSScriptRoot;Start-Sleep -Seconds 2}
$cfg=Get-Content (Join-Path $PSScriptRoot 'config.json') -Raw | ConvertFrom-Json
Start-Process ('http://127.0.0.1:8765/#access='+[string]$cfg.access_token)
