@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  set "GD_PY=python"
) else (
  py -3.12 -c "import sys" >nul 2>nul
  if errorlevel 1 (set "GD_PY=py -3") else (set "GD_PY=py -3.12")
)
%GD_PY% -c "import sys,tkinter; assert sys.version_info >= (3,10); assert sys.maxsize > 2**32"
if errorlevel 1 goto error
if not exist ".venv\Scripts\python.exe" %GD_PY% -m venv .venv
if errorlevel 1 goto error
.venv\Scripts\python.exe -m pip install -r OUTLOOK\requirements.txt -c OUTLOOK\constraints-tested.txt
if errorlevel 1 goto error
.venv\Scripts\python.exe OUTLOOK\preparar.py
if errorlevel 1 goto error
.venv\Scripts\python.exe ejecutar_pruebas.py
if errorlevel 1 goto error
echo Instalacion y pruebas locales terminadas. Abre GESTORIA_DIAZ.pyw.
echo Aun debes validar las ventanas, la cuenta autorizada y LDPlayer reales.
pause
exit /b 0
:error
echo No termino la instalacion. Revisa Python 3.12 x64 con Tk, Internet y el error anterior.
pause
exit /b 1
