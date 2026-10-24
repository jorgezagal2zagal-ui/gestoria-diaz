"""Contraseña común: persistencia, prioridad y arranque con datos ficticios."""
import json
from contextlib import closing
import secrets
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app
from app import App
from credenciales import Vault


class FakeProtector:
    """Sustituto de DPAPI para Linux; no representa cifrado Windows real."""
    def __init__(self):
        self.values = {}

    def protect(self, value):
        token = secrets.token_bytes(32)
        self.values[token] = value
        return token

    def unprotect(self, token):
        return self.values[token]


class CommonPassword(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'vault.sqlite3'
        self.protector = FakeProtector()
        self.vault = Vault(self.protector, self.path)

    def test_existing_accounts_all_use_common_password(self):
        self.vault.save([('one@example.invalid', 'synthetic-one'),
                         ('two@example.invalid', 'synthetic-two'),
                         ('three@example.invalid', None)])
        self.vault.set_common_password('synthetic-shared')
        for email in ('one@example.invalid', 'two@example.invalid', 'three@example.invalid'):
            self.assertEqual(self.vault.password(email), 'synthetic-shared')
            self.assertTrue(self.vault.has_password(email))

    def test_future_imports_use_common_even_if_txt_contains_another_password(self):
        self.vault.set_common_password('synthetic-shared')
        self.vault.save([('future@example.invalid', None),
                         ('specific@example.invalid', 'synthetic-other')])
        self.assertEqual(self.vault.password('future@example.invalid'), 'synthetic-shared')
        self.assertEqual(self.vault.password('specific@example.invalid'), 'synthetic-shared')

    def test_manual_email_without_import_uses_common(self):
        self.vault.set_common_password('synthetic-shared')
        self.assertEqual(self.vault.password(' NEW@example.invalid '), 'synthetic-shared')
        self.assertTrue(self.vault.has_password('new@example.invalid'))

    def test_reopening_vault_preserves_common_setting(self):
        self.vault.set_common_password('synthetic-shared')
        reopened = Vault(self.protector, self.path)
        self.assertTrue(reopened.has_common_password())
        self.assertEqual(reopened.password('one@example.invalid'), 'synthetic-shared')

    def test_changing_common_applies_to_all(self):
        self.vault.set_common_password('synthetic-first')
        self.vault.set_common_password('synthetic-second')
        self.assertEqual(self.vault.password('one@example.invalid'), 'synthetic-second')
        self.assertEqual(self.vault.password('two@example.invalid'), 'synthetic-second')

    def test_sqlite_contains_protector_output_and_not_plaintext(self):
        password = 'synthetic-shared-secret-for-storage-test'
        self.vault.set_common_password(password)
        with closing(sqlite3.connect(self.path)) as db, db:
            blob = db.execute('SELECT secreto FROM preferencias_cifradas').fetchone()[0]
        self.assertIsInstance(blob, bytes)
        self.assertIn(blob, self.protector.values)
        self.assertNotIn(password.encode(), self.path.read_bytes())

    def test_forgetting_common_restores_individual_passwords(self):
        self.vault.save([('one@example.invalid', 'synthetic-original')])
        self.vault.set_common_password('synthetic-shared')
        self.vault.clear_common_password()
        self.assertFalse(self.vault.has_common_password())
        self.assertEqual(self.vault.password('one@example.invalid'), 'synthetic-original')
        self.assertIsNone(self.vault.password('two@example.invalid'))
        self.assertFalse(self.vault.has_password('two@example.invalid'))

    def test_invalid_input_preserves_previous_setting(self):
        self.vault.set_common_password('synthetic-original')
        for value in ('', 'x'*1025, None):
            with self.subTest(length=len(value) if isinstance(value, str) else None):
                with self.assertRaises(ValueError):
                    self.vault.set_common_password(value)
                self.assertEqual(self.vault.password('one@example.invalid'), 'synthetic-original')

    def test_protector_failure_preserves_previous_setting(self):
        self.vault.set_common_password('synthetic-original')
        with patch.object(self.protector, 'protect', side_effect=OSError('synthetic-error')):
            with self.assertRaises(OSError):
                self.vault.set_common_password('synthetic-new')
        self.assertEqual(self.vault.password('one@example.invalid'), 'synthetic-original')

    def test_invalid_email_does_not_receive_common(self):
        self.vault.set_common_password('synthetic-shared')
        self.assertIsNone(self.vault.password('not-an-email'))
        self.assertFalse(self.vault.has_password('not-an-email'))

    def test_existing_database_migrates_without_losing_individual_data(self):
        legacy_path = Path(self.temp.name)/'legacy.sqlite3'
        blob = self.protector.protect('synthetic-original')
        with closing(sqlite3.connect(legacy_path)) as db, db:
            db.execute('CREATE TABLE credenciales (email TEXT PRIMARY KEY, secreto BLOB, actualizado TEXT)')
            db.execute('INSERT INTO credenciales(email,secreto) VALUES (?,?)', ('one@example.invalid', blob))
        migrated = Vault(self.protector, legacy_path)
        self.assertFalse(migrated.has_common_password())
        self.assertEqual(migrated.password('one@example.invalid'), 'synthetic-original')


def variable(value=''):
    result = Mock()
    result.get.return_value = value
    return result


class CommonPasswordUI(unittest.TestCase):
    setUp = CommonPassword.setUp

    def fake(self):
        fake = SimpleNamespace(_vault=lambda: self.vault,
            email=variable('one@example.invalid'), password=variable('synthetic-shared'),
            save_pw=variable(False), common_password_status=variable(), info=variable(),
            sender=variable(), client_id=variable(), auto_queue=variable(False),
            _guard_new_login=Mock(return_value=True), _start_browser=Mock(return_value=True))
        fake._update_common_password_status = lambda: App._update_common_password_status(fake)
        return fake

    def test_save_button_applies_common_and_clears_visible_field(self):
        fake = self.fake()
        App.save_password_for_all(fake)
        self.assertEqual(self.vault.password('two@example.invalid'), 'synthetic-shared')
        fake.password.set.assert_called_once_with('')
        fake.save_pw.set.assert_called_once_with(False)
        self.assertIn('todos los correos', fake.common_password_status.set.call_args.args[0])
        self.assertNotIn('synthetic-shared', fake.info.set.call_args.args[0])

    def test_manual_start_uses_saved_common_and_never_puts_it_in_settings(self):
        self.vault.set_common_password('synthetic-saved')
        fake = self.fake()
        with patch.object(app, 'save_settings') as save:
            App.open_incognito(fake)
        fake._start_browser.assert_called_once_with('one@example.invalid', 'synthetic-saved')
        self.assertNotIn('synthetic-saved', json.dumps(save.call_args.args[0]))
        self.assertNotIn('synthetic-shared', json.dumps(save.call_args.args[0]))

    def test_automatic_start_uses_common_for_selected_request(self):
        self.vault.set_common_password('synthetic-saved')
        fake = self.fake()
        fake.auto_queue = variable(True)
        fake._auto_started_request = None
        fake.browser = SimpleNamespace(running=False, rate_limited=False)
        fake.cooldown = SimpleNamespace(remaining=lambda: 0)
        fake.queue = SimpleNamespace(is_selected_new=lambda email: email=='one@example.invalid')
        App._maybe_start_request_account(fake, {'status':'ESPERANDO_CODIGO',
                                               'request_id':'synthetic-request', 'email':'one@example.invalid'})
        fake._start_browser.assert_called_once_with('one@example.invalid', 'synthetic-saved')
        self.assertEqual(fake._auto_started_request, 'synthetic-request')

    def test_save_failure_does_not_display_password_or_mark_success(self):
        fake = self.fake()
        with patch.object(self.protector, 'protect', side_effect=OSError('synthetic-shared')), \
             patch.object(app.messagebox, 'showerror') as error:
            App.save_password_for_all(fake)
        self.assertFalse(self.vault.has_common_password())
        fake.password.set.assert_not_called()
        fake.info.set.assert_not_called()
        self.assertNotIn('synthetic-shared', str(error.call_args))

    def test_no_common_keeps_individual_login_behavior(self):
        self.vault.save([('one@example.invalid', 'synthetic-individual')])
        fake = self.fake()
        fake.password.get.return_value = ''
        with patch.object(app, 'save_settings'):
            App.open_incognito(fake)
        fake._start_browser.assert_called_once_with('one@example.invalid', 'synthetic-individual')

    def test_forget_button_clears_common(self):
        self.vault.set_common_password('synthetic-saved')
        fake = self.fake()
        App.forget_common_password(fake)
        self.assertFalse(self.vault.has_common_password())
        fake.password.set.assert_called_once_with('')


if __name__ == '__main__':
    unittest.main(verbosity=2)
