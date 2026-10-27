@echo off
cd /d "%~dp0"
py -3 preparar_entorno.py
if errorlevel 1 (
 pause
 exit /b 1
)
set SE_TIMEOUT=30
"%~dp0.venv\Scripts\python.exe" "%~dp0panel_unificado.py"
if errorlevel 1 pause
