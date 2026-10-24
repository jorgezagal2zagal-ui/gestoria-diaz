# -*- coding: utf-8 -*-
"""Administración de cuentas locales: limpieza explícita con bloqueo por reservas.
No elimina cuentas ni mensajes reales de Microsoft; no toca historial de bloqueos.
"""
from __future__ import annotations
from pool_v14 import SharedPool, PoolError

def clear_available_list(pool: SharedPool):
    # Transacción atómica, especialmente importante con cuatro procesos.
    with pool.db() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            busy=db.execute("SELECT COUNT(*) FROM cuentas WHERE estado='OCUPADO'").fetchone()[0]
            if busy:
                raise PoolError(f'Hay {busy} correos OCUPADO; termina esos trámites antes de borrar.')
            addresses=[r['email'] for r in db.execute('SELECT email FROM cuentas ORDER BY n')]
            db.execute('DELETE FROM cuentas')
            # El contador de terminados se conserva; borrar manualmente no es consumo.
            db.execute('COMMIT')
            return addresses
        except Exception:
            db.execute('ROLLBACK')
            raise
