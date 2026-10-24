# -*- coding: utf-8 -*-
"""Cuentas no utilizables por este bot: bloqueos reales o factor adicional.
Persistencia en lista compartida con SQLite, sin guardar contraseñas.
"""
from bloqueadas_v19 import BlockedRegistry
class BlockedRegistryV21(BlockedRegistry):
    def __init__(self,pool=None):
        super().__init__(pool=pool)
        # Protege también ante una importación nueva del mismo correo.
        # Así el bot IMSS anterior no vuelve a reservar una cuenta apartada.
        with self.pool.db() as db:
            db.executescript("""            CREATE TRIGGER IF NOT EXISTS gestoria_v21_bloqueada_al_importar
            AFTER INSERT ON cuentas
            WHEN EXISTS(SELECT 1 FROM cuentas_bloqueadas WHERE email=NEW.email)
            BEGIN
              UPDATE cuentas SET estado='REVISAR', folio=NULL,
                      actualizado=CURRENT_TIMESTAMP WHERE email=NEW.email;
            END;
            CREATE TRIGGER IF NOT EXISTS gestoria_v21_bloqueada_al_activar
            AFTER UPDATE OF estado ON cuentas
            WHEN NEW.estado='DISPONIBLE'
              AND EXISTS(SELECT 1 FROM cuentas_bloqueadas WHERE email=NEW.email)
            BEGIN
              UPDATE cuentas SET estado='REVISAR', folio=NULL,
                      actualizado=CURRENT_TIMESTAMP WHERE email=NEW.email;
            END;
            """)
            db.execute("UPDATE cuentas SET estado='REVISAR',folio=NULL,actualizado=CURRENT_TIMESTAMP WHERE estado='DISPONIBLE' AND email IN (SELECT email FROM cuentas_bloqueadas)")

    def mark(self,email,folio,motivo='Microsoft bloqueó esta cuenta'):
        email=(email or '').strip().lower()
        if not email or not folio:return False
        with self.pool.db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row=db.execute('SELECT estado,folio FROM cuentas WHERE email=?',(email,)).fetchone()
                if not row or row['folio']!=folio or row['estado'] not in ('OCUPADO','REVISAR'):
                    db.execute('COMMIT');return False
                db.execute("UPDATE cuentas SET estado='REVISAR',actualizado=CURRENT_TIMESTAMP WHERE email=? AND folio=?",(email,folio))
                db.execute('INSERT OR IGNORE INTO cuentas_bloqueadas(email,folio,motivo) VALUES(?,?,?)',
                           (email,folio,motivo))
                db.execute('COMMIT');return True
            except Exception:
                db.execute('ROLLBACK');raise
