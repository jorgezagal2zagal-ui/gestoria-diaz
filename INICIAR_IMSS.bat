@echo off
cd /d "%~dp0"
py -3 gestoria_5_instancias.py
if errorlevel 1 pause
