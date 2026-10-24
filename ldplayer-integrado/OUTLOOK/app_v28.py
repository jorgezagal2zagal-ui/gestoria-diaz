# -*- coding: utf-8 -*-
"""V28: maneja avisos opcionales del video; no cambia IMSS ni el enlace."""
from app_v27 import OutlookV27
import app as baseapp
import navegador_v28 as browser_v28
from lector_reciente_v14 import scan_visible_inbox

browser_v28.scan_visible_inbox = scan_visible_inbox
baseapp.BrowserLogin = browser_v28.BrowserLogin
DEFAULT_SENDER_IMSS = 'verifica-noreplay@imss.gob.mx'

class OutlookV28(OutlookV27):
    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V28 · AVISOS AUTOMÁTICOS')
        if not self.sender.get().strip():
            self.sender.set(DEFAULT_SENDER_IMSS)
            self.browser.set_sender(DEFAULT_SENDER_IMSS)
        self.info.set('V28: guarda contraseñas DESACTIVADO; ofertas de clave de paso, sesión y recuperación se rechazan automáticamente. Se respeta la verificación adicional de Microsoft.')

if __name__ == '__main__':
    OutlookV28().mainloop()
