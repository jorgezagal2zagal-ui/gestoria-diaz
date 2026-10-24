# -*- coding: utf-8 -*-
"""Gestoría Díaz V10 - Mantiene V7 y V8 sin cambios.
Amplía paso 1 con PIN del dispositivo (en memoria) y retorno asistido al inicio.
"""
from __future__ import annotations
import re
import threading
import tkinter as tk
from tkinter import messagebox
from gestoria_paso1_v8 import Panel, GOLD, BG, PANEL, FG, GREEN, BLUE, RED
from imss_paso1 import do_login
from validacion_pin import enter_pin_once, return_to_login


class PanelV9(Panel):
    def __init__(self, root):
        super().__init__(root)
        root.title('GESTORÍA DÍAZ · IMSS DIGITAL · PIN + ENTER V10')
        root.geometry('1040x865'); root.minsize(870,760)
        self.pin_var=tk.StringVar()
        self.use_pin=tk.BooleanVar(value=True)
        self.pin_var.trace_add('write', self.filter_pin)
        # Fila de seguridad dentro del formulario existente; no modifica V8 ni V7.
        form=self.add_btn.master
        row=tk.Frame(form,bg=PANEL)
        row.pack(fill='x',pady=(6,8),before=self.add_btn)
        tk.Label(row,text='PIN de los 4 Android (solo en memoria)',bg=PANEL,fg=FG).pack(side='left',padx=(0,12))
        self.pin_entry=tk.Entry(row,textvariable=self.pin_var,show='●',width=12,bg='#eae9e5',fg='#181818',bd=0,font=('Segoe UI',12))
        self.pin_entry.pack(side='left',ipady=5,padx=(0,10))
        tk.Checkbutton(row,text='Validar PIN automáticamente cuando se detecte su pantalla',
                       variable=self.use_pin,bg=PANEL,fg=FG,selectcolor=PANEL,
                       activebackground=PANEL,activeforeground=FG,bd=0).pack(side='left')
        tk.Button(row,text='Borrar PIN',command=lambda:self.pin_var.set(''),
                  bg='#343842',fg=FG,bd=0,padx=8,pady=6).pack(side='right')
        for i, s in enumerate(self.status_labels):
            card=s.master
            tk.Button(card,text='FINALIZAR Y VOLVER AL INICIO',
                      command=lambda j=i:self.ask_to_reset(j),
                      bg='#343842',fg=FG,activebackground=GOLD,bd=0,
                      font=('Segoe UI',8,'bold'),padx=8,pady=6).pack(fill='x',pady=(3,0))
        # Cambio visual para distinguir la versión; el núcleo funcional V7/V8 se mantiene.
        for child in root.winfo_children():
            if isinstance(child,tk.Frame) and child.winfo_children():
                for label in child.winfo_children():
                    if isinstance(label,tk.Label) and 'PRUEBA PASO 1 V8' in label.cget('text'):
                        label.configure(text='IMSS DIGITAL · 4 LDPLAYER · PRUEBA PIN + ENTER V10')
                        break
        self.log('V10: confirmacion Enter tras PIN; nucleo V7 y primer paso V8 intactos.')
        self.log('V10 NO lee correos/OTP ni genera PDFs. No guarda PIN o datos personales.')

    def filter_pin(self,*_):
        val=self.pin_var.get()
        sanitized=re.sub(r'\D','',val)[:8]
        if val!=sanitized: self.pin_var.set(sanitized)

    def set_status(self,i,status,detail):
        super().set_status(i,status,detail)
        if status in ('ESPERANDO PIN','VALIDACIÓN EN CURSO','ESPERANDO CÓDIGO'):
            self.status_labels[i].configure(fg=BLUE)

    def dispatch(self):
        # Misma lógica de cola V8, capturando PIN al asignar cada solicitud.
        if self.working: return
        while self.pending:
            slot=next((i for i,s in enumerate(self.states) if s=='LIBRE' and self.serials[i]),None)
            if slot is None: break
            reqid,curp,email=self.pending.popleft()
            self.set_status(slot,'OCUPADO','Ingresando CURP, correo y aviso')
            allow=self.allow_manual[slot]
            self.allow_manual[slot]=False
            pin=self.pin_var.get() if self.use_pin.get() else ''
            self.log(f'Solicitud #{reqid} asignada a Android {slot+1}.')
            self.update_count()
            self.executor.submit(self.login_worker,slot,reqid,curp,email,allow,pin)

    def login_worker(self,slot,reqid,curp,email,override,pin):
        try:
            state,detail=do_login(self.adb,self.serials[slot],curp,email,
                         ready_confirmed_by_operator=override,
                         update=lambda txt:self.send('status',slot,'OCUPADO',txt))
            if state=='ESPERANDO CÓDIGO':
                # Este estado V8 también cubre el PIN del dispositivo. Detectarlo antes.
                state,detail=enter_pin_once(self.adb,self.serials[slot],pin,
                           update=lambda txt:self.send('status',slot,'OCUPADO',txt))
        except Exception:
            state,detail='REVISAR','No terminó la etapa. Revisa la pantalla del emulador.'
        self.send('work_result',slot,state,detail)
        self.send('log',f'Android {slot+1} · solicitud #{reqid}: {state} (sin datos privados).')
        # La referencia local a PIN se deja fuera de registros y archivos.
        del pin

    def ask_to_reset(self,i):
        if not self.serials[i]:
            messagebox.showinfo('Sin ADB',f'Android {i+1} no está conectado.'); return
        if self.states[i]=='OCUPADO':
            messagebox.showwarning('En ejecución','No interrumpas una operación en curso.');return
        if not messagebox.askyesno('Confirmar trámite completado',
                     f'¿Terminó el trámite en Android {i+1} y ya obtuviste/verificaste el PDF?\n\n'
                     'Intentaré regresar a la pantalla CURP y correo sin borrar datos ni cerrar LDPlayer.'):
            return
        self.set_status(i,'OCUPADO','Volviendo a la pantalla inicial')
        threading.Thread(target=self.reset_worker,args=(i,self.serials[i]),daemon=True).start()

    def reset_worker(self,i,serial):
        try:
            state,detail=return_to_login(self.adb,serial,
                                 update=lambda msg:self.send('status',i,'OCUPADO',msg))
        except Exception:
            state,detail='REVISAR','No se pudo confirmar pantalla inicial.'
        self.send('work_result',i,state,detail)
        self.send('log',f'Android {i+1}: retorno -> {state}.')

    def close(self):
        self.pin_var.set('')
        super().close()


def main():
    root=tk.Tk()
    PanelV9(root)
    root.mainloop()

if __name__=='__main__':
    main()
