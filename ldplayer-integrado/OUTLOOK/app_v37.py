# -*- coding: utf-8 -*-
"""Outlook V37: visible Chrome + diagnostics; non-blocking close.

Cierre asíncrono: el botón X no espera en hilo Tk por servidores o workers.
"""
import os,sys,tkinter as tk,threading
from tkinter import messagebox
from app_v36 import OutlookV36, OutlookWorkerV36

class OutlookV37(OutlookV36):
    def start_worker(self,n):
        if n not in (2,3,4):return
        old=self.children.get(n)
        if old and old.poll() is None:return
        import subprocess
        from pathlib import Path
        env=os.environ.copy()
        env.update(GD_WORKER_SLOT=str(n),GD_HEADLESS='0',GD_BG_WORKER='1')
        self.children[n]=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',str(n)],
             env=env,cwd=str(Path(__file__).resolve().parent),close_fds=True)

    def __init__(self):
        self._closing_v37=False
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V37 · 4 CHROME VISIBLES · CIERRE CORREGIDO')
        self.protocol('WM_DELETE_WINDOW',self.close)
        self._diag('V37: cierre no bloqueante habilitado')

    def close(self):
        if self._closing_v37:return
        try:
            state=self.state.status().get('status','SIN_SOLICITUD')
        except Exception:state='SIN_SOLICITUD'
        # Avoid synchronous network I/O on the Tk event loop.
        try:
            active=state in ('ESPERANDO_CODIGO','CODIGO_DISPONIBLE','CODIGO_ENVIADO_AL_CELULAR')
            active=active or any('ESPERANDO CODIGO' in v.get().upper() or 'CÓDIGO' in v.get().upper()
                                 for v in self.worker_labels.values())
        except Exception:active=True
        if active and not messagebox.askyesno('Trámites abiertos',
              'Hay códigos o sesiones pendientes. ¿Cerrar las cuatro sesiones de Outlook? '
              'Los trámites sin terminar requerirán revisión.',parent=self):
            return
        self._closing_v37=True
        self._closed=True
        try:self.browser.stop()  # Signals browser thread without waiting for Chrome.
        except Exception:pass
        children=list(getattr(self,'children',{}).values())
        server=getattr(self,'server',None)
        def finish():
            for proc in children:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        try:proc.wait(timeout=4)
                        except Exception:proc.kill()
                except Exception:pass
            if server is not None:
                try:server.close()
                except Exception:pass
        threading.Thread(target=finish,name='outlook-v37-clean-exit',daemon=True).start()
        # UI exits immediately; background browser workers clean up independently.
        try:tk.Tk.destroy(self)
        except Exception:pass

def main():
    os.environ['GD_HEADLESS']='0'
    if '--worker' in sys.argv:
        i=sys.argv.index('--worker')
        slot=int(sys.argv[i+1])
        if slot not in (2,3,4):raise ValueError('Canal de Outlook inválido')
        os.environ['GD_WORKER_SLOT']=str(slot)
        app=OutlookWorkerV36()
        app.withdraw()
    else:
        app=OutlookV37()
    app.mainloop()
if __name__=='__main__':main()
