# -*- coding: utf-8 -*-
"""V32 4 simultaneous Outlook sessions, independent worker reservation."""
import os,time
from preparacion_v20 import PreparationV20
class PreparationV32(PreparationV20):
    def __init__(self,worker=None):
        super().__init__()
        self.worker=int(worker if worker is not None else os.environ.get('GD_WORKER_SLOT','1'))
        if self.worker not in (1,2,3,4):raise ValueError('Worker fuera de rango')
        with self.db() as db:
            cols={r[1] for r in db.execute('PRAGMA table_info(tareas)')}
            if 'worker' not in cols:
                db.execute('ALTER TABLE tareas ADD COLUMN worker INTEGER NOT NULL DEFAULT 0')
    def heartbeat(self):
        super().heartbeat()
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO heartbeat(nombre,ts) VALUES(?,?)',
                       ('outlook_v32_'+str(self.worker),time.time()))
    def pending(self):
        with self.db() as db:
            row=db.execute("SELECT folio,email,estado FROM tareas WHERE worker=? AND estado IN ('PENDIENTE','ABRIENDO') ORDER BY actualizado LIMIT 1",(self.worker,)).fetchone()
            return dict(row) if row else None
