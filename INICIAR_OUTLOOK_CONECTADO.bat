@echo off
cd /d "%~dp0"
set SE_TIMEOUT=30
py -3 preparar_entorno.py
if errorlevel 1 (
 pause
 exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0outlook_conectado.py"
if errorlevel 1 pause
