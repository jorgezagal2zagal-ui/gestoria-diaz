import os
import time
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
import enlace_integrado as link
from lector_integrado import validate_message, mailbox_identity_verified, _sender, _received, scan_visible_inbox
import navegador_v28 as nav

EMAIL = 'autorizada@example.invalid'
SENDER = 'notificaciones@example.invalid'
SERIAL = 'emulator-5554'
FOLIO = 'a' * 32


class LinkTests(unittest.TestCase):
    def setUp(self):self.state = link.State()
    def start(self):return self.state.start(EMAIL, FOLIO, SERIAL)

    def test_no_code_before_imss_waits(self):
        self.assertEqual(self.start()['status'], 'PREPARANDO_IMSS')
        with self.assertRaises(ValueError):self.state.put_code(FOLIO, '001234', EMAIL)

    def test_code_and_finish_need_correct_order(self):
        self.start();self.state.requesting(FOLIO);self.state.waiting(FOLIO)
        with self.assertRaises(ValueError):self.state.imss_done(FOLIO)
        self.state.put_code(FOLIO, '001234', EMAIL)
        with self.assertRaises(ValueError):self.state.imss_done(FOLIO)
        self.state.acknowledge(FOLIO);self.state.imss_done(FOLIO)
        result = self.state.status(FOLIO)
        self.assertEqual(result['status'], 'CODIGO_CONFIRMADO_FIN');self.assertIsNone(result['code'])

    def test_wrong_folio_email_and_serial_rejected(self):
        self.start();self.state.requesting(FOLIO);self.state.waiting(FOLIO)
        for folio, email in [('b'*32, EMAIL), (FOLIO, 'otra@example.invalid')]:
            with self.assertRaises(ValueError):self.state.put_code(folio, '001234', email)
        with self.assertRaises(ValueError):self.state.start(EMAIL, FOLIO, 'emulator-5556')

    def test_physical_and_wifi_serial_rejected(self):
        for serial in ('HONOR', '192.168.0.1:5555', None):
            with self.assertRaises(ValueError):self.state.start(EMAIL, FOLIO, serial)

    def test_first_code_cannot_be_replaced(self):
        self.start();self.state.requesting(FOLIO);self.state.waiting(FOLIO);self.state.put_code(FOLIO, '001234', EMAIL)
        self.state.put_code(FOLIO, '001234', EMAIL)
        with self.assertRaises(ValueError):self.state.put_code(FOLIO, '654321', EMAIL)

    def test_expiry_purges_code(self):
        self.start();self.state.requesting(FOLIO);self.state.waiting(FOLIO);self.state.put_code(FOLIO, '001234', EMAIL)
        self.state.job['created'] -= 901
        state = self.state.status(FOLIO)
        self.assertEqual(state['status'], 'CADUCADA');self.assertIsNone(state['code'])

    def test_replay_and_cancel_after_finish_rejected(self):
        self.start();self.state.requesting(FOLIO);self.state.waiting(FOLIO);self.state.put_code(FOLIO, '001234', EMAIL)
        self.state.acknowledge(FOLIO);self.state.imss_done(FOLIO)
        with self.assertRaises(ValueError):self.state.put_code(FOLIO, '001234', EMAIL)
        with self.assertRaises(ValueError):self.state.cancel(FOLIO)

    def test_cancel_purges_pending_code(self):
        self.start();self.state.requesting(FOLIO);self.state.waiting(FOLIO);self.state.put_code(FOLIO, '001234', EMAIL)
        self.state.cancel(FOLIO)
        self.assertIsNone(self.state.status(FOLIO)['code'])

    def test_new_job_never_replaces_live_job(self):
        self.start()
        with self.assertRaises(ValueError):self.state.start(EMAIL, 'b'*32, SERIAL)

    def test_repeated_registration_is_not_fresh(self):
        self.assertTrue(self.start()['new_request'])
        self.assertNotIn('new_request', self.start())

    def test_secure_protocol_is_identical_in_both_components(self):
        from pathlib import Path
        folder = Path(__file__).resolve().parent
        self.assertEqual((folder/'enlace_integrado.py').read_bytes(), (folder.parent/'IMSS'/'enlace_integrado.py').read_bytes())

    def test_ack_without_code_rejected(self):
        self.start()
        with self.assertRaises(ValueError):self.state.acknowledge(FOLIO)

    def test_http_authentication_origin_and_ready(self):
        server = link.Server(self.state, port=0, mailbox_ready=lambda:dict(ready=True, email=EMAIL, phase='mail'),
                             can_begin=lambda email, folio, serial:email == EMAIL and folio == FOLIO)
        server.start()
        try:
            port = server.server.server_address[1]
            client = link.Client(port=port)
            self.assertEqual(client.ready()['protocol'], 2)
            self.assertTrue(client.ready()['ready'])
            client.begin(EMAIL, FOLIO, SERIAL);client.requesting(FOLIO);client.waiting(FOLIO)
            client.call('/v1/codigo', dict(id=FOLIO, email=EMAIL, code='001234'))
            self.assertEqual(client.status(FOLIO)['code'], '001234')
            for headers in ({}, {'X-GD-Link-Key':link.shared_key(), 'Origin':'https://example.invalid'}):
                request = Request('http://127.0.0.1:'+str(port)+'/v2/listo', headers=headers)
                with self.assertRaises(HTTPError) as error:build_opener(ProxyHandler({})).open(request)
                self.assertEqual(error.exception.code, 401)
            with self.assertRaises(link.LinkError):client.begin(EMAIL, 'b'*32, SERIAL)
        finally:server.close()


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.start = (self.now-timedelta(seconds=10)).isoformat()
        self.received = (self.now-timedelta(seconds=2)).isoformat()
        self.body = 'Código de verificación IMSS. Tu código de verificación es: 001234'

    def check(self, **kwargs):
        data = dict(sender=SENDER, received=self.received, subject='Código de verificación',
                    body=self.body, expected_sender=SENDER, started=self.start, now=self.now)
        data.update(kwargs)
        return validate_message(**data)

    def test_recent_message_preserves_zero(self):self.assertEqual(self.check(), '001234')
    def test_wrong_sender_rejected(self):self.assertIsNone(self.check(sender='otro@example.invalid'))
    def test_substring_sender_rejected(self):self.assertIsNone(self.check(sender='x'+SENDER))
    def test_missing_date_rejected(self):self.assertIsNone(self.check(received=None))
    def test_date_without_timezone_rejected(self):self.assertIsNone(self.check(received='2026-10-24T12:00:00'))
    def test_old_message_rejected(self):self.assertIsNone(self.check(received=(self.now-timedelta(seconds=11)).isoformat()))
    def test_future_message_rejected(self):self.assertIsNone(self.check(received=(self.now+timedelta(minutes=2)).isoformat()))
    def test_expired_request_rejected(self):self.assertIsNone(self.check(started=(self.now-timedelta(minutes=16)).isoformat()))
    def test_ambiguous_codes_rejected(self):self.assertIsNone(self.check(body=self.body+' Otro código 654321'))
    def test_microsoft_login_mail_rejected(self):self.assertIsNone(self.check(subject='Código de inicio de sesión Microsoft'))

    def test_account_identity_must_come_from_profile_control(self):
        item = Mock();item.is_visible.return_value = True
        item.get_attribute.side_effect = lambda attr:EMAIL if attr == 'aria-label' else None
        loc = Mock();loc.count.return_value = 1;loc.nth.return_value = item
        page = SimpleNamespace(url='https://outlook.live.com/mail/0/inbox', locator=lambda css:loc)
        self.assertTrue(mailbox_identity_verified(page, EMAIL))
        self.assertFalse(mailbox_identity_verified(page, 'otra@example.invalid'))

    def test_login_url_never_counts_as_mailbox(self):
        self.assertFalse(mailbox_identity_verified(SimpleNamespace(url='https://login.live.com/'), EMAIL))

    def test_reader_refuses_undated_open_message(self):
        page = SimpleNamespace(url='https://outlook.live.com/mail/0/inbox', wait_for_timeout=Mock())
        row = Mock();pane = Mock();pane.inner_text.return_value = self.body
        with patch('lector_integrado._candidate_rows', return_value=[('m1', row, 'Código de verificación')]), \
             patch('lector_integrado._containers', return_value=[pane]), \
             patch('lector_integrado._sender', return_value=SENDER), patch('lector_integrado._received', return_value=None):
            self.assertIsNone(scan_visible_inbox(page, SENDER, self.start, set()))

    def test_reader_uses_scoped_metadata_and_blocks_replay(self):
        page = SimpleNamespace(url='https://outlook.live.com/mail/0/inbox', wait_for_timeout=Mock())
        row = Mock();pane = Mock();pane.inner_text.return_value = self.body
        ignored = set()
        with patch('lector_integrado._candidate_rows', return_value=[('m1', row, 'Código de verificación')]), \
             patch('lector_integrado._containers', return_value=[pane]), \
             patch('lector_integrado._sender', return_value=SENDER), patch('lector_integrado._received', return_value=self.received):
            self.assertEqual(scan_visible_inbox(page, SENDER, self.start, ignored), '001234')
            self.assertIsNone(scan_visible_inbox(page, SENDER, self.start, ignored))
        self.assertEqual(row.click.call_count, 1)


