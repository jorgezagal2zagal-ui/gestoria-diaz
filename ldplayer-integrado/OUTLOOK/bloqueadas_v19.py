# -*- coding: utf-8 -*-
"""Lista local separada para cuentas bloqueadas. No guarda contraseñas.
Persistente incluso al cerrar Outlook. Compatible con IMSS V17: REVISAR queda
reservado y su folio no vuelve a estar DISPONIBLE.
"""
from pool_v14 import SharedPool
class BlockedRegistry:
    def __init__(self,pool=None):
        self.pool=pool or SharedPool()
        with self.pool.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS cuentas_bloqueadas(
                email TEXT PRIMARY KEY, folio TEXT, motivo TEXT NOT NULL,
                fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    def mark(self,email,folio):
        email=email.strip().lower()
        with self.pool.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                # Doble salvaguarda: jamás modificar otra cuenta o solicitud.
                row=db.execute('SELECT estado,folio FROM cuentas WHERE email=?',(email,)).fetchone()
                if row is None or row['folio']!=folio or row['estado'] not in ('OCUPADO','REVISAR'):
                    db.execute('COMMIT');return False
                db.execute('UPDATE cuentas SET estado=?,actualizado=CURRENT_TIMESTAMP WHERE email=? AND folio=?',('REVISAR',email,folio))
                db.execute('INSERT OR IGNORE INTO cuentas_bloqueadas(email,folio,motivo) VALUES(?,?,?)',
                    (email,folio,'Microsoft bloqueó esta cuenta'))
                db.execute('COMMIT')
                return True
            except Exception:
                db.execute('ROLLBACK');raise
    def entries(self):
        with self.pool.db() as db:
            return [dict(r) for r in db.execute('SELECT email,fecha,motivo FROM cuentas_bloqueadas ORDER BY fecha DESC,email')]
    def count(self):
        with self.pool.db() as db:
            return db.execute('SELECT COUNT(*) FROM cuentas_bloqueadas').fetchone()[0]
