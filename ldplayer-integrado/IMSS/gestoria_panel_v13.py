# -*- coding: utf-8 -*-
"""V13: panel IMSS V12 intacto, con puente Outlook V15.2."""
from __future__ import annotations
import queue
import threading
import tkinter as tk
from tkinter import messagebox
from gestoria_panel_v12 import PanelV12
from gestoria_paso1_v8 import GREEN, GOLD, FG
from puente_imss_outlook_v13 import PuenteOutlook, tramitar_con_outlook


class PanelV13(PanelV12):
    def __init__(self, root):
        super().__init__(root)
        root.title('GESTORÍA DÍAZ · IMSS V13 + OUTLOOK V15.2')
        self.puente=PuenteOutlook()
        self.active_outlook=None
        self.active_outlook_slot=None
        self.stop_outlook=threading.Event()
        self.connect_btn.configure(text='1. CONECTAR + ABRIR IMSS (BASE V7/V12)')
        self.add_btn.configure(text='2. TRAMITAR CON OUTLOOK (COLA SEGURA)')
        self.outlook_button=tk.Button(self.connect_btn.master,text='PROBAR OUTLOOK',command=self.test_outlook,
                bg='#343842',fg=FG,font=('Segoe UI',9,'bold'),bd=0,pady=12)
        self.outlook_button.pack(side='left',padx=(3,4))
        self.status_outlook=tk.Label(root,text='OUTLOOK: sin comprobar | máximo 1 código simultáneo',
                  bg='#111215',fg=GOLD,font=('Segoe UI',9,'bold'))
        self.status_outlook.pack(anchor='w',padx=20,before=self.add_btn.master)
        # Recuperación manual si IMSS no confirma que tomó el OTP.
        menu=root.nametowidget(root['menu'])
        submenu=tk.Menu(menu,tearoff=False)
        submenu.add_command(label='Detener búsqueda actual del código',command=self.detener_espera)
        submenu.add_command(label='Cancelar enlace Outlook actual (requiere confirmación)',command=self.cancel_current)
        submenu.add_command(label='Confirmar código aceptado y liberar Outlook',command=self.complete_current)
        menu.add_cascade(label='Enlace Outlook',menu=submenu)
        self.log('V13: enlaza con Outlook V15.2 mediante localhost. Solo un OTP a la vez.')
        self.log('El paso 1 y la apertura IMSS siguen siendo los archivos originales de V12/V7.')

    def test_outlook(self):
        def worker():
            try:
                answer=self.puente.comprobar()
                self.send('outlook_state','OUTLOOK CONECTADO · '+('listo' if answer.get('available') else 'ocupado'))
            except Exception:
                self.send('outlook_state','OUTLOOK NO CONECTADO · abre OUTLOOK V15.2 primero')
        threading.Thread(target=worker,daemon=True).start()

    def dispatch(self):
        # V15.2 dispone de una sola reserva activa: nunca iniciar dos códigos a la vez.
        if self.working or self.active_outlook is not None or not self.pending:return
        slot=next((i for i,s in enumerate(self.states) if s=='LIBRE' and self.serials[i]),None)
        if slot is None:return
        reqid,curp,email=self.pending.popleft()
        self.set_status(slot,'OCUPADO','Conectando con Outlook antes de iniciar sesión')
        allow=self.allow_manual[slot]
        self.allow_manual[slot]=False
        pin=self.pin_var.get() if self.use_pin.get() else ''
        self.active_outlook=True
        self.active_outlook_slot=slot
        self.stop_outlook=threading.Event()
        self.update_count()
        self.log(f'Solicitud #{reqid} asignada a Android {slot+1}. Enlace único Outlook.')
        self.executor.submit(self.login_worker,slot,reqid,curp,email,allow,pin,self.stop_outlook)

    def login_worker(self,slot,reqid,curp,email,override,pin,stop):
        estado,detalle,folio,terminado=tramitar_con_outlook(
            self.adb,self.serials[slot],curp,email,pin,override,
            update=lambda msg:self.send('status',slot,'OCUPADO',msg),
            stop=stop,puente=self.puente)
        # No transmitir CURP/correo/PIN/OTP en los eventos de UI ni al registro.
        self.send('bridge_result',slot,reqid,estado,detalle,folio,terminado)
        del pin

    def pump(self):
        """Misma cola de Tk de la V8, ampliada con eventos del puente."""
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
                    self.allow_manual[slot]=False
                    self.set_status(slot,'LIBRE' if ok else 'REVISAR',detail)
                elif action=='manual_check':
                    i,serial=args
                    # Fallback visual de la V8, sin modificar el código fuente.
                    from gestoria_prueba_v7 import foreground
                    if foreground(self.adb,serial) is True:
                        if messagebox.askyesno('Confirmar pantalla inicial',
                            f'Android {i+1}: ¿ves la pantalla de CURP y correo de IMSS Digital?'):
                            self.allow_manual[i]=True
                            self.set_status(i,'LIBRE','Inicio confirmado por operador')
                elif action=='finish':self.working=False
                elif action=='outlook_state':self.status_outlook.configure(text=args[0])
                elif action=='bridge_result':
                    slot,reqid,estado,detalle,folio,terminado=args
                    self.set_status(slot,estado,detalle)
                    self.log(f'Android {slot+1} · solicitud #{reqid}: {estado}. Sin datos privados.')
                    if terminado or not folio:
                        self.active_outlook=None
                        self.active_outlook_slot=None
                        self.status_outlook.configure(text='OUTLOOK: disponible para siguiente solicitud')
                    else:
                        self.active_outlook=folio
                        self.status_outlook.configure(text='OUTLOOK: solicitud reservada · revisa antes de liberar')
                    self.update_count()
                elif action=='release_done':
                    slot,ok=args
                    if ok:
                        self.active_outlook=None
                        self.active_outlook_slot=None
                        self.status_outlook.configure(text='OUTLOOK: enlace liberado')
                        self.log('Enlace Outlook liberado tras confirmación. No cambia el estado de Android.')
                    else:self.log('No fue posible liberar Outlook; revisa el panel del correo.')
        except queue.Empty:pass
        self.dispatch()
        self.root.after(140,self.pump)

    def _finish_manually(self, done):
        if not isinstance(self.active_outlook,str):
            messagebox.showinfo('Sin solicitud','No hay un folio Outlook pendiente de liberar.')
            return
        prompt=('¿Confirmas que el código fue aceptado por IMSS Digital? '
                'Esta acción permite iniciar la siguiente consulta de correo.' if done
                else '¿Cancelar la solicitud de Outlook actual? Si IMSS espera un código, tendrás que revisar ese trámite manualmente.')
        if not messagebox.askyesno('Confirmar',prompt):return
        folio=self.active_outlook
        self.stop_outlook.set()
        def worker():
            try:
                if done:
                    self.puente.confirmar_recepcion(folio)
                    self.puente.terminar_enlace(folio)
                else:self.puente.cancelar(folio)
                self.send('release_done',self.active_outlook_slot,True)
            except Exception:self.send('release_done',self.active_outlook_slot,False)
        threading.Thread(target=worker,daemon=True).start()

    def detener_espera(self):
        if self.active_outlook is None:
            messagebox.showinfo('Sin espera','No hay ninguna solicitud Outlook en curso.')
            return
        self.stop_outlook.set()
        messagebox.showinfo('Detención solicitada','La búsqueda se detendrá sin reiniciar el emulador. Cuando el panel indique revisión, podrás cancelar el enlace desde este menú.')

    def cancel_current(self):self._finish_manually(False)
    def complete_current(self):self._finish_manually(True)

    def close(self):
        # No cancela automáticamente una sesión Outlook abierta en el otro programa.
        self.stop_outlook.set()
        super().close()


def main():
    root=tk.Tk()
    PanelV13(root)
    root.mainloop()
if __name__=='__main__':main()
