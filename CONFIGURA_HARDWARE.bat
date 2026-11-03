@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Prima installa PC ECO Control. & pause & exit /b 1)
".venv\Scripts\python.exe" CONFIGURA_HARDWARE.py
