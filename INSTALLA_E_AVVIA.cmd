@echo off
setlocal
cd /d "%~dp0"
title PC ECO Control - installazione automatica
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLA_E_AVVIA.ps1"
if errorlevel 1 (
 echo.
 echo Installazione non completata. Controlla il messaggio qui sopra.
 pause
 exit /b 1
)
endlocal
