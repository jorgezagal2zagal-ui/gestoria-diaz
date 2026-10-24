# -*- coding: utf-8 -*-
"""V22: estado de cola y recuperación SOLO al confirmar pantalla inicial IMSS.

No modifica ADB V7, lista compartida, contraseñas ni cuentas retenidas.
"""

def can_recover(*,state,has_folio,active_outlook,has_serial,busy):
    return (state=='REVISAR' and not has_folio and not active_outlook
            and bool(has_serial) and not busy)

