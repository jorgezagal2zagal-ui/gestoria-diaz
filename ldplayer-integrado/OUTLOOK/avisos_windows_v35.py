# -*- coding: utf-8 -*-
"""Decline only an optional Microsoft *create/save* passkey prompt on Windows.

Use UI Automation for the native 'Seguridad de Windows' dialog, which Playwright
cannot inspect or click. Never decline an existing passkey sign-in challenge,
MFA, recovery, or unrelated Windows prompt. No coordinate-based clicks.
"""
from __future__ import annotations
import os
import threading
import time
import unicodedata
from avisos_perfil import _process_snapshot, descendant_browser_pids, _nodes

WINDOW_NAMES=('seguridad de windows','windows security','guardar la clave de paso','save a passkey',
              'guardar una clave de paso')
CRED_BROKERS={'credentialuibroker.exe','credentialui.exe'}
CREATE_TEXT=('guardar la clave de paso','guardar una clave de paso',
             'save a passkey','save your passkey','saving your passkey')
CANCEL_BUTTONS={'cancelar','cancel','no','ahora no','not now'}


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(s or ''))
                   if not unicodedata.combining(c)).casefold().strip()


def verified_creation(window_name,visible_text,host_process='',armed=False):
    """Require passkey CREATION wording + Microsoft login origin + OS dialog."""
    title=norm(window_name)
    body=norm(visible_text)
    host=norm(host_process)
    os_dialog=(any(phrase in title for phrase in WINDOW_NAMES)
               or (host in CRED_BROKERS and any(t in body for t in ('seguridad de windows','windows security'))))
    create=any(t in body for t in CREATE_TEXT)
    microsoft=any(t in body for t in ('login.microsoft.com','login.live.com'))
    # 'armed' is set only after Playwright sees Microsoft's official /fido/create
    # screen. It corroborates a native OS modal but DOES NOT replace the text
    # checks: don't press Cancel on a passkey sign-in challenge.
    return bool(os_dialog and create and microsoft)


def safe_cancel_name(name):
    return norm(name) in CANCEL_BUTTONS


def requested_action(title,body,button,host_process='',armed=False):
    if verified_creation(title,body,host_process,armed) and safe_cancel_name(button):
        return 'Guardar la clave de paso de Microsoft'
    return None


def describe_window(window,proc_name):
    """Collect all accessible names, including Custom and Window nodes.
    The older bot only collected Text and Pane names, missing the header and
    domain in many CredentialUIBroker builds.
    """
    nodes=list(_nodes(window,limit=850,max_depth=16))
    names=[]
    for node in nodes:
        try:
            value=str(node.Name or '')
            if value and len(value)<600:
                names.append(value)
        except Exception: pass
    return nodes,' '.join(names)[:20000]


def find_cancel_candidate(window,proc_name='',armed=False):
    try:
        nodes,body=describe_window(window,proc_name)
        title=str(window.Name or '')
        # Fallback for OS dialogs whose top-level Window.Name is blank: inner
        # 'Seguridad de Windows' title is surfaced as a TextControl.
        if not verified_creation(title,body,proc_name,armed):
            if (any(t in norm(body) for t in ('seguridad de windows','windows security'))
                and verified_creation('Seguridad de Windows',body,proc_name,armed)):
                pass
            else:return None
        # Prefer real semantic button, then a labelled CustomControl, then
        # labelled TextControl (Windows 11 exposes some buttons as Custom).
        for typ in ('ButtonControl','SplitButtonControl','CustomControl','TextControl'):
            for c in nodes:
                try:
                    if c.ControlTypeName != typ or not safe_cancel_name(c.Name):continue
                    if not c.IsEnabled or c.IsOffscreen:continue
                    return c
                except Exception:continue
    except Exception:return None
    return None


def activate_verified_cancel(control):
    try:
        control.GetInvokePattern().Invoke()
        return True
    except Exception:
        try:
            control.Click()
            return True
        except Exception:return False


class OptionalWindowsPromptsV35:
    def __init__(self,on_status):
        self.on_status=on_status
        self.stopped=threading.Event()
        self.thread=None
        self.passkey_until=0
        self.lock=threading.Lock()
        self._last_diag=0

    def arm_passkey(self,armed):
        if armed:
            with self.lock:
                self.passkey_until=time.monotonic()+180

    def is_passkey_armed(self):
        with self.lock:return time.monotonic()<self.passkey_until

    def disarm_passkey(self):
        with self.lock:self.passkey_until=0

    def start(self):
        if os.name!='nt':return
        self.thread=threading.Thread(target=self._run,name='GD-WindowsPasskeyCancel',daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=1)

    def _run(self):
        try:
            import uiautomation as auto
        except ImportError:
            self.on_status('AVISO: falta uiautomation. Ejecuta INSTALAR_CONTROL_WINDOWS_V35.bat para cancelar la clave de paso.')
            return
        except Exception as exc:
            self.on_status('No se pudo iniciar control de Windows: '+type(exc).__name__+'. Ejecuta el instalador V35.')
            return
        self.on_status('Control V35 de la clave de paso Windows ACTIVO; esperaré oferta Microsoft para pulsar Cancelar.')
        try:
            with auto.UIAutomationInitializerInThread():
                while not self.stopped.wait(0.35):
                    try:
                        rows=_process_snapshot()
                        process_names={int(pid):str(name).casefold() for pid,_,name in rows}
                        owned=descendant_browser_pids(rows,os.getpid())
                        armed=self.is_passkey_armed()
                        if not owned and not armed:continue
                        for window in auto.GetRootControl().GetChildren():
                            if self.stopped.is_set():return
                            try:
                                title=norm(window.Name)
                                pid=window.ProcessId
                                process_name=process_names.get(pid,'')
                                eligible=(pid in owned or process_name in CRED_BROKERS
                                          or any(s in title for s in WINDOW_NAMES))
                                if not eligible:continue
                                button=find_cancel_candidate(window,process_name,armed)
                                if button is None:continue
                                if activate_verified_cancel(button):
                                    self.on_status('CLAVE DE PASO: pulsé «Cancelar» en Seguridad de Windows. Continúo con Outlook.')
                                    break
                            except Exception:continue
                    except Exception as exc:
                        now=time.monotonic()
                        if now-self._last_diag>20:
                            self.on_status('Control de avisos Windows: reintentando acceso UIA ('+type(exc).__name__+').')
                            self._last_diag=now
        except Exception as exc:
            self.on_status('La automatización de Seguridad de Windows no está disponible ('+type(exc).__name__+').')
