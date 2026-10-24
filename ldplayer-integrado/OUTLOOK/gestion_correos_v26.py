# -*- coding: utf-8 -*-
"""Gestoría Díaz V26 — retiro explícito de la lista compartida Outlook/IMSS.

La eliminación usa una transacción SQLite; nunca borra una reserva OCUPADO.
Los registros de cuentas bloqueadas NO se borran, para evitar reutilización.
"""
from __future__ import annotations

from pool_v14 import SharedPool, EMAIL, PoolError


class AccountListEditor:
    def __init__(self, pool=None):
        self.pool = pool if pool is not None else SharedPool()

    def remove(self, selected=None):
        """Devuelve (emails_borrados, emails_ocupados).

        selected=None borra toda la lista elegible. La fuente definitiva es la
        base de datos en el momento de la transacción (sin confiar en la GUI).
        """
        if selected is not None:
            emails = list(dict.fromkeys(str(x).strip().lower() for x in selected))
            if not emails or len(emails) > 10000 or any(not EMAIL.fullmatch(e) for e in emails):
                raise PoolError('Selecciona correos válidos antes de borrar.')
        else:
            emails = None
        with self.pool.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                if emails is None:
                    rows = db.execute('SELECT email,estado FROM cuentas ORDER BY n').fetchall()
                else:
                    # Lista corta o grande sin sobrepasar límite de parámetros SQLite.
                    rows = []
                    for email in emails:
                        row = db.execute('SELECT email,estado FROM cuentas WHERE email=?', (email,)).fetchone()
                        if row:
                            rows.append(row)
                removed, busy = [], []
                for row in rows:
                    email, estado = row['email'], row['estado']
                    if estado == 'OCUPADO':
                        busy.append(email)
                        continue
                    # No modifica contadores de trámites terminados: eliminación
                    # administrativa no significa que un correo haya sido usado.
                    result = db.execute("DELETE FROM cuentas WHERE email=? AND estado IN ('DISPONIBLE','REVISAR')", (email,))
                    if result.rowcount == 1:
                        removed.append(email)
                db.execute('COMMIT')
                return removed, busy
            except Exception:
                db.execute('ROLLBACK')
                raise
