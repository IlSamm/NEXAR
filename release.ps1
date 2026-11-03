# Pubblica una nuova versione di NEXAR: test, exe, zip + hash, tag e release GitHub.
# Le app installate la scaricano da sole (entro 6 ore, o subito con "Controlla ora" / /aggiorna su Telegram).
#   .\release.ps1 1.0.1 "Cosa cambia in questa versione"
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Notes = ''
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Versione nel formato 1.2.3' }
if (git tag --list "v$Version") { throw "La versione $Version esiste già" }

$py = Get-Content version.py -Raw
[IO.File]::WriteAllText("$PSScriptRoot\version.py", ($py -replace "VERSION = '[^']*'", "VERSION = '$Version'"))

py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Test falliti: release annullata' }
py make_icon.py | Out-Null

# L'exe in dist\NEXAR blocca i file: chiudilo (i dati sono in %LOCALAPPDATA%\NEXAR e non vengono toccati).
Get-Process NEXAR -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$PSScriptRoot\dist\*" } | Stop-Process -Force
py -m PyInstaller --noconfirm NEXAR.spec
if ($LASTEXITCODE -ne 0) { throw 'Compilazione fallita' }

New-Item -ItemType Directory -Force release | Out-Null
$name = "NEXAR-$Version-win64.zip"
$zip = Join-Path release $name
Compress-Archive -Path dist\NEXAR -DestinationPath $zip -Force
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$PSScriptRoot\$zip.sha256", "$hash  $name`n")

if (-not $Notes) { $Notes = "NEXAR $Version" }
git add -A
git commit -m "NEXAR $Version"
git tag "v$Version"
git push origin HEAD --tags
gh release create "v$Version" $zip "$zip.sha256" --title "NEXAR $Version" --notes $Notes
Write-Host "Pubblicata NEXAR $Version" -ForegroundColor Green
