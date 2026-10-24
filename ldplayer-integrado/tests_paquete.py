import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import arranque
from inicio_windows import respaldar_datos


class PackageTests(unittest.TestCase):
    def test_sqlite_backup_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, LOCALAPPDATA=temp):
            folder = Path(temp)/'GestoriaDiaz'/'CompartidoV14'
            folder.mkdir(parents=True)
            source = folder/'lista_correos.sqlite3'
            with sqlite3.connect(source) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE pruebas (n INTEGER)')
                db.execute('INSERT INTO pruebas VALUES (7)')
                db.commit()
                respaldar_datos()
                self.assertEqual(db.execute('SELECT n FROM pruebas').fetchone(), (7,))
            copies = list((Path(temp)/'GestoriaDiaz'/'RespaldosIntegracion').glob('*/lista_correos.sqlite3'))
            self.assertEqual(len(copies), 1)
            with sqlite3.connect(copies[0]) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                self.assertEqual(db.execute('SELECT n FROM pruebas').fetchone(), (7,))

    def test_absent_user_data_does_not_create_backup(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, LOCALAPPDATA=temp):
            respaldar_datos()
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_windows_launcher_starts_two_distinct_entries(self):
        with patch.object(arranque.sys, 'platform', 'win32'), patch.object(Path, 'is_file', return_value=True), \
             patch.object(arranque.subprocess, 'Popen') as process:
            arranque.abrir(('OUTLOOK', 'IMSS'))
        self.assertEqual([call.args[0][-1] for call in process.call_args_list], ['OUTLOOK', 'IMSS'])
        for call in process.call_args_list:
            self.assertTrue(call.args[0][0].endswith('pythonw.exe'))
            self.assertTrue(call.args[0][1].endswith('inicio_windows.py'))

    def test_missing_installation_shows_instructions_without_starting(self):
        with patch.object(arranque.sys, 'platform', 'win32'), patch.object(Path, 'is_file', return_value=False), \
             patch.object(arranque, 'aviso') as notice, patch.object(arranque.subprocess, 'Popen') as process:
            arranque.abrir(('OUTLOOK',))
        notice.assert_called_once();process.assert_not_called()


if __name__ == '__main__':unittest.main()
