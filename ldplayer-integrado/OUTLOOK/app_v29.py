# -*- coding: utf-8 -*-
"""V29: Outlook V28 with a precise message-reading fix and bridge feedback."""
from app_v28 import OutlookV28, DEFAULT_SENDER_IMSS
import app as baseapp
import navegador_v28 as browser
from lector_reciente_v29 import scan_visible_inbox

browser.scan_visible_inbox=scan_visible_inbox
baseapp.BrowserLogin=browser.BrowserLogin

class OutlookV29(OutlookV28):
    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V29 · LECTOR IMSS CORREGIDO')
        self.info.set('V29: mensajes IMSS con fecha visible; lector y enlace local preparados. No acepta claves de paso ni guardar contraseñas.')

if __name__ == '__main__': OutlookV29().mainloop()
