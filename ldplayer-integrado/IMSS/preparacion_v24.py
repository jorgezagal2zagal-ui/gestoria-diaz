# -*- coding: utf-8 -*-
"""Multi-preparation: each folio is permanently associated with one Outlook worker."""
import time
from preparacion_v20 import PreparationV20
class PreparationV24(PreparationV20):
    def __init__(self):
        super().__init__()
        with self.db() as d:
            names={row[1] for row in d.execute('PRAGMA table_info(tareas)')}
            if 'worker' not in names:
                d.execute('ALTER TABLE tareas ADD COLUMN worker INTEGER NOT NULL DEFAULT 0')
    def create(self,folio,email,worker):
        if worker not in (1,2,3,4):raise ValueError('Worker no válido')
        super().create(folio,email)
        with self.db() as d:
            d.execute('UPDATE tareas SET worker=? WHERE folio=? AND email=?',(worker,folio,email))
    def live(self,worker,max_age=8):
        with self.db() as d:
            row=d.execute('SELECT ts FROM heartbeat WHERE nombre=?',('outlook_v32_'+str(worker),)).fetchone()
            return bool(row and 0<=time.time()-row['ts']<=max_age)
