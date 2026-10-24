# -*- coding: utf-8 -*-
"""Diagnóstico de procesos de navegador; no inicia sesión ni toca credenciales."""
from __future__ import annotations
import os,re

def clean(value):
    text=str(value or '')
    text=re.sub(r'[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}', '[CORREO]',text,flags=re.I)
    text=re.sub(r'(?i)(contrase(?:ñ|n)a|password|codigo|token)\s*[:=]\s*\S+',r'\1=[OCULTO]',text)
    return text[:240]

def window_state():
    """No captura títulos, URLs, nombres de cuenta ni texto de ventanas."""
    if os.name!='nt':return {'supported':False,'processes':None,'visible':None}
    try:
        import ctypes
        from ctypes import wintypes
        from avisos_perfil import _process_snapshot,descendant_browser_pids
        pids=descendant_browser_pids(_process_snapshot(),os.getpid())
        user32=ctypes.windll.user32
        callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        visible=set()
        def check(hwnd,param):
            if user32.IsWindowVisible(hwnd):
                pid=wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                if pid.value in pids:visible.add(pid.value)
            return True
        callback=callback_type(check)
        user32.EnumWindows(callback,0)
        return {'supported':True,'processes':len(pids),'visible':len(visible)}
    except Exception:
        return {'supported':False,'processes':None,'visible':None}

def classify(browser,age,win):
    if bool(getattr(browser,'rate_limited',False)):
        return 'MICROSOFT LIMITÓ ACCESOS · No abrir otras cuentas.'
    running=bool(getattr(browser,'running',False))
    confirmed=bool(browser.browser_opened.is_set())
    phase=str(getattr(browser,'phase','idle'))
    if not running:
        if phase=='error':return 'ERROR AL ABRIR CHROME · Ver Diagnóstico y copiar resultado.'
        return 'SIN NAVEGADOR ACTIVO · Esperando solicitud IMSS.'
    if not confirmed:
        if age is not None and age>20:
            return 'SIN CONFIRMAR: Playwright no creó la pestaña tras 20 s.'
        return 'PREPARANDO CHROME · Todavía no se confirma ninguna pestaña.'
    if win['supported'] and win['visible']==0 and age is not None and age>12:
        return 'AVISO: Playwright creó pestaña, pero Windows aún no detecta Chrome visible.'
    if win['supported'] and win['visible']:
        return 'NAVEGADOR VISIBLE · Fase actual: '+phase.upper()
    return 'PESTAÑA CREADA · Fase actual: '+phase.upper()
