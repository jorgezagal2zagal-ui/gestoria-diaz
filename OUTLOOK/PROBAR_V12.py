# -*- coding: utf-8 -*-
"""Pruebas de cola, selección y migración V11->V12. No accede a Microsoft."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
from queue_store import QueueStore
from cooldown import Cooldown
from credenciales import parse_list, Vault

clock=[100.0]; cool=Cooldown(60,clock=lambda:clock[0]);cool.begin()
assert cool.remaining()==60
clock[0]+=30;assert cool.remaining()==30
clock[0]+=30;assert cool.remaining()==0
parsed=parse_list('uno@hotmail.com | CONTRA: demo.abc\ndos@outlook.com:Clave.124\n')
assert len(parsed)==2
class DummyDPAPI:
    def protect(self,x):return ('ENC:'+x).encode()
    def unprotect(self,x):return x.decode().removeprefix('ENC:')
with TemporaryDirectory() as tmp:
    v=Vault(protector=DummyDPAPI(),path=Path(tmp)/'vault.sqlite3')
    v.save(parsed)
    assert v.password('uno@hotmail.com')=='demo.abc'
    path=Path(tmp)/'queue.sqlite3'
    q=QueueStore(path)
    assert q.add([e for e,_ in parsed])==2
    assert q.add(['uno@hotmail.com'])==0
    assert q.counts()=={'total':2,'nuevos':2,'usados':0,'seleccionados':0}
    q.select_all(); assert q.counts()['seleccionados']==2
    assert q.choose()=='uno@hotmail.com'
    assert q.choose(exclude='uno@hotmail.com')=='dos@outlook.com'
    q.mark_started('uno@hotmail.com')
    assert q.entries()[0]['estado']=='USADO'
    assert q.entries()[1]['estado']=='NUEVO'
    assert q.choose()=='dos@outlook.com'
    # Seleccionar, importar o reabrir no cambia el estado.
    q.set_selected(['uno@hotmail.com']);assert q.choose() is None
    q2=QueueStore(path)
    assert q2.counts()=={'total':2,'nuevos':1,'usados':1,'seleccionados':1}
    q2.deselect_all();assert q2.counts()['seleccionados']==0
    assert q2.entries()[0]['estado']=='USADO'
with TemporaryDirectory() as tmp:
    # Migración sin borrar la base local existente de V11.
    path=Path(tmp)/'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE correo (n INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,estado TEXT DEFAULT "PENDIENTE")')
        db.executemany('INSERT INTO correo(email,estado) VALUES(?,?)', [('viejo@hotmail.com','UTILIZADO'),('nuevo@outlook.com','ACTUAL'),('tercero@hotmail.com','REVISAR')])
    q=QueueStore(path)
    a=q.entries();assert [r['estado'] for r in a]==['USADO','NUEVO','NUEVO']
    assert a[1]['seleccionado']==1
    assert q.counts()['usados']==1
print('V12: pruebas locales superadas; no se accedió a cuentas Microsoft.')
