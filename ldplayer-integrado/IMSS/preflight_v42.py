# -*- coding: utf-8 -*-
"""Estado de preparacion de bandejas en la misma DB SQLite compartida.

La cuenta no se reserva para IMSS hasta tener bandeja confirmada. Una cuenta
que solicita recuperación obligatoria se aparta sin manipular Microsoft.
"""
import sqlite3, time
from pool_v14 import SharedPool, PoolError

class Preflight:
    def __init__(self,pool=None):
        self.pool=pool or SharedPool()
        with self.pool.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS preflight_v42 (
                email TEXT PRIMARY KEY, worker INTEGER NOT NULL,
                estado TEXT NOT NULL, actualizado REAL NOT NULL,
                motivo TEXT NOT NULL DEFAULT '')''')
    def claim(self,worker):
        assert worker in (1,2,3,4)
        with self.pool.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                existing=db.execute('''SELECT email,estado,actualizado FROM preflight_v42
                    WHERE worker=? AND estado IN ('PREPARANDO','LISTO','ASIGNADO') LIMIT 1''',(worker,)).fetchone()
                if existing:
                    db.execute('COMMIT')
                    return None
                row=db.execute('''SELECT c.email FROM cuentas c
                    LEFT JOIN preflight_v42 p ON p.email=c.email
                    WHERE c.estado='DISPONIBLE' AND p.email IS NULL
                    ORDER BY c.n LIMIT 1''').fetchone()
                if not row: db.execute('COMMIT');return None
                email=row['email']
                db.execute("INSERT INTO preflight_v42(email,worker,estado,actualizado) VALUES(?,?,'PREPARANDO',?)",
                           (email,worker,time.time()))
                db.execute('COMMIT');return email
            except Exception:db.execute('ROLLBACK');raise
    def for_worker(self,worker):
        with self.pool.db() as db:
            row=db.execute('''SELECT email,estado,actualizado,motivo FROM preflight_v42
                   WHERE worker=? AND estado IN ('PREPARANDO','LISTO','ASIGNADO') LIMIT 1''',(worker,)).fetchone()
            return dict(row) if row else None
    def set_ready(self,email,worker):
        with self.pool.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                n=db.execute('''UPDATE preflight_v42 SET estado='LISTO',actualizado=?
                 WHERE email=? AND worker=? AND estado='PREPARANDO' AND EXISTS
                 (SELECT 1 FROM cuentas WHERE email=? AND estado='DISPONIBLE')''',
                 (time.time(),email,worker,email)).rowcount
                db.execute('COMMIT');return bool(n)
            except Exception:db.execute('ROLLBACK');raise
    def fail(self,email,worker,motivo):
        """Conservar estado ERROR, excluir permanentemente de disponibles, sin reintentos."""
        with self.pool.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                n=db.execute('''UPDATE preflight_v42 SET estado='ERROR', motivo=?, actualizado=?
                   WHERE email=? AND worker=? AND estado IN ('PREPARANDO','LISTO')''',
                   (str(motivo)[:130],time.time(),email,worker)).rowcount
                if n:
                    db.execute("UPDATE cuentas SET estado='REVISAR', actualizado=CURRENT_TIMESTAMP WHERE email=? AND estado='DISPONIBLE'",(email,))
                db.execute('COMMIT');return bool(n)
            except Exception:db.execute('ROLLBACK');raise
    def release_assigned_if_review(self,email,worker):
        # El IMSS puede cancelar un folio tras fallar. Nunca dejar una marca
        # ASIGNADO permanente que bloquee la proxima cuenta del mismo canal.
        with self.pool.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row=db.execute('SELECT estado FROM cuentas WHERE email=?',(email,)).fetchone()
                if not row or row['estado']!='REVISAR':
                    db.execute('COMMIT');return False
                n=db.execute('''UPDATE preflight_v42 SET estado='ERROR',motivo=?,actualizado=?
                    WHERE email=? AND worker=? AND estado='ASIGNADO' ''',
                    ('Tramite IMSS cancelado; cuenta apartada',time.time(),email,worker)).rowcount
                db.execute('COMMIT');return bool(n)
            except Exception:db.execute('ROLLBACK');raise

    def ready_for(self,worker):
        with self.pool.db() as db:
            row=db.execute('''SELECT p.email FROM preflight_v42 p
                JOIN cuentas c ON c.email=p.email
                WHERE p.worker=? AND p.estado='LISTO' AND c.estado='DISPONIBLE' LIMIT 1''',(worker,)).fetchone()
            return row['email'] if row else None
    def take_ready(self,worker,folio):
        """Reserva atomica: Outlook verificado -> folio IMSS, sin posibilidad de cruce."""
        import re
        if not re.fullmatch(r'[a-f0-9]{32}',folio or ''):raise PoolError('Folio invalido')
        with self.pool.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row=db.execute('''SELECT p.email FROM preflight_v42 p JOIN cuentas c ON p.email=c.email
                   WHERE p.worker=? AND p.estado='LISTO' AND c.estado='DISPONIBLE' LIMIT 1''',(worker,)).fetchone()
                if not row:db.execute('COMMIT');return None
                email=row['email']
                n=db.execute('''UPDATE cuentas SET estado='OCUPADO',folio=?,actualizado=CURRENT_TIMESTAMP
                    WHERE email=? AND estado='DISPONIBLE' ''',(folio,email)).rowcount
                if n!=1:raise PoolError('La cuenta dejo de estar disponible')
                db.execute("UPDATE preflight_v42 SET estado='ASIGNADO',actualizado=? WHERE email=? AND worker=? AND estado='LISTO'",
                           (time.time(),email,worker))
                db.execute('COMMIT');return email
            except Exception:db.execute('ROLLBACK');raise
    def states(self):
        with self.pool.db() as db:
            return [dict(row) for row in db.execute('''SELECT worker,estado,COUNT(*) AS cantidad
               FROM preflight_v42 GROUP BY worker,estado ORDER BY worker''')]
