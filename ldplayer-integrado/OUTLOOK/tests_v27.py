import tempfile,sqlite3,unittest,uuid
from pathlib import Path
from pool_v14 import SharedPool
from gestion_correos_v27 import AccountListEditorV27

class TestV27(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.dir=Path(self.tmp.name)
  self.pool=SharedPool(self.dir/'test.sqlite3')
  self.prep=self.dir/'prep.sqlite3'
  with sqlite3.connect(self.prep) as db:
   db.execute('CREATE TABLE tareas(folio TEXT PRIMARY KEY,email TEXT,estado TEXT,actualizado REAL)')
  self.editor=AccountListEditorV27(self.pool,self.prep,self.dir/'respaldo')
 def add(self,email='a@outlook.com'):
  self.assertEqual(1,self.pool.add([email]))
  return email
 def test_delete_busy_explicit(self):
  a=self.add('a@outlook.com');b=self.add('b@outlook.com')
  fid=uuid.uuid4().hex
  self.assertEqual(a,self.pool.reserve(fid))
  with sqlite3.connect(self.prep) as db:
   db.execute('INSERT INTO tareas VALUES(?,?,?,0)',(fid,a,'PENDIENTE'))
  removed,busy=self.editor.remove(None)
  self.assertEqual([b],removed);self.assertEqual([a],busy)
  self.assertEqual(1,len(self.pool.entries()))
  removed,folios,backup=self.editor.remove_with_stale_reservations(None)
  self.assertEqual([a],removed);self.assertEqual([fid],folios)
  self.assertTrue(Path(backup).is_file())
  self.assertEqual([],self.pool.entries())
  with sqlite3.connect(self.prep) as db:
   self.assertEqual(0,db.execute('SELECT COUNT(*) FROM tareas').fetchone()[0])
  self.assertEqual(0,self.pool.counts()['ELIMINADOS'])
 def test_only_selected_and_keep_other_reservation(self):
  a=self.add('a@outlook.com');b=self.add('b@outlook.com');c=self.add('c@outlook.com')
  fid=uuid.uuid4().hex;self.assertEqual(a,self.pool.reserve(fid))
  removed,folios,_=self.editor.remove_with_stale_reservations([b])
  self.assertEqual([b],removed);self.assertEqual([],folios)
  self.assertEqual({a,c},{r['email'] for r in self.pool.entries()})
 def test_blocked_registry_remains(self):
  self.add('a@outlook.com')
  with self.pool.db() as db:
   db.execute('CREATE TABLE cuentas_bloqueadas(email TEXT PRIMARY KEY,folio TEXT,motivo TEXT,fecha TEXT)')
   db.execute("INSERT INTO cuentas_bloqueadas VALUES('a@outlook.com',NULL,'MFA','hoy')")
  self.editor.remove_with_stale_reservations(None)
  with self.pool.db() as db:
   self.assertEqual(1,db.execute('SELECT COUNT(*) FROM cuentas_bloqueadas').fetchone()[0])
 def test_reject_bad_addresses(self):
  with self.assertRaises(Exception):self.editor.remove_with_stale_reservations(['nope'])
  self.add()
  self.assertEqual(1,len(self.pool.entries()))

if __name__=='__main__':unittest.main()
