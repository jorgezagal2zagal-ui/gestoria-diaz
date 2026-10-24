# -*- coding: utf-8 -*-
"""V12: conectar y abrir IMSS con un solo botón. No modifica la base V7."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import tkinter as tk
from tkinter import messagebox
from gestoria_panel_v11 import PanelV11
from gestoria_prueba_v7 import (locate_adb,process,adb_run,devices_from_output,
                                 launch_imss,foreground)
from gestoria_prueba_v23 import select_serials, MAX_ANDROID
from imss_flujo_v11 import quick_ui
from imss_flujo_v12 import step_flow_v12
from imss_paso1 import login_detected
from validacion_pin import pin_prompt,waiting_email_code

class PanelV12(PanelV11):
    def __init__(self,root):
        super().__init__(root)
        root.title('GESTORÍA DÍAZ · IMSS DIGITAL V12 · INICIO AUTOMÁTICO + RÁPIDO')
        self.connect_btn.configure(text='1. CONECTAR + ABRIR IMSS EN LOS 4')
        # El botón antiguo no es necesario; en V12 conectar también abre.
        self.open_btn.pack_forget()
        self.add_btn.configure(text='2. ENVIAR SOLICITUD AL ANDROID LIBRE / COLA')
        for child in root.winfo_children():
            if isinstance(child,tk.Frame):
                for elem in child.winfo_children():
                    if isinstance(elem,tk.Label) and 'IMSS DIGITAL' in elem.cget('text') and 'LDPLAYER' in elem.cget('text'):
                        elem.configure(text='IMSS DIGITAL · 4 EMULADORES · V12 INICIO AUTOMÁTICO')
        self.log('V12: conectar abre IMSS sin segundo botón; entrada agrupada para mayor velocidad.')
        self.log('Si una instancia está en verificación, no se reinicia su aplicación.')

    def connect(self):
        if self.working: return
        if any(s in ('OCUPADO','ESPERANDO CÓDIGO','ESPERANDO PIN',
                     'VALIDACIÓN EN CURSO') for s in self.states):
            messagebox.showwarning('Trámite en curso',
                'Finaliza la verificación antes de volver a conectar los Android.')
            return
        self.working=True
        for i in range(MAX_ANDROID): self.set_status(i,'BUSCANDO','Conectando ADB y abriendo IMSS')
        threading.Thread(target=self.connect_worker,daemon=True).start()

    @staticmethod
    def start_and_assess(adb, serial, update=lambda msg:None):
        """La función de apertura es EXACTAMENTE launch_imss de la V7."""
        rc,out=adb_run(adb,serial,'shell','echo','GESTORIA_OK',timeout=10)
        if rc or 'GESTORIA_OK' not in out:
            return 'REVISAR','ADB no respondió en esta instancia.'
        front=foreground(adb,serial)
        if front is True:
            update('IMSS ya estaba abierto; se conserva esa pantalla')
        elif front is False:
            update('Abriendo IMSS Digital automáticamente (V7)')
            label,detail=launch_imss(adb,serial,lambda _:None)
            if label!='ABIERTA':
                return 'REVISAR',detail
        else:
            return 'REVISAR','ADB no pudo confirmar app activa; no se reinició ninguna verificación.'
        # Un emulador solo queda LIBRE si expone la pantalla inicial.
        try: nodes=quick_ui(adb,serial)
        except Exception:
            return 'REVISAR','IMSS abierto, pero no se pudo comprobar el formulario inicial.'
        if login_detected(nodes):
            return 'LIBRE',f'{serial} · IMSS Digital abierto, CURP y correo listos.'
        if pin_prompt(nodes):
            return 'ESPERANDO PIN', f'{serial} · PIN del dispositivo pendiente; no se interrumpió.'
        if waiting_email_code(nodes):
            return 'ESPERANDO CÓDIGO', f'{serial} · Código de correo pendiente; no se interrumpió.'
        return 'REVISAR',f'{serial} · IMSS abierto; pantalla distinta al inicio.'

    def connect_worker(self):
        try:
            adb=locate_adb()
            if not adb: raise RuntimeError('No se encontró adb.exe de LDPlayer. Revisa la carpeta instalada.')
            rc,_=process([adb,'start-server'],timeout=18)
            if rc: raise RuntimeError('ADB no pudo iniciarse.')
            rc,out=process([adb,'devices','-l'],timeout=18)
            if rc: raise RuntimeError('ADB no pudo leer los emuladores.')
            selected=select_serials(devices_from_output(out))
            if len(selected)<MAX_ANDROID:
                # Igual que la V8: intentar puertos locales en lugar de ignorar emuladores.
                for idx in range(MAX_ANDROID):
                    if idx not in [n for n,_ in selected]:
                        try:process([adb,'connect',f'127.0.0.1:{5555+idx*2}'],timeout=7)
                        except Exception:pass
                rc,out=process([adb,'devices','-l'],timeout=15)
                if rc==0: selected=select_serials(devices_from_output(out))
            serials=[None]*MAX_ANDROID
            assessments=[('SIN CONEXIÓN','No se detectó un emulador activo') for _ in range(MAX_ANDROID)]
            # Los 4 arrancan en paralelo tan pronto ADB los enumera.
            with ThreadPoolExecutor(max_workers=MAX_ANDROID) as pool:
                tasks={}
                for slot,(_,serial) in enumerate(selected[:MAX_ANDROID]):
                    serials[slot]=serial
                    def progress(txt,s=slot): self.send('status',s,'ABRIENDO',txt)
                    tasks[pool.submit(self.start_and_assess,adb,serial,progress)]=slot
                for task in as_completed(tasks):
                    slot=tasks[task]
                    try: assessments[slot]=task.result()
                    except Exception:
                        assessments[slot]=('REVISAR','Error al comprobar apertura; revisa IMSS Digital.')
            self.send('attached',adb,serials,assessments)
            ready=sum(status=='LIBRE' for status,_ in assessments)
            self.send('log',f'V12: ADB {sum(bool(x) for x in serials)}/{MAX_ANDROID} · IMSS inicial {ready}/{MAX_ANDROID}.')
        except Exception as exc:
            self.send('log','Error conectando/abriendo: '+str(exc)[:160])
            for i in range(MAX_ANDROID): self.send('status',i,'REVISAR','Verifica ADB y emuladores encendidos')
            self.send('finish')

    def login_worker(self,slot,reqid,curp,email,override,pin):
        try:
            status,detail=step_flow_v12(self.adb,self.serials[slot],curp,email,pin,
                ready_confirmed_by_operator=override,
                update=lambda text:self.send('status',slot,'OCUPADO',text))
        except Exception:
            status,detail='REVISAR','No terminó el paso. Revisa la pantalla del emulador.'
        self.send('work_result',slot,status,detail)
        self.send('log',f'Android {slot+1} · solicitud #{reqid}: {status} (sin datos privados).')
        del pin

def main():
    root=tk.Tk();PanelV12(root);root.mainloop()
if __name__=='__main__':main()
