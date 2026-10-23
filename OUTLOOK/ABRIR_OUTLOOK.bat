@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto preparar
.venv\Scripts\python.exe -c "import tkinter; import playwright.sync_api; import uiautomation"
if errorlevel 1 goto preparar
goto iniciar
:preparar
echo Preparando el entorno de Outlook. Espera a que termine...
call "%~dp0INSTALAR.bat" --auto
if errorlevel 1 goto error
:iniciar
.venv\Scripts\python.exe ejecutar.py
set "TASK_EXIT=%ERRORLEVEL%"
if not "%TASK_EXIT%"=="0" pause
exit /b %TASK_EXIT%
:error
echo No se pudo preparar Outlook. Revisa el error anterior.
pause
exit /b 1
