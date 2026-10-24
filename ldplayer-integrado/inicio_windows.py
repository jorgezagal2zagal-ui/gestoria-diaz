"""Respaldar SQLite antes de iniciar; impedir dos paneles de la misma integración."""
import ctypes
from datetime import datetime
import os
from pathlib import Path
import runpy
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent


def respaldar_datos():
    base = Path(os.environ['LOCALAPPDATA'])/'GestoriaDiaz'
    source = base/'CompartidoV14'
    if not source.is_dir():return
    target = base/'RespaldosIntegracion'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    databases = list(source.glob('*.sqlite3'))
    if not databases:return
    target.mkdir(parents=True, exist_ok=False)
    for path in databases:
        with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as original:
            with sqlite3.connect(target/path.name) as backup:original.backup(backup)


def main():
    component = sys.argv[1] if len(sys.argv) == 2 else ''
    if component not in ('IMSS', 'OUTLOOK'):raise ValueError('Componente inválido')
    if sys.platform != 'win32':raise RuntimeError('Se requiere Windows')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.CreateMutexW(None, False, 'Local\\GestoriaDiaz_LDPlayer_Integrado_'+component)
    if not handle:raise RuntimeError('No se pudo reservar el panel')
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        from arranque import aviso
        aviso('Este panel de la integración ya está abierto. Usa su ventana existente.')
        return
    try:
        respaldar_datos()
        folder = ROOT/component
        sys.path.insert(0, str(folder))
        os.chdir(folder)
        script = 'gestoria_imss_integrado.py' if component == 'IMSS' else 'outlook_integrado.py'
        runpy.run_path(str(folder/script), run_name='__main__')
    finally:kernel.CloseHandle(handle)


if __name__ == '__main__':
    try:main()
    except Exception as exc:
        from arranque import aviso
        aviso('No se pudo abrir el panel ('+type(exc).__name__+'). Revisa INSTALAR_WINDOWS.bat y las instrucciones. No se registraron datos de cuentas ni códigos.')
