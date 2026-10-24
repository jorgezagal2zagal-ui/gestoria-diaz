# -*- coding: utf-8 -*-
"""Identidad V17 del enlace compartido, compatible con el DB V15.
No modifica ni borra las solicitudes o correos existentes.
"""
import time
from preparacion_v15 import Preparation

class PreparationV17(Preparation):
    def heartbeat(self):
        super().heartbeat()  # Conserva compatibilidad con el panel anterior.
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO heartbeat(nombre,ts) VALUES('outlook_v17',?)", (time.time(),))

    def live(self,max_age=8):
        with self.db() as db:
            row=db.execute("SELECT ts FROM heartbeat WHERE nombre='outlook_v17'").fetchone()
            return bool(row and 0<=time.time()-row['ts']<=max_age)
