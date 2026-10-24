# -*- coding: utf-8 -*-
"""Gestoría Díaz IMSS V24, 4 concurrent slot-bound Outlook links. ADB V7 unchanged."""
from __future__ import annotations
import queue,re,threading,time,uuid,tkinter as tk
from tkinter import messagebox,simpledialog
from gestoria_panel_v23 import PanelV23
from gestoria_paso1_v8 import GOLD,PANEL,FG
from puente_imss_outlook_v14 import PuenteOutlook,tramitar_con_outlook
from enlace import Client
from preparacion_v24 import PreparationV24
from gestoria_prueba_v7 import foreground
from imss_paso1 import login_detected
from imss_flujo_v11 import quick_ui
from gestoria_panel_v20 import MAX_CUENTAS_POR_SOLICITUD

class PanelV24(PanelV23):
    def __init__(self,root):
        self.peers=[PuenteOutlook(Client(port=8797+i,timeout=2)) for i in range(4)]
        self.peer_ok=[False]*4
        self.active_jobs={}
        self.job_stops={}
        super().__init__(root)
        self.preparacion=PreparationV24()
        root.title('GESTORÍA DÍAZ · IMSS V24 · 4 SOLICITUDES EN PARALELO')
        self.add_btn.configure(text='AGREGAR CURP · PRÓXIMO ANDROID LIBRE (HASTA 4 SIMULTÁNEOS)')
        self.status_outlook.configure(text='OUTLOOK: sesiones 1–4: comprobando conexiones independientes…')
        # On each press of Agregar CURP, the operator is responsible for ensuring
        # the titular actually authorized that particular request.
        form=self.add_btn.master
        for child in form.winfo_children():
            if isinstance(child,tk.Checkbutton) and 'titular autoriz' in str(child.cget('text')).lower():
                child.pack_forget()
        tk.Label(form,text='Solo solicitudes con autorización del titular. Al agregar cada CURP confirmas contar con ella.',
                 bg=PANEL,fg=GOLD,wraplength=1050,justify='left').pack(anchor='w',before=self.add_btn,pady=5)
        self.log('V24: 4 sesiones Outlook aisladas con puertos 8797 a 8800 y 4 folios independientes.')
        self.log('V24: al añadir CURP declaras tener autorización del titular de ESA solicitud.')

    def _update_queue_explain(self):
        if self.monitor_stop.is_set():return
        count=len(self.pending)
        busy=len(self.active_jobs)
        free=sum(1 for i,st in enumerate(self.states) if st=='LIBRE' and i not in self.active_jobs)
        connected=sum(bool(x) for x in self.peer_ok)
        if count:
            text=f'COLA: {count} solicitudes esperando · {busy}/4 activos · {connected}/4 Outlook disponibles · {free} Android libres.'
        else:
            text=f'LISTO PARA OTRA CURP · {busy}/4 activos · {connected}/4 Outlook disponibles · {free} Android libres.'
        self.queue_explain.set(text)
        self.root.after(1800,self._update_queue_explain)

    def probe_outlook_loop(self):
        # Invoked during constructor by V14; peers are initialized first.
        while not self.monitor_stop.wait(2.5):
            available=[]
            for i,peer in enumerate(self.peers):
                try:
                    ping=peer.comprobar()
                    ok=bool(ping.get('available')) and self.preparacion.live(i+1)
                except Exception:ok=False
                available.append(ok)
            self.peer_ok[:]=available
            self.send('outlook_state',f'OUTLOOK V32: {sum(available)}/4 sesiones libres · {len(self.active_jobs)}/4 trámites activos')

    def enqueue(self):
        curp=self.curp_var.get().strip().upper()
        if not re.fullmatch(r'[A-Z0-9]{18}',curp):
            messagebox.showerror('CURP','Ingresa 18 caracteres alfanuméricos.');return
        if not self.adb or not any(self.serials):
            messagebox.showwarning('ADB','Conecta primero los cuatro emuladores.');return
        if len(self.pending)>=100:
            messagebox.showwarning('Cola','Máximo de 100 solicitudes pendientes.');return
        # The button action is an explicit declaration regarding this CURP;
        # there is no prechecked checkbox silently attesting for the user.
        self.sequence+=1
        self.pending.append((self.sequence,curp,None))
        self.curp_var.set('')
        self.update_count()
        self.log(f'Solicitud #{self.sequence} agregada. En cuanto haya un Android y Outlook libres, se inicia.')
        self.dispatch()

    def dispatch(self):
        if self.working or not self.pending or not hasattr(self,'preparacion'):return
        for slot in range(4):
            if not self.pending:break
            if (slot in self.active_jobs or not self.serials[slot] or
                self.states[slot]!='LIBRE' or not self.peer_ok[slot]):continue
            folio=uuid.uuid4().hex
            try:email=self.pool.reserve(folio)
            except Exception:self.log('No se pudo reservar una cuenta de correo para un trámite.');break
            if not email:break
            try:self.preparacion.create(folio,email,worker=slot+1)
            except Exception:
                self.pool.review(folio)
                self.log('No pudo prepararse la bandeja del Android '+str(slot+1));continue
            reqid,curp,_=self.pending.popleft()
            self.folios[slot]=folio
            self.set_status(slot,'OCUPADO',f'Outlook {slot+1}: comprobando bandeja propia')
            pin=self.pin_var.get() if self.use_pin.get() else ''
            override=self.allow_manual[slot];self.allow_manual[slot]=False
            stop=threading.Event()
            self.active_jobs[slot]={'folio':folio,'reqid':reqid}
            self.job_stops[slot]=stop
            self.peer_ok[slot]=False
            self.update_count();self.update_pool_label()
            self.log(f'Android {slot+1}: solicitud #{reqid} asignada a Outlook {slot+1}.')
            self.executor.submit(self.login_worker,slot,reqid,curp,email,override,pin,stop,folio)
        self.active_outlook=bool(self.active_jobs)

    def login_worker(self,slot,reqid,curp,email,override,pin,stop,folio):
        chosen_email=email;chosen_folio=folio
        try:
            for attempt in range(MAX_CUENTAS_POR_SOLICITUD):
                deadline=time.monotonic()+190
                stage=None
                while time.monotonic()<deadline and not stop.is_set():
                    info=self.preparacion.status(chosen_folio)
                    stage=info['estado'] if info else 'REVISAR'
                    if stage in ('LISTO','BLOQUEADA','REVISAR','LIMITE_MICROSOFT','METODO_NO_DISPONIBLE'):break
                    stop.wait(1.25)
                if stop.is_set():break
                if stage=='LISTO':
                    self.send('status',slot,'OCUPADO','Bandeja lista; iniciando IMSS Digital')
                    state,detail,fn,finished=tramitar_con_outlook(
                        self.adb,self.serials[slot],curp,chosen_email,pin,override,
                        update=lambda txt:self.send('status',slot,'OCUPADO',txt),
                        stop=stop,puente=self.peers[slot],folio_id=chosen_folio)
                    self.send('bridge_result',slot,reqid,state,detail,fn,finished)
                    return
                self.pool.review(chosen_folio)
                if stage=='LIMITE_MICROSOFT':
                    self.send('bridge_result',slot,reqid,'REVISAR',
                        'Límite Microsoft: no se reintentan accesos.',None,True);return
                self.preparacion.finish(chosen_folio)
                # A single alternative after explicit unavailable sign-in method,
                # never rotate accounts to bypass a limit, challenge, or ban.
                if stage!='METODO_NO_DISPONIBLE' or attempt>=1:break
                next_folio=uuid.uuid4().hex
                next_email=self.pool.reserve(next_folio)
                if not next_email:break
                try:self.preparacion.create(next_folio,next_email,worker=slot+1)
                except Exception:self.pool.review(next_folio);break
                self.folios[slot]=next_folio
                self.active_jobs[slot]['folio']=next_folio
                chosen_email,chosen_folio=next_email,next_folio
                self.send('status',slot,'OCUPADO','Método de contraseña no disponible: revisando otra cuenta autorizada')
            self.send('bridge_result',slot,reqid,'REVISAR',
                'No se confirmó la bandeja; revisar acceso a Outlook.',None,True)
        except Exception as exc:
            try:self.pool.review(chosen_folio)
            except Exception:pass
            self.send('bridge_result',slot,reqid,'REVISAR',
                'Error de preparación ('+type(exc).__name__+').',None,True)
        finally:del pin

    def pump(self):
        try:
            while True:
                action,*args=self.messages.get_nowait()
                if action=='log':self.log(args[0])
                elif action=='status':self.set_status(*args)
                elif action=='attached':
                    self.adb,self.serials,assessments=args
                    for i,info in enumerate(assessments):self.set_status(i,info[0],info[1])
                    self.working=False
                elif action=='opened':
                    for i,status,detail in args[0]:self.set_status(i,status,detail)
                    self.working=False
                elif action=='ready':
                    slot,ok,detail=args
                    if self.folios[slot]:ok=False;detail='Correo aún vinculado; termina el trámite.'
                    self.allow_manual[slot]=False
                    self.set_status(slot,'LIBRE' if ok else 'REVISAR',detail)
                elif action=='manual_check':
                    i,serial=args
                    if not self.folios[i] and foreground(self.adb,serial) is True:
                        if messagebox.askyesno('Confirmar inicio',f'Android {i+1}: ¿ves el inicio IMSS?'):
                            self.allow_manual[i]=True
                            self.set_status(i,'LIBRE','Inicio confirmado por operador')
                elif action=='finish':self.working=False
                elif action=='outlook_state':self.status_outlook.configure(text=args[0])
                elif action=='bridge_result':
                    slot,reqid,status,detail,folio,finished=args
                    self.set_status(slot,status,detail)
                    self.log(f'Android {slot+1} solicitud #{reqid}: {status} (datos privados omitidos).')
                    self.active_jobs.pop(slot,None)
                    self.job_stops.pop(slot,None)
                    if not folio:
                        old=self.folios[slot]
                        if old:
                            try:self.pool.review(old)
                            except Exception:pass
                        # Do not automatically free the Android after failure.
                    elif not finished:
                        try:self.pool.review(folio)
                        except Exception:pass
                    self.active_outlook=bool(self.active_jobs)
                    self.update_count()
                elif action=='reset_v14':
                    slot,status,detail,error=args
                    if status=='LIBRE' and not error:
                        self.folios[slot]=None
                        self.set_status(slot,'LIBRE','PDF confirmado · correo consumido · IMSS en inicio')
                    else:self.set_status(slot,'REVISAR',detail or 'PDF no confirmado; revisar')
                    self.reset_in_progress.discard(slot)
                elif action=='watchdog_v14':
                    slot,ok,detail=args
                    self.set_status(slot,('REVISAR' if self.folios[slot] else 'LIBRE') if ok else 'REVISAR',detail)
                elif action=='outlook_available':pass
                elif action=='release_done':
                    slot,ok=args
                    if ok:self.log(f'Outlook {slot+1}: enlace liberado.')
                    else:self.log(f'Outlook {slot+1}: no se pudo liberar.')
        except queue.Empty:pass
        self.update_pool_label()
        self.dispatch()
        self.root.after(450,self.pump)

    def _finish_manually(self,done):
        eligible={i:data for i,data in self.active_jobs.items() if data.get('folio')}
        if not eligible:
            messagebox.showinfo('Sin enlace activo','No hay folio activo.');return
        slot=simpledialog.askinteger('Android','Elige Android a liberar (1–4):',minvalue=1,maxvalue=4)
        if slot is None:return
        i=slot-1
        if i not in eligible:
            messagebox.showwarning('Sin folio','Ese Android no tiene código activo.');return
        if not messagebox.askyesno('Confirmar','¿El código ya fue aceptado?' if done else '¿Cancelar este enlace?'):
            return
        folio=eligible[i]['folio']
        self.job_stops[i].set()
        def worker():
            try:
                if done:
                    self.peers[i].confirmar_recepcion(folio);self.peers[i].terminar_enlace(folio)
                else:self.peers[i].cancelar(folio)
                self.send('release_done',i,True)
            except Exception:self.send('release_done',i,False)
        threading.Thread(target=worker,daemon=True).start()

    def detener_espera(self):
        if not self.active_jobs:return
        slot=simpledialog.askinteger('Detener','Elige Android (1–4):',minvalue=1,maxvalue=4)
        if slot and (slot-1) in self.job_stops:self.job_stops[slot-1].set()

    def close(self):
        for flag in self.job_stops.values():flag.set()
        super().close()

def main():
    root=tk.Tk();PanelV24(root);root.mainloop()
if __name__=='__main__':main()
