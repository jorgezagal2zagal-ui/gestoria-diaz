# -*- coding: utf-8 -*-
"""V30: misma conexión segura V29 con IMSS V23 (cuatro emuladores en cola)."""
from app_v29 import OutlookV29

class OutlookV30(OutlookV29):
    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V30 · IMSS V23 / 4 ANDROID')
        self.info.set('V30: compatible con los 4 LDPlayer de IMSS V23. Una sesión/código a la vez; las otras solicitudes quedan en cola. Rechaza ofertas opcionales de Microsoft.')

if __name__=='__main__': OutlookV30().mainloop()
