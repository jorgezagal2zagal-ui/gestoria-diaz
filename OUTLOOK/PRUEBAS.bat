@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
 set "TASK_PY=.venv\Scripts\python.exe"
) else (
 where py >nul 2>nul
 if errorlevel 1 (set "TASK_PY=python") else (set "TASK_PY=py -3")
)
%TASK_PY% validar.py
set "TASK_EXIT=%ERRORLEVEL%"
pause
exit /b %TASK_EXIT%
