# -*- coding: utf-8 -*-
"""IMSS V27: Android step 1 and Outlook sign-in proceed concurrently.
One folio/email per Android; no automatic account rotation after IMSS has started.
"""
import threading,time,queue
from gestoria_panel_v24 import PanelV24
from puente_imss_outlook_v14 import tramitar_con_outlook
from imss_flujo_v13 import step_flow_v12
from gestoria_panel_v20 import MAX_CUENTAS_POR_SOLICITUD

class PanelV27(PanelV24):
    def __init__(self,root):
        super().__init__(root)
        root.title('GESTORÍA DÍAZ · IMSS V27 · CUATRO ANDROID + OUTLOOK SIMULTÁNEOS')
        self.log('V27: IMSS inicia y Outlook opera en paralelo; se verifica CURP antes de correo.')
        import tkinter as tk
        from gestoria_paso1_v8 import GOLD
        self.root.title('GESTORÍA DÍAZ · IMSS V27 ACTUALIZADO · CURP VERIFICADA + ENTRADA ÁGIL · 4 ANDROID')
        tk.Label(self.root,text='IMSS V27 NUEVO  |  4 ANDROID  |  CURP + CORREO VERIFICADOS ANTES DE ENVIAR',
                 bg='#111215',fg=GOLD,font=('Segoe UI',11,'bold')).pack(
                    anchor='w',padx=20,before=self.add_btn.master)


    def login_worker(self,slot,reqid,curp,email,override,pin,stop,folio):
        early=queue.Queue(maxsize=1)
        def imss_first():
            try:
                answer=step_flow_v12(self.adb,self.serials[slot],curp,email,pin,
                                     ready_confirmed_by_operator=override,
                                     update=lambda txt:self.send('status',slot,'OCUPADO',txt))
            except Exception as exc:
                answer=('REVISAR','No se completó el inicio de IMSS ('+type(exc).__name__+').')
            early.put(answer)
        thread=threading.Thread(target=imss_first,daemon=True,name='imss-v26-android-'+str(slot+1))
        thread.start()
        self.send('status',slot,'OCUPADO','IMSS y Outlook trabajando en paralelo')
        stage=None
        deadline=time.monotonic()+190
        while time.monotonic()<deadline and not stop.is_set():
            task=self.preparacion.status(folio)
            stage=task['estado'] if task else 'REVISAR'
            if stage in ('LISTO','BLOQUEADA','REVISAR','LIMITE_MICROSOFT','METODO_NO_DISPONIBLE'):
                break
            stop.wait(1.1)
        if stop.is_set():
            self.send('bridge_result',slot,reqid,'REVISAR','Trámite detenido; revisar ambas pantallas.',folio,False)
            return
        if stage!='LISTO':
            try:self.pool.review(folio)
            except Exception:pass
            details={'BLOQUEADA':'Cuenta bloqueada por Microsoft',
                     'LIMITE_MICROSOFT':'Microsoft limitó el acceso, sin nuevos intentos',
                     'METODO_NO_DISPONIBLE':'Microsoft exige otro método de inicio',
                     'REVISAR':'Outlook necesita revisión'}
            detail=details.get(stage,'Outlook no confirmó la bandeja en el tiempo permitido')
            self.send('bridge_result',slot,reqid,'REVISAR',detail+'. Android reservado para evitar cruzar códigos.',folio,False)
            return
        def already_started(stop_signal):
            # Never repeat the CURP/login; wait for the one-time Android result.
            while not stop_signal.is_set():
                try:return early.get(timeout=1.0)
                except queue.Empty:continue
            return 'REVISAR','El trámite fue detenido mientras IMSS trabajaba.'
        try:
            state,detail,linked,finished=tramitar_con_outlook(
                self.adb,self.serials[slot],curp,email,pin,override,
                update=lambda txt:self.send('status',slot,'OCUPADO',txt),
                stop=stop,puente=self.peers[slot],folio_id=folio,
                prestarted_flow=already_started)
            self.send('bridge_result',slot,reqid,state,detail,linked,finished)
        except Exception as exc:
            self.send('bridge_result',slot,reqid,'REVISAR',
                'Falla en el enlace ('+type(exc).__name__+'); revisar sin repetir la solicitud.',folio,False)
        finally:
            del pin

def main():
    import tkinter as tk
    root=tk.Tk();PanelV27(root);root.mainloop()
if __name__=='__main__':main()
