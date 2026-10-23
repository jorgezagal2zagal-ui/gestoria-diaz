# -*- coding: utf-8 -*-
"""Cola de cuentas Outlook. Solo direcciones, estados y selección; SIN contraseñas."""
from __future__ import annotations
import sqlite3
import threading
from core import data_dir, EMAIL_RE

class QueueStore:
    def __init__(self, path=None):
        self.path = str(path or (data_dir() / 'cola_simple.sqlite3'))
        self.lock = threading.RLock()
        self._init()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _init(self):
        with self.lock, self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS correo (
              n INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT UNIQUE NOT NULL,
              estado TEXT NOT NULL DEFAULT 'NUEVO',
              seleccionado INTEGER NOT NULL DEFAULT 0)''')
            cols = {r['name'] for r in db.execute('PRAGMA table_info(correo)')}
            if 'seleccionado' not in cols:
                db.execute('ALTER TABLE correo ADD COLUMN seleccionado INTEGER NOT NULL DEFAULT 0')
                # Cuenta ACTUAL era la seleccionada en la versión anterior.
                db.execute("UPDATE correo SET seleccionado=1 WHERE estado='ACTUAL'")
            # Conservar 'USADO' únicamente para UTILIZADO anterior o sesiones iniciadas.
            db.execute("UPDATE correo SET estado='USADO' WHERE estado='UTILIZADO'")
            db.execute("UPDATE correo SET estado='NUEVO' WHERE estado NOT IN ('USADO','NUEVO')")

    @staticmethod
    def normalize(email):
        return email.strip().lower()

    def add(self, emails):
        added = 0
        with self.lock, self.connect() as db:
            for email in emails:
                address = self.normalize(email)
                if EMAIL_RE.fullmatch(address):
                    added += db.execute('INSERT OR IGNORE INTO correo(email) VALUES(?)',(address,)).rowcount
        return added

    def entries(self):
        with self.lock, self.connect() as db:
            return [dict(r) for r in db.execute('SELECT email,estado,seleccionado FROM correo ORDER BY n')]

    def counts(self):
        with self.lock, self.connect() as db:
            row = db.execute("""SELECT COUNT(*) total,
                   SUM(CASE WHEN estado='NUEVO' THEN 1 ELSE 0 END) nuevos,
                   SUM(CASE WHEN estado='USADO' THEN 1 ELSE 0 END) usados,
                   SUM(CASE WHEN seleccionado=1 THEN 1 ELSE 0 END) seleccionados
                   FROM correo""").fetchone()
            return {k:int(row[k] or 0) for k in ('total','nuevos','usados','seleccionados')}

    def set_selected(self, emails):
        valid = {self.normalize(e) for e in emails if EMAIL_RE.fullmatch(self.normalize(e))}
        with self.lock, self.connect() as db:
            db.execute('UPDATE correo SET seleccionado=0')
            if valid:
                db.executemany('UPDATE correo SET seleccionado=1 WHERE email=?',((e,) for e in valid))

    def select_all(self):
        with self.lock, self.connect() as db:db.execute('UPDATE correo SET seleccionado=1')

    def deselect_all(self):
        with self.lock, self.connect() as db:db.execute('UPDATE correo SET seleccionado=0')

    def activate(self,email):
        address = self.normalize(email)
        with self.lock, self.connect() as db:
            if not db.execute('SELECT 1 FROM correo WHERE email=?',(address,)).fetchone():return False
            db.execute('UPDATE correo SET seleccionado=1 WHERE email=?',(address,))
            return True

    def is_selected_new(self,email):
        with self.lock, self.connect() as db:
            return bool(db.execute("SELECT 1 FROM correo WHERE email=? AND estado='NUEVO' AND seleccionado=1",(self.normalize(email),)).fetchone())

    def choose(self,exclude=None):
        """Solo una cuenta NUEVA, marcada por el usuario, en orden de importación."""
        with self.lock, self.connect() as db:
            row=db.execute("""SELECT email FROM correo WHERE estado='NUEVO' AND seleccionado=1
                 AND email != ? ORDER BY n LIMIT 1""",(self.normalize(exclude) if exclude else '',)).fetchone()
            return row['email'] if row else None

    def mark_started(self,email):
        """'Usado' significa intento de acceso iniciado, NO importación o selección."""
        with self.lock, self.connect() as db:
            return db.execute("UPDATE correo SET estado='USADO' WHERE email=? AND estado='NUEVO'",(self.normalize(email),)).rowcount

    def reset_for_tests(self):
        with self.lock, self.connect() as db:db.execute('DELETE FROM correo')
