# -*- coding: utf-8 -*-
"""V36: 4 truly visible Chrome instances, diagnostics and verified manual IMSS code bridge."""
import os,sys,tkinter as tk,time,threading,subprocess
from pathlib import Path
from tkinter import ttk,messagebox,scrolledtext
# These are set before importing any module that binds a slot-local bridge port.
if '--worker' in sys.argv:
    idx=sys.argv.index('--worker')
    os.environ['GD_WORKER_SLOT']=sys.argv[idx+1]
else:
    os.environ['GD_WORKER_SLOT']='1'
os.environ['GD_HEADLESS']='0'
from app_v35 import OutlookV35
from app_v32 import OutlookV32
from enlace import Client
from diagnostico_v36 import record,tail
from app import BG,BOX,GOLD,WHITE,GRAY

class DiagnosticMixin:
    def _diag(self,message):
        try:record(int(os.environ.get('GD_WORKER_SLOT','1')),message)
        except Exception:pass
    def _show_browser_event(self,message):
        self._diag('CHROME: '+str(message))
        super()._show_browser_event(message)
    def _deliver_browser_code(self,request_id,code,email):
        self._diag('CÓDIGO IMSS: encontrado, intentando depositar en enlace local.')
        try:
            result=super()._deliver_browser_code(request_id,code,email)
            self._diag('CÓDIGO IMSS: depositado en enlace; Android debe confirmar recepción.')
            return result
        except Exception as e:
            self._diag('FALLO DE ENTREGA: '+type(e).__name__)
            raise
    def _tick_once(self):
        super()._tick_once()
        try:
            state=self.state.status()['status']
            phase=getattr(self.browser,'phase','desconocido')
            if (state,phase)!=getattr(self,'_v36_last',None):
                self._v36_last=(state,phase)
                self._diag('ESTADO: '+state+'; navegador: '+phase)
            if self.browser.running and self.browser.browser_opened.is_set():
                now=time.monotonic()
                if now-getattr(self,'_v36_wincheck_at',0)>6:
                    self._v36_wincheck_at=now
                    from diagnostico_v23 import window_state
                    win=window_state()
                    signal=(win.get('processes'),win.get('visible'))
                    if signal!=getattr(self,'_v36_last_windows',None):
                        self._v36_last_windows=signal
                        self._diag('VENTANAS WINDOWS: Chrome hijos='+str(signal[0])+', visibles='+str(signal[1]))

        except Exception:pass

class OutlookWorkerV36(DiagnosticMixin,OutlookV32):
    pass

