@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto comprobar
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 goto error_python
:comprobar
".venv\Scripts\python.exe" -c "import tkinter" >nul 2>nul
if errorlevel 1 goto error_python
".venv\Scripts\python.exe" -c "import selenium" >nul 2>nul
if errorlevel 1 (
  echo Instalando el lector Outlook. La primera vez requiere Internet...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto error_lector
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 (
  echo No se pudo abrir el panel. Copia el error mostrado arriba.
  pause
)
exit /b
:error_python
echo Instala Python 3.11 o posterior con Tcl/Tk y la opcion Add Python to PATH.
echo Despues extrae el ZIP completo y vuelve a abrir ABRIR_BOT.bat.
pause
exit /b 1
:error_lector
echo No se pudo instalar Selenium. Revisa Internet y vuelve a abrir el archivo.
echo Para usar solo ADB y pegar el codigo manualmente, ejecuta: python app.py
pause
exit /b 1
