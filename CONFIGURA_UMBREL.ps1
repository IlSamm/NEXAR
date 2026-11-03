# Configura accesso proxy di Umbrel; richiede UAC e IP LAN di Umbrel.
$ErrorActionPreference='Stop'
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Start-Process powershell.exe -Verb RunAs -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"')
  exit
}
Set-Location $PSScriptRoot
Write-Host 'PC ECO Control - Accesso iPhone via Umbrel' -ForegroundColor Cyan
$defaultUmbrel=''
try {
  $records=Resolve-DnsName 'umbrel.local' -Type A -ErrorAction Stop | Where-Object {$_.IPAddress -match '^\d+\.\d+\.\d+\.\d+$'}
  if($records){$defaultUmbrel=$records[0].IPAddress}
} catch {}
$line=Read-Host ('Indirizzo IP LAN di Umbrel' + $(if($defaultUmbrel){" [$defaultUmbrel]"}else{''}))
$umbrel=if($line){$line}else{$defaultUmbrel}
$ipObject=$null
if(-not [System.Net.IPAddress]::TryParse($umbrel,[ref]$ipObject) -or $ipObject.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork){throw 'IP Umbrel non valido.'}
# Identifica l'IPv4 del PC sull'interfaccia con gateway di default.
$pc=''
try {
 $route=Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1
 $ip=Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex | Where-Object {$_.IPAddress -notlike '169.254.*'} | Select-Object -First 1
 $pc=$ip.IPAddress
} catch {}
if(-not $pc){$pc=Read-Host 'Inserisci IPv4 LAN del PC (ipconfig)'}
$pcIpObject=$null
if(-not [System.Net.IPAddress]::TryParse($pc,[ref]$pcIpObject) -or $pcIpObject.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork){throw 'IP del PC non valido.'}
$configPath=Join-Path $PSScriptRoot 'config.json'
if(-not(Test-Path $configPath)){throw 'Esegui prima INSTALLA_E_AVVIA.cmd'}
$config=Get-Content $configPath -Raw | ConvertFrom-Json
$config.web.host='0.0.0.0'
$config | ConvertTo-Json -Depth 25 | Set-Content -Path $configPath -Encoding UTF8
# Questo file non contiene token: solo gli indirizzi LAN.
$compose=@"
services:
  pc-eco-dashboard:
    image: caddy:2-alpine
    container_name: pc-eco-dashboard
    command: ["reverse-proxy", "--from", ":80", "--to", "${pc}:8765"]
    ports:
      - "8787:80"
    restart: unless-stopped
"@
$composePath=Join-Path $PSScriptRoot 'umbrel\docker-compose-pronto.yml'
$compose | Set-Content -Path $composePath -Encoding UTF8
Get-NetFirewallRule -DisplayName 'PC ECO - solo Umbrel' -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName 'PC ECO - solo Umbrel' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress $umbrel -Profile Private | Out-Null
try {$compose | Set-Clipboard} catch {}
Write-Host ''
Write-Host 'CONFIGURAZIONE WINDOWS COMPLETATA.' -ForegroundColor Green
Write-Host "PC LAN: $pc | Umbrel: $umbrel"
Write-Host "Stack Docker generato: $composePath"
Write-Host 'Apri Portainer su Umbrel -> Stacks -> Add stack -> incolla il compose che ho copiato negli appunti -> Deploy.'
Write-Host 'Riavvia l app PC ECO Control (icona tray -> Esci -> AVVIA.bat).'
Write-Host 'Poi apri su iPhone http://umbrel.local:8787 connesso al Wi-Fi domestico.'
Write-Host 'Per accesso fuori casa usa Tailscale, NON aprire porte del router.'
Write-Host 'Non espone direttamente a Internet la porta 8765; controlla altre regole firewall preesistenti.'
Pause
