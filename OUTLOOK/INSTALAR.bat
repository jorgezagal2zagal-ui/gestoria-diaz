@echo off
setlocal
if /i "%~1"=="--auto" set "TASK_NONINTERACTIVE=1"
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (set "TASK_PY=python") else (set "TASK_PY=py -3")
%TASK_PY% -c "import struct, sys; sys.exit(0 if sys.version_info >= (3,12) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 goto error
if not exist ".venv\Scripts\python.exe" %TASK_PY% -m venv .venv
if errorlevel 1 goto error
.venv\Scripts\python.exe -m pip install -r requirements.txt -c constraints-tested.txt
if errorlevel 1 goto error
.venv\Scripts\python.exe preparar.py
if errorlevel 1 goto error
.venv\Scripts\python.exe -c "import tkinter"
if errorlevel 1 goto error
.venv\Scripts\python.exe validar.py
if errorlevel 1 goto error
echo Preparacion local terminada. Falta verificar la integracion real con tus dispositivos y cuentas.
if not defined TASK_NONINTERACTIVE pause
exit /b 0
:error
echo No se completo la preparacion. Revisa Python 3.12+ de 64 bits, Tk e Internet.
if not defined TASK_NONINTERACTIVE pause
exit /b 1
