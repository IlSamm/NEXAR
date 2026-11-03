# Compila NEXAR in dist\NEXAR\NEXAR.exe (senza pubblicare). Per una release usa release.ps1.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
py -m pip install -r requirements.txt 'pyinstaller>=6,<7'
if ($LASTEXITCODE -ne 0) { throw 'Installazione librerie fallita' }
Get-Process NEXAR -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$PSScriptRoot\dist\*" } | Stop-Process -Force
py -m PyInstaller --noconfirm NEXAR.spec
if ($LASTEXITCODE -ne 0) { throw 'Compilazione fallita' }
Write-Host 'App: dist\NEXAR\NEXAR.exe  (i tuoi dati restano in %LOCALAPPDATA%\NEXAR)' -ForegroundColor Green
