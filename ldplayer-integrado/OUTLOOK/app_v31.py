# -*- coding: utf-8 -*-
"""V31: opt-out robust of optional passkey saving; IMSS V23 unchanged."""
from app_v30 import OutlookV30

class OutlookV31(OutlookV30):
    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V31 · 4 ANDROID / SIN PASSKEY')
        self.info.set('V31: rechaza «Guardar la clave de paso» de Microsoft/Windows pulsando «Cancelar», evita guardar contraseña y responde «No» a mantener sesión. IMSS V23 intacto.')

if __name__=='__main__': OutlookV31().mainloop()