class OutlookV36(DiagnosticMixin,OutlookV35):
    def __init__(self):
        self._v36_last=None
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V36 · CHROME VISIBLE + DIAGNÓSTICO')
        self.geometry('1000x850')
        main=self.winfo_children()[0]
        box=tk.Frame(main,bg=BOX,padx=9,pady=9)
        box.pack(fill='x',padx=0,pady=(5,6),before=main.winfo_children()[0])
        tk.Label(box,text='CHROME VISIBLE · DIAGNÓSTICO DE 4 CANALES · ENTREGA MANUAL DE EMERGENCIA',
            bg=BOX,fg=GOLD,font=('Segoe UI',10,'bold'),anchor='w').pack(fill='x')
        row=tk.Frame(box,bg=BOX);row.pack(fill='x',pady=(7,2))
        tk.Label(row,text='Android / Outlook:',bg=BOX,fg=WHITE).pack(side='left')
        self.slot_v36=tk.StringVar(value='1')
        self.slot_choose=ttk.Combobox(row,textvariable=self.slot_v36,width=5,
                                     values=['1','2','3','4'],state='readonly')
        self.slot_choose.pack(side='left',padx=7)
        tk.Label(row,text='Código IMSS:',bg=BOX,fg=WHITE).pack(side='left')
        self.code_v36=tk.StringVar()
        self.manual_entry=ttk.Entry(row,textvariable=self.code_v36,width=9,show='●')
        self.manual_entry.pack(side='left',padx=7)
        self.button(row,'ENTREGAR AL ANDROID',self.manual_send_v36,True).pack(side='left',padx=4)
        self.button(row,'VER DIAGNÓSTICO',self.view_diagnostics_v36).pack(side='left',padx=4)
        tk.Label(box,text='Este campo es exclusivamente para el código del correo IMSS, NO para códigos de inicio de sesión Microsoft. '+
            'Sólo permite enviar al folio activo del Android seleccionado.',
            bg=BOX,fg=GRAY,justify='left',wraplength=950).pack(fill='x',pady=(4,1))
        self._diag('PANEL V36: Chrome visible solicitado para los 4 canales.')
    def start_worker(self,n):
        if n not in (2,3,4):return
        old=self.children.get(n)
        if old and old.poll() is None:return
        env=os.environ.copy()
        env.update(GD_WORKER_SLOT=str(n),GD_HEADLESS='0',GD_BG_WORKER='1')
        self.children[n]=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',str(n)],
            env=env,cwd=str(Path(__file__).resolve().parent),close_fds=True)

    def manual_send_v36(self):
        import re
        from enlace import Client
        n=int(self.slot_v36.get())
        code=self.code_v36.get().strip()
        if not re.fullmatch(r'[0-9]{6}',code):
            messagebox.showwarning('Código IMSS','Introduce los 6 dígitos del correo de IMSS, NO de Microsoft.',parent=self)
            return
        client=Client(port=8796+n,timeout=1.0)
        try:
            state=client.call('/v1/estado')
            if state.get('status') not in ('ESPERANDO_CODIGO','CODIGO_DISPONIBLE'):
                raise ValueError('El Android seleccionado no tiene un trámite IMSS esperando código.')
            folio=state.get('request_id')
            email=state.get('email')
            if not folio or not email:raise ValueError('Falta correo o folio de la solicitud IMSS.')
            # Prevent sending a Microsoft sign-in code by requiring human confirmation.
            if not messagebox.askyesno('Confirmar código IMSS',
                  f'¿Confirmas que estos 6 dígitos proceden del CORREO DE VERIFICACIÓN IMSS\n'+
                  f'y corresponden a Android {n}, no del inicio de sesión Microsoft?',parent=self):return
            client.call('/v1/codigo',{'id':folio,'email':email,'code':code})
            self.code_v36.set('')
            self._diag('ENTREGA MANUAL: código depositado en canal '+str(n)+'; pendiente Android.')
            messagebox.showinfo('Enviado al enlace',
                f'Código disponible para Android {n}. El otro bot debe leerlo y confirmar el avance.\n'+
                'No significa que IMSS ya haya aceptado el código.',parent=self)
        except Exception as e:
            self._diag('ERROR ENTREGA MANUAL canal '+str(n)+': '+type(e).__name__)
            messagebox.showerror('No se entregó el código',str(e)[:250],parent=self)
    def view_diagnostics_v36(self):
        win=tk.Toplevel(self)
        win.title('Gestoría Díaz · Diagnóstico en vivo · Sin códigos ni contraseñas')
        win.geometry('930x500');win.configure(bg=BG)
        view=scrolledtext.ScrolledText(win,bg=BOX,fg=WHITE,insertbackground=WHITE,font=('Consolas',9))
        view.pack(fill='both',expand=True,padx=9,pady=9)
        def refresh():
            if not win.winfo_exists():return
            out=[]
            for n in (1,2,3,4):
                out.append('===== OUTLOOK / ANDROID '+str(n)+' =====')
                out.extend(tail(n,20))
                try:
                    st=Client(port=8796+n,timeout=0.15).call('/v1/estado')
                    out.append('ENLACE: '+str(st.get('status')))
                except Exception as e:
                    out.append('ENLACE: SIN CONEXIÓN ('+type(e).__name__+')')
            view.configure(state='normal')
            view.delete('1.0','end');view.insert('end','\n'.join(out))
            view.configure(state='disabled')
            win.after(1200,refresh)
        refresh()

def main():
    os.environ['GD_HEADLESS']='0'
    if '--worker' in sys.argv:
        idx=sys.argv.index('--worker')
        n=int(sys.argv[idx+1])
        if n not in (2,3,4):raise ValueError('Worker inválido')
        os.environ['GD_WORKER_SLOT']=str(n)
        app=OutlookWorkerV36()
        app.withdraw()  # The Tk worker alone is hidden; Chromium stays visible.
        app._diag('TRABAJADOR: esperando solicitud en Chrome visible')
    else:
        app=OutlookV36()
    app.mainloop()
if __name__=='__main__':main()
