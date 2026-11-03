@echo off
rem Compila NEXAR (dist\NEXAR\NEXAR.exe). I dati restano in %LOCALAPPDATA%\NEXAR.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0CREA_EXE.ps1"
pause
