# -*- coding: utf-8 -*-
"""V17: diagnóstico real de coordinación sin tocar el motor ADB V7."""
from __future__ import annotations
import threading
import tkinter as tk
from gestoria_panel_v15 import PanelV15
from preparacion_v17 import PreparationV17

class PanelV17(PanelV15):
    def __init__(self,root):
        super().__init__(root)
        self.preparacion=PreparationV17()
        root.title('GESTORÍA DÍAZ · IMSS V17 · COORDINACIÓN CORREGIDA')
        self.add_btn.configure(text='2. SOLICITAR · OUTLOOK PRIMERO')
        self.status_outlook.configure(text='OUTLOOK V17: comprobando enlace y cola…')
        self.log('V17: espera un Outlook V17 activo y SIN sesión anterior pendiente.')
        self.log('V17: si Outlook muestra sesión previa, usa su botón LIBERAR SOLO CON CONFIRMACIÓN.')

    def probe_outlook_loop(self):
        while not self.monitor_stop.wait(2.0):
            try:
                if not self.preparacion.live():
                    self.send('outlook_available',False)
                    self.send('outlook_state','OUTLOOK V17: sin conexión. Cierra otras versiones y abre Outlook V17.')
                    continue
                response=self.puente.comprobar()
                available=bool(response.get('available'))
                self.send('outlook_available',available)
                if available:
                    self.send('outlook_state','OUTLOOK V17: conectado y disponible · cola puede iniciar')
                else:
                    self.send('outlook_state','OUTLOOK V17: sesión anterior / espera / enfriamiento. Revisa Outlook.')
            except Exception:
                self.send('outlook_available',False)
                self.send('outlook_state','OUTLOOK V17: no responde el enlace local. Cierra el Outlook anterior.')

    def dispatch(self):
        # No reservar correos ante latidos de otra versión del bot.
        if not self.preparacion.live():return
        return super().dispatch()

def main():
    root=tk.Tk()
    PanelV17(root)
    root.mainloop()
if __name__=='__main__':main()