class SecurityPauseTests(unittest.TestCase):
    def test_logs_redact_otp_and_named_password(self):
        from diagnostico_v36 import record, path
        record(1, 'contraseña=secreto_sintetico código: 001234')
        result = path(1).read_text()
        self.assertNotIn('secreto_sintetico', result);self.assertNotIn('001234', result)

    def test_existing_passkey_authentication_pauses_and_disarms_optional_guard(self):
        browser = nav.BrowserLogin(Mock());browser._optional_prompt_guard = Mock()
        page = SimpleNamespace(url='https://account.microsoft.com/fido/authenticate', locator=Mock())
        page.locator.return_value.inner_text.return_value = 'Use your passkey'
        with patch.object(nav, 'is_microsoft_rate_limited', return_value=False), \
             patch.object(nav, 'is_microsoft_account_blocked', return_value=False):
            self.assertTrue(browser._manual_security_wait(page))
        browser._optional_prompt_guard.disarm_passkey.assert_called_once()

    def test_challenge_pause_is_sticky_until_real_inbox(self):
        browser = nav.BrowserLogin(Mock())
        page = SimpleNamespace(url='https://login.live.com/verify', locator=Mock())
        page.locator.return_value.inner_text.return_value = 'Verifica tu identidad'
        with patch.object(nav, 'is_microsoft_rate_limited', return_value=False), \
             patch.object(nav, 'is_microsoft_account_blocked', return_value=False), \
             patch.object(nav, 'is_additional_verification_required', return_value=True):
            self.assertTrue(browser._manual_security_wait(page))
        self.assertEqual(browser.phase, 'security_manual');self.assertFalse(browser.stop_event.is_set())
        page.url = 'https://login.live.com/password'
        page.locator.return_value.inner_text.return_value = 'Contraseña'
        with patch.object(nav, 'is_microsoft_rate_limited', return_value=False), \
             patch.object(nav, 'is_microsoft_account_blocked', return_value=False), \
             patch.object(nav, 'is_additional_verification_required', return_value=False), \
             patch.object(nav, 'is_mandatory_recovery_email_interrupt', return_value=False), \
             patch.object(nav, 'inbox_ui_verified', return_value=False):
            self.assertTrue(browser._manual_security_wait(page))
        page.url = 'https://outlook.live.com/mail/0/inbox'
        with patch.object(nav, 'is_microsoft_rate_limited', return_value=False), \
             patch.object(nav, 'is_microsoft_account_blocked', return_value=False), \
             patch.object(nav, 'inbox_ui_verified', return_value=True):
            self.assertFalse(browser._manual_security_wait(page))
        self.assertFalse(browser.manual_security_pending)

    def test_optional_passkey_creation_is_not_mfa_bypass(self):
        browser = nav.BrowserLogin(Mock())
        page = SimpleNamespace(url='https://account.microsoft.com/fido/create', locator=Mock())
        with patch.object(nav, 'is_microsoft_rate_limited', return_value=False), \
             patch.object(nav, 'is_microsoft_account_blocked', return_value=False):
            self.assertFalse(browser._manual_security_wait(page))


if __name__ == '__main__':unittest.main()
