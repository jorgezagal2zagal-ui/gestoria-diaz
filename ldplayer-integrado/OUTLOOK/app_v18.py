# -*- coding: utf-8 -*-
"""Outlook V18: persistent account profiles + respect Microsoft's 429 limits.
IMSS V17 untouched. Reads only the authorized mailbox for its current request.
"""
import tkinter as tk
from app_v17 import OutlookV17
import app as baseapp
import navegador_v18 as navegador
from lector_reciente_v14 import scan_visible_inbox
from guardia_v18 import faltan_segundos
navegador.scan_visible_inbox=scan_visible_inbox
# app.App.__init__ looks up BrowserLogin dynamically. Install V18 only in
# the Outlook process, without changing IMSS files or prior V17 sources.
baseapp.BrowserLogin=navegador.BrowserLogin

class OutlookV18(OutlookV17):
    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V18 · SESIÓN ESTABLE')
        self.info.set('V18: una sesión dedicada por correo. Si está vigente, se reutiliza sin volver a ingresar.')
        main=self.winfo_children()[0]
        tk.Label(main,text='V18: Chrome con perfil propio por cuenta (sin reutilizar el perfil personal). Microsoft 429 = pausa global.',
                 bg='#101419',fg='#E8BB62',wraplength=700,justify='left').pack(fill='x',pady=5)

    def _guard_new_login(self):
        wait=faltan_segundos()
        if wait:
            message='Microsoft limitó los intentos. Pausa global activa; revisa Outlook manualmente si es necesario.'
            self.info.set(message)
            self.recovery_info.set(message)
            return False
        return super()._guard_new_login()

    def _tick_once(self):
        wait=faltan_segundos()
        if wait:
            # Keep service heartbeat responsive while login requests are blocked.
            self.preparacion.heartbeat()
            self.info.set('Acceso a Microsoft pausado por 429; no se cambiará de cuenta ni se reintentará durante esta pausa.')
            self.recovery_info.set('Límite Microsoft 429. Revisa la cuenta en Chrome normal y permite que Microsoft restablezca el acceso.')
            return
        super()._tick_once()

if __name__=='__main__':OutlookV18().mainloop()
