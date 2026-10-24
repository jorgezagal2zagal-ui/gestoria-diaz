# -*- coding: utf-8 -*-
"""Outlook V38: abre correos IMSS en bandeja compacta; conserva V37."""
import os,sys,subprocess
from pathlib import Path
if '--worker' in sys.argv:
    _index=sys.argv.index('--worker')
    os.environ['GD_WORKER_SLOT']=sys.argv[_index+1]
else:
    os.environ['GD_WORKER_SLOT']='1'
os.environ['GD_HEADLESS']='0'

from app_v37 import OutlookV37, OutlookWorkerV36
import navegador_v28 as browser
from lector_reciente_v38 import compact_inbox_verified,scan_visible_inbox

browser.inbox_ui_verified=compact_inbox_verified
browser.scan_visible_inbox=scan_visible_inbox


class OutlookV38(OutlookV37):
    def start_worker(self,n):
        if n not in (2,3,4):return
        old=self.children.get(n)
        if old and old.poll() is None:return
        env=os.environ.copy()
        env.update(GD_WORKER_SLOT=str(n),GD_HEADLESS='0',GD_BG_WORKER='1')
        self.children[n]=subprocess.Popen(
            [sys.executable,str(Path(__file__).resolve()),'--worker',str(n)],
            env=env,cwd=str(Path(__file__).resolve().parent),close_fds=True)

    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V38 · ABRIR CORREO IMSS CORREGIDO')
        self._diag('V38: detección de bandeja compacta y apertura de correo habilitadas')


def main():
    if '--worker' in sys.argv:
        slot=int(sys.argv[sys.argv.index('--worker')+1])
        if slot not in (2,3,4):raise ValueError('Canal Outlook inválido')
        app=OutlookWorkerV36()
        app.withdraw()
    else:
        app=OutlookV38()
    app.mainloop()

if __name__=='__main__':main()
