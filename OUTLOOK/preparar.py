"""Preparación del navegador antes de abrir el panel Windows."""
import os
from pathlib import Path
import subprocess
import sys


def installed_windows_browser():
    if sys.platform!='win32':return False
    for variable in ('ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA'):
        base=os.environ.get(variable)
        if not base:continue
        for relative in ('Microsoft/Edge/Application/msedge.exe',
                         'Google/Chrome/Application/chrome.exe'):
            if (Path(base)/relative).is_file():return True
    return False


def ensure_browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('Falta Playwright. Ejecuta INSTALAR.bat para preparar el programa.')
        return 1
    native_available=installed_windows_browser()
    with sync_playwright() as playwright:
        if Path(playwright.chromium.executable_path).is_file():return 0
    print('Preparando Chromium para el acceso automático. Espera a que termine la descarga…')
    result=subprocess.run([sys.executable,'-m','playwright','install','chromium'])
    if result.returncode and native_available:
        print('Chromium no se pudo preparar. Se utilizará Edge o Chrome instalado.')
        return 0
    if result.returncode:
        print('No se pudo instalar Chromium. Revisa Internet y ejecuta INSTALAR.bat.')
    return result.returncode


if __name__=='__main__':
    raise SystemExit(ensure_browser())
