@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
 echo Primero ejecuta INSTALAR_WINDOWS.bat.
 pause
 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "GESTORIA_DIAZ.pyw"
exit /b 0
