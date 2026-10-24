# -*- coding: utf-8 -*-
"""Gestoría Díaz V27: administración explícita de reservas antiguas.

No altera autenticación Microsoft ni ADB. El borrado de OCUPADO solo se realiza
con autorización separada de la persona responsable y con IMSS detenido.
"""
from __future__ import annotations
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from gestion_correos_v26 import AccountListEditor
from pool_v14 import EMAIL, PoolError
from preparacion_v15 import DB as PREPARATION_DB

class AccountListEditorV27(AccountListEditor):
    def __init__(self, pool=None, preparation_path=None, backup_dir=None):
        super().__init__(pool)
        self.preparation_path = Path(preparation_path or PREPARATION_DB)
        self.backup_dir = Path(backup_dir or self.pool.path.parent / 'respaldos_administracion')

    def remove_with_stale_reservations(self, selected=None):
        """Quita cuentas inclusive OCUPADO tras confirmación fuerte en la GUI.

        Registra respaldo del catálogo sin contraseñas y cancela tareas Outlook
        cuyos folios corresponden a las reservas retiradas.
        No borra el historial de cuentas bloqueadas.
        """
        if selected is None:
            emails = None
        else:
            emails=list(dict.fromkeys(str(x).strip().lower() for x in selected))
            if not emails or len(emails)>10000 or any(not EMAIL.fullmatch(e) for e in emails):
                raise PoolError('Selección de correos incorrecta.')
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = self.backup_dir / f'lista_antes_de_borrar_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}.sqlite3'
        # SQLite backup conserva un snapshot consistente aun con journal WAL.
        with self.pool.db() as source, sqlite3.connect(str(backup)) as dest:
            source.backup(dest)
        with self.pool.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                if emails is None:
                    rows=db.execute('SELECT email,estado,folio FROM cuentas').fetchall()
                else:
                    rows=[]
                    for addr in emails:
                        row=db.execute('SELECT email,estado,folio FROM cuentas WHERE email=?',(addr,)).fetchone()
                        if row: rows.append(row)
                removed=[]; folios=[]
                for row in rows:
                    # Solo estados válidos; verificación extra en SQL.
                    changed=db.execute("DELETE FROM cuentas WHERE email=? AND estado IN ('DISPONIBLE','OCUPADO','REVISAR')",(row['email'],))
                    if changed.rowcount:
                        removed.append(row['email'])
                        if row['folio'] and re.fullmatch('[0-9a-f]{32}',row['folio']):
                            folios.append(row['folio'])
                # Administrar el catálogo no equivale a 'correo utilizado'.
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK')
                raise
        if folios and self.preparation_path.exists():
            with sqlite3.connect(str(self.preparation_path),timeout=10) as prep:
                for folio in set(folios):
                    prep.execute('DELETE FROM tareas WHERE folio=?',(folio,))
        return removed, folios, str(backup)
