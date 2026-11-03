# PC ECO Control - setup automatizzato, codice leggibile e senza credenziali distribuite.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host 'PC ECO CONTROL - INSTALLAZIONE E AVVIO' -ForegroundColor Cyan
Write-Host 'Verifico Python 3.11+, dipendenze e avvio con Windows.'
function Test-Python([string]$Exe,[string[]]$PreArgs) {
    try {
        & $Exe @PreArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {return $false}
}
$exe = $null
$preArgs = @()
if (Test-Python -Exe 'py' -PreArgs @('-3')) { $exe = 'py'; $preArgs = @('-3') }
elseif (Test-Python -Exe 'python' -PreArgs @()) { $exe = 'python' }
else {
  $candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:ProgramFiles\Python313\python.exe",
    "$env:ProgramFiles\Python312\python.exe",
    "$env:ProgramFiles\Python311\python.exe"
  )
  foreach($path in $candidates){if((Test-Path $path) -and (Test-Python -Exe $path -PreArgs @())){$exe=$path;break}}
}
if (-not $exe) {
  $winget=Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {throw 'Python non installato e winget non disponibile. Installa Python 3.13 da python.org, poi ripeti.'}
  Write-Host 'Python non trovato. Installo Python 3.13 da winget (origine ufficiale).' -ForegroundColor Yellow
  & winget install --id Python.Python.3.13 --exact --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity
  if ($LASTEXITCODE -ne 0) {throw 'Installazione Python non riuscita; apri winget e verifica permessi/rete.'}
  $path="$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
  if ((Test-Path $path) -and (Test-Python -Exe $path -PreArgs @())) {$exe=$path}
  elseif(Test-Python -Exe 'py' -PreArgs @('-3')) {$exe='py';$preArgs=@('-3')}
  else {throw 'Python installato ma non rilevato. Riavvia Windows, poi esegui di nuovo questo file.'}
}
Write-Host 'Python compatibile trovato.' -ForegroundColor Green
if (-not (Test-Path '.venv\Scripts\python.exe')) {
  & $exe @preArgs -m venv .venv
  if ($LASTEXITCODE -ne 0) {throw 'Impossibile creare ambiente Python isolato.'}
}
$py=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pyw=Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
& $py -m pip install --disable-pip-version-check -r requirements.txt
if($LASTEXITCODE -ne 0){throw 'Impossibile installare i moduli. Serve Internet al primo avvio.'}
& $py inizializza.py
if($LASTEXITCODE -ne 0){throw 'Impossibile generare la configurazione.'}
# Installazione dell'avvio automatico all'accesso Windows (solo l'utente corrente).
$startup=[Environment]::GetFolderPath('Startup')
$shortcut=Join-Path $startup 'PC ECO Control.lnk'
$wsh=New-Object -ComObject WScript.Shell
$link=$wsh.CreateShortcut($shortcut)
$link.TargetPath=$pyw
$link.Arguments='"' + (Join-Path $PSScriptRoot 'tray.py') + '"'
$link.WorkingDirectory=$PSScriptRoot
$link.Description='PC ECO Control - agente locale Windows e Telegram'
$link.Save()
# Evita di creare due agenti sulla stessa porta: segnala l'eventuale conflitto.
$port=8765
$running=$false
try {$client=[System.Net.Sockets.TcpClient]::new();$client.Connect('127.0.0.1',$port);$running=$true;$client.Close()} catch {}
if (-not $running){
  Start-Process -FilePath $pyw -ArgumentList ('"'+(Join-Path $PSScriptRoot 'tray.py')+'"') -WorkingDirectory $PSScriptRoot
  Start-Sleep -Seconds 2
}
$config=Get-Content (Join-Path $PSScriptRoot 'config.json') -Raw | ConvertFrom-Json
$dashboard='http://127.0.0.1:8765/#access='+[string]$config.access_token
Start-Process $dashboard
Write-Host ''
Write-Host 'INSTALLAZIONE COMPLETATA. La dashboard si e aperta sul PC.' -ForegroundColor Green
Write-Host 'Telegram: nella sezione Telegram collega il token di @BotFather con un codice temporaneo.'
Write-Host 'Umbrel: usa il file CONFIGURA_UMBREL.ps1, dopo aver verificato la dashboard.'
Write-Host 'Il programma parte automaticamente dopo il login Windows.'
