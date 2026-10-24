# -*- coding: utf-8 -*-
"""Panel V11: conserva conexión/apertura V7 y panel V8/V10 sin modificarlos."""
from __future__ import annotations
import tkinter as tk
from gestoria_paso2_v9 import PanelV9
from imss_flujo_v11 import step_flow

class PanelV11(PanelV9):
    def __init__(self,root):
        super().__init__(root)
        root.title('GESTORÍA DÍAZ · IMSS DIGITAL V11 · CONFIRMAR + RÁPIDO')
        for child in root.winfo_children():
            if isinstance(child,tk.Frame):
                for label in child.winfo_children():
                    if isinstance(label,tk.Label) and 'PRUEBA PIN + ENTER V10' in label.cget('text'):
                        label.configure(text='IMSS DIGITAL · 4 LDPLAYER · V11 CONFIRMAR CORREO')
        self.log('V11: confirma aviso de correo, reduce borrados y consultas repetidas. V7/V8/V10 intactos.')
    def login_worker(self,slot,reqid,curp,email,override,pin):
        try:
            state,detail=step_flow(self.adb,self.serials[slot],curp,email,pin,
                        ready_confirmed_by_operator=override,
                        update=lambda txt:self.send('status',slot,'OCUPADO',txt))
        except Exception:
            state,detail='REVISAR','No terminó la etapa. Revisa la pantalla del emulador.'
        self.send('work_result',slot,state,detail)
        self.send('log',f'Android {slot+1} · solicitud #{reqid}: {state} (sin datos privados).')
        del pin

def main():
    root=tk.Tk();PanelV11(root);root.mainloop()
if __name__=='__main__': main()
