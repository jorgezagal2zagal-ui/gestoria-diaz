"""Regresión WinError 32: conservar referencias no debe dejar SQLite abierto.

Se prueban conexiones reales y datos ficticios. Mantener las referencias impide
que el recolector de basura oculte el fallo observado en Windows.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from credenciales import Vault
from queue_store import QueueStore


class FakeProtector:
    def protect(self,value):return ('synthetic:'+value).encode()
    def unprotect(self,value):return value.decode().removeprefix('synthetic:')


class SQLiteResources(unittest.TestCase):
    @contextmanager
    def tracked_connections(self):
        original=sqlite3.connect
        connections=[]
        def connect(*args,**kwargs):
            connection=original(*args,**kwargs)
            connections.append(connection)
            return connection
        with patch.object(sqlite3,'connect',side_effect=connect):
            try:yield connections
            finally:
                for connection in connections:connection.close()

    def assert_released(self,connections):
        self.assertTrue(connections)
        for connection in connections:
            with self.assertRaises(sqlite3.ProgrammingError):connection.execute('SELECT 1')

    def test_vault_releases_handles_before_the_file_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary,self.tracked_connections() as connections:
            path=Path(temporary)/'vault.sqlite3'
            vault=Vault(FakeProtector(),path)
            self.assert_released(connections)
            operations=[lambda:vault.save([('one@example.invalid','synthetic-password')]),
                lambda:vault.password('one@example.invalid'),lambda:vault.has_password('one@example.invalid'),
                lambda:vault.set_common_password('synthetic-common'),vault.has_common_password,
                lambda:vault.password('future@example.invalid'),vault.clear_common_password,
                lambda:vault.remove('one@example.invalid')]
            for operation in operations:
                operation()
                self.assert_released(connections)
            path.unlink()
            self.assertFalse(path.exists())

    def test_vault_rolls_back_partial_save_and_releases_the_failed_connection(self):
        with tempfile.TemporaryDirectory() as temporary,self.tracked_connections() as connections:
            vault=Vault(FakeProtector(),Path(temporary)/'vault.sqlite3')
            with self.assertRaises(ValueError):
                vault.save([('first@example.invalid','synthetic-password'),('second@example.invalid','')])
            self.assertFalse(vault.has_password('first@example.invalid'))
            self.assert_released(connections)

    def test_queue_releases_handles_after_reads_writes_and_early_returns(self):
        with tempfile.TemporaryDirectory() as temporary,self.tracked_connections() as connections:
            path=Path(temporary)/'queue.sqlite3'
            queue=QueueStore(path)
            self.assert_released(connections)
            operations=[lambda:queue.add(['one@example.invalid']),queue.entries,queue.counts,
                lambda:queue.set_selected(['one@example.invalid']),queue.select_all,
                queue.deselect_all,lambda:queue.activate('missing@example.invalid'),
                lambda:queue.activate('one@example.invalid'),
                lambda:queue.is_selected_new('one@example.invalid'),queue.choose,
                lambda:queue.mark_started('one@example.invalid'),queue.reset_for_tests]
            for operation in operations:
                operation()
                self.assert_released(connections)
            path.unlink()
            self.assertFalse(path.exists())

    def test_queue_rolls_back_partial_import_and_releases_the_failed_connection(self):
        with tempfile.TemporaryDirectory() as temporary,self.tracked_connections() as connections:
            queue=QueueStore(Path(temporary)/'queue.sqlite3')
            with self.assertRaises(AttributeError):queue.add(['first@example.invalid',None])
            self.assertEqual(queue.entries(),[])
            self.assert_released(connections)


if __name__=='__main__':unittest.main(verbosity=2)
