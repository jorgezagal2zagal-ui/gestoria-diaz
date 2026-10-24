# -*- coding: utf-8 -*-
"""Panel V22: recupera Android únicamente cuando IMSS está en su inicio.

La validación del correo, apertura ADB V7 y lógica de trámites V20 quedan sin tocar.
"""
import threading
import tkinter as tk
from gestoria_panel_v20 import PanelV20
from gestoria_paso1_v8 import GOLD
from recuperacion_v22 import can_recover
from imss_paso1 import login_detected
from imss_flujo_v11 import quick_ui

class PanelV22(PanelV20):
    def __init__(self,root):
        super().__init__(root)
        self.root.title('GESTORÍA DÍAZ · IMSS V22 · ESTADO Y RECUPERACIÓN')
        self.queue_explain=tk.StringVar(value='Comprobando estado de la cola…')
        self._recovery_busy=set()
        self._last_explain=None
        tk.Label(root,textvariable=self.queue_explain,bg='#111215',fg=GOLD,
                 font=('Segoe UI',10,'bold'),wraplength=820,justify='left').pack(
                 anchor='w',padx=20,before=self.add_btn.master)
        self.root.after(1800,self._update_queue_explain)
        threading.Thread(target=self._recovery_poll,daemon=True).start()
        self.log('V22: si NO hay CURP en cola, Outlook espera correctamente; no es una falla.')
        self.log('V22: recuperación de Android en REVISAR solo si no tiene folio y se comprueba inicio IMSS.')

    def _update_queue_explain(self):
        if self.monitor_stop.is_set():return
        count=len(self.pending)
        held=sum(1 for s in self.states if s=='REVISAR')
        available=sum(1 for s in self.states if s=='LIBRE')
        if not count:
            msg=f'SIN SOLICITUDES NUEVAS · {available} Android libres, {held} en revisión. Para continuar ingresa otra CURP autorizada.'
        elif self.active_outlook is not None:
            msg=f'EN PROCESO · {count} CURP en cola; Outlook atiende una solicitud. No se asigna otro correo hasta resolverla.'
        elif not self.outlook_can_start:
            msg=f'EN ESPERA DE OUTLOOK · {count} CURP en cola. Revisa que Outlook esté disponible; no cambia cuentas para superar bloqueos.'
        else:
            msg=f'LISTO PARA ASIGNAR · {count} CURP en cola y {available} Android libres.'
        self.queue_explain.set(msg)
        self.root.after(1800,self._update_queue_explain)

    def _recovery_poll(self):
        while not self.monitor_stop.wait(10):
            if not self.adb:continue
            for i,serial in enumerate(list(self.serials)):
                if self.monitor_stop.is_set():return
                if i in self._recovery_busy:continue
                if not can_recover(state=self.states[i],has_folio=self.folios[i],
                    active_outlook=self.active_outlook,has_serial=serial,
                    busy=bool(self.working or i in self.reset_in_progress)):
                    continue
                self._recovery_busy.add(i)
                try:
                    ok=login_detected(quick_ui(self.adb,serial))
                    if ok and can_recover(state=self.states[i],has_folio=self.folios[i],
                        active_outlook=self.active_outlook,has_serial=serial,
                        busy=bool(self.working or i in self.reset_in_progress)):
                        self.send('ready',i,True,'IMSS en inicio verificado; Android recuperado sin reutilizar correo retenido')
                except Exception:
                    pass # Ante duda, sigue REVISAR; no intervenir en el trámite.
                finally:
                    self._recovery_busy.discard(i)

def main():
    root=tk.Tk();PanelV22(root);root.mainloop()
if __name__=='__main__':main()
