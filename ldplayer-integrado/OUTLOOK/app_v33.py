# -*- coding: utf-8 -*-
"""One visible dashboard, 4 separate browser sessions running in the background.
The localhost OTP bridges and reservation logic are unchanged from V32.
"""
import os,sys,time,subprocess,tkinter as tk
from pathlib import Path
from tkinter import messagebox
# Set the channel BEFORE importing enlace.py, which binds its own localhost port.
if '--worker' in sys.argv:
    _i=sys.argv.index('--worker')
    os.environ['GD_WORKER_SLOT']=sys.argv[_i+1]
else:
    os.environ['GD_WORKER_SLOT']='1'
os.environ['GD_HEADLESS']='1'
from app_v32 import OutlookV32
from preparacion_v32 import PreparationV32
from enlace import Client
from app import BG,BOX,GOLD,WHITE,GRAY

class OutlookV33(OutlookV32):
    def __init__(self):
        self.children={}
        self.owned=True
        os.environ['GD_WORKER_SLOT']='1'
        os.environ['GD_HEADLESS']='1'
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V33 · PANEL ÚNICO · 4 SESIONES EN SEGUNDO PLANO')
        self.geometry('940x820')
        main=self.winfo_children()[0]
        controls=tk.Frame(main,bg=BG)
        controls.pack(fill='x',pady=6)
        tk.Label(controls,text='CUATRO BUZONES EN PARALELO · 1 SOLO PANEL',bg=BG,fg=GOLD,
                 font=('Segoe UI',11,'bold')).pack(anchor='w')
        tk.Label(controls,text='4 procesos aislados, 4 perfiles de correo, 4 códigos independientes. Chrome no aparece salvo que elijas modo visible para resolver un acceso.',
                 bg=BG,fg=GRAY,wraplength=850,justify='left').pack(anchor='w',pady=3)
        self.worker_labels={}
        for n in range(1,5):
            var=tk.StringVar(value='Iniciando...')
            line=tk.Frame(controls,bg=BOX,padx=8,pady=5);line.pack(fill='x',pady=2)
            tk.Label(line,text=f'BUZÓN {n}  ·  ANDROID {n}',bg=BOX,fg=GOLD,width=25,anchor='w',font=('Segoe UI',9,'bold')).pack(side='left')
            tk.Label(line,textvariable=var,bg=BOX,fg=WHITE,anchor='w').pack(side='left',fill='x',expand=True)
            self.worker_labels[n]=var
        self.button(controls,'ACTUALIZAR ESTADOS',self.refresh_workers).pack(fill='x',pady=4)
        for n in (2,3,4): self.start_worker(n)
        self.after(1300,self.refresh_workers)

    def start_worker(self,n):
        if n not in (2,3,4):return
        old=self.children.get(n)
        if old and old.poll() is None:return
        env=os.environ.copy()
        env.update(GD_WORKER_SLOT=str(n),GD_HEADLESS='1',GD_BG_WORKER='1')
        # The extracted source directory is stable across launcher and child Python.
        p=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',str(n)],
                           env=env,cwd=str(Path(__file__).resolve().parent),close_fds=True)
        self.children[n]=p

    def refresh_workers(self):
        if self._closed:return
        for n in range(1,5):
            try:
                child=self.children.get(n)
                if n>1 and (child is None or child.poll() is not None):
                    self.worker_labels[n].set('Proceso detenido · revisa acceso y reinicia el panel')
                    continue
                prep=PreparationV32(n)
                heartbeat=prep.live(n,max_age=12)
                client=Client(port=8796+n,timeout=0.35)
                result=client.ping()
                status=client.call('/v1/estado').get('status','SIN_SOLICITUD')
                self.worker_labels[n].set(('ACTIVO' if heartbeat else 'INICIANDO')+
                    (' · DISPONIBLE' if result.get('available') else ' · OCUPADO')+
                    ' · '+status.replace('_',' '))
            except Exception:
                self.worker_labels[n].set('Iniciando conexión local…')
        self.after(2200,self.refresh_workers)

    def close(self):
        # Do not silently discard an active IMSS session.
        if self.children and not self._closed:
            try:
                active=[]
                for n in range(1,5):
                    try:
                        c=Client(port=8796+n,timeout=0.3)
                        if c.call('/v1/estado').get('status') in ('ESPERANDO_CODIGO','CODIGO_DISPONIBLE','CODIGO_ENVIADO_AL_CELULAR'):
                            active.append(str(n))
                    except Exception: pass
                if active and not messagebox.askyesno('Trámites activos',
                    'Outlook sigue esperando códigos en canales: '+', '.join(active)+'. ¿Cerrar de todos modos?',parent=self):
                    return
            except Exception:pass
            for p in self.children.values():
                try:
                    if p.poll() is None:p.terminate()
                except Exception:pass
        super().close()

def main():
    if '--worker' in sys.argv:
        i=sys.argv.index('--worker')
        n=int(sys.argv[i+1])
        if n not in (2,3,4): raise ValueError('Sesión secundaria incorrecta')
        os.environ['GD_WORKER_SLOT']=str(n)
        os.environ['GD_HEADLESS']='1'
        app=OutlookV32()
        app.withdraw()  # Headless worker has no extra app window.
    else:
        app=OutlookV33()
    app.mainloop()
if __name__=='__main__':main()
