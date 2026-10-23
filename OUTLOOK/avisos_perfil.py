"""Rechaza ofertas de perfil/sincronización en ventanas del navegador de ESTE bot.

No escribe credenciales, no cierra ventanas y no acepta/cancela verificaciones.
La UI nativa solo se automatiza en Windows mediante UI Automation.
"""
import ctypes
from ctypes import wintypes
from collections import deque
import os
import re
import threading
import unicodedata


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text or '')
                   if not unicodedata.combining(c)).casefold()


TITLE=re.compile(r'^(?:asistencia (?:de )?microsoft edge|microsoft edge assistance|'
                 r'(?:inicia(?:r)? sesion en|sign in to) (?:microsoft edge|google chrome|chrome)|'
                 r'activar (?:la )?sincronizacion|turn on sync)\s*[?¿!¡.]*$')
OFFER=re.compile(r'inicia(?:r)? sesion en microsoft edge|sign in to microsoft edge|'
                 r'inicia(?:r)? sesion en (?:google )?chrome|sign in to (?:google )?chrome|'
                 r'sincronizar datos|turn on sync|sync your (?:data|profile)')
DECLINE=re.compile(r'^(?:no[,\s]+gracias|no[,\s]+thanks|ahora no|not now|cancelar|cancel)$')


def is_profile_offer(title,text,button):
    return bool(TITLE.fullmatch(normalize(title).strip()) and
                OFFER.search(normalize(text)) and DECLINE.fullmatch(normalize(button).strip()))


def descendant_browser_pids(rows,parent_pid):
    parents={pid:parent for pid,parent,name in rows}
    result=set()
    for pid,parent,name in rows:
        if name.casefold() not in ('chrome.exe','msedge.exe','chromium.exe'):continue
        seen=set();current=pid
        while current in parents and current not in seen:
            seen.add(current);current=parents[current]
            if current==parent_pid:
                result.add(pid);break
    return result


def _process_snapshot():
    class ProcessEntry(ctypes.Structure):
        _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),
            ('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),
            ('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
            ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),
            ('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    for name in ('Process32FirstW','Process32NextW'):
        fn=getattr(kernel,name);fn.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessEntry)];fn.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.CreateToolhelp32Snapshot(2,0)
    if handle==ctypes.c_void_p(-1).value:return []
    rows=[]
    try:
        entry=ProcessEntry();entry.dwSize=ctypes.sizeof(entry)
        valid=kernel.Process32FirstW(handle,ctypes.byref(entry))
        while valid:
            rows.append((entry.th32ProcessID,entry.th32ParentProcessID,entry.szExeFile))
            valid=kernel.Process32NextW(handle,ctypes.byref(entry))
    finally:kernel.CloseHandle(handle)
    return rows


def _nodes(root,limit=240,max_depth=9):
    pending=deque([(root,0)]);visited=0
    while pending and visited<limit:
        node,depth=pending.popleft();visited+=1
        yield node
        if depth>=max_depth:continue
        try:pending.extend((child,depth+1) for child in node.GetChildren())
        except Exception:continue


def decline_profile_dialog(dialog,owned_pids,stop_event=None):
    """Un diálogo nativo identificado por título exacto, PID propio y oferta de perfil."""
    try:
        title=dialog.Name
        if dialog.ControlTypeName not in ('WindowControl','PaneControl','CustomControl'):return False
        if dialog.ProcessId not in owned_pids or not TITLE.fullmatch(normalize(title).strip()):return False
        if dialog.IsOffscreen:return False
        nodes=list(_nodes(dialog))
        text=' '.join(node.Name for node in nodes if node.ControlTypeName in ('TextControl','ButtonControl'))
        for node in nodes:
            if (node.ControlTypeName=='ButtonControl' and node.IsEnabled and not node.IsOffscreen
                    and is_profile_offer(title,text,node.Name)):
                if stop_event is not None and stop_event.is_set():return False
                node.GetInvokePattern().Invoke()
                return True
    except Exception:return False
    return False


class ProfilePromptGuard:
    def __init__(self,callback):
        self.callback=callback;self.stopped=threading.Event();self.thread=None

    def start(self):
        if os.name!='nt':return
        self.thread=threading.Thread(target=self._run,daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread is not None:self.thread.join(timeout=1)

    def _run(self):
        try:
            import uiautomation as auto
            with auto.UIAutomationInitializerInThread():
                while not self.stopped.wait(1):
                    owned=descendant_browser_pids(_process_snapshot(),os.getpid())
                    if not owned:continue
                    for window in auto.GetRootControl().GetChildren():
                        if self.stopped.is_set():return
                        try:
                            if window.ProcessId not in owned:continue
                            # Los avisos nativos pueden ser ventanas superiores o hijas.
                            for dialog in _nodes(window,limit=160,max_depth=6):
                                if decline_profile_dialog(dialog,owned,self.stopped):
                                    self.callback('Elegí «No, gracias»/«Cancelar» en el aviso de perfil del navegador. Continúo con Outlook.')
                                    break
                        except Exception:continue
        except Exception:
            self.callback('No se pudo activar el rechazo de avisos de perfil. Si aparece ese aviso, pulsa No, gracias; la sesión permanece abierta.')
