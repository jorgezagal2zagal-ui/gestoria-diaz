# -*- coding: utf-8 -*-
"""IMSS V30: Android step 1 and Outlook sign-in proceed concurrently.
One folio/email per Android; no automatic account rotation after IMSS has started.
"""
import threading,time,queue
from gestoria_panel_v24 import PanelV24
from puente_imss_outlook_v14 import tramitar_con_outlook
from imss_flujo_v14 import step_flow_v12
from gestoria_panel_v20 import MAX_CUENTAS_POR_SOLICITUD

class PanelV30(PanelV24):
    def __init__(self,root):
        self._stall_progress={}
        self._stall_recovery={}
        self._imss_entry_threads={}
        self._job_done={}
        self._worker_done={}
        self._review_cleanup={}
        super().__init__(root)
        root.title('GESTORÍA DÍAZ · IMSS V30 · CUATRO ANDROID + OUTLOOK SIMULTÁNEOS')
        self.log('V30: el vigilante recupera el Android si no hay avance; no borra la app ni reutiliza el correo.')
        import tkinter as tk
        from gestoria_paso1_v8 import GOLD
        self.root.title('GESTORÍA DÍAZ · IMSS V30 · RECUPERACIÓN AUTOMÁTICA · 4 ANDROID')
        tk.Label(self.root,text='IMSS V30  |  4 ANDROID  |  AUTORECUPERACIÓN: 120 s SIN AVANCE / 300 s EN CÓDIGO',
                 bg='#111215',fg=GOLD,font=('Segoe UI',11,'bold')).pack(
                    anchor='w',padx=20,before=self.add_btn.master)
        tk.Button(self.add_btn.master,text='RECUPERAR UN ANDROID ATORADO (MANUAL)',
                  bg='#343842',fg='#f8f5ed',bd=0,pady=7,
                  command=self.recover_manual).pack(fill='x',before=self.add_btn,pady=3)
        self.root.after(1000,self._stall_tick)

    def send(self,*message):
        # Called from workers: only a lock-free monotonic timestamp is updated.
        # Never copy CURP, OTP or email to diagnostic records.
        if message and message[0]=='status' and len(message)>=4 and message[2]=='OCUPADO':
            slot=message[1]
            if slot in self._stall_progress:
                entry=self._stall_progress[slot]
                stage=str(message[3])
                if stage != entry['stage']:
                    entry['stage']=stage
                    entry['changed']=time.monotonic()
                    if 'codigo' in stage.casefold() or 'código' in stage.casefold():
                        entry['code_phase']=True
        if message and message[0]=='bridge_result' and len(message)>=7:
            _,slot,reqid,state,detail,folio,finished=message[:7]
            # Only auto-recover failures BEFORE delivering any verification code.
            # Never discard a potentially accepted OTP or a PDF in progress.
            desc=str(detail).casefold()
            safe_before_otp=any(term in desc for term in (
                'no llegó un código', 'no se confirmó en imss la pantalla',
                'no se confirmó la pantalla del código',
                'outlook no confirmó', 'no se confirmó la bandeja',
                'outlook no aceptó', 'no se completó el inicio de imss',
                'campo de correo', 'verificación final fallida',
                'no pudo rellenar', 'formulario no enviado',
                'no se pudo comprobar el correo'))
            if state=='REVISAR' and folio and not finished and safe_before_otp:
                self._review_cleanup[slot]={
                    'folio':folio,'reqid':reqid,'since':time.monotonic()}
        return super().send(*message)

    def _stall_tick(self):
        if self.monitor_stop.is_set():return
        now=time.monotonic()
        for slot,job in list(self.active_jobs.items()):
            if slot in self._stall_recovery:continue
            current=self._stall_progress.get(slot)
            if current is None or current['folio']!=job['folio']:
                self._stall_progress[slot]={
                    'folio':job['folio'],'changed':now,'stage':'iniciando',
                    'code_phase':False}
                continue
            if self.states[slot]!='OCUPADO':continue
            limit=300 if current['code_phase'] else 120
            if now-current['changed']>=limit:
                self._begin_recovery(slot,job,reason='SIN AVANCE durante '+str(limit)+' s')
        for slot,review in list(self._review_cleanup.items()):
            if self.folios[slot]!=review['folio']:
                self._review_cleanup.pop(slot,None)
                continue
            if (slot not in self.active_jobs and slot not in self._stall_recovery
                and self.states[slot]=='REVISAR' and now-review['since']>=90):
                self._begin_recovery(slot,review,reason='ERROR SIN AVANCE durante 90 s')
                self._review_cleanup.pop(slot,None)
        for slot,record in list(self._stall_recovery.items()):
            if record.get('future') is None:
                # Do not reset the app while ANY prior worker can still send ADB commands.
                entry_thread=self._imss_entry_threads.get(slot)
                worker_done=self._worker_done.get(slot)
                if ((worker_done and worker_done.is_set()) and
                    (entry_thread is None or not entry_thread.is_alive()) and
                    slot not in self.active_jobs):
                    record['future']=self.executor.submit(self._restore_slot,slot,record['folio'])
                elif now-record['since']>90:
                    self.set_status(slot,'REVISAR','Reinicio suspendido: proceso ADB aún activo; no se mezclaron solicitudes.')
                    # Keep the slot blocked. Never launch a second job on a live worker.
            elif record['future'].done():
                try:ok,reason=record['future'].result()
                except Exception as exc:ok,reason=False,'Error al recuperar ('+type(exc).__name__+')'
                self._finish_recovery(slot,record,ok,reason)
        self.root.after(1000,self._stall_tick)

    def _begin_recovery(self,slot,job,reason):
        if slot in self._stall_recovery:return
        folio=job['folio']
        self._stall_recovery[slot]={'folio':folio,'reqid':job['reqid'],
                                   'since':time.monotonic(),'future':None}
        flag=self.job_stops.get(slot)
        if flag:flag.set()
        self.set_status(slot,'RECUPERANDO','Deteniendo la solicitud anterior de forma segura…')
        self.log(f'Android {slot+1}: {reason}. Correo anterior se aparta, nunca se reutiliza.')

    def _restore_slot(self,slot,folio):
        from gestoria_prueba_v7 import adb_run, launch_imss, PACKAGE
        from imss_flujo_v11 import quick_ui
        from imss_paso1 import login_detected
        try:
            self.pool.review(folio)
        except Exception:pass
        # The cancellation is not considered successful if Outlook did not accept it.
        try:
            resp=self.peers[slot].cancelar(folio)
            if not (isinstance(resp,dict) and resp.get('ok') is True):
                return False,'Outlook no confirmó cancelación; sesión retenida.'
        except Exception:
            # The IMSS form may stall before Outlook has registered the folio.
            # Only accept the server's explicit SIN_SOLICITUD/CANCELADA status;
            # a network error or another active folio MUST block reuse.
            try:
                state=self.peers[slot].estado(folio).get('status')
            except Exception:
                return False,'Outlook no responde o mantiene otra solicitud; revisión necesaria.'
            if state not in ('SIN_SOLICITUD','CANCELADA'):
                return False,'Outlook no confirmó cancelación del enlace; sesión retenida.'
        try:self.preparacion.finish(folio)
        except Exception:pass
        serial=self.serials[slot]
        if not serial or not self.adb:return False,'ADB no tiene conexión con el Android.'
        try:
            # Force-stop only the IMSS application. NEVER pm clear, wipe data or factory reset.
            rc,_=adb_run(self.adb,serial,'shell','am','force-stop',PACKAGE,timeout=14)
            if rc:return False,'Android no pudo cerrar IMSS Digital.'
            state,_=launch_imss(self.adb,serial,lambda _msg:None)
            if state!='ABIERTA':return False,'No se logró reabrir IMSS Digital.'
            for _ in range(3):
                if login_detected(quick_ui(self.adb,serial)):
                    return True,'IMSS reiniciado y pantalla inicial confirmada.'
                time.sleep(1.0)
            return False,'No se confirmó formulario inicial; Android retenido para revisión.'
        except Exception as exc:
            return False,'Fallo al reiniciar IMSS ('+type(exc).__name__+')'

    def _finish_recovery(self,slot,record,ok,detail):
        # Slot must still refer to the canceled folio. If not, do not touch it.
        if self.folios[slot]!=record['folio']:
            self._stall_recovery.pop(slot,None)
            return
        if ok:
            self.folios[slot]=None
            self.allow_manual[slot]=False
            self.set_status(slot,'LIBRE','Recuperado; disponible para otra CURP.')
            self.log(f'Android {slot+1}: recuperado y disponible; código anterior cancelado.')
        else:
            self.set_status(slot,'REVISAR',detail)
            self.log(f'Android {slot+1}: recuperación incompleta, permanece retenido.')
        self._stall_progress.pop(slot,None)
        self._review_cleanup.pop(slot,None)
        self._stall_recovery.pop(slot,None)
        self.update_count()

    def recover_manual(self):
        from tkinter import simpledialog,messagebox
        slot=simpledialog.askinteger('Recuperar Android','Android a recuperar (1 a 4):',minvalue=1,maxvalue=4)
        if slot is None:return
        idx=slot-1
        job=self.active_jobs.get(idx)
        if not job and self.folios[idx] and self.states[idx]=='REVISAR':
            job={'folio':self.folios[idx], 'reqid':0}
        if not job:
            messagebox.showinfo('Android','No tiene una operación activa ni un folio en revisión.')
            return
        if not messagebox.askyesno('Cancelar trámite',
                  f'¿Cancelar el trámite activo del Android {slot}? El correo quedará en REVISAR, no se reutilizará.'):
            return
        self._begin_recovery(idx,job,'RECUPERACIÓN MANUAL')

    def login_worker(self,slot,reqid,curp,email,override,pin,stop,folio):
        done=threading.Event()
        self._worker_done[slot]=done
        early=queue.Queue(maxsize=1)
        def imss_first():
            try:
                answer=step_flow_v12(self.adb,self.serials[slot],curp,email,pin,
                                     ready_confirmed_by_operator=override,
                                     update=lambda txt:self.send('status',slot,'OCUPADO',txt),stop=stop)
            except Exception as exc:
                answer=('REVISAR','No se completó el inicio de IMSS ('+type(exc).__name__+').')
            early.put(answer)
        thread=threading.Thread(target=imss_first,daemon=True,name='imss-v30-android-'+str(slot+1))
        self._imss_entry_threads[slot]=thread
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
            done.set()
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
            done.set()
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
            done.set()
            del pin

def main():
    import tkinter as tk
    root=tk.Tk();PanelV30(root);root.mainloop()
if __name__=='__main__':main()
