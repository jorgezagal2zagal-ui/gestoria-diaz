@echo off
cd /d "%~dp0"
py -3 preparar_entorno.py
if errorlevel 1 (
 pause
 exit /b 1
)
set SE_TIMEOUT=30
start "Outlook conectado V2" "%~dp0.venv\Scripts\python.exe" "%~dp0outlook_conectado.py"
start "Instancias IMSS V2" "%~dp0.venv\Scripts\python.exe" "%~dp0gestoria_5_instancias.py"
