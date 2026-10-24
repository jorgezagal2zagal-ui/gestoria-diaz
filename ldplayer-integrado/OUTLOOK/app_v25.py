# -*- coding: utf-8 -*-
"""Outlook V25: Otras formas de iniciar sesión en Microsoft (paso seguro)."""
from app_v24 import OutlookV24
import app as baseapp
import navegador_v25 as navegador
from lector_reciente_v14 import scan_visible_inbox

# App elige BrowserLogin al crear el panel; V21 vinculaba el de su versión.
navegador.scan_visible_inbox=scan_visible_inbox
baseapp.BrowserLogin=navegador.BrowserLogin

class OutlookV25(OutlookV24):
    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V25 · OTRAS FORMAS DE INICIAR SESIÓN')

if __name__=='__main__':
    OutlookV25().mainloop()
