"""Regressions for ZIP temporary folders disappearing before identity PIN entry."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'gestoria_5_instancias.py'


def load_application(path, name='gestoria_storage_tests'):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bot = load_application(SOURCE)


def storage_application():
    app = bot.App.__new__(bot.App)
    app.root = Mock()
    app.emit = Mock()
    app.usados_sesion = set()
    app.correos_pendientes = []
    app.correos = ['FIRST@EXAMPLE.TEST', 'second@example.test', 'first@example.test']
    return app


def node(text='', rid='', kind='android.widget.TextView'):
    return {'texto': text, 'valor': text, 'descripcion': '', 'rid': rid,
            'clase': kind, 'enabled': True, 'visible': True,
            'xy': (100, 100), 'area': 2000}


class DataDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gestoria-storage-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.program = self.base / 'program'
        self.program.mkdir()
        self.data = self.base / 'profile' / 'GestoriaDiaz'
        for name, value in (
            ('CARPETA_PROGRAMA', self.program),
            ('CARPETA', self.data),
            ('MAPA', self.data / 'instancias.json'),
            ('USADOS', self.data / 'correos_usados.csv'),
        ):
            replacement = patch.object(bot, name, value, create=True)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_windows_prefers_durable_local_appdata_outside_the_program(self):
        local = self.base / 'local-profile'
        roaming = self.base / 'roaming-profile'
        with patch.object(sys, 'platform', 'win32'), \
                patch.dict(os.environ, {'LOCALAPPDATA': str(local), 'APPDATA': str(roaming)}, clear=True):
            self.assertEqual(bot.directorio_datos(), local / 'GestoriaDiaz')

    def test_windows_falls_back_to_roaming_then_profile_local_data(self):
        roaming = self.base / 'roaming-profile'
        home = self.base / 'home'
        with patch.object(sys, 'platform', 'win32'), \
                patch.dict(os.environ, {'APPDATA': str(roaming)}, clear=True):
            self.assertEqual(bot.directorio_datos(), roaming / 'GestoriaDiaz')
        with patch.object(sys, 'platform', 'win32'), \
                patch.dict(os.environ, {}, clear=True), patch.object(Path, 'home', return_value=home):
            self.assertEqual(bot.directorio_datos(), home / 'AppData' / 'Local' / 'GestoriaDiaz')

    def test_linux_uses_an_isolated_data_subdirectory(self):
        with patch.object(sys, 'platform', 'linux'), \
                patch.dict(os.environ, {'LOCALAPPDATA': str(self.base / 'unrelated')}, clear=True):
            self.assertEqual(bot.directorio_datos(), self.program / '.gestoria-datos')

    def test_old_csv_and_map_are_copied_without_removing_the_originals(self):
        old_map = {'SYNTHETIC-INSTANCE': '1'}
        old_csv = 'fecha,curp,correo,instancia,tramite\n2026-01-01,SYNTHETIC,first@example.test,SYNTHETIC,synthetic\n'
        (self.program / 'instancias.json').write_text(json.dumps(old_map), encoding='utf-8')
        (self.program / 'correos_usados.csv').write_text(old_csv, encoding='utf-8')
        bot.preparar_datos()
        self.assertEqual(json.loads(bot.MAPA.read_text(encoding='utf-8')), old_map)
        self.assertEqual(bot.USADOS.read_text(encoding='utf-8'), old_csv)
        self.assertEqual(bot.correos_usados(), {'first@example.test'})
        self.assertTrue((self.program / 'instancias.json').is_file())
        self.assertTrue((self.program / 'correos_usados.csv').is_file())

    def test_repeated_preparation_preserves_existing_persistent_data(self):
        self.data.mkdir(parents=True)
        saved_map = '{"SYNTHETIC-NEW": "5"}'
        saved_csv = 'fecha,curp,correo,instancia,tramite\n2026-01-02,SYNTHETIC,new@example.test,SYNTHETIC,synthetic\n'
        bot.MAPA.write_text(saved_map, encoding='utf-8')
        bot.USADOS.write_text(saved_csv, encoding='utf-8')
        (self.program / 'instancias.json').write_text('{"OLD": "1"}', encoding='utf-8')
        (self.program / 'correos_usados.csv').write_text('old data', encoding='utf-8')
        bot.preparar_datos()
        bot.preparar_datos()
        self.assertEqual(bot.MAPA.read_text(encoding='utf-8'), saved_map)
        self.assertEqual(bot.USADOS.read_text(encoding='utf-8'), saved_csv)

    def test_csv_and_map_recreate_missing_parent_directories(self):
        bot.marcar_usado('SYNTHETIC', 'first@example.test', 'SYNTHETIC', 'synthetic')
        self.assertEqual(bot.correos_usados(), {'first@example.test'})
        shutil.rmtree(self.data)
        bot.guardar_mapa({'SYNTHETIC': '3'})
        self.assertEqual(bot.leer_mapa(), {'SYNTHETIC': '3'})
        shutil.rmtree(self.data)
        bot.marcar_usado('SYNTHETIC', 'second@example.test', 'SYNTHETIC', 'synthetic')
        with bot.USADOS.open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([row['correo'] for row in rows], ['second@example.test'])

    def test_capture_creates_all_missing_persistent_parent_directories(self):
        app = bot.App.__new__(bot.App)
        with patch.object(bot, 'adb', return_value='') as adb:
            image = app.foto('synthetic-console', '1', 'synthetic.png')
        self.assertEqual(image, self.data / 'capturas' / 'synthetic.png')
        self.assertTrue(image.parent.is_dir())
        self.assertEqual(adb.call_args.args[-1], str(image))

    def test_deleted_zip_extraction_directory_does_not_break_csv_or_map(self):
        extracted = self.base / 'temporary-zip-extraction'
        extracted.mkdir()
        script = extracted / SOURCE.name
        script.write_bytes(SOURCE.read_bytes())
        local = self.base / 'durable-profile'
        with patch.object(sys, 'platform', 'win32'), \
                patch.dict(os.environ, {'LOCALAPPDATA': str(local)}, clear=True):
            loaded = load_application(script, 'gestoria_deleted_zip_tests')
        shutil.rmtree(extracted)
        self.assertFalse(script.parent.exists())
        self.assertEqual(loaded.CARPETA, local / 'GestoriaDiaz')
        loaded.marcar_usado('SYNTHETIC', 'first@example.test', 'SYNTHETIC', 'synthetic')
        loaded.guardar_mapa({'SYNTHETIC': '4'})
        self.assertEqual(loaded.correos_usados(), {'first@example.test'})
        self.assertEqual(loaded.leer_mapa(), {'SYNTHETIC': '4'})
        self.assertTrue((local / 'GestoriaDiaz' / 'correos_usados.csv').is_file())
        self.assertFalse(extracted.exists(), 'Writing data must not recreate the ZIP temporary folder')


class PendingEmailPersistenceTests(unittest.TestCase):
    def test_failed_write_keeps_email_reserved_and_retry_persists_it_once(self):
        app = storage_application()
        with patch.object(bot, 'marcar_usado', side_effect=[FileNotFoundError('synthetic missing directory'), None]) as write, \
                patch.object(bot, 'correos_usados', return_value=set()):
            app.registrar_correo('SYNTHETIC', 'first@example.test', 'SYNTHETIC', 'synthetic')
            self.assertIn('first@example.test', app.usados_sesion)
            self.assertEqual(app.disponibles(), ['second@example.test'])
            self.assertTrue(app.emit.called, 'Failed persistence should be reported without aborting the flow')
            app.guardar_correos_pendientes()
            app.guardar_correos_pendientes()
        self.assertEqual(write.call_count, 2, 'A persisted pending record must not be written again')
        write.assert_called_with('SYNTHETIC', 'first@example.test', 'SYNTHETIC', 'synthetic')

    def test_email_is_reserved_before_attempting_disk_write(self):
        app = storage_application()

        def unavailable(*args):
            self.assertIn('first@example.test', app.usados_sesion)
            raise PermissionError('synthetic profile unavailable')

        with patch.object(bot, 'marcar_usado', side_effect=unavailable), \
                patch.object(bot, 'correos_usados', return_value=set()):
            app.registrar_correo('SYNTHETIC', 'first@example.test', 'SYNTHETIC', 'synthetic')
            self.assertEqual(app.disponibles(), ['second@example.test'])

    def test_storage_error_does_not_abort_before_identity_pin_or_email_code(self):
        app = storage_application()
        app.events = queue.Queue()
        app.refrescar_correos = Mock()
        app.btn_codigo = Mock()
        app.btn_consulta = Mock()
        app.pendiente = None
        app.foto = Mock(return_value=Path('synthetic.png'))
        login = [node(rid='example:id/txtCURP', kind='android.widget.EditText'),
                 node(rid='example:id/txtCorreo', kind='android.widget.EditText'),
                 node('Iniciar sesión', rid='example:id/btnIniciar')]
        identity = [node('Validación de identidad'),
                    node(rid='android:id/password_entry', kind='android.widget.EditText')]
        pages = iter([login, login, identity, [node('Código de validación')]])
        with patch.object(bot, 'listar', return_value={'SYNTHETIC': {'index': '2', 'android': True}}), \
                patch.object(bot, 'adb', return_value='OK'), \
                patch.object(bot, 'abrir_app'), patch.object(bot, 'escribir'), \
                patch.object(bot, 'tocar'), \
                patch.object(bot, 'marcar_usado', side_effect=FileNotFoundError('synthetic missing directory')), \
                patch.object(bot, 'PIN_EMULADOR', '8706'), \
                patch.object(bot.time, 'sleep'), \
                patch.object(bot, 'pantalla', side_effect=lambda *args: next(pages)), \
                patch.object(bot, 'enviar_pin_identidad', return_value=True) as send:
            app._consulta('synthetic-console', 'SYNTHETIC', 'first@example.test', 'SYNTHETIC', 'synthetic')
        send.assert_called_once()
        self.assertIsNotNone(app.pendiente)
        self.assertIn('first@example.test', app.usados_sesion)
        self.assertTrue(any('Esperando código' in call.args[0] for call in app.emit.call_args_list))
        self.assertFalse(any('ERROR en consulta' in call.args[0] for call in app.emit.call_args_list))


if __name__ == '__main__':
    unittest.main()
