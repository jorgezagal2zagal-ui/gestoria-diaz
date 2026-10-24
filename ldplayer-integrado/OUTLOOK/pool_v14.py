# -*- coding: utf-8 -*-
"""V14: una lista única, nueva y local. No incluye credenciales de versiones anteriores.

En el DB compartido sólo hay direcciones de correo, estados y un contador histórico
SIN correo identificable. Contraseñas individuales protegidas por Windows DPAPI
(gestiona credenciales.Vault en el perfil de Windows).
"""
from __future__ import annotations
from pathlib import Path
from contextlib import contextmanager
import os, re, sqlite3, uuid

BASE = Path(os.environ.get('LOCALAPPDATA') or str(Path.home())) / 'GestoriaDiaz' / 'CompartidoV14'
POOL_DB = BASE / 'lista_correos.sqlite3'
VAULT_DB = BASE / 'passwords_dpapi.sqlite3'
EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

class PoolError(RuntimeError):
    pass

class SharedPool:
    def __init__(self, path=None):
        self.path=Path(path or POOL_DB)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("""CREATE TABLE IF NOT EXISTS cuentas(
               n INTEGER PRIMARY KEY AUTOINCREMENT,
               email TEXT NOT NULL UNIQUE,
               estado TEXT NOT NULL CHECK(estado IN ('DISPONIBLE','OCUPADO','REVISAR')),
               folio TEXT UNIQUE,
               actualizado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            db.execute('CREATE TABLE IF NOT EXISTS contadores(clave TEXT PRIMARY KEY, cantidad INTEGER NOT NULL DEFAULT 0)')
            db.execute("INSERT OR IGNORE INTO contadores(clave,cantidad) VALUES('eliminados',0)")

    @contextmanager
    def db(self):
        db=sqlite3.connect(str(self.path),timeout=12,isolation_level=None)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA busy_timeout=12000')
        try: yield db
        finally: db.close()

    def replace_fresh(self,emails):
        """Nueva importación con reemplazo EXPRESO; bloquea si hay cuentas ocupadas."""
        normalized=list(dict.fromkeys(str(e).strip().lower() for e in emails))
        if not normalized or len(normalized)>10000 or any(not EMAIL.fullmatch(e) for e in normalized):
            raise PoolError('TXT vacío, demasiado grande o con algún correo inválido')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                if db.execute("SELECT 1 FROM cuentas WHERE estado IN ('OCUPADO','REVISAR') LIMIT 1").fetchone():
                    raise PoolError('Hay correos ocupados o en revisión; no se puede sustituir toda la lista')
                db.execute('DELETE FROM cuentas')
                db.executemany("INSERT INTO cuentas(email,estado) VALUES(?,'DISPONIBLE')",((e,) for e in normalized))
                db.execute("UPDATE contadores SET cantidad=0 WHERE clave='eliminados'")
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK');raise
        return len(normalized)

    def add(self,emails):
        rows=list(dict.fromkeys(str(e).strip().lower() for e in emails))
        if any(not EMAIL.fullmatch(e) for e in rows): raise PoolError('Correo inválido')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                n=0
                for e in rows:
                    n+=db.execute("INSERT OR IGNORE INTO cuentas(email,estado) VALUES(?,'DISPONIBLE')",(e,)).rowcount
                db.execute('COMMIT');return n
            except Exception:db.execute('ROLLBACK');raise

    def counts(self):
        with self.db() as db:
            counts={k:int(db.execute('SELECT COUNT(*) FROM cuentas WHERE estado=?',(k,)).fetchone()[0])
                  for k in ('DISPONIBLE','OCUPADO','REVISAR')}
            counts['ELIMINADOS']=int(db.execute("SELECT cantidad FROM contadores WHERE clave='eliminados'").fetchone()[0])
            counts['EN_LISTA']=sum(counts[k] for k in ('DISPONIBLE','OCUPADO','REVISAR'))
            return counts

    def entries(self):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT email,estado,folio FROM cuentas ORDER BY n')]

    def reserve(self,folio):
        if not re.fullmatch('[0-9a-f]{32}',folio or ''):raise PoolError('Folio inválido')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row=db.execute("SELECT email FROM cuentas WHERE estado='DISPONIBLE' ORDER BY n LIMIT 1").fetchone()
                if row is None:db.execute('COMMIT');return None
                res=db.execute("UPDATE cuentas SET estado='OCUPADO',folio=?,actualizado=CURRENT_TIMESTAMP WHERE email=? AND estado='DISPONIBLE'",(folio,row['email']))
                if res.rowcount!=1:raise PoolError('Reserva modificada en otro proceso')
                db.execute('COMMIT');return row['email']
            except Exception:db.execute('ROLLBACK');raise

    def by_folio(self,folio):
        with self.db() as db:
            row=db.execute('SELECT email,estado,folio FROM cuentas WHERE folio=?',(folio,)).fetchone()
            return dict(row) if row else None

    def has_occupied_email(self,email):
        with self.db() as db:
            return bool(db.execute("SELECT 1 FROM cuentas WHERE email=? AND estado='OCUPADO'",(email.strip().lower(),)).fetchone())

    def review(self,folio):
        with self.db() as db:
            return db.execute("UPDATE cuentas SET estado='REVISAR',actualizado=CURRENT_TIMESTAMP WHERE folio=? AND estado='OCUPADO'",(folio,)).rowcount==1

    def consume(self,folio):
        """Eliminar dirección de la lista y sumar contador; nunca antes de éxito confirmado.
        Retorna email para limpiar secreto DPAPI posteriormente.
        """
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row=db.execute("SELECT email FROM cuentas WHERE folio=? AND estado IN ('OCUPADO','REVISAR')",(folio,)).fetchone()
                if row is None:raise PoolError('No hay correo reservado para finalizar')
                db.execute('DELETE FROM cuentas WHERE folio=?',(folio,))
                db.execute("UPDATE contadores SET cantidad=cantidad+1 WHERE clave='eliminados'")
                db.execute('COMMIT');return row['email']
            except Exception: db.execute('ROLLBACK');raise

class SharedQueueAdapter:
    """Adaptador del panel Outlook V15, respaldado por el MISMO archivo que IMSS."""
    def __init__(self): self.pool=SharedPool()
    def add(self,emails):return self.pool.add(emails)
    def entries(self):
        return [dict(email=row['email'],estado=('NUEVO' if row['estado']=='DISPONIBLE' else row['estado']),
                     seleccionado=(1 if row['estado']!='REVISAR' else 0)) for row in self.pool.entries()]
    def counts(self):
        c=self.pool.counts()
        return {'total':c['EN_LISTA'],'nuevos':c['DISPONIBLE'],
                'usados':c['ELIMINADOS'],'seleccionados':c['DISPONIBLE']+c['OCUPADO']}
    def choose(self,exclude=None):
        return next((x['email'] for x in self.entries() if x['estado']=='NUEVO' and x['email']!=exclude),None)
    def is_selected_new(self,email):
        return any(r['email']==email.lower() and r['estado']=='OCUPADO' for r in self.entries())
    def mark_started(self,email):
        # Entrar a Microsoft NO significa que ya se utilizó: sigue OCUPADO.
        return 1 if self.pool.has_occupied_email(email) else 0
    def activate(self,email):
        return any(x['email']==email.strip().lower() for x in self.entries())
    def set_selected(self,emails): return None # la asignación es siempre automática
    def select_all(self): return None
    def deselect_all(self): return None

