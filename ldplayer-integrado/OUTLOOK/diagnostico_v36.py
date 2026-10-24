# -*- coding: utf-8 -*-
"""Short redacted troubleshooting log for each authorized Outlook worker."""
from pathlib import Path
import os, re, threading
from datetime import datetime
BASE=Path(os.environ.get('LOCALAPPDATA') or str(Path.home()))/'GestoriaDiaz'/'DiagnosticosV36'
LOCK=threading.RLock()
def redact(raw):
    text=str(raw)
    text=re.sub(r'(?i)[\w.+-]+@[\w.-]+\.[a-z]{2,}', '[CORREO]',text)
    text=re.sub(r'(?i)https?://[^\s]+','[ENLACE]',text)
    text=re.sub(r'\b\d{5,}\b','[NUMERO]',text)
    text=re.sub(r'(?i)(password|contraseña|contrasena|token|secreto|code|codigo|código)[\s:=]+[^\s,;]+',r'\1=[OCULTO]',text)
    return ' '.join(text.split())[:210]
def path(slot):
    slot=int(slot)
    if slot not in (1,2,3,4):raise ValueError('Canal incorrecto')
    return BASE / ('outlook_%s.log' % slot)
def record(slot,event):
    with LOCK:
        BASE.mkdir(parents=True,exist_ok=True)
        target=path(slot)
        if target.exists() and target.stat().st_size>180000:
            # Rotate just one sanitized text log (no raw browser captures).
            target.replace(target.with_suffix('.prev.log'))
        with target.open('a',encoding='utf-8') as f:
            f.write(datetime.now().strftime('%Y-%m-%d %H:%M:%S')+' | '+redact(event)+'\n')
def tail(slot,lines=40):
    p=path(slot)
    if not p.exists():return ['Sin eventos registrados.']
    return p.read_text(encoding='utf-8',errors='replace').splitlines()[-lines:]
