@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Prima esegui INSTALLA.ps1 & pause & exit /b 1)
".venv\Scripts\python.exe" main.py
pause
