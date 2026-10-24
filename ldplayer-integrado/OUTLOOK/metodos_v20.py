# -*- coding: utf-8 -*-
"""Cuentas cuya autenticación con contraseña Microsoft no está disponible.
No significa que la cuenta haya sido bloqueada. No se guardan claves."""
from pool_v14 import SharedPool
class MethodRegistry:
    def __init__(self,pool=None):
        self.pool=pool or SharedPool()
        with self.pool.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS cuentas_otro_metodo(
                email TEXT PRIMARY KEY, folio TEXT, fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                motivo TEXT NOT NULL)''')
    def mark(self,email,folio):
        email=(email or '').strip().lower()
        with self.pool.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row=db.execute('SELECT estado,folio FROM cuentas WHERE email=?',(email,)).fetchone()
                if not row or row['folio']!=folio or row['estado'] not in ('OCUPADO','REVISAR'):
                    db.execute('COMMIT');return False
                db.execute("UPDATE cuentas SET estado='REVISAR',actualizado=CURRENT_TIMESTAMP WHERE email=? AND folio=?",(email,folio))
                db.execute('INSERT OR IGNORE INTO cuentas_otro_metodo(email,folio,motivo) VALUES(?,?,?)',
                    (email,folio,'Microsoft exige otro método de inicio'))
                db.execute('COMMIT');return True
            except Exception:
                db.execute('ROLLBACK');raise
    def entries(self):
        with self.pool.db() as db:
            return [dict(r) for r in db.execute('SELECT email,fecha,motivo FROM cuentas_otro_metodo ORDER BY fecha DESC,email')]
    def count(self):
        with self.pool.db() as db:
            return db.execute('SELECT COUNT(*) FROM cuentas_otro_metodo').fetchone()[0]
