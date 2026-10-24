@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Primero ejecuta INSTALAR_WINDOWS.bat.
 pause
 exit /b 1
)
.venv\Scripts\python.exe ejecutar_pruebas.py
set "GD_RESULT=%ERRORLEVEL%"
pause
exit /b %GD_RESULT%
