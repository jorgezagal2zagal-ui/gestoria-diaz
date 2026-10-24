# -*- coding: utf-8 -*-
"""Amplía sólo los estados del enlace. No modifica la base ni IMSS V7."""
import time
from preparacion_v17 import PreparationV17

class PreparationV20(PreparationV17):
    def set(self,folio,email,status):
        if status=='METODO_NO_DISPONIBLE':
            with self.db() as db:
                return db.execute("UPDATE tareas SET estado=?,actualizado=? WHERE folio=? AND email=? AND estado IN ('PENDIENTE','ABRIENDO')",
                                  (status,time.time(),folio,email)).rowcount==1
        return super().set(folio,email,status)
