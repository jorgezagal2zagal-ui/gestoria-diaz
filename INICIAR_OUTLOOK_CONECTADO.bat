@echo off
cd /d "%~dp0"
set SE_TIMEOUT=30
py -3 -m pip install -r outlook_bot\requirements.txt
if errorlevel 1 (
 pause
 exit /b 1
)
py -3 outlook_conectado.py
if errorlevel 1 pause
