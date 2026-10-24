# -*- coding: utf-8 -*-
"""PIN del dispositivo: DPAPI de Windows, ligado al usuario local. Nunca en texto claro."""
from pathlib import Path
import os,re
from credenciales import WindowsDPAPI
FILE=Path(os.environ.get('LOCALAPPDATA') or str(Path.home()))/'GestoriaDiaz'/'PIN_IMSS'/'pin.dpapi'
def save_pin(pin):
    if not re.fullmatch(r'\d{4,8}',pin or ''):raise ValueError('El PIN debe tener de 4 a 8 dígitos')
    raw=WindowsDPAPI().protect(pin)
    FILE.parent.mkdir(parents=True,exist_ok=True)
    tmp=FILE.with_suffix('.tmp');tmp.write_bytes(raw);tmp.replace(FILE)
def read_pin():
    if not FILE.exists():return ''
    val=WindowsDPAPI().unprotect(FILE.read_bytes())
    if not re.fullmatch(r'\d{4,8}',val):raise ValueError('PIN cifrado inválido')
    return val
def delete_pin():
    FILE.unlink(missing_ok=True)
