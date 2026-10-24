# -*- coding: utf-8 -*-
"""V15: PIN local cifrado + Outlook confirma bandeja ANTES de iniciar IMSS."""
import threading,time,uuid,tkinter as tk
from tkinter import messagebox
from gestoria_panel_v14 import PanelV14
from preparacion_v15 import Preparation
from pin_protegido_v15 import save_pin,read_pin,delete_pin
from puente_imss_outlook_v14 import tramitar_con_outlook

MAX_CUENTAS_POR_SOLICITUD=3

class PanelV15(PanelV14):
    def __init__(self,root):
        super().__init__(root)
        self.preparacion=Preparation()
        root.title('GESTORÍA DÍAZ · IMSS V16 · INGRESO VERIFICADO')
        self.add_btn.configure(text='2. SOLICITAR · OUTLOOK PRIMERO, IMSS DESPUÉS')
        self.connect_btn.configure(text='1. CONECTAR Y ABRIR IMSS (V7 INTACTA)')
        try:
            recovered=read_pin()
            if recovered:self.pin_var.set(recovered)
        except Exception:self.log('No pudo restaurarse el PIN cifrado; vuelve a guardarlo.')
        bar=self.pin_entry.master
        tk.Button(bar,text='GUARDAR PIN EN WINDOWS',command=self.persist_pin,
                  bg='#e4b650',fg='#111215',bd=0,padx=9,pady=7).pack(side='left',padx=(4,7))
        tk.Button(bar,text='OLVIDAR PIN',command=self.forget_pin,
                  bg='#333842',fg='#fff',bd=0,padx=9,pady=7).pack(side='left')
        self.log('V15: el PIN se cifra con Windows DPAPI; nunca se registra ni va al enlace Outlook.')
        self.log('Outlook comprueba bandeja antes de enviar CURP y correo a IMSS.')
        self.log('V16: sin borrados innecesarios; verifica CURP y correo antes de Iniciar sesión.')
    def persist_pin(self):
        try:
            save_pin(self.pin_var.get())
            messagebox.showinfo('PIN protegido','PIN guardado cifrado para tu usuario de Windows.')
        except Exception as e:messagebox.showerror('PIN','No se pudo guardar el PIN: '+type(e).__name__)
    def forget_pin(self):
        try:delete_pin();self.pin_var.set('');self.log('PIN cifrado eliminado de Windows.')
        except Exception:messagebox.showerror('PIN','No se pudo eliminar el PIN guardado.')
    def dispatch(self):
        if (self.working or self.active_outlook is not None or not self.pending or
            not self.outlook_can_start):return
        if not self.preparacion.live():
            return  # Esperar a OUTLOOK V15 real; no hablar con una versión anterior.
        slot=next((i for i,s in enumerate(self.states) if s=='LIBRE' and self.serials[i]),None)
        if slot is None:return
        folio=uuid.uuid4().hex
        try:email=self.pool.reserve(folio)
        except Exception:self.log('No pudo reservarse un correo.');return
        if not email:return
        try:self.preparacion.create(folio,email)
        except Exception:
            self.pool.review(folio);self.log('No pudo prepararse Outlook; cuenta para revisión.');return
        reqid,curp,_=self.pending.popleft()
        self.folios[slot]=folio
        self.set_status(slot,'OCUPADO','Outlook primero: esperando acceso real a bandeja')
        override=self.allow_manual[slot];self.allow_manual[slot]=False
        pin=self.pin_var.get() if self.use_pin.get() else ''
        self.active_outlook=True;self.active_outlook_slot=slot
        self.stop_outlook=threading.Event()
        self.update_count();self.update_pool_label()
        self.log(f'Android {slot+1} solicitud #{reqid}: esperando que Outlook confirme su bandeja.')
        self.executor.submit(self.login_worker,slot,reqid,curp,email,override,pin,self.stop_outlook,folio)
    def login_worker(self,slot,reqid,curp,email,override,pin,stop,folio):
        chosen_email=email;chosen_folio=folio
        try:
            for attempt in range(MAX_CUENTAS_POR_SOLICITUD):
                deadline=time.monotonic()+190
                stage=None
                while time.monotonic()<deadline and not stop.is_set():
                    info=self.preparacion.status(chosen_folio)
                    stage=info['estado'] if info else 'REVISAR'
                    if stage in ('LISTO','BLOQUEADA','REVISAR','LIMITE_MICROSOFT'):break
                    stop.wait(1.25)
                if stop.is_set():break
                if stage=='LISTO':
                    self.send('status',slot,'OCUPADO','Bandeja Outlook comprobada; iniciando IMSS Digital')
                    estado,detalle,fol,fin=tramitar_con_outlook(
                        self.adb,self.serials[slot],curp,chosen_email,pin,override,
                        update=lambda msg:self.send('status',slot,'OCUPADO',msg),
                        stop=stop,puente=self.puente,folio_id=chosen_folio)
                    self.send('bridge_result',slot,reqid,estado,detalle,fol,fin)
                    return
                if stage=='LIMITE_MICROSOFT':
                    self.pool.review(chosen_folio)
                    self.folios[slot]=None
                    self.send('bridge_result',slot,reqid,'REVISAR',
                       'Microsoft limitó solicitudes: detenido sin cambiar de cuenta.',None,True)
                    return
                # Cuenta bloqueada/inaccesible: dejarla en REVISAR. Ningún intento
                # adicional contra ella ni método para eludir MFA/429.
                self.pool.review(chosen_folio)
                self.preparacion.finish(chosen_folio)
                if stage!='BLOQUEADA':
                    self.folios[slot]=None
                    self.send('bridge_result',slot,reqid,'REVISAR',
                         'No se confirmó bandeja Outlook; requiere revisión manual.',None,True)
                    return
                if attempt+1>=MAX_CUENTAS_POR_SOLICITUD:break
                next_folio=uuid.uuid4().hex
                next_email=self.pool.reserve(next_folio)
                if not next_email:break
                try:self.preparacion.create(next_folio,next_email)
                except Exception:self.pool.review(next_folio);break
                chosen_email,chosen_folio=next_email,next_folio
                self.folios[slot]=next_folio
                self.send('status',slot,'OCUPADO',f'Cuenta anterior bloqueada; comprobando alternativa autorizada {attempt+2}/{MAX_CUENTAS_POR_SOLICITUD}')
            self.folios[slot]=None
            self.send('bridge_result',slot,reqid,'REVISAR',
               'No se encontró bandeja disponible; revisa los bloqueos de Microsoft.',None,True)
        except Exception as exc:
            self.pool.review(chosen_folio)
            self.folios[slot]=None
            self.send('bridge_result',slot,reqid,'REVISAR',
                'Error durante preparación de Outlook ('+type(exc).__name__+').',None,True)
        finally:
            # No guardar nunca PIN ni CURP en registros, TXT ni cola compartida.
            del pin

def main():
    root=tk.Tk();PanelV15(root);root.mainloop()
if __name__=='__main__':main()
