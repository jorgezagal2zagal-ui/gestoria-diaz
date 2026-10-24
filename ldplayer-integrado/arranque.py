"""Lanzadores Windows con entorno propio y errores sin datos sensibles."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def aviso(text):
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk();root.withdraw()
    messagebox.showinfo('Gestoría Díaz', text, parent=root)
    root.destroy()


def abrir(componentes):
    if sys.platform != 'win32':
        raise SystemExit('Estas ventanas requieren Windows. Para pruebas: python ejecutar_pruebas.py')
    python = ROOT/'.venv'/'Scripts'/'pythonw.exe'
    if not python.is_file():
        aviso('Primero ejecuta INSTALAR_WINDOWS.bat. Necesitas Python 3.12 de 64 bits con Tk.')
        return
    for component in componentes:
        subprocess.Popen([str(python), str(ROOT/'inicio_windows.py'), component],
                         cwd=str(ROOT), close_fds=True)
