# Pubblica una nuova versione di NEXAR: test, exe, zip + hash, tag e release GitHub.
# Le app installate la scaricano da sole (entro 6 ore, o subito con "Controlla ora" / /aggiorna su Telegram).
#   .\release.ps1 1.0.1 "Cosa cambia in questa versione"
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Notes = ''
)
# 'Continue': PyInstaller, git e gh scrivono messaggi normali su stderr, che PowerShell 5.1 tratterebbe come errori.
# Ogni passo controlla il proprio codice di uscita.
$ErrorActionPreference = 'Continue'
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
py -m PyInstaller --noconfirm --log-level WARN NEXAR.spec
if ($LASTEXITCODE -ne 0) { throw 'Compilazione fallita' }

# Windows Defender deve dare il via libera: un falso positivo cancellerebbe NEXAR a chi la scarica.
$mp = "$env:ProgramFiles\Windows Defender\MpCmdRun.exe"
function Assert-Clean($path) {
    if (-not (Test-Path $mp)) { Write-Host 'Defender non disponibile: scansione saltata' -ForegroundColor Yellow; return }
    $out = & $mp -Scan -ScanType 3 -File (Resolve-Path $path) -DisableRemediation 2>&1 | Out-String
    if ($out -notmatch 'found no threats') { throw "Defender segnala $path come minaccia: release annullata`n$out" }
}
Assert-Clean dist\NEXAR

New-Item -ItemType Directory -Force release | Out-Null
$name = "NEXAR-$Version-win64.zip"
$zip = Join-Path release $name
Compress-Archive -Path dist\NEXAR -DestinationPath $zip -Force -ErrorAction Stop
Assert-Clean $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$PSScriptRoot\$zip.sha256", "$hash  $name`n")

if (-not $Notes) { $Notes = "NEXAR $Version" }
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { git commit -q -m "NEXAR $Version" }
git tag "v$Version"
git push -q origin HEAD --tags
if ($LASTEXITCODE -ne 0) { throw 'Push su GitHub fallito' }
gh release create "v$Version" $zip "$zip.sha256" --title "NEXAR $Version" --notes $Notes
if ($LASTEXITCODE -ne 0) { throw 'Creazione release fallita' }
Write-Host "Pubblicata NEXAR $Version" -ForegroundColor Green
