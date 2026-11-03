@echo off
powershell.exe -NoProfile -Command "$p=Join-Path ([Environment]::GetFolderPath('Startup')) 'PC ECO Control.lnk'; if(Test-Path $p){Remove-Item $p;Write-Host 'Collegamento esecuzione automatica rimosso.'}; Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'PC ECO Control','NEXAR' -ErrorAction SilentlyContinue; Write-Host 'Avvio automatico disattivato.'"
pause
