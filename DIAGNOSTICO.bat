@echo off
cd /d "%~dp0"
py -3 preparar_entorno.py
if errorlevel 1 (
 pause
 exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0diagnostico_conexion.py"
pause
