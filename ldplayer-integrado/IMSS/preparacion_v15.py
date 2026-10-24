# -*- coding: utf-8 -*-
"""Coordinación local previa al IMSS; no contiene contraseñas ni códigos."""
import re,sqlite3,time,os
from pathlib import Path
from contextlib import contextmanager
from pool_v14 import SharedPool
BASE=Path(os.environ.get('LOCALAPPDATA') or str(Path.home()))/'GestoriaDiaz'/'CompartidoV14'
DB=BASE/'preparacion_v15.sqlite3'
class Preparation:
    def __init__(self,path=None):
        self.path=Path(path or DB)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as d:
            d.execute('PRAGMA journal_mode=WAL')
            d.execute("""CREATE TABLE IF NOT EXISTS tareas(
                folio TEXT PRIMARY KEY, email TEXT NOT NULL,
                estado TEXT NOT NULL, actualizado REAL NOT NULL)""")
            d.execute('CREATE TABLE IF NOT EXISTS heartbeat (nombre TEXT PRIMARY KEY, ts REAL NOT NULL)')
    @contextmanager
    def db(self):
        d=sqlite3.connect(self.path,timeout=12,isolation_level=None)
        d.row_factory=sqlite3.Row
        d.execute('PRAGMA busy_timeout=12000')
        try:yield d
        finally:d.close()
    def heartbeat(self):
        with self.db() as d:
            d.execute("INSERT OR REPLACE INTO heartbeat(nombre,ts) VALUES('outlook_v15',?)",(time.time(),))
    def live(self,max_age=8):
        with self.db() as d:
            row=d.execute("SELECT ts FROM heartbeat WHERE nombre='outlook_v15'").fetchone()
            return bool(row and 0 <= time.time()-row['ts'] <= max_age)
    def create(self,folio,email):
        if not re.fullmatch('[0-9a-f]{32}',folio or ''):raise ValueError('Folio inválido')
        row=SharedPool().by_folio(folio)
        if not row or row['email']!=email or row['estado']!='OCUPADO':raise ValueError('Reserva de correo no válida')
        with self.db() as d:
            d.execute('INSERT INTO tareas(folio,email,estado,actualizado) VALUES(?,?,?,?)',(folio,email,'PENDIENTE',time.time()))
    def pending(self):
        with self.db() as d:
            row=d.execute("SELECT folio,email,estado FROM tareas WHERE estado IN ('PENDIENTE','ABRIENDO') ORDER BY actualizado LIMIT 1").fetchone()
            return dict(row) if row else None
    def status(self,folio):
        with self.db() as d:
            row=d.execute('SELECT email,estado,actualizado FROM tareas WHERE folio=?',(folio,)).fetchone()
            return dict(row) if row else None
    def set(self,folio,email,status):
        if status not in ('ABRIENDO','LISTO','BLOQUEADA','REVISAR','LIMITE_MICROSOFT'):raise ValueError('Estado incorrecto')
        with self.db() as d:
            return d.execute("UPDATE tareas SET estado=?,actualizado=? WHERE folio=? AND email=? AND estado IN ('PENDIENTE','ABRIENDO')",
                      (status,time.time(),folio,email)).rowcount==1
    def finish(self,folio):
        with self.db() as d:d.execute('DELETE FROM tareas WHERE folio=?',(folio,))
