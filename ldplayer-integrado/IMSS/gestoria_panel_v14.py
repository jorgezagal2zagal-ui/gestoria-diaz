# -*- coding: utf-8 -*-
"""IMSS V14: cola CURP solamente, cuentas compartidas, cierre seguro y vigilante de inicio.

El núcleo ADB/abrir V7 y los flujos IMSS V8-V12 no son editados.
"""
from __future__ import annotations
import queue, re, threading, time, uuid
from tkinter import filedialog, messagebox
import tkinter as tk
from gestoria_panel_v13 import PanelV13
from puente_imss_outlook_v14 import tramitar_con_outlook
from gestoria_prueba_v7 import adb_run, launch_imss, foreground
from imss_paso1 import login_detected
from imss_flujo_v11 import quick_ui
from pool_v14 import SharedPool, VAULT_DB

class PanelV14(PanelV13):
    def __init__(self,root):
        super().__init__(root)
        self.pool=SharedPool()
        self.folios=[None]*4
        self.monitor_stop=threading.Event()
        self.reset_in_progress=set()
        self.outlook_can_start=False
        threading.Thread(target=self.probe_outlook_loop,daemon=True).start()
        root.title('GESTORÍA DÍAZ · IMSS DIGITAL V14 · COLA COMPARTIDA')
        self.add_btn.configure(text='2. ENVIAR CURP AL ANDROID LIBRE + CORREO AUTOMÁTICO')
        # La entrada de correo de V8 permanece en su archivo original, pero
        # no se muestra en V14: la asignación es exclusiva de SQLite.
        self.email_entry.master.pack_forget()
        import_btn=tk.Button(self.add_btn.master,text='IMPORTAR TXT CORREOS | CONTRASEÑAS',
                  command=self.import_pool,bg='#343842',fg='#f8f5ed',bd=0,pady=8)
        import_btn.pack(fill='x',before=self.add_btn,pady=5)
        self.pool_label=tk.Label(root,text='Lista compartida: comprobando…',
            bg='#111215',fg='#e2b44c',font=('Segoe UI',10,'bold'))
        self.pool_label.pack(anchor='w',padx=20,before=self.add_btn.master)
        self.log('V14: ingresa sólo CURP. IMSS reserva automáticamente un correo NUEVO. Outlook usa esa misma cuenta.')
        self.log('Correo usado se elimina sólo después de confirmar PDF y verificar retorno a inicio.')
        threading.Thread(target=self.watch_loop,daemon=True).start()

    def import_pool(self):
        from pool_v14 import PoolError
        try:
            from tkinter import filedialog
            import os,sys
            # Reutiliza el lector robusto original de Outlook sin importar su UI.
            from credenciales import decode_file, Vault
            path=filedialog.askopenfilename(title='Importar nueva lista compartida',filetypes=[('TXT','*.txt')])
            if not path:return
            items=decode_file(path)
            if not items or any(not passwd for _,passwd in items):
                raise ValueError('Cada línea necesita correo y contraseña, separados por |')
            if not messagebox.askyesno('Reemplazar lista NUEVA V14',
                     f'Se reemplazará la lista V14 con {len(items)} correos. '
                     'No se cambiarán los bots anteriores. ¿Confirmas?'):
                return
            c=self.pool.counts()
            if c['OCUPADO'] or c['REVISAR']:
                raise PoolError('Finaliza o resuelve primero los correos ocupados o en revisión')
            vault=Vault(path=VAULT_DB)
            vault.save(items)
            self.pool.replace_fresh([e for e,_pw in items])
            with vault._db() as db:
                valid={r['email'] for r in self.pool.entries()}
                for (email,) in db.execute('SELECT email FROM credenciales').fetchall():
                    if email not in valid:db.execute('DELETE FROM credenciales WHERE email=?',(email,))
            self.update_pool_label()
            self.log(f'Lista nueva importada: {len(items)} disponibles (sin mostrar secretos).')
            messagebox.showinfo('Lista compartida','Lista importada. El bot Outlook V14 también la ve.')
        except Exception as exc:
            messagebox.showerror('Lista TXT','No se pudo importar: '+str(exc)[:160])

    def update_pool_label(self):
        try:
            c=self.pool.counts()
            self.pool_label.configure(text='CORREOS · Disponibles: {DISPONIBLE}  |  Ocupados: {OCUPADO}  |  Revisar: {REVISAR}  |  Eliminados: {ELIMINADOS}'.format(**c))
        except Exception:self.pool_label.configure(text='CORREOS · Error al leer el listado compartido')

    def probe_outlook_loop(self):
        while not self.monitor_stop.wait(2.5):
            try:
                state=self.puente.comprobar()
                self.send('outlook_available',bool(state.get('available')))
            except Exception:
                self.send('outlook_available',False)

    def enqueue(self):
        curp=self.curp_var.get().strip().upper()
        if not re.fullmatch(r'[A-Z0-9]{18}',curp):
            messagebox.showerror('CURP','Ingresa 18 caracteres alfanuméricos.');return
        if not self.permission.get():
            messagebox.showwarning('Autorización','Confirma primero la autorización del titular.');return
        if not self.adb or not any(self.serials):
            messagebox.showwarning('ADB','Conecta primero los emuladores.');return
        if len(self.pending)>=100:
            messagebox.showwarning('Cola','Máximo de 100 solicitudes pendientes.');return
        self.sequence+=1
        self.pending.append((self.sequence,curp,None))
        self.curp_var.set('');self.permission.set(False)
        self.update_count()
        self.log('CURP añadida a la cola; el correo se asignará cuando haya un Android libre.')

    def dispatch(self):
        # No consumir una cuenta cuando el lector Outlook todavía esté preparando
        # el navegador, en período de enfriamiento o sin conectarse.
        if (self.working or self.active_outlook is not None or not self.pending
            or not self.outlook_can_start):return
        slot=next((i for i,s in enumerate(self.states) if s=='LIBRE' and self.serials[i]),None)
        if slot is None:return
        folio=uuid.uuid4().hex
        try: email=self.pool.reserve(folio)
        except Exception as exc:
            self.log('No se pudo reservar correo en el listado compartido ('+type(exc).__name__+').');return
        if not email:return
        reqid,curp,_unused=self.pending.popleft()
        self.folios[slot]=folio
        self.set_status(slot,'OCUPADO','IMSS y Outlook preparados con una misma cuenta')
        override=self.allow_manual[slot];self.allow_manual[slot]=False
        pin=self.pin_var.get() if self.use_pin.get() else ''
        self.active_outlook=True;self.active_outlook_slot=slot
        self.stop_outlook=threading.Event()
        self.update_count();self.update_pool_label()
        self.log(f'Android {slot+1} solicitud #{reqid}: correo reservado; iniciando ambos bots.')
        self.executor.submit(self.login_worker,slot,reqid,curp,email,override,pin,self.stop_outlook,folio)

    def login_worker(self,slot,reqid,curp,email,override,pin,stop,folio):
        estado,detalle,folio_s,terminado=tramitar_con_outlook(
            self.adb,self.serials[slot],curp,email,pin,override,
            update=lambda msg:self.send('status',slot,'OCUPADO',msg),
            stop=stop,puente=self.puente,folio_id=folio)
        self.send('bridge_result',slot,reqid,estado,detalle,folio_s,terminado)
        del pin

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
                    # Nunca liberar al Android mientras esté vinculado a un correo.
                    if self.folios[slot]:ok=False;detail='Correo todavía vinculado; finaliza el trámite primero.'
                    self.allow_manual[slot]=False
                    self.set_status(slot,'LIBRE' if ok else 'REVISAR',detail)
                elif action=='manual_check':
                    i,serial=args
                    if not self.folios[i] and foreground(self.adb,serial) is True:
                        if messagebox.askyesno('Confirmar inicio',f'Android {i+1}: ¿ves CURP y correo en IMSS?'):
                            self.allow_manual[i]=True
                            self.set_status(i,'LIBRE','Inicio confirmado por operador')
                elif action=='finish':self.working=False
                elif action=='outlook_state':self.status_outlook.configure(text=args[0])
                elif action=='outlook_available':
                    self.outlook_can_start=bool(args[0])
                    if not self.outlook_can_start:
                        self.status_outlook.configure(text='OUTLOOK: preparando o en enfriamiento · cola espera')
                elif action=='bridge_result':
                    slot,reqid,estado,detalle,folio,terminado=args
                    self.set_status(slot,estado,detalle)
                    self.log(f'Android {slot+1} solicitud #{reqid}: {estado} (sin datos privados).')
                    if terminado or not folio:
                        self.active_outlook=None;self.active_outlook_slot=None
                        self.status_outlook.configure(text='OUTLOOK: listo para otra solicitud')
                        if not folio and self.folios[slot]:self.pool.review(self.folios[slot])
                    else:
                        self.active_outlook=folio
                        self.status_outlook.configure(text='OUTLOOK: solicitud retenida para revisión')
                        if folio:self.pool.review(folio)
                    self.update_count()
                elif action=='release_done':
                    slot,ok=args
                    if ok:
                        self.active_outlook=None;self.active_outlook_slot=None
                        self.status_outlook.configure(text='OUTLOOK: enlace liberado')
                        self.log('Enlace Outlook liberado; el correo sigue retenido hasta entregar el reporte.')
                    else:self.log('No se pudo liberar Outlook; revisión necesaria.')
                elif action=='reset_v14':
                    slot,estado,detalle,error=args
                    if estado=='LIBRE' and not error:
                        self.folios[slot]=None
                        self.set_status(slot,'LIBRE','PDF confirmado · correo eliminado · IMSS en inicio')
                        self.log(f'Android {slot+1}: reporte confirmado; correo retirado y secreto eliminado.')
                    else:
                        self.set_status(slot,'REVISAR',detalle or 'No se confirmó retorno a inicio')
                        self.log(f'Android {slot+1}: no se eliminó el correo. Revisar para evitar perder credenciales.')
                    self.reset_in_progress.discard(slot)
                elif action=='watchdog_v14':
                    slot,ok,details=args
                    if ok:
                        self.set_status(slot,'REVISAR' if self.folios[slot] else 'LIBRE',details)
                        self.log(f'Android {slot+1}: regresó al escritorio, IMSS se abrió automáticamente.')
                    else:
                        self.set_status(slot,'REVISAR',details)
                else:pass
        except queue.Empty:pass
        self.update_pool_label()
        self.dispatch()
        self.root.after(450,self.pump)

    def ask_to_reset(self,i):
        if not self.serials[i]:
            messagebox.showinfo('ADB', 'Android no conectado');return
        if i in self.reset_in_progress or self.states[i]=='OCUPADO':
            messagebox.showwarning('Ocupado','Espera a que termine la operación o la validación.');return
        folio=self.folios[i]
        if not folio:
            messagebox.showinfo('Sin correo','Esta instancia no tiene correo asignado; usa COMPROBAR SI ESTÁ LIBRE.');return
        if not messagebox.askyesno('Confirmar PDF y eliminación',
            f'¿Confirmas que el PDF correcto del trámite en Android {i+1} YA fue recibido/verificado?\n\n'
            'Sólo cuando el Android regrese al inicio, se ELIMINARÁ de la lista V14 '
            'el correo usado y su contraseña cifrada. La cuenta Microsoft real no se borrará.'):
            return
        self.reset_in_progress.add(i)
        self.set_status(i,'OCUPADO','Comprobando retorno a la pantalla inicial')
        threading.Thread(target=self.reset_worker_v14,args=(i,self.serials[i],folio),daemon=True).start()

    def reset_worker_v14(self,i,serial,folio):
        from validacion_pin import return_to_login
        try:
            estado,detalle=return_to_login(self.adb,serial,update=lambda msg:self.send('status',i,'OCUPADO',msg))
            if estado=='LIBRE':
                used=self.pool.consume(folio)  # Idempotente si V31 ya retiró la cuenta al confirmar OTP.
                if used:
                    try:
                        from credenciales import Vault
                        Vault(path=VAULT_DB).remove(used)
                    except Exception:
                        self.send('log','AVISO: correo retirado; revisar limpieza del secreto local.')
                self.send('reset_v14',i,'LIBRE',detalle,False)
            else:
                self.pool.review(folio)
                self.send('reset_v14',i,'REVISAR',detalle,True)
        except Exception:
            try:self.pool.review(folio)
            except Exception:pass
            self.send('reset_v14',i,'REVISAR','Falló la vuelta a inicio. No se eliminó la cuenta.',True)

    @staticmethod
    def is_ldplayer_home(adb,serial):
        """Reabrir sólo si Android CONFIRMA que está en un launcher, nunca en un diálogo."""
        rc,out=adb_run(adb,serial,'shell','dumpsys','window','windows',timeout=8)
        if rc:return False
        # Priorizar mCurrentFocus para no confundir otras actividades en segundo plano.
        lines=[line.lower() for line in out.splitlines() if 'mcurrentfocus' in line.lower()]
        if not lines:return False
        focus=lines[-1]
        return ('launcher' in focus or 'ldmnq' in focus) and 'st.android.imsspublico' not in focus

    def watch_loop(self):
        while not self.monitor_stop.wait(3):
            if not self.adb or self.working:continue
            for i,serial in enumerate(list(self.serials)):
                if self.monitor_stop.is_set():return
                if not serial or i in self.reset_in_progress or self.states[i] in ('OCUPADO','ABRIENDO','BUSCANDO'):
                    continue
                try:
                    if not self.is_ldplayer_home(self.adb,serial):continue
                    previous=self.states[i]
                    self.send('status',i,'ABRIENDO','El emulador regresó al inicio; abriendo IMSS Digital')
                    label,detail=launch_imss(self.adb,serial,lambda _s:None)
                    ok=label=='ABIERTA'
                    if ok and not self.folios[i]:
                        try:ok=login_detected(quick_ui(self.adb,serial))
                        except Exception:ok=False
                    self.send('watchdog_v14',i,ok,
                         ('IMSS reabierto; solicitud previa pendiente' if self.folios[i] else
                          'IMSS Digital de nuevo en pantalla inicial') if ok else 'No pudo confirmarse IMSS; revisar Android')
                except Exception:self.send('watchdog_v14',i,False,'No se pudo comprobar la pantalla de inicio')

    def close(self):
        self.monitor_stop.set()
        super().close()

def main():
    root=tk.Tk();PanelV14(root);root.mainloop()
if __name__=='__main__':main()
