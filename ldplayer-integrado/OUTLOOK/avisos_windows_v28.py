# -*- coding: utf-8 -*-
"""Rechazo ACOTADO de ofertas nativas del video, solo Windows.

Solo clicks sobre textos inequívocos de creación de passkey, guardar
contraseña en navegador DEL BOT, o registrar Outlook como manejador de
correo. Nunca pulsa botones de autenticación, 'Continuar' ni 'Permitir'.
"""
from __future__ import annotations
import os
import re
import threading
import time
import unicodedata
from avisos_perfil import _process_snapshot, descendant_browser_pids, _nodes


def normalize(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(s or ''))
                   if not unicodedata.combining(c)).casefold()


def is_windows_passkey_creation(title, text, armed):
    """Only a Windows Security OFFER to save NEW passkey for Microsoft.

    Never act on a 'use existing passkey', 2FA challenge, or arbitrary app.
    """
    if not armed:
        return False
    title, text = normalize(title).strip(), normalize(text)
    trusted_window = ('seguridad de windows' in title or 'windows security' in title
                      or title in ('guardar la clave de paso', 'save a passkey'))
    creation_offer = any(phrase in text for phrase in (
        'guardar la clave de paso', 'guardar una clave de paso',
        'save a passkey', 'save your passkey', 'saving your passkey'))
    trusted_domain = 'login.microsoft.com' in text
    return trusted_window and creation_offer and trusted_domain


def requested_action(title, text, button, owned, passkey_armed):
    title,text,button=map(normalize,(title,text,button))
    button=button.strip()
    if is_windows_passkey_creation(title, text, passkey_armed):
        if button in ('cancelar','cancel','no','not now'):
            return 'clave de paso de Windows'
    if not owned:return None
    if (('quieres guardar la contrasena' in text or 'save password' in text)
            and button in ('nunca','never','no, gracias','no thanks')):
        return 'guardado de contraseña de Chrome'
    if (('outlook.live.com quiere' in text or 'outlook.live.com wants' in text)
            and ('abrir vinculos de correo electronico' in text or 'open email links' in text)
            and button in ('bloquear','block')):
        return 'permiso de abrir vínculos de correo'
    return None


class OptionalWindowsPromptsV28:
    def __init__(self,on_status):
        self.on_status=on_status
        self.stopped=threading.Event()
        self.passkey_until=0.0
        self.passkey_lock=threading.Lock()
        self.thread=None

    def arm_passkey(self,armed):
        # Keep the authorization window briefly after the URL navigates away:
        # the native OS popup may outlive /fido/create. Never arm on another URL.
        if armed:
            with self.passkey_lock:
                self.passkey_until=time.monotonic()+180

    def is_passkey_armed(self):
        with self.passkey_lock:
            return time.monotonic()<self.passkey_until

    def start(self):
        if os.name!='nt':return
        self.thread=threading.Thread(target=self._run,daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=1)

    def _run(self):
        try:
            import uiautomation as auto
            self.on_status('Detector nativo de ventanas Windows activo.')
            with auto.UIAutomationInitializerInThread():
                while not self.stopped.wait(.8):
                    owned=descendant_browser_pids(_process_snapshot(),os.getpid())
                    armed=self.is_passkey_armed()
                    if not owned and not armed:continue
                    for window in auto.GetRootControl().GetChildren():
                        if self.stopped.is_set():return
                        try:
                            title=window.Name
                            win_owned=window.ProcessId in owned
                            win_windows_security=(armed or bool(owned)) and (
                                'seguridad de windows' in normalize(title) or
                                'windows security' in normalize(title) or
                                normalize(title).strip() in ('guardar la clave de paso', 'save a passkey'))
                            if not win_owned and not win_windows_security:continue
                            controls=list(_nodes(window,limit=520,max_depth=12))
                            # Only while this bot owns a Chrome instance or an official creation
                            # window was recently seen. Exact creation text + login.microsoft.com required.
                            # Windows Security may be an OS process rather than a
                            # descendant Chrome PID. Its exact site and prompt
                            # wording still have to match before acting.
                            labels=' '.join(str(c.Name or '') for c in controls
                                            if c.ControlTypeName in ('TextControl','ButtonControl','HyperlinkControl','GroupControl','PaneControl'))
                            for c in controls:
                                if self.stopped.is_set():return
                                if c.ControlTypeName not in ('ButtonControl','SplitButtonControl','CustomControl') or not c.IsEnabled or c.IsOffscreen:continue
                                action=requested_action(title,labels,c.Name,win_owned,armed or bool(owned))
                                if not action:continue
                                try:
                                    c.GetInvokePattern().Invoke()
                                except Exception:
                                    # UI Automation's Invoke is missing on some
                                    # versions of Windows Security; click only
                                    # the verified named button, never coordinates.
                                    try: c.Click()
                                    except Exception:continue
                                self.on_status('Elegí «No»/«Cancelar» en la oferta opcional: '+action+'.')
                                # Avoid acting on stale accessibility nodes.
                                break
                        except Exception:continue
        except Exception:
            # Browser DOM handling is still available even when UIA is missing.
            self.on_status('Avisos de Windows no disponibles: instala las dependencias con INSTALAR.bat o cancela la oferta de clave de paso manualmente.')
